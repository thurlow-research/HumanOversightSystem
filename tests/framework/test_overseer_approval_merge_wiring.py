"""Text-pin tests for #2213 slice S1b — the overseer wiring of
`bootstrap/overseer_merge.sh on-human-approval`
(docs/v0.7.0/ADR-2213-merge-on-human-approval.md AD-8, AD-9, AD-11;
docs/v0.7.0/TECHNICAL-DESIGN-2213-merge-on-human-approval.md §10 item 3).

Prose-structure tests in the style of `test_overseer_verdict_artifact.py`: they
read the governance documents and pin the instruction text that makes the
merge-on-approval command run first, retire the old unconditional merge rule,
and keep the AD-11 label semantics. No network.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OVERSEER = ROOT / ".claude" / "agents" / "overseer.md"
WORKER = ROOT / ".claude" / "agents" / "worker.md"
CRON_PROMPT = ROOT / "bootstrap" / "overseer-cron-prompt.md"
CONTRACT = ROOT / "contract" / "OVERSIGHT-CONTRACT.md"
LABELS = ROOT / "docs" / "LABELS.md"

MERGE_CMD = "bash bootstrap/overseer_merge.sh on-human-approval --app overseer --pr <n>"
PROVENANCE_CMD = "bash bootstrap/merge_authority.sh merge-provenance --app overseer --pr <n>"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} is missing — has it moved?"
    return path.read_text(encoding="utf-8")


def _section(text: str, heading_prefix: str, next_heading_prefix: str) -> str:
    """Text from the first line starting with `heading_prefix` up to the next
    line starting with `next_heading_prefix` (or end of file)."""
    start = text.find("\n" + heading_prefix)
    assert start != -1, f"heading {heading_prefix!r} not found"
    assert text.count("\n" + heading_prefix) == 1, f"heading {heading_prefix!r} is not unique"
    start += 1
    end = text.find("\n" + next_heading_prefix, start + 1)
    return text[start:] if end == -1 else text[start:end]


def _overseer_what_you_do() -> str:
    return _section(_read(OVERSEER), "### What you do\n", "### Credentials")


# a. overseer.md step 1a ------------------------------------------------------


def test_overseer_what_you_do_contains_literal_merge_command():
    assert MERGE_CMD in _overseer_what_you_do(), (
        "overseer.md '### What you do' must carry the literal on-human-approval command"
    )


def test_overseer_step_1a_runs_before_review_work():
    section = _overseer_what_you_do()
    step_1a = section.find("\n1a. ")
    step_2a = section.find("\n2a. ")
    assert step_1a != -1, "step 1a missing from '### What you do'"
    assert step_2a != -1, "step 2a (CI terminal-state precheck) missing"
    assert step_1a < step_2a, "step 1a must appear before step 2a — it runs before review work"
    assert section.find(MERGE_CMD) < step_2a, "merge command must sit inside step 1a, before 2a"


def test_overseer_step_1a_names_all_outcomes_and_defer_posts_nothing():
    section = _overseer_what_you_do()
    step_1a = section[section.find("\n1a. "): section.find("\n2. ")]
    for outcome in ("MERGED", "DEFER", "NOT_ELIGIBLE", "UNDETERMINABLE"):
        assert f"`{outcome}`" in step_1a, f"step 1a must name outcome {outcome}"
    defer_line = next(line for line in step_1a.splitlines() if "`DEFER`" in line)
    assert "post nothing" in defer_line, "step 1a must say DEFER posts nothing"


# b. cron prompt --------------------------------------------------------------


def test_cron_prompt_runs_merge_command_before_check_pr_reviewed():
    text = _read(CRON_PROMPT)
    assert MERGE_CMD in text, "cron prompt must carry the literal on-human-approval command"
    reviewed = text.find("bash scripts/oversight/check_pr_reviewed.sh")
    assert reviewed != -1, "check_pr_reviewed.sh command missing from cron prompt"
    assert text.find(MERGE_CMD) < reviewed, (
        "merge-on-approval must run before the idempotency precheck"
    )


# c. retired rule -------------------------------------------------------------


def test_retired_unconditional_merge_rule_is_gone():
    text = _read(OVERSEER)
    for phrase in ("merge immediately — unconditional", "CRITICAL-tier rule (3)", "item (3))"):
        assert phrase not in text, f"retired rule text still present in overseer.md: {phrase!r}"


# d. expected action ----------------------------------------------------------


def test_expected_action_stays_approve_after_human_approval():
    assert "The expected action stays `APPROVE` after a human has approved this head" in _read(
        OVERSEER
    )


# e. loop-start provenance check ----------------------------------------------


def test_loop_start_precheck_uses_merge_provenance():
    section = _section(_read(OVERSEER), "### Loop-start precheck", "### Release-gate")
    assert PROVENANCE_CMD in section, "loop-start precheck must run merge-provenance"
    assert "authorized_on_human_approval" in section


def test_cron_prompt_step0_uses_merge_provenance():
    section = _section(_read(CRON_PROMPT), "**Step 0 — Between-cycle", "**Step 0b")
    assert PROVENANCE_CMD in section
    assert "authorized_on_human_approval" in section


# f. contract §6a events ------------------------------------------------------


def test_contract_lists_every_approval_merge_event():
    from scripts.automation.lib import approval_merge

    contract = _read(CONTRACT)
    for name in ("EVENT_AUTHORIZED", "EVENT_MERGED", "EVENT_FAILED", "EVENT_BASE_MISMATCH"):
        event = getattr(approval_merge, name)
        assert f"| `{event}` |" in contract, (
            f"contract §6a has no table row for {name} ({event!r})"
        )


# g. LABELS.md needs-human meaning --------------------------------------------


def test_labels_needs_human_row_states_ad11_meaning():
    rows = [r for r in _read(LABELS).splitlines() if r.startswith("| `needs-human` |")]
    assert len(rows) == 1, "expected exactly one needs-human row in docs/LABELS.md"
    assert "the overseer is waiting for you" in rows[0]
    assert "never with a comment alone" in rows[0]


# h. no overseer `unlabeled` is a resume --------------------------------------


def test_worker_r5_still_requires_human_codeowner_unlabeled_actor():
    section = _section(_read(WORKER), "### Step R5", "### Step R6")
    assert "most recent `unlabeled` event for `needs-human` — `actor.login`" in section
    assert "must NOT be in `BOT_ACCOUNTS`" in section
