"""AC-2 guard: #1034's JS lane must not perturb the Python path (epic #1029, S1).

`run_validators.sh` feeds the composite risk score, which is a PROTECTED SURFACE:
a change that shifts the score on an unrelated Python changeset silently re-tiers
every future PR. S1 adds a parallel `JS_FILES` routing lane, so the binding
acceptance criterion is that a Python-only changeset comes out *byte-identical*.

Two levels of assertion:

1. **Seam level** — with a Python-only diff, `JS_FILES` is empty and the
   `ALL_FILES`/`PY_FILES` split is exactly what it was before S1.
2. **Composite golden** — a full hermetic run (validators served by the canned
   shim, see `fixtures/validator_python_shim.py`) reproduces
   `fixtures/composite_golden_python_only.json`, a fingerprint captured from
   pre-S1 `main` (DQ-5 fallback: `test_validators_mocked.py` carries per-validator
   assertions but no composite baseline to reuse).

The golden pins score, tier, validator count, and the exact (dimension, score,
weight) set — so a dropped dimension, a doubled dispatch, or a changed argv that
reaches a different file set all surface as a failure rather than a quiet drift.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.oversight.run_validators_harness import (
    OUT_REL,
    argv_fingerprint,
    commit_files,
    composite_fingerprint,
    filelist_split,
    hermetic_run,
    init_repo,
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDEN = _FIXTURES / "composite_golden_python_only.json"
_GOLDEN_ARGV = _FIXTURES / "argv_golden_python_only.json"

# The same Python-only fixture the golden was captured from. Changing it
# invalidates the golden — recapture deliberately, never to make a test pass.
_PY_ONLY = {
    "pkg/mod.py": "def f(x):\n    return x + 1\n",
    "pkg/util.py": "def g():\n    return 42\n",
}


def _python_only_repo(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_files(tmp_path, _PY_ONLY, subject="add python module")


def test_python_only_diff_leaves_js_files_empty(tmp_path: Path):
    """The mechanical half of AC-2: no Python file may leak into the JS lane."""
    _python_only_repo(tmp_path)

    split = filelist_split(tmp_path, "--diff", "HEAD~1")

    assert split["JS_FILES"] == []
    assert split["ALL_FILES"] == ["pkg/mod.py", "pkg/util.py"]
    assert split["PY_FILES"] == ["pkg/mod.py", "pkg/util.py"]


def test_python_only_composite_matches_pre_s1_golden(tmp_path: Path):
    """The real AC-2 assertion: identical composite score and tier."""
    _python_only_repo(tmp_path)

    proc = hermetic_run(tmp_path, "pkg/mod.py", "pkg/util.py")
    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"

    golden = json.loads(_GOLDEN.read_text())
    actual = composite_fingerprint(tmp_path)

    assert actual["composite_score"] == golden["composite_score"], (
        "composite score drifted on a Python-only changeset — the JS lane must "
        f"be inert here.\n{proc.stdout}"
    )
    assert actual["tier"] == golden["tier"]
    # Compare as lists-of-lists; json round-trips tuples to lists.
    assert [list(d) for d in actual["dimensions"]] == [list(d) for d in golden["dimensions"]]
    assert actual["validator_count"] == golden["validator_count"]
    assert actual["successful_validators"] == golden["successful_validators"]


def test_python_only_dispatches_no_js_validator(tmp_path: Path):
    """No `*_js.json` result file may be produced by a Python-only changeset."""
    _python_only_repo(tmp_path)

    hermetic_run(tmp_path, "pkg/mod.py", "pkg/util.py")

    produced = {p.name for p in (tmp_path / OUT_REL).glob("*.json")}
    assert not [n for n in produced if n.endswith("_js.json")], produced


def test_python_only_validator_argv_matches_pre_s1_golden(tmp_path: Path):
    """Every validator must be dispatched with the exact pre-S1 argv.

    Stronger than the composite check, which a canned score could mask: this
    pins the literal command line, so S1.4's `PY_FILES ∪ JS_FILES` union has to
    collapse to exactly `"${PY_FILES[@]}"` when the JS lane is empty. The golden
    was captured by running pre-S1 `main`'s script under the same shim.
    """
    _python_only_repo(tmp_path)

    proc = hermetic_run(tmp_path, "pkg/mod.py", "pkg/util.py")
    assert proc.returncode == 0, f"run failed:\n{proc.stdout}\n{proc.stderr}"

    golden = json.loads(_GOLDEN_ARGV.read_text())
    assert argv_fingerprint(tmp_path) == [list(c) for c in golden]


def test_prompt_ambiguity_union_collapses_to_py_files(tmp_path: Path):
    """S1.4 focused: the un-gated call still receives only the Python files."""
    _python_only_repo(tmp_path)

    hermetic_run(tmp_path, "pkg/mod.py", "pkg/util.py")

    calls = {c[0]: c[1:] for c in argv_fingerprint(tmp_path)}
    assert calls["prompt_audit_risk.py"] == [
        "--prompts-dir",
        "prompts",
        "--step",
        "",
        "pkg/mod.py",
        "pkg/util.py",
    ]
    result = json.loads((tmp_path / OUT_REL / "prompt_ambiguity.json").read_text())
    assert result.get("error") is None
