"""`.env` reviewer-threshold clamp for scripts/run_second_review.sh (#985).

`run_second_review.sh` deliberately does NOT source the repo-local `.env` (it is
author-controlled; sourcing would execute author code before the gate — #765). It
does, however, extract the two reviewer-firing thresholds from that untrusted
`.env`. Before #985 it did so with no upper bound, so an author under review could
commit `OVERSIGHT_AGY_THRESHOLD=9` (and codex likewise) to *raise* the thresholds
above any composite score → `select_reviewers` returns (false, false) → the script
writes a `verdict: skipped` sentinel and exits 0, silently suppressing the
cross-vendor second review.

The fix: a `.env` value may only *lower* (strengthen) a threshold, never raise it.
The effective threshold is min(trusted_baseline, clamp(env_value, 0, 1)); malformed
or out-of-range values are ignored and the baseline is kept.

These tests drive the real script as a subprocess with a crafted `.env` in a tmp
cwd. They exercise only the skip path (score below both effective thresholds, no
`--tier`), which writes the sentinel BEFORE any reviewer CLI is consulted — so they
are hermetic (no agy/codex needed) and assert on the thresholds the sentinel echoes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_second_review.sh"


def _run(tmp_path: Path, env_body: str | None, step: str, score: str
         ) -> subprocess.CompletedProcess:
    if env_body is not None:
        (tmp_path / ".env").write_text(env_body)
    return subprocess.run(
        ["bash", str(_SCRIPT), "--step", step, "--score", score],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
    )


def _sentinel_fields(tmp_path: Path, step: str) -> dict[str, str]:
    """Parse the `key: value` lines of the skip sentinel for the given step."""
    matches = sorted((tmp_path / ".claudetmp" / "second-review").glob(f"step{step}-*.md"))
    assert matches, f"no skip sentinel written for step {step}"
    fields: dict[str, str] = {}
    for line in matches[-1].read_text().splitlines():
        if ": " in line:
            k, _, v = line.partition(": ")
            fields[k.strip()] = v.strip()
    return fields


def test_env_raise_is_ignored(tmp_path):
    """The headline #985 attack: `.env` inflates both thresholds to 9 to self-skip.
    The raise must be ignored — effective thresholds stay at the trusted defaults."""
    r = _run(tmp_path,
             "OVERSIGHT_AGY_THRESHOLD=9\nOVERSIGHT_CODEX_THRESHOLD=9\n",
             step="1", score="0.1")
    assert r.returncode == 0, r.stderr
    fields = _sentinel_fields(tmp_path, "1")
    assert fields["verdict"] == "skipped"
    assert fields["agy_threshold"] == "0.30", fields
    assert fields["codex_threshold"] == "0.55", fields


def test_env_lowering_is_preserved(tmp_path):
    """A `.env` value that LOWERS (strengthens) a threshold is legitimate and kept —
    it can only cause reviewers to fire more readily, never less."""
    r = _run(tmp_path, "OVERSIGHT_AGY_THRESHOLD=0.05\n", step="2", score="0.02")
    assert r.returncode == 0, r.stderr
    fields = _sentinel_fields(tmp_path, "2")
    assert fields["agy_threshold"] == "0.05", fields
    # codex untouched by .env → trusted default.
    assert fields["codex_threshold"] == "0.55", fields


def test_env_above_one_is_ignored(tmp_path):
    """A value above the [0,1] domain is a raise beyond the baseline → ignored."""
    r = _run(tmp_path, "OVERSIGHT_CODEX_THRESHOLD=1.5\n", step="3", score="0.1")
    assert r.returncode == 0, r.stderr
    fields = _sentinel_fields(tmp_path, "3")
    assert fields["codex_threshold"] == "0.55", fields


def test_env_malformed_is_ignored(tmp_path):
    """A non-numeric / malformed value (e.g. `0.3.0`) is ignored; baseline kept."""
    r = _run(tmp_path, "OVERSIGHT_AGY_THRESHOLD=0.3.0\n", step="4", score="0.1")
    assert r.returncode == 0, r.stderr
    fields = _sentinel_fields(tmp_path, "4")
    assert fields["agy_threshold"] == "0.30", fields


def test_no_env_uses_trusted_defaults(tmp_path):
    """Absent a `.env`, the built-in trusted defaults apply unchanged."""
    r = _run(tmp_path, None, step="5", score="0.1")
    assert r.returncode == 0, r.stderr
    fields = _sentinel_fields(tmp_path, "5")
    assert fields["agy_threshold"] == "0.30", fields
    assert fields["codex_threshold"] == "0.55", fields
