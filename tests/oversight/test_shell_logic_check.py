"""
Unit tests for shell_logic_check.py (#1241).

Style mirrors test_validators_integration.py: import the validator module
directly (conftest.py puts scripts/oversight/validators/ on sys.path) and
call main([...]) against real temp files.
"""
import os
import tempfile
import textwrap

import pytest

from shell_logic_check import main as sl_main

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tmpfile(content: str, suffix: str = ".sh") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


CLEAN_SH = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -euo pipefail
    echo "hello"
    python3 script.py "$@"
""")

# Reproduces the canonical fixed-flag-parsing shape used throughout
# bootstrap/*.sh (see bootstrap/create_branch.sh lines ~66-74).
FLAG_PARSE_ONLY_SH = textwrap.dedent("""\
    #!/usr/bin/env bash
    ISSUE=""
    SLUG=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --issue) ISSUE="$2"; shift 2 ;;
            --slug)  SLUG="$2"; shift 2 ;;
            *)       echo "unknown"; exit 1 ;;
        esac
    done
    echo "$ISSUE $SLUG"
""")

# Several genuine decision constructs outside any flag-parsing loop. Includes
# one single-outcome guard clause (no else — exempt) alongside a real if/else
# fork, a case, and a while, so the count exercises both the exemption and
# the constructs it must not swallow.
LOGIC_HEAVY_SH = textwrap.dedent("""\
    #!/usr/bin/env bash
    if [[ -z "$FOO" ]]; then
        echo "missing FOO"
        exit 1
    fi
    if [[ -n "$BAR" ]]; then
        echo "bar set"
    else
        echo "bar unset"
    fi
    case "$MODE" in
        prod) echo "prod" ;;
        *)    echo "other" ;;
    esac
    while read -r line; do
        echo "$line"
    done < input.txt
""")

# Guard-clause fixture pair: identical shape, differing only in else presence.
GUARD_CLAUSE_NO_ELSE_SH = textwrap.dedent("""\
    #!/usr/bin/env bash
    if [[ -z "$x" ]]; then
        err "x required"
    fi
""")

GUARD_CLAUSE_WITH_ELSE_SH = textwrap.dedent("""\
    #!/usr/bin/env bash
    if [[ -z "$x" ]]; then
        a=1
    else
        a=2
    fi
""")


class TestShellLogicCheck:
    def test_no_files(self):
        result = sl_main([])
        assert result["score"] == pytest.approx(0.0)
        assert result["raw_value"]["decision_construct_count"] == 0

    def test_clean_launcher_scores_zero(self):
        path = _tmpfile(CLEAN_SH)
        try:
            result = sl_main([path])
            assert result["score"] == pytest.approx(0.0)
            assert result["findings"] == [] or result["evidence"] == []
        finally:
            os.unlink(path)

    def test_fixed_flag_parsing_shape_exempted(self):
        path = _tmpfile(FLAG_PARSE_ONLY_SH)
        try:
            result = sl_main([path])
            assert result["score"] == pytest.approx(0.0)
            assert result["raw_value"]["decision_construct_count"] == 0
            assert result["evidence"] == []
        finally:
            os.unlink(path)

    def test_logic_heavy_file_scores_nonzero_with_findings(self):
        path = _tmpfile(LOGIC_HEAVY_SH)
        try:
            result = sl_main([path])
            # First if is a single-outcome guard clause (no else - exempt).
            # if/else fork, case, while = 3 decision constructs -> 1-3 band -> 0.3
            assert result["raw_value"]["decision_construct_count"] == 3
            assert result["score"] == pytest.approx(0.3)
            assert len(result["evidence"]) == 1
            assert result["evidence"][0]["file"] == path
        finally:
            os.unlink(path)

    def test_hos_bootstrap_hard_exempted_regardless_of_content(self):
        # Construct a temp file at a path ending in bootstrap/hos_bootstrap.sh
        # (validator checks the path string, not file location) with plenty
        # of decision constructs, and assert it is fully exempted.
        tmpdir = tempfile.mkdtemp()
        bootstrap_dir = os.path.join(tmpdir, "bootstrap")
        os.makedirs(bootstrap_dir)
        path = os.path.join(bootstrap_dir, "hos_bootstrap.sh")
        with open(path, "w") as f:
            f.write(LOGIC_HEAVY_SH)
        try:
            result = sl_main([path])
            assert result["score"] == pytest.approx(0.0)
            assert result["raw_value"]["decision_construct_count"] == 0
            assert path in result["raw_value"]["exempted_files"]
            assert result["evidence"] == []
        finally:
            os.unlink(path)
            os.rmdir(bootstrap_dir)
            os.rmdir(tmpdir)

    def test_result_envelope(self):
        path = _tmpfile(CLEAN_SH)
        try:
            result = sl_main([path])
            for key in ("dimension", "score", "raw_value", "weight",
                        "evidence", "checklist_items", "findings", "error"):
                assert key in result
            assert result["dimension"] == "shell_logic"
        finally:
            os.unlink(path)


class TestShellLogicCheckRealFiles:
    """Empirical sanity check against real files in this repo (#1241)."""

    def test_create_branch_sh_is_a_genuine_thin_launcher_but_has_real_guard_clauses(self):
        path = os.path.join(ROOT, "bootstrap", "create_branch.sh")
        assert os.path.isfile(path)
        result = sl_main([path])
        # create_branch.sh uses the canonical fixed-flag-parsing loop (exempt)
        # plus six standalone `if` statements outside that loop (verified by
        # reading the file: lines ~92, 110, 111, 125, 131, 133) — all six are
        # single-outcome guard clauses (err "...", no else/elif), so each is
        # exempt under the guard-clause rule. Genuine count is zero: this file
        # really is a thin launcher, not a false negative from the exemption
        # over-applying.
        assert result["raw_value"]["decision_construct_count"] == 0
        assert result["score"] == pytest.approx(0.0)

    def test_hos_bootstrap_sh_is_exactly_zero_hard_exemption(self):
        path = os.path.join(ROOT, "bootstrap", "hos_bootstrap.sh")
        assert os.path.isfile(path)
        result = sl_main([path])
        # Large script, many genuine if/case constructs — but it is the
        # machine bootstrap that installs Python itself, hard-exempted by
        # policy (#1241) regardless of content.
        assert result["score"] == pytest.approx(0.0)
        assert result["raw_value"]["decision_construct_count"] == 0
        assert path in result["raw_value"]["exempted_files"]
