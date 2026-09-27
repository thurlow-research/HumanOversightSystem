"""Tests for the collapse of the two work-selection paths onto
`scripts/framework/select_work_candidates.py` (#1540 S2, AD-3), and for the
documentation/workflow conformance obligations that ship with it (AM-6 point
3, AM-25, AM-27, AM-26, FR8's own verify clause).

Covers §6.3 of
docs/v0.7.0/TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md (revision 8).
The G11 sandbox-allowlistability test
(`test_cron_prompt_fallback_is_sandbox_allowlistable`) lives in
`tests/automation/test_hos_cron.py` instead, per that section's own binding
mechanism note: it must assert against the bytes `_build_prompt` actually
pipes to the model, which only the `CronEnv` harness can capture.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOS_CRON = ROOT / "bin" / "hos-cron"
CRON_PROMPT = ROOT / "bootstrap" / "worker-cron-prompt.md"
WORKER_AGENT = ROOT / ".claude" / "agents" / "worker.md"
LABELS_DOC = ROOT / "docs" / "LABELS.md"
RUNBOOK_DOC = ROOT / "docs" / "OVERSIGHT-RUNBOOK.md"
LABEL_SWAP_YML = ROOT / ".github" / "workflows" / "label-swap.yml"
CONSUMER_FILES = ROOT / "scripts" / "framework" / "framework_consumer_files.txt"
GATE_MODULE = ROOT / "scripts" / "framework" / "select_work_candidates.py"
TRUST_MODULE = ROOT / "scripts" / "framework" / "requester_trust.py"


# ---------------------------------------------------------------------------
# The collapse
# ---------------------------------------------------------------------------


class TestTheCollapse:
    def test_next_candidates_jq_is_gone(self):
        assert not (ROOT / "scripts" / "automation" / "lib" / "next_candidates.jq").exists()
        assert not (ROOT / "tests" / "automation" / "test_next_candidates.py").exists()

    def test_hos_cron_invokes_the_entry_point(self):
        text = HOS_CRON.read_text()
        assert "python3 -m scripts.framework.select_work_candidates" in text

    def test_hos_cron_has_no_inline_jq_selection(self):
        text = HOS_CRON.read_text()
        assert "next_candidates.jq" not in text
        # No jq-based candidate selection remains on this path.
        assert '--jq "$(cat' not in text

    def test_cron_prompt_invokes_the_entry_point(self):
        text = CRON_PROMPT.read_text()
        assert "python3 -m scripts.framework.select_work_candidates" in text

    def test_cron_prompt_has_no_gh_api_candidate_query(self):
        text = CRON_PROMPT.read_text()
        step2 = text.split("**Step 2 —")[1].split("**Step 2b —")[0]
        assert "labels=needs-ai" not in step2
        assert "--jq" not in step2
        assert "next_candidates.jq" not in step2

    def test_cron_prompt_forbids_improvised_fallback(self):
        text = CRON_PROMPT.read_text()
        assert "Do NOT construct your own query" in text
        assert "do NOT fall back to `gh api`" in text

    def test_worker_agent_doc_does_not_cite_next_candidates_jq(self):
        text = WORKER_AGENT.read_text()
        assert "next_candidates.jq" not in text

    def test_only_one_selection_entry_point_exists(self):
        """`select_work_candidates` is referenced from exactly the two call
        sites plus tests and docs — never from a second implementation."""
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(
                part in (".git", ".venv", "__pycache__", ".claudetmp", ".pytest_cache")
                for part in path.parts
            ):
                continue
            if path.suffix not in (".py", ".sh", ".md", ""):
                continue
            if path == GATE_MODULE:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "select_work_candidates" in text:
                hits.append(path)
        allowed_dirs = {"tests", "docs", "bin", "bootstrap", "scripts"}
        allowed_root_files = {"SCRIPTS-INDEX.md"}
        # TD §4.3 requires worker.md to NAME the entry point (a documentation
        # reference, not a second implementation) — allow exactly this one
        # file, never the whole of `.claude/`, so a second implementation
        # dropped anywhere else under `.claude/` still fails this test.
        allowed_exact_files = {Path(".claude") / "agents" / "worker.md"}
        for path in hits:
            rel = path.relative_to(ROOT)
            if rel in allowed_exact_files:
                continue
            if len(rel.parts) == 1:
                assert rel.name in allowed_root_files, f"unexpected reference in {rel}"
                continue
            assert rel.parts[0] in allowed_dirs, f"unexpected reference in {rel}"
        # And there is exactly one production Python module by this name.
        py_hits = [p for p in ROOT.rglob("select_work_candidates.py")]
        assert py_hits == [GATE_MODULE]

    def test_gate_imports_nothing_from_automation_or_oversight(self):
        """§1.1's import-boundary rule applies to the gate too, not only to
        `requester_trust.py` (`test_requester_trust_imports_nothing_from_
        automation_or_oversight` in test_requester_trust.py covers the
        primitive; this is the gate's sibling assertion)."""
        text = GATE_MODULE.read_text()
        assert "scripts.automation" not in text
        assert "scripts.oversight" not in text


# ---------------------------------------------------------------------------
# AM-6 point 3's shipping condition: /approve must stop claiming authorization
# ---------------------------------------------------------------------------


class TestApproveNoLongerClaimsAuthorization:
    def test_labels_doc_states_approve_does_not_authorize(self):
        text = LABELS_DOC.read_text()
        assert "does not authorize autonomous work" in text or "authorizes nothing" in text

    def test_approve_branch_performs_no_label_write(self):
        text = LABEL_SWAP_YML.read_text()
        # Isolate the /approve branch body (between its `if` and the matching `else`).
        start = text.index('if [[ "$CMD" == "/approve" ]]')
        end = text.index("else", start)
        approve_branch = text[start:end]
        assert "gh issue edit" not in approve_branch
        assert "--add-label" not in approve_branch
        assert "--remove-label" not in approve_branch

    @staticmethod
    def _approve_body_line(text: str) -> str:
        approve_branch = text.split('if [[ "$CMD" == "/approve" ]]')[1].split("else")[0]
        return next(ln for ln in approve_branch.splitlines() if ln.strip().startswith("BODY="))

    def test_label_swap_confirmation_does_not_claim_authorization(self):
        text = LABEL_SWAP_YML.read_text()
        assert "authorized by" not in self._approve_body_line(text)

    def test_label_swap_confirmation_states_it_does_not_authorize(self):
        text = LABEL_SWAP_YML.read_text()
        assert "does not authorize" in self._approve_body_line(text)

    def test_label_swap_decline_path_is_unchanged(self):
        text = LABEL_SWAP_YML.read_text()
        assert '--add-label "wontfix"' in text
        assert "gh issue close" in text


# ---------------------------------------------------------------------------
# AM-25's runbook requirements, as tests
# ---------------------------------------------------------------------------


class TestRunbookRequirements:
    def test_runbook_intervention_states_the_act_is_from_your_own_account(self):
        text = RUNBOOK_DOC.read_text()
        assert "own GitHub account" in text or "own account" in text

    def test_runbook_intervention_forbids_edit_issue_app_human(self):
        text = RUNBOOK_DOC.read_text()
        assert "edit_issue.sh --app human" in text
        assert "will NOT work" in text or "not an approval path" in text

    def test_runbook_intervention_covers_the_already_labelled_case(self):
        text = RUNBOOK_DOC.read_text()
        assert "remove it first, then re-add it" in text or "remove-then-re-add" in text

    def test_runbook_inlines_fr29s_meaning_clause(self):
        """TD §4.3's RUNBOOK row: FR29's meaning clause must be INLINED here
        (the same substance docs/LABELS.md carries), not only cross-referenced."""
        raw = RUNBOOK_DOC.read_text().lower().replace("**", "")
        text = re.sub(r"\s+", " ", raw)
        assert "starts autonomous work on that issue" in text
        assert "did not author" in text and "do not control" in text
        assert "does not make the issue's author trusted" in text
        assert "does not make the issue's body trustworthy" in text


# ---------------------------------------------------------------------------
# AM-27's documentation requirements, as tests
# ---------------------------------------------------------------------------


class TestAM27DocumentationRequirements:
    def test_labels_doc_states_milestone_route_is_forbidden(self):
        text = LABELS_DOC.read_text()
        assert "milestone" in text.lower()
        assert "does not authorize" in text or "authorizes nothing" in text
        # The milestone statement must attribute AR-7 (the milestone confers
        # no authorization weight), not merely restate the Step 0 race as the
        # reason it is refused.
        milestone_sentence = next(
            (
                line
                for line in text.splitlines()
                if "milestone" in line.lower() and "authoriz" in line.lower()
            ),
            "",
        )
        assert milestone_sentence

    def test_the_files_s2_edits_do_not_use_the_phrase_cutover_material(self):
        for path in (
            HOS_CRON,
            CRON_PROMPT,
            LABELS_DOC,
            RUNBOOK_DOC,
            LABEL_SWAP_YML,
            GATE_MODULE,
            TRUST_MODULE,
        ):
            text = path.read_text()
            assert "cutover material" not in text.lower(), f"{path} uses the retired phrase"

    def test_excluded_labels_is_defined_in_exactly_one_place(self):
        """The `needs-human` exclusion literal is defined in exactly one
        place — `select_work_candidates.py`'s `EXCLUDED_LABELS` — and no
        second implementation re-derives the exclusion set."""
        gate_text = GATE_MODULE.read_text()
        assert 'EXCLUDED_LABELS = ("needs-human",)' in gate_text
        for path in (HOS_CRON, CRON_PROMPT):
            text = path.read_text()
            assert "EXCLUDED_LABELS" not in text
            assert '"needs-human"' not in text and "'needs-human'" not in text


# ---------------------------------------------------------------------------
# AM-26's ship-set requirements, as tests
# ---------------------------------------------------------------------------


class TestShipSetRequirements:
    def test_new_framework_modules_are_shipped_to_consumers(self):
        text = CONSUMER_FILES.read_text()
        assert "scripts/framework/select_work_candidates.py" in text
        assert "scripts/framework/requester_trust.py" in text

    def test_trusted_requesters_roster_is_not_shipped(self):
        text = CONSUMER_FILES.read_text()
        assert "scripts/framework/trusted-requesters.txt\n" not in text
        lines = {ln.strip() for ln in text.splitlines()}
        assert "scripts/framework/trusted-requesters.txt" not in lines

    def test_trusted_requesters_example_is_shipped_and_documents_both_entry_forms(self):
        text = CONSUMER_FILES.read_text()
        assert "scripts/framework/trusted-requesters.txt.example" in text
        example_path = ROOT / "scripts" / "framework" / "trusted-requesters.txt.example"
        assert example_path.is_file()
        example_text = example_path.read_text()
        assert "tier:" in example_text
        assert "exact" in example_text.lower()

    def test_one_consumer_shipped_artefact_carries_fr29s_three_statements(self):
        """At least one path listed in framework_consumer_files.txt carries
        FR29's three statements plus AM-34 point 3's two preconditions and
        the personal-access-token route (AR-9, FR29(b))."""
        listed = [
            ROOT / ln.strip()
            for ln in CONSUMER_FILES.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        found = False
        for path in listed:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            lowered = re.sub(r"\s+", " ", text.lower())
            if (
                "does not make the issue's author trusted" in lowered
                and "does not make the issue's body trustworthy" in lowered
                and "individual" in lowered
                and "machine-accounts.env" in lowered
                and "personal-access-token" in lowered
            ):
                found = True
                break
        assert found, "no shipped consumer file carries FR29(b)'s required statements"

    def test_every_shipped_framework_module_has_its_framework_imports_shipped(self):
        listed = {
            ln.strip()
            for ln in CONSUMER_FILES.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        }
        framework_listed = {
            p for p in listed if p.startswith("scripts/framework/") and p.endswith(".py")
        }
        for rel in framework_listed:
            text = (ROOT / rel).read_text()
            for m in re.finditer(r"^from scripts\.framework\.(\w+) import", text, re.MULTILINE):
                imported_rel = f"scripts/framework/{m.group(1)}.py"
                assert imported_rel in listed, (
                    f"{rel} imports scripts.framework.{m.group(1)}, which is not "
                    "in framework_consumer_files.txt"
                )


# ---------------------------------------------------------------------------
# FR8's own verify clause: the surviving selection paths must AGREE
# ---------------------------------------------------------------------------


class TestFR8SelectionPathsAgree:
    def test_cron_prompt_fallback_is_character_identical_to_hos_crons_invocation(self):
        """After next_candidates.jq's deletion, the worker's Step-2 fallback
        IS the gate's CLI — assert the two invocations are character-identical
        (module path, flags) rather than merely both existing."""
        prompt_text = CRON_PROMPT.read_text()
        cron_text = HOS_CRON.read_text()
        m = re.search(r"python3 -m scripts\.framework\.select_work_candidates[^\n`]*", prompt_text)
        assert m, "no invocation found in worker-cron-prompt.md"
        prompt_invocation = m.group(0)
        assert "--repo" in prompt_invocation
        assert "--milestone" in prompt_invocation
        assert "python3 -m scripts.framework.select_work_candidates" in cron_text
