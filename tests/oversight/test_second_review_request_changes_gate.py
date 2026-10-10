"""Blocking-verdict fail-close for scripts/run_second_review.sh (#986).

`validation_logic.py process` sets `verdict: request_changes` iff
`new_blocking_count > 0` — the cross-vendor review surfaced blocking findings not
already dispositioned in this step's convergence ledger — and then exits 0 for
EVERY verdict ("the shell decides pass/fail", binding 3). Before #986 the shell's
final guards only fail-closed on `verdict == error` (exit 1) and warned on
`unparseable` (exit 0); a parseable `request_changes` fell through both branches
→ the script exited 0. `run_review_chain.sh:278` gates purely on that exit code,
so a blocking cross-vendor verdict silently printed "second review passed" and
the chain proceeded to the panel. The blocking finding survived only in the
`.claudetmp/second-review/…` artifact, which nothing downstream reads.

The fix: the shell exits 2 (distinct from the reviewer-error exit 1) on a
`request_changes` verdict, so `run_review_chain.sh`'s `else die` branch halts the
pre-PR chain until the findings are dispositioned.

These tests drive the real script as a subprocess with a fake `agy` on PATH so
they are hermetic (no real agy/codex, no network). The fake reviewer emits a
`blocking`-severity finding, which counts as blocking for the verdict but is NOT
`critical`/`high`, so `create_finding_issues` never shells out to `gh` — the test
touches no GitHub state.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.tmp_hygiene import child_env

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_second_review.sh"

# A JSON object salvage_review_json/parse_json_blocks will keep (has findings +
# verdict). `severity: blocking` is in BLOCKING_SEVERITIES yet not critical/high,
# so it gates the verdict without triggering a `gh issue create`.
_AGY_REQUEST_CHANGES = (
    '{"reviewer":"agy","lens":"correctness",'
    '"findings":[{"severity":"blocking","file":"target.py","line":1,'
    '"finding":"unchecked auth path","suggestion":"add an authz check"}],'
    '"verdict":"request_changes","summary":"one blocking finding"}'
)
_AGY_APPROVE = (
    '{"reviewer":"agy","lens":"correctness","findings":[],'
    '"verdict":"approve","summary":"no findings"}'
)


def _run(
    tmp_path: Path, agy_json: str, score: str, ledger_entry: dict | None = None
) -> subprocess.CompletedProcess:
    """Drive the real script with a fake `agy` emitting `agy_json` on PATH.

    `ledger_entry`, if given, is written to the step-3 convergence ledger first.
    """
    if ledger_entry is not None:
        ledger_dir = tmp_path / ".claudetmp" / "second-review"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        (ledger_dir / "step3-ledger.jsonl").write_text(json.dumps(ledger_entry) + "\n")
    # A real file to review → non-empty DIFF_CONTENT via the `--files` cat fallback
    # (tmp cwd is not a git repo, so `git diff HEAD` fails and the script cats it).
    (tmp_path / "target.py").write_text("def f():\n    return 1\n")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    agy = fake_bin / "agy"
    # Ignore all args; emit the canned JSON review on stdout.
    agy.write_text("#!/usr/bin/env bash\ncat <<'JSON'\n" + agy_json + "\nJSON\n")
    agy.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    return subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "3",
            "--tier",
            "MEDIUM",
            "--score",
            score,
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=child_env(env),
    )


def _artifact_fields(tmp_path: Path, step: str) -> dict[str, str]:
    """Parse the `key: value` header lines of the second-review artifact."""
    matches = sorted((tmp_path / ".claudetmp" / "second-review").glob(f"step{step}-*.md"))
    assert matches, f"no second-review artifact written for step {step}"
    fields: dict[str, str] = {}
    for line in matches[-1].read_text().splitlines():
        if line.startswith("verdict:") or ": " in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields


def test_request_changes_blocking_fails_closed(tmp_path):
    """The #986 headline: a parseable `request_changes` verdict with a NEW blocking
    finding must halt the chain via a non-zero exit — not fall through to exit 0."""
    r = _run(tmp_path, _AGY_REQUEST_CHANGES, score="0.5")
    assert r.returncode == 2, f"expected fail-closed exit 2, got {r.returncode}\n{r.stderr}"
    assert "FAIL-CLOSED" in r.stderr, r.stderr
    assert "request_changes" in r.stderr, r.stderr
    # The artifact records the blocking verdict the chain must act on.
    fields = _artifact_fields(tmp_path, "3")
    assert fields.get("verdict") == "request_changes", fields
    assert int(fields.get("new_blocking_count", "0")) >= 1, fields


def test_request_changes_exit_code_distinct_from_reviewer_error(tmp_path):
    """The blocking-verdict exit (2) is distinct from the reviewer-error exit (1),
    so a chain/operator can tell "review found blocking findings" from "a reviewer
    crashed and produced no judgment"."""
    r = _run(tmp_path, _AGY_REQUEST_CHANGES, score="0.5")
    assert r.returncode == 2, r.stderr
    # An empty agy response would classify as verdict=error → exit 1 (existing guard).
    err = _run(tmp_path, "", score="0.5")
    assert err.returncode == 1, err.stderr


