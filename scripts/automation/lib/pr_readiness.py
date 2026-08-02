"""pr_readiness.py — worker pre-PR deterministic self-assessment gate (#317, #1131).

worker.md step 8.9 runs this immediately before `gh pr create` (never after):
exit 0 = PASS, proceed to open the PR; exit non-zero = do NOT open a PR.

`docs/specs/SPEC-317-worker-pre-pr-gate.md` and
`docs/v0.4.0/TECHNICAL-DESIGN-317-pre-pr-gate.md` specified this module
(REQ-W-01..W-17) on 2026-06-16, but it was never built — worker.md cited a
gate that did not exist (#1131, the "startup-artifact-gap" this issue tracks).
Several artifacts that design assumed have since diverged or were never built:

  * REQ-W-01/02 assumed persisted, head_sha-stamped markers
    (`.claudetmp/oversight/inner-loop-result.json`, `gates-result.json`).
    Neither exists. REQ-W-01 is implemented by actually re-running the
    inner-loop test command (deterministic, no trust placed in an assertion).
    REQ-W-02 reads the real marker `scripts/oversight/gates/run_gates.sh`
    writes: `.claudetmp/oversight/validators/gate-results.json`.
  * REQ-W-03's staleness guard uses the one artifact that actually carries a
    `head_sha` stamp: the committed `signoffs/validators/step{N}/summary.json`
    (falls back to the ephemeral `.claudetmp/oversight/validators/summary.json`,
    existence-only, when the committed copy is absent).
  * REQ-W-05/06 read the markdown sign-off register
    (`.claudetmp/signoffs/step{N}-register.md`) — the artifact the
    oversight-evaluator itself reads for Phase 1 compliance — not the
    committed `.stamp` files (`scripts/oversight/signoff_gate.py`), which
    structurally cannot represent `ESCALATED` (REQ-W-06 has no other source).
  * REQ-W-09 shells out to `scripts/oversight/change_classifier.py
    --domains-only --roles <N/A'd roles>`, the existing independent
    re-derivation tool cited by `contract/OVERSIGHT-CONTRACT.md` §2a condition
    9 for exactly this purpose. Roles with no domain rule (code-review,
    test-unit, test-system, process) cannot be independently verified and are
    silently skipped rather than failed.
  * REQ-W-13 globs `.claudetmp/oversight/step{N}-evaluation-*.md` (the path
    `oversight-evaluator.md`'s own output contract documents) — not
    `.claudetmp/signoffs/` as worker.md step 8.5's prose loosely says.
  * REQ-W-17's "claim envelope" alternative is dropped: current worker.md
    step 8.9 already resolves this to session-state.md only, and nothing
    populates a claim envelope with gate-result data.
  * REQ-W-15/16 (the gate is deterministic and non-bypassable) are properties
    of this module's existence and CLI contract, not runtime checks — hence
    only 14 checks execute per run, matching the design doc's "all 14 checks
    run even after a FAIL."

Entry point: `assess_pr_readiness(cid, base_sha, head_sha, step, risk_tier,
*, repo_root=".", ...)` runs every check (continues past a FAIL) and returns
a `ReadinessResult`. `write_session_state()` records the result to
`.claudetmp/session-state.md`; a write failure there is a hard FAIL
(architect binding 3 — session-state.md is the authoritative record).

CLI: python -m scripts.automation.lib.pr_readiness --cid C --base-sha B \
    --head-sha H --step N --risk-tier TIER [--system-test-applicable] \
    [--manifest PATH] [--repo-root PATH] [--no-write-state]
Exit 0 = PASS, 1 = FAIL, 2 = operational error (bad arguments/environment).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from scripts.automation.lib.gate_compliance import (
    load_composite_score,
    load_gate_results,
)
from scripts.automation.lib.gate_compliance import (
    gates_required as _gates_required_flag,
)
from scripts.automation.lib.merge_authority import RiskTier

# ---------------------------------------------------------------------------
# Artifact paths (relative to repo_root)
# ---------------------------------------------------------------------------

_INNER_LOOP_TEST_SCRIPT = "scripts/framework/run_tests_inner_loop.sh"
_SUMMARY_PATH = ".claudetmp/oversight/validators/summary.json"
_RISK_ASSESSMENT_PATH = ".claudetmp/oversight/validators/risk-assessment.md"
_CHANGE_CLASSIFIER_SCRIPT = "scripts/oversight/change_classifier.py"
_SESSION_STATE_PATH = ".claudetmp/session-state.md"
_STEP_MANIFEST_DEFAULT = "contract/step-manifest.yaml"

# Roles change_classifier.py's DOMAIN_RULES can independently verify (#74).
# Any other N/A'd role is not independently checkable and is skipped.
_DOMAIN_CHECKABLE_ROLES = frozenset({"security", "privacy", "ui", "ops", "reliability", "infra"})

_ESCALATED_STATUS = "ESCALATED"
_NA_STATUSES = frozenset({"N/A", "NA"})
_REGISTER_REQUIRED_FIELDS = ("Status", "Agent", "Artifact", "Iterations")

# Doc-currency heuristic (REQ-W-11, best-effort): surfaces whose contract
# changes are expected to carry an accompanying doc update.
_DOC_TRIGGER_GLOBS = (
    re.compile(r"^\.claude/agents/.*\.md$"),
    re.compile(r"^contract/.*\.(md|yaml)$"),
)
_DOC_SATISFYING_GLOB = re.compile(r"^docs/")


def _committed_summary_path(step: Union[str, int]) -> str:
    return f"signoffs/validators/step{step}/summary.json"


def _register_path(step: Union[str, int]) -> str:
    return f".claudetmp/signoffs/step{step}-register.md"


def _human_authorization_path(step: Union[str, int]) -> str:
    return f".claudetmp/oversight/step{step}-human-authorization.md"


def _second_review_glob(step: Union[str, int]) -> str:
    return f".claudetmp/second-review/step{step}-*.md"


def _evaluation_glob(step: Union[str, int]) -> str:
    return f".claudetmp/oversight/step{step}-evaluation-*.md"


def _panel_context_path(step: Union[str, int]) -> str:
    return f".claudetmp/oversight/step{step}-panel-context.md"


def _handoff_path(step: Union[str, int]) -> str:
    return f".claudetmp/oversight/step{step}-handoff.md"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    check_id: str
    passed: bool
    detail: str


@dataclass
class ReadinessResult:
    cid: str
    step: Union[str, int]
    checks: list[CheckResult] = field(default_factory=list)
    session_state_written: bool = False
    session_state_error: Optional[str] = None

    @property
    def checks_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def passed(self) -> bool:
        # Architect binding 3: a session-state.md write failure is a hard FAIL
        # even when every check passed — it is the authoritative record.
        return self.checks_passed and self.session_state_error is None

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_markdown(self, *, timestamp: Optional[str] = None) -> str:
        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            "## Pre-PR gate result",
            f"- Timestamp: {ts}",
            f"- cid: {self.cid}",
            f"- Step: {self.step}",
            f"- Result: {'PASS' if self.passed else 'FAIL'}",
        ]
        if self.failures:
            lines.append("- Failing checks:")
            for c in self.failures:
                lines.append(f"  - [{c.check_id}] {c.detail}")
        if self.session_state_error:
            lines.append(f"- session-state write error: {self.session_state_error}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Small IO helpers
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_json(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _run(cmd: list[str], cwd: Path, timeout: Optional[int] = None) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _tier_gte(tier: str, floor: str) -> bool:
    """True when `tier` is at or above `floor` in RiskTier order (never hardcoded)."""
    return RiskTier.from_str(tier).value >= RiskTier.from_str(floor).value


# ---------------------------------------------------------------------------
# Register parsing (markdown sign-off register — REQ-W-05/06/09/12)
# ---------------------------------------------------------------------------

_ENTRY_HEADER_RE = re.compile(r"^##\s+(?P<role>[^|#]+?)\s*(?:\|.*)?$")


def _parse_register(text: str) -> list[dict]:
    """Parse `.claudetmp/signoffs/step{N}-register.md` into ordered entries.

    Each entry: {"role": str, "fields": {field_name: value}}. Entries appear
    in file order; a role may have multiple entries (one per iteration/file
    group) — callers that want "current state" take the last matching entry.
    """
    entries: list[dict] = []
    current: Optional[dict] = None
    for line in text.splitlines():
        m = _ENTRY_HEADER_RE.match(line)
        if m:
            if current is not None:
                entries.append(current)
            current = {"role": m.group("role").strip(), "fields": {}}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current["fields"][key.strip()] = value.strip()
    if current is not None:
        entries.append(current)
    return entries


def _latest_entry_by_role(entries: list[dict], role: str) -> Optional[dict]:
    for entry in reversed(entries):
        if entry["role"].lower() == role.lower():
            return entry
    return None


def _parse_required_signoffs(manifest_path: Path, step: Union[str, int]) -> list[str]:
    """Extract `required_signoffs: [a, b, c]` for `step` from step-manifest.yaml.

    Hand-rolled line scan (stdlib only), mirroring gate_compliance.gates_required's
    approach for the same file. Returns [] if the manifest, the step, or the
    field is absent.
    """
    text = _read_text(manifest_path)
    if text is None:
        return []
    step_str = str(step)
    in_steps = False
    in_target_step = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("steps:"):
            in_steps = True
            continue
        if not in_steps:
            continue
        if line and not line[0].isspace() and ":" in line and not stripped.startswith("-"):
            in_steps = False
            in_target_step = False
            continue
        if stripped.startswith("- id:"):
            id_val = stripped[len("- id:"):].strip().strip("\"'")
            in_target_step = id_val == step_str
            continue
        if in_target_step and stripped.startswith("id:"):
            id_val = stripped[len("id:"):].strip().strip("\"'")
            in_target_step = id_val == step_str
            continue
        if in_target_step and stripped.startswith("required_signoffs:"):
            raw = stripped[len("required_signoffs:"):].strip()
            raw = raw.strip("[]")
            if not raw:
                return []
            return [r.strip() for r in raw.split(",") if r.strip()]
    return []


# ---------------------------------------------------------------------------
# Individual checks (REQ-W-01..W-14) — every check always runs
# ---------------------------------------------------------------------------


def _check_inner_loop_tests(repo_root: Path) -> CheckResult:
    script = repo_root / _INNER_LOOP_TEST_SCRIPT
    if not script.exists():
        return CheckResult("REQ-W-01", False, f"missing {_INNER_LOOP_TEST_SCRIPT}")
    result = _run(["bash", str(script)], cwd=repo_root, timeout=900)
    if result is None:
        return CheckResult("REQ-W-01", False, "inner-loop test run failed to execute (timeout/OS error)")
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-15:])
        return CheckResult("REQ-W-01", False, f"inner-loop tests exited {result.returncode}\n{tail}")
    return CheckResult("REQ-W-01", True, "inner-loop tests exit 0")


def _check_gates(repo_root: Path, manifest_path: Path, step: Union[str, int]) -> CheckResult:
    required = _gates_required_flag(manifest_path, step)
    results = load_gate_results(repo_root)
    if required and not results:
        return CheckResult("REQ-W-02", False, "gates_required=true but gate-results.json is absent")
    failed = [r for r in results if r.get("exit_code", 0) != 0 and not r.get("suspended", False)]
    if failed:
        names = ", ".join(str(r.get("gate", "<unknown>")) for r in failed)
        return CheckResult("REQ-W-02", False, f"gate(s) failed: {names}")
    return CheckResult("REQ-W-02", True, "gates pass" if results else "no gates required for this step")


def _check_validators_current(repo_root: Path, step: Union[str, int], head_sha: str) -> CheckResult:
    committed = _read_json(repo_root / _committed_summary_path(step))
    if committed is not None:
        composite = committed.get("composite_score")
        stamped_head = committed.get("head_sha")
        if composite is None:
            return CheckResult("REQ-W-03", False, f"{_committed_summary_path(step)} missing composite_score")
        if stamped_head != head_sha:
            return CheckResult(
                "REQ-W-03", False,
                f"{_committed_summary_path(step)} head_sha={stamped_head!r} != current head {head_sha!r} — stale",
            )
        return CheckResult("REQ-W-03", True, f"validators current (head_sha matches, score={composite})")

    composite = load_composite_score(repo_root)
    if composite is None:
        return CheckResult("REQ-W-03", False, f"neither {_committed_summary_path(step)} nor {_SUMMARY_PATH} has a composite_score")
    return CheckResult(
        "REQ-W-03", True,
        f"validators ran (score={composite}); no committed summary yet to stamp-check head_sha",
    )


def _check_risk_assessment_scope(repo_root: Path, base_sha: str, head_sha: str) -> CheckResult:
    text = _read_text(repo_root / _RISK_ASSESSMENT_PATH)
    if text is None:
        return CheckResult("REQ-W-04", False, f"missing {_RISK_ASSESSMENT_PATH}")
    fields = {}
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            fields[key.strip()] = value.strip()
    doc_base, doc_head = fields.get("base_sha"), fields.get("head_sha")
    if doc_base != base_sha or doc_head != head_sha:
        return CheckResult(
            "REQ-W-04", False,
            f"risk-assessment.md scoped to base_sha={doc_base!r} head_sha={doc_head!r}, expected {base_sha!r}/{head_sha!r}",
        )
    return CheckResult("REQ-W-04", True, "risk-assessment.md scoped to current commit range")


def _load_register(repo_root: Path, step: Union[str, int]) -> tuple[Optional[str], list[dict]]:
    text = _read_text(repo_root / _register_path(step))
    if text is None:
        return None, []
    return text, _parse_register(text)


def _check_signoffs_present(
    entries: list[dict], register_present: bool, required_roles: list[str]
) -> CheckResult:
    if not register_present:
        return CheckResult("REQ-W-05", False, "sign-off register is missing")
    if not required_roles:
        return CheckResult("REQ-W-05", True, "no required_signoffs configured for this step")
    missing = []
    for role in required_roles:
        entry = _latest_entry_by_role(entries, role)
        if entry is None:
            missing.append(f"{role}: no entry")
            continue
        absent_fields = [f for f in _REGISTER_REQUIRED_FIELDS if not entry["fields"].get(f)]
        if absent_fields:
            missing.append(f"{role}: missing field(s) {', '.join(absent_fields)}")
    if missing:
        return CheckResult("REQ-W-05", False, "; ".join(missing))
    return CheckResult("REQ-W-05", True, f"all {len(required_roles)} required role(s) present with required fields")


def _check_no_unresolved_escalations(entries: list[dict], register_present: bool) -> CheckResult:
    if not register_present:
        return CheckResult("REQ-W-06", False, "sign-off register is missing")
    unresolved = []
    for entry in entries:
        status = entry["fields"].get("Status", "").strip().upper()
        if status == _ESCALATED_STATUS and not entry["fields"].get("Human_resolution", "").strip():
            unresolved.append(entry["role"])
    if unresolved:
        return CheckResult("REQ-W-06", False, f"ESCALATED without Human_resolution: {', '.join(unresolved)}")
    return CheckResult("REQ-W-06", True, "no unresolved ESCALATED entries")


def _check_critical_human_authorization(repo_root: Path, step: Union[str, int], risk_tier: str) -> CheckResult:
    if not _tier_gte(risk_tier, "CRITICAL"):
        return CheckResult("REQ-W-07", True, f"tier {risk_tier} below CRITICAL — not required")
    text = _read_text(repo_root / _human_authorization_path(step))
    if text is None or not text.strip():
        return CheckResult("REQ-W-07", False, f"missing/empty {_human_authorization_path(step)}")
    return CheckResult("REQ-W-07", True, "human-authorization file present")


_SECOND_REVIEW_NON_TERMINAL = frozenset({"error", "skipped", "unparseable", "pending"})


def _check_second_review(repo_root: Path, step: Union[str, int], risk_tier: str) -> CheckResult:
    if not _tier_gte(risk_tier, "MEDIUM"):
        return CheckResult("REQ-W-08", True, f"tier {risk_tier} below MEDIUM — not required")
    matches = sorted((repo_root / ".claudetmp" / "second-review").glob(f"step{step}-*.md")) \
        if (repo_root / ".claudetmp" / "second-review").is_dir() else []
    if not matches:
        return CheckResult("REQ-W-08", False, f"no second-review file matching {_second_review_glob(step)}")
    latest = matches[-1]
    text = _read_text(latest) or ""
    verdict = None
    for line in text.splitlines()[:10]:
        stripped = line.strip()
        if stripped.lower().startswith("verdict:"):
            verdict = stripped.split(":", 1)[1].strip().lower()
            break
    if verdict is None or verdict in _SECOND_REVIEW_NON_TERMINAL:
        return CheckResult("REQ-W-08", False, f"{latest.name} verdict={verdict!r} — not a terminal, non-error verdict")
    return CheckResult("REQ-W-08", True, f"{latest.name} verdict={verdict}")


def _check_na_domains(repo_root: Path, entries: list[dict], base_sha: str, head_sha: str) -> CheckResult:
    na_roles = sorted(
        {
            e["role"] for e in entries
            if e["fields"].get("Status", "").strip().upper() in _NA_STATUSES
            and e["role"].lower() in _DOMAIN_CHECKABLE_ROLES
        }
    )
    if not na_roles:
        return CheckResult("REQ-W-09", True, "no independently-checkable N/A entries")
    script = repo_root / _CHANGE_CLASSIFIER_SCRIPT
    if not script.exists():
        return CheckResult("REQ-W-09", False, f"missing {_CHANGE_CLASSIFIER_SCRIPT} — cannot verify N/A waiver(s)")
    result = _run(
        [sys.executable, str(script), "--base", base_sha, "--head", head_sha, "--domains-only", "--roles", ",".join(na_roles)],
        cwd=repo_root, timeout=120,
    )
    if result is None or result.returncode != 0:
        return CheckResult("REQ-W-09", False, "change_classifier.py failed to run — cannot verify N/A waiver(s)")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return CheckResult("REQ-W-09", False, "change_classifier.py produced unparseable output")
    touched = set(payload.get("domains_touched", {}) or {})
    invalidated = sorted(r for r in na_roles if r.lower() in touched)
    if invalidated:
        return CheckResult("REQ-W-09", False, f"N/A not credible — domain(s) actually touched: {', '.join(invalidated)}")
    return CheckResult("REQ-W-09", True, f"{len(na_roles)} N/A waiver(s) independently verified")


def _check_prompt_artifact_trailers(repo_root: Path, base_sha: str, head_sha: str, risk_tier: str) -> CheckResult:
    if not _tier_gte(risk_tier, "MEDIUM"):
        return CheckResult("REQ-W-10", True, f"tier {risk_tier} below MEDIUM — not required")
    result = _run(["git", "log", "--format=%H", f"{base_sha}..{head_sha}"], cwd=repo_root)
    if result is None or result.returncode != 0:
        return CheckResult("REQ-W-10", False, f"git log {base_sha}..{head_sha} failed")
    shas = [s for s in result.stdout.splitlines() if s]
    if not shas:
        return CheckResult("REQ-W-10", True, "no commits in range")
    missing = []
    for sha in shas:
        msg_result = _run(["git", "log", "-1", "--format=%B", sha], cwd=repo_root)
        body = msg_result.stdout if msg_result else ""
        if "Prompt-Artifact:" not in body:
            missing.append(sha[:8])
    if missing:
        return CheckResult("REQ-W-10", False, f"commit(s) missing Prompt-Artifact trailer: {', '.join(missing)}")
    return CheckResult("REQ-W-10", True, f"all {len(shas)} commit(s) carry a Prompt-Artifact trailer")


def _check_doc_currency(repo_root: Path, base_sha: str, head_sha: str) -> CheckResult:
    result = _run(["git", "diff", "--name-only", f"{base_sha}..{head_sha}"], cwd=repo_root)
    if result is None or result.returncode != 0:
        return CheckResult("REQ-W-11", False, f"git diff --name-only {base_sha}..{head_sha} failed")
    changed = [f for f in result.stdout.splitlines() if f]
    triggers = [f for f in changed if any(rx.match(f) for rx in _DOC_TRIGGER_GLOBS)]
    if not triggers:
        return CheckResult("REQ-W-11", True, "no doc-requiring surface changed")
    if any(_DOC_SATISFYING_GLOB.match(f) for f in changed):
        return CheckResult("REQ-W-11", True, "doc-requiring surface changed and docs/ updated alongside it")
    return CheckResult(
        "REQ-W-11", False,
        f"contract/agent surface changed ({', '.join(triggers[:5])}) with no docs/ update in the same range",
    )


def _check_system_tests(entries: list[dict], register_present: bool, system_test_applicable: bool) -> CheckResult:
    if not system_test_applicable:
        return CheckResult("REQ-W-12", True, "system tests not applicable to this step")
    if not register_present:
        return CheckResult("REQ-W-12", False, "sign-off register is missing")
    entry = _latest_entry_by_role(entries, "test-system")
    if entry is None:
        return CheckResult("REQ-W-12", False, "system tests applicable but no test-system register entry")
    status = entry["fields"].get("Status", "").strip().upper()
    if status not in {"APPROVED", "CONDITIONAL"}:
        return CheckResult("REQ-W-12", False, f"test-system entry status is {status!r}, expected APPROVED/CONDITIONAL")
    return CheckResult("REQ-W-12", True, "system tests approved")


_EVALUATOR_ACCEPTABLE = frozenset({"PROCEED", "CONDITIONAL_PROCEED"})


def _check_evaluator_verdict(repo_root: Path, step: Union[str, int]) -> CheckResult:
    directory = repo_root / ".claudetmp" / "oversight"
    matches = sorted(directory.glob(f"step{step}-evaluation-*.md")) if directory.is_dir() else []
    if not matches:
        return CheckResult("REQ-W-13", False, f"no evaluation file matching {_evaluation_glob(step)}")
    latest = matches[-1]
    text = _read_text(latest) or ""
    verdict = None
    m = re.search(r"\*\*Recommendation:\*\*\s*([A-Z_]+)", text)
    if m:
        verdict = m.group(1)
    if verdict not in _EVALUATOR_ACCEPTABLE:
        return CheckResult("REQ-W-13", False, f"{latest.name} recommendation={verdict!r} — not PROCEED/CONDITIONAL_PROCEED")
    return CheckResult("REQ-W-13", True, f"{latest.name} recommendation={verdict}")


def _check_handoff_artifacts(repo_root: Path, step: Union[str, int]) -> CheckResult:
    missing = [
        p for p in (_panel_context_path(step), _handoff_path(step))
        if not (repo_root / p).exists()
    ]
    if missing:
        return CheckResult("REQ-W-14", False, f"missing: {', '.join(missing)}")
    return CheckResult("REQ-W-14", True, "panel-context.md and handoff.md present")


# ---------------------------------------------------------------------------
# session-state.md recording (REQ-W-17)
# ---------------------------------------------------------------------------


def write_session_state(repo_root: Path, result: ReadinessResult) -> None:
    """Append the gate result to `.claudetmp/session-state.md`.

    Mutates `result.session_state_written` / `result.session_state_error` in
    place. A write failure is surfaced via `session_state_error`, which makes
    `ReadinessResult.passed` False regardless of check outcomes (architect
    binding 3 — session-state.md is the authoritative record of gate runs).
    """
    path = repo_root / _SESSION_STATE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + result.to_markdown())
        result.session_state_written = True
    except OSError as exc:
        result.session_state_error = str(exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def assess_pr_readiness(
    cid: str,
    base_sha: str,
    head_sha: str,
    step: Union[str, int],
    risk_tier: str,
    *,
    repo_root: Union[str, Path] = ".",
    system_test_applicable: bool = False,
    write_state: bool = True,
    step_manifest_path: Optional[Union[str, Path]] = None,
) -> ReadinessResult:
    """Run REQ-W-01..W-14, then (if write_state) record to session-state.md.

    Every check runs regardless of earlier failures — the caller always gets
    a full picture of every gap, not just the first one hit.
    """
    root = Path(repo_root)
    manifest_path = Path(step_manifest_path) if step_manifest_path else root / _STEP_MANIFEST_DEFAULT
    register_text, entries = _load_register(root, step)
    register_present = register_text is not None
    required_roles = _parse_required_signoffs(manifest_path, step)

    checks = [
        _check_inner_loop_tests(root),
        _check_gates(root, manifest_path, step),
        _check_validators_current(root, step, head_sha),
        _check_risk_assessment_scope(root, base_sha, head_sha),
        _check_signoffs_present(entries, register_present, required_roles),
        _check_no_unresolved_escalations(entries, register_present),
        _check_critical_human_authorization(root, step, risk_tier),
        _check_second_review(root, step, risk_tier),
        _check_na_domains(root, entries, base_sha, head_sha),
        _check_prompt_artifact_trailers(root, base_sha, head_sha, risk_tier),
        _check_doc_currency(root, base_sha, head_sha),
        _check_system_tests(entries, register_present, system_test_applicable),
        _check_evaluator_verdict(root, step),
        _check_handoff_artifacts(root, step),
    ]

    result = ReadinessResult(cid=cid, step=step, checks=checks)
    if write_state:
        write_session_state(root, result)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker pre-PR deterministic self-assessment gate (#317).")
    parser.add_argument("--cid", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("--risk-tier", required=True, choices=[t.name for t in RiskTier])
    parser.add_argument("--system-test-applicable", action="store_true")
    parser.add_argument("--manifest", default=None, help=f"default: <repo-root>/{_STEP_MANIFEST_DEFAULT}")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--no-write-state", action="store_true")
    args = parser.parse_args()

    root = Path(args.repo_root)
    if not root.is_dir():
        sys.stderr.write(f"pr_readiness: repo-root not found: {root}\n")
        return 2

    result = assess_pr_readiness(
        args.cid, args.base_sha, args.head_sha, args.step, args.risk_tier,
        repo_root=root,
        system_test_applicable=args.system_test_applicable,
        write_state=not args.no_write_state,
        step_manifest_path=args.manifest,
    )

    print(f"=== pr_readiness — cid={result.cid} step={result.step} ===")
    for c in result.checks:
        mark = "✓" if c.passed else "✗"
        print(f"  {mark} [{c.check_id}] {c.detail}")
    if result.session_state_error:
        print(f"  ✗ session-state.md write failed: {result.session_state_error}")
    print()
    print(f"pr_readiness: {'PASS' if result.passed else 'FAIL'}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
