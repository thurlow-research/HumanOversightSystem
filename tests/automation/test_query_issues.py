"""Tests for bootstrap/query_issues.sh (#1192, consolidated by #1204).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH so
argument-parsing, milestone-prefix resolution, PR filtering, and the
mint/query/revoke flow are exercised without touching the network or a real
GitHub App. The gh stub returns real JSON that the script's own `--jq` calls
filter for real (via the actual installed `jq`), so the filtering behaviour
under test is genuine, not a canned string.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
QUERY_ISSUES_SH = REPO_ROOT / "bootstrap" / "query_issues.sh"

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

# A fake `gh` that understands enough of `gh api` to feed real JSON through
# the real `--jq` expressions query_issues.sh passes, so PR-filtering and the
# NONE-milestone rendering are genuinely exercised.
GH_STUB = r"""#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"

if [[ "$1" != "api" ]]; then exit 1; fi
shift

JQ_EXPR=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jq) JQ_EXPR="$2"; shift 2 ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done
PATH_ARG="${POSITIONAL[0]:-}"

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
        emit '[{"number":10,"title":"v0.6.0 — Astro & JS Support","state":"open"},{"number":11,"title":"v0.7.0 — Quality","state":"open"},{"number":12,"title":"v0.6.1 — patch","state":"closed"}]'
        ;;
    */issues/*/comments\?*)
        [[ "${GH_FAIL_COMMENTS:-}" == "1" ]] && exit 1
        emit '[{"user":{"login":"octocat"},"created_at":"2026-08-01T00:00:00Z","body":"first comment"},{"user":{"login":"monalisa"},"created_at":"2026-08-02T00:00:00Z","body":"second comment"}]'
        ;;
    */issues\?*)
        [[ "${GH_FAIL_LIST:-}" == "1" ]] && exit 1
        emit '[{"number":201,"title":"Issue A","state":"open","milestone":{"title":"v0.6.0 — Astro & JS Support"},"labels":[{"name":"needs-ai"}],"pull_request":null},{"number":202,"title":"A PR not an issue","state":"open","milestone":null,"labels":[],"pull_request":{"url":"x"}},{"number":203,"title":"Issue B no milestone","state":"open","milestone":null,"labels":[{"name":"needs-human"}],"pull_request":null}]'
        ;;
    */issues/*)
        [[ "${GH_FAIL_GET_ISSUE:-}" == "1" ]] && exit 1
        NUM="$(printf '%s' "$PATH_ARG" | grep -oE '[0-9]+' | tail -1)"
        if [[ "$NUM" == "888" ]]; then
            MILESTONE_FIELD="null"
        else
            MILESTONE_FIELD='{"title":"v0.6.0 — Astro & JS Support"}'
        fi
        emit "{\"number\":${NUM},\"title\":\"Test issue ${NUM}\",\"state\":\"open\",\"milestone\":${MILESTONE_FIELD},\"labels\":[{\"name\":\"needs-ai\"}],\"body\":\"line one\\nDecision: ship it\"}"
        ;;
    */assignees\?*)
        [[ "${GH_FAIL_ASSIGNABLE:-}" == "1" ]] && exit 1
        emit '[{"login":"octocat"},{"login":"monalisa"}]'
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
        self.script = self.bootstrap_dir / "query_issues.sh"
        shutil.copy(QUERY_ISSUES_SH, self.script)
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


