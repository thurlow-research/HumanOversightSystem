"""SPEC-374 confidence asymmetry — static grep assertions (T1) and behavioral
invariance test (T2).

T1 — grep assertions (OQ-374-03 primary verifier):
  T1-a  No routing-path agent file instructs reading a CONFIDENCE value to lower a
        tier, remove a reviewer, or reduce sign-offs.
  T1-b  The evaluator emits no own CONFIDENCE field (C3 prohibition present; output
        template has no CONFIDENCE line).
  T1-c  AGENTS.md §3 contains the required asymmetry wording and empirical figures.
  T1-d  The CONFIDENCE self-flag format block is still present in AGENTS.md (C1 was
        additive only).
  T1-e  The CONFIDENCE < 70% Phase-2 bullet is still present in the evaluator (C2
        boundary: existing check preserved).

T2 — behavioral invariance (OQ-374-03 one executable-routing test):
  Guards against future commit-body reads that might import confidence into
  classification.  change_classifier.py is the only deterministic executable on the
  routing path the evaluator drives; the orchestrator and risk-assessor are
  prose-driven (covered by T1 static greps).  Even if the classifier currently does
  not read the commit body at all, this test pins the invariant so a future change
  that starts reading commit bodies cannot silently introduce a confidence dependence.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

# ── Repository root ──────────────────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _REPO / ".claude" / "agents"
_AGENTS_MD = _REPO / "AGENTS.md"

_EVALUATOR = _AGENTS_DIR / "oversight-evaluator.md"
_ORCHESTRATOR = _AGENTS_DIR / "oversight-orchestrator.md"
_RISK_ASSESSOR = _AGENTS_DIR / "risk-assessor.md"

_ROUTING_AGENTS = [_EVALUATOR, _ORCHESTRATOR, _RISK_ASSESSOR]

# ── Load change_classifier without altering sys.path ────────────────────────
_CC_PATH = _REPO / "scripts" / "oversight" / "change_classifier.py"
_cc_spec = importlib.util.spec_from_file_location("change_classifier", _CC_PATH)
cc = importlib.util.module_from_spec(_cc_spec)
_cc_spec.loader.exec_module(cc)


# ── T1-a: no risk-lowering confidence reads in routing-path files ────────────
class TestT1aRoutingExclusion:
    """A confidence value MUST NOT be read to lower oversight in any routing agent."""

    def test_orchestrator_no_risk_lowering_confidence_read(self):
        """oversight-orchestrator.md must not instruct lowering a tier/reviewer on confidence."""
        text = _ORCHESTRATOR.read_text(encoding="utf-8").lower()
        # Pattern: "confidence" near a lowering verb near a governance noun.
        # Split check so we can produce a precise failure message.
        lowering_verbs = ("lower", "reduce", "skip", "waive", "remove")
        gov_nouns = ("tier", "review", "sign-off", "signoff", "reviewer")
        _assert_no_confidence_lowering(text, lowering_verbs, gov_nouns, _ORCHESTRATOR)

    def test_risk_assessor_no_risk_lowering_confidence_read(self):
        """risk-assessor.md must not instruct lowering a tier/reviewer on confidence."""
        text = _RISK_ASSESSOR.read_text(encoding="utf-8").lower()
        lowering_verbs = ("lower", "reduce", "skip", "waive", "remove")
        gov_nouns = ("tier", "review", "sign-off", "signoff", "reviewer")
        _assert_no_confidence_lowering(text, lowering_verbs, gov_nouns, _RISK_ASSESSOR)

    def test_evaluator_allowed_confidence_contexts_only(self):
        """oversight-evaluator.md may reference confidence only in the four allowed contexts:
        (i) the Phase-2 low-confidence flag, (ii) the C2 asymmetry note, (iii) the C4 scan,
        (iv) the C3 prohibition.  It must not instruct lowering a tier/reviewer on confidence.
        """
        text = _EVALUATOR.read_text(encoding="utf-8").lower()
        lowering_verbs = ("lower", "reduce", "skip", "waive", "remove")
        gov_nouns = ("tier", "reviewer", "sign-off", "signoff")
        # Narrow: look for the conjunction confidence + lowering verb + governance noun
        # in the same clause.  We approximate with a 120-char sliding window.
        _assert_no_confidence_lowering(text, lowering_verbs, gov_nouns, _EVALUATOR)


# ── T1-b: evaluator emits no CONFIDENCE field (OQ-374-02) ───────────────────
class TestT1bNoEvaluatorConfidenceField:
    def test_prohibition_bullet_present(self):
        text = _EVALUATOR.read_text(encoding="utf-8")
        assert "Do not emit a `CONFIDENCE:` field" in text, (
            "C3 prohibition bullet missing from oversight-evaluator.md"
        )

    def test_output_template_has_no_confidence_line(self):
        text = _EVALUATOR.read_text(encoding="utf-8")
        # The Output section defines the evaluation .md template.  It must not
        # contain a CONFIDENCE: field/line.
        # Locate the Output section, then assert.
        output_start = text.find("## Output")
        assert output_start != -1, "## Output section not found in oversight-evaluator.md"
        # The output template ends at the next ## heading or end-of-file.
        output_section = text[output_start:]
        next_section = output_section.find("\n## ", 4)
        template_block = output_section[:next_section] if next_section != -1 else output_section
        assert "CONFIDENCE:" not in template_block, (
            "CONFIDENCE: field found inside the ## Output template in oversight-evaluator.md — "
            "the evaluator must not declare confidence (OQ-374-02 / C3)"
        )


# ── T1-c: AGENTS.md asymmetry wording + empirical figures (AC-374-01) ────────
class TestT1cAgentsMdAsymmetryText:
    def test_asymmetry_rule_heading_present(self):
        text = _AGENTS_MD.read_text(encoding="utf-8")
        assert "asymmetry rule" in text, (
            "AGENTS.md §3 missing 'asymmetry rule' (C1 not applied)"
        )

    def test_empirical_figures_present(self):
        text = _AGENTS_MD.read_text(encoding="utf-8")
        for token in ("99.9%", "3.16%", "3.96%", "Ferdous et al. 2026"):
            assert token in text, (
                f"AGENTS.md missing required empirical token '{token}' (AC-374-01)"
            )

    def test_prohibition_wording_present(self):
        text = _AGENTS_MD.read_text(encoding="utf-8")
        assert "MUST NEVER lower a risk tier" in text, (
            "AGENTS.md asymmetry prohibition wording missing (AC-374-01)"
        )


# ── T1-d: CONFIDENCE self-flag format block still present (AC-374-04) ─────────
class TestT1dConfidenceFieldNotRemoved:
    def test_confidence_format_block_present(self):
        text = _AGENTS_MD.read_text(encoding="utf-8")
        assert "CONFIDENCE: [percentage]" in text, (
            "AGENTS.md CONFIDENCE: format block removed — C1 must be additive only (AC-374-04)"
        )


# ── T1-e: CONFIDENCE < 70% Phase-2 bullet still present (AC-374-05) ───────────
class TestT1ePhase2LowConfidenceFlagPreserved:
    def test_low_confidence_flag_bullet_present(self):
        text = _EVALUATOR.read_text(encoding="utf-8")
        assert "CONFIDENCE < 70%" in text, (
            "oversight-evaluator.md CONFIDENCE < 70% Phase-2 bullet removed — "
            "C2 must be additive only (AC-374-05)"
        )


# ── T2: behavioral invariance — change_classifier output is blind to CONFIDENCE ─
class TestT2ConfidenceRoutingInvariance:
    """Guards against future commit-body reads that might import confidence into
    classification.

    The classifier is deterministic and currently operates on diff content only
    (file names and added lines), not commit messages or self-flag blocks.  This
    test pins that invariant: two otherwise-identical diffs that differ only in a
    CONFIDENCE: line must produce identical domains_touched and structural_signals.

    If a future change makes the classifier read commit bodies or self-flag blocks,
    this test turns red — surfacing the confidence-routing dependency before it
    ships.
    """

    def _make_diff_with_confidence(self, confidence_value: str) -> tuple[list, dict]:
        """Produce (name_status, added_lines) for a synthetic diff that includes a
        CONFIDENCE: line in a commit-body-like comment.  All content is identical
        except the confidence percentage.
        """
        # A simple Python file change — touches security domain.
        name_status = [("M", "src/auth/middleware.py")]
        added_lines = {
            "src/auth/middleware.py": [
                f"# CONFIDENCE: {confidence_value}",
                "    def process_request(self, request):",
                "        user = request.user",
            ]
        }
        return name_status, added_lines

    def test_domains_identical_under_varying_confidence(self):
        ns_low, added_low = self._make_diff_with_confidence("40%")
        ns_high, added_high = self._make_diff_with_confidence("99%")

        domains_low = cc.detect_domains(ns_low, added_low)
        domains_high = cc.detect_domains(ns_high, added_high)

        # The set of touched domains must be identical regardless of confidence value.
        assert set(domains_low.keys()) == set(domains_high.keys()), (
            f"domains_touched differ under varying CONFIDENCE: "
            f"40% → {set(domains_low.keys())}, 99% → {set(domains_high.keys())}"
        )

    def test_structural_signals_identical_under_varying_confidence(self):
        ns_low, added_low = self._make_diff_with_confidence("40%")
        ns_high, added_high = self._make_diff_with_confidence("99%")

        sigs_low = {s["signal"] for s in cc.detect_structural(ns_low, added_low)}
        sigs_high = {s["signal"] for s in cc.detect_structural(ns_high, added_high)}

        assert sigs_low == sigs_high, (
            f"structural_signals differ under varying CONFIDENCE: "
            f"40% → {sigs_low}, 99% → {sigs_high}"
        )

    def test_full_json_output_identical_via_subprocess(self):
        """End-to-end: call the classifier via subprocess on a real throwaway git
        repo.  Two commits differ only in a CONFIDENCE: line in the commit message.
        The JSON output domains_touched and structural_signals must be identical.
        """
        import os
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "test_repo"
            repo.mkdir()

            def git(*args: str) -> str:
                result = subprocess.run(
                    ["git", "-C", str(repo)] + list(args),
                    capture_output=True, text=True, check=True
                )
                return result.stdout.strip()

            # Minimal git setup
            git("init")
            git("config", "user.email", "test@test.com")
            git("config", "user.name", "Test")

            src = repo / "src"
            src.mkdir()
            (src / "app.py").write_text("x = 1\n")
            git("add", ".")
            git("commit", "-m", "initial")
            base_sha = git("rev-parse", "HEAD")

            # Commit A: CONFIDENCE: 40%
            (src / "app.py").write_text("x = 1\ny = 2\n")
            git("add", ".")
            git("commit", "-m", "change\n\nCONFIDENCE: 40%\nBasis: low certainty")
            sha_a = git("rev-parse", "HEAD")

            # Reset to base, make identical content change with CONFIDENCE: 99%
            git("reset", "--hard", base_sha)
            (src / "app.py").write_text("x = 1\ny = 2\n")
            git("add", ".")
            git("commit", "-m", "change\n\nCONFIDENCE: 99%\nBasis: very confident")
            sha_b = git("rev-parse", "HEAD")

            def run_classifier(base: str, head: str) -> dict:
                result = subprocess.run(
                    ["python3", str(_CC_PATH),
                     "--base", base, "--head", head],
                    capture_output=True, text=True, cwd=str(repo)
                )
                assert result.returncode == 0, (
                    f"classifier exited {result.returncode}: {result.stderr}"
                )
                return json.loads(result.stdout)

            out_a = run_classifier(base_sha, sha_a)
            out_b = run_classifier(base_sha, sha_b)

            assert set(out_a["domains_touched"].keys()) == set(out_b["domains_touched"].keys()), (
                "domains_touched differ between CONFIDENCE: 40% and CONFIDENCE: 99% commits"
            )
            assert (
                {s["signal"] for s in out_a["structural_signals"]}
                == {s["signal"] for s in out_b["structural_signals"]}
            ), (
                "structural_signals differ between CONFIDENCE: 40% and CONFIDENCE: 99% commits"
            )


# ── helpers ──────────────────────────────────────────────────────────────────

def _assert_no_confidence_lowering(
    text: str,
    lowering_verbs: tuple[str, ...],
    gov_nouns: tuple[str, ...],
    filepath: Path,
    window: int = 120,
) -> None:
    """Slide a window over `text` looking for: 'confidence' within `window` chars
    of both a lowering verb AND a governance noun.  Fails with a precise message.
    """
    conf_positions = []
    start = 0
    while True:
        idx = text.find("confidence", start)
        if idx == -1:
            break
        conf_positions.append(idx)
        start = idx + 1

    for pos in conf_positions:
        snippet = text[max(0, pos - window // 2): pos + window // 2]
        has_verb = any(v in snippet for v in lowering_verbs)
        has_noun = any(n in snippet for n in gov_nouns)
        if has_verb and has_noun:
            # Check if this is one of the four permitted evaluator contexts.
            # We allow: the asymmetry note (one-directional), the C4 scan label,
            # the C3 prohibition, the Phase-2 low-confidence flag (< 70%).
            allowed_markers = (
                "one-directional",
                "confidence-as-justification scan",
                "do not emit a `confidence:`",
                "confidence < 70%",
                "spec-374",
                # Also allow the asymmetry rule's own wording about what is prohibited
                "must never lower a risk tier",
                "prohibition",
            )
            if not any(m in snippet for m in allowed_markers):
                raise AssertionError(
                    f"{filepath.name}: found possible confidence-lowering instruction.\n"
                    f"Snippet: ...{snippet!r}...\n"
                    "If this is a legitimate allowed context, add its marker to "
                    "`allowed_markers` in the test and document why."
                )
