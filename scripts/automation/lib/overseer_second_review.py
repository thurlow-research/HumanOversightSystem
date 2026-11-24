"""overseer_second_review.py — the overseer's own cross-vendor second review per PR head (#2357, ADR-2357).

For one open PR, this module resolves the head and base, derives the review tier from
git objects (never from PR text), reuses a stored result when one exists for that exact
head, and otherwise runs `scripts/run_second_review.sh --authority` from the trusted main
checkout. It classifies the report into one closed result, writes the overseer-owned
record under `.claudetmp/overseer-authority/second-review/`, and prints one JSON line.

It has no GitHub write side effects: it never posts, labels, merges or creates issues.
All vendor text is untrusted data; the only text that leaves this module is
code-templated, sanitised and size-bounded (TD-2357-S1a section 6).

CLI:
    python3 -m scripts.automation.lib.overseer_second_review run --pr <N> [--cache-only]
    python3 -m scripts.automation.lib.overseer_second_review mark-hold-label \
        --pr <N> --head <sha40> --applied true|false
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Optional, Sequence

from scripts.automation.lib import github, merge_authority, merge_config
from scripts.oversight import second_review_logic, validation_logic
from scripts.oversight.lib import audit_log

# --------------------------------------------------------------------------- #
# Constants                                                                   #
# --------------------------------------------------------------------------- #
SCHEMA = 1
CHECK = "second-review"
LOCK_NAMESPACE = "osr"
STATE_SUBDIR = (".claudetmp", "overseer-authority", "second-review")
OSR_LOCK_TIMEOUT_SECONDS = 60.0
PENDING_STUCK_AT = 3
SR_ENTRY_CAP = 40
DETAIL_MAX_CHARS = 2000
FINDINGS_FILE_BUDGET_BYTES = 200_000
RECORD_MAX_BYTES = 1_048_576
REPORT_MAX_BYTES = 8 * 1024 * 1024
GIT_TIMEOUT = 60
FETCH_TIMEOUT = 300
CLASSIFIER_TIMEOUT = 120
REVIEW_TIMEOUT: Optional[float] = 3600.0
HELD_LABELS = frozenset({"needs-human", "hos-halt"})
TIERS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
VENDORS = ("agy", "codex")
VENDORSETS = ("none", "agy", "agy+codex")
MAX_PR_NUMBER = 9_999_999
COUNTER_LOCK_TIMEOUT_SECONDS = 10.0
CHECK_MARKER_PREFIX = "<!-- hos-overseer-check"
FINAL_REASON_FOR_VERDICT = {
    "approve": "ok",
    "request_changes": "findings",
    "not-required": "tier-below-medium",
}
# The closed key set of every result line (TD-2357-S1a 5.8, plus the S1b pending-counter keys).
RESULT_KEYS = frozenset(
    {
        "check",
        "schema",
        "pr",
        "head_sha",
        "base_sha",
        "range",
        "tier",
        "vendors",
        "verdict",
        "status",
        "reason",
        "reused",
        "findings_file",
        "record",
        "hold_label_applied",
        "pending_count",
        "pending_last_reason",
    }
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REASON_RE = re.compile(r"^[a-z0-9:-]{1,64}$")
_INT_FIELD_RE = re.compile(r"^[0-9]{1,7}$")
_HEADER_LINE_RE = re.compile(r"^([a-z_]+): (.*)$")
_AI_RISK_RE = re.compile(r"^AI-Risk:[ \t]*(LOW|MEDIUM|HIGH|CRITICAL)\b", re.I | re.M)

_VENDOR_HOLD_TOKENS = (
    "vendor-unavailable",
    "vendor-error",
    "vendor-timeout",
    "vendor-missing",
    "prompt-not-consumed",
)
HOLD_REASONS = frozenset(
    {f"{token}:{vendor}" for token in _VENDOR_HOLD_TOKENS for vendor in VENDORS}
    | {
        "unparseable",
        "diff-too-large",
        "empty-diff",
        "review-inconsistent",
        "pending-stuck",
        "binary-unreviewed",
    }
)
# A re-run on the same head and base cannot change these and would cost a full vendor call.
DETERMINISTIC_HOLDS = frozenset({"binary-unreviewed"})
PENDING_COUNTED = frozenset(
    {"fetch-failed", "base-unresolved", "lock-unavailable", "review-failed", "diff-failed"}
)
PENDING_UNCOUNTED = frozenset(
    {
        "untrusted-checkout",
        "budget",
        "head-moved",
        "lock-busy",
        "pr-not-found",
        "pr-not-open",
        "github-error",
        "config-error",
        "state-write-failed",
    }
)

KeyedLockTimeout = merge_authority.KeyedLockTimeout
KeyedLockUnavailable = merge_authority.KeyedLockUnavailable


# --------------------------------------------------------------------------- #
# Injection seams                                                             #
# --------------------------------------------------------------------------- #
class CmdResult(NamedTuple):
    rc: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Config:
    repo_root: Path  # trusted checkout; state root; cwd of every subprocess
    tools_root: Path  # where scripts/ is read from
    repo_slug: Optional[str] = None  # None -> merge_config.resolve_repo_slug(repo_root)
    lock_timeout: float = OSR_LOCK_TIMEOUT_SECONDS


@dataclass(frozen=True)
class Deps:
    get_pull: Callable[[str, str, int], Optional[dict]]
    run_cmd: Callable[
        [Sequence[str], Path, Optional[float], Optional[Mapping[str, str]]], CmdResult
    ]
    now: Callable[[], datetime]
    write_audit: Callable[[dict, Path], None]


def _default_run_cmd(
    argv: Sequence[str],
    cwd: Path,
    timeout: Optional[float],
    env: Optional[Mapping[str, str]],
) -> CmdResult:
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=None if env is None else dict(env),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return CmdResult(124, "", "timeout")
    except OSError as exc:
        return CmdResult(127, "", str(exc))
    return CmdResult(proc.returncode, proc.stdout, proc.stderr)


def _default_write_audit(event: dict, path: Path) -> None:
    audit_log.write_event(event, root=str(path))


def default_config() -> Config:
    root = Path(__file__).resolve().parents[3]
    return Config(repo_root=root, tools_root=root)


def default_deps() -> Deps:
    return Deps(
        get_pull=github.get_pull,
        run_cmd=_default_run_cmd,
        now=lambda: datetime.now(timezone.utc),
        write_audit=_default_write_audit,
    )


def _log(message: str) -> None:
    print(f"overseer_second_review: {message}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# State layout, locks, atomic writes                                          #
# --------------------------------------------------------------------------- #
def state_dir(repo_root: Path) -> Path:
    return Path(repo_root).joinpath(*STATE_SUBDIR)


def records_dir(repo_root: Path) -> Path:
    return state_dir(repo_root) / "records"


def runs_dir(repo_root: Path) -> Path:
    return state_dir(repo_root) / "runs"


def _record_path(repo_root: Path, pr: int, head: str, vendorset: str) -> Path:
    return records_dir(repo_root) / f"pr{pr}-{head}-{vendorset}.json"


def _pending_path(repo_root: Path, pr: int, head: str) -> Path:
    return records_dir(repo_root) / f"pr{pr}-{head}-pending.json"


def _raise_path(repo_root: Path, pr: int, head: str) -> Path:
    return records_dir(repo_root) / f"pr{pr}-{head}-raise.json"


def head_lock(repo_root: Path, slug: str, pr: int, head: str, timeout: float):
    """One lock per (repo, PR, head): serializes every writer of that head's files (A6)."""
    return merge_authority.keyed_flock(
        LOCK_NAMESPACE,
        f"{slug}\0pr{pr}\0{head}",
        subject=f"pr{pr}@{head[:12]}",
        repo_root=str(repo_root),
        timeout=timeout,
    )