def test_approve_verdict_still_passes(tmp_path):
    """Regression guard: a clean `approve` verdict must NOT be caught by the new
    fail-close — the reviewer fired, found nothing blocking, and the chain proceeds."""
    r = _run(tmp_path, _AGY_APPROVE, score="0.5")
    assert r.returncode == 0, f"approve must exit 0, got {r.returncode}\n{r.stderr}"
    fields = _artifact_fields(tmp_path, "3")
    assert fields.get("verdict") == "approve", fields


# #2036: aggregate must honour the ledger, or the no-downgrade ratchet in
# `process` makes a step whose only blocking finding is already filed
# unconvergeable. The finding below is `blocking` (not critical/high) so the run
# never shells out to `gh`.
_AGY_LEDGERABLE = (
    '{"reviewer":"agy","lens":"correctness",'
    '"findings":[{"severity":"blocking","file":"target.py","category":"CWE-20",'
    '"line":1,"finding":"unvalidated input","suggestion":"validate"}],'
    '"verdict":"request_changes","summary":"one blocking finding"}'
)


def _ledger(disposition: str) -> dict:
    return {"files": ["target.py"], "class": "CWE-20", "disposition": disposition}


def test_ledgered_filed_blocking_finding_converges(tmp_path):
    r = _run(tmp_path, _AGY_LEDGERABLE, score="0.5", ledger_entry=_ledger("filed:#2032"))
    assert r.returncode == 0, f"ledgered finding must converge, got {r.returncode}\n{r.stderr}"
    fields = _artifact_fields(tmp_path, "3")
    assert fields.get("verdict") == "approve", fields
    assert fields.get("new_blocking_count") == "0", fields


def test_ledgered_fixed_blocking_finding_converges(tmp_path):
    r = _run(tmp_path, _AGY_LEDGERABLE, score="0.5", ledger_entry=_ledger("fixed"))
    assert r.returncode == 0, r.stderr


def test_unledgered_blocking_finding_still_fails_closed(tmp_path):
    r = _run(tmp_path, _AGY_LEDGERABLE, score="0.5")
    assert r.returncode == 2, r.stderr


def test_noise_and_residual_dispositions_do_not_converge(tmp_path):
    for disposition in ("noise", "residual"):
        case = tmp_path / disposition
        case.mkdir()
        r = _run(case, _AGY_LEDGERABLE, score="0.5", ledger_entry=_ledger(disposition))
        assert r.returncode == 2, f"{disposition} must not resolve: {r.returncode}\n{r.stderr}"
        assert _artifact_fields(case, "3").get("verdict") == "request_changes"
