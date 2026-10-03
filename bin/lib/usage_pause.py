"""Forced-command template and read path for the /usage read (ADR-1944, S1 part).

Library behind bin/hos-usage-poll: the loopback read, the strict JSON envelope
parser, the settings parser, the reading file and the one decision rule
(evaluate_cycle). Python 3, standard library only, 3.9-compatible syntax.

The poller's only decision-path output is the reading file, overwritten
atomically. Settings are parsed, never sourced. No function on the decision path
raises: every failure is a value.

Test-only overrides (named here and in the tests, nowhere else):
HOS_USAGE_PAUSE_CONF (settings path), HOS_USAGE_PROM_PATH (metrics path, a later
slice) and HOS_USAGE_KEY_PATH (loopback key path).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, NoReturn, Optional, Sequence, Tuple

# ── BEGIN SETTINGS DEFAULTS AND BOUNDS (ADR-1944 A2-10; the only place these numbers appear) ──
DEFAULT_SESSION_THRESHOLD = 90
DEFAULT_WEEKLY_THRESHOLD = 90
DEFAULT_WEEKLY_MODEL_THRESHOLD = 90
DEFAULT_FAIL_MODE = "closed"
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_STALENESS_SECONDS = 900
DEFAULT_READ_TIMEOUT_SECONDS = 60
DEFAULT_HISTORY_DAYS = 90
DEFAULT_HISTORY_MAX_MB = 100

THRESHOLD_MIN = 1
THRESHOLD_MAX = 100
POLL_INTERVAL_MIN = 60
POLL_INTERVAL_MAX = 3600
POLL_INTERVAL_STEP = 60
STALENESS_MIN = 1
STALENESS_MAX = 7200
READ_TIMEOUT_MIN = 5
READ_TIMEOUT_MAX = 3600
READ_TIMEOUT_MARGIN = 30
HISTORY_DAYS_MIN = 1
HISTORY_DAYS_MAX = 3650
HISTORY_MAX_MB_MIN = 1
HISTORY_MAX_MB_MAX = 10240

DEFAULTS: Mapping[str, object] = {
    "session_threshold": DEFAULT_SESSION_THRESHOLD,
    "weekly_threshold": DEFAULT_WEEKLY_THRESHOLD,
    "weekly_model_threshold": DEFAULT_WEEKLY_MODEL_THRESHOLD,
    "fail_mode": DEFAULT_FAIL_MODE,
    "poll_interval_seconds": DEFAULT_POLL_INTERVAL_SECONDS,
    "staleness_seconds": DEFAULT_STALENESS_SECONDS,
    "read_timeout_seconds": DEFAULT_READ_TIMEOUT_SECONDS,
    "history_days": DEFAULT_HISTORY_DAYS,
    "history_max_mb": DEFAULT_HISTORY_MAX_MB,
    "claude_bin": None,
}
# ── END SETTINGS DEFAULTS AND BOUNDS ──

SCHEMA_VERSION = 1
READ_FAILURE_REASONS: FrozenSet[str] = frozenset(
    {
        "ssh_failed",
        "timeout",
        "spawn_failed",
        "envelope_invalid",
        "empty_session",
        "missing_session",
        "missing_weekly",
        "unparseable",
        "crashed",
    }
)
UNUSABLE_REASONS: FrozenSet[str] = frozenset(
    {
        "poller_not_installed",
        "reading_missing",
        "reading_truncated",
        "schema_unknown",
        "reading_unreadable",
        "reading_stale",
        "reading_future",
    }
)
GATE_SENTINEL = "# HOS-USAGE-PAUSE-GATE schema=1"
REMOTE_CMD_TEMPLATE = "{claude_bin} -p /usage --output-format json"  # noqa: E501  # ADR-1944 A2-9: forced-command template; executed by sshd, never by HOS (T4.1b)
SSH_OPTIONS: Tuple[str, ...] = (
    "-o",
    "BatchMode=yes",
    "-o",
    "IdentitiesOnly=yes",
    "-o",
    "RequestTTY=no",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ServerAliveInterval=10",
    "-o",
    "ServerAliveCountMax=3",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    "LogLevel=ERROR",
    "-o",
    "ClearAllForwardings=yes",
    "-o",
    "ForwardAgent=no",
    "-o",
    "ForwardX11=no",
    "-o",
    "IdentityAgent=none",
)
KILL_GRACE_SECONDS = 5
STALENESS_KILL_MARGIN = 2 * KILL_GRACE_SECONDS
STDERR_TAIL_CHARS = 190
GROUP_WORLD_WRITE_BITS = 0o022
INPUT_CAP_BYTES = 65536
HISTORY_LINE_CAP_BYTES = 16384
MAX_WINDOWS = 8
STALE_FUTURE_TOLERANCE_SECONDS = 120
CHECK_READ_KEYS: FrozenSet[str] = frozenset(
    {"kind", "run_epoch", "outcome", "reason", "session_pct", "weekly_all_pct"}
)

# Format caps (reading-file framing, section 1.3). Named so no bare number sits in a function body.
RESETS_CAP_CHARS = 100
NAME_CAP_CHARS = 64
VALUE_CAP_CHARS = 200
REASON_CAP_CHARS = 200
UNKNOWN_KEY_CAP_CHARS = 40
MODEL_SLUG_CAP_CHARS = 32
WINDOW_SLUG_CAP_CHARS = 16
SETTINGS_FILE_CAP_BYTES = 65536
SSH_FAILURE_RC = 255
SUBPROCESS_TIMEOUT_SECONDS = 30
EXIT_USAGE = 64
EXIT_FAIL = 1
EXPECTED_KEY_MODE = 0o600
STATE_DIR_MODE = 0o700
FILE_MODE = 0o600
CRON_SCHEDULE_FIELDS = 5

STDOUT_TMP = "poll.stdout.tmp"
STDERR_TMP = "poll.stderr.tmp"
READING_NAME = "reading"
LAST_RAW_NAME = "last-raw"

_INT_RE = re.compile(r"(0|[1-9][0-9]*)", re.ASCII)
_UINT_RE = re.compile(r"[0-9]+", re.ASCII)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_READING_LINE_RE = re.compile(r"[a-z0-9_]+=[^\x00-\x1f\x7f]*")
_SETTINGS_LINE_RE = re.compile(r"([a-z_]+)=(.*)")
_CLAUDE_BIN_RE = re.compile(r"/[A-Za-z0-9._+/-]{1,254}", re.ASCII)
_ANSI_OSC_RE = re.compile("\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)")
_ANSI_CSI_RE = re.compile("\x1b\\[[0-?]*[ -/]*[@-~]")

_SESSION_PCT_RE = re.compile(r"Current session: ([0-9]{1,3})% used", re.ASCII)
_SESSION_RESETS_RE = re.compile(r"Current session: [0-9]{1,3}% used · resets (.*)", re.ASCII)
_WEEKLY_ALL_PCT_RE = re.compile(r"Current week \(all models\): ([0-9]{1,3})% used", re.ASCII)
_WEEKLY_ALL_RESETS_RE = re.compile(
    r"Current week \(all models\): [0-9]{1,3}% used · resets (.*)", re.ASCII
)
_MODEL_RE = re.compile(r"Current week \(([^)]+)\): ([0-9]{1,3})% used(?: · resets (.*))?", re.ASCII)
_MARKER_RE = re.compile(
    r"^You are currently using your subscription to power your Claude Code usage\s*$",
    re.ASCII | re.MULTILINE,
)
_ANY_USED_RE = re.compile(r"[0-9]+% used", re.ASCII)
_EMPTY_USAGE_RE = re.compile(r"Usage:\s+0 input", re.ASCII)
_EMPTY_COST_MARKER = "Total cost:"
_WINDOW_HEADER_RE = re.compile(
    r"^\s*Last (\S+) · ([0-9]{1,12}) requests · ([0-9]{1,12}) sessions\s*$", re.ASCII
)
_HEAVY_RE = re.compile(
    r"^\s*([0-9]{1,3})% of your usage came from subagent-heavy sessions\s*$", re.ASCII
)
_CONTEXT_RE = re.compile(r"^\s*([0-9]{1,3})% of your usage was at >150k context\s*$", re.ASCII)
_LONG_SESSION_RE = re.compile(
    r"^\s*([0-9]{1,3})% of your usage came from sessions active for 8\+ hours\s*$", re.ASCII
)
_TOP_RE = re.compile(r"^\s*Top subagents: (.+?)\s*$", re.ASCII)
_TOP_MORE_RE = re.compile(r"\+([0-9]{1,12}) more", re.ASCII)
_TOP_ITEM_RE = re.compile(r"(\S(?:.*\S)?) ([0-9]{1,3})%", re.ASCII)
_PUB_RE = re.compile(r"(\S+) (\S+)(?: .*)?")
_KEY_TYPE_PREFIXES = ("ssh-", "ecdsa-", "sk-")
_ENV_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


# ───────────────────────────── data types ─────────────────────────────


@dataclass(frozen=True)
class ReadOutcome:
    kind: str  # exited | timeout | spawn_failed
    rc: Optional[int]
    detail: Optional[str]


@dataclass(frozen=True)
class EnvelopeResult:
    ok: bool
    reason: Optional[str]
    result_text: Optional[str]
    cost_usd: Optional[float]
    tokens: Mapping[str, int]
    read_tokens: Optional[int]


@dataclass(frozen=True)
class ModelWeekly:
    name: str
    slug: str
    pct: int
    resets: Optional[str]


@dataclass(frozen=True)
class WindowBreakdown:
    window_label: str
    slug: str
    requests: Optional[int]
    sessions: Optional[int]
    subagent_heavy_pct: Optional[int]
    long_context_pct: Optional[int]
    long_session_pct: Optional[int]
    top_subagents: Optional[Tuple[Tuple[str, int], ...]]
    top_subagents_more: Optional[int]


@dataclass(frozen=True)
class ParseResult:
    ok: bool
    reason: Optional[str]
    session_pct: Optional[int]
    session_resets: Optional[str]
    weekly_all_pct: Optional[int]
    weekly_all_resets: Optional[str]
    models: Tuple[ModelWeekly, ...]
    windows: Tuple[WindowBreakdown, ...]
    subscription_marker: bool


@dataclass(frozen=True)
class SettingsResult:
    values: Mapping[str, object]
    status: str  # valid | defaults | invalid:<key>
    invalid_key: Optional[str]
    invalid_value: Optional[str]


@dataclass(frozen=True)
class ReadingRead:
    state: str  # ok | missing | truncated | schema_unknown | unreadable
    fields: Mapping[str, str]


@dataclass(frozen=True)
class Decision:
    decision: str
    klass: str
    reason: str
    session_pct: Optional[int]
    weekly_all_pct: Optional[int]
    reading_age_s: Optional[int]
    fail_mode: str
    settings: str
    unchecked: bool


@dataclass(frozen=True)
class Classification:
    outcome: str  # success | failure
    reason: Optional[str]
    detail: Optional[str]
    remote_exit: Optional[int]
    envelope: Optional[EnvelopeResult]
    parsed: Optional[ParseResult]


# ───────────────────────────── small helpers ─────────────────────────────


def _cap(text: str, limit: int) -> str:
    return text[:limit]


def _strip_control(text: str) -> str:
    return _CONTROL_RE.sub("", text)


def _flatten(text: str) -> str:
    """Control characters become spaces and whitespace runs collapse (log/detail text)."""
    return " ".join(_CONTROL_RE.sub(" ", text).split())


def ascii_fold(text: str) -> str:
    """Replace every non-ASCII character with '?' (verdict/log/audit text, TD-O-14)."""
    return "".join(ch if ch.isascii() else "?" for ch in text)


def _slug(text: str, cap: int) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:cap]


def _is_uint(value: Optional[str]) -> bool:
    return value is not None and _UINT_RE.fullmatch(value) is not None


def _utc_iso(epoch: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _read_bytes(path: Path, cap: int) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(cap)
    except OSError:
        return b""


def _read_tail(path: Path, cap: int) -> bytes:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - cap))
            return fh.read(cap)
    except OSError:
        return b""


def format_cost(value: float) -> str:
    """Shortest round-trip decimal; a trailing '.0' is dropped, so 0 stays 0."""
    text = repr(float(value))
    if text.endswith(".0"):
        text = text[: -len(".0")]
    return text


def remote_cmd(claude_bin: str) -> str:
    return REMOTE_CMD_TEMPLATE.format(claude_bin=claude_bin)


def decode_result_text(text: str) -> str:
    text = _ANSI_OSC_RE.sub("", text)
    text = _ANSI_CSI_RE.sub("", text)
    return text.replace("\r", "")


# ───────────────────────────── the read ─────────────────────────────


def _create_fresh(path: Path, mode: int) -> int:
    """Create `path` anew: a stale file or symlink there is removed, never followed or reused."""
    try:
        os.unlink(str(path))
    except FileNotFoundError:
        pass
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)
    return fd


def _open_private(path: Path):
    return os.fdopen(_create_fresh(path, FILE_MODE), "wb")


def read_usage(
    *, key_path: Path, timeout_s: int, stdout_path: Path, stderr_path: Path
) -> ReadOutcome:
    """One bounded ssh loopback read. No remote command is sent; sshd runs the forced command."""
    argv = ["ssh", "-n", "-i", str(key_path), *SSH_OPTIONS, "127.0.0.1"]
    try:
        with _open_private(stdout_path) as out_fh, _open_private(stderr_path) as err_fh:
            try:
                proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=out_fh,
                    stderr=err_fh,
                    start_new_session=True,
                )
            except OSError as exc:
                return ReadOutcome("spawn_failed", None, _flatten(str(exc)))
            try:
                rc = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                return ReadOutcome("timeout", None, _kill_group(proc))
    except OSError as exc:
        return ReadOutcome("spawn_failed", None, _flatten(str(exc)))
    # A negative rc is death by signal: it maps to rc=None, and the strict parse of whatever
    # stdout holds still decides success.
    return ReadOutcome("exited", rc if rc >= 0 else None, None)


def _kill_group(proc: "subprocess.Popen[bytes]") -> Optional[str]:
    """TERM then KILL the process group, each wait bounded. Returns a detail when a kill was refused."""
    problem: Optional[str] = None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            problem = "kill %s refused: %s" % (sig.name, _flatten(str(exc)))
        try:
            proc.wait(timeout=KILL_GRACE_SECONDS)
            return problem
        except subprocess.TimeoutExpired:
            continue
    return problem


def classify_transport(outcome: ReadOutcome) -> Optional[str]:
    if outcome.kind == "timeout":
        return "timeout"
    if outcome.kind == "spawn_failed":
        return "spawn_failed"
    if outcome.kind == "exited" and outcome.rc == SSH_FAILURE_RC:
        return "ssh_failed"
    return None


# ───────────────────────────── envelope ─────────────────────────────

_WATCHED_KEYS = frozenset(
    {
        "result",
        "total_cost_usd",
        "usage",
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }
)
_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _pairs_hook(pairs: Sequence[Tuple[str, object]]) -> Dict[str, object]:
    seen = set()
    for key, _value in pairs:
        if key in _WATCHED_KEYS:
            if key in seen:
                raise ValueError("duplicate key " + key)
            seen.add(key)
    return dict(pairs)


def _reject_constant(name: str) -> object:
    raise ValueError("non-finite constant " + name)


def _envelope_invalid() -> EnvelopeResult:
    return EnvelopeResult(False, "envelope_invalid", None, None, {}, None)


def _valid_cost(raw_cost: object) -> Optional[float]:
    """A finite, non-negative number as float; anything else (including overflow) is absent."""
    if not isinstance(raw_cost, (int, float)) or isinstance(raw_cost, bool):
        return None
    try:
        value = float(raw_cost)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def parse_envelope(raw: bytes) -> EnvelopeResult:
    """Strict parse of the --output-format json envelope. Reads six fields and nothing else."""
    try:
        text = raw[:INPUT_CAP_BYTES].decode("utf-8", errors="replace")
        doc = json.loads(text, object_pairs_hook=_pairs_hook, parse_constant=_reject_constant)
        if not isinstance(doc, dict):
            return _envelope_invalid()
        result = doc.get("result")
        if not isinstance(result, str):
            return _envelope_invalid()
        cost = _valid_cost(doc.get("total_cost_usd"))
        tokens: Dict[str, int] = {}
        usage = doc.get("usage")
        if isinstance(usage, dict):
            for key in _TOKEN_KEYS:
                val = usage.get(key)
                if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
                    tokens[key] = val
        read_tokens = sum(tokens.values()) if len(tokens) == len(_TOKEN_KEYS) else None
        return EnvelopeResult(True, None, decode_result_text(result), cost, tokens, read_tokens)
    except (ValueError, RecursionError):  # JSON syntax, duplicate keys, int limits, nesting
        return _envelope_invalid()


# ───────────────────────────── usage text ─────────────────────────────


def _last_match(pattern: "re.Pattern[str]", text: str) -> Optional["re.Match[str]"]:
    matches = list(pattern.finditer(text))
    return matches[-1] if matches else None


def _resets(match: Optional["re.Match[str]"]) -> Optional[str]:
    if match is None:
        return None
    value = _strip_control(match.group(1)).strip()
    return _cap(value, RESETS_CAP_CHARS) or None


def _extract_models(text: str) -> Tuple[ModelWeekly, ...]:
    models: Dict[str, ModelWeekly] = {}
    for match in _MODEL_RE.finditer(text):
        if match.group(1) == "all models":
            continue
        name = _cap(_strip_control(match.group(1)), NAME_CAP_CHARS)
        slug = _slug(name, MODEL_SLUG_CAP_CHARS)
        if not slug:
            continue
        resets = match.group(3)
        models.pop(slug, None)
        models[slug] = ModelWeekly(
            name, slug, int(match.group(2)), _resets(match) if resets is not None else None
        )
    return tuple(models.values())


def _parse_top(body: str) -> Optional[Tuple[Tuple[Tuple[str, int], ...], int]]:
    items = body.split(", ")
    more = 0
    last = _TOP_MORE_RE.fullmatch(items[-1])
    if last is not None:
        more = int(last.group(1))
        items = items[:-1]
    names = []
    out = []
    for item in items:
        item_match = _TOP_ITEM_RE.fullmatch(item)
        if item_match is None:
            return None
        name = _strip_control(item_match.group(1))
        if name in names:
            return None
        names.append(name)
        out.append((name, int(item_match.group(2))))
    if not out:
        return None
    return tuple(out), more


def _parse_window_block(
    label: str, slug: str, requests: int, sessions: int, lines: Sequence[str]
) -> WindowBreakdown:
    def single(pattern: "re.Pattern[str]") -> Optional[int]:
        hits = [m for m in (pattern.match(line) for line in lines) if m is not None]
        return int(hits[0].group(1)) if len(hits) == 1 else None

    tops = [m for m in (_TOP_RE.match(line) for line in lines) if m is not None]
    top = _parse_top(tops[0].group(1)) if len(tops) == 1 else None
    return WindowBreakdown(
        label,
        slug,
        requests,
        sessions,
        single(_HEAVY_RE),
        single(_CONTEXT_RE),
        single(_LONG_SESSION_RE),
        top[0] if top else None,
        top[1] if top else None,
    )


def _extract_windows(text: str) -> Tuple[WindowBreakdown, ...]:
    blocks: List[Tuple[str, str, int, int, List[str]]] = []
    current: Optional[List[str]] = None
    for line in text.split("\n"):
        header = _WINDOW_HEADER_RE.match(line)
        if header is not None:
            current = []
            blocks.append(
                (
                    header.group(1),
                    _slug(header.group(1), WINDOW_SLUG_CAP_CHARS),
                    int(header.group(2)),
                    int(header.group(3)),
                    current,
                )
            )
        elif not line.strip():
            current = None
        elif current is not None:
            current.append(line)
    counts: Dict[str, int] = {}
    for _label, slug, _req, _ses, _lines in blocks:
        counts[slug] = counts.get(slug, 0) + 1
    windows = []
    for label, slug, req, ses, lines in blocks:
        if not slug or counts[slug] != 1:
            continue
        try:
            windows.append(_parse_window_block(label, slug, req, ses, lines))
        except Exception:  # noqa: BLE001 - one window never changes ok/reason
            continue
        if len(windows) == MAX_WINDOWS:
            break
    return tuple(windows)


def _int_group(match: Optional["re.Match[str]"]) -> Optional[int]:
    return int(match.group(1)) if match is not None else None


def parse_usage(text: str) -> ParseResult:
    session = _last_match(_SESSION_PCT_RE, text)
    weekly = _last_match(_WEEKLY_ALL_PCT_RE, text)
    marker = _MARKER_RE.search(text) is not None
    session_pct = _int_group(session)
    weekly_pct = _int_group(weekly)
    session_resets = _resets(_last_match(_SESSION_RESETS_RE, text))
    weekly_resets = _resets(_last_match(_WEEKLY_ALL_RESETS_RE, text))
    if session_pct is not None and weekly_pct is not None:
        try:
            models = _extract_models(text)
        except Exception:  # noqa: BLE001
            models = ()
        try:
            windows = _extract_windows(text)
        except Exception:  # noqa: BLE001
            windows = ()
        return ParseResult(
            True,
            None,
            session_pct,
            session_resets,
            weekly_pct,
            weekly_resets,
            models,
            windows,
            marker,
        )
    if _ANY_USED_RE.search(text) is None and (
        text.strip() == "" or _EMPTY_COST_MARKER in text or _EMPTY_USAGE_RE.search(text)
    ):
        reason = "empty_session"
    elif session_pct is not None:
        reason = "missing_weekly"
    elif weekly_pct is not None:
        reason = "missing_session"
    else:
        reason = "unparseable"
    return ParseResult(
        False, reason, session_pct, session_resets, weekly_pct, weekly_resets, (), (), marker
    )


def classify_read(
    outcome: Optional[ReadOutcome],
    stdout: bytes,
    stderr: bytes,
    transport_reason: Optional[str] = None,
    transport_detail: Optional[str] = None,
) -> Classification:
    """Section 3.4: pre-ssh refusal, transport, envelope, content, in that order."""
    if transport_reason is not None:
        return Classification("failure", transport_reason, transport_detail, None, None, None)
    if outcome is None:
        return Classification("failure", "crashed", "no read outcome", None, None, None)
    remote_exit = outcome.rc if outcome.kind == "exited" else None
    stderr_detail = (
        "stderr:" + _flatten(stderr.decode("utf-8", errors="replace"))[-STDERR_TAIL_CHARS:]
    )
    reason = classify_transport(outcome)
    if reason is not None:
        return Classification(
            "failure", reason, outcome.detail or stderr_detail, remote_exit, None, None
        )
    envelope = parse_envelope(stdout)
    if not envelope.ok:
        return Classification("failure", "envelope_invalid", stderr_detail, remote_exit, None, None)
    parsed = parse_usage(envelope.result_text or "")
    if parsed.ok:
        return Classification("success", None, None, remote_exit, envelope, parsed)
    detail = "result:" + _flatten(envelope.result_text or "")
    return Classification("failure", parsed.reason, detail, remote_exit, envelope, parsed)


# ───────────────────────────── settings ─────────────────────────────


def _defaults_result(
    status: str, key: Optional[str] = None, value: Optional[str] = None
) -> SettingsResult:
    return SettingsResult(dict(DEFAULTS), status, key, value)


def _int_in(value: str, low: int, high: int) -> Optional[int]:
    if _INT_RE.fullmatch(value) is None:
        return None
    number = int(value)
    return number if low <= number <= high else None


def _valid_claude_bin(value: str) -> bool:
    if _CLAUDE_BIN_RE.fullmatch(value) is None or value.endswith("/"):
        return False
    return not any(part in (".", "..") for part in value.split("/"))


def _parse_setting(key: str, value: str) -> Optional[object]:
    if key in ("session_threshold", "weekly_threshold", "weekly_model_threshold"):
        return _int_in(value, THRESHOLD_MIN, THRESHOLD_MAX)
    if key == "fail_mode":
        return value if value in ("closed", "open") else None
    if key == "poll_interval_seconds":
        number = _int_in(value, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX)
        return number if number is not None and number % POLL_INTERVAL_STEP == 0 else None
    if key == "staleness_seconds":
        return _int_in(value, STALENESS_MIN, STALENESS_MAX)
    if key == "read_timeout_seconds":
        return _int_in(value, READ_TIMEOUT_MIN, READ_TIMEOUT_MAX)
    if key == "history_days":
        return _int_in(value, HISTORY_DAYS_MIN, HISTORY_DAYS_MAX)
    if key == "history_max_mb":
        return _int_in(value, HISTORY_MAX_MB_MIN, HISTORY_MAX_MB_MAX)
    if key == "claude_bin":
        return value if _valid_claude_bin(value) else None
    return None


def load_settings(path: Path) -> SettingsResult:
    """Parse (never source) the settings file. Never raises."""
    try:
        try:
            with open(path, "rb") as fh:
                data = fh.read(SETTINGS_FILE_CAP_BYTES + 1)
        except FileNotFoundError:
            return _defaults_result("defaults")
        if len(data) > SETTINGS_FILE_CAP_BYTES:
            return _defaults_result("invalid:file_unreadable", "file_unreadable", "oversize")
        text = data.decode("utf-8")
    except (OSError, ValueError):
        return _defaults_result("invalid:file_unreadable", "file_unreadable", "unreadable")
    try:
        return _parse_settings_text(text)
    except Exception:  # noqa: BLE001 - settings parsing never raises
        return _defaults_result("invalid:file_unreadable", "file_unreadable", "unparseable")


def _parse_settings_text(text: str) -> SettingsResult:
    values: Dict[str, object] = dict(DEFAULTS)
    seen = set()
    for number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = _SETTINGS_LINE_RE.fullmatch(line.rstrip())
        if match is None:
            return _defaults_result(
                "invalid:line_%d" % number, "line_%d" % number, _cap(line, NAME_CAP_CHARS)
            )
        key, value = match.group(1), match.group(2)
        if key not in DEFAULTS:
            short = _cap(re.sub(r"[^a-z0-9_]", "_", key), UNKNOWN_KEY_CAP_CHARS)
            return _defaults_result("invalid:" + short, short, _cap(value, NAME_CAP_CHARS))
        if key in seen:
            return _defaults_result("invalid:" + key, key, "duplicate")
        seen.add(key)
        parsed = _parse_setting(key, value)
        if parsed is None:
            return _defaults_result("invalid:" + key, key, _cap(value, NAME_CAP_CHARS))
        values[key] = parsed
    interval = int(values["poll_interval_seconds"])  # type: ignore[call-overload]
    timeout = int(values["read_timeout_seconds"])  # type: ignore[call-overload]
    staleness = int(values["staleness_seconds"])  # type: ignore[call-overload]
    if timeout > interval - READ_TIMEOUT_MARGIN:
        return _defaults_result(
            "invalid:read_timeout_seconds", "read_timeout_seconds", str(timeout)
        )
    if staleness <= interval + timeout + STALENESS_KILL_MARGIN:
        return _defaults_result("invalid:staleness_seconds", "staleness_seconds", str(staleness))
    return SettingsResult(values, "valid" if seen else "defaults", None, None)


def default_conf_path() -> Path:
    override = os.environ.get("HOS_USAGE_PAUSE_CONF")
    if override:
        return Path(override)
    return Path(_home()) / ".config" / "hos" / "usage-pause.conf"


def _home() -> str:
    return os.environ.get("HOME") or os.path.expanduser("~")


def default_key_path() -> Path:
    override = os.environ.get("HOS_USAGE_KEY_PATH")
    if override:
        return Path(override)
    return Path(_home()) / ".ssh" / "hos_loopback"


def resolve_claude_bin(settings: SettingsResult) -> Optional[str]:
    configured = settings.values.get("claude_bin")
    if isinstance(configured, str):
        return configured
    found = shutil.which("claude")
    if found is None:
        return None
    found = os.path.abspath(found)
    return found if _valid_claude_bin(found) else None


# ───────────────────────────── reading file ─────────────────────────────


def read_reading(path: Path) -> ReadingRead:
    """Section 3.6 read rules. Never raises."""
    try:
        try:
            with open(path, "rb") as fh:
                data = fh.read(INPUT_CAP_BYTES + 1)
        except FileNotFoundError:
            return ReadingRead("missing", {})
        if len(data) > INPUT_CAP_BYTES:
            return ReadingRead("unreadable", {})
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ReadingRead("unreadable", {})
    if not text.endswith("\n"):
        return ReadingRead("truncated", {})
    lines = text[:-1].split("\n")
    if lines[-1] != "end=1":
        return ReadingRead("truncated", {})
    if re.fullmatch(r"schema=[0-9]+", lines[0], re.ASCII) is None:
        return ReadingRead("unreadable", {})
    if lines[0] != "schema=%d" % SCHEMA_VERSION:
        return ReadingRead("schema_unknown", {})
    fields: Dict[str, str] = {}
    for line in lines[1:-1]:
        if _READING_LINE_RE.fullmatch(line) is None:
            return ReadingRead("unreadable", {})
        key, value = line.split("=", 1)
        if key in ("schema", "end") or key in fields:
            return ReadingRead("unreadable", {})
        fields[key] = value
    return ReadingRead("ok", fields)


def _value_cap(key: str) -> int:
    if key.endswith("_resets") or key.endswith("_name"):
        return RESETS_CAP_CHARS
    return VALUE_CAP_CHARS


def render_reading(fields: Sequence[Tuple[str, str]]) -> str:
    """Framing and sanitizing; the schema line comes from the caller, end=1 is appended."""
    out = []
    seen = set()
    for key, value in fields:
        if key in seen or re.fullmatch(r"[a-z0-9_]+", key) is None:
            continue
        clean = _cap(_CONTROL_RE.sub(" ", value).strip(), _value_cap(key)).strip()
        if not clean:
            continue
        seen.add(key)
        out.append("%s=%s\n" % (key, clean))
    out.append("end=1\n")
    return "".join(out)


def write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Section 1.5: render in memory, write <file>.tmp, fsync, rename, best-effort dir fsync.

    On any failure the tmp file is removed, so no *.tmp survives a failed write.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = _create_fresh(tmp, mode)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


# ───────────────────────────── decision ─────────────────────────────


def _unusable(
    settings: SettingsResult,
    reason: str,
    klass: str,
    session: Optional[int],
    weekly: Optional[int],
    age: Optional[int],
) -> Decision:
    fail_mode = str(settings.values["fail_mode"])
    if fail_mode == "open":
        return Decision(
            "run", "failopen", reason, session, weekly, age, fail_mode, settings.status, True
        )
    return Decision("pause", klass, reason, session, weekly, age, fail_mode, settings.status, False)


def _model_entries(fields: Mapping[str, str]) -> Optional[List[Tuple[str, int]]]:
    """(name, pct) for every model, or None when the model keys are inconsistent."""
    out = []
    for key, value in fields.items():
        match = re.fullmatch(r"weekly_model_(.+)_pct", key)
        if match is None:
            continue
        name = fields.get("weekly_model_%s_name" % match.group(1))
        if name is None or not _is_uint(value):
            return None
        out.append((name, int(value)))
    return sorted(out)


def evaluate_cycle(
    reading: ReadingRead,
    settings: SettingsResult,
    now: float,
    *,
    poller_artifacts_present: bool,
) -> Decision:
    """The only decision rule (section 3.6, R1-R13). Pure; never raises."""
    try:
        return _evaluate(reading, settings, now, poller_artifacts_present)
    except Exception:  # noqa: BLE001 - a rule failure must still be a value
        return Decision(
            "pause",
            "reading_unusable",
            "reading_unreadable",
            None,
            None,
            None,
            str(DEFAULTS["fail_mode"]),
            settings.status,
            False,
        )


def _evaluate(
    reading: ReadingRead, settings: SettingsResult, now: float, artifacts: bool
) -> Decision:
    fail_mode = str(settings.values["fail_mode"])
    if settings.status.startswith("invalid:"):
        return Decision(
            "pause",
            "settings_invalid",
            "settings_invalid:" + settings.status[len("invalid:") :],
            None,
            None,
            None,
            fail_mode,
            settings.status,
            False,
        )
    if reading.state == "missing":
        reason = "reading_missing" if artifacts else "poller_not_installed"
        return _unusable(settings, reason, "reading_unusable", None, None, None)
    if reading.state != "ok":
        reason = {
            "truncated": "reading_truncated",
            "schema_unknown": "schema_unknown",
        }.get(reading.state, "reading_unreadable")
        return _unusable(settings, reason, "reading_unusable", None, None, None)
    fields = reading.fields
    run_epoch = fields.get("run_epoch")
    outcome = fields.get("outcome")
    if (
        fields.get("kind") != "reading"
        or not _is_uint(run_epoch)
        or outcome
        not in (
            "success",
            "failure",
            "crashed",
        )
    ):
        return _unusable(settings, "reading_unreadable", "reading_unusable", None, None, None)
    age = int(now - int(run_epoch or "0"))
    session = int(fields["session_pct"]) if _is_uint(fields.get("session_pct")) else None
    weekly = int(fields["weekly_all_pct"]) if _is_uint(fields.get("weekly_all_pct")) else None
    if age < -STALE_FUTURE_TOLERANCE_SECONDS:
        return _unusable(settings, "reading_future", "reading_unusable", session, weekly, age)
    if age > int(str(settings.values["staleness_seconds"])):
        return _unusable(settings, "reading_stale", "reading_unusable", session, weekly, age)
    if outcome != "success":
        reason = fields.get("reason", "")
        token = reason if reason in READ_FAILURE_REASONS else "unknown"
        return _unusable(settings, "read_failed:" + token, "read_failed", session, weekly, age)
    models = _model_entries(fields)
    if session is None or weekly is None or models is None:
        return _unusable(settings, "reading_unreadable", "reading_unusable", session, weekly, age)
    limits = (
        ("session", session, int(str(settings.values["session_threshold"]))),
        ("weekly_all", weekly, int(str(settings.values["weekly_threshold"]))),
    ) + tuple(
        ("weekly_model:" + name, pct, int(str(settings.values["weekly_model_threshold"])))
        for name, pct in models
    )
    over = ["%s %d%% >= %d" % item for item in limits if item[1] >= item[2]]
    if over:
        reason = _cap("; ".join(over), REASON_CAP_CHARS)
        return Decision(
            "pause", "limit", reason, session, weekly, age, fail_mode, settings.status, False
        )
    summary = ", ".join("%s %d%% < %d" % item for item in limits)
    reason = _cap("%s (reading age %ds)" % (summary, max(age, 0)), REASON_CAP_CHARS)
    return Decision("run", "ok", reason, session, weekly, age, fail_mode, settings.status, False)


# ───────────────────────────── building the reading ─────────────────────────────


def _bounded_top(items: Tuple[Tuple[str, int], ...]) -> Optional[Tuple[str, int]]:
    """The joined list within the value cap and the number of trailing items dropped."""
    parts: List[str] = []
    for name, pct in items:
        candidate = ",".join(parts + ["%s=%d" % (name, pct)])
        if len(candidate) > VALUE_CAP_CHARS:
            break
        parts.append("%s=%d" % (name, pct))
    return (",".join(parts), len(items) - len(parts)) if parts else None


def build_reading(
    *,
    run_epoch: int,
    classification: Classification,
    diagnostics: Optional[str],
    previous: Optional[ReadingRead],
    settings: SettingsResult,
) -> List[Tuple[str, str]]:
    """Section 1.3 key order, including the poller's informational view (section 3.7 P7)."""
    cls = classification
    success = cls.outcome == "success"
    outcome = "success" if success else ("crashed" if cls.reason == "crashed" else "failure")
    out: List[Tuple[str, str]] = [
        ("schema", str(SCHEMA_VERSION)),
        ("kind", "reading"),
        ("run_at", _utc_iso(run_epoch)),
        ("run_epoch", str(run_epoch)),
        ("outcome", outcome),
    ]
    if not success:
        out.append(("reason", cls.reason or "crashed"))
        out.append(("detail", cls.detail or ""))
    if diagnostics:
        out.append(("diagnostics", diagnostics))
    if cls.remote_exit is not None:
        out.append(("remote_exit", str(cls.remote_exit)))
    parsed = cls.parsed
    if success:
        out.append(("parsed_via", "grep"))
    if parsed is not None:
        out.append(("subscription_marker", "present" if parsed.subscription_marker else "absent"))
    if success and parsed is not None:
        out.extend(_success_fields(parsed))
    envelope = cls.envelope
    if envelope is not None:
        if envelope.cost_usd is not None:
            out.append(("cost_usd", format_cost(envelope.cost_usd)))
        for key in _TOKEN_KEYS:
            if key in envelope.tokens:
                out.append((key, str(envelope.tokens[key])))
        if envelope.read_tokens is not None:
            out.append(("read_tokens", str(envelope.read_tokens)))
    prev_fields = previous.fields if previous is not None and previous.state == "ok" else {}
    prev_failures = prev_fields.get("consecutive_failures")
    if success:
        failures = 0
    else:
        failures = int(prev_failures) + 1 if prev_failures and _is_uint(prev_failures) else 1
    out.append(("consecutive_failures", str(failures)))
    if success:
        out.append(("last_success_epoch", str(run_epoch)))
    elif _is_uint(prev_fields.get("last_success_epoch")):
        out.append(("last_success_epoch", prev_fields["last_success_epoch"]))
    out.extend(_poll_view(out, settings, run_epoch))
    return out


def _success_fields(parsed: ParseResult) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    out.append(("session_pct", str(parsed.session_pct)))
    out.append(("session_resets", parsed.session_resets or ""))
    out.append(("weekly_all_pct", str(parsed.weekly_all_pct)))
    out.append(("weekly_all_resets", parsed.weekly_all_resets or ""))
    for model in parsed.models:
        prefix = "weekly_model_" + model.slug
        out.append((prefix + "_name", model.name))
        out.append((prefix + "_pct", str(model.pct)))
        out.append((prefix + "_resets", model.resets or ""))
    for win in parsed.windows:
        slug = win.slug
        counters = (
            ("requests_", win.requests),
            ("sessions_", win.sessions),
            ("subagent_heavy_pct_", win.subagent_heavy_pct),
            ("long_context_pct_", win.long_context_pct),
            ("long_session_pct_", win.long_session_pct),
        )
        for prefix, number in counters:
            if number is not None:
                out.append((prefix + slug, str(number)))
        if win.top_subagents is not None and win.top_subagents_more is not None:
            bounded = _bounded_top(win.top_subagents)
            if bounded is not None:
                joined, dropped = bounded
                out.append(("top_subagents_" + slug, joined))
                out.append(("top_subagents_more_" + slug, str(win.top_subagents_more + dropped)))
    return out


