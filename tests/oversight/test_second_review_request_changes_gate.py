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

import os
import subprocess
from pathlib import Path

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


def _run(tmp_path: Path, agy_json: str, score: str) -> subprocess.CompletedProcess:
    """Drive the real script with a fake `agy` emitting `agy_json` on PATH."""
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
        ["bash", str(_SCRIPT), "--files", "target.py",
         "--step", "3", "--tier", "MEDIUM", "--score", score],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=120, env=env,
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