def _sweep_stale_tmp(directory: Path) -> None:
    """Best-effort removal of abandoned `.tmp-*` files older than an hour."""
    cutoff = time.time() - 3600
    try:
        for entry in directory.glob(".tmp-*"):
            with contextlib.suppress(OSError):
                if entry.lstat().st_mtime < cutoff:
                    entry.unlink()
    except OSError:
        pass


def _private_dir_ok(path: Path) -> bool:
    """A real directory (not a symlink) owned by this uid with no group or other access."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(st.st_mode)
        and not stat.S_ISLNK(st.st_mode)
        and st.st_uid == os.geteuid()
        and st.st_mode & 0o077 == 0
    )


def _ensure_private_dir(path: Path) -> None:
    """Create `path` if needed and refuse to write into one that is not private (AR10)."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _private_dir_ok(path):
        raise OSError(f"{path.name} directory is not private")


def _atomic_write_text(path: Path, text: str) -> None:
    parent = path.parent
    _ensure_private_dir(parent)
    _sweep_stale_tmp(parent)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _atomic_write_json(path: Path, obj: Any) -> None:
    _atomic_write_text(path, json.dumps(obj, sort_keys=True, indent=2) + "\n")


_ABSENT = object()


def _read_json_dict(path: Path, max_bytes: int, *, private: bool = False) -> Any:
    """The parsed dict, `_ABSENT` when the file does not exist, else None (invalid).

    Refuses symlinks, non-regular files and anything over `max_bytes`. With `private`, also
    refuses a file this uid does not own or that grants group or other access (TD 7.1)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return _ABSENT
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            return None
        if private and (st.st_uid != os.geteuid() or st.st_mode & 0o077):
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(max_bytes + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError is a ValueError
        return None
    return obj if isinstance(obj, dict) else None


def _is_int(value: Any, expected: Optional[int] = None) -> bool:
    return type(value) is int and (expected is None or value == expected)


# --------------------------------------------------------------------------- #
# Vendor sets                                                                 #
# --------------------------------------------------------------------------- #
def required_vendorset(tier: str) -> str:
    """The vendors a tier requires, from the same table and inert thresholds as the shell."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier!r}")
    run_agy, run_codex = second_review_logic.select_reviewers(0.0, tier, 1.0, 1.0)
    if run_codex and not run_agy:
        raise ValueError("codex without agy is not a valid vendor set")
    if run_agy and run_codex:
        return "agy+codex"
    return "agy" if run_agy else "none"


def vendors_list(vendorset: str) -> list[str]:
    if vendorset == "none":
        return []
    if vendorset == "agy":
        return ["agy"]
    if vendorset == "agy+codex":
        return ["agy", "codex"]
    raise ValueError(f"unknown vendor set: {vendorset!r}")


def _vendorset_of(vendors: Sequence[str]) -> str:
    return "+".join(vendors) if vendors else "none"


# --------------------------------------------------------------------------- #
# Reading records                                                             #
# --------------------------------------------------------------------------- #
def _findings_shape_ok(path: Path, head: str, runs: Path) -> bool:
    if not (_private_dir_ok(runs) and _private_dir_ok(path.parent)):
        return False
    data = _read_json_dict(path, merge_authority.FINDINGS_FILE_MAX_BYTES, private=True)
    if data is None or data is _ABSENT:
        return False
    return (
        set(data) == {"findings", "reviewed_head"}
        and data["reviewed_head"] == head
        and isinstance(data["findings"], list)
        and len(data["findings"]) > 0
    )


def _created_at_ok(value: Any) -> bool:
    if not (isinstance(value, str) and _CREATED_AT_RE.match(value)):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _record_consistent(rec: dict, vendorset: str) -> bool:
    """The self-consistency rules of TD-2357-S1b 7.2 (the schema and key checks come first)."""
    status, verdict, reason, tier = (rec.get(k) for k in ("status", "verdict", "reason", "tier"))
    if not _created_at_ok(rec.get("created_at")):
        return False
    if tier is None:
        if not (status == "hold" and reason == "pending-stuck"):
            return False
    elif tier not in TIERS or rec.get("vendors_required") != vendors_list(required_vendorset(tier)):
        return False
    hold_label = rec.get("hold_label_applied")
    if status == "hold":
        return type(hold_label) is bool
    if (
        hold_label is not None
        or not isinstance(verdict, str)
        or reason != FINAL_REASON_FOR_VERDICT.get(verdict)
    ):
        return False
    required, ran = rec["vendors_required"], rec.get("vendors_run")
    if verdict == "not-required":
        return ran == []
    if verdict == "approve":
        return ran == required
    # A mixed result omits the vendor that failed (ADR A2), so only a subset is required.
    return (
        isinstance(ran, list)
        and len(ran) > 0
        and all(isinstance(v, str) for v in ran)
        and [v for v in required if v in ran] == ran
    )


def load_record(
    repo_root: Path,
    *,
    repo: str,
    pr: int,
    head_sha: str,
    base_sha: Optional[str] = None,
    vendorset: str,
) -> Optional[dict]:
    """A valid record for the key, or None meaning "treat as absent"."""
    if not _private_dir_ok(records_dir(repo_root)):
        return None
    rec = _read_json_dict(
        _record_path(repo_root, pr, head_sha, vendorset), RECORD_MAX_BYTES, private=True
    )
    if rec is None or rec is _ABSENT:
        return None
    if not (
        _is_int(rec.get("schema"), SCHEMA)
        and rec.get("check") == CHECK
        and rec.get("repo") == repo
        and _is_int(rec.get("pr"), pr)
        and rec.get("head_sha") == head_sha
    ):
        return None
    if base_sha is not None and rec.get("base_sha") != base_sha:
        return None
    if rec.get("vendors_required") != vendors_list(vendorset):
        return None
    failures = rec.get("vendor_failures")
    if not isinstance(failures, list) or not all(
        isinstance(item, str) and item in HOLD_REASONS for item in failures
    ):
        return None
    status = rec.get("status")
    verdict = rec.get("verdict")
    if status == "final":
        if verdict not in ("approve", "request_changes", "not-required"):
            return None
        if verdict == "approve" and not (
            rec.get("vendors_run") == rec.get("vendors_required")
            and _is_int(rec.get("unresolved_findings"), 0)
            and _is_int(rec.get("files_reviewed"))
            and rec["files_reviewed"] >= 1
            and _is_int(rec.get("binary_files"), 0)
        ):
            return None
        if verdict == "request_changes":
            findings_file = rec.get("findings_file")
            if not isinstance(findings_file, str):
                return None
            candidate = Path(findings_file)
            runs = runs_dir(repo_root)
            if not candidate.is_absolute() or os.path.normpath(candidate) != str(candidate):
                return None
            if runs not in candidate.parents or not _findings_shape_ok(candidate, head_sha, runs):
                return None
    elif status == "hold":
        if verdict != "hold" or rec.get("reason") not in HOLD_REASONS:
            return None
    else:
        return None
    if not _record_consistent(rec, vendorset):
        return None
    return rec


def find_records(repo_root: Path, *, repo: str, pr: int, head_sha: str) -> list[dict]:
    """Every valid record for (repo, pr, head) across vendor sets, newest first."""
    found = []
    for vendorset in VENDORSETS:
        rec = load_record(repo_root, repo=repo, pr=pr, head_sha=head_sha, vendorset=vendorset)
        if rec is not None:
            found.append(rec)
    found.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return found


# --------------------------------------------------------------------------- #
# Raise file (written by S1b's approval gate)                                 #
# --------------------------------------------------------------------------- #
def _raise_valid(rec: Any, slug: str, pr: int, head: str) -> bool:
    return (
        isinstance(rec, dict)
        and _is_int(rec.get("schema"), SCHEMA)
        and rec.get("check") == CHECK
        and rec.get("repo") == slug
        and _is_int(rec.get("pr"), pr)
        and rec.get("head_sha") == head
        and rec.get("tier") in TIERS
    )


def write_raise(repo_root: Path, *, repo: str, pr: int, head_sha: str, tier: str) -> Path:
    """Record a tier raise for a head. A raise never lowers an existing raise."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier!r}")
    if not isinstance(head_sha, str) or not _HEX40.match(head_sha):
        raise ValueError("head_sha must be 40 lowercase hex characters")
    if not _is_int(pr) or not 1 <= pr <= MAX_PR_NUMBER:
        raise ValueError("pr out of range")
    path = _raise_path(repo_root, pr, head_sha)
    with head_lock(repo_root, repo, pr, head_sha, OSR_LOCK_TIMEOUT_SECONDS):
        existing = _read_json_dict(path, RECORD_MAX_BYTES)
        if _raise_valid(existing, repo, pr, head_sha):
            assert isinstance(existing, dict)
            if TIERS.index(existing["tier"]) >= TIERS.index(tier):
                return path
        _atomic_write_json(
            path,
            {
                "schema": SCHEMA,
                "check": CHECK,
                "repo": repo,
                "pr": pr,
                "head_sha": head_sha,
                "tier": tier,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
    return path


# --------------------------------------------------------------------------- #
# Tier                                                                        #
# --------------------------------------------------------------------------- #
def read_raise(repo_root: Path, *, slug: str, pr: int, head: str) -> tuple[Optional[str], bool]:
    """The only reader of the raise file: (tier, False) valid, (None, True) invalid, (None, False) absent."""
    raw = _read_json_dict(_raise_path(repo_root, pr, head), RECORD_MAX_BYTES, private=True)
    if raw is _ABSENT:
        return None, False
    if _raise_valid(raw, slug, pr, head):
        assert isinstance(raw, dict)
        return raw["tier"], False
    return None, True


def compute_tier(
    repo_root: Path,
    tools_root: Path,
    base: str,
    head: str,
    pr: int,
    slug: str,
    run_cmd: Callable[..., CmdResult],
) -> tuple[str, dict]:
    """max(floor, declared, raise). An input that cannot be determined counts as HIGH."""
    defaulted: list[str] = []

    floor: Optional[str] = None
    classifier = tools_root / "scripts/oversight/change_classifier.py"
    res = run_cmd(
        [sys.executable, str(classifier), "--tier-floor", "--base", base, "--head", head],
        repo_root,
        CLASSIFIER_TIMEOUT,
        None,
    )
    if res.rc == 0:
        try:
            parsed = json.loads(res.stdout)
            value = parsed.get("tier_floor") if isinstance(parsed, dict) else None
            if value in TIERS:
                floor = value
        except ValueError:
            pass
    if floor is None:
        defaulted.append("floor-error")

    declared: Optional[str] = None
    res = run_cmd(
        ["git", "-C", str(repo_root), "log", "--format=%B%x00", f"{base}..{head}"],
        repo_root,
        GIT_TIMEOUT,
        None,
    )
    if res.rc != 0:
        defaulted.append("git-error")
    else:
        found = [m.upper() for m in _AI_RISK_RE.findall(res.stdout)]
        if found:
            declared = max(found, key=TIERS.index)
        else:
            defaulted.append("declared-absent")

    raised, raise_invalid = read_raise(repo_root, slug=slug, pr=pr, head=head)
    effective = [floor or "HIGH", declared or "HIGH"]
    if raise_invalid:
        defaulted.append("raise-invalid")
        effective.append("HIGH")
    elif raised is not None:
        effective.append(raised)
    tier = max(effective, key=TIERS.index)
    return tier, {"floor": floor, "declared": declared, "raise": raised, "defaulted": defaulted}


# --------------------------------------------------------------------------- #
# Sanitising and findings                                                     #
# --------------------------------------------------------------------------- #
def sanitize(text: Any) -> str:
    """One-line, bounded, marker-free text from untrusted vendor output (TD section 6.2)."""
    if not isinstance(text, str):
        return ""
    chars = []
    for ch in text:
        category = unicodedata.category(ch)
        if category in ("Cc", "Zl", "Zp"):
            chars.append(" ")
        elif category != "Cf":
            chars.append(ch)
    cleaned = " ".join("".join(chars).split())
    while True:
        stripped = re.sub(r"^/hos", "", cleaned, flags=re.I).lstrip()
        if stripped == cleaned:
            break
        cleaned = stripped
    while True:
        replaced = cleaned.replace("<!--", "<! --").replace("-->", "-- >")
        if replaced == cleaned:
            break
        cleaned = replaced
    # GitHub renders these in the bounce comment: defang mentions and link/image syntax.
    cleaned = re.sub(r"@(?=[A-Za-z0-9_-])", "@\u200d", cleaned)
    cleaned = cleaned.replace("](", "]\u200d(").replace("![", "!\u200d[")
    if len(cleaned) > DETAIL_MAX_CHARS:
        cleaned = cleaned[: DETAIL_MAX_CHARS - 1] + "…"
    return cleaned


_DETAIL_KEYS = ("finding", "why", "attack_scenario", "suggestion", "cwe", "line")
_SEVERITY_ORDER = {"critical": 0, "high": 1, "blocking": 2}
_TRAILING_POSITION_RE = re.compile(r":\d+(:\d+)?$")


def _detail_of(item: dict) -> str:
    parts = []
    for key in _DETAIL_KEYS:
        value = item.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        parts.append(f"{key}: {value}")
    return sanitize(" | ".join(parts))


def _path_of(item: dict, changed: set[str]) -> Optional[str]:
    candidate = item.get("file")
    if not isinstance(candidate, str):
        files = item.get("files")
        candidate = (
            next((f for f in files if isinstance(f, str)), None)
            if isinstance(files, list)
            else None
        )
    if candidate is None:
        return None
    candidate = unicodedata.normalize("NFC", candidate)
    if candidate.startswith("./"):
        candidate = candidate[2:]
    candidate = _TRAILING_POSITION_RE.sub("", candidate)
    return candidate if candidate in changed else None


def _fp8(item: dict) -> str:
    try:
        fingerprint = validation_logic.fingerprint(item)
    except Exception:  # noqa: BLE001 — a malformed vendor item must not crash the runner
        fingerprint = json.dumps(item, sort_keys=True, default=str)
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]


@dataclass
class _VendorStatus:
    vendor: str
    status: str  # approve | request_changes | failed | unparseable
    token: Optional[str] = None  # the hold reason token, for `failed`
    blocking: list = field(default_factory=list)  # [(severity, item)]
    verdict_entry: bool = False
    verdict_detail: str = ""

    @property
    def failure_token(self) -> Optional[str]:
        if self.status == "failed":
            return self.token
        if self.status == "unparseable":
            return "unparseable"
        return None


def build_entries(statuses: Sequence[_VendorStatus], changed: set[str]) -> list[dict]:
    """Deduplicated, capped `sr-` findings entries in vendor order (TD sections 6.1 and 6.3)."""
    entries: list[dict] = []
    for status in statuses:
        if status.status != "request_changes":
            continue
        vendor = status.vendor
        ordered = sorted(status.blocking, key=lambda pair: _SEVERITY_ORDER.get(pair[0], 3))
        for severity, item in ordered:
            entries.append(
                {
                    "class": "REVIEW_FINDING",
                    "slug": f"sr-{vendor}-{_fp8(item)}",
                    "summary": f"overseer second review ({vendor}): {severity} finding",
                    "detail": _detail_of(item),
                    "path": _path_of(item, changed),
                }
            )
        if status.verdict_entry:
            entries.append(
                {
                    "class": "REVIEW_FINDING",
                    "slug": f"sr-{vendor}-verdict",
                    "summary": (
                        f"overseer second review ({vendor}): request_changes with no "
                        "extractable blocking finding"
                    ),
                    "detail": sanitize(status.verdict_detail),
                    "path": None,
                }
            )

    kept: list[dict] = []
    index: dict[str, int] = {}
    dropped: dict[str, int] = {}
    for entry in entries:
        key = f"REVIEW_FINDING:{entry['path'] or '-'}:{entry['slug']}"
        if key in index:
            dropped[key] = dropped.get(key, 0) + 1
            continue
        index[key] = len(kept)
        kept.append(entry)
    for key, count in dropped.items():
        entry = kept[index[key]]
        entry["summary"] = f"{entry['summary']} (+{count} more with the same file and class)"

    if len(kept) > SR_ENTRY_CAP:
        keep = SR_ENTRY_CAP - 1
        overflow = len(kept) - keep
        kept = kept[:keep] + [
            {
                "class": "REVIEW_FINDING",
                "slug": "sr-overflow",
                "summary": f"overseer second review: {overflow} more blocking finding(s) not listed",
                "detail": "",
                "path": None,
            }
        ]
    return kept


def _serialize_findings(entries: list[dict], head: str) -> str:
    def dump(items: list[dict]) -> str:
        obj = {"findings": items, "reviewed_head": head}
        return json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n"

    text = dump(entries)
    if len(text.encode("utf-8")) <= FINDINGS_FILE_BUDGET_BYTES:
        return text
    trimmed = [
        {**e, "detail": e["detail"][:499] + "…" if len(e["detail"]) > 500 else e["detail"]}
        for e in entries
    ]
    text = dump(trimmed)
    if len(text.encode("utf-8")) <= FINDINGS_FILE_BUDGET_BYTES:
        return text
    return dump([{**e, "detail": ""} for e in entries])


class _FindingsInvalid(Exception):
    pass


def _validate_entries(entries: list[dict], changed: Sequence[str], slug: str) -> None:
    try:
        canonical, _ = merge_authority.canonicalize_findings_ex(
            {"findings": entries}, changed_paths=changed, head_check_runs=(), repo_slug=slug
        )
    except Exception as exc:  # noqa: BLE001 — any schema failure is a runner bug (TD 6.5)
        raise _FindingsInvalid(type(exc).__name__) from exc
    if len(canonical) != len(entries):
        raise _FindingsInvalid("entry-count-mismatch")


# --------------------------------------------------------------------------- #
# Classifying a run                                                           #
# --------------------------------------------------------------------------- #
@dataclass
class _Outcome:
    kind: str  # final | hold | pending
    verdict: str
    reason: str
    unresolved: int = 0
    vendors_run: list = field(default_factory=list)
    vendor_failures: list = field(default_factory=list)
    statuses: list = field(default_factory=list)
    files_reviewed: Optional[int] = None
    binary_files: Optional[int] = None
    outfile: Optional[str] = None


def _pending(reason: str) -> _Outcome:
    return _Outcome("pending", "pending", reason)


def _hold(reason: str, **kw: Any) -> _Outcome:
    return _Outcome("hold", "hold", reason, **kw)


def _parse_header(content: str) -> tuple[dict, bool]:
    """(first value per key, whether any key repeated) over the lines before the first `## `."""
    values: dict[str, str] = {}
    duplicate = False
    for line in content.split("\n"):
        if line.startswith("## "):
            break
        match = _HEADER_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key in values:
            duplicate = True
        else:
            values[key] = value
    return values, duplicate


_RC_FOR_VERDICT = {"approve": (0,), "unparseable": (0,), "error": (1,), "request_changes": (2,)}


def _detail_token(detail: Any, vendor: str) -> str:
    if detail == "prompt_too_large":
        return "diff-too-large"
    if detail == "timeout":
        return f"vendor-timeout:{vendor}"
    if detail == "prompt_not_consumed":
        return f"prompt-not-consumed:{vendor}"
    if detail in ("binary_not_found", "not_executable", "exec_failed"):
        return f"vendor-unavailable:{vendor}"
    return f"vendor-error:{vendor}"


def _vendor_status(vendor: str, section: Optional[str]) -> _VendorStatus:
    if section is None:
        return _VendorStatus(vendor, "failed", f"vendor-missing:{vendor}")
    heading, _, body = section.partition("\n")
    if "skipped" in heading.lower():
        return _VendorStatus(vendor, "failed", f"vendor-missing:{vendor}")

    objs = validation_logic.extract_json_objects(body)
    for obj in objs:
        if obj.get("outcome") == "invocation_failed":
            return _VendorStatus(vendor, "failed", _detail_token(obj.get("outcome_detail"), vendor))
    if any("extraction_error" in obj for obj in objs):
        return _VendorStatus(vendor, "unparseable")
    if not objs:
        prose = second_review_logic.classify_prose(second_review_logic._fenced_body(body))
        if prose == "request_changes":
            return _VendorStatus(
                vendor,
                "request_changes",
                verdict_entry=True,
                verdict_detail=second_review_logic._fenced_body(body),
            )
        return _VendorStatus(vendor, "unparseable")

    blocking: list = []
    malformed = False
    any_rc = False
    all_approve = True
    summary = ""
    for obj in objs:
        verdict = str(obj.get("verdict")).strip().lower()
        if verdict == "error" or obj.get("error"):
            return _VendorStatus(vendor, "failed", f"vendor-error:{vendor}")
        if verdict == "request_changes":
            any_rc = True
            if not summary and isinstance(obj.get("summary"), str):
                summary = obj["summary"]
        if verdict != "approve":
            all_approve = False
        for key in ("findings", "attacks"):
            if key not in obj:
                continue
            items = obj[key]
            if not isinstance(items, list):
                malformed = True
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("severity")).strip().lower()
                if severity in validation_logic.BLOCKING_SEVERITIES:
                    blocking.append((severity, item))
    if any_rc or blocking or malformed:
        return _VendorStatus(
            vendor,
            "request_changes",
            blocking=blocking,
            verdict_entry=malformed or not blocking,
            verdict_detail=summary,
        )
    if all_approve:
        return _VendorStatus(vendor, "approve")
    return _VendorStatus(vendor, "unparseable")


def classify_run(cmd: CmdResult, run_dir: Path, vendorset: str, base: str, head: str) -> _Outcome:
    """Map one `run_second_review.sh --authority` run to a closed result (TD section 5.5)."""
    if cmd.rc not in (0, 1, 2):
        return _pending("review-failed")

    try:
        reports = sorted(run_dir.glob("*.md"))
    except OSError:
        return _pending("review-failed")
    if len(reports) != 1:
        return _pending("review-failed")
    report = reports[0]
    try:
        st = report.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > REPORT_MAX_BYTES:
            return _pending("review-failed")
        content = report.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return _pending("review-failed")
    outfile = str(report)

    header, duplicate = _parse_header(content)
    verdict = header.get("verdict")
    if verdict is None or "mode" not in header:
        return _pending("review-failed")
    if header["mode"] != "authority" or verdict not in _RC_FOR_VERDICT:
        return _pending("review-failed")
    if cmd.rc not in _RC_FOR_VERDICT[verdict]:
        return _pending("review-failed")

    has_reason = "reason" in header
    files_raw = header.get("files_reviewed", "")
    binary_raw = header.get("binary_files", "")
    files_ok = bool(_INT_FIELD_RE.match(files_raw)) and bool(_INT_FIELD_RE.match(binary_raw))
    files_reviewed = int(files_raw) if _INT_FIELD_RE.match(files_raw) else None
    binary_files = int(binary_raw) if _INT_FIELD_RE.match(binary_raw) else None

    def inconsistent() -> _Outcome:
        return _hold(
            "review-inconsistent",
            outfile=outfile,
            files_reviewed=files_reviewed,
            binary_files=binary_files,
        )

    if (
        duplicate
        or header.get("vendors_required") != vendorset
        or header.get("reviewed_range") != f"{base}..{head}"
        or (run_dir / "no-ledger.jsonl").exists()
        or (not has_reason and not files_ok)
        or (has_reason and verdict != "error")
    ):
        return inconsistent()

    if has_reason:
        reason = header["reason"]
        if reason == "diff-failed":
            return _pending("diff-failed")
        if reason == "empty-diff":
            return _hold("empty-diff", outfile=outfile)
        if reason in {f"vendor-unavailable:{v}" for v in VENDORS}:
            return _hold(reason, outfile=outfile)
        return inconsistent()

    required = vendors_list(vendorset)
    # The fence-aware split below can be fooled by vendor text that inverts a fence, so also
    # require the raw heading count and the fence parity to be exactly what the shell writes.
    raw_headings = len(re.findall(r"(?m)^## (?:agy|codex)", content))
    fence_lines = sum(1 for line in content.splitlines() if line.lstrip().startswith("```"))
    if raw_headings != len(required) or fence_lines % 2:
        return inconsistent()
    sections = second_review_logic._split_sections(content)
    by_vendor: dict[str, list[str]] = {}
    for section in sections:
        first = section.split("\n", 1)[0].lower()
        for vendor in VENDORS:
            if first.startswith(vendor):
                if vendor not in required:
                    return inconsistent()
                by_vendor.setdefault(vendor, []).append(section)
    if any(len(found) > 1 for found in by_vendor.values()):
        return inconsistent()

    statuses = [
        _vendor_status(vendor, by_vendor[vendor][0] if vendor in by_vendor else None)
        for vendor in required
    ]
    vendors_run = [s.vendor for s in statuses if s.status in ("approve", "request_changes")]
    common: dict[str, Any] = {
        "statuses": statuses,
        "vendors_run": vendors_run,
        "files_reviewed": files_reviewed,
        "binary_files": binary_files,
        "outfile": outfile,
    }

    if any(s.status == "request_changes" for s in statuses):
        unresolved = max(1, sum(len(s.blocking) for s in statuses))
        failures = [t for s in statuses if (t := s.failure_token) is not None]
        return _Outcome(
            "final",
            "request_changes",
            "findings",
            unresolved=unresolved,
            vendor_failures=failures,
            **common,
        )
    failed = next((s for s in statuses if s.status == "failed"), None)
    if failed is not None:
        return _hold(str(failed.token), **common)
    if any(s.status == "unparseable" for s in statuses):
        return _hold("unparseable", **common)

    counts_clean = all(
        _INT_FIELD_RE.match(header.get(key, "")) and int(header[key]) == 0
        for key in ("unresolved_findings", "blocking_count", "new_blocking_count")
    )
    if verdict != "approve" or not counts_clean or not files_reviewed:
        return _hold("review-inconsistent", **common)
    if binary_files:
        return _hold("binary-unreviewed", **common)
    return _Outcome("final", "approve", "ok", **common)


# --------------------------------------------------------------------------- #
# The runner                                                                  #
# --------------------------------------------------------------------------- #
@dataclass
class _Ctx:
    config: Config
    deps: Deps
    pr: int
    slug: str = ""
    head: Optional[str] = None
    base_tip: Optional[str] = None
    base: Optional[str] = None
    tier: Optional[str] = None
    tier_sources: Optional[dict] = None
    vendorset: Optional[str] = None
    worktree_created: bool = False
    pending_count: Optional[int] = None
    pending_last_reason: Optional[str] = None

    @property
    def root(self) -> Path:
        return self.config.repo_root

    def run(self, argv: Sequence[str], timeout: Optional[float], env=None) -> CmdResult:
        return self.deps.run_cmd(argv, self.root, timeout, env)

    def git(self, *args: str) -> CmdResult:
        return self.run(["git", "-C", str(self.root), *args], GIT_TIMEOUT)

    def timestamp(self) -> str:
        return self.deps.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(ctx: _Ctx, **over: Any) -> dict:
    result = {
        "check": CHECK,
        "schema": SCHEMA,
        "pr": ctx.pr,
        "head_sha": ctx.head,
        "base_sha": ctx.base,
        "range": f"{ctx.base}..{ctx.head}" if ctx.base and ctx.head else None,
        "tier": ctx.tier,
        "vendors": ctx.vendorset,
        "verdict": "pending",
        "status": None,
        "reason": "",
        "reused": False,
        "findings_file": None,
        "record": None,
        "hold_label_applied": None,
        "pending_count": ctx.pending_count,
        "pending_last_reason": ctx.pending_last_reason,
    }
    result.update(over)
    if set(result) != RESULT_KEYS:
        raise RuntimeError("result keys drifted from RESULT_KEYS")
    return result


def _result_from_record(ctx: _Ctx, rec: dict, *, reused: bool) -> dict:
    vendorset = _vendorset_of(rec["vendors_required"])
    ctx.base = rec.get("base_sha") or ctx.base
    return _result(
        ctx,
        base_sha=rec.get("base_sha"),
        range=rec.get("range"),
        tier=rec.get("tier"),
        vendors=vendorset,
        verdict=rec["verdict"],
        status=rec["status"],
        reason=rec.get("reason", ""),
        reused=reused,
        findings_file=rec.get("findings_file"),
        record=str(_record_path(ctx.root, ctx.pr, rec["head_sha"], vendorset)),
        hold_label_applied=rec.get("hold_label_applied"),
        pending_count=None if reused else ctx.pending_count,
        pending_last_reason=None if reused else ctx.pending_last_reason,
    )


def _clear_counter(ctx: _Ctx) -> None:
    assert ctx.head
    try:
        os.unlink(_pending_path(ctx.root, ctx.pr, ctx.head))
    except FileNotFoundError:
        pass
    except OSError as exc:
        _log(f"WARN could not clear the pending counter ({type(exc).__name__})")


def _audit(ctx: _Ctx, rec: dict) -> None:
    event = {
        "event": "overseer-second-review",
        "timestamp": ctx.timestamp(),
        "actor": os.environ.get("HOS_BOT_LOGIN") or None,
        "repo": rec["repo"],
        "pr": rec["pr"],
        "head_sha": rec["head_sha"],
        "base_sha": rec["base_sha"],
        "range": rec["range"],
        "tier": rec["tier"],
        "vendors": _vendorset_of(rec["vendors_required"]),
        "status": rec["status"],
        "verdict": rec["verdict"],
        "reason": rec["reason"],
        "unresolved_findings": rec["unresolved_findings"],
        "vendor_failures": rec["vendor_failures"],
        "files_reviewed": rec["files_reviewed"],
        "binary_files": rec["binary_files"],
        "outfile": rec["outfile"],
        "reused": False,
    }
    try:
        ctx.deps.write_audit(event, ctx.root)
    except Exception as exc:  # noqa: BLE001 — audit is evidence, never a gate
        _log(f"WARN audit write failed ({type(exc).__name__})")


def _write_record(
    ctx: _Ctx,
    *,
    status: str,
    verdict: str,
    reason: str,
    vendorset: str,
    unresolved: int = 0,
    findings_file: Optional[str] = None,
    outfile: Optional[str] = None,
    vendors_run: Sequence[str] = (),
    files_reviewed: Optional[int] = None,
    binary_files: Optional[int] = None,
    vendor_failures: Sequence[str] = (),
) -> dict:
    """Write the record atomically, clear the pending counter, emit the audit event."""
    assert ctx.head
    rec = {
        "schema": SCHEMA,
        "check": CHECK,
        "repo": ctx.slug,
        "pr": ctx.pr,
        "head_sha": ctx.head,
        "base_sha": ctx.base,
        "range": f"{ctx.base}..{ctx.head}" if ctx.base else None,
        "tier": ctx.tier,
        "tier_sources": ctx.tier_sources,
        "vendors_required": vendors_list(vendorset),
        "vendors_run": list(vendors_run),
        "status": status,
        "verdict": verdict,
        "reason": reason,
        "unresolved_findings": unresolved,
        "findings_file": findings_file,
        "outfile": outfile,
        "files_reviewed": files_reviewed,
        "binary_files": binary_files,
        "hold_label_applied": False if status == "hold" else None,
        "vendor_failures": list(vendor_failures),
        "created_at": ctx.timestamp(),
    }
    _atomic_write_json(_record_path(ctx.root, ctx.pr, ctx.head, vendorset), rec)
    _clear_counter(ctx)
    _audit(ctx, rec)
    return rec


def _read_counter(ctx: _Ctx) -> int:
    assert ctx.head
    raw = _read_json_dict(_pending_path(ctx.root, ctx.pr, ctx.head), RECORD_MAX_BYTES)
    if (
        isinstance(raw, dict)
        and _is_int(raw.get("schema"), SCHEMA)
        and raw.get("check") == CHECK
        and raw.get("repo") == ctx.slug
        and _is_int(raw.get("pr"), ctx.pr)
        and raw.get("head_sha") == ctx.head
        and _is_int(raw.get("count"))
        and raw["count"] >= 0
    ):
        return raw["count"]
    return 0


def _refresh_raise_locked(ctx: _Ctx) -> None:
    """Re-read the raise under head_lock and lift the provisional tier; never lowers (TD 5.3 R9 step 0)."""
    assert ctx.head and ctx.tier is not None
    r_tier, r_invalid = read_raise(ctx.root, slug=ctx.slug, pr=ctx.pr, head=ctx.head)
    candidate = "HIGH" if r_invalid else r_tier
    if candidate is None or TIERS.index(candidate) <= TIERS.index(ctx.tier):
        return
    ctx.tier = candidate
    ctx.vendorset = required_vendorset(candidate)
    if ctx.tier_sources is not None:
        ctx.tier_sources["raise"] = r_tier
        if r_invalid and "raise-invalid" not in ctx.tier_sources["defaulted"]:
            ctx.tier_sources["defaulted"].append("raise-invalid")


def _count_pending_locked(ctx: _Ctx, reason: str) -> Optional[dict]:
    assert ctx.head
    count = _read_counter(ctx) + 1
    _atomic_write_json(
        _pending_path(ctx.root, ctx.pr, ctx.head),
        {
            "schema": SCHEMA,
            "check": CHECK,
            "repo": ctx.slug,
            "pr": ctx.pr,
            "head_sha": ctx.head,
            "count": count,
            "last_reason": reason,
            "updated_at": ctx.timestamp(),
        },
    )
    ctx.pending_count, ctx.pending_last_reason = count, reason
    if count < PENDING_STUCK_AT:
        return None
    vendorset = ctx.vendorset
    if ctx.base is not None and vendorset is not None:
        existing = load_record(
            ctx.root,
            repo=ctx.slug,
            pr=ctx.pr,
            head_sha=ctx.head,
            base_sha=ctx.base,
            vendorset=vendorset,
        )
        if existing is not None and (
            existing["status"] == "final" or existing["reason"] in DETERMINISTIC_HOLDS
        ):
            _clear_counter(ctx)
            return _result_from_record(ctx, existing, reused=True)
        target = vendorset
    else:
        target = vendorset or "agy+codex"
        if vendorset is None:
            collision = load_record(
                ctx.root, repo=ctx.slug, pr=ctx.pr, head_sha=ctx.head, vendorset=target
            )
            if collision is not None and collision["status"] == "final":
                return _result(
                    ctx,
                    verdict="hold",
                    status="hold",
                    reason="pending-stuck",
                    tier=None,
                    vendors=None,
                )
    rec = _write_record(
        ctx, status="hold", verdict="hold", reason="pending-stuck", vendorset=target
    )
    return _result_from_record(ctx, rec, reused=False)


def _count_pending(ctx: _Ctx, reason: str, *, lock_held: bool) -> Optional[dict]:
    """Advance the consecutive-pending counter; a result only when it is stuck (TD 5.7)."""
    if lock_held:
        return _count_pending_locked(ctx, reason)
    assert ctx.head
    try:
        with head_lock(ctx.root, ctx.slug, ctx.pr, ctx.head, COUNTER_LOCK_TIMEOUT_SECONDS):
            if ctx.vendorset is not None:
                _refresh_raise_locked(ctx)
            return _count_pending_locked(ctx, reason)
    except (KeyedLockTimeout, KeyedLockUnavailable, OSError) as exc:
        _log(f"WARN pending counter skipped ({type(exc).__name__})")
        return None


def _pend(ctx: _Ctx, reason: str, *, lock_held: bool = False) -> dict:
    if reason in PENDING_COUNTED and ctx.head:
        stuck = _count_pending(ctx, reason, lock_held=lock_held)
        if stuck is not None:
            return stuck
    return _result(ctx, verdict="pending", reason=reason)


def _trusted_checkout(ctx: _Ctx) -> bool:
    branch = ctx.git("symbolic-ref", "--short", "HEAD")
    head = ctx.git("rev-parse", "HEAD")
    origin = ctx.git("rev-parse", "refs/remotes/origin/main")
    status = ctx.git("status", "--porcelain", "--untracked-files=no")
    if any(r.rc != 0 for r in (branch, head, origin, status)):
        return False
    return (
        branch.stdout.strip() == "main"
        and head.stdout.strip() != ""
        and head.stdout.strip() == origin.stdout.strip()
        and status.stdout.strip() == ""
    )


def _object_present(ctx: _Ctx, sha: str) -> bool:
    return ctx.git("cat-file", "-e", f"{sha}^{{commit}}").rc == 0


def _fetch_head(ctx: _Ctx) -> Optional[str]:
    """Run the worktree fetch that pins the head. None on success, else the pending reason."""
    assert ctx.head
    ctx.worktree_created = True  # cleanup must run whatever the rc
    script = ctx.config.tools_root / "bootstrap/review_worktree.sh"
    res = ctx.run(
        [
            "bash",
            str(script),
            "--pr",
            str(ctx.pr),
            "--expect-sha",
            ctx.head,
            "--repo",
            str(ctx.root),
        ],
        FETCH_TIMEOUT,
    )
    if res.rc == 4:
        return "head-moved"
    if res.rc != 0:
        return "fetch-failed"
    if f"HEAD={ctx.head}" not in [line.strip() for line in res.stdout.splitlines()]:
        return "head-moved"
    return None


def _cleanup_worktree(ctx: _Ctx) -> None:
    script = ctx.config.tools_root / "bootstrap/review_worktree.sh"
    try:
        res = ctx.run(
            ["bash", str(script), "--cleanup", "--pr", str(ctx.pr), "--repo", str(ctx.root)],
            FETCH_TIMEOUT,
        )
        if res.rc != 0:
            _log(f"WARN worktree cleanup exited {res.rc}")
    except Exception as exc:  # noqa: BLE001 — hygiene must not mask the real outcome
        _log(f"WARN worktree cleanup failed ({type(exc).__name__})")


def _changed_paths(ctx: _Ctx) -> Optional[list[str]]:
    assert ctx.base and ctx.head
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    res = ctx.run(
        [
            "git",
            "-c",
            "core.attributesFile=/dev/null",
            "-C",
            str(ctx.root),
            "diff",
            "--name-only",
            "-z",
            f"{ctx.base}..{ctx.head}",
        ],
        GIT_TIMEOUT,
        env,
    )
    if res.rc != 0:
        return None
    return [unicodedata.normalize("NFC", p) for p in res.stdout.split("\0") if p]


def _write_findings(ctx: _Ctx, outcome: _Outcome, run_dir: Path) -> Path:
    """Write findings.json for a request_changes outcome; raises _FindingsInvalid."""
    assert ctx.head
    changed = _changed_paths(ctx)
    entries = build_entries(outcome.statuses, set(changed or ()))
    _validate_entries(entries, changed or (), ctx.slug)
    path = run_dir / "findings.json"
    _atomic_write_text(path, _serialize_findings(entries, ctx.head))
    return path


def _review_and_record(ctx: _Ctx, cache_only: bool) -> dict:
    """Steps R9 a-g, run while holding the head lock."""
    assert ctx.head and ctx.base and ctx.tier and ctx.vendorset
    rec = load_record(
        ctx.root,
        repo=ctx.slug,
        pr=ctx.pr,
        head_sha=ctx.head,
        base_sha=ctx.base,
        vendorset=ctx.vendorset,
    )
    if rec is not None and (rec["status"] == "final" or rec["reason"] in DETERMINISTIC_HOLDS):
        return _result_from_record(ctx, rec, reused=True)

    if ctx.vendorset == "none":
        written = _write_record(
            ctx,
            status="final",
            verdict="not-required",
            reason="tier-below-medium",
            vendorset="none",
        )
        return _result_from_record(ctx, written, reused=False)

    if cache_only:
        return _result(ctx, verdict="pending", reason="budget")

    # Refuse before any fetch or vendor call: a directory that readers will not trust would
    # make every later cycle re-review at full vendor cost (AR10).
    _ensure_private_dir(records_dir(ctx.root))
    runs = runs_dir(ctx.root)
    _ensure_private_dir(runs)

    if not ctx.worktree_created:
        failure = _fetch_head(ctx)
        if failure is not None:
            return _pend(ctx, failure, lock_held=True)

    now = ctx.deps.now()
    run_dir = runs / (
        f"pr{ctx.pr}-{ctx.head[:12]}-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    )
    run_dir.mkdir(mode=0o700, exist_ok=False)

    cmd = ctx.run(
        [
            "bash",
            str(ctx.config.tools_root / "scripts/run_second_review.sh"),
            "--authority",
            "--out-dir",
            str(run_dir),
            "--step",
            f"pr{ctx.pr}",
            "--diff",
            f"{ctx.base}..{ctx.head}",
            "--tier",
            ctx.tier,
            "--score",
            "0",
        ],
        REVIEW_TIMEOUT,
    )
    outcome = classify_run(cmd, run_dir, ctx.vendorset, ctx.base, ctx.head)

    if outcome.kind == "pending":
        return _pend(ctx, outcome.reason, lock_held=True)

    findings_file: Optional[str] = None
    if outcome.kind == "final" and outcome.verdict == "request_changes":
        try:
            findings_file = str(_write_findings(ctx, outcome, run_dir))
        except _FindingsInvalid as exc:
            _log(f"findings file failed validation ({exc}); holding")
            outcome = _hold(
                "review-inconsistent",
                outfile=outcome.outfile,
                files_reviewed=outcome.files_reviewed,
                binary_files=outcome.binary_files,
            )

    written = _write_record(
        ctx,
        status=outcome.kind,
        verdict=outcome.verdict,
        reason=outcome.reason,
        vendorset=ctx.vendorset,
        unresolved=outcome.unresolved,
        findings_file=findings_file,
        outfile=outcome.outfile,
        vendors_run=outcome.vendors_run,
        files_reviewed=outcome.files_reviewed,
        binary_files=outcome.binary_files,
        vendor_failures=outcome.vendor_failures,
    )
    return _result_from_record(ctx, written, reused=False)


def _run(ctx: _Ctx, cache_only: bool) -> dict:
    config = ctx.config
    try:
        ctx.slug = merge_config.resolve_repo_slug(config.repo_root, config.repo_slug)
    except merge_config.ConfigError:
        return _pend(ctx, "config-error")
    owner, name = ctx.slug.split("/", 1)

    if not _trusted_checkout(ctx):
        return _pend(ctx, "untrusted-checkout")

    try:
        pull = ctx.deps.get_pull(owner, name, ctx.pr)
    except github.GitHubError:
        return _pend(ctx, "github-error")
    if pull is None:
        return _pend(ctx, "pr-not-found")
    if pull.get("state") != "open":
        return _pend(ctx, "pr-not-open")
    head_obj, base_obj = pull.get("head"), pull.get("base")
    head = head_obj.get("sha") if isinstance(head_obj, dict) else None
    base_tip = base_obj.get("sha") if isinstance(base_obj, dict) else None
    if not (
        isinstance(head, str)
        and _HEX40.match(head)
        and isinstance(base_tip, str)
        and _HEX40.match(base_tip)
    ):
        return _pend(ctx, "github-error")
    ctx.head, ctx.base_tip = head, base_tip
    labels = pull.get("labels") or []
    label_names = {
        label.get("name") for label in labels if isinstance(label, dict) and "name" in label
    }

    if label_names & HELD_LABELS:
        holds = [
            r
            for r in find_records(ctx.root, repo=ctx.slug, pr=ctx.pr, head_sha=head)
            if r["status"] == "hold"
        ]
        if holds:
            return _result_from_record(ctx, holds[0], reused=True)
        return _result(ctx, verdict="skipped-held", reason="held-label")

    if not (_object_present(ctx, head) and _object_present(ctx, base_tip)):
        failure = _fetch_head(ctx)
        if failure is not None:
            return _pend(ctx, failure)
        if not _object_present(ctx, head):
            return _pend(ctx, "fetch-failed")
        if not _object_present(ctx, base_tip):
            return _pend(ctx, "base-unresolved")

    merge_base = ctx.git("merge-base", base_tip, head)
    base = merge_base.stdout.strip()
    if merge_base.rc != 0 or not _HEX40.match(base):
        return _pend(ctx, "base-unresolved")
    ctx.base = base

    ctx.tier, ctx.tier_sources = compute_tier(
        ctx.root, config.tools_root, base, head, ctx.pr, ctx.slug, ctx.deps.run_cmd
    )
    ctx.vendorset = required_vendorset(ctx.tier)

    try:
        with head_lock(ctx.root, ctx.slug, ctx.pr, head, config.lock_timeout):
            _refresh_raise_locked(ctx)
            return _review_and_record(ctx, cache_only)
    except KeyedLockTimeout:
        return _result(ctx, verdict="pending", reason="lock-busy")
    except KeyedLockUnavailable:
        return _pend(ctx, "lock-unavailable")
    except OSError as exc:
        _log(f"state write failed ({type(exc).__name__})")
        return _result(ctx, verdict="pending", reason="state-write-failed")


def run(
    pr_number: int,
    *,
    cache_only: bool = False,
    config: Optional[Config] = None,
    deps: Optional[Deps] = None,
) -> dict:
    """Review (or reuse the review of) one open PR head and return the closed result."""
    if type(pr_number) is not int or not 1 <= pr_number <= MAX_PR_NUMBER:
        raise ValueError(f"pr_number must be an int in 1..{MAX_PR_NUMBER}")
    ctx = _Ctx(config or default_config(), deps or default_deps(), pr_number)
    try:
        return _run(ctx, cache_only)
    finally:
        if ctx.worktree_created:
            _cleanup_worktree(ctx)


# --------------------------------------------------------------------------- #
# The approval gate (G1c) and the check marker                                #
# --------------------------------------------------------------------------- #
class GateResult(NamedTuple):
    ok: bool
    reason: Optional[str]
    diag: dict
    record: Optional[dict]
    raise_written: bool


_DIAG_KEYS = (
    "record_path",
    "status",
    "verdict",
    "reason",
    "tier",
    "tier_sources",
    "required_tier",
    "required_vendors",
    "vendors_run",
    "unresolved_findings",
    "files_reviewed",
    "binary_files",
    "vendor_failures",
    "outfile",
    "findings_file",
    "created_at",
    "base_sha",
    "raise_tier",
    "raise_invalid",
    "raise_written",
    "raise_error",
)
_DIAG_RECORD_FIELDS = (
    "status",
    "verdict",
    "reason",
    "tier",
    "vendors_run",
    "unresolved_findings",
    "files_reviewed",
    "binary_files",
    "vendor_failures",
    "outfile",
    "findings_file",
    "created_at",
    "base_sha",
)


def pinned_base(repo_root: Path, base_tip: str, head: str) -> Optional[str]:
    """`git merge-base <base_tip> <head>`, or None when an input is not a SHA or git fails."""
    if not (isinstance(base_tip, str) and _HEX40.match(base_tip)):
        return None
    if not (isinstance(head, str) and _HEX40.match(head)):
        return None
    res = _default_run_cmd(
        ["git", "-C", str(repo_root), "merge-base", base_tip, head], repo_root, GIT_TIMEOUT, None
    )
    base = res.stdout.strip()
    return base if res.rc == 0 and _HEX40.match(base) else None


def _clean_diag_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, list):
        return [_clean_diag_value(item) for item in value]
    return value


def approval_gate(
    repo_root: Path,
    *,
    repo: str,
    pr: int,
    head_sha: str,
    base_tip: str,
    argv_tier: str,
    lock_timeout: float = 10.0,
) -> GateResult:
    """G1c (TD-2357-S1b 8.2): may the overseer approve this head? Reads only; the one write
    is the tier raise, and only when the caller's own tier outranks every stored input."""
    diag: dict = {key: None for key in _DIAG_KEYS}
    diag["raise_written"] = False

    def refuse(reason: str) -> GateResult:
        return GateResult(False, reason, diag, None, False)

    base = pinned_base(repo_root, base_tip, head_sha)
    if base is None:
        return refuse("second_review_record_missing")
    argv = "LOW" if argv_tier == "SAFE" else argv_tier
    try:
        with head_lock(repo_root, repo, pr, head_sha, lock_timeout):
            raised, raise_invalid = read_raise(repo_root, slug=repo, pr=pr, head=head_sha)
            found = {
                vendorset: rec
                for vendorset in VENDORSETS
                if (
                    rec := load_record(
                        repo_root,
                        repo=repo,
                        pr=pr,
                        head_sha=head_sha,
                        base_sha=base,
                        vendorset=vendorset,
                    )
                )
                is not None
            }
    except (KeyedLockTimeout, KeyedLockUnavailable, OSError):
        return refuse("second_review_record_unverifiable")

    raise_floor = "HIGH" if raise_invalid else raised
    record_tiers = [r["tier"] for r in found.values() if r["tier"] is not None]
    stored = [t for t in (raise_floor, *record_tiers) if t is not None]
    tier = max([argv, *stored], key=TIERS.index)
    needed = required_vendorset(tier)
    diag.update(
        base_sha=base,
        required_tier=tier,
        required_vendors=needed,
        raise_tier=raised,
        raise_invalid=raise_invalid,
        tier_sources={
            "argv": argv,
            "raise": raised,
            "records": [
                {"vendors": vendorset, "tier": r["tier"]} for vendorset, r in found.items()
            ],
        },
    )

    rec = found.get(needed)
    if rec is not None:
        diag["record_path"] = str(_record_path(repo_root, pr, head_sha, needed))
        for key in _DIAG_RECORD_FIELDS:
            diag[key] = _clean_diag_value(rec.get(key))
    diag["record_path"] = _clean_diag_value(diag["record_path"])

    reason = _gate_refusal(found, needed, rec)

    # The caller's tier outranks everything stored: a later run must review at that tier.
    stored_floor = max(stored, key=TIERS.index) if stored else "LOW"
    if VENDORSETS.index(required_vendorset(argv)) > VENDORSETS.index(
        required_vendorset(stored_floor)
    ):
        try:
            write_raise(repo_root, repo=repo, pr=pr, head_sha=head_sha, tier=argv)
            diag["raise_written"] = True
        except (OSError, ValueError, KeyedLockTimeout, KeyedLockUnavailable) as exc:
            diag["raise_error"] = type(exc).__name__

    if reason is not None:
        return GateResult(False, reason, diag, None, diag["raise_written"])
    return GateResult(True, None, diag, rec, diag["raise_written"])


def _gate_refusal(found: dict, needed: str, rec: Optional[dict]) -> Optional[str]:
    """The refusal reason for the record at the needed vendor set, or None to accept."""
    if rec is None:
        lower = VENDORSETS[: VENDORSETS.index(needed)]
        if any(found[v]["status"] == "final" for v in lower if v in found):
            return "second_review_tier_raise"
        return "second_review_record_missing"
    if rec["status"] != "final":
        return "second_review_not_approved"
    if needed == "none":
        return None if rec["verdict"] == "not-required" else "second_review_not_approved"
    if rec["verdict"] != "approve":
        return "second_review_not_approved"
    if not (
        rec["unresolved_findings"] == 0
        and rec["binary_files"] == 0
        and rec["vendors_run"] == vendors_list(needed)
    ):
        return "second_review_not_approved"
    return None


def check_marker(*, pr: int, head_sha: str, record: Optional[dict]) -> str:
    """The AD-4 marker line. A record with no tier (a hold written before the tier was known)
    renders `tier=- vendors=-`: its vendor set is a placeholder, not a requirement."""
    if not (_is_int(pr) and 1 <= pr <= MAX_PR_NUMBER and _HEX40.match(head_sha)):
        raise ValueError("pr or head_sha is not valid")
    tier, vendors, verdict = "-", "-", "none"
    if record is not None:
        verdict = record["verdict"]
        if record.get("tier") is not None:
            tier = record["tier"]
            vendors = _vendorset_of(record["vendors_required"])
    return (
        f"{CHECK_MARKER_PREFIX} v=1 check={CHECK} pr={pr} head={head_sha} tier={tier} "
        f"vendors={vendors} verdict={verdict} bounced=false -->"
    )


# --------------------------------------------------------------------------- #
# mark-hold-label and the CLI                                                 #
# --------------------------------------------------------------------------- #
def mark_hold_label(repo_root: Path, *, repo: str, pr: int, head_sha: str, applied: bool) -> int:
    """Set hold_label_applied on every valid hold record for the head. Exit-code semantics:
    0 updated at least one, 3 no hold record (final records are never touched)."""
    with head_lock(repo_root, repo, pr, head_sha, OSR_LOCK_TIMEOUT_SECONDS):
        holds = [
            r
            for r in find_records(repo_root, repo=repo, pr=pr, head_sha=head_sha)
            if r["status"] == "hold"
        ]
        if not holds:
            return 3
        for rec in holds:
            rec["hold_label_applied"] = applied
            _atomic_write_json(
                _record_path(repo_root, pr, head_sha, _vendorset_of(rec["vendors_required"])), rec
            )
    return 0


def _pr_arg(value: str) -> int:
    if not re.match(r"^[1-9][0-9]{0,6}$", value):
        raise argparse.ArgumentTypeError("must be an integer in 1..9999999")
    return int(value)


def _head_arg(value: str) -> str:
    if not _HEX40.match(value):
        raise argparse.ArgumentTypeError("must be 40 lowercase hex characters")
    return value


def _bool_arg(value: str) -> bool:
    if value not in ("true", "false"):
        raise argparse.ArgumentTypeError("must be true or false")
    return value == "true"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overseer_second_review", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="review or reuse the review of one PR head")
    run_p.add_argument("--pr", type=_pr_arg, required=True)
    run_p.add_argument("--cache-only", action="store_true")
    mark_p = sub.add_parser("mark-hold-label", help="record that needs-human was applied")
    mark_p.add_argument("--pr", type=_pr_arg, required=True)
    mark_p.add_argument("--head", type=_head_arg, required=True)
    mark_p.add_argument("--applied", type=_bool_arg, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "run":
            result = run(args.pr, cache_only=args.cache_only)
            sys.stdout.write(
                json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
            )
            return 0
        config = default_config()
        slug = merge_config.resolve_repo_slug(config.repo_root, config.repo_slug)
        return mark_hold_label(
            config.repo_root, repo=slug, pr=args.pr, head_sha=args.head, applied=args.applied
        )
    except Exception:  # noqa: BLE001 — the contract is exit 1, traceback on stderr, no stdout
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