def poll_view(
    fields: Sequence[Tuple[str, str]], settings: SettingsResult, run_epoch: int
) -> Decision:
    """The poller's informational view: the same rule the gate uses, evaluated at poll time."""
    reading = ReadingRead("ok", dict(fields))
    return evaluate_cycle(reading, settings, float(run_epoch), poller_artifacts_present=True)


def _poll_view(
    fields: Sequence[Tuple[str, str]], settings: SettingsResult, run_epoch: int
) -> List[Tuple[str, str]]:
    decision = poll_view(fields, settings, run_epoch)
    out = [
        ("poll_settings_status", settings.status),
        ("poll_fail_mode", str(settings.values["fail_mode"])),
    ]
    if not settings.status.startswith("invalid:"):
        out.append(("poll_session_threshold", str(settings.values["session_threshold"])))
        out.append(("poll_weekly_threshold", str(settings.values["weekly_threshold"])))
        out.append(("poll_weekly_model_threshold", str(settings.values["weekly_model_threshold"])))
    out.append(("poll_staleness_seconds", str(settings.values["staleness_seconds"])))
    out.append(("poll_pause_condition", "1" if decision.decision == "pause" else "0"))
    out.append(("poll_pause_reason", _cap(decision.reason, REASON_CAP_CHARS)))
    return out


# ───────────────────────────── remote command, setup, check ─────────────────────────────


def _cron_schedule(interval: int) -> str:
    if interval == POLL_INTERVAL_MAX:
        return "0 * * * *"
    return "*/%d * * * *" % (interval // POLL_INTERVAL_STEP)


def _split_options(options: str) -> List[str]:
    """Split an authorized_keys option list on unquoted commas (OpenSSH quoting)."""
    parts: List[str] = []
    buf: List[str] = []
    quoted = False
    escaped = False
    for ch in options:
        if escaped:
            buf.append(ch)
            escaped = False
        elif quoted and ch == "\\":
            buf.append(ch)
            escaped = True
        elif ch == '"':
            buf.append(ch)
            quoted = not quoted
        elif ch == "," and not quoted:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _line_options(line: str) -> Optional[str]:
    """The option list of an authorized_keys line, or None when the line starts at the key type."""
    stripped = line.strip()
    if stripped.startswith(_KEY_TYPE_PREFIXES):
        return None
    quoted = False
    escaped = False
    for index, ch in enumerate(stripped):
        if escaped:
            escaped = False
        elif quoted and ch == "\\":
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif ch.isspace() and not quoted:
            return stripped[:index]
    return stripped


def _unquote_option(value: str) -> Optional[str]:
    """The value of a double-quoted option, or None when it is not double-quoted."""
    if value == '"' or not (value.startswith('"') and value.endswith('"')):
        return None
    return value[1:-1].replace('\\"', '"')


def check_authorized_keys(
    pub_path: Path, keys_path: Path, expected_cmd: Optional[str]
) -> Tuple[bool, str]:
    """Item 2: the one authorized_keys line has exactly from= and command=, byte-equal."""
    try:
        pub = _PUB_RE.fullmatch(pub_path.read_text(encoding="utf-8").strip().split("\n")[0])
    except (OSError, UnicodeDecodeError, IndexError):
        pub = None
    if pub is None:
        return False, "cannot read %s" % pub_path
    blob = pub.group(2)
    try:
        lines = keys_path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return False, "cannot read %s" % keys_path
    hits = [
        ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#") and blob in ln.split()
    ]
    if not hits:
        return False, "no authorized_keys line carries the key in %s" % pub_path
    if len(hits) > 1:
        return False, "%d authorized_keys lines carry the key; exactly one is allowed" % len(hits)
    options = _line_options(hits[0])
    parts = _split_options(options) if options else []
    seen_from = None
    seen_cmd = None
    for part in parts:
        if part.startswith("from=") or part.startswith("command="):
            name = part.split("=", 1)[0]
            if (seen_from if name == "from" else seen_cmd) is not None:
                return False, "duplicate option: %s=" % name
            value = _unquote_option(part[len(name) + 1 :])
            if value is None:
                return False, "option %s= value must be double-quoted" % name
            if name == "from":
                seen_from = value
            else:
                seen_cmd = value
        else:
            return False, "extra option: %s" % part
    if seen_from is None:
        return False, "missing from="
    if seen_from != "127.0.0.1,::1":
        return False, "from= mismatch: expected '127.0.0.1,::1' got '%s'" % seen_from
    if seen_cmd is None:
        return False, "missing command="
    if expected_cmd is None:
        return False, "cannot compute the expected command: claude not found"
    if seen_cmd != expected_cmd:
        return False, "command mismatch: expected '%s' got '%s'" % (expected_cmd, seen_cmd)
    return True, "one line, from= and command= only"


def _expand_home(token: str, home: str) -> str:
    for prefix in ("$HOME/", "${HOME}/", "~/"):
        if token.startswith(prefix):
            return home + "/" + token[len(prefix) :]
    return token


def _crontab_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip() and not ln.strip().startswith("#")]


def _command_tokens(line: str) -> Optional[Tuple[List[str], List[str]]]:
    """(schedule fields, command tokens) of a crontab line, or None when unparseable."""
    if line.startswith("@"):
        pieces = line.split(None, 1)
        schedule = pieces[:1]
    else:
        pieces = line.split(None, CRON_SCHEDULE_FIELDS)
        schedule = pieces[:CRON_SCHEDULE_FIELDS]
    rest = pieces[len(schedule)] if len(pieces) > len(schedule) else ""
    try:
        return schedule, shlex.split(rest)
    except ValueError:
        return None


def check_crontab_poller(
    lines: Sequence[str], interval: int, self_path: str, home: str
) -> Tuple[bool, str]:
    """Item 5."""
    hits = [ln for ln in lines if "hos-usage-poll" in ln]
    if not hits:
        return False, "no crontab line runs hos-usage-poll — add the line printed by --print-setup"
    if len(hits) > 1:
        return False, "%d crontab lines run hos-usage-poll; exactly one per host" % len(hits)
    line = hits[0]
    if ">>" in line:
        return False, "crontab line appends with >>; use > (one poll log, overwritten)"
    parsed = _command_tokens(line)
    if parsed is None:
        return False, "cannot parse the crontab line"
    schedule, tokens = parsed
    expected = _cron_schedule(interval).split()
    if schedule != expected:
        return False, "schedule '%s' does not match poll_interval_seconds=%d (expected '%s')" % (
            " ".join(schedule),
            interval,
            " ".join(expected),
        )
    command = [t for t in tokens if not _ENV_ASSIGN_RE.fullmatch(t)]
    if not command:
        return False, "crontab line has no command"
    invoked = _expand_home(command[0], home)
    if os.path.realpath(invoked) != os.path.realpath(self_path):
        return False, "crontab runs %s, not this copy %s" % (invoked, self_path)
    return True, "one entry, schedule %s, path is this copy" % " ".join(schedule)


def check_gate_copies(lines: Sequence[str], home: str) -> List[Tuple[str, str]]:
    """Item 8: every scheduled hos-cron copy carries the gate. Returns (status, text) rows."""
    copies: Dict[str, str] = {}
    rows: List[Tuple[str, str]] = []
    for line in lines:
        parsed = _command_tokens(line)
        if parsed is None:
            continue
        for token in parsed[1]:
            if os.path.basename(token) != "hos-cron":
                continue
            path = _expand_home(token, home)
            if not os.path.isabs(path):
                rows.append(
                    (
                        "FAIL",
                        "cannot resolve relative hos-cron path '%s' — use an absolute path" % token,
                    )
                )
                continue
            copies[os.path.realpath(path) if os.path.exists(path) else path] = path
    if not copies and not rows:
        return [("INFO", "no hos-cron scheduled in this user's crontab")]
    for resolved in sorted(copies):
        try:
            content = Path(resolved).read_text(encoding="utf-8", errors="replace")
        except OSError:
            rows.append(("FAIL", "%s: missing or unreadable hos-cron" % resolved))
            continue
        if not any(ln.rstrip() == GATE_SENTINEL for ln in content.split("\n")):
            rows.append(
                (
                    "FAIL",
                    "%s: no usage-pause gate — this copy's cycles are NOT paused; upgrade it"
                    % resolved,
                )
            )
        elif not os.path.isfile(os.path.join(os.path.dirname(resolved), "lib", "usage_pause.py")):
            rows.append(
                (
                    "FAIL",
                    "%s: gate present but lib/usage_pause.py missing — every cycle will pause with check_error"
                    % resolved,
                )
            )
        else:
            rows.append(("PASS", "%s: gate present" % resolved))
    return rows


class _Report:
    def __init__(self) -> None:
        self.failures = 0

    def add(self, status: str, number: int, text: str, remedy: Optional[str] = None) -> None:
        if status == "FAIL":
            self.failures += 1
        suffix = " — " + remedy if remedy else ""
        print("%s  %d  %s%s" % (status, number, text, suffix))


def _run_text(argv: Sequence[str]) -> Optional["subprocess.CompletedProcess[str]"]:
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _success_summary(cls: Classification) -> str:
    parsed = cls.parsed
    assert parsed is not None and cls.envelope is not None
    text = "SUCCESS session=%d weekly_all=%d" % (
        parsed.session_pct or 0,
        parsed.weekly_all_pct or 0,
    )
    for model in parsed.models:
        text += " %s=%d" % (model.slug, model.pct)
    cost = cls.envelope.cost_usd
    tokens = cls.envelope.read_tokens
    text += " cost_usd=%s" % (format_cost(cost) if cost is not None else "absent")
    text += " read_tokens=%s" % (tokens if tokens is not None else "absent")
    return text


def _capture_target_problem(target: str) -> Optional[str]:
    """The parent directory must be ours and not group/world-writable (the file holds a session id)."""
    parent = os.path.dirname(os.path.abspath(target))
    try:
        info = os.stat(parent)
    except OSError:
        return None  # a missing parent is reported by the write itself
    if info.st_uid != os.getuid():
        return "%s is not owned by the current user" % parent
    if info.st_mode & GROUP_WORLD_WRITE_BITS:
        return "%s is group- or world-writable" % parent
    return None


def _state_dir() -> Path:
    return Path(os.environ.get("HOS_STATE_DIR") or Path(_home()) / ".hos")


def _check_state_dir(report: "_Report") -> None:
    """Item 12: the crontab redirect needs this directory before the poller can start."""
    path = _state_dir() / "usage-pause"
    remedy = "run --print-setup block 1"
    try:
        info = os.stat(path)
    except OSError:
        report.add("FAIL", 12, "%s is absent" % path, remedy)
        return
    if not stat.S_ISDIR(info.st_mode):
        report.add("FAIL", 12, "%s is not a directory" % path, remedy)
    elif not os.access(path, os.W_OK | os.X_OK):
        report.add("FAIL", 12, "%s is not writable" % path, remedy)
    elif stat.S_IMODE(info.st_mode) != STATE_DIR_MODE:
        report.add(
            "FAIL", 12, "%s mode is %04o, not 0700" % (path, stat.S_IMODE(info.st_mode)), remedy
        )
    else:
        report.add("PASS", 12, "%s exists, mode 0700, writable" % path)


def _check_reading(report: "_Report", settings: SettingsResult, cron_ok: bool) -> None:
    """Item 11: what the poller has actually written, and how old it is."""
    current = read_reading(_state_dir() / "usage-pause" / READING_NAME)
    run_epoch = current.fields.get("run_epoch")
    if current.state != "ok" or not _is_uint(run_epoch):
        report.add(
            "FAIL" if cron_ok else "INFO",
            11,
            "no usable reading (%s)" % current.state,
            "wait one poll interval, then check poll.last.log" if cron_ok else None,
        )
        return
    age = int(time.time()) - int(run_epoch or "0")
    fields = current.fields
    text = "reading age=%ds outcome=%s reason=%s consecutive_failures=%s" % (
        age,
        fields.get("outcome", "-"),
        fields.get("reason", "-"),
        fields.get("consecutive_failures", "-"),
    )
    if age > int(str(settings.values["staleness_seconds"])):
        report.add(
            "FAIL", 11, text, "the poller is not running: check crontab -l and poll.last.log"
        )
    else:
        report.add("INFO", 11, text)


def run_check(self_path: str, capture_fixture: Optional[str]) -> int:
    """--check: read-only preflight (section 3.10). Writes only the optional capture file."""
    if capture_fixture is not None and os.path.lexists(capture_fixture):
        print(
            "hos-usage-poll: --capture-fixture target already exists: %s" % capture_fixture,
            file=sys.stderr,
        )
        return EXIT_USAGE
    if capture_fixture is not None:
        problem = _capture_target_problem(capture_fixture)
        if problem is not None:
            print("hos-usage-poll: --capture-fixture refused: %s" % problem, file=sys.stderr)
            return EXIT_USAGE
    home = _home()
    report = _Report()
    settings = load_settings(default_conf_path())
    key = default_key_path()
    pub = Path(str(key) + ".pub")
    claude_bin = resolve_claude_bin(settings)

    # 1. key
    try:
        mode = stat.S_IMODE(os.stat(key).st_mode)
        if mode == EXPECTED_KEY_MODE:
            report.add("PASS", 1, "%s exists, mode 0600" % key)
        else:
            report.add("FAIL", 1, "%s mode is %04o" % (key, mode), "chmod 600 %s" % key)
    except OSError:
        report.add("FAIL", 1, "%s is missing" % key, "run: hos-usage-poll --print-setup")

    # 2. authorized_keys
    expected = remote_cmd(claude_bin) if claude_bin else None
    ok, text = check_authorized_keys(pub, Path(home) / ".ssh" / "authorized_keys", expected)
    report.add(
        "PASS" if ok else "FAIL", 2, text, None if ok else "regenerate the line with --print-setup"
    )

    # 3. known_hosts
    kh = _run_text(
        ["ssh-keygen", "-F", "127.0.0.1", "-f", str(Path(home) / ".ssh" / "known_hosts")]
    )
    if kh is not None and kh.returncode == 0:
        report.add("PASS", 3, "127.0.0.1 is in known_hosts")
    else:
        report.add("FAIL", 3, "127.0.0.1 is not in known_hosts", "seed it (--print-setup block 4)")

    # 4. settings
    if settings.status.startswith("invalid:"):
        report.add(
            "FAIL",
            4,
            "settings invalid: %s=%s" % (settings.invalid_key, settings.invalid_value),
            "fix %s" % default_conf_path(),
        )
    else:
        report.add("PASS", 4, "settings %s" % settings.status)

    # 5 and 8 share one crontab read
    cron = _run_text(["crontab", "-l"])
    cron_lines = _crontab_lines(cron.stdout) if cron is not None and cron.returncode == 0 else None
    interval = int(str(settings.values["poll_interval_seconds"]))
    cron_ok = False
    if cron_lines is None:
        report.add(
            "FAIL",
            5,
            "crontab -l failed or crontab is absent",
            "install the line printed by --print-setup",
        )
    else:
        ok, text = check_crontab_poller(cron_lines, interval, self_path, home)
        cron_ok = ok
        report.add("PASS" if ok else "FAIL", 5, text)

    # 6. claude
    if claude_bin and os.access(claude_bin, os.X_OK):
        report.add("PASS", 6, "claude_bin %s is executable" % claude_bin)
    else:
        report.add(
            "FAIL",
            6,
            "claude_not_executable: %s" % (claude_bin or "claude not found"),
            "set claude_bin or fix PATH, then regenerate the authorized_keys line",
        )

    # 7. one real read, then 10
    cls = _check_read(report, key, settings, capture_fixture)

    # 8. every scheduled hos-cron copy carries the gate
    if cron_lines is None:
        report.add("FAIL", 8, "crontab unavailable; cannot check scheduled hos-cron copies")
    else:
        for status, row in check_gate_copies(cron_lines, home):
            report.add(status, 8, row)

    # 10. informational pause view of the item-7 read
    if cls is not None and cls.outcome == "success":
        now = int(time.time())
        fields = build_reading(
            run_epoch=now, classification=cls, diagnostics=None, previous=None, settings=settings
        )
        view = dict(fields)
        report.add(
            "INFO",
            10,
            "pause_condition=%s reason=%s"
            % (view["poll_pause_condition"], view["poll_pause_reason"]),
        )
    else:
        report.add("SKIP", 10, "no successful read")

    _check_reading(report, settings, cron_ok)
    _check_state_dir(report)

    if report.failures:
        print("RESULT: FAIL (%d failed)" % report.failures)
        return EXIT_FAIL
    print("RESULT: PASS")
    return 0


def _check_read(
    report: _Report, key: Path, settings: SettingsResult, capture_fixture: Optional[str]
) -> Optional[Classification]:
    if not key.is_file():
        report.add("FAIL", 7, "FAILED reason=ssh_failed detail=loopback key missing")
        return None
    capture_error: Optional[str] = None
    work = Path(os.environ.get("TMPDIR") or "/tmp") / (
        "hos-usage-check-%d-%s" % (os.getpid(), os.urandom(6).hex())
    )
    try:
        os.mkdir(str(work), STATE_DIR_MODE)
    except OSError as exc:
        report.add("FAIL", 7, "cannot create a temp directory: %s" % _flatten(str(exc)))
        return None
    try:
        out_path, err_path = work / "stdout", work / "stderr"
        timeout = int(str(settings.values["read_timeout_seconds"]))
        outcome = read_usage(
            key_path=key, timeout_s=timeout, stdout_path=out_path, stderr_path=err_path
        )
        raw_out = out_path.read_bytes() if out_path.exists() else b""
        raw_err = err_path.read_bytes() if err_path.exists() else b""
        cls = classify_read(outcome, raw_out, raw_err)
        if capture_fixture is not None and outcome.kind == "exited":
            try:
                write_atomic(Path(capture_fixture), raw_out, FILE_MODE)
            except OSError as exc:
                capture_error = _flatten(str(exc))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)
    if cls.outcome != "success":
        report.add("FAIL", 7, "FAILED reason=%s detail=%s" % (cls.reason, cls.detail or "-"))
    else:
        envelope = cls.envelope
        assert envelope is not None
        summary = _success_summary(cls)
        if envelope.cost_usd == 0 and envelope.read_tokens == 0:
            report.add("PASS", 7, summary)
        else:
            report.add("FAIL", 7, summary, "read cost not zero/unknown — FR-9")
    if raw_err:
        report.add("INFO", 7, "stderr non-empty (%d bytes)" % len(raw_err))
    if capture_error is not None:
        report.add("FAIL", 7, "capture failed: %s" % capture_error)
    elif capture_fixture is not None and outcome.kind != "exited":
        report.add("INFO", 7, "capture skipped: read did not exit")
    elif capture_fixture is not None:
        report.add("INFO", 7, "captured %d bytes to %s" % (len(raw_out), capture_fixture))
    return cls


def run_print_setup(self_path: str) -> int:
    """--print-setup: prints the setup, never mutates (section 3.11)."""
    home = _home()
    settings = load_settings(default_conf_path())
    interval = int(str(settings.values["poll_interval_seconds"]))
    claude_bin = resolve_claude_bin(settings)
    key = "~/.ssh/hos_loopback"
    pub = Path(home) / ".ssh" / "hos_loopback.pub"
    print("# 1. State directory")
    print("mkdir -p ~/.hos/usage-pause && chmod 700 ~/.hos/usage-pause")
    print()
    print("# 2. Loopback key (personal login; never claude-auth credentials)")
    print("ssh-keygen -t ed25519 -N '' -C hos-loopback -f %s" % key)
    print()
    print("# 3. authorized_keys: append exactly this one line to ~/.ssh/authorized_keys")
    missing = []
    try:
        pub_match = _PUB_RE.fullmatch(pub.read_text(encoding="utf-8").strip().split("\n")[0])
    except (OSError, UnicodeDecodeError, IndexError):
        pub_match = None
    if pub_match is None:
        missing.append("MISSING: %s — run block 2 first, then re-run --print-setup" % pub)
    elif claude_bin is None:
        missing.append(
            "MISSING: claude not found — set claude_bin in the settings file or fix PATH"
        )
    else:
        print(
            'from="127.0.0.1,::1",command="%s" %s %s hos-loopback'
            % (remote_cmd(claude_bin), pub_match.group(1), pub_match.group(2))
        )
    print()
    print("# 4. known_hosts: seed from the on-disk host key (no network trust)")
    print(
        "printf '127.0.0.1 %s\\n' \"$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)\" >> ~/.ssh/known_hosts"
    )
    print()
    print("# 5. Crontab line — the single install-path definition (crontab -e)")
    print(
        "%s  %s > %s 2>&1"
        % (
            _cron_schedule(interval),
            shlex.quote(self_path),
            shlex.quote(home + "/.hos/usage-pause/poll.last.log"),
        )
    )
    print()
    print("# 6. Verify: first run captures the unfiltered envelope, then a plain check")
    print(
        "%s --check --capture-fixture %s"
        % (
            shlex.quote(self_path),
            shlex.quote("%s/hos-usage-envelope-%s.json" % (home, time.strftime("%Y%m%d"))),
        )
    )
    print("%s --check" % shlex.quote(self_path))
    for line in missing:
        print(line)
    return EXIT_FAIL if missing else 0


# ───────────────────────────── CLI ─────────────────────────────


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print("usage_pause: %s" % message, file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _state_paths(state_dir: str) -> Tuple[Path, Path]:
    base = Path(state_dir) / "usage-pause"
    return base, base / READING_NAME


def _cmd_poll_params(_args: argparse.Namespace) -> int:
    settings = load_settings(default_conf_path())
    print("read_timeout_seconds=%s" % settings.values["read_timeout_seconds"])
    print("settings_status=%s" % settings.status)
    return 0


def _cmd_read_usage(args: argparse.Namespace) -> int:
    outcome = read_usage(
        key_path=Path(args.key),
        timeout_s=args.timeout,
        stdout_path=Path(args.stdout),
        stderr_path=Path(args.stderr),
    )
    print("read=%s rc=%s" % (outcome.kind, "-" if outcome.rc is None else outcome.rc))
    return 0


def _cmd_poll_record(args: argparse.Namespace) -> int:
    base, reading_path = _state_paths(args.state_dir)
    os.makedirs(str(base), STATE_DIR_MODE, exist_ok=True)
    run_epoch = int(time.time())
    settings = load_settings(default_conf_path())
    previous = read_reading(reading_path)
    if args.transport_reason is not None or args.read is None:
        cls = classify_read(
            None, b"", b"", args.transport_reason or "crashed", args.detail or "no read recorded"
        )
    else:
        outcome = ReadOutcome(args.read, args.rc, None)
        cls = classify_read(
            outcome,
            _read_bytes(Path(args.stdout), INPUT_CAP_BYTES) if args.stdout else b"",
            _read_tail(Path(args.stderr), INPUT_CAP_BYTES) if args.stderr else b"",
        )
    fields = build_reading(
        run_epoch=run_epoch,
        classification=cls,
        diagnostics=args.diagnostics or None,
        previous=previous,
        settings=settings,
    )
    try:
        write_atomic(reading_path, render_reading(fields).encode("utf-8"), FILE_MODE)
    except OSError as exc:
        print("hos-usage-poll: cannot write reading: %s" % _flatten(str(exc)), file=sys.stderr)
        return EXIT_FAIL
    view = dict(fields)
    parts = ["[hos-usage-poll] %s outcome=%s" % (view["run_at"], view["outcome"])]
    if "reason" in view:
        parts.append("reason=%s" % view["reason"])
    if "session_pct" in view:
        parts.append("session=%s weekly_all=%s" % (view["session_pct"], view["weekly_all_pct"]))
    if "cost_usd" in view or "read_tokens" in view:
        parts.append(
            "cost=%s tokens=%s" % (view.get("cost_usd", "-"), view.get("read_tokens", "-"))
        )
    parts.append(
        "pause_condition=%s (%s)"
        % (view["poll_pause_condition"], ascii_fold(view["poll_pause_reason"]))
    )
    print(" ".join(parts))
    return 0


def _cmd_last_raw(args: argparse.Namespace) -> int:
    base, _reading = _state_paths(args.state_dir)
    os.makedirs(str(base), STATE_DIR_MODE, exist_ok=True)
    body = b""
    stream = "none"
    rc_text = "-" if args.rc is None else str(args.rc)
    if args.read != "none":
        from_stderr = args.read != "exited" or args.rc == SSH_FAILURE_RC
        stream = "stderr" if from_stderr else "stdout"
        if args.stdout and not from_stderr:
            body = _read_bytes(Path(args.stdout), INPUT_CAP_BYTES)
        elif args.stderr and from_stderr:
            body = _read_tail(Path(args.stderr), INPUT_CAP_BYTES)
    header = "# hos-usage-poll last-raw run_epoch=%d read=%s rc=%s stream=%s bytes=%d\n" % (
        args.run_epoch,
        args.read,
        rc_text,
        stream,
        len(body),
    )
    try:
        write_atomic(base / LAST_RAW_NAME, header.encode("utf-8") + body, FILE_MODE)
    except OSError as exc:
        print("hos-usage-poll: cannot write last-raw: %s" % _flatten(str(exc)), file=sys.stderr)
        return EXIT_FAIL
    return 0


def _cmd_remote_cmd(_args: argparse.Namespace) -> int:
    claude_bin = resolve_claude_bin(load_settings(default_conf_path()))
    if claude_bin is None:
        print("hos-usage-poll: no claude_bin resolves; set claude_bin or fix PATH", file=sys.stderr)
        return EXIT_FAIL
    print(remote_cmd(claude_bin))
    return 0


def _cmd_check_setup(args: argparse.Namespace) -> int:
    return run_check(args.self_path, args.capture_fixture)


def _cmd_print_setup(args: argparse.Namespace) -> int:
    return run_print_setup(args.self_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="usage_pause.py")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("poll-params").set_defaults(func=_cmd_poll_params)
    p = sub.add_parser("read-usage")
    p.add_argument("--timeout", type=int, required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--stdout", required=True)
    p.add_argument("--stderr", required=True)
    p.set_defaults(func=_cmd_read_usage)
    p = sub.add_parser("poll-record")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--read", choices=("exited", "timeout", "spawn_failed"))
    p.add_argument("--rc", type=int)
    p.add_argument("--stdout")
    p.add_argument("--stderr")
    p.add_argument("--transport-reason", choices=sorted(READ_FAILURE_REASONS))
    p.add_argument("--detail")
    p.add_argument("--diagnostics")
    p.set_defaults(func=_cmd_poll_record)
    p = sub.add_parser("last-raw")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--read", required=True, choices=("exited", "timeout", "spawn_failed", "none"))
    p.add_argument("--rc", type=int)
    p.add_argument("--stdout")
    p.add_argument("--stderr")
    p.add_argument("--run-epoch", type=int, required=True)
    p.set_defaults(func=_cmd_last_raw)
    sub.add_parser("remote-cmd").set_defaults(func=_cmd_remote_cmd)
    p = sub.add_parser("check-setup")
    p.add_argument("--self-path", required=True)
    p.add_argument("--capture-fixture")
    p.set_defaults(func=_cmd_check_setup)
    p = sub.add_parser("print-setup")
    p.add_argument("--self-path", required=True)
    p.set_defaults(func=_cmd_print_setup)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
