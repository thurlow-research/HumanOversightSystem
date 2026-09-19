"""Acceptance tests for #1643 W4 — migrating the `claude -p` call sites to
bootstrap/invoke_agent.sh (docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md
§6, §9.4 T4.1-T4.6; docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md AD-16).

Scoping note on T4.1/T4.2/T4.3, read before changing these tests: the literal
task wording ("grep -rn '...' over the repo returns nothing / returns exactly
<2 files>") is imprecise against the REAL repo tree and against the ADR's own
later amendments:

  1. Comments and docs legitimately NAME the old constructs (`claude -p`,
     `run_capped`, `_TIMEOUT_BIN`, a synthesized `"verdict":"error"` literal)
     for historical/explanatory context — a plain substring grep matches
     prose as readily as code. These tests therefore only look at CODE lines
     (a line is excluded if, after stripping leading whitespace, it starts
     with `#`).
  2. `run_capped` is ALSO the name of an unrelated, legitimate, already-shipped
     (W1) Python function internal to `scripts/automation/agent_invoke_cli.py`
     (the primitive's own subprocess-launch helper) — explicitly out of scope
     here ("Do not change ... agent_invoke_cli.py") — plus its dedicated test
     file `tests/automation/test_agent_invoke_cli.py`.
  3. T4.2's "delete both `run_capped` copies" premise (TD §6.3) was itself
     amended by ADR-1643 §9.4 (ESC-D/TD-F5, "Amends AD-5.3"), AFTER the TD
     table was written and never revised there: `validate_agents.sh`'s copy
     has no `claude` consumer to migrate (`validate_agents.sh` has no claude
     call site at all — only `agy`/`codex`), so its `run_capped` deletion is
     an unrelated refactor of the cross-vendor validation path and MOVES OUT
     of W4 to a follow-up issue. Only `validate_scripts.sh`'s copy — the one
     actually attached to a real migration — is deleted here. The ADR's own
     "copy ledger" for the state after W4 (§9.4): one shared bash helper
     (`with_timeout`, in `scripts/oversight/run_with_retry.sh`) and exactly
     two remaining PRIVATE bash timeout-capping copies —
     `scripts/framework/validate_agents.sh` (the follow-up) and
     `bin/hos-cron` (deliberately out of scope of both W4 and the follow-up:
     it bounds a whole cron cycle, not an AI review, per §9.4). T4.2 below
     asserts exactly that ledger, using the marker both remaining private
     copies actually share (`_TIMEOUT_BIN`) rather than the literal string
     `run_capped`, since `bin/hos-cron`'s copy never used that function name.
"""

import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_VALIDATION_LOGIC_PATH = ROOT / "scripts" / "oversight" / "validation_logic.py"
_spec = importlib.util.spec_from_file_location("validation_logic", _VALIDATION_LOGIC_PATH)
assert (
    _spec is not None and _spec.loader is not None
), f"could not build a module spec for {_VALIDATION_LOGIC_PATH} — has it moved?"
validation_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validation_logic)

_EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "node_modules"}


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_PARTS for part in path.parts)


def _code_lines(path: Path):
    """Yield (lineno, line) for every line in `path` that is not comment-only
    (leading-whitespace-stripped line does not start with `#`)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        yield lineno, line


def _iter_files(*root_dirs):
    for root_dir in root_dirs:
        base = ROOT / root_dir
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_dir() or _is_excluded(path):
                continue
            yield path


# ── T4.1 — no raw `claude -p` / `claude --print` outside the named exemptions ──
_CLAUDE_CLI_PATTERN = re.compile(r"claude -p|claude --print")

# scripts/run_panel.sh is exempt until W4b lands (TD §6.4, TD-F4): it migrates
# the panel's Claude seats to shipped agent files, which is out of scope for
# W4. scripts/framework/validate_scripts.sh is exempt until W4c lands: the
# architect ruled (ADR-1643 Amendment 6,
# docs/v0.7.0/ADR-1643-AMENDMENT-6-scripts-review-seat.md) that §6.2's
# migration needs a new shipped `scripts-reviewer` agent — a protected-surface
# addition requiring human approval — because `self-reviewer` is scoped to
# governance text (not this file's bash/portability/fetch-exec lens) and
# `code-reviewer`/`security-reviewer` are diff-centric by an unwaivable CORE
# constraint, while validate_scripts.sh supplies a whole-corpus package with
# no diff. As each slice lands, its entry is removed and this set shrinks —
# the assertion tightens automatically rather than breaking.
_T4_1_EXPECTED_EXEMPTIONS = {
    "bootstrap/setup_clis.sh",  # EXEMPT (§6.5): the machine-bootstrap smoke test.
    "scripts/run_panel.sh",  # EXEMPT until W4b (TD §6.4) migrates the panel's Claude seats.
    # EXEMPT until W4c (#1756, ADR-1643 Amendment 6) ships a scripts-reviewer agent.
    "scripts/framework/validate_scripts.sh",
}


def test_T4_1_no_raw_claude_cli_outside_named_exemptions():
    hits = set()
    for path in _iter_files("scripts", "bootstrap", "bin"):
        for _lineno, line in _code_lines(path):
            if _CLAUDE_CLI_PATTERN.search(line):
                hits.add(str(path.relative_to(ROOT)))
                break
    assert hits == _T4_1_EXPECTED_EXEMPTIONS, (
        f"raw `claude -p`/`claude --print` call sites found: {sorted(hits)} — "
        f"expected exactly {sorted(_T4_1_EXPECTED_EXEMPTIONS)}. Every other "
        "caller must go through bootstrap/invoke_agent.sh (ADR-1643 AD-16)."
    )


# ── T4.2 — validate_scripts.sh's private run_capped copy is gone; the ADR-1643
#          §9.4 "copy ledger" for everything else holds (AD-5.3 as amended) ──
_TIMEOUT_BIN_ASSIGNMENT_PATTERN = re.compile(r"_TIMEOUT_BIN\s*=")

# scripts/oversight/run_with_retry.sh is the ADR's "one shared bash helper"
# (with_timeout) — its own _TIMEOUT_BIN is the canonical implementation every
# migrated call site now delegates to, not a "private copy", so it is
# excluded from the private-copy ledger below by construction.
_SHARED_HELPER = "scripts/oversight/run_with_retry.sh"

# The two remaining PRIVATE bash timeout-capping copies per ADR-1643 §9.4's
# ledger (both still use `_TIMEOUT_BIN`; only validate_agents.sh's still
# wraps it in a function literally named `run_capped` — bin/hos-cron's never
# used that name, so this checks the marker they actually share).
_T4_2_EXPECTED_TIMEOUT_BIN_COPIES = {
    # EXEMPT (ADR-1643 §9.4): moved to a follow-up issue, not W4 — no claude consumer to migrate.
    "scripts/framework/validate_agents.sh",
    # EXEMPT (ADR-1643 §9.4): out of scope of W4 AND the follow-up — bounds a whole cron cycle, not an AI review.
    "bin/hos-cron",
}


def test_T4_2_validate_scripts_no_longer_has_a_private_timeout_bin_copy():
    """Positive confirmation of the one migration T4.2 actually covers: no
    `run_capped` function and no `_TIMEOUT_BIN` definition remain in
    validate_scripts.sh (ADR-1643 §9.4 — this is the copy that WAS attached
    to a real migration)."""
    path = ROOT / "scripts" / "framework" / "validate_scripts.sh"
    for lineno, line in _code_lines(path):
        assert (
            "run_capped" not in line
        ), f"validate_scripts.sh:{lineno} still references run_capped in code: {line!r}"
        assert not _TIMEOUT_BIN_ASSIGNMENT_PATTERN.search(
            line
        ), f"validate_scripts.sh:{lineno} still defines _TIMEOUT_BIN: {line!r}"


def test_T4_2_private_timeout_bin_copy_ledger_matches_adr_1643_section_9_4():
    """After W4: one shared bash helper (with_timeout, excluded here) and
    exactly the two remaining private copies ADR-1643 §9.4 names. If a third
    copy appears, or one of these two is unexpectedly migrated/deleted
    without updating this ledger, this test catches the drift."""
    hits = set()
    for path in _iter_files("scripts", "bootstrap", "bin"):
        rel = str(path.relative_to(ROOT))
        if rel == _SHARED_HELPER:
            continue
        for _lineno, line in _code_lines(path):
            if _TIMEOUT_BIN_ASSIGNMENT_PATTERN.search(line):
                hits.add(rel)
                break
    assert hits == _T4_2_EXPECTED_TIMEOUT_BIN_COPIES, (
        f"private _TIMEOUT_BIN copies found: {sorted(hits)} — expected exactly "
        f"{sorted(_T4_2_EXPECTED_TIMEOUT_BIN_COPIES)} per ADR-1643 §9.4's copy "
        "ledger (one shared helper in run_with_retry.sh, two remaining private "
        "copies)."
    )


# ── T4.3 — validate_self.sh synthesizes no `"verdict":"error"` literal ─────────
def test_T4_3_validate_self_has_no_synthesized_verdict_error_literal():
    path = ROOT / "scripts" / "framework" / "validate_self.sh"
    for lineno, line in _code_lines(path):
        assert '"verdict":"error"' not in line, (
            f"validate_self.sh:{lineno} still synthesizes a literal "
            f'"verdict":"error" block: {line!r} — the invocation_failed '
            "document already carries verdict:error structurally (AD-6)."
        )


# ── ops-reviewer finding (#1676) — the Opus status line must surface WHICH
#    failure occurred (outcome/outcome_detail), not just THAT one did ─────────
#
# invoke_agent.sh's own header is explicit that exit 0 covers the ENTIRE
# invocation_failed taxonomy (timeout, not_authenticated, cli_unavailable,
# unparseable, crash, permission_denied, refused, schema_violation,
# usage_limit, posture_invalid, agent_unavailable, ...) — run_opus's
# rc-based guard (kept, for the wrapper's own launch-failure case) never
# fires for any of these, so a status line that claims "see error above"
# for this case points the operator at output that does not exist. These
# tests exercise the ACTUAL python3 snippet embedded in validate_self.sh
# (extracted by regex, so they drift-detect if the snippet changes) rather
# than a hand-copied duplicate.
def _extract_opus_outcome_detail_python_snippet():
    text = (ROOT / "scripts" / "framework" / "validate_self.sh").read_text(encoding="utf-8")
    match = re.search(r"python3 -c '\n(.*?)\n'", text, re.DOTALL)
    assert match, (
        "could not find the outcome/outcome_detail extraction python3 -c "
        "snippet in validate_self.sh — has the status-line fix (#1676) been "
        "removed or reshaped?"
    )
    return match.group(1)


def test_status_line_surfaces_outcome_detail_on_invocation_failed():
    snippet = _extract_opus_outcome_detail_python_snippet()
    doc = '{"outcome":"invocation_failed","outcome_detail":"not_authenticated"}'
    result = subprocess.run(["python3", "-c", snippet], input=doc, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "invocation_failed"
    assert detail == "not_authenticated"


def test_status_line_reports_completed_outcome_with_no_detail():
    snippet = _extract_opus_outcome_detail_python_snippet()
    doc = '{"outcome":"completed","outcome_detail":null,"verdict":"approve"}'
    result = subprocess.run(["python3", "-c", snippet], input=doc, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "completed"
    assert detail == "-"


def test_status_line_handles_unparseable_output_without_crashing():
    snippet = _extract_opus_outcome_detail_python_snippet()
    result = subprocess.run(
        ["python3", "-c", snippet], input="not json at all", capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "__PARSE_ERROR__"
    assert detail == "__PARSE_ERROR__"


def test_status_line_no_longer_makes_the_false_see_error_above_claim():
    text = (ROOT / "scripts" / "framework" / "validate_self.sh").read_text(encoding="utf-8")
    assert "FAILED — see error above" not in text, (
        "the status line still claims 'see error above' for a case "
        "(structured invocation_failed) where run_opus's rc-based guard "
        "never printed anything above (#1676)"
    )
    assert (
        "outcome_detail=" in text
    ), "the status line no longer surfaces outcome_detail to the operator (#1676)"


# ── T4.5 — setup_clis.sh carries the exemption comment citing ADR-1643 ────────
def test_T4_5_setup_clis_carries_the_adr_1643_exemption_comment():
    text = (ROOT / "bootstrap" / "setup_clis.sh").read_text(encoding="utf-8")
    assert "EXEMPT from ADR-1643 AD-16" in text
    # The exemption comment must sit directly above the smoke_claude definition
    # it excuses, not floating disconnected elsewhere in the file.
    idx_comment = text.index("EXEMPT from ADR-1643 AD-16")
    idx_def = text.index("smoke_claude()")
    assert idx_comment < idx_def, "exemption comment must precede smoke_claude()"
    between = text[idx_comment:idx_def]
    assert between.count("\n") <= 6, "exemption comment is not directly above smoke_claude()"


# ── T4.6 — CLAUDE.md documents the new canonical entry point ──────────────────
def test_T4_6_claude_md_documents_invoke_agent_entry_point():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "`bootstrap/invoke_agent.sh`" in text
    assert (
        "Invoking a shipped Claude agent as a subprocess and getting a "
        "machine-readable verdict | `bootstrap/invoke_agent.sh`" in text
    )


# ── T4.4 — validate_scripts.sh's tiered required/optional lane behaviour ──────
#
# Scoping note: `validation_logic.compute_verdict` (which `validate_scripts.sh`
# delegates its aggregation to, unchanged by this migration) has NO concept of
# "required" vs "optional" reviewer identity — ANY block whose own `verdict`
# is `"error"` counts as blocking (validation_logic.py:285, the #670 fix),
# regardless of which reviewer produced it. Confirmed empirically: a synthetic
# {"reviewer":"agy", ..., "verdict":"error"} block alone, aggregated with a
# clean opus block, still yields overall verdict "request_changes". So the
# real, verifiable "tiered" property in this (unchanged) codebase is not
# "an optional lane's error verdict is exempted from blocking" — it is that
# the REQUIRED (opus) lane always runs and fails closed on any hiccup
# (run_scripts.sh has no --skip-opus), while the OPTIONAL (agy/codex) lanes
# can be entirely ABSENT from the aggregated output (--skip-agy/--skip-codex/
# --skip-3p, or the CLI simply not being on PATH) without forcing a block —
# there is no requirement that they run at all. These two tests characterize
# exactly that: (1) the required lane's own fail-closed synthesized body is,
# on its own, blocking; (2) a clean required lane with no optional-lane block
# present at all is not.
def test_T4_4_required_lane_failure_is_blocking():
    """Mirrors the exact shape run_reviewer()'s opus branch synthesizes on
    failure (validate_scripts.sh, kind=="opus" fail-closed path, #669): a
    single blocking-severity finding, verdict "request_changes"."""
    required_lane_failure_block = {
        "reviewer": "opus-self",
        "lens": "scripts",
        "findings": [
            {
                "severity": "blocking",
                "category": "fail-open",
                "files": ["<reviewer:opus-self>"],
                "description": "Required Opus scripts reviewer failed (rc=1); "
                "treated as a blocking finding so a hung/erroring deterministic "
                "reviewer cannot silently converge to PASS (#669).",
                "fix": "Re-run validate_scripts.sh.",
            }
        ],
        "verdict": "request_changes",
        "summary": "Required reviewer failed — fail-closed (#669).",
    }
    result = validation_logic.compute_verdict(
        [required_lane_failure_block], str(ROOT / "does" / "not" / "exist.jsonl"), strict_empty=True
    )
    assert result["verdict"] == "request_changes"
    assert result["new_blocking_count"] > 0


def test_T4_4_optional_lane_absence_does_not_block():
    """A required (opus) lane that reported cleanly, with no optional-lane
    (agy/codex) block present at all — matching --skip-3p, or the CLI simply
    not being installed — must not force a block on its own."""
    clean_required_lane_only = {
        "reviewer": "opus-self",
        "lens": "scripts",
        "findings": [],
        "verdict": "approve",
        "summary": "Clean.",
    }
    result = validation_logic.compute_verdict(
        [clean_required_lane_only], str(ROOT / "does" / "not" / "exist.jsonl"), strict_empty=True
    )
    assert result["verdict"] == "approve"
    assert result["new_blocking_count"] == 0


def test_T4_4_skip_3p_flag_still_exists():
    """The optional lanes remain independently skippable post-migration — the
    flag wiring itself (SKIP_AGY/SKIP_CODEX) is untouched by W4."""
    text = (ROOT / "scripts" / "framework" / "validate_scripts.sh").read_text()
    assert "--skip-agy" in text and "--skip-codex" in text and "--skip-3p" in text
    assert "SKIP_AGY=true; SKIP_CODEX=true" in text
