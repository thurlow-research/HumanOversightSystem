"""Tests for bootstrap/edit_issue.sh (#1175, consolidated by #1204).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH so
argument-parsing, milestone-prefix resolution, label/assignee edits, the
verify-and-print step, and the mint/edit/revoke flow are exercised without
touching the network or a real GitHub App. The gh stub returns real JSON that
the script's own `jq` calls filter for real, so milestone-prefix matching and
the verify-step output format are genuinely exercised, not just assumed.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
EDIT_ISSUE_SH = REPO_ROOT / "bootstrap" / "edit_issue.sh"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='fake-bot[bot]'\\n"
"""

GIT_STUB = """#!/usr/bin/env bash
echo "GIT_CALLED_WITH:$*" >> "$CAPTURE_FILE"
i=0
if [[ "$1" == "-C" ]]; then i=2; fi
sub="${@:$((i+1)):1}"
case "$sub" in
  remote) echo "https://github.com/test-owner/test-repo.git" ;;
esac
exit 0
"""

CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
exit 0
"""

# A fake `gh` that understands enough of `gh api` to exercise the real
# `jq` filters edit_issue.sh pipes output through, so the tests check real
# filtering behaviour rather than a canned string.
GH_STUB = r"""#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"

if [[ "$1" != "api" ]]; then exit 1; fi
shift

METHOD="GET"
JQ_EXPR=""
HAS_INPUT=0
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --method) METHOD="$2"; shift 2 ;;
        --jq) JQ_EXPR="$2"; shift 2 ;;
        --input) HAS_INPUT=1; shift 2 ;;
        -f|-F) shift 2 ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done
PATH_ARG="${POSITIONAL[0]:-}"

if [[ "$HAS_INPUT" -eq 1 ]]; then
    STDIN_BODY="$(cat)"
    echo "GH_STDIN:$STDIN_BODY" >> "$CAPTURE_FILE"
fi

emit() {
    if [[ -n "$JQ_EXPR" ]]; then
        printf '%s' "$1" | jq -r "$JQ_EXPR"
    else
        printf '%s\n' "$1"
    fi
}

case "$PATH_ARG" in
    */milestones\?*)
        [[ "${GH_FAIL_MILESTONES:-}" == "1" ]] && exit 1
        emit '[{"number":10,"title":"v0.6.0 — Astro & JS Support"},{"number":11,"title":"v0.7.0 — Quality"},{"number":12,"title":"v0.6.1 — patch"}]'
        ;;
    */issues/*/labels/*)
        [[ "${GH_FAIL_REMOVE_LABEL:-}" == "1" ]] && exit 1
        ;;
    */issues/*/labels)
        [[ "${GH_FAIL_ADD_LABEL:-}" == "1" ]] && exit 1
        ;;
    */issues/*/assignees)
        [[ "${GH_FAIL_ASSIGNEES:-}" == "1" ]] && exit 1
        ;;
    */issues/*)
        if [[ "$METHOD" == "PATCH" ]]; then
            [[ "${GH_FAIL_PATCH:-}" == "1" ]] && exit 1
        else
            [[ "${GH_FAIL_GET_ISSUE:-}" == "1" ]] && exit 1
            NUM="$(printf '%s' "$PATH_ARG" | grep -oE '[0-9]+' | tail -1)"
            if [[ "$NUM" == "888" ]]; then
                MILESTONE_FIELD="null"
            else
                MILESTONE_FIELD='{"title":"v0.6.0 — Astro & JS Support"}'
            fi
            emit "{\"number\":${NUM},\"title\":\"Test issue ${NUM}\",\"state\":\"open\",\"milestone\":${MILESTONE_FIELD},\"labels\":[{\"name\":\"needs-ai\"}],\"assignees\":[{\"login\":\"octocat\"}]}"
        fi
        ;;
    *)
        exit 1
        ;;
esac
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bootstrap_dir = tmp_path / "bootstrap"
        self.bootstrap_dir.mkdir()
        self.script = self.bootstrap_dir / "edit_issue.sh"
        shutil.copy(EDIT_ISSUE_SH, self.script)
        self.script.chmod(0o755)
        _write_exec(self.bootstrap_dir / "get_app_token.sh", GET_APP_TOKEN_STUB)

        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "git", GIT_STUB)
        _write_exec(self.stub_bin / "gh", GH_STUB)
        _write_exec(self.stub_bin / "curl", CURL_STUB)

        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

    def run(self, args, env_overrides=None):
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
        }
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [BASH, str(self.script), *args],
            capture_output=True, text=True, timeout=30, check=False, env=env,
        )

    def capture(self) -> str:
        return self.capture_file.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


# --------------------------------------------------------------------------- #
# Argument validation
# --------------------------------------------------------------------------- #


def test_missing_number(h):
    result = h.run(["--app", "worker", "--title", "t"])
    assert result.returncode != 0
    assert "--number" in result.stderr


def test_non_numeric_number_rejected(h):
    result = h.run(["--number", "not-a-number", "--app", "worker", "--title", "t"])
    assert result.returncode != 0
    assert "--number" in result.stderr


def test_missing_app(h):
    result = h.run(["--number", "42", "--title", "t"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_app_value(h):
    result = h.run(["--number", "42", "--app", "bogus", "--title", "t"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_state_value(h):
    result = h.run(["--number", "42", "--app", "worker", "--state", "bogus"])
    assert result.returncode != 0
    assert "--state" in result.stderr


def test_no_edit_flag_rejected(h):
    result = h.run(["--number", "42", "--app", "worker"])
    assert result.returncode != 0
    assert "at least one edit flag" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


def test_body_flag_rejected(h):
    result = h.run(["--number", "42", "--app", "worker", "--body", "inline text"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


def test_body_file_missing_rejected(h, tmp_path):
    missing = tmp_path / "does-not-exist.md"
    result = h.run(["--number", "201", "--app", "worker", "--body-file", str(missing)])
    assert result.returncode != 0
    assert "not found" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


def test_body_file_at_path_literal_rejected(h, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("@/tmp/claude/body.md")
    result = h.run(["--number", "201", "--app", "worker", "--body-file", str(body_file)])
    assert result.returncode != 0
    assert "@path literal" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


# --------------------------------------------------------------------------- #
# Milestone prefix resolution (real jq filtering against stub JSON)
# --------------------------------------------------------------------------- #


def test_milestone_unambiguous_prefix_resolves_and_patches(h):
    result = h.run(["--number", "201", "--app", "worker", "--milestone", "v0.7.0"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert 'GH_STDIN:{"milestone":11}' in cap


def test_milestone_ambiguous_prefix_aborts_before_patch(h):
    result = h.run(["--number", "201", "--app", "worker", "--milestone", "v0.6"])
    assert result.returncode != 0
    assert "ambiguous" in result.stderr
    cap = h.capture()
    assert "--method PATCH" not in cap


def test_milestone_unknown_prefix_errors(h):
    result = h.run(["--number", "201", "--app", "worker", "--milestone", "v9.9.9"])
    assert result.returncode != 0
    assert "no milestone found" in result.stderr


def test_milestone_none_clears_via_patch(h):
    result = h.run(["--number", "201", "--app", "worker", "--milestone", "none"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert 'GH_STDIN:{"milestone":null}' in cap


# --------------------------------------------------------------------------- #
# Labels and assignees
# --------------------------------------------------------------------------- #


def test_add_label_posts_json_body(h):
    result = h.run(["--number", "201", "--app", "worker", "--add-label", "needs-ai,priority:high"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert '"labels":["needs-ai","priority:high"]' in cap


def test_remove_label_url_encodes_special_characters(h):
    result = h.run(["--number", "201", "--app", "worker", "--remove-label", "priority:high"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "labels/priority%3Ahigh" in cap


def test_remove_label_failure_warns_but_does_not_abort(h):
    result = h.run(
        ["--number", "201", "--app", "worker", "--remove-label", "needs-ai"],
        env_overrides={"GH_FAIL_REMOVE_LABEL": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "could not remove label" in result.stderr


def test_add_assignee_posts_json_body(h):
    result = h.run(["--number", "201", "--app", "worker", "--assignee", "octocat"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert '"assignees":["octocat"]' in cap


# --------------------------------------------------------------------------- #
# Body edits (#1312)
# --------------------------------------------------------------------------- #


def test_body_file_sent_as_json_body_via_input(h, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text('New body with a "quote" and\na newline.\n')
    result = h.run(["--number", "201", "--app", "worker", "--body-file", str(body_file)])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert 'GH_STDIN:{"body":"New body with a \\"quote\\" and\\na newline.\\n"}' in cap


def test_body_file_combines_with_title_in_single_patch(h, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("Updated scope.\n")
    result = h.run(
        ["--number", "201", "--app", "worker", "--title", "New title", "--body-file", str(body_file)]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert '"title":"New title"' in cap
    assert '"body":"Updated scope.\\n"' in cap
    # single PATCH to the issue resource, not two round trips
    assert cap.count("GH_STDIN:") == 1


def test_body_file_only_edit_does_not_require_other_flags(h, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("Body only.\n")
    result = h.run(["--number", "201", "--app", "worker", "--body-file", str(body_file)])
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Verify-and-print output format
# --------------------------------------------------------------------------- #


def test_happy_path_verifies_and_prints_resulting_state(h):
    result = h.run(["--number", "201", "--app", "worker", "--title", "New title", "--state", "closed"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "#201 milestone=v0.6.0 — Astro & JS Support state=open labels=needs-ai "
        "assignees=octocat Test issue 201"
    )


def test_no_milestone_renders_as_none(h):
    result = h.run(["--number", "888", "--app", "worker", "--state", "closed"])
    assert result.returncode == 0, result.stderr
    assert "milestone=NONE" in result.stdout


# --------------------------------------------------------------------------- #
# Token lifecycle
# --------------------------------------------------------------------------- #


def test_token_mint_failure_aborts_before_gh(h):
    result = h.run(
        ["--number", "201", "--app", "worker", "--title", "t"],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap


def test_gh_failure_still_revokes_token(h):
    result = h.run(
        ["--number", "201", "--app", "worker", "--title", "t"],
        env_overrides={"GH_FAIL_PATCH": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap
