#!/usr/bin/env python3
"""
agent_invoke_cli.py — L2 deterministic agent-invocation primitive (#1643 W1).

Invokes exactly one shipped, named agent (AD-3) through the `claude` CLI,
classifies the result with a fail-closed allowlist (AD-4, amended by
ADR-1643 Amendment 1 §9.1/§9.2), and emits exactly one JSON result document
on stdout (AD-6). This module owns the record schema and the exit codes,
exactly as `merge_authority_cli.py` owns its own (#1357 ARCH-3a) — invoked
exclusively through `bootstrap/invoke_agent.sh` (L3), which passes stdout and
the exit code through byte-for-byte and mints no token (this surface performs
no GitHub I/O).

Contract: docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md §2 (AD-1
through AD-9) and §9 (Amendment 1 — governs wherever it differs from the
technical design);
docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md §3 (W1) and §4
(shape only — the input_digest/--not-applicable/--output-file round-trip
*obligations* of §4 are W2's, not this module's slice gate, but this module
already emits the fields those obligations will be checked against).

--require-env-auth is MANDATORY for every non-interactive caller (bin/hos-cron
in either role, any script a cron cycle executes) per ADR-1643 Amendment 1
§9.3. This module does not know its caller and cannot enforce that; it is
documented here and in bootstrap/invoke_agent.sh's header so the obligation
travels with both canonical entry points. Post-hoc `not_authenticated`
detection (§3.7) is unconditional regardless of the flag.

Importing this module performs no I/O, no config read, no subprocess launch,
and no clock read beyond constant definition — the only module-level work is
the sys.path bootstrap below, which makes the CLI cwd-immune (mirrors
merge_authority_cli.py's rationale: a cwd-relative import silently disables
the guard the moment someone invokes it from elsewhere).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Import bootstrap (TD §2): insert this CLI's own repo root at sys.path[0]
# before importing scripts.* so imports resolve regardless of cwd. Do not
# rely on being invoked from the repo root; do not rely on PYTHONPATH.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_DEFAULT_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

import yaml  # noqa: E402

# ---------------------------------------------------------------------------
# Module constants (TD §3.1 member 6)
# ---------------------------------------------------------------------------

SCHEMA = "hos.agent-invocation-result"
SCHEMA_VERSION = 1

# Re-exported literally from scripts/oversight/validation_logic.py's own
# constants (SEVERITIES, ERROR_VERDICT-derived VERDICTS). Not imported: that
# module is not an importable package (no __init__.py; tests/conftest.py
# injects the path) and classify()/`_extract_payload()` must stay pure with
# no I/O, so the values are copied here as a literal and must be kept in sync
# by hand if scripts/oversight/validation_logic.py's SEVERITIES ever changes.
SEVERITIES = ["critical", "high", "blocking", "warning", "medium", "low", "none"]
VERDICTS = frozenset({"approve", "request_changes", "error"})

# AD-4 amended by ADR-1643 §9.1/§9.2 (A4): the only value that lets
# `terminal_reason` pass. An allowlist of *good* values, not a denylist of
# bad ones — a CLI version that introduces a new terminal reason we have
# never seen fails closed by default (this is the design move that makes
# #669/#1362 unrepeatable rather than re-fixed).
GOOD_TERMINAL_REASONS = frozenset({"completed"})

# terminal_reason values this classifier already recognises as bad and can
# label precisely (TD §3.7 rule 4). Any other bad value still blocks, via the
# `terminal_reason:<value>` catch-all — this is the allowlist-not-denylist
# property, applied to labelling as well as to gating.
_KNOWN_BAD_TERMINAL_REASONS = frozenset({"api_error", "usage_limit", "refusal", "max_turns"})
_NOT_LOGGED_IN_RE = re.compile(r"not logged in", re.IGNORECASE)

# The full top-level field set observed on a real "claude --print
# --output-format json" result envelope (ADR-1643 TD §0.2 probe A, plus
# probe R's api_error_status). Anything else is recorded in
# invocation.envelope_unknown_fields[] and does not block (ADR-1643 §9.2(a));
# an unrecognised *value or shape* in one of the decision fields below still
# blocks via classify()'s own checks.
KNOWN_ENVELOPE_TOP_LEVEL_FIELDS = frozenset(
    {
        "duration_api_ms",
        "stop_reason",
        "session_id",
        "total_cost_usd",
        "usage",
        "modelUsage",
        "permission_denials",
        "terminal_reason",
        "fast_mode_state",
        "fast_mode_disabled_reason",
        "subagent_stats",
        "is_error",
        "num_turns",
        "subtype",
        "api_error_status",
        "result",
        "ttft_ms",
        "type",
        "duration_ms",
        "uuid",
        "ttft_stream_ms",
        "time_to_request_ms",
        "first_content_frame_ms",
        "queued_turn_count",
        "result_index",
    }
)

# A payload extracted from `result` may never assert one of L2's own fields
# (§4.3 rule 5) — there is no path by which an agent declares itself exempt
# (worker.md:373-378: "v0.4.0 #556: workers repeatedly self-exempted on this
# basis").
_FORBIDDEN_PAYLOAD_KEYS = frozenset({"applicability", "outcome", "input", "invocation"})

AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
POSTURE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

KNOWN_POSTURES = frozenset({"review-read-only", "review-read-only-gh-read"})

DEFAULT_TIMEOUT_S = 300
MIN_TIMEOUT_S = 30
MAX_TIMEOUT_S = 1800

DEFAULT_GRACE_S = 10
MIN_GRACE_S = 1
MAX_GRACE_S = 60

_STDOUT_PARTIAL_CAP = 4096
_STDERR_TAIL_CAP = 4096

_FRONTMATTER_RE = re.compile(rb"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Control-flow exceptions — never raised past main(); no bare `sys.exit`
# anywhere else in this module (TD §3.1 member 1).
# ---------------------------------------------------------------------------


class _UsageError(Exception):
    """A caller programming error: exit 2, one stderr line, no document."""


class _OperationalError(Exception):
    """The primitive itself could not emit a document: exit 1, one stderr
    line, no document."""


class _PreflightFailure(Exception):
    """A precondition failed in a way that is a *record*, not a silence
    (AD-3/AD-7): exit 0, a conforming invocation_failed document, no process
    launched."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class AgentRef:
    name: str
    path: Path
    bytes_: bytes
    sha256: str


@dataclass
class Posture:
    id: str
    settings_path: Path
    sidecar_path: Path
    settings_bytes: bytes
    sidecar_bytes: bytes
    permission_mode: str
    allowed_tools: list[str]
    disallowed_tools: list[str]
    sha256: str


@dataclass
class ProcResult:
    rc: int | None
    timed_out: bool
    stdout_bytes: bytes
    stderr_bytes: bytes
    duration_ms: int
    stdout_partial: bytes | None = None


@dataclass
class Classification:
    outcome: str  # "completed" | "invocation_failed"
    outcome_detail: str | None
    envelope: dict | None
    envelope_unknown_fields: list[str] = field(default_factory=list)
    payload: dict | None = None


# ---------------------------------------------------------------------------
# AD-3 — agent resolution (§3.4 P3/P4)
# ---------------------------------------------------------------------------


def _parse_frontmatter(data: bytes) -> dict | None:
    """Extract and parse the YAML frontmatter block of an agent file. Returns
    None on any structural or parse failure — the caller maps that to
    `agent_unavailable`, never a fallback."""
    match = _FRONTMATTER_RE.match(data)
    if not match:
        return None
    try:
        parsed = yaml.safe_load(match.group(1).decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return None
    return parsed if isinstance(parsed, dict) else None


def resolve_agent(repo_root: Path, name: str) -> AgentRef:
    """AD-3's resolution and existence check. A shipped, named agent is the
    only unit of invocation — absent, empty, or mismatched-name all raise
    `_PreflightFailure("agent_unavailable")`. Never a fallback to a
    general-purpose agent, never a bare model (#1126/#608)."""
    path = repo_root / ".claude" / "agents" / f"{name}.md"
    if not path.is_file():
        raise _PreflightFailure("agent_unavailable")
    data = path.read_bytes()
    if not data.strip():
        raise _PreflightFailure("agent_unavailable")
    frontmatter = _parse_frontmatter(data)
    if frontmatter is None or frontmatter.get("name") != name:
        # TD-D3: a file that exists but declares a different `name:` is the
        # #608 governance hole — the caller believes it invoked one agent and
        # the CLI resolved something else.
        raise _PreflightFailure("agent_unavailable")
    return AgentRef(name=name, path=path, bytes_=data, sha256=hashlib.sha256(data).hexdigest())


# ---------------------------------------------------------------------------
# AD-7 — posture loading and validation (§3.6 V1-V11)
# ---------------------------------------------------------------------------


def load_posture(repo_root: Path, name: str) -> Posture:
    """AD-7's posture load and validation. `name` not in KNOWN_POSTURES is a
    caller programming error (exit 2, via `_UsageError`); every other miss
    (V2-V11) is a `_PreflightFailure("posture_invalid")` record, because a
    malformed or tampered posture file is an environment state, not a typo.
    """
    if name not in KNOWN_POSTURES:
        raise _UsageError(f"unknown --posture: {name!r}")

    postures_dir = repo_root / "contract" / "dimensions" / "postures"
    settings_path = postures_dir / f"{name}.settings.json"
    sidecar_path = postures_dir / f"{name}.hos.json"

    if not settings_path.is_file() or not sidecar_path.is_file():  # V2
        raise _PreflightFailure("posture_invalid")

    settings_bytes = settings_path.read_bytes()
    sidecar_bytes = sidecar_path.read_bytes()

    try:  # V3
        settings = json.loads(settings_bytes)
        sidecar = json.loads(sidecar_bytes)
    except json.JSONDecodeError:
        raise _PreflightFailure("posture_invalid")
    if not isinstance(settings, dict) or not isinstance(sidecar, dict):
        raise _PreflightFailure("posture_invalid")

    if sidecar.get("schema") != "hos.invocation-posture" or sidecar.get("schema_version") != 1:
        raise _PreflightFailure("posture_invalid")  # V4
    if sidecar.get("id") != name or settings_path.stem.split(".")[0] != name:
        raise _PreflightFailure("posture_invalid")  # V5

    permission_mode = sidecar.get("permission_mode")
    if permission_mode not in ("manual", "dontAsk"):
        raise _PreflightFailure("posture_invalid")  # V6

    permissions = settings.get("permissions")
    if (
        not isinstance(permissions, dict)
        or permissions.get("disableBypassPermissionsMode") != "disable"
    ):
        raise _PreflightFailure("posture_invalid")  # V7

    allow = permissions.get("allow")
    deny = permissions.get("deny")
    if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
        raise _PreflightFailure("posture_invalid")  # V8
    if not isinstance(deny, list) or not all(isinstance(x, str) for x in deny):
        raise _PreflightFailure("posture_invalid")  # V8

    allowed_tools = sidecar.get("allowed_tools")
    disallowed_tools = sidecar.get("disallowed_tools")
    if not isinstance(allowed_tools, list) or not all(isinstance(x, str) for x in allowed_tools):
        raise _PreflightFailure("posture_invalid")
    if not isinstance(disallowed_tools, list) or not all(
        isinstance(x, str) for x in disallowed_tools
    ):
        raise _PreflightFailure("posture_invalid")

    if set(allowed_tools) & set(disallowed_tools):
        raise _PreflightFailure("posture_invalid")  # V9
    if not set(disallowed_tools) <= set(deny):
        raise _PreflightFailure("posture_invalid")  # V10

    if permissions.get("defaultMode") == "bypassPermissions":
        raise _PreflightFailure("posture_invalid")  # V11
    if b"dangerously" in settings_bytes.lower():
        raise _PreflightFailure("posture_invalid")  # V11

    posture_sha256 = hashlib.sha256(settings_bytes + b"\0" + sidecar_bytes).hexdigest()
    return Posture(
        id=name,
        settings_path=settings_path,
        sidecar_path=sidecar_path,
        settings_bytes=settings_bytes,
        sidecar_bytes=sidecar_bytes,
        permission_mode=permission_mode,
        allowed_tools=list(allowed_tools),
        disallowed_tools=list(disallowed_tools),
        sha256=posture_sha256,
    )


# ---------------------------------------------------------------------------
# AD-5 — launch, cap, and process-group reap (§3.5)
# ---------------------------------------------------------------------------


def run_capped(
    argv: list[str],
    *,
    stdin_bytes: bytes,
    cwd: Path,
    timeout_s: int,
    grace_s: int,
) -> ProcResult:
    """Launch `argv` in its own process group, deliver `stdin_bytes` on
    stdin, and enforce `timeout_s` ourselves (AD-5) — `start_new_session=True`
    is the whole point, since `claude` spawns tool subprocesses that a signal
    to the direct pid alone would orphan. On expiry: SIGTERM the group, wait
    `grace_s`, then SIGKILL the group. Both signals target the process
    *group*, never the pid. Stdout and stderr are read on separate threads
    while stdin is written, so a full pipe buffer on one stream can never
    deadlock the others (never `communicate()` without a timeout, never a
    merged stream)."""
    start = time.monotonic()
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        start_new_session=True,
    )

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    def _write_stdin() -> None:
        try:
            if stdin_bytes:
                proc.stdin.write(stdin_bytes)  # type: ignore[union-attr]
        except OSError:
            pass
        finally:
            try:
                proc.stdin.close()  # type: ignore[union-attr]
            except OSError:
                pass

    def _read(stream, sink: list[bytes]) -> None:
        try:
            for chunk in iter(lambda: stream.read(65536), b""):
                sink.append(chunk)
        except (OSError, ValueError):
            pass

    writer = threading.Thread(target=_write_stdin, daemon=True)
    out_reader = threading.Thread(target=_read, args=(proc.stdout, stdout_chunks), daemon=True)
    err_reader = threading.Thread(target=_read, args=(proc.stderr, stderr_chunks), daemon=True)
    writer.start()
    out_reader.start()
    err_reader.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()

    writer.join(timeout=grace_s + 5)
    out_reader.join(timeout=grace_s + 5)
    err_reader.join(timeout=grace_s + 5)

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout_bytes = b"".join(stdout_chunks)
    stderr_bytes = b"".join(stderr_chunks)

    stdout_partial = None
    if timed_out:
        # Partial stdout captured before the kill cannot be a complete
        # envelope, so it is discarded for classification purposes but kept,
        # truncated, for diagnosis (§3.5.5).
        stdout_partial = stdout_bytes[:_STDOUT_PARTIAL_CAP]
        stdout_bytes = b""

    return ProcResult(
        rc=proc.returncode,
        timed_out=timed_out,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        duration_ms=duration_ms,
        stdout_partial=stdout_partial,
    )


# ---------------------------------------------------------------------------
# AD-4 (amended by ADR-1643 §9.1/§9.2) — the classifier (§3.7)
# ---------------------------------------------------------------------------


def _parse_envelope(stdout_bytes: bytes) -> dict | None:
    """A2 — stdout must parse as exactly one JSON object, surrounding
    whitespace tolerated, nothing else. No brace scanning, no prose
    tolerance — that posture is correct for a foreign vendor's stdout
    (agy/codex) and wrong for our own primitive, which can be strict."""
    try:
        text = stdout_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _classify_refused(subagent_stats: object) -> str:
    """A6, with the ADR-1643 §9.1 value rules made explicit:
    - quantifies over VALUES, never a known key set (a refusal reason never
      seen before still blocks, with no code change);
    - "the integer 0" excludes booleans (`isinstance(True, int)` is True in
      Python — checked first, before the int check, so it can't slip through);
    - null/None is not zero and is never treated as one;
    - only a flat mapping of scalars is accepted — nested mapping, list, or
      string all violate;
    - absence is harmless.
    Returns one of: "absent", "ok", "nonzero", "shape_violation"."""
    if subagent_stats is None:
        return "absent"
    if not isinstance(subagent_stats, dict):
        return "shape_violation"
    if "refused" not in subagent_stats:
        return "absent"
    refused = subagent_stats["refused"]
    if isinstance(refused, bool):
        return "shape_violation"
    if isinstance(refused, int):
        return "ok" if refused == 0 else "nonzero"
    if isinstance(refused, dict):
        values = list(refused.values())
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int):
                return "shape_violation"
        return "ok" if all(value == 0 for value in values) else "nonzero"
    return "shape_violation"


def _terminal_reason_status(envelope: dict) -> tuple[str, str | None]:
    """A4 (ADR-1643 §9.2(b)): terminal_reason must be PRESENT, a string, and
    in GOOD_TERMINAL_REASONS. Returns ("missing"|"shape_violation"|"good"|
    "bad", value-or-None) — the value is a str exactly when the status is
    "good" or "bad" (both only reached after `isinstance(value, str)`
    holds), None for "missing"/"shape_violation"."""
    if "terminal_reason" not in envelope:
        return "missing", None
    value = envelope["terminal_reason"]
    if not isinstance(value, str):
        return "shape_violation", None
    if value in GOOD_TERMINAL_REASONS:
        return "good", value
    return "bad", value


def _terminal_reason_detail(value: str, result: object) -> str:
    """TD §3.7 rule 4's labelling, unchanged by the amendment. The
    `terminal_reason:<value>` catch-all is what makes a brand new bad value
    fail closed by default rather than needing a code change (#669/#1362)."""
    if value == "api_error" and isinstance(result, str) and _NOT_LOGGED_IN_RE.search(result):
        return "not_authenticated"
    if value in _KNOWN_BAD_TERMINAL_REASONS:
        return value
    return f"terminal_reason:{value}"


def _extract_payload(envelope: dict) -> dict | None:
    """§4.3 — strict payload extraction. Deliberately NOT
    `validation_logic.extract_json_objects`: that reader is prose-tolerant
    because agy and codex both prepend commentary; our own agent is
    instructed by our own prompt template and can be held to a contract.
    Returns the normalised payload dict, or None on any schema violation.
    Pure: no I/O."""
    result = envelope.get("result")
    if not isinstance(result, str):
        return None

    text = result.strip()
    if text.startswith("```json") and text.endswith("```") and len(text) > len("```json") + 3:
        text = text[len("```json") : -3].strip()
    elif text.startswith("```") and text.endswith("```") and len(text) > 6:
        text = text[3:-3].strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if _FORBIDDEN_PAYLOAD_KEYS & payload.keys():
        return None

    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        return None

    findings = payload.get("findings")
    if not isinstance(findings, list):
        return None

    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, str):
        return None

    attacks = payload.get("attacks")
    if attacks is None:
        attacks = []
    if not isinstance(attacks, list):
        return None

    normalised_findings = []
    for finding in findings:
        if not isinstance(finding, dict):
            return None
        severity = finding.get("severity")
        if severity not in SEVERITIES:
            return None
        raw_files = finding.get("files")
        raw_file = finding.get("file")
        has_files_list = (
            isinstance(raw_files, list)
            and bool(raw_files)
            and all(isinstance(x, str) for x in raw_files)
        )
        has_single_file = isinstance(raw_file, str)
        if not has_files_list and not has_single_file:
            return None
        norm = dict(finding)
        # Re-narrowed inline (mypy cannot carry the isinstance() results
        # above through the has_files_list/has_single_file booleans): both
        # branches below re-check the same condition directly on the raw
        # value so `files`/`single_file` are concretely typed, not Any|None.
        if isinstance(raw_files, list) and raw_files and all(isinstance(x, str) for x in raw_files):
            files: list[str] = list(raw_files)
        elif isinstance(raw_file, str):
            files = [raw_file]
        else:
            files = []
        single_file: str | None = (
            raw_file if isinstance(raw_file, str) else (files[0] if files else None)
        )
        category = norm.get("category")
        finding_type = norm.get("type")
        if category is None and finding_type is not None:
            category = finding_type
        if finding_type is None and category is not None:
            finding_type = category
        norm["files"] = files
        norm["file"] = single_file
        norm["category"] = category
        norm["type"] = finding_type
        norm.setdefault("line", None)
        normalised_findings.append(norm)

    return {
        "verdict": verdict,
        "summary": summary,
        "findings": normalised_findings,
        "attacks": attacks,
    }


def classify(proc: ProcResult) -> Classification:
    """AD-4's allowlist, amended by ADR-1643 §9.1/§9.2 — implements the A1-A9
    table, not the ADR's original (superseded) rows and not TD §3.7's
    superseded C4/C6 rows. Pure: value in, value out, no I/O.

    `outcome == "completed"` only when every row holds; any miss produces
    `outcome == "invocation_failed"` with a precedence-ordered detail
    (TD §3.7, with `terminal_reason_missing` inserted at rule 4's position,
    replacing rule 4's absent case, per ADR-1643 §9.2(b))."""
    if proc.timed_out:  # A1
        return Classification(outcome="invocation_failed", outcome_detail="timeout", envelope=None)

    envelope = _parse_envelope(proc.stdout_bytes)  # A2
    if envelope is None:
        return Classification(
            outcome="invocation_failed", outcome_detail="unparseable", envelope=None
        )

    unknown_fields = sorted(set(envelope) - KNOWN_ENVELOPE_TOP_LEVEL_FIELDS)

    is_error = envelope.get("is_error")
    if is_error is not None and not isinstance(is_error, bool):  # A3 shape
        return Classification(
            outcome="invocation_failed",
            outcome_detail="envelope_shape_violation",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    permission_denials = envelope.get("permission_denials")
    if permission_denials is not None and not isinstance(permission_denials, list):  # A5 shape
        return Classification(
            outcome="invocation_failed",
            outcome_detail="envelope_shape_violation",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    refused_status = _classify_refused(envelope.get("subagent_stats"))  # A6
    if refused_status == "shape_violation":
        return Classification(
            outcome="invocation_failed",
            outcome_detail="envelope_shape_violation",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    tr_status, tr_value = _terminal_reason_status(envelope)  # A4
    if tr_status == "shape_violation":
        return Classification(
            outcome="invocation_failed",
            outcome_detail="envelope_shape_violation",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )
    if tr_status == "missing":
        return Classification(
            outcome="invocation_failed",
            outcome_detail="terminal_reason_missing",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )
    if tr_status == "bad":
        # Guaranteed by _terminal_reason_status's own branching (see its
        # docstring): "bad" is only returned alongside a str value. Asserted
        # rather than cast so a future change that breaks the correlation
        # fails loudly here instead of passing a non-str silently onward.
        assert isinstance(tr_value, str)
        detail = _terminal_reason_detail(tr_value, envelope.get("result"))
        return Classification(
            outcome="invocation_failed",
            outcome_detail=detail,
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    if is_error:  # A3 value
        return Classification(
            outcome="invocation_failed",
            outcome_detail="crash",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    if permission_denials:  # A5 value
        return Classification(
            outcome="invocation_failed",
            outcome_detail="permission_denied",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    if refused_status == "nonzero":  # A6 value
        return Classification(
            outcome="invocation_failed",
            outcome_detail="refused",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    if proc.rc != 0:  # A7
        return Classification(
            outcome="invocation_failed",
            outcome_detail="crash",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    payload = _extract_payload(envelope)  # A8
    if payload is None:
        return Classification(
            outcome="invocation_failed",
            outcome_detail="schema_violation",
            envelope=envelope,
            envelope_unknown_fields=unknown_fields,
        )

    # A9 — unknown top-level fields never affect the outcome.
    return Classification(
        outcome="completed",
        outcome_detail=None,
        envelope=envelope,
        envelope_unknown_fields=unknown_fields,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# AD-6 — the result document assembler (TD §4, shape only — see module
# docstring)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _matched_files_digest(repo_root: Path, matched_files: list[str]) -> str | None:
    """TD §4.4 — over file *bytes*, not paths: a rename with no content
    change does not invalidate a record; a content change with no rename
    does. Missing/unreadable files hash to a stable sentinel rather than
    raising, since this is a diagnostic identity function, not a gate."""
    if not matched_files:
        return None
    pairs = []
    for rel in sorted(matched_files):
        path = repo_root / rel
        try:
            file_hash = _sha256_bytes(path.read_bytes())
        except OSError:
            file_hash = "unreadable"
        pairs.append([rel, file_hash])
    return _sha256_bytes(json.dumps(pairs, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def compute_input_digest(
    *,
    agent: str,
    agent_file_sha256: str | None,
    posture_id: str | None,
    posture_sha256: str | None,
    input_file_sha256: str | None,
    prompt_template_version: str | None,
    dimension: str,
    binding: str | None,
    matched_files_sha256: str | None,
    base_sha: str | None,
    head_sha: str | None,
) -> str:
    """TD §4.4 — one function, two populations. Absent components are
    explicitly None so a W1-era ad-hoc digest can never accidentally equal a
    later binding-keyed digest. `binding_sha256` (the binding's own resolved
    JSON) has no source in W1, which has no registry, and is carried as None."""
    manifest = {
        "v": 1,
        "agent": agent,
        "agent_file_sha256": agent_file_sha256,
        "posture": posture_id,
        "posture_sha256": posture_sha256,
        "input_file_sha256": input_file_sha256,
        "prompt_template_version": prompt_template_version,
        "dimension": dimension,
        "binding": binding,
        "binding_sha256": None,
        "matched_files_sha256": matched_files_sha256,
        "base_sha": base_sha,
        "head_sha": head_sha,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(manifest_bytes)


def build_document(
    *,
    outcome: str,
    outcome_detail: str | None,
    verdict: str,
    summary: str | None,
    findings: list[dict],
    attacks: list[dict],
    applicability: str,
    applicability_reason: str,
    dimension: str,
    lens: str,
    binding: str | None,
    agent: str,
    posture: str | None,
    input_block: dict,
    invocation_block: dict,
) -> dict:
    """AD-6's document assembler. Field order is fixed (not
    `sort_keys=True`) so two documents diff readably; `main()` serialises
    with `json.dumps(doc, sort_keys=False)`.

    `outcome == "invocation_failed"` forces `verdict == "error"` at the call
    site (see `_verdict_for_outcome`), never here — this function assembles
    what it is given and asserts nothing about the relationship itself, so a
    caller bug can't silently launder an unenforced invariant through a
    default."""
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "reviewer": "claude",
        "lens": lens,
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "attacks": attacks,
        "outcome": outcome,
        "outcome_detail": outcome_detail,
        "applicability": applicability,
        "applicability_reason": applicability_reason,
        "dimension": dimension,
        "binding": binding,
        "agent": agent,
        "posture": posture,
        "input": input_block,
        "invocation": invocation_block,
        "observability": {
            "token_tracker_recorded": False,
            "audit_record": None,
        },
    }


def _verdict_for_outcome(outcome: str, payload_verdict: str | None) -> str:
    """AD-6's non-negotiable rule: `invocation_failed` always forces
    `verdict: "error"`, whatever the agent said. Verified downstream by
    `validation_logic.compute_verdict`'s #670 error-block path (W2's T2.6,
    not this module's own test obligation, but the rule is enforced here
    regardless)."""
    if outcome == "invocation_failed":
        return "error"
    return payload_verdict or "error"


def _ad_hoc_applicability_reason(binding: str | None) -> str:
    """§4.2: `applicability_reason` is mandatory and non-empty. For an
    ad-hoc call (no binding — W1 has no registry) L2 supplies a fixed
    reason; a binding-driven call's reason is the registry's, not ours to
    invent (owned by W7)."""
    if binding:
        return "matched by binding"
    return "invoked directly (no binding)"


# ---------------------------------------------------------------------------
# CLI surface (§3.2)
# ---------------------------------------------------------------------------

# Flags that must never be defined on the parser at all (§3.2): a caller who
# passes one is told which forbidden flag they used, via parse_known_args'
# leftover list, rather than argparse silently accepting it.
_FORBIDDEN_FLAGS = {
    "--agents": "inline agent definitions are forbidden through this surface (AD-3)",
    "--permission-mode": "permission mode comes from the posture, never the caller (AD-7)",
    "--output-format": "output format is always json and is set by this CLI (AD-4)",
    "--allowed-tools": "tool lists come from the posture (AD-7)",
    "--disallowed-tools": "tool lists come from the posture (AD-7)",
    "--tools": "tool lists come from the posture (AD-7)",
    "--dangerously-skip-permissions": (
        "bypass permissions is never allowed through this surface (AD-7)"
    ),
    "--allow-dangerously-skip-permissions": (
        "bypass permissions is never allowed through this surface (AD-7)"
    ),
    "--settings": "settings come from the posture, never the caller (AD-7)",
}


class _SilentArgumentParser(argparse.ArgumentParser):
    """argparse's default `error()` prints a usage block AND an error line
    then calls `sys.exit(2)` — two stderr lines and an exit path main() does
    not own. Exit-code table (§3.3) promises exactly one stderr line for a
    usage error; this override raises `_UsageError` directly so `main()`
    stays the sole author of both the exit code and the stderr text."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _SilentArgumentParser(prog="agent_invoke_cli.py", add_help=False)
    parser.add_argument("--agent")
    parser.add_argument("--input-file")
    parser.add_argument("--posture")
    parser.add_argument("--dimension", default="ad-hoc")
    parser.add_argument("--binding", default=None)
    parser.add_argument("--lens", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--grace", type=int, default=DEFAULT_GRACE_S)
    parser.add_argument("--model", default=None)
    parser.add_argument("--step", default=None)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--base-sha", default=None)
    parser.add_argument("--matched-file", action="append", default=None)
    parser.add_argument("--prompt-template-version", default=None)
    parser.add_argument("--output-file", default=None)
    parser.add_argument("--not-applicable", default=None)
    parser.add_argument("--require-env-auth", action="store_true")
    return parser


def _check_forbidden_and_unknown(extras: list[str]) -> None:
    for token in extras:
        if not token.startswith("--"):
            continue
        name = token.split("=", 1)[0]
        if name in _FORBIDDEN_FLAGS:
            raise _UsageError(f"forbidden flag {name}: {_FORBIDDEN_FLAGS[name]}")
    if extras:
        raise _UsageError(f"unrecognized arguments: {' '.join(extras)}")


# ---------------------------------------------------------------------------
# Launch-argv construction (§3.5)
# ---------------------------------------------------------------------------


def _build_claude_argv(
    *,
    agent: str,
    posture: Posture,
    model: str | None,
) -> list[str]:
    return [
        "claude",
        "--print",
        "--output-format",
        "json",
        "--agent",
        agent,
        "--settings",
        str(posture.settings_path.resolve()),
        "--permission-mode",
        posture.permission_mode,
        "--permission-prompts",
        "none",
        "--allowed-tools",
        " ".join(posture.allowed_tools),
        "--disallowed-tools",
        " ".join(posture.disallowed_tools),
        "--exclude-dynamic-system-prompt-sections",
        "--no-session-persistence",
        *(["--model", model] if model else []),
    ]


def _capture_cli_version() -> str | None:
    """ADR-1643 §9.2(c): captured per invocation, diagnostic only — never a
    decision input. Never gates, never pins a supported version."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.decode("utf-8", errors="replace").strip()
    return text or None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
    """Parse argv, run every precondition (§3.4), launch and classify at most
    one `claude` invocation, print exactly one JSON document to stdout, and
    return the exit code. Never calls sys.exit itself except through the
    final `if __name__ == "__main__"` line.

    `repo_root` is a test-only injection point: `argparse` never defines it
    and the `__main__` block never populates it from `sys.argv`.
    """
    resolved_root = Path(repo_root).resolve() if repo_root is not None else _DEFAULT_REPO_ROOT
    real_argv = sys.argv[1:] if argv is None else list(argv)

    try:
        return _main_impl(real_argv, resolved_root)
    except _UsageError as exc:
        print(f"agent_invoke: {exc}", file=sys.stderr)
        return 2
    except _OperationalError as exc:
        print(f"agent_invoke: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — top-level catch is exit 1's stated cause
        print(f"agent_invoke: unhandled error: {exc}", file=sys.stderr)
        return 1


def _validate_and_normalize_args(args: argparse.Namespace) -> None:
    """Pure flag-shape/flag-combination usage checks: independent of
    repo/environment state, so checked before the P1-P8 sequence begins
    rather than interleaved with it. (Suggestion 3 of the W1 fix pass.)"""
    if args.not_applicable is not None and args.input_file is not None:
        raise _UsageError("--not-applicable may not be combined with --input-file")
    if not (MIN_TIMEOUT_S <= args.timeout <= MAX_TIMEOUT_S):
        raise _UsageError(
            f"--timeout must be between {MIN_TIMEOUT_S} and {MAX_TIMEOUT_S}, got: {args.timeout}"
        )
    if not (MIN_GRACE_S <= args.grace <= MAX_GRACE_S):
        raise _UsageError(
            f"--grace must be between {MIN_GRACE_S} and {MAX_GRACE_S}, got: {args.grace}"
        )


def _build_input_block(
    args: argparse.Namespace,
    *,
    agent_ref: AgentRef,
    posture: Posture,
    matched_files: list[str],
    matched_files_sha256: str | None,
    input_file_sha256: str,
    dimension: str,
) -> dict:
    """The `input{}` block for a completed/failed (post-launch) document.
    Extracted from `_main_impl` (suggestion 3 of the W1 fix pass) purely to
    shrink that function; the fields and their source are unchanged."""
    input_digest = compute_input_digest(
        agent=args.agent,
        agent_file_sha256=agent_ref.sha256,
        posture_id=posture.id,
        posture_sha256=posture.sha256,
        input_file_sha256=input_file_sha256,
        prompt_template_version=args.prompt_template_version,
        dimension=dimension,
        binding=args.binding,
        matched_files_sha256=matched_files_sha256,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
    )
    return {
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "predicate_matched_files": matched_files,
        "input_file_sha256": input_file_sha256,
        "agent_file_sha256": agent_ref.sha256,
        "posture_sha256": posture.sha256,
        "prompt_template_version": args.prompt_template_version,
        "matched_files_sha256": matched_files_sha256,
        "input_digest": input_digest,
    }


def _build_invocation_block(
    args: argparse.Namespace,
    *,
    started_at: str,
    ended_at: str,
    proc: ProcResult,
    cli_version: str | None,
    classification: Classification,
    model_value: str | None,
    model_source: str,
) -> dict:
    """The `invocation{}` block for a completed/failed (post-launch)
    document. Extracted from `_main_impl` (suggestion 3 of the W1 fix pass)
    purely to shrink that function; the fields and their source are
    unchanged."""
    envelope = classification.envelope or {}
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": proc.duration_ms,
        "timeout_seconds": args.timeout,
        "timed_out": proc.timed_out,
        "exit_code": proc.rc,
        "model": model_value,
        "model_source": model_source,
        "cli_version": cli_version,
        "num_turns": envelope.get("num_turns"),
        "session_id": envelope.get("session_id"),
        "usage": envelope.get("usage"),
        "model_usage": envelope.get("modelUsage"),
        "total_cost_usd": envelope.get("total_cost_usd"),
        "envelope": classification.envelope,
        "envelope_unknown_fields": classification.envelope_unknown_fields,
        "stdout_partial": (
            proc.stdout_partial[:_STDOUT_PARTIAL_CAP].decode("utf-8", errors="replace")
            if proc.stdout_partial
            else None
        ),
        "stderr_tail": (
            proc.stderr_bytes[-_STDERR_TAIL_CAP:].decode("utf-8", errors="replace")
            if proc.stderr_bytes
            else None
        ),
    }


def _main_impl(real_argv: list[str], resolved_root: Path) -> int:
    parser = _build_parser()
    # argparse's own type coercion (e.g. non-integer --timeout) calls
    # parser.error(), which _SilentArgumentParser raises as _UsageError
    # directly rather than printing and calling sys.exit — main() stays the
    # sole author of the exit code and the stderr text.
    args, extras = parser.parse_known_args(real_argv)
    _check_forbidden_and_unknown(extras)
    _validate_and_normalize_args(args)

    not_applicable_reason: str | None = args.not_applicable
    dimension = args.dimension
    lens = args.lens or dimension
    matched_files = list(args.matched_file) if args.matched_file else []

    # ------------------------------------------------------------------
    # TD §3.4's P1-P8, kept together in one visible sequence on purpose:
    # fragmenting this into per-precondition functions would cost the
    # auditability of the ordering itself, which is the point of writing
    # it as an ordered table in the first place (risk-assessor inspection
    # item #3; code-reviewer suggestion 3 explicitly asked this stay whole).
    #
    # Ordering ruling (risk-assessor inspection item #3, checklist row 1):
    # the compound case of a caller passing a nonexistent --agent AND
    # omitting --posture now resolves to the P3/P4 agent_unavailable
    # DOCUMENT, not a bare exit-2 usage error, because the --posture/
    # --input-file "required unless --not-applicable" checks are placed
    # AFTER P3/P4 below, not before. This is a deliberate move, not the
    # order this module shipped with initially: TD §3.4 states P3/P4 before
    # P5/P6 explicitly, and §3.3's "a silence is never a result" reasoning
    # for why a missing agent file gets a document rather than an exit code
    # applies with the same force whether the *other* thing wrong with the
    # invocation is an environment state or a caller typo — the caller
    # learns about the agent problem either way, from a document, not a
    # bare stderr line that never mentions it. Pinned by
    # test_compound_agent_unavailable_takes_priority_over_missing_posture
    # (tests/automation/test_agent_invoke_cli.py). Flagged for
    # technical-design's correction pass: TD §3.4 does not currently state
    # where the --posture/--input-file "required" checks sit relative to
    # P3/P4; this resolves that gap in the same direction the table's own
    # P3-before-P5 ordering already points.
    # ------------------------------------------------------------------

    # P1 — repo root must resolve before anything else.
    if not (resolved_root / ".claude" / "agents").is_dir():
        raise _OperationalError(f"repo root unresolvable: {resolved_root}")

    # P2 — agent name grammar.
    if not args.agent:
        raise _UsageError("--agent is required")
    if not AGENT_NAME_RE.match(args.agent):
        raise _UsageError(f"--agent must match ^[a-z][a-z0-9-]*$, got: {args.agent!r}")

    # P3/P4 — agent resolution. Required in every path, including
    # --not-applicable (§4.5: the full input block, including the agent's
    # digest, is still computed for a not_applicable record).
    try:
        agent_ref = resolve_agent(resolved_root, args.agent)
    except _PreflightFailure as failure:
        return _emit_preflight_document(
            failure.detail,
            args=args,
            dimension=dimension,
            lens=lens,
            matched_files=matched_files,
            agent_file_sha256=None,
        )

    if not_applicable_reason is not None:
        return _emit_not_applicable(
            not_applicable_reason,
            args=args,
            dimension=dimension,
            lens=lens,
            matched_files=matched_files,
            agent_ref=agent_ref,
            repo_root=resolved_root,
        )

    # --posture/--input-file are REQUIRED unless --not-applicable (§3.2).
    # Checked here, after P3/P4 — see the ordering ruling above.
    if not args.posture:
        raise _UsageError("--posture is required unless --not-applicable is given")
    if not POSTURE_NAME_RE.match(args.posture):
        raise _UsageError(f"--posture must match ^[a-z][a-z0-9-]*$, got: {args.posture!r}")
    if not args.input_file:
        raise _UsageError("--input-file is required unless --not-applicable is given")

    # P5 — posture.
    try:
        posture = load_posture(resolved_root, args.posture)
    except _PreflightFailure as failure:
        return _emit_preflight_document(
            failure.detail,
            args=args,
            dimension=dimension,
            lens=lens,
            matched_files=matched_files,
            agent_file_sha256=agent_ref.sha256,
        )

    # P6 — input file.
    input_path = Path(args.input_file)
    if not input_path.is_file():
        raise _UsageError(f"--input-file not found: {args.input_file}")
    input_bytes = input_path.read_bytes()
    if not input_bytes:
        raise _UsageError(f"--input-file is empty: {args.input_file}")
    try:
        input_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise _UsageError(f"--input-file is not valid UTF-8: {args.input_file}")

    # P7 — auth pre-flight, opt-in (ADR-1643 §9.3: mandatory for
    # non-interactive callers, enforced by convention at the call site, not
    # by this module, which cannot see who is calling it).
    if args.require_env_auth:
        if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
            return _emit_preflight_document(
                "not_authenticated",
                args=args,
                dimension=dimension,
                lens=lens,
                matched_files=matched_files,
                agent_file_sha256=agent_ref.sha256,
                posture=posture,
            )

    # P8 — the CLI itself must resolve.
    if shutil.which("claude") is None:
        return _emit_preflight_document(
            "cli_unavailable",
            args=args,
            dimension=dimension,
            lens=lens,
            matched_files=matched_files,
            agent_file_sha256=agent_ref.sha256,
            posture=posture,
        )

    # ------------------------------------------------------------------
    # Launch, classify, assemble, emit.
    # ------------------------------------------------------------------
    started_at = _now_iso()
    claude_argv = _build_claude_argv(agent=args.agent, posture=posture, model=args.model)
    proc = run_capped(
        claude_argv,
        stdin_bytes=input_bytes,
        cwd=resolved_root,
        timeout_s=args.timeout,
        grace_s=args.grace,
    )
    ended_at = _now_iso()
    cli_version = _capture_cli_version()

    classification = classify(proc)

    if classification.outcome_detail == "usage_limit":
        # ADR-1643 §9.3/TD §5.3: the phrase is chosen to match
        # bin/hos-cron's live grep verbatim so a caller that tees this
        # stderr into its own capture gets detection for free.
        print(
            f"agent_invoke: usage limit reached — nested invocation of agent "
            f"'{args.agent}' stopped (terminal_reason=usage_limit)",
            file=sys.stderr,
        )

    input_file_sha256 = _sha256_bytes(input_bytes)
    matched_files_sha256 = _matched_files_digest(resolved_root, matched_files)
    input_block = _build_input_block(
        args,
        agent_ref=agent_ref,
        posture=posture,
        matched_files=matched_files,
        matched_files_sha256=matched_files_sha256,
        input_file_sha256=input_file_sha256,
        dimension=dimension,
    )

    payload = classification.payload or {}
    verdict = _verdict_for_outcome(classification.outcome, payload.get("verdict"))
    model_source = "cli_override" if args.model else "agent_frontmatter"
    model_value = args.model if args.model else _agent_frontmatter_model(agent_ref.bytes_)
    invocation_block = _build_invocation_block(
        args,
        started_at=started_at,
        ended_at=ended_at,
        proc=proc,
        cli_version=cli_version,
        classification=classification,
        model_value=model_value,
        model_source=model_source,
    )

    doc = build_document(
        outcome=classification.outcome,
        outcome_detail=classification.outcome_detail,
        verdict=verdict,
        summary=payload.get("summary"),
        findings=payload.get("findings", []),
        attacks=payload.get("attacks", []),
        applicability="applicable",
        applicability_reason=_ad_hoc_applicability_reason(args.binding),
        dimension=dimension,
        lens=lens,
        binding=args.binding,
        agent=args.agent,
        posture=posture.id,
        input_block=input_block,
        invocation_block=invocation_block,
    )
    return _emit(doc, args.output_file)


def _agent_frontmatter_model(agent_bytes: bytes) -> str | None:
    frontmatter = _parse_frontmatter(agent_bytes)
    if not frontmatter:
        return None
    value = frontmatter.get("model")
    return value if isinstance(value, str) else None


def _emit(doc: dict, output_file: str | None) -> int:
    """TD-D2: stdout is authoritative; `--output-file`, when given, receives
    the byte-identical content — one producer, one serialisation, the file
    is a copy, never a second rendering. `print(text)` would append its own
    `\\n`, independently of whatever `write_bytes` below wrote, so the same
    `payload` bytes are used for both destinations rather than re-deriving
    the trailing newline twice."""
    payload = (json.dumps(doc, sort_keys=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(payload)
    sys.stdout.flush()
    if output_file:
        try:
            Path(output_file).write_bytes(payload)
        except OSError as exc:
            raise _OperationalError(f"--output-file unwritable: {exc}")
    return 0


def _emit_preflight_document(
    detail: str,
    *,
    args: argparse.Namespace,
    dimension: str,
    lens: str,
    matched_files: list[str],
    agent_file_sha256: str | None,
    posture: Posture | None = None,
) -> int:
    """A precondition failed before any process was launched (P3/P4, P5, P7,
    P8). Emits a full `invocation_failed` document — never a silent exit —
    with as much of the input block populated as is knowable at this point."""
    input_file_sha256 = None
    if args.input_file:
        input_path = Path(args.input_file)
        if input_path.is_file():
            try:
                input_file_sha256 = _sha256_bytes(input_path.read_bytes())
            except OSError:
                input_file_sha256 = None

    posture_sha256 = posture.sha256 if posture else None
    posture_id = posture.id if posture else args.posture

    input_digest = compute_input_digest(
        agent=args.agent,
        agent_file_sha256=agent_file_sha256,
        posture_id=posture_id,
        posture_sha256=posture_sha256,
        input_file_sha256=input_file_sha256,
        prompt_template_version=args.prompt_template_version,
        dimension=dimension,
        binding=args.binding,
        matched_files_sha256=None,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
    )
    input_block = {
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "predicate_matched_files": matched_files,
        "input_file_sha256": input_file_sha256,
        "agent_file_sha256": agent_file_sha256,
        "posture_sha256": posture_sha256,
        "prompt_template_version": args.prompt_template_version,
        "matched_files_sha256": None,
        "input_digest": input_digest,
    }
    invocation_block = {
        "started_at": _now_iso(),
        "ended_at": _now_iso(),
        "duration_ms": 0,
        "timeout_seconds": args.timeout,
        "timed_out": False,
        "exit_code": None,
        "model": None,
        "model_source": None,
        "cli_version": None,
        "num_turns": None,
        "session_id": None,
        "usage": None,
        "model_usage": None,
        "total_cost_usd": None,
        "envelope": None,
        "envelope_unknown_fields": [],
        "stdout_partial": None,
        "stderr_tail": None,
    }
    doc = build_document(
        outcome="invocation_failed",
        outcome_detail=detail,
        verdict="error",
        summary=None,
        findings=[],
        attacks=[],
        applicability="applicable",
        applicability_reason=_ad_hoc_applicability_reason(args.binding),
        dimension=dimension,
        lens=lens,
        binding=args.binding,
        agent=args.agent,
        posture=posture_id,
        input_block=input_block,
        invocation_block=invocation_block,
    )
    return _emit(doc, args.output_file)


def _emit_not_applicable(
    reason: str,
    *,
    args: argparse.Namespace,
    dimension: str,
    lens: str,
    matched_files: list[str],
    agent_ref: AgentRef,
    repo_root: Path,
) -> int:
    """§4.5 — `--not-applicable` launches no process at all. The record is
    written and stored like any other: this closes AF-8's SKIP-as-exit-0
    fail-open by construction (a `not_applicable` record is never
    byte-identical to a `completed` one — they differ in `applicability`,
    `applicability_reason`, and `invocation.*`)."""
    matched_files_sha256 = _matched_files_digest(repo_root, matched_files)
    input_digest = compute_input_digest(
        agent=args.agent,
        agent_file_sha256=agent_ref.sha256,
        posture_id=None,
        posture_sha256=None,
        input_file_sha256=None,
        prompt_template_version=args.prompt_template_version,
        dimension=dimension,
        binding=args.binding,
        matched_files_sha256=matched_files_sha256,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
    )
    input_block = {
        "head_sha": args.head_sha,
        "base_sha": args.base_sha,
        "predicate_matched_files": matched_files,
        "input_file_sha256": None,
        "agent_file_sha256": agent_ref.sha256,
        "posture_sha256": None,
        "prompt_template_version": args.prompt_template_version,
        "matched_files_sha256": matched_files_sha256,
        "input_digest": input_digest,
    }
    invocation_block = {
        "started_at": _now_iso(),
        "ended_at": _now_iso(),
        "duration_ms": 0,
        "timeout_seconds": args.timeout,
        "timed_out": False,
        "exit_code": None,
        "model": None,
        "model_source": None,
        "cli_version": None,
        "num_turns": None,
        "session_id": None,
        "usage": None,
        "model_usage": None,
        "total_cost_usd": None,
        "envelope": None,
        "envelope_unknown_fields": [],
        "stdout_partial": None,
        "stderr_tail": None,
    }
    doc = build_document(
        outcome="completed",
        outcome_detail=None,
        verdict="approve",
        summary=None,
        findings=[],
        attacks=[],
        applicability="not_applicable",
        applicability_reason=reason,
        dimension=dimension,
        lens=lens,
        binding=args.binding,
        agent=args.agent,
        posture=None,
        input_block=input_block,
        invocation_block=invocation_block,
    )
    return _emit(doc, args.output_file)


if __name__ == "__main__":
    sys.exit(main())