def test_missing_app(h):
    result = h.run(["--issue", "201"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_app_value(h):
    result = h.run(["--app", "bogus", "--issue", "201"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_no_mode_rejected(h):
    result = h.run(["--app", "worker"])
    assert result.returncode != 0
    assert "exactly one of" in result.stderr


def test_two_modes_rejected(h):
    result = h.run(["--app", "worker", "--issue", "201", "--list"])
    assert result.returncode != 0
    assert "exactly one of" in result.stderr


def test_milestone_and_milestone_less_mutually_exclusive(h):
    result = h.run(["--app", "worker", "--list", "--milestone", "v0.7.0", "--milestone-less"])
    assert result.returncode != 0
    assert "mutually exclusive" in result.stderr


def test_invalid_state_filter(h):
    result = h.run(["--app", "worker", "--list", "--state", "bogus"])
    assert result.returncode != 0
    assert "--state" in result.stderr


def test_non_numeric_issue_number_rejected(h):
    result = h.run(["--app", "worker", "--issue", "abc"])
    assert result.returncode != 0
    assert "--issue" in result.stderr


# --------------------------------------------------------------------------- #
# --issue: single, multiple, no-milestone rendering
# --------------------------------------------------------------------------- #


def test_single_issue_query(h):
    result = h.run(["--app", "worker", "--issue", "201"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "#201 milestone=v0.6.0 — Astro & JS Support state=open labels=needs-ai Test issue 201"
    )


def test_multiple_issue_query(h):
    result = h.run(["--app", "worker", "--issue", "201,888"])
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("#201")
    assert lines[1].startswith("#888")


def test_issue_with_no_milestone_renders_none(h):
    result = h.run(["--app", "worker", "--issue", "888"])
    assert result.returncode == 0, result.stderr
    assert "milestone=NONE" in result.stdout


# --------------------------------------------------------------------------- #
# --full: raw issue body
# --------------------------------------------------------------------------- #


def test_full_appends_raw_body_after_summary_line(h):
    result = h.run(["--app", "worker", "--issue", "201", "--full"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(
        "#201 milestone=v0.6.0 — Astro & JS Support state=open labels=needs-ai Test issue 201"
    )
    assert "Decision: ship it" in result.stdout


def test_default_issue_query_omits_body(h):
    result = h.run(["--app", "worker", "--issue", "201"])
    assert result.returncode == 0, result.stderr
    assert "Decision: ship it" not in result.stdout


def test_full_without_issue_rejected(h):
    result = h.run(["--app", "worker", "--list", "--full"])
    assert result.returncode != 0
    assert "--full" in result.stderr


# --------------------------------------------------------------------------- #
# --list: PR filtering, milestone-less, milestone-prefix resolution
# --------------------------------------------------------------------------- #


def test_list_filters_out_pull_requests(h):
    result = h.run(["--app", "worker", "--list"])
    assert result.returncode == 0, result.stderr
    assert "#202" not in result.stdout
    assert "#201" in result.stdout
    assert "#203" in result.stdout


def test_list_milestone_less_sets_none_param(h):
    result = h.run(["--app", "worker", "--list", "--milestone-less"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "milestone=none" in cap


def test_list_milestone_prefix_resolves_to_id(h):
    result = h.run(["--app", "worker", "--list", "--milestone", "v0.7.0"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "milestone=11" in cap


def test_list_milestone_ambiguous_prefix_errors(h):
    result = h.run(["--app", "worker", "--list", "--milestone", "v0.6"])
    assert result.returncode != 0
    assert "ambiguous" in result.stderr


# --------------------------------------------------------------------------- #
# --comments and --assignable-users
# --------------------------------------------------------------------------- #


def test_comments_lists_each_comment(h):
    result = h.run(["--app", "worker", "--comments", "201"])
    assert result.returncode == 0, result.stderr
    assert "octocat" in result.stdout
    assert "monalisa" in result.stdout
    assert "first comment" in result.stdout
    assert "second comment" in result.stdout


def test_assignable_users_lists_logins(h):
    result = h.run(["--app", "worker", "--assignable-users"])
    assert result.returncode == 0, result.stderr
    assert "octocat" in result.stdout.splitlines()
    assert "monalisa" in result.stdout.splitlines()


# --------------------------------------------------------------------------- #
# --list-milestones
# --------------------------------------------------------------------------- #


def test_list_milestones_prints_number_title_state(h):
    result = h.run(["--app", "worker", "--list-milestones"])
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert "#10 v0.6.0 — Astro & JS Support [open]" in lines
    assert "#11 v0.7.0 — Quality [open]" in lines
    assert "#12 v0.6.1 — patch [closed]" in lines


def test_list_milestones_failure_propagates(h):
    result = h.run(
        ["--app", "worker", "--list-milestones"],
        env_overrides={"GH_FAIL_MILESTONES": "1"},
    )
    assert result.returncode != 0
    assert "failed to list milestones" in result.stderr


def test_list_milestones_mutually_exclusive_with_list(h):
    result = h.run(["--app", "worker", "--list", "--list-milestones"])
    assert result.returncode != 0
    assert "exactly one of" in result.stderr


# --------------------------------------------------------------------------- #
# Token lifecycle
# --------------------------------------------------------------------------- #


def test_token_mint_failure_aborts_before_gh(h):
    result = h.run(
        ["--app", "worker", "--issue", "201"],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap


def test_gh_failure_still_revokes_token(h):
    result = h.run(
        ["--app", "worker", "--list"],
        env_overrides={"GH_FAIL_LIST": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap
