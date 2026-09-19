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
  3. T4.2's "delete both `run_capped` copies" premise (TD §6.3) was amended
     TWICE, in opposite directions, after the TD table was written and never
     revised there. First, ADR-1643 §9.4 (ESC-D/TD-F5, "Amends AD-5.3") took
     `validate_agents.sh`'s copy out of W4 entirely (no `claude` consumer to
     migrate — only `agy`/`codex` — so its deletion is an unrelated refactor,
     moved to follow-up #1671), leaving `validate_scripts.sh`'s copy — the
     one actually attached to a real migration — as the only one W4 deleted.
     Then AD-16.6 (2026-09-19) REVERSED that: a HIGH cross-vendor finding
     (codex, CWE-400) showed `with_timeout` has no equivalent to
     `run_capped`'s TERM/KILL fallback, and `validate_scripts.sh`'s prompt
     embeds attacker-influenceable content (`KNOWN_ISSUES`, from live `gh
     issue list` titles) — turning a lost fallback into a reachable hang on
     a required, fail-closed gate, not a portability nicety. So
     `validate_scripts.sh`'s copy is RESTORED too; W4 now deletes NEITHER
     copy. The ledger after W4: one shared bash helper (`with_timeout`, in
     `scripts/oversight/run_with_retry.sh`) and exactly THREE remaining
     PRIVATE bash timeout-capping copies — `scripts/framework/validate_agents.sh`
     (#1671), `scripts/framework/validate_scripts.sh` (#1757, AD-16.6), and
     `bin/hos-cron` (deliberately out of scope of everything: it bounds a
     whole cron cycle, not an AI review). T4.2 below asserts exactly that
     ledger, using the marker all three private copies actually share
     (`_TIMEOUT_BIN`) rather than the literal string `run_capped`, since
     `bin/hos-cron`'s copy never used that function name. Note
     `validate_scripts.sh` also still appears in T4.1's exemption set, for
     the SEPARATE, independently-tracked #1756 reason (the unmigrated
     `claude -p` opus seat, §6.2/W4c) — the two exemptions are not the same
     thing and must not be conflated.
"""

import ast
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


# ── T4.2 — the private _TIMEOUT_BIN/run_capped copy ledger, per AD-16.6 ────────
#
# AD-16.6 (2026-09-19) REVERSED the earlier AD-5.3-as-amended acceptance:
# codex's HIGH cross-vendor finding (CWE-400) showed `with_timeout`'s missing
# TERM/KILL fallback turns a required, fail-closed gate into one an
# attacker-influenceable input (KNOWN_ISSUES, built from live `gh issue list`
# titles) can hang forever — not the availability nicety it was first framed
# as. validate_scripts.sh's private `run_capped` copy is therefore RESTORED,
# not deleted: W4 changes its timeout behaviour not at all. The fix (porting
# the fallback into with_timeout() itself) is tracked as #1757, not done
# here — that helper has five other live callers, including the blocking
# gates/secret_scan.sh and gates/security_scan.sh, where the timeout argument
# is currently inert on an affected host, so porting the fallback needs its
# own reviewed slice.
_TIMEOUT_BIN_ASSIGNMENT_PATTERN = re.compile(r"_TIMEOUT_BIN\s*=")

# scripts/oversight/run_with_retry.sh is the ADR's "one shared bash helper"
# (with_timeout) — its own _TIMEOUT_BIN is the canonical implementation every
# migrated call site delegates to, not a "private copy", so it is excluded
# from the private-copy ledger below by construction.
_SHARED_HELPER = "scripts/oversight/run_with_retry.sh"

# The three PRIVATE bash timeout-capping copies after W4 (all still use
# `_TIMEOUT_BIN`; only validate_agents.sh's and validate_scripts.sh's wrap it
# in a function literally named `run_capped` — bin/hos-cron's never used
# that name, so this checks the marker all three actually share). Two
# INDEPENDENT reasons put validate_scripts.sh in this set specifically — see
# its comment below; do not conflate them.
_T4_2_EXPECTED_TIMEOUT_BIN_COPIES = {
    # EXEMPT (#1671): moved to a follow-up issue, not W4 — no claude consumer to migrate.
    "scripts/framework/validate_agents.sh",
    # EXEMPT (#1757, AD-16.6): the attacker-influenceable-hang finding above — a
    # DIFFERENT reason than this same file's T4.1 exemption (#1756, the
    # unmigrated claude -p seat). validate_scripts.sh is tracked in BOTH
    # ledgers, independently.
    "scripts/framework/validate_scripts.sh",
    # EXEMPT: out of scope of W4 and every follow-up — bounds a whole cron cycle, not an AI review.
    "bin/hos-cron",
}


def test_T4_2_private_timeout_bin_copy_ledger_is_exactly_three():
    """One shared bash helper (with_timeout, excluded here) and exactly the
    three remaining private copies named above. If a fourth copy appears, or
    one of these three is unexpectedly migrated/deleted without updating
    this ledger, this test catches the drift."""
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
        f"{sorted(_T4_2_EXPECTED_TIMEOUT_BIN_COPIES)} (one shared helper in "
        "run_with_retry.sh, three remaining private copies, AD-16.6)."
    )


def test_T4_2_validate_scripts_run_capped_is_unchanged_by_w4():
    """Net effect of AD-16.6: validate_scripts.sh's timeout behaviour is
    untouched by W4. All three run_reviewer branches still call the private
    run_capped, and no CODE line (comments may explain the rejected
    alternative by name, per AD-16.6's own restored comment) depends on
    with_timeout/run_with_retry.sh."""
    path = ROOT / "scripts" / "framework" / "validate_scripts.sh"
    text = path.read_text(encoding="utf-8")
    assert 'run_capped "$AI_REVIEW_TIMEOUT" "$out" claude -p --model "$MODEL"' in text
    assert 'run_capped "$AI_REVIEW_TIMEOUT" "$out" agy --sandbox -p "$prompt"' in text
    assert 'run_capped "$AI_REVIEW_TIMEOUT" "$out" codex exec' in text
    for lineno, line in _code_lines(path):
        assert (
            "with_timeout" not in line
        ), f"validate_scripts.sh:{lineno} still calls with_timeout: {line!r}"
        assert (
            "run_with_retry.sh" not in line
        ), f"validate_scripts.sh:{lineno} still sources run_with_retry.sh: {line!r}"


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
#    failure occurred (outcome/outcome_detail), not just THAT one did; and
#    codex's cross-vendor finding — it must use the SAME parser the
#    finalizer uses, so status reporting and the blocking decision can never
#    read the same bytes differently ────────────────────────────────────────
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
# than a hand-copied duplicate. The snippet now parses through
# validation_logic.extract_json_objects — the same function the finalizer
# uses — so it takes validation_logic.py's path as sys.argv[1]; every
# subprocess.run below passes it explicitly for that reason.
def _extract_opus_outcome_detail_python_snippet():
    text = (ROOT / "scripts" / "framework" / "validate_self.sh").read_text(encoding="utf-8")
    match = re.search(r"python3 -c '\n(.*?)\n'", text, re.DOTALL)
    assert match, (
        "could not find the outcome/outcome_detail extraction python3 -c "
        "snippet in validate_self.sh — has the status-line fix (#1676) been "
        "removed or reshaped?"
    )
    return match.group(1)


def _run_opus_status_snippet(doc_text: str) -> subprocess.CompletedProcess:
    snippet = _extract_opus_outcome_detail_python_snippet()
    return subprocess.run(
        ["python3", "-c", snippet, str(_VALIDATION_LOGIC_PATH)],
        input=doc_text,
        capture_output=True,
        text=True,
    )


def test_status_line_surfaces_outcome_detail_on_invocation_failed():
    doc = '{"outcome":"invocation_failed","outcome_detail":"not_authenticated","findings":[],"verdict":"error"}'
    result = _run_opus_status_snippet(doc)
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "invocation_failed"
    assert detail == "not_authenticated"


def test_status_line_reports_completed_outcome_with_no_detail():
    doc = '{"outcome":"completed","outcome_detail":null,"verdict":"approve","findings":[]}'
    result = _run_opus_status_snippet(doc)
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "completed"
    assert detail == "-"


def test_status_line_handles_unparseable_output_without_crashing():
    result = _run_opus_status_snippet("not json at all")
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "__PARSE_ERROR__"
    assert detail == "__PARSE_ERROR__"


def test_status_line_fails_closed_on_multiple_blocks_rather_than_risk_a_false_done():
    """codex's finding, made concrete: if the input ever contains more than
    one parseable JSON block (never true for a real invoke_agent.sh emission,
    but the whole point is not to assume that), the status line must not
    silently report "done" off block[0] while a later block would have made
    the finalizer's aggregate block. It must fail closed instead."""
    doc = (
        '{"outcome":"completed","verdict":"approve","findings":[]} '
        '{"outcome":"invocation_failed","outcome_detail":"crash","verdict":"error","findings":[]}'
    )
    result = _run_opus_status_snippet(doc)
    assert result.returncode == 0, result.stderr
    outcome, _, detail = result.stdout.strip().partition("\t")
    assert outcome == "__PARSE_ERROR__"
    assert detail == "__PARSE_ERROR__"


def test_status_line_uses_the_same_extractor_the_finalizer_uses():
    """Static guard against the exact parser-divergence codex flagged: the
    embedded snippet must call validation_logic's own extract_json_objects,
    not a bare json.load, so status reporting and the blocking decision
    (python3 "$VALIDATION_LOGIC" process, below in the same file) can never
    read the same $OPUS_OUT bytes through two different parsers."""
    snippet = _extract_opus_outcome_detail_python_snippet()
    assert "extract_json_objects" in snippet
    assert "json.load(sys.stdin)" not in snippet


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
    text = (ROOT / "scripts" / "framework" / "validate_scripts.sh").read_text(encoding="utf-8")
    assert "--skip-agy" in text and "--skip-codex" in text and "--skip-3p" in text
    assert "SKIP_AGY=true; SKIP_CODEX=true" in text


# ── agy finding (round N) — every read_text() in THIS file passes an explicit
#    encoding. This module reads its own subject files (validate_self.sh,
#    validate_scripts.sh, ...), which contain non-ASCII (em dash, §); under a
#    C/ASCII locale a bare .read_text() raises UnicodeDecodeError rather than
#    reading the file. A regression here would break every test that follows
#    it, silently, on any host with a non-UTF-8 default locale.
def test_this_test_file_never_reads_text_without_an_explicit_encoding():
    """AST-based, not a text/regex scan: a substring or regex check over this
    file's own source text is self-referential (this very check's code and
    docstrings legitimately mention `.read_text(` in prose/string literals,
    which a naive scan flags against itself). Walking the parsed syntax tree
    for actual `.read_text(...)` Call nodes sidesteps that entirely."""
    this_file = Path(__file__)
    tree = ast.parse(this_file.read_text(encoding="utf-8"), filename=str(this_file))
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read_text"
        ):
            continue
        has_encoding = any(kw.arg == "encoding" for kw in node.keywords)
        assert has_encoding, (
            f"{this_file.name}:{node.lineno} calls .read_text() without an "
            "explicit encoding= keyword argument"
        )
