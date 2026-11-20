#!/usr/bin/env python3
"""suspension_manager.py — manage contract/gate-suspension.md.

Implements the low-friction / high-audit levers for the unified suspension
mechanism (HOS#62), governed by the RATCHET PRINCIPLE
(research/findings/ratchet-principle.md):

    The system may auto-TIGHTEN (re-enable a gate). It may never auto-LOOSEN
    (suspend one). This module contains NO code path that writes a SUSPENDED
    line — it only ever removes them. Only a human may suspend.

Levers:
  --census       Print active suspensions; warn on past `review-by`; emit a
                 `suspension-census` audit event (the health metric).
  --check        For each AUTO-CHECKABLE suspended gate, run its gate script
                 and record pass/fail in the pass-history.
  --auto-remove  Remove suspensions that have passed N consecutive checks and
                 are eligible (pure script gate, not [pinned], auto-remove on).
                 Appends to the Re-enable log and emits `gate-auto-reenabled`.
  (default)      Run census + check + auto-remove in sequence.
  --is-suspended GATE
                 Exit 0 only when GATE's suspension status is `active`.
  --suspension-status GATE
                 Print STATUS=/GATE=/EXPIRES=/UNTIL_CLOSED=/DETAIL= and exit
                 0 active, 1 absent, 3 expired, 4 malformed, 5 unknown (2 = usage).
  --validate-dep-trace STEP --range BASE..HEAD
                 Structurally validate the dep-mapper manual trace (#2214).
  --check-suspended-resolutions STEP --range BASE..HEAD --tier T
                 --human-gate-required true|false [--require-disclosure]
                 Re-derive whether a `suspended:` blocking-finding resolution
                 is valid (#2214). Exit 0 ok/not applicable, 4 fail, 2 error.

Time-boxed suspensions (#2214): a SUSPENDED line may carry `expires: YYYY-MM-DD`
(inclusive, UTC) and/or `until-closed: #N` (ends once the issue closes as
completed, judged from its close history). Only status `active` suppresses
anything; absent/expired/malformed/unknown all fail closed. No CLI flag can
override the clock, the issue state, or the file paths used by the status and
resolution checks.

Config (env or scripts/framework/config.sh):
  SUSPENSION_AUTO_REMOVE        true|false  (default true)
  SUSPENSION_AUTO_REMOVE_RUNS   int         (default 3 consecutive passes)

Stdlib only — no third-party imports, so no venv dependency.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

SUSPENSION_FILE = "contract/gate-suspension.md"
HISTORY_FILE = ".claudetmp/oversight/suspension-history.jsonl"


def _load_audit_log():
    """Load the canonical per-entry audit-record helper by file path.

    suspension_manager runs as a plain script (sys.path[0] = its own dir), so a
    package import is not reliable here; load the sibling lib/ module directly.
    """
    path = Path(__file__).resolve().parent / "lib" / "audit_log.py"
    spec = importlib.util.spec_from_file_location("hos_audit_log", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AUDIT_LOG = _load_audit_log()

# Gates that can be auto-removed: PURE script gates whose passing genuinely
# means the gate is satisfied. `security` is deliberately excluded — it has a
# reviewer-role counterpart that a passing security_scan cannot satisfy, so it
# is only ever nudged, never auto-removed.
AUTO_CHECKABLE_GATES: dict[str, str] = {
    "lint": "scripts/oversight/gates/lint_check.sh",
    "secrets": "scripts/oversight/gates/secret_scan.sh",  # pragma: allowlist secret
    "types": "scripts/oversight/gates/type_check.sh",
    "template-refs": "scripts/oversight/gates/template_refs_check.sh",
    "portability": "scripts/oversight/gates/portability_check.sh",
    "django": "scripts/oversight/gates/django_check.sh",
}

_SUSPENDED_RE = re.compile(
    r"^SUSPENDED:\s*(?P<gate>[a-z0-9-]+)"
    r"(?P<flags>(?:\s+\[pinned\]|\s+review-by:\s*\d{4}-\d{2}-\d{2}"
    r"|\s+expires:\s*\d{4}-\d{2}-\d{2}|\s+until-closed:\s*#\d+)*)\s*$"
)
# Names a gate but may fail the strict grammar (unknown flag, bad value, ...).
_SUSPENDED_LOOSE_RE = re.compile(r"^SUSPENDED:\s*(?P<gate>[a-z0-9-]+)(\s|$)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Suspension:
    def __init__(
        self,
        gate: str,
        pinned: bool,
        review_by: str | None,
        raw_line: str,
        expires: str | None = None,
        until_closed: int | None = None,
        malformed: bool = False,
    ):
        self.gate = gate
        self.pinned = pinned
        self.review_by = review_by
        self.raw_line = raw_line
        self.expires = expires
        self.until_closed = until_closed
        self.malformed = malformed


def _candidate_lines(text: str):
    """Yield raw lines outside HTML comment blocks (template examples live there)."""
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        # Track comment blocks crudely but correctly for our single-line needs.
        if "<!--" in stripped and "-->" not in stripped:
            in_comment = True
            continue
        if "-->" in stripped:
            in_comment = False
            continue
        if in_comment:
            continue
        yield line


def _valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def parse_suspensions(text: str) -> list[Suspension]:
    """Parse SUSPENDED: lines from the 'Currently suspended' section.

    Only lines outside HTML comments are considered (the template's examples
    live inside <!-- --> and must be ignored). Lines that name a gate but fail
    the strict grammar are NOT returned here (see suspension_status).
    """
    out: list[Suspension] = []
    for line in _candidate_lines(text):
        m = _SUSPENDED_RE.match(line.strip())
        if not m:
            continue
        flags = m.group("flags") or ""
        pinned = "[pinned]" in flags
        rb = re.search(r"review-by:\s*(\d{4}-\d{2}-\d{2})", flags)
        exp_all = re.findall(r"expires:\s*(\d{4}-\d{2}-\d{2})", flags)
        uc_all = re.findall(r"until-closed:\s*#(\d+)", flags)
        malformed = len(exp_all) > 1 or len(uc_all) > 1 or any(not _valid_date(d) for d in exp_all)
        out.append(
            Suspension(
                m.group("gate"),
                pinned,
                rb.group(1) if rb else None,
                line,
                expires=exp_all[0] if exp_all else None,
                until_closed=int(uc_all[0]) if uc_all else None,
                malformed=malformed,
            )
        )
    return out


def _gate_line_counts(text: str) -> tuple[dict[str, int], set[str]]:
    """Per-gate count of lines naming the gate, plus gates with a loose-only line."""
    counts: dict[str, int] = {}
    loose_only: set[str] = set()
    for line in _candidate_lines(text):
        stripped = line.strip()
        lm = _SUSPENDED_LOOSE_RE.match(stripped)
        if not lm:
            continue
        gate = lm.group("gate")
        counts[gate] = counts.get(gate, 0) + 1
        if not _SUSPENDED_RE.match(stripped):
            loose_only.add(gate)
    return counts, loose_only


STATUS_ACTIVE = "active"
STATUS_ABSENT = "absent"
STATUS_EXPIRED = "expired"
STATUS_MALFORMED = "malformed"
STATUS_UNKNOWN = "unknown"

_STATUS_EXIT = {
    STATUS_ACTIVE: 0,
    STATUS_ABSENT: 1,
    STATUS_EXPIRED: 3,
    STATUS_MALFORMED: 4,
    STATUS_UNKNOWN: 5,
}

IssueState = Callable[[int], "tuple[str, str | None, list[str | None]]"]


def _default_issue_state(n: int, repo_root=".") -> tuple[str, str | None, list[str | None]]:
    """Look up issue #n: (current state, current state_reason, past close reasons).

    Imports the GitHub helper lazily so this module stays stdlib-only at import
    time. Any failure raises, which the caller turns into status `unknown`. The
    repo slug comes from `repo_root`'s origin remote, not the process cwd.
    """
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.automation.lib import github, merge_config  # noqa: PLC0415

    slug = merge_config.resolve_repo_slug(repo_root)
    owner, _, repo = slug.partition("/")
    issue = github.get_issue(owner, repo, n)
    if issue is None:
        raise LookupError(f"issue #{n} not found")
    events = github.list_issue_events(owner, repo, n)
    past = [e.get("state_reason") for e in events if e.get("event") == "closed"]
    return issue["state"], issue.get("state_reason"), past


def _well_formed_issue_state(value) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 3
        and isinstance(value[0], str)
        and (value[1] is None or isinstance(value[1], str))
        and isinstance(value[2], list)
        and all(r is None or isinstance(r, str) for r in value[2])
    )


def suspension_status(
    text: str,
    gate: str,
    today: str | None = None,
    issue_state: IssueState | None = None,
    repo_root=None,
) -> dict:
    """Classify gate's suspension: absent | malformed | expired | unknown | active.

    Pure apart from the injectable `today` (YYYY-MM-DD, UTC) and `issue_state`
    lookup. Only `active` suppresses anything (D-4). `expires:` is INCLUSIVE:
    active through that date, expired from the next UTC day — unlike
    grandfathered_until, where a date equal to today counts as expired (D-2).
    An `until-closed:` issue ends the suspension if ANY close in its history was
    not `not_planned`, even if it was reopened (D-3); an ambiguous close counts
    as landed. The date is checked first, so an expired date never calls
    `issue_state` (D-5). `repo_root` only picks where the default lookup resolves
    the repo slug (None: the process cwd).
    """

    def result(status: str, detail: str, sus: Suspension | None = None) -> dict:
        return {
            "status": status,
            "gate": gate,
            "expires": sus.expires if sus else None,
            "until_closed": sus.until_closed if sus else None,
            "detail": detail,
        }

    counts, loose_only = _gate_line_counts(text)
    if counts.get(gate, 0) == 0:
        return result(STATUS_ABSENT, "no SUSPENDED line for gate")
    matching = [s for s in parse_suspensions(text) if s.gate == gate]
    if counts[gate] > 1 or gate in loose_only or any(s.malformed for s in matching):
        return result(STATUS_MALFORMED, "duplicate or malformed SUSPENDED line")
    sus = matching[0]

    if sus.expires is not None:
        today_v = today if today is not None else _today()
        if today_v > sus.expires:
            nxt = (datetime.strptime(sus.expires, "%Y-%m-%d") + timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            return result(STATUS_EXPIRED, f"expired {nxt}", sus)

    if sus.until_closed is not None:
        if issue_state is not None:
            lookup = issue_state
        elif repo_root is not None:

            def lookup(num: int):
                return _default_issue_state(num, repo_root)

        else:
            lookup = _default_issue_state
        n = sus.until_closed
        try:
            state = lookup(n)
        except Exception as exc:  # fail closed on any lookup error
            return result(STATUS_UNKNOWN, f"#{n} lookup failed: {type(exc).__name__}", sus)
        if not _well_formed_issue_state(state):
            return result(STATUS_UNKNOWN, f"#{n} lookup returned an unexpected shape", sus)
        current, reason, past = state
        for past_reason in past:
            if past_reason != "not_planned":
                return result(STATUS_EXPIRED, f"#{n} closed ({past_reason}) — landed", sus)
        if current == "closed" and reason != "not_planned":
            return result(STATUS_EXPIRED, f"#{n} closed ({reason}) — landed", sus)
        if current not in ("open", "closed"):
            return result(STATUS_UNKNOWN, f"#{n} in unexpected state {current!r}", sus)

    return result(STATUS_ACTIVE, "active", sus)


def acknowledged_security(text: str) -> bool:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if s.replace(" ", "").lower().startswith("security-suspension-acknowledged:yes"):
            return True
    return False


def _iter_noncomment_lines(text: str):
    """Yield stripped lines that are outside HTML comment blocks and not '#' comments.

    Mirrors parse_suspensions()'s crude-but-correct comment tracking — the template
    keeps its examples inside <!-- --> and as '#'-prefixed lines, and those must be
    ignored (a human enables a field by un-commenting it).
    """
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if "<!--" in stripped and "-->" not in stripped:
            in_comment = True
            continue
        if "-->" in stripped:
            in_comment = False
            continue
        if in_comment:
            continue
        if stripped.startswith("#"):
            continue
        yield stripped


_TRUTHY = ("1", "true", "yes", "on")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_per_step_scope(text: str) -> tuple[bool, list[str]]:
    """Parse `per_step_scope:` and `steps:` from a gate-suspension file (SPEC-83 R1).

    Returns (per_step_scope, steps). HTML-commented and '#'-commented lines are
    ignored (template examples). Both block-list (`  - step-3`) and inline
    (`steps: [step-3, step-4]`) forms are accepted. Step IDs are returned verbatim
    (byte-exact, case-sensitive — the caller matches with `==`).
    """
    per_step = False
    steps: list[str] = []
    in_block_list = False
    for stripped in _iter_noncomment_lines(text):
        low = stripped.lower()
        if low.replace(" ", "").startswith("per_step_scope:"):
            val = stripped.split(":", 1)[1].strip().lower()
            per_step = val in _TRUTHY
            in_block_list = False
            continue
        if low.startswith("steps:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest.startswith("[") and rest.endswith("]"):
                # inline form: steps: [step-3, step-4]
                inner = rest[1:-1].strip()
                if inner:
                    steps.extend(s.strip().strip("'\"") for s in inner.split(",") if s.strip())
                in_block_list = False
            elif rest:
                # `steps: step-3` single inline value (no brackets)
                steps.append(rest.strip("'\""))
                in_block_list = False
            else:
                in_block_list = True  # block-list entries follow on subsequent lines
            continue
        if in_block_list:
            if stripped.startswith("- "):
                steps.append(stripped[2:].strip().strip("'\""))
                continue
            in_block_list = False  # non-list line ends the block
    return per_step, steps


def validate_per_step_scope(text: str, step_id: str) -> dict:
    """Classify the per-step scope fields against a step ID (SPEC-83 R2.2a / R1.6).

    Returns:
      {per_step_scope: bool, malformed: bool, covers_step: bool, steps: [str]}

    - per_step_scope False (blanket/absent) → not malformed, not covering.
    - per_step_scope True + empty/absent steps → malformed True (R1.6 distinct FAIL).
    - per_step_scope True + non-empty steps → covers_step = (step_id in steps), exact match.

    Does NOT check the tier or security-suspension-acknowledged — that stays with the
    evaluator (R2.3). Pure classifier of the scope fields.
    """
    per_step, steps = parse_per_step_scope(text)
    malformed = per_step and not steps
    covers = per_step and not malformed and step_id in steps
    return {
        "per_step_scope": per_step,
        "malformed": malformed,
        "covers_step": covers,
        "steps": steps,
    }


def check_grandfathered_until(text: str, today: str | None = None) -> dict:
    """Resolve the `grandfathered_until:` transition date (SPEC-83 R3).

    Reuses the `review-by:` date idiom: lexicographic YYYY-MM-DD comparison against
    today. `today` defaults to _today() (injectable for tests).

    Returns {present: bool, date: str|None, status: str} where status is one of:
      "absent"    — no grandfathered_until line → no grandfathering (FAIL applies)
      "future"    — date strictly after today  → WARN + CONDITIONAL_PROCEED
      "expired"   — date today or in the past  → FAIL (period over)
      "malformed" — value not YYYY-MM-DD       → FAIL (fail-closed)
    """
    today = today or _today()
    for stripped in _iter_noncomment_lines(text):
        if stripped.lower().replace(" ", "").startswith("grandfathered_until:"):
            val = stripped.split(":", 1)[1].strip()
            if not _DATE_RE.match(val):
                return {"present": True, "date": val or None, "status": "malformed"}
            # strictly-future = grandfathered; today or past = expired (period over)
            status = "future" if val > today else "expired"
            return {"present": True, "date": val, "status": status}
    return {"present": False, "date": None, "status": "absent"}


def _read_config_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        cfg = Path("scripts/framework/config.sh")
        if cfg.exists():
            m = re.search(rf"^{name}=[\"']?(\w+)[\"']?", cfg.read_text(), re.M)
            if m:
                val = m.group(1)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _read_config_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        cfg = Path("scripts/framework/config.sh")
        if cfg.exists():
            m = re.search(rf"^{name}=[\"']?(\d+)[\"']?", cfg.read_text(), re.M)
            if m:
                val = m.group(1)
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def load_history() -> list[dict]:
    p = Path(HISTORY_FILE)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def record_check(gate: str, passed: bool) -> None:
    p = Path(HISTORY_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"gate": gate, "passed": passed, "timestamp": _now()}) + "\n")


def consecutive_passes(history: list[dict], gate: str) -> int:
    """Count trailing consecutive passes for `gate` (most recent first)."""
    n = 0
    for entry in reversed([h for h in history if h.get("gate") == gate]):
        if entry.get("passed"):
            n += 1
        else:
            break
    return n


def emit_audit(event: dict) -> None:
    """Write `event` as a write-once per-entry audit record (SPEC-888, #888 P2).

    The record lands under audit/log/<YYYY>/<MM>/ so two branches never touch the
    same file — the audit-log merge conflict is removed at its source rather than
    synced around. No-op when audit/ is absent (the original guard is preserved).
    """
    if Path("audit").is_dir():
        event = {**event, "timestamp": _now()}
        _AUDIT_LOG.write_event(event, root=".")


def run_gate(script: str) -> bool:
    """Run a gate script in --all mode; True if it passes (exit 0)."""
    if not Path(script).exists():
        return False
    try:
        r = subprocess.run(["bash", script, "--all"], capture_output=True, text=True, timeout=300)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def cmd_census(suspensions: list[Suspension], quiet: bool = False, text: str | None = None) -> None:
    """Print and audit active suspensions. Never makes a network call.

    Expired dates and malformed lines are flagged and NOT counted. An
    `until-closed:` line is not checked here (that needs the network).
    """
    today = _today()
    counts, loose_only = _gate_line_counts(text) if text is not None else ({}, set())
    active: list[Suspension] = []
    lines: list[str] = []
    for s in suspensions:
        malformed = s.malformed or counts.get(s.gate, 1) > 1
        expired = s.expires is not None and today > s.expires
        extra = []
        if s.pinned:
            extra.append("pinned")
        if s.review_by:
            overdue = s.review_by < today
            extra.append(f"review-by {s.review_by}" + (" ⚠ OVERDUE" if overdue else ""))
        if s.expires:
            extra.append(f"expires {s.expires}")
        if s.until_closed is not None:
            extra.append(f"until-closed #{s.until_closed}: not checked by census")
        tag = f" ({', '.join(extra)})" if extra else ""
        flag = ""
        if malformed:
            flag = " MALFORMED — not suppressing"
        elif expired:
            flag = " EXPIRED — no longer suppressing; remove this line"
        else:
            active.append(s)
        lines.append(f"  - {s.gate}{tag}{flag}")
    for gate in sorted(loose_only):
        if not any(s.gate == gate for s in suspensions):
            lines.append(f"  - {gate} MALFORMED — not suppressing")
    gates = [s.gate for s in active]
    if not quiet:
        print(f"Active suspensions: {len(gates)}")
        for line in lines:
            print(line)
    emit_audit(
        {"event": "suspension-census", "active_suspensions": len(gates), "suspended_gates": gates}
    )


def cmd_check(suspensions: list[Suspension]) -> None:
    for s in suspensions:
        script = AUTO_CHECKABLE_GATES.get(s.gate)
        if not script:
            continue  # not auto-checkable (reviewer role or dual gate) — skip
        passed = run_gate(script)
        record_check(s.gate, passed)
        print(f"  check {s.gate}: {'pass' if passed else 'fail'}")


def cmd_auto_remove(text: str, suspensions: list[Suspension]) -> str:
    """Return the (possibly modified) suspension-file text with eligible
    suspensions removed. NEVER adds a SUSPENDED line (ratchet)."""
    if not _read_config_bool("SUSPENSION_AUTO_REMOVE", True):
        print("auto-remove disabled (SUSPENSION_AUTO_REMOVE=false) — nudging only")
    auto = _read_config_bool("SUSPENSION_AUTO_REMOVE", True)
    needed = _read_config_int("SUSPENSION_AUTO_REMOVE_RUNS", 3)
    history = load_history()

    lines = text.splitlines(keepends=True)
    removed: list[str] = []
    for s in suspensions:
        eligible = s.gate in AUTO_CHECKABLE_GATES and not s.pinned
        passes = consecutive_passes(history, s.gate)
        if eligible and passes >= needed:
            if auto:
                lines = [ln for ln in lines if ln.rstrip("\n") != s.raw_line.rstrip("\n")]
                removed.append(s.gate)
                emit_audit(
                    {
                        "event": "gate-auto-reenabled",
                        "gate": s.gate,
                        "consecutive_passes": passes,
                    }
                )
                print(f"  auto-removed: {s.gate} (passed {passes} consecutive checks)")
            else:
                print(f"  NUDGE: {s.gate} now passes ({passes}×) — you may remove it")
        elif s.gate in AUTO_CHECKABLE_GATES and passes >= needed and s.pinned:
            print(f"  NUDGE: {s.gate} now passes but is [pinned] — remove manually")

    new_text = "".join(lines)
    if removed:
        new_text = _append_reenable_log(new_text, removed)
    return new_text


def _append_reenable_log(text: str, gates: list[str]) -> str:
    """Append rows to the Re-enable log table."""
    rows = "".join(
        f"| {g} | {_today()} | auto-removed after consecutive passes | suspension-manager |\n"
        for g in gates
    )
    if "## Re-enable log" in text:
        # Insert after the table header if present, else after the heading.
        return text.rstrip() + "\n" + rows
    return text.rstrip() + "\n\n## Re-enable log\n\n" + rows


def _read_reason_category(suspension_file: str) -> str:
    """Read reason_category from gate-suspension.md; return 'unspecified' if absent."""
    try:
        text = Path(suspension_file).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            low = line.strip().lower()
            if low.startswith("reason_category:"):
                val = line.split(":", 1)[1].strip().strip("'\"").upper()
                if val and not val.startswith("["):  # skip template placeholders
                    return val
    except (OSError, UnicodeDecodeError):
        pass
    return "unspecified"


def cmd_emit_audit(
    gate: str,
    authorized_by: str | None,
    step: str | None = None,
    suspension_file: str = SUSPENSION_FILE,
) -> int:
    """Append a `gate-suspended` event to audit/oversight-log.jsonl.

    Canonical home for the audit JSON that check_suspension.sh used to build by
    hand with printf (HOS#337). Now includes the three OVERSIGHT-CONTRACT §6a
    fields deferred from #337: step, suspension_file, reason_category (#397).
    No-op when audit/ is absent (the guard lives in emit_audit). Best-effort:
    always exits 0.
    """
    emit_audit(
        {
            "event": "gate-suspended",
            "gate": gate,
            "authorized_by": authorized_by or "unknown",
            "step": step or "unknown",
            "suspension_file": suspension_file,
            "reason_category": _read_reason_category(suspension_file),
        }
    )
    return 0


def cmd_is_suspended(gate: str) -> int:
    """Exit 0 only if gate's suspension status is `active`, exit 1 otherwise.

    Used by run_gates.sh to populate the 'suspended' field in gate-results.json
    without sourcing the bash check_suspension.sh helper. Expired, malformed and
    unknown all mean "not suspended" (D-4). A gate whose line has no
    `until-closed:` never makes a network call.
    """
    susp_path = Path(SUSPENSION_FILE)
    if not susp_path.exists():
        return 1
    status = suspension_status(susp_path.read_text(), gate)["status"]
    return 0 if status == STATUS_ACTIVE else 1


# ---------------------------------------------------------------------------
# #2214 — dep-mapper LOW suspension: manual trace, resolution check, disclosure
# ---------------------------------------------------------------------------

DEP_MAPPER_GATE = "dep-mapper"
_RISK_ASSESSMENT_PATH = ".claudetmp/oversight/validators/risk-assessment.md"
_STEP_MANIFEST_PATH = "contract/step-manifest.yaml"
_TIERS = ("SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL")
_SUSPENDED_RESOLUTION_RE = re.compile(
    r"^suspended:\s*(?P<gate>[a-z0-9-]+)\s*\(trace:\s*(?P<path>\S+)\)\s*$"
)
_DEP_VALID_RESOLUTION_RE = re.compile(r"^(unresolved\s*$|escalated:\s*\S|suspended:)", re.I)
_DISCLOSURE_HEADING = "## dep-mapper LOW disclosure (suspended blocker)"
# The orchestrator copies the trace's sections into the disclosure, headings included.
_DISCLOSURE_COPIED_HEADINGS = (
    "## Callers / readers checked",
    "## Items dep-mapper left untraced",
)


def dep_trace_path(step: str) -> str:
    """The single source for the manual-trace path."""
    return f".claudetmp/oversight/step{step}-dep-mapper-trace.md"


def _tier_rank(value) -> int:
    """Index in _TIERS; an absent or unparseable tier counts as CRITICAL (fail closed)."""
    v = str(value or "").strip().upper()
    return _TIERS.index(v) if v in _TIERS else len(_TIERS) - 1


def _git(
    args: list[str], repo_root, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess | None:
    """Run git in `repo_root` with a 60s timeout; None on timeout or OSError.

    `env` is overlaid on os.environ; only the origin lookup (§5.2.1) passes it. Replace refs
    are always disabled (GIT_NO_REPLACE_OBJECTS=1): refs/replace/<sha> could otherwise make
    show, ls-tree and diff return a forged object under the real SHA.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            timeout=60,
            env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", **(env or {})},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def changed_files_in_range(base_sha: str, head_sha: str, repo_root=".") -> list[str] | None:
    """Paths changed in base..head, renames split into delete + add; None on git failure.

    `--no-renames` keeps a renamed-away old path in the list, and `-z` keeps
    non-ASCII paths unquoted. Option-shaped revisions are refused.
    """
    if base_sha.startswith("-") or head_sha.startswith("-"):
        return None
    r = _git(
        ["diff", "--name-only", "--no-renames", "-z", f"{base_sha}..{head_sha}", "--"], repo_root
    )
    if r is None or r.returncode != 0:
        return None
    return [p for p in r.stdout.decode("utf-8", "replace").split("\0") if p]


_HEX_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SYMREF_RE = re.compile(r"^ref: refs/heads/(?P<d>[^\t]+)$")
_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _stderr_line(r: subprocess.CompletedProcess) -> str:
    text = r.stderr.decode("utf-8", "replace")
    return next((ln.strip() for ln in text.split("\n") if ln.strip()), "")[:200]


def _default_ls_remote(repo_root=".") -> tuple[str | None, str | None, str | None]:
    """(default branch, its SHA, None) from `git ls-remote --symref origin HEAD`, or
    (None, None, reason). Only lines whose second field is exactly HEAD are used, and
    each kind of line must appear once, so pushed decoy refs such as x/HEAD are ignored
    (AR4-4). The local origin/HEAD is never read: an agent can repoint it (AR4-1)."""
    r = _git(
        ["ls-remote", "--symref", "--exit-code", "origin", "HEAD"],
        repo_root,
        env={"GIT_TERMINAL_PROMPT": "0"},
    )
    if r is None:
        return None, None, "git ls-remote did not complete within 60s or could not be started"
    if r.returncode == 2:
        return None, None, "origin reports no HEAD"
    if r.returncode != 0:
        return None, None, f"exit {r.returncode}: {_stderr_line(r)}"
    symrefs: list[str] = []
    shas: list[str] = []
    for raw in r.stdout.decode("utf-8", "replace").split("\n"):
        fields = raw.removesuffix("\r").split("\t")
        if len(fields) != 2 or fields[1] != "HEAD":
            continue
        m = _SYMREF_RE.match(fields[0])
        if m:
            symrefs.append(m.group("d"))
        elif _HEX_SHA_RE.match(fields[0]):
            shas.append(fields[0])
    if not symrefs:
        return (
            None,
            None,
            'origin did not report its default branch (no "ref: refs/heads/... HEAD" line)',
        )
    if len(symrefs) > 1 or len(shas) != 1:
        return None, None, "ambiguous or incomplete ls-remote output for HEAD"
    d = symrefs[0]
    if not _BRANCH_NAME_RE.match(d) or d.startswith("-") or ".." in d:
        return None, None, "unusable default-branch name from origin"
    return d, shas[0], None


def read_default_branch_suspension(repo_root=".", ls_remote=None) -> dict:
    """The fixed suspension file as it is on origin's default branch (D-16, §5.2.1).

    Returns {text, error, sha, branch}. The default branch and its SHA come from the
    remote in one call; the local origin/<D> must equal that SHA (E-F1, E-F3), and the
    file is read at the verified SHA, so nothing moves between the check and the read.
    `text` is None on every error path, and also, with `error` None, when the file does
    not exist at that commit. Never fetches.
    """
    out: dict = {"text": None, "error": None, "sha": None, "branch": None}
    d, remote_sha, reason = (ls_remote or _default_ls_remote)(repo_root)
    if d is None or remote_sha is None:
        out["error"] = (
            f"S4: could not confirm origin/{d or 'HEAD'} is current ({reason}); failing closed. "
            "Check network access and the GitHub token, then re-run"
        )
        return out
    out["branch"] = d
    r = _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{d}^{{commit}}"], repo_root)
    local = r.stdout.decode().strip() if r is not None and r.returncode == 0 else ""
    if not _HEX_SHA_RE.match(local):
        out["error"] = f"S4: local ref origin/{d} not found; run 'git fetch origin' and re-run"
        return out
    if local != remote_sha:
        out["error"] = (
            f"S4: local origin/{d} is {local[:12]} but origin has {remote_sha[:12]}; the "
            "default-branch suspension may have been revoked or changed. "
            "Run 'git fetch origin' and re-run"
        )
        return out
    out["sha"] = remote_sha

    def read_failed(why: str) -> dict:
        out["error"] = (
            f"S4: could not read {SUSPENSION_FILE} at origin/{d} {remote_sha[:12]} ({why}); "
            "failing closed, re-run"
        )
        return out

    tree = _git(["ls-tree", "-z", remote_sha, "--", SUSPENSION_FILE], repo_root)
    if tree is None:
        return read_failed("timeout")
    if tree.returncode != 0:
        return read_failed(f"exit {tree.returncode}: {_stderr_line(tree)}")
    entries = [e for e in tree.stdout.decode("utf-8", "replace").split("\0") if e]
    if not entries:
        return out
    if len(entries) != 1 or not re.fullmatch(
        r"100644 blob [0-9a-f]{40,64}\t" + re.escape(SUSPENSION_FILE), entries[0]
    ):
        return read_failed("not a regular file")
    shown = _git(["show", f"{remote_sha}:{SUSPENSION_FILE}"], repo_root)
    if shown is None:
        return read_failed("timeout")
    if shown.returncode != 0:
        return read_failed(f"exit {shown.returncode}: {_stderr_line(shown)}")
    out["text"] = shown.stdout.decode("utf-8", "replace")
    return out


def read_exact_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def _yaml_scalar(value: str) -> str:
    """A YAML scalar minus an inline `# comment` and surrounding quotes."""
    return re.sub(r"(^|\s)#.*$", "", value).strip().strip("\"'")


_ANCHOR_RE = re.compile(r"(?:^|[:\-,\[{])\s*[&*][A-Za-z0-9_-]+")
_MERGE_KEY_RE = re.compile(r"""(?:^|[\s\-{,])["']?<<["']?\s*:""")


def manifest_human_gate_required(manifest_path, step) -> bool:
    """Is `step` behind the human gate per step-manifest.yaml? Fails closed.

    Canonical form or fail closed: an absent manifest -> False (TD D-17), but a
    manifest that exists and is anything other than plainly parsed -> True. That
    covers: unreadable / undecodable, no `steps:` block, `step` not listed, a
    `human_gate_required` value other than true/false/yes/no/1/0, YAML merge keys
    (`<<:`), anchors or aliases, a flow-style step item or flow collection
    mentioning `id` / `human_gate_required`, and any `human_gate_required` token
    inside the target step that was not consumed as a canonical key (duplicate,
    nested or mis-indented). A step that omits the key -> False. Keys and values
    are normalised (quotes, inline comments); step items are recognised by the
    indent of the first `- ` under `steps:`, and `id:` may appear anywhere in the
    item. Same line-scan approach as gate_compliance.gates_required (stdlib only).
    """
    path = Path(manifest_path)
    if not path.exists():
        return False
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return True
    in_steps = False
    item_indent: int | None = None
    key_indent: int | None = None
    items: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code = re.sub(r"(^|\s)#.*$", "", line)
        if _MERGE_KEY_RE.search(code) or _ANCHOR_RE.search(code):
            return True
        indent = len(line) - len(line.lstrip())
        if not in_steps:
            if re.match(r"steps:(\s|$)", line):
                in_steps = True
                if re.match(r"steps:\s*[\[{]", line):
                    return True
            continue
        if indent == 0 and not stripped.startswith("-"):
            in_steps = False
            continue
        if stripped.startswith("-") and (item_indent is None or indent == item_indent):
            item_indent = indent
            items.append({"raw_hgr": 0})
            body = stripped[1:].lstrip()
            key_indent = len(line) - len(body)
            stripped = body
            indent = key_indent
            if body.startswith(("{", "[")):
                return True
        if re.search(r"\{", code) and re.search(r"human_gate_required|\bid\b", code):
            return True
        if not items:
            continue
        if "human_gate_required" in code:
            items[-1]["raw_hgr"] += 1
        if indent != key_indent or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = _yaml_scalar(key)
        if key in ("id", "human_gate_required"):
            items[-1].setdefault(key, _yaml_scalar(value))
    target = [it for it in items if it.get("id") == str(step)]
    if not target:
        return True
    for it in target:
        flag = it.get("human_gate_required")
        if it["raw_hgr"] != (0 if flag is None else 1):
            return True
        if flag is None:
            continue
        if flag.lower() in ("false", "no", "0"):
            continue
        return True
    return False


def _split_lines(text: str | None) -> list[str]:
    """R0: normalise CR/CRLF, then split on "\\n" only.

    str.splitlines() also breaks on U+000B, U+000C, U+001C-U+001E, U+0085, U+2028 and
    U+2029, which CommonMark treats as ordinary characters, so the validator and GitHub
    would disagree about where a line starts.
    """
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _section_span(lines: list[str], heading: str) -> tuple[int, list[str]] | None:
    """(index of the first section line, section lines) under `heading`, up to the next
    `## ` line; None if the heading is absent. The heading is at column 0, trailing
    spaces allowed, so a copy of it is a copied heading in the disclosure (D-21)."""
    for i, line in enumerate(lines):
        if line.rstrip(" ") == heading:
            out: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                out.append(nxt)
            return i + 1, out
    return None


def _section_lines(text: str, heading: str) -> list[str] | None:
    span = _section_span(_split_lines(text), heading)
    return None if span is None else span[1]


def _table_cells(line: str) -> list[str]:
    """Cells of a table row. At most one outer pipe is dropped on each side (as
    _cell_count does), so "|| a |" keeps its empty first cell."""
    text = line.strip()
    text = text[1:] if text.startswith("|") else text
    text = text[:-1] if text.endswith("|") else text
    return [c.strip() for c in text.split("|")]


_TRACE_RESULT_PREFIXES = ("pass", "no impact", "n/a")

# ---------------------------------------------------------------------------
# Disclosure visibility allowlist (AM-1, D-19..D-21; #2349)
#
# The disclosure section of the PR body must be plain visible text. Instead of
# denying known-bad constructs (which never converged), every raw line of the
# section must match a closed line grammar (R1-R7), and the prefix before the
# heading must be the fixed AI-Submitted block (P0-P9). The trace's two copied
# sections are held to the same rules at trace time (V9).
# ---------------------------------------------------------------------------

_AI_SUBMITTED_HEADING = "## 🤖 AI-Submitted Pull Request"
_ATX_HEADING_RE = re.compile(r"^#{1,6}( |$)")
_ATTRIBUTION_LINE = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
# R1: ASCII letters, digits, space and the punctuation below; "|" is added for table rows.
_R1_ALLOWED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789" " .,:;()/-_'\"!?=+%#@{}^—–→§"
)
_R3_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789(./\"'")
# ":name:" candidates, overlapping so a rejected all-digit span such as ":100:" cannot hide
# a real shortcode that starts at its closing colon. Linear: a name run ends at a colon.
_SHORTCODE_CANDIDATE_RE = re.compile(r"(?=:([a-z0-9_+-]+):)", re.I)
_NON_DIGIT_NAME_RE = re.compile(r"[a-z_+-]", re.I)
_DELIMITER_ROW_RE = re.compile(r"^\|( *:?-+:? *\|)+$")
_CONTAINER_PREFIX_RE = re.compile(r"^[ \t]*(?:>|[-*+][ \t]|\d{1,9}[.)][ \t])")
_PLAIN_LINK = re.compile(r"(?<!!)\[[^\[\]\n]*\]\([^\s()<>\"']*\)")
_CALLERS_HEADING, _ITEMS_HEADING = _DISCLOSURE_COPIED_HEADINGS
_NO_TABLE_IN_ITEMS = (
    "table rows are not allowed here (the disclosure carries one table, the callers table)"
)

# (line number or None, message without its "disclosure line <k>: " prefix)
_RuleError = tuple[int | None, str]


def _char_label(c: str) -> str:
    shown = c if c.isprintable() else c.encode("unicode_escape").decode("ascii")
    return f'"{shown}" (U+{ord(c):04X})'


def _prefix_line_errors(line: str, k: int) -> list[str]:
    """P0-P5 for one prefix line (the lines before the disclosure heading)."""
    pre = f"disclosure prefix line {k}: "
    out: list[str] = []
    for c in line:
        if (unicodedata.category(c) == "Cc" and c != "\t") or c in "\u2028\u2029":
            out.append(
                f"{pre}control or line-separator character U+{ord(c):04X} "
                "before the disclosure heading"
            )
            break
    rest = line
    while (m := _CONTAINER_PREFIX_RE.match(rest)) is not None:
        rest = rest[m.end() :]
    rest = rest.lstrip(" \t")
    where = "place the disclosure section directly after the AI-Submitted block"
    if rest.startswith(("```", "~~~")):
        out.append(
            f"{pre}code fence before the disclosure heading (GitHub may render the "
            f"disclosure as code, math or a diagram); {where}"
        )
    if "$" in line:
        out.append(
            f'{pre}"$" before the disclosure heading (GitHub math can hide the '
            f"disclosure); {where}"
        )
    if re.search(r"<[A-Za-z/?!]", line):
        out.append(
            f"{pre}raw HTML before the disclosure heading, which GitHub may hide or "
            f"collapse; {where}"
        )
    if "]:" in line:
        out.append(f'{pre}"]:" (link-reference definition) before the disclosure heading')
    leftover = _PLAIN_LINK.sub("", line)
    if any(tok in leftover for tok in ("](", "][", "![")):
        out.append(f"{pre}link with a title, reference link or image before the disclosure heading")
    return out


def _prefix_errors(lines: list[str], h: int) -> list[str]:
    """P0-P5 and P7-P9 for lines[:h], where lines[h] is the disclosure heading."""
    errors: list[str] = []
    if not h or lines[0].rstrip(" ") != _AI_SUBMITTED_HEADING:
        errors.append(
            f'disclosure prefix line 1: the PR body must start with "{_AI_SUBMITTED_HEADING}"'
        )
    for i in range(h):
        errors.extend(_prefix_line_errors(lines[i], i + 1))
        if i and _ATX_HEADING_RE.match(lines[i]):
            errors.append(
                f"disclosure prefix line {i + 1}: heading before the disclosure heading; "
                "place the disclosure section directly after the AI-Submitted block"
            )
    if h and lines[h - 1].rstrip(" "):
        errors.append(
            f"disclosure prefix line {h}: the line before the disclosure heading must be blank"
        )
    return errors


def _line_kind(line: str) -> str:
    """A blank, B copied heading, C attribution literal, D table row, E prose or bullet.
    `line` has no trailing spaces."""
    if not line:
        return "A"
    if line in _DISCLOSURE_COPIED_HEADINGS:
        return "B"
    if line == _ATTRIBUTION_LINE:
        return "C"
    return "D" if line.startswith("|") else "E"


def _text_rule_error(line: str, kind: str) -> str | None:
    """R1-R4 for one Kind D or E line; only the first rule it breaks is reported."""
    allowed = (_R1_ALLOWED | {"|"}) if kind == "D" else _R1_ALLOWED
    bad = next((c for c in line if c not in allowed), None)
    if bad is not None:
        return (
            f"character {_char_label(bad)} is not allowed in the disclosure section; allowed "
            "are letters, digits, spaces and . , : ; ( ) / - _ ' \" ! ? = + % # @ { } ^ "
            '— – → §, plus "|" in table rows'
        )
    if kind == "E":
        rest = line.lstrip(" ")
        if len(line) - len(rest) > 3:
            return "indented 4 or more spaces (GitHub renders it as code); use at most 3"
        if not (rest[0] in _R3_START or (rest.startswith("- ") and rest[2:3] in _R3_START)):
            return (
                'line must start with a letter, digit, "(", ".", "/" or a quote, or with '
                f'"- " directly followed by one; found "{rest[:3]}"'
            )
    # A delimiter row holds only | : - and spaces; ":---:" is alignment, not a shortcode.
    name = None if _DELIMITER_ROW_RE.match(line) else _emoji_shortcode(line)
    if name:
        return f'":{name}:" may render as an emoji instead of text; reword it'
    return None


def _emoji_shortcode(text: str) -> str | None:
    """The name of the first ":name:" in `text` that has a non-digit character, else None.
    All-digit forms such as ":05:" are not matched (residual R-8)."""
    for m in _SHORTCODE_CANDIDATE_RE.finditer(text):
        if _NON_DIGIT_NAME_RE.search(m.group(1)):
            return m.group(1)
    return None


def _cell_count(line: str) -> int:
    body = line[1:]
    return len((body[:-1] if body.endswith("|") else body).split("|"))


def _table_block_errors(
    lines: list[str], s: int, e: int, kind_d: list[int], mode: str
) -> list[_RuleError]:
    """R5 for the Kind D lines (indexes into `lines`) of the section lines[s:e].

    `mode` is "disclosure", or "callers" for the trace's callers section, whose own
    heading (the line before `s`) counts as Kind B for R5(d) (AR2-5). The end of a
    trace section is not treated as EOF: a table running into the next heading fails.
    """
    out: list[_RuleError] = []
    first = [kind_d[0]]
    for i in kind_d[1:]:
        if i != first[-1] + 1:
            out.append((None, f"section has more than one table (line {i + 1})"))
            break
        first.append(i)
    head, rows = first[0], first[1:]
    for i in first:
        if len(lines[i].rstrip(" ")) < 2 or not lines[i].rstrip(" ").endswith("|"):
            out.append((i + 1, 'table row must start and end with "|"'))
    n = _cell_count(lines[head].rstrip(" "))
    delim = lines[first[1]].rstrip(" ") if len(first) > 1 else ""
    if not _DELIMITER_ROW_RE.match(delim) or _cell_count(delim) != n:
        out.append((None, "callers table has no delimiter row matching its header"))
    for i in rows[1:]:
        m = _cell_count(lines[i].rstrip(" "))
        if m != n:
            out.append((i + 1, f"table row has {m} cells, header has {n}"))
    before_ok = (head == s and mode == "callers") or (
        head > 0 and _line_kind(lines[head - 1].rstrip(" ")) in "AB"
    )
    after = first[-1] + 1
    after_ok = after >= len(lines) or not lines[after].rstrip(" ")
    if not (before_ok and after_ok):
        out.append(
            (
                head + 1 if not before_ok else after + 1,
                "table must have a blank line or section heading before it and a blank "
                "line after it",
            )
        )
    if mode == "disclosure":
        heads = {
            h: next((i for i in range(s, e) if lines[i].rstrip(" ") == h), None)
            for h in _DISCLOSURE_COPIED_HEADINGS
        }
        c, it = heads[_CALLERS_HEADING], heads[_ITEMS_HEADING]
        if c is None or head < c or (it is not None and head > it):
            out.append(
                (
                    head + 1,
                    f'the table must be the copied callers table, under "{_CALLERS_HEADING}"',
                )
            )
    return out


def _section_grammar_errors(lines: list[str], s: int, e: int, mode: str) -> list[_RuleError]:
    """R1-R5 for the section lines[s:e] (R6 and R7 belong to the disclosure's own end).

    `mode`: "disclosure", "callers" (a trace section that may hold the callers table) or
    "items" (a trace section that may hold no table row at all, AR2-4).
    """
    out: list[_RuleError] = []
    seen: list[str] = []
    kind_d: list[int] = []
    for i in range(s, e):
        line = lines[i].rstrip(" ")
        kind = _line_kind(line)
        k = i + 1
        if kind == "B":
            if line in seen or (line == _ITEMS_HEADING and _CALLERS_HEADING not in seen):
                out.append((k, f'copied heading "{line}" repeated or out of order'))
            seen.append(line)
        elif kind == "D" and mode == "items":
            out.append((k, _NO_TABLE_IN_ITEMS))
        elif kind in "DE":
            if kind == "D":
                kind_d.append(i)
            msg = _text_rule_error(line, kind)
            if msg:
                out.append((k, msg))
    if kind_d:
        out.extend(_table_block_errors(lines, s, e, kind_d, mode))
    return out


_CLOSING_KEYWORDS_PATH = (
    Path(__file__).resolve().parent.parent / "automation" / "closing_keywords.py"
)


def _closing_ref_errors(lines: list[str], s: int, e: int) -> list[_RuleError]:
    """R8: no GitHub closing reference in the section lines[s:e] (AM-3).

    Runs the real guard grammar (closing_keywords.find_closing_refs) over the joined lines,
    because a keyword can end one line and its reference start the next. The slug "_/_"
    makes every match an error. If the module cannot be loaded, the check fails closed.
    """
    try:
        spec = importlib.util.spec_from_file_location("closing_keywords", _CLOSING_KEYWORDS_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        matches = module.find_closing_refs("\n".join(lines[s:e]), "_/_")
    except Exception:  # fail closed: any load or call failure
        return [
            (
                None,
                "cannot be checked for closing references: closing_keywords.py could not be loaded",
            )
        ]
    return [
        (
            s + m.line,
            f'"{m.snippet}" is a GitHub closing reference to {m.key}; merging the PR would '
            'close it. Reword it (for example "issue N")',
        )
        for m in matches
    ]


def _format_disclosure_error(err: _RuleError) -> str:
    k, msg = err
    return f"disclosure line {k}: {msg}" if k is not None else f"disclosure {msg}"


def _value_fails_line_rules(value: str) -> bool:
    """True when `value` (the suspension's "Authorized by:" text) cannot be written into
    the disclosure section: it breaks R1 (character set) or R4 (emoji shortcode)."""
    return any(c not in _R1_ALLOWED for c in value) or _emoji_shortcode(value) is not None


def validate_dep_trace(
    text: str, step: str, base_sha: str, head_sha: str, changed_files: list[str]
) -> dict:
    """Structurally validate a dep-mapper manual trace (V1-V9). Collects every error.

    Proves a trace exists, covers the diff, claims PASS, and that its two copied
    sections can be written into the disclosure unchanged (V9, D-21). It cannot prove
    the trace is true (D-12). Every rule splits lines as R0 specifies, so the line
    numbers in V9 agree with the file.
    """
    errors: list[str] = []
    lines = _split_lines(text)

    first = next((ln for ln in lines if ln.strip()), "")
    m = re.match(r"^# dep-mapper manual trace [—-] step (\S+)\s*$", first)
    if not m:
        errors.append("V1: first line is not '# dep-mapper manual trace — step {N}'")
    elif m.group(1) != str(step):
        errors.append(f"V1: trace is for step {m.group(1)!r}, expected {str(step)!r}")

    expected_range = f"{base_sha}..{head_sha}"
    range_vals = [
        ln.strip().split(":", 1)[1].strip() for ln in lines if ln.strip().startswith("Range:")
    ]
    if not range_vals:
        errors.append("V2: no 'Range:' line")
    elif range_vals[0] != expected_range:
        errors.append(f"V2: Range {range_vals[0]!r} != {expected_range!r} (stale trace)")

    if not any(
        ln.strip().startswith("dep-mapper result:") and "Data confidence: LOW" in ln for ln in lines
    ):
        errors.append("V3: no 'dep-mapper result:' line containing 'Data confidence: LOW'")

    data_rows: list[list[str]] = []
    section = _section_lines(text, _CALLERS_HEADING)
    table = [ln for ln in (section or []) if ln.strip().startswith("|")]
    if not table:
        errors.append("V4: no table under '## Callers / readers checked'")
    else:
        header = _table_cells(table[0])
        if header[0] != "Changed file" or header[-1] != "Result":
            errors.append("V4: table header must start 'Changed file' and end 'Result'")
        data_rows = [
            _table_cells(r)
            for r in table[1:]
            if not all(re.fullmatch(r":?-+:?", c) for c in _table_cells(r))
        ]
        if not data_rows:
            errors.append("V4: table has no data rows")

    first_cells = [r[0].replace("`", "") for r in data_rows]
    for path in changed_files:
        if path.startswith(("tests/", "audit/")):
            continue
        rx = re.compile(r"(?:^|[\s,(])" + re.escape(path) + r"(?:$|[\s,)])")
        if not any(rx.search(cell) for cell in first_cells):
            errors.append(f"V5: changed file not covered by any trace row: {path}")

    for row in data_rows:
        result = row[-1].replace("`", "").replace("*", "").strip().lower()
        if result.startswith("fail"):
            errors.append(f"V6: trace reports a failing caller (row: {row[0]})")
        elif not result.startswith(_TRACE_RESULT_PREFIXES):
            errors.append(f"V6: unrecognised result {row[-1]!r} (row: {row[0]})")

    untraced = _section_lines(text, _ITEMS_HEADING)
    if untraced is None or not any(ln.strip() for ln in untraced):
        errors.append("V7: '## Items dep-mapper left untraced' missing or empty")

    conclusion = _section_lines(text, "## Conclusion")
    if conclusion is None or not any(
        re.fullmatch(r"Result:\s*PASS", ln.strip()) for ln in conclusion
    ):
        errors.append("V8: '## Conclusion' has no 'Result: PASS' line")

    for heading, mode in ((_CALLERS_HEADING, "callers"), (_ITEMS_HEADING, "items")):
        span = _section_span(lines, heading)
        if span is not None:
            start, body = span
            end = start + len(body)
            for k, msg in _section_grammar_errors(lines, start, end, mode) + _closing_ref_errors(
                lines, start, end
            ):
                where = f"{heading} line {k}" if k is not None else heading
                errors.append(f"V9: {where}: {msg}")

    return {"valid": not errors, "errors": errors}


def _trace_table(text: str) -> tuple[list[str] | None, list[list[str]]]:
    """(header cells, data rows) of the '## Callers / readers checked' table."""
    return _table_from_lines(_section_lines(text, "## Callers / readers checked") or [])


def _table_from_lines(lines: list[str]) -> tuple[list[str] | None, list[list[str]]]:
    table = [ln for ln in lines if ln.strip().startswith("|")]
    if not table:
        return None, []
    rows = [
        _table_cells(r)
        for r in table[1:]
        if not all(re.fullmatch(r":?-+:?", c) for c in _table_cells(r))
    ]
    return _table_cells(table[0]), rows


def _norm_cells(cells: list[str]) -> tuple[str, ...]:
    return tuple(" ".join(c.split()) for c in cells)


def _authorized_by(suspension_text: str) -> str | None:
    for line in _candidate_lines(suspension_text):
        m = re.match(r"^Authorized by:\s*(\S.*?)\s*$", line)
        if m:
            return m.group(1)
    return None


def validate_disclosure(
    handoff_text: str, step: str, trace_text: str, suspension_text: str
) -> dict:
    """Check the PR-body disclosure section (§5.3) against the validated trace (#2349).

    The section is checked as visible text by an allowlist (AM-1, D-19..D-21): every
    raw line must match the line grammar R1-R7, and the lines before the heading must
    be the fixed AI-Submitted block (P0-P9). Nothing is stripped first, and the text
    after the section is not checked (D-20). Beyond that, the disclosed callers table
    must equal the trace's (header and every row, in order), every non-blank 'untraced'
    line of the trace must appear, and the disclosed authorizer / expiry /
    until-closed must match the default-branch suspension. Proves the disclosure
    repeats the trace; it cannot prove the trace is true (D-12). `trace_text` and
    `suspension_text` are required: with nothing to compare against, the check fails
    closed.
    """
    lines = _split_lines(handoff_text)
    heads = [i for i, ln in enumerate(lines) if ln.rstrip(" ") == _DISCLOSURE_HEADING]
    if not heads:
        return {"valid": False, "errors": [f"disclosure heading missing: {_DISCLOSURE_HEADING}"]}
    if len(heads) > 1:
        return {
            "valid": False,
            "errors": [f"disclosure heading appears {len(heads)} times; exactly one is allowed"],
        }
    h = heads[0]
    s = h + 1
    e = next(
        (
            i
            for i in range(s, len(lines))
            if _ATX_HEADING_RE.match(lines[i])
            and lines[i].rstrip(" ") not in _DISCLOSURE_COPIED_HEADINGS
        ),
        len(lines),
    )
    section = lines[s:e]
    body = "\n".join(section)
    errors = _prefix_errors(lines, h)
    errors.extend(
        _format_disclosure_error(err) for err in _section_grammar_errors(lines, s, e, "disclosure")
    )
    if section and e < len(lines) and section[-1].rstrip(" "):
        errors.append(
            f"disclosure line {e}: the line before the heading that ends the disclosure "
            "section must be blank"
        )
    errors.extend(_format_disclosure_error(err) for err in _closing_ref_errors(lines, s, e))
    for token in ("Data confidence: LOW", "contract/gate-suspension.md", dep_trace_path(step)):
        if token not in body:
            errors.append(f"disclosure missing {token!r}")
    if not any(ln.startswith("| Changed file") for ln in section):
        errors.append("disclosure missing the copied trace table ('| Changed file')")
    if not any(re.fullmatch(r"Result:\s*PASS\s*", ln) for ln in section):
        errors.append("disclosure missing 'Result: PASS'")

    # Callers table: header and rows must equal the trace's.
    t_header, t_rows = _trace_table(trace_text or "")
    if t_header is None or not t_rows:
        errors.append("disclosure cannot be compared: trace has no callers table")
    else:
        d_header, d_rows = _table_from_lines(section)
        if d_header is None or _norm_cells(d_header) != _norm_cells(t_header):
            errors.append("disclosed callers table header differs from the trace")
        d_norm = [_norm_cells(r) for r in d_rows]
        t_norm = [_norm_cells(r) for r in t_rows]
        for r in t_norm:
            if r not in d_norm:
                errors.append(f"disclosed callers table omits or alters trace row: {r[0]}")
        for r in d_norm:
            if r not in t_norm:
                errors.append(f"disclosed callers table has a row not in the trace: {r[0]}")
        if set(t_norm) == set(d_norm) and t_norm != d_norm:
            errors.append("disclosed callers table rows differ from the trace in order or count")

    # Untraced items: the copied heading, then the trace's non-blank lines exactly (same
    # order and count, nothing extra) up to the closing "Result: PASS" line.
    want = [" ".join(ln.split()) for ln in _section_lines(trace_text or "", _ITEMS_HEADING) or []]
    want = [ln for ln in want if ln]
    heads = [i for i, ln in enumerate(section) if ln.rstrip(" ") == _ITEMS_HEADING]
    if not heads:
        errors.append(f"disclosure missing the copied heading {_ITEMS_HEADING!r}")
    else:
        got = [" ".join(ln.split()) for ln in section[heads[0] + 1 :]]
        got = [ln for ln in got if ln]
        while got and got[-1] == _ATTRIBUTION_LINE:  # Kind C, if the section runs to EOF
            got.pop()
        if got and re.fullmatch(r"Result:\s*PASS", got[-1]):
            got.pop()
        for ln in (Counter(want) - Counter(got)).elements():
            errors.append(f"disclosure omits untraced item: {ln[:80]}")
        for ln in (Counter(got) - Counter(want)).elements():
            errors.append(
                f"disclosure has a line under {_ITEMS_HEADING!r} that is not in the trace: "
                f"{ln[:80]}"
            )
        if got != want and Counter(got) == Counter(want):
            errors.append("disclosed untraced items differ from the trace in order or count")

    # Authorizer / expiry / until-closed must match the suspension.
    by = _authorized_by(suspension_text or "")
    sus = [s for s in parse_suspensions(suspension_text or "") if s.gate == DEP_MAPPER_GATE]
    if by is None or len(sus) != 1:
        errors.append("disclosure cannot be compared: suspension authorizer or line not found")
    else:
        got_by = re.findall(r"Authorized by:[ \t]*(.*?)(?=\s*[;]|\s*$)", body, re.M)
        if _value_fails_line_rules(by):
            errors.append(
                'suspension "Authorized by:" value contains characters the disclosure section '
                "cannot carry; a human must change contract/gate-suspension.md"
            )
        elif not got_by or any(v != by for v in got_by):
            errors.append(f"disclosure does not state exactly 'Authorized by: {by}'")
        want_exp = sus[0].expires or "none"
        want_uc = f"issue {sus[0].until_closed}" if sus[0].until_closed is not None else "none"
        got_exp = re.findall(r"expires:\s*(\d{4}-\d{2}-\d{2}|none)", body)
        # "until-closed: #N" would read as "closed #N" to the closing-keyword guard (AM-3)
        got_uc = [
            "none" if m.group(1) == "none" else f"issue {int(m.group(2))}"
            for m in re.finditer(r"until-closed:[ \t]*(issue[ \t]+(\d+)|none)(?![0-9A-Za-z])", body)
        ]
        if re.search(r"until-closed:\s*(?:#|GH-)\d+", body, re.I):
            errors.append(
                'disclosure writes until-closed as "#N"; GitHub\'s closing-keyword guard '
                '(scripts/automation/closing_keywords.py) reads "closed #N" as closing issue N, '
                'so write "until-closed: issue N"'
            )
        if not got_exp or any(v != want_exp for v in got_exp):
            errors.append(f"disclosed expiry {got_exp or 'absent'} != suspension {want_exp!r}")
        if not got_uc or any(v != want_uc for v in got_uc):
            errors.append(f"disclosed until-closed {got_uc or 'absent'} != suspension {want_uc!r}")
    return {"valid": not errors, "errors": errors}


def parse_blocking_findings(text: str) -> list[dict]:
    """Parse the `blocking_findings:` block of risk-assessment.md.

    Blank lines and `#` comment lines (at any indent) never end the block; it
    ends at the first other line that is neither indented nor a list item. Keys and
    values are normalised with `_yaml_scalar` (quotes and inline comments dropped).
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^blocking_findings:", ln)), None)
    if start is None:
        return []
    inline = lines[start].split(":", 1)[1].split("#", 1)[0].strip()
    if inline == "[]":
        return []
    findings: list[dict] = []
    current: dict | None = None
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if not line[0].isspace() and not stripped.startswith("- "):
            break
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
            current = {}
            findings.append(current)
        if current is None or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = _yaml_scalar(key).lower()
        value = _yaml_scalar(value)
        if key == "source":
            value = value.lower()
        current[key] = value
    return findings


def _header_fields(text: str) -> tuple[dict, set[str]]:
    """Top-level `key: value` lines before `blocking_findings:` / the first `## ` heading.

    Indented and comment lines are skipped, values are normalised, the first
    occurrence of a key wins, and keys seen more than once are returned too so
    the caller can fail closed.
    """
    fields: dict = {}
    dups: set[str] = set()
    for line in text.splitlines():
        if line.startswith("## ") or re.match(r"^blocking_findings\s*:", line):
            break
        if not line.strip() or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = _yaml_scalar(key).lower()
        if key in fields:
            dups.add(key)
            continue
        fields[key] = _yaml_scalar(value)
    return fields, dups


# Un-anchored on purpose: a token hidden in a flow mapping, after a `- `, or mid-line
# must still be counted. Only `#`-comment lines are skipped (template examples).
_DEP_SOURCE_TOKEN_RE = re.compile(r"""(?i)\bsource["']?\s*:\s*["']?dep-mapper\b""")
_SUSPENDED_TOKEN_RE = re.compile(r"""(?i)\bresolution["']?\s*:\s*["']?suspended:""")


def _count_tokens(text: str, rx: re.Pattern) -> int:
    return sum(
        len(rx.findall(line)) for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def has_flow_findings(text: str) -> bool:
    """True if the `blocking_findings:` block uses flow style (not canonical form).

    The literal empty list `blocking_findings: []` is fine. Anything else flow-like
    is flagged: an inline non-empty collection, a list item or value that begins
    with `{` or `[`, or a `{` outside quotes.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^blocking_findings:", ln)), None)
    if start is None:
        return False
    inline = _yaml_scalar(lines[start].split(":", 1)[1])
    if inline == "[]":
        return False
    if inline:
        return True
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace() and not stripped.startswith("- "):
            break
        code = re.sub(r"(^|\s)#.*$", "", stripped)
        if code.startswith("- "):
            code = code[2:].strip()
        if code.startswith(("{", "[")):
            return True
        _, sep, value = code.partition(":")
        if sep and value.strip().startswith(("{", "[")):
            return True
        if "{" in re.sub(r"""("[^"]*"|'[^']*')""", "", code):
            return True
    return False


_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def is_full_sha(value) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA_RE.match(value))


def suspension_applies(risk_text: str) -> bool:
    """True when the assessment holds a `suspended:` resolution or a dep-mapper finding.

    Fails closed: a raw `source: dep-mapper` line anywhere counts, even one the
    parser did not attribute to a finding.
    """
    findings = parse_blocking_findings(risk_text)
    return bool(
        has_flow_findings(risk_text)
        or _count_tokens(risk_text, _SUSPENDED_TOKEN_RE)
        or _count_tokens(risk_text, _DEP_SOURCE_TOKEN_RE)
        or any(f.get("resolution", "").lower().startswith("suspended:") for f in findings)
        or any(f.get("source") == DEP_MAPPER_GATE for f in findings)
    )


def check_suspended_resolutions(
    risk_text: str,
    step: str,
    base_sha: str,
    head_sha: str,
    tier: str,
    human_gate_required: bool,
    changed_files: list[str],
    main_suspension_text: str | None,
    worktree_suspension_text: str | None,
    handoff_text: str | None = None,
    require_disclosure: bool = False,
    today: str | None = None,
    issue_state: IssueState | None = None,
    read_text: Callable[[str], str | None] | None = None,
    repo_root=".",
    *,
    main_suspension_error: str | None,
) -> dict:
    """Decide whether `suspended:` blocking-finding resolutions are valid (S0-S7).

    `main_suspension_error` is required: it is the reader's `error` for the default-branch
    suspension (§5.2.1). When set, S4 fails with that message, so a caller cannot skip
    the freshness check. This function never makes the network call itself.

    Returns {applies, ok, findings: [{id, ok, errors}], errors}. `errors` holds
    whole-file (S0) failures. Everything is re-derived: the tier is raised to the
    assessment's validated_tier (absent -> CRITICAL), and the suspension must be
    the default-branch copy, recomputed as `active` here. `repo_root` is where the
    default trace reader resolves relative paths (an addition to the TD signature).
    """
    step = str(step)
    findings = parse_blocking_findings(risk_text)
    raw_count = _count_tokens(risk_text, _SUSPENDED_TOKEN_RE)
    suspended = [f for f in findings if f.get("resolution", "").lower().startswith("suspended:")]
    dep_findings = [f for f in findings if f.get("source") == DEP_MAPPER_GATE]
    raw_dep_count = _count_tokens(risk_text, _DEP_SOURCE_TOKEN_RE)
    flow = has_flow_findings(risk_text)
    if not (raw_count or suspended or dep_findings or raw_dep_count or flow):
        return {"applies": False, "ok": True, "findings": [], "errors": []}

    errors: list[str] = []
    if not (is_full_sha(base_sha) and is_full_sha(head_sha)):
        errors.append(
            f"S0: base/head must be full 40-hex SHAs, got {base_sha!r}..{head_sha!r} "
            "(a symbolic or short revision cannot prove the trace is fresh)"
        )
    if flow:
        errors.append("S0: flow-style content in blocking_findings — not canonical block form")
    if raw_dep_count != len(dep_findings):
        errors.append(
            f"S0: {raw_dep_count} 'source: dep-mapper' lines but the parser found "
            f"{len(dep_findings)} dep-mapper findings — unparseable findings block"
        )
    if raw_count != len(suspended):
        errors.append(
            f"S0: {raw_count} 'resolution: suspended:' lines but the parser found "
            f"{len(suspended)} — unparseable findings block"
        )
    header, header_dups = _header_fields(risk_text)
    for key in sorted(header_dups & {"validated_tier", "base_sha", "head_sha"}):
        errors.append(f"S0: duplicate header key {key!r} in the risk assessment")
    if header.get("base_sha") != base_sha or header.get("head_sha") != head_sha:
        errors.append(
            f"S0: risk-assessment range {header.get('base_sha')!r}..{header.get('head_sha')!r} "
            f"!= {base_sha!r}..{head_sha!r}"
        )

    reader = read_text or (lambda p: read_exact_text(Path(repo_root) / p))
    behind_human_gate = bool(human_gate_required) or (
        max(_tier_rank(tier), _tier_rank(header.get("validated_tier"))) >= _tier_rank("CRITICAL")
    )
    status_cache: list[dict] = []

    def main_status() -> dict:
        if not status_cache:
            status_cache.append(
                suspension_status(
                    main_suspension_text or "", DEP_MAPPER_GATE, today, issue_state, repo_root
                )
            )
        return status_cache[0]

    results: list[dict] = []
    for f in suspended:
        errs: list[str] = []
        m = _SUSPENDED_RESOLUTION_RE.match(f.get("resolution", ""))
        if not m:
            errs.append("S1: malformed suspended resolution")
        else:
            if m.group("gate") != DEP_MAPPER_GATE:
                errs.append(f"S1: suspended gate {m.group('gate')!r} is not dep-mapper")
            if m.group("path") != dep_trace_path(step):
                errs.append(f"S2: trace path {m.group('path')!r} != {dep_trace_path(step)!r}")
        if f.get("source") != DEP_MAPPER_GATE:
            errs.append(f"S1: source {f.get('source')!r} may not use a suspended resolution")
        if behind_human_gate:
            errs.append("S3: step is behind the human gate (CRITICAL or human_gate_required)")
        if main_suspension_error is not None:
            errs.append(main_suspension_error)
        elif main_suspension_text is None:
            errs.append("S4: suspension not on the default branch")
        elif main_suspension_text != worktree_suspension_text:
            errs.append("S4: suspension file modified on this branch")
        else:
            st = main_status()
            if st["status"] != STATUS_ACTIVE:
                errs.append(f"S4: suspension is {st['status']} ({st['detail']})")
        trace = reader(dep_trace_path(step))
        if trace is None:
            errs.append("S5: manual trace absent")
        else:
            errs.extend(
                "S5: " + e
                for e in validate_dep_trace(trace, step, base_sha, head_sha, changed_files)[
                    "errors"
                ]
            )
        if require_disclosure:
            if handoff_text is None:
                errs.append("S6: handoff (PR body) absent")
            else:
                errs.extend(
                    "S6: " + e
                    for e in validate_disclosure(
                        handoff_text, step, trace or "", main_suspension_text or ""
                    )["errors"]
                )
        results.append({"id": f.get("id", "?"), "ok": not errs, "errors": errs})

    for f in dep_findings:
        resolution = f.get("resolution", "").strip()
        if not _DEP_VALID_RESOLUTION_RE.match(resolution):
            results.append(
                {
                    "id": f.get("id", "?"),
                    "ok": False,
                    "errors": [
                        f"S7: a dep-mapper finding may only be 'unresolved', 'escalated: "
                        f"<artifact>' or 'suspended: ...', not {resolution!r}"
                    ],
                }
            )

    ok = not errors and all(r["ok"] for r in results)
    return {"applies": True, "ok": ok, "findings": results, "errors": errors}


# --- CLI handlers -----------------------------------------------------------

_RANGE_RE = re.compile(r"^([0-9a-fA-F]{40})\.\.([0-9a-fA-F]{40})$")


def cmd_suspension_status(gate: str) -> int:
    """Print the status of `gate` from the fixed suspension file (no overrides)."""
    text = read_exact_text(Path(SUSPENSION_FILE)) or ""
    st = suspension_status(text, gate)
    print(f"STATUS={st['status']}")
    print(f"GATE={st['gate']}")
    print(f"EXPIRES={st['expires'] or ''}")
    print(f"UNTIL_CLOSED={'' if st['until_closed'] is None else st['until_closed']}")
    print(f"DETAIL={st['detail']}")
    return _STATUS_EXIT[st["status"]]


def cmd_validate_dep_trace(step: str, range_spec: str | None) -> int:
    m = _RANGE_RE.match(range_spec or "")
    if not m:
        print("--validate-dep-trace requires --range BASE..HEAD", file=sys.stderr)
        return 2
    base, head = m.groups()
    changed = changed_files_in_range(base, head)
    if changed is None:
        print(f"git diff --name-only {base}..{head} failed", file=sys.stderr)
        return 2
    text = read_exact_text(Path(dep_trace_path(step)))
    if text is None:
        print("TRACE=absent")
        return 1
    res = validate_dep_trace(text, step, base, head, changed)
    print(f"TRACE={'valid' if res['valid'] else 'invalid'}")
    for e in res["errors"]:
        print(f"ERROR={e}")
    return 0 if res["valid"] else 4


def cmd_check_suspended_resolutions(
    step: str,
    range_spec: str | None,
    tier: str | None,
    human_gate_required: str | None,
    require_disclosure: bool,
) -> int:
    m = _RANGE_RE.match(range_spec or "")
    if not m or tier is None or human_gate_required not in ("true", "false"):
        print(
            "--check-suspended-resolutions requires --range BASE..HEAD, --tier and "
            "--human-gate-required true|false",
            file=sys.stderr,
        )
        return 2
    if tier.upper() not in _TIERS:
        print(f"--tier must be one of {', '.join(_TIERS)}", file=sys.stderr)
        return 2
    base, head = m.groups()
    risk_text = read_exact_text(Path(_RISK_ASSESSMENT_PATH))
    if risk_text is None:
        print(f"{_RISK_ASSESSMENT_PATH} missing", file=sys.stderr)
        return 2
    changed = changed_files_in_range(base, head)
    if changed is None:
        print(f"git diff --name-only {base}..{head} failed", file=sys.stderr)
        return 2
    gate_flag = human_gate_required == "true" or manifest_human_gate_required(
        _STEP_MANIFEST_PATH, step
    )
    # No origin lookup unless a suspension applies (as REQ-W-18 does): no network otherwise.
    main = (
        read_default_branch_suspension()
        if suspension_applies(risk_text)
        else {"text": None, "error": None}
    )
    res = check_suspended_resolutions(
        risk_text,
        step,
        base,
        head,
        tier,
        gate_flag,
        changed,
        main["text"],
        read_exact_text(Path(SUSPENSION_FILE)),
        handoff_text=read_exact_text(Path(f".claudetmp/oversight/step{step}-handoff.md")),
        require_disclosure=require_disclosure,
        main_suspension_error=main["error"],
    )
    print(f"APPLIES={'yes' if res['applies'] else 'no'}")
    print(f"RESULT={'ok' if res['ok'] else 'fail'}")
    for e in res["errors"]:
        print(f"ERROR={e}")
    for f in res["findings"]:
        for e in f["errors"]:
            print(f"ERROR={f['id']}: {e}")
    return 0 if res["ok"] else 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--auto-remove", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--is-suspended",
        metavar="GATE",
        help="Exit 0 if GATE is currently suspended, exit 1 otherwise.",
    )
    parser.add_argument(
        "--emit-audit",
        action="store_true",
        help="Append a gate-suspended audit event (use with --gate / --authorized-by).",
    )
    parser.add_argument("--gate", metavar="GATE", help="Gate name for --emit-audit.")
    parser.add_argument(
        "--authorized-by",
        metavar="VALUE",
        help="Authorizer string for --emit-audit (default: unknown).",
    )
    parser.add_argument(
        "--step",
        metavar="STEP_ID",
        default=None,
        help="Build step the suspension applies to, for --emit-audit (#397).",
    )
    parser.add_argument(
        "--suspension-file",
        metavar="PATH",
        default=SUSPENSION_FILE,
        help=f"Path to the suspension record file (default: {SUSPENSION_FILE}).",
    )
    parser.add_argument(
        "--suspension-status",
        metavar="GATE",
        help="Print GATE's time-boxed status; exit 0 active, 1 absent, 3 expired, "
        "4 malformed, 5 unknown. Reads contract/gate-suspension.md only.",
    )
    parser.add_argument("--validate-dep-trace", metavar="STEP")
    parser.add_argument("--check-suspended-resolutions", metavar="STEP")
    parser.add_argument("--range", metavar="BASE..HEAD", default=None)
    parser.add_argument("--tier", default=None)
    parser.add_argument("--human-gate-required", default=None, choices=["true", "false"])
    parser.add_argument("--require-disclosure", action="store_true")
    args = parser.parse_args()

    if args.suspension_status:
        return cmd_suspension_status(args.suspension_status)
    if args.validate_dep_trace:
        return cmd_validate_dep_trace(args.validate_dep_trace, args.range)
    if args.check_suspended_resolutions:
        return cmd_check_suspended_resolutions(
            args.check_suspended_resolutions,
            args.range,
            args.tier,
            args.human_gate_required,
            args.require_disclosure,
        )

    # Point query — does not need the suspension file to exist to parse.
    if args.is_suspended:
        return cmd_is_suspended(args.is_suspended)

    # Audit emission — does not need the suspension file to exist; the caller
    # already knows the gate is suspended by the time it emits.
    if args.emit_audit:
        if not args.gate:
            print("--emit-audit requires --gate", file=sys.stderr)
            return 2
        return cmd_emit_audit(
            args.gate,
            args.authorized_by,
            step=args.step,
            suspension_file=args.suspension_file,
        )

    susp_path = Path(SUSPENSION_FILE)
    if not susp_path.exists():
        if not args.quiet:
            print("No contract/gate-suspension.md — nothing to manage.")
        return 0

    text = susp_path.read_text()
    suspensions = parse_suspensions(text)

    run_all = not (args.census or args.check or args.auto_remove)

    if args.census or run_all:
        cmd_census(suspensions, quiet=args.quiet, text=text)
    if args.check or run_all:
        cmd_check(suspensions)
    if args.auto_remove or run_all:
        new_text = cmd_auto_remove(text, suspensions)
        if new_text != text:
            susp_path.write_text(new_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
