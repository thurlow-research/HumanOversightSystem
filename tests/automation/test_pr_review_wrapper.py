"""Tests for bootstrap/pr_review.sh + scripts/automation/pr_review_cli.py (#1657).

W1-W14 per docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md §8.1
and the binding conditions in docs/v0.7.0/ADR-1657-overseer-review-objects.md
§3 (ARCH-3, ARCH-9, ARCH-10).

Runs the real `bootstrap/pr_review.sh` -> real `scripts/automation/pr_review_cli.py`
against a fixture repo tree with stubbed git/gh/curl/get_app_token.sh on PATH,
mirroring tests/automation/test_post_review_thread.py's harness idiom. Unlike
post_review_thread.sh, pr_review.sh shells out to a real python3 subprocess
running the real pr_review_cli.py, so the fixture tree also carries copies of
every module that CLI imports or loads by file path (scripts/automation/lib/*,
scripts/oversight/codeowners.py, scripts/framework/require_tier_ceiling.py)
plus controllable copies of scripts/framework/machine-accounts.env,
scripts/framework/protected_surfaces.txt, and .github/CODEOWNERS. The `gh`
stub serves `pulls/<n>`, `pulls/<n>/reviews`, `pulls/<n>/files` (GET) and
`pulls/<n>/reviews`, `pulls/<n>/requested_reviewers` (POST) from fixtures
keyed by env vars, and records every call (including POST stdin bodies) to
CAPTURE_FILE. No network access.
"""

import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

import scripts.automation.pr_review_cli as cli

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
PR_REVIEW_SH = REPO_ROOT / "bootstrap" / "pr_review.sh"

DEFAULT_HEAD_SHA = "sha-headabc123"
DEFAULT_AUTHOR = "hos-worker-hos[bot]"
DEFAULT_BOT_LOGIN = "fake-overseer-bot[bot]"
DEFAULT_HUMAN_REVIEWER = "hos-default-human"

GET_APP_TOKEN_STUB = f"""#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${{FAIL_TOKEN_MINT:-}}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='{DEFAULT_BOT_LOGIN}'\\n"
"""

GIT_STUB = """#!/usr/bin/env bash
echo "GIT_CALLED_WITH:$*" >> "$CAPTURE_FILE"
args=("$@")
n=${#args[@]}
is_get_url_origin=0
if [[ $n -ge 3 ]]; then
    a="${args[$((n-3))]}"; b="${args[$((n-2))]}"; c="${args[$((n-1))]}"
    if [[ "$a" == "remote" && "$b" == "get-url" && "$c" == "origin" ]]; then
        is_get_url_origin=1
    fi
fi
if [[ "$is_get_url_origin" == "1" ]]; then
    echo "${GIT_ORIGIN_URL:-https://github.com/test-owner/test-repo.git}"
fi
exit 0
"""

# `gh api --include [--input -] <path> [--method <M>]` — emulate the
# HTTP/2 <status>\\r\\n\\r\\n<body> shape github.py::_run_gh parses, driven by
# env-var fixtures. Exit 0 for status<400, exit 1 otherwise (mirrors gh's own
# non-zero exit on API errors, which _run_gh relies on).
GH_STUB = r"""#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"
# Only used by the SIGTERM-mid-flight test below — a deliberate stall so the
# test has a reliable window to deliver the signal while pr_review_cli.py is
# genuinely in flight. 0 (no sleep) for every other test.
sleep "${GH_STUB_SLEEP_SECONDS:-0}"

HAS_INPUT=0
for a in "$@"; do
    if [[ "$a" == "--input" ]]; then HAS_INPUT=1; fi
done

BODY=""
if [[ "$HAS_INPUT" == "1" ]]; then
    BODY="$(cat)"
    echo "GH_STDIN_BODY:$BODY" >> "$CAPTURE_FILE"
fi

PATH_ARG=""
for a in "$@"; do
    if [[ "$a" == /repos/* ]]; then PATH_ARG="$a"; break; fi
done

METHOD="GET"
prev=""
for a in "$@"; do
    if [[ "$prev" == "--method" ]]; then METHOD="$a"; fi
    prev="$a"
done

emit() {
    printf 'HTTP/2 %s\r\n\r\n%s' "$1" "$2"
}

case "$PATH_ARG" in
  */pulls/*/requested_reviewers*)
    if [[ "${FAIL_REQUEST_REVIEWER:-}" == "1" ]]; then
        emit 422 '{"message":"Reviews may only be requested from collaborators."}'
        exit 1
    fi
    emit 200 '{"id":1}'
    exit 0
    ;;
  */pulls/*/reviews*)
    if [[ "$METHOD" == "POST" ]]; then
        if [[ "${FAIL_SUBMIT_REVIEW:-}" == "1" ]]; then
            emit 500 '{"message":"server error"}'
            exit 1
        fi
        if [[ "${STALE_COMMIT:-}" == "1" ]]; then
            emit 422 '{"message":"commit_id is not part of the pull request"}'
            exit 1
        fi
        resp_json="$(python3 - "$BODY" "${MISMATCHED_STATE:-0}" "${AT_PATH_READBACK:-0}" <<'PYEOF'
import json, sys
body_json = json.loads(sys.argv[1])
event = body_json["event"]
rbody = body_json["body"]
cid = body_json["commit_id"]
state = "APPROVED" if event == "APPROVE" else "COMMENTED"
if sys.argv[2] == "1":
    state = "PENDING"
out_body = rbody
if sys.argv[3] == "1":
    out_body = "@/tmp/some-file"
resp = {
    "id": 9001,
    "state": state,
    "body": out_body,
    "commit_id": cid,
    "html_url": "https://github.com/test-owner/test-repo/pull/1#pullrequestreview-9001",
}
print(json.dumps(resp))
PYEOF
)"
        RC=$?
        if [[ "$RC" != "0" ]]; then exit 1; fi
        emit 200 "$resp_json"
        exit 0
    else
        emit 200 "${PR_REVIEWS_JSON:-[]}"
        exit 0
    fi
    ;;
  */pulls/*/files*)
    json_out="$(python3 - <<'PYEOF'
import json, os
files = [f for f in os.environ.get("PR_FILES", "README.md").split(" ") if f]
print(json.dumps([{"filename": f} for f in files]))
PYEOF
)"
    emit 200 "$json_out"
    exit 0
    ;;
  */pulls/*)
    json_out="$(python3 - <<'PYEOF'
import json, os
reviewers = [r for r in os.environ.get("PR_REQUESTED_REVIEWERS", "").split(" ") if r]
print(json.dumps({
    "head": {"sha": os.environ.get("PR_HEAD_SHA", "sha-headabc123")},
    "user": {"login": os.environ.get("PR_AUTHOR", "hos-worker-hos[bot]")},
    "requested_reviewers": [{"login": r} for r in reviewers],
    "review_comments": int(os.environ.get("PR_REVIEW_COMMENTS", "0")),
}))
PYEOF
)"
    emit 200 "$json_out"
    exit 0
    ;;
  *)
    emit 404 '{"message":"not found"}'
    exit 1
    ;;
esac
"""

# Emulates revoke_app_token.sh's `curl -s -o /dev/null -w '%{http_code}' ...`
# usage: the real curl prints the response code to stdout (body discarded via
# -o /dev/null). Answer 204 (GitHub's real DELETE .../installation/token
# response) so the wrapper script's success path exercises cleanly.
CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
printf '204'
exit 0
"""

VALID_OVERSEER_BODY = (
    "**Executive summary:** Recommend approving this PR. "
    "Expected action: **NO ACTION**. Not verified this run: nothing.\n"
)

DEFAULT_ENV = f"""BOT_WORKER_USERNAME="hos-worker-hos[bot]"
BOT_OVERSEER_USERNAME="{DEFAULT_BOT_LOGIN}"
BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"
COPILOT_BOT_LOGIN="copilot[bot]"
BOT_ACCOUNTS="hos-worker-hos[bot] {DEFAULT_BOT_LOGIN} scottthurlow-claude[bot] copilot[bot]"
OVERSEER_CEILING="HIGH"
TIER_CEILING_CHECK_NAME="require-tier-ceiling"
HUMAN_REVIEWER="{DEFAULT_HUMAN_REVIEWER}"
"""

DEFAULT_PROTECTED_SURFACES = ".claude/agents/**\n"

DEFAULT_CODEOWNERS = "/.claude/agents/    @hos-default-human\n"


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.repo_root = tmp_path / "repo"
        self.repo_root.mkdir()

        bdir = self.repo_root / "bootstrap"
        bdir.mkdir()
        shutil.copy(PR_REVIEW_SH, bdir / "pr_review.sh")
        (bdir / "pr_review.sh").chmod(0o755)
        shutil.copy(REPO_ROOT / "bootstrap" / "revoke_app_token.sh", bdir / "revoke_app_token.sh")
        (bdir / "revoke_app_token.sh").chmod(0o755)
        _write_exec(bdir / "get_app_token.sh", GET_APP_TOKEN_STUB)
        lib_dir = bdir / "lib"
        lib_dir.mkdir()
        shutil.copy(
            REPO_ROOT / "bootstrap" / "lib" / "comment_format_check.sh",
            lib_dir / "comment_format_check.sh",
        )

        scripts_dir = self.repo_root / "scripts"
        scripts_dir.mkdir()
        shutil.copy(REPO_ROOT / "scripts" / "__init__.py", scripts_dir / "__init__.py")

        automation_dir = scripts_dir / "automation"
        automation_dir.mkdir()
        shutil.copy(
            REPO_ROOT / "scripts" / "automation" / "__init__.py",
            automation_dir / "__init__.py",
        )
        shutil.copy(
            REPO_ROOT / "scripts" / "automation" / "pr_review_cli.py",
            automation_dir / "pr_review_cli.py",
        )

        lib2_dir = automation_dir / "lib"
        lib2_dir.mkdir()
        for fname in ("__init__.py", "github.py", "merge_authority.py", "merge_config.py"):
            shutil.copy(REPO_ROOT / "scripts" / "automation" / "lib" / fname, lib2_dir / fname)

        oversight_dir = scripts_dir / "oversight"
        oversight_dir.mkdir()
        shutil.copy(
            REPO_ROOT / "scripts" / "oversight" / "codeowners.py",
            oversight_dir / "codeowners.py",
        )
        oversight_lib_dir = oversight_dir / "lib"
        oversight_lib_dir.mkdir()
        shutil.copy(
            REPO_ROOT / "scripts" / "oversight" / "lib" / "audit_log.py",
            oversight_lib_dir / "audit_log.py",
        )

        framework_dir = scripts_dir / "framework"
        framework_dir.mkdir()
        shutil.copy(
            REPO_ROOT / "scripts" / "framework" / "require_tier_ceiling.py",
            framework_dir / "require_tier_ceiling.py",
        )
        (framework_dir / "machine-accounts.env").write_text(DEFAULT_ENV)
        (framework_dir / "protected_surfaces.txt").write_text(DEFAULT_PROTECTED_SURFACES)

        self.codeowners_path = self.repo_root / ".github" / "CODEOWNERS"
        self.codeowners_path.parent.mkdir(parents=True, exist_ok=True)
        self.codeowners_path.write_text(DEFAULT_CODEOWNERS)

        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "git", GIT_STUB)
        _write_exec(self.stub_bin / "gh", GH_STUB)
        _write_exec(self.stub_bin / "curl", CURL_STUB)

        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

        self.body_file = tmp_path / "body.md"
        self.body_file.write_text(VALID_OVERSEER_BODY)

    def set_codeowners(self, text: str) -> None:
        self.codeowners_path.write_text(text)

    def set_overseer_handle(self, handle: str) -> None:
        """Rewrite BOT_OVERSEER_USERNAME in machine-accounts.env, keeping
        every other key at its DEFAULT_ENV value. Used to construct a G0b
        identity mismatch: GET_APP_TOKEN_STUB always exports a fixed
        HOS_BOT_LOGIN (mirroring a real mint's own env override, which
        env_overrides cannot pre-empt), so the mismatch must come from the
        configured overseer handle diverging from that fixed mint identity,
        not the other way around."""
        env_path = self.repo_root / "scripts" / "framework" / "machine-accounts.env"
        env_path.write_text(DEFAULT_ENV.replace(f'"{DEFAULT_BOT_LOGIN}"', f'"{handle}"', 1))

    def run(self, args, env_overrides=None):
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
            "PR_HEAD_SHA": DEFAULT_HEAD_SHA,
            "PR_AUTHOR": DEFAULT_AUTHOR,
            "PR_FILES": "README.md",
            "PR_REVIEWS_JSON": "[]",
            "PR_REQUESTED_REVIEWERS": "",
            "PR_REVIEW_COMMENTS": "0",
        }
        if env_overrides:
            env.update(env_overrides)
        # --repo goes after the subcommand token (args[0]) — the subcommand
        # is positional and must come first.
        full_args = [args[0], "--repo", "test-owner/test-repo", *args[1:]]
        return subprocess.run(
            [BASH, str(self.repo_root / "bootstrap" / "pr_review.sh"), *full_args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )

    def capture(self) -> str:
        return self.capture_file.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def _parse_stdout_json(result) -> dict:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one stdout line, got: {result.stdout!r}"
    return json.loads(lines[0])


# --------------------------------------------------------------------------- #
# W1/W2 — verdict posts a review object, never a conversation comment
# --------------------------------------------------------------------------- #


def test_w1_comment_event_posts_review_not_issue_comment(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "123",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "repos/test-owner/test-repo/pulls/123/reviews" in cap
    assert "gh issue comment" not in cap
    assert "/issues/123/comments" not in cap


def test_w2_approve_event_posts_approve_with_commit_id(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "123",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert len(stdin_lines) == 1, cap
    payload = json.loads(stdin_lines[0][len("GH_STDIN_BODY:") :])
    assert payload["event"] == "APPROVE"
    assert payload["commit_id"] == DEFAULT_HEAD_SHA


# --------------------------------------------------------------------------- #
# W3-W5 — argument validation
# --------------------------------------------------------------------------- #


def test_w3_rejects_inline_body(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body",
            "inline text",
        ]
    )
    # TD-1657 §4.6 step 2: this is a usage error (exit 2), not an operational
    # failure — the same class argparse's own "unrecognized arguments" would
    # produce for an unknown --body flag (also verify-then-fix, #1657 PR-1
    # review round 4: this previously used err() and exited 1).
    assert result.returncode == 2, result.stderr
    assert "--body-file" in result.stderr


def test_w3_rejects_inline_body_equals_form(h):
    """`--body=<text>` must be caught too — the split-token match alone
    (`"$_arg" == "--body"`) missed the `=` form (also verify-then-fix,
    #1657 PR-1 review round 4)."""
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body=inline text",
        ]
    )
    assert result.returncode == 2, result.stderr
    assert "--body-file" in result.stderr


def test_w4_missing_tier_exits_2(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 2, result.stderr


def test_w4_missing_body_file_exits_2(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
        ]
    )
    assert result.returncode == 2, result.stderr


def test_w4_missing_body_file_path_in_enforce_mode_still_exits_2_with_envelope(h):
    """Also verify-then-fix (#1657 PR-1 review round 4): in
    HOS_COMMENT_FORMAT_MODE=enforce, a --body-file path that does not exist
    must still reach pr_review_cli.py's own G5 (exit 2, one JSON envelope)
    rather than being misread by the bash-level format check as a "missing
    **Executive summary:** heading" content violation and refused via
    err() — exit 1, no JSON, wrong reason."""
    missing_path = h.tmp / "does-not-exist.md"
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(missing_path),
        ],
        env_overrides={"HOS_COMMENT_FORMAT_MODE": "enforce"},
    )
    assert result.returncode == 2, result.stderr
    record = _parse_stdout_json(result)
    assert "body-file" in (record["error"] or "").lower()


def test_w5_request_changes_rejected(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "request_changes",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 2, result.stderr
    assert "post_review_thread.sh" in result.stderr


# --------------------------------------------------------------------------- #
# W6 — mint/revoke on both the success path and a failure path
# --------------------------------------------------------------------------- #


def test_w6_token_minted_and_revoked_on_success(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in cap
    # bootstrap/revoke_app_token.sh's own curl invocation (MUST_FIX B, #1657
    # PR-1 review round 2) — --connect-timeout/--max-time (never absent, the
    # thing this fix adds) and -X DELETE against installation/token.
    assert (
        "CURL_CALLED_WITH:-s -o /dev/null -w %{http_code} --connect-timeout 10 --max-time 30 -X DELETE"
        in cap
    )
    assert "installation/token" in cap


def test_w6_token_revoked_on_failure_path(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"FAIL_SUBMIT_REVIEW": "1"},
    )
    assert result.returncode == 1, result.stderr
    cap = h.capture()
    assert (
        "CURL_CALLED_WITH:-s -o /dev/null -w %{http_code} --connect-timeout 10 --max-time 30 -X DELETE"
        in cap
    )


def test_w6_token_revoked_exactly_once_on_sigterm(h):
    """SHOULD_FIX 6 (#1657 PR-1 review round 4): a cron-imposed SIGTERM
    kills the script without ever running an EXIT-only trap, leaving the
    minted token live until natural expiry. Send SIGTERM mid-flight (after
    the mint succeeded, while pr_review_cli.py's GitHub fetch is
    deliberately stalled) and confirm the token is still revoked — exactly
    once, proving the idempotency guard as well as the trap itself."""
    env = {
        "PATH": f"{h.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "CAPTURE_FILE": str(h.capture_file),
        "HOME": str(h.tmp / "home"),
        "PR_HEAD_SHA": DEFAULT_HEAD_SHA,
        "PR_AUTHOR": DEFAULT_AUTHOR,
        "PR_FILES": "README.md",
        "PR_REVIEWS_JSON": "[]",
        "PR_REQUESTED_REVIEWERS": "",
        "PR_REVIEW_COMMENTS": "0",
        "GH_STUB_SLEEP_SECONDS": "5",
    }
    full_args = [
        "submit-verdict",
        "--repo",
        "test-owner/test-repo",
        "--app",
        "overseer",
        "--pr",
        "42",
        "--event",
        "comment",
        "--tier",
        "LOW",
        "--body-file",
        str(h.body_file),
    ]
    proc = subprocess.Popen(
        [BASH, str(h.repo_root / "bootstrap" / "pr_review.sh"), *full_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        # Poll (bounded, short interval) for the mint to have completed —
        # the process is genuinely in flight, stalled inside the (now
        # slow) GH_STUB call, once this line is present.
        deadline = 10.0
        waited = 0.0
        while waited < deadline:
            if "GET_APP_TOKEN_CALLED_WITH" in h.capture():
                break
            time.sleep(0.1)
            waited += 0.1
        else:
            proc.kill()
            pytest.fail("mint never happened within the poll deadline")

        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert proc.returncode == -signal.SIGTERM, (proc.returncode, proc.stderr.read())
    cap = h.capture()
    revoke_calls = [
        line
        for line in cap.splitlines()
        if line.startswith("CURL_CALLED_WITH") and "installation/token" in line
    ]
    assert len(revoke_calls) == 1, cap


# --------------------------------------------------------------------------- #
# W7 — the envelope is exactly one JSON object on every exit code
# --------------------------------------------------------------------------- #

_ENVELOPE_KEYS = {"schema_version", "subcommand", "pr", "app_role", "not_verified", "error"}


def test_w7_envelope_exit_0(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()


def test_w7_envelope_exit_1(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"FAIL_SUBMIT_REVIEW": "1"},
    )
    assert result.returncode == 1, result.stderr
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()


def test_w7_envelope_exit_2(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 2, result.stderr
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()


def test_w7_envelope_exit_3(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "CRITICAL",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()


# --------------------------------------------------------------------------- #
# W8-W10 — the trigger set, "must not widen" pinned at the script level
# --------------------------------------------------------------------------- #


def test_w8_low_tier_non_protected_refuses_no_post(h):
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "LOW"],
        env_overrides={"PR_FILES": "README.md"},
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "no_qualifying_trigger"
    cap = h.capture()
    assert "requested_reviewers" not in cap


def test_w9_protected_surface_requests_codeowners_login(h):
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "LOW"],
        env_overrides={"PR_FILES": ".claude/agents/overseer.md"},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["requested"] is True
    assert record["resolution_source"] == "codeowners"
    cap = h.capture()
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert len(stdin_lines) == 1, cap
    payload = json.loads(stdin_lines[0][len("GH_STDIN_BODY:") :])
    assert payload == {"reviewers": ["hos-default-human"]}


def test_w10_critical_tier_requests_regardless_of_protected_surface(h):
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "requested_reviewers" in cap
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert len(stdin_lines) == 1, cap


def test_explicit_reviewer_leading_at_is_stripped(h):
    """SHOULD_FIX 5 (#1657 PR-1 review round 4): an explicit `--reviewer
    @someone` must have its leading '@' stripped before the bot-account and
    PR-author self-request checks (which compare against un-prefixed
    logins) and before the POST — GitHub itself 422s a "@login" reviewer
    request."""
    result = h.run(
        [
            "request-reviewer",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--tier",
            "CRITICAL",
            "--reviewer",
            "@carol",
        ],
        env_overrides={"PR_FILES": "README.md"},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["requested"] is True
    assert record["resolved_reviewer"] == "carol"
    cap = h.capture()
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert len(stdin_lines) == 1, cap
    payload = json.loads(stdin_lines[0][len("GH_STDIN_BODY:") :])
    assert payload == {"reviewers": ["carol"]}


# --------------------------------------------------------------------------- #
# W11-W12 — idempotency, and the livelock guard (ARCH-9: APPROVED and COMMENTED)
# --------------------------------------------------------------------------- #


def test_w11_already_requested_skips(h):
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md", "PR_REQUESTED_REVIEWERS": "hos-default-human"},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["skipped"] is True
    assert record["skip_reason"] == "already_requested"
    cap = h.capture()
    assert "requested_reviewers" not in cap


def test_w12_livelock_guard_approved_review_on_head_skips(h):
    """The livelock guard: decide_merge_authority returns HUMAN_REQUIRED on an
    outstanding request from human_reviewer before it ever checks for a human
    approval, so a re-request after approval flips an approved PR back to
    HUMAN_REQUIRED every cycle. Covers ARCH-9's APPROVED case."""
    reviews = json.dumps(
        [
            {
                "user": {"login": "hos-default-human"},
                "state": "APPROVED",
                "commit_id": DEFAULT_HEAD_SHA,
            }
        ]
    )
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md", "PR_REVIEWS_JSON": reviews},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["skipped"] is True
    assert record["skip_reason"] == "already_reviewed_head"
    cap = h.capture()
    assert "requested_reviewers" not in cap


def test_w12_livelock_guard_commented_review_on_head_skips(h):
    """ARCH-9's COMMENTED case: I2's predicate is 'any review state', not
    just APPROVED — a COMMENTED review on the current head also suppresses
    the request (it costs a notification, never a gate, and the human
    demonstrably already has that head in view)."""
    reviews = json.dumps(
        [
            {
                "user": {"login": "hos-default-human"},
                "state": "COMMENTED",
                "commit_id": DEFAULT_HEAD_SHA,
            }
        ]
    )
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md", "PR_REVIEWS_JSON": reviews},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["skipped"] is True
    assert record["skip_reason"] == "already_reviewed_head"
    cap = h.capture()
    assert "requested_reviewers" not in cap


# --------------------------------------------------------------------------- #
# W13 — G1: never approve above OVERSEER_CEILING
# --------------------------------------------------------------------------- #


def test_w13_above_ceiling_approve_refused(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "CRITICAL",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "above_ceiling_approve"
    # SHOULD_FIX 3 (#1657 PR-1 review round 4): the refusal payload must
    # still pin the evaluated commit, not leave commit_id null.
    assert record["commit_id"] == DEFAULT_HEAD_SHA
    cap = h.capture()
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert not stdin_lines, cap


def test_w13b_self_authored_approve_refused_carries_commit_id(h):
    """SHOULD_FIX 3 (#1657 PR-1 review round 4) — the G2 self_authored
    refusal must also pin commit_id, not leave it null."""
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"PR_AUTHOR": DEFAULT_BOT_LOGIN},
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "self_authored"
    assert record["commit_id"] == DEFAULT_HEAD_SHA


# --------------------------------------------------------------------------- #
# MUST_FIX 1 (#1657 PR-1 review round 4) — --app never authorizes approve on
# its own; only the overseer app role may clear G1/G2 and post an APPROVE.
# --------------------------------------------------------------------------- #


def test_worker_app_cannot_approve_even_when_otherwise_eligible(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "worker",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "approve_requires_overseer_identity"
    assert record["commit_id"] == DEFAULT_HEAD_SHA
    cap = h.capture()
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert not stdin_lines, cap


def test_human_app_cannot_approve(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "human",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "approve_requires_overseer_identity"


def test_worker_app_comment_event_unaffected_by_approve_identity_gate(h):
    """Non-approve events must not be touched by the new G0 gate — a
    worker-app `comment` still posts normally."""
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "worker",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "repos/test-owner/test-repo/pulls/42/reviews" in cap


def test_overseer_app_can_still_approve_when_otherwise_eligible(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["posted"] is True


# --------------------------------------------------------------------------- #
# MUST_FIX 2 (#1657 PR-1 review round 4) — an explicit --repo that does not
# match the local checkout's own origin remote is refused before any GitHub
# call is made.
# --------------------------------------------------------------------------- #


def test_explicit_repo_mismatching_origin_is_refused_before_any_gh_call(h):
    # h.run() itself always injects `--repo test-owner/test-repo` ahead of
    # these args; argparse's default store action keeps the *last*
    # occurrence of a repeated flag, so appending a second, mismatching
    # --repo here is what the CLI actually sees.
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
            "--repo",
            "some-other-org/some-other-repo",
        ]
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "repo_scope_mismatch"
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap


def test_explicit_repo_matching_origin_still_works(h):
    """An explicit --repo that matches origin's own slug must still work —
    this guard is scoped to a mismatch only."""
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# W14 — fail-closed on an unevaluable trigger (0 changed files)
# --------------------------------------------------------------------------- #


def test_w14_empty_changed_files_fails_closed_exit_1(h):
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "LOW"],
        env_overrides={"PR_FILES": ""},
    )
    assert result.returncode == 1, result.stderr
    assert "changed files" in (result.stdout + result.stderr)
    cap = h.capture()
    assert "requested_reviewers" not in cap


# --------------------------------------------------------------------------- #
# W15 — an unreadable/undecodable --body-file must still exit 2 with exactly
# one JSON envelope, never an uncaught traceback (MUST_FIX 1, code-reviewer
# finding on #1657 PR-1: UnicodeDecodeError is a ValueError subclass, not an
# OSError, so it previously propagated uncaught through main()).
# --------------------------------------------------------------------------- #


def test_w15_invalid_utf8_body_file_exits_2_with_clean_envelope(h):
    bad_body = h.tmp / "bad_body.md"
    bad_body.write_bytes(b"\xff\xfe not valid utf-8")
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(bad_body),
        ]
    )
    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()
    assert "unreadable" in (record.get("error") or "")


# --------------------------------------------------------------------------- #
# W16 — a failed token mint (TD §4.7); and revoke_token's GH_TOKEN branch
# must not error when no token was ever minted (SHOULD_FIX 2, code-reviewer
# finding on #1657 PR-1). Two cases (SHOULD_FIX E, #1657 PR-1 review round
# 2): W16a is the realistic production scenario — GH_TOKEN and HOS_BOT_LOGIN
# both come from the same get_app_token.sh call, so a real mint failure
# leaves both unset and this exits 1 per TD §4.7, not 0. W16b is a distinct,
# clearly-labelled second case with HOS_BOT_LOGIN forced into the
# environment independently of the mint (e.g. carried over from elsewhere in
# the caller's process) — worth covering because it is the one case where
# TD §4.7's "proceed without a token" text is reachable, but it is not the
# realistic single-mint-failure scenario and must not be mistaken for one.
# --------------------------------------------------------------------------- #


def test_w16a_token_mint_failure_realistic_no_override_exits_1(h):
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode == 1, result.stderr
    assert "failed to mint" in result.stderr
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()
    error = (record.get("error") or "").lower()
    # SHOULD_FIX F: the mint failure must be named explicitly, not reported
    # as if HOS_BOT_LOGIN were simply misconfigured.
    assert "mint failed" in error
    assert "next cycle" in error
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in cap
    assert "CURL_CALLED_WITH:-s -o /dev/null" not in cap


def test_w16b_token_mint_failure_with_bot_login_forced_warns_and_proceeds(h):
    # HOS_BOT_LOGIN is normally exported by get_app_token.sh's own stdout
    # (GET_APP_TOKEN_STUB), which a failed mint never reaches — supply it
    # directly so this test isolates the mint-failure/proceed behavior from
    # the "HOS_BOT_LOGIN unset" failure mode W16a covers. Not the realistic
    # scenario — see the section note above.
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"FAIL_TOKEN_MINT": "1", "HOS_BOT_LOGIN": DEFAULT_BOT_LOGIN},
    )
    # (b) the exit code is pr_review_cli.py's own (0 here — the fixture gh
    # stub does not gate on auth), never a bash-forced code from the mint
    # step itself.
    assert result.returncode == 0, result.stderr
    assert "failed to mint" in result.stderr
    # (a) exactly one JSON envelope on stdout
    record = _parse_stdout_json(result)
    assert _ENVELOPE_KEYS <= record.keys()
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in cap
    # (c) revoke_token must not error, and must not attempt the DELETE call,
    # when GH_TOKEN was never set because the mint failed.
    assert "CURL_CALLED_WITH:-s -o /dev/null" not in cap


# --------------------------------------------------------------------------- #
# W17 — MUST_FIX A (privacy, #1657 PR-1 review round 2): a raw e-mail-shaped
# CODEOWNERS owner co-listed with a usable human owner must never appear in
# the printed envelope, on the request, both idempotent-skip, and failure
# outcome paths. (The no_qualifying_trigger refusal payload is already
# minimized and does not carry codeowners_owners at all — not exercised
# here.)
# --------------------------------------------------------------------------- #

MIXED_EMAIL_CODEOWNERS = "README.md @carol dev@example.com\n"


def test_w17_request_path_never_leaks_email_owner(h):
    h.set_codeowners(MIXED_EMAIL_CODEOWNERS)
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md"},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["requested"] is True
    assert record["resolved_reviewer"] == "carol"
    assert "dev@example.com" not in result.stdout


def test_w17_already_requested_skip_never_leaks_email_owner(h):
    h.set_codeowners(MIXED_EMAIL_CODEOWNERS)
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md", "PR_REQUESTED_REVIEWERS": "carol"},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["skipped"] is True
    assert record["skip_reason"] == "already_requested"
    assert "dev@example.com" not in result.stdout


def test_w17_already_reviewed_head_skip_never_leaks_email_owner(h):
    h.set_codeowners(MIXED_EMAIL_CODEOWNERS)
    reviews = json.dumps(
        [{"user": {"login": "carol"}, "state": "APPROVED", "commit_id": DEFAULT_HEAD_SHA}]
    )
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md", "PR_REVIEWS_JSON": reviews},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["skipped"] is True
    assert record["skip_reason"] == "already_reviewed_head"
    assert "dev@example.com" not in result.stdout


def test_w17_failed_request_never_leaks_email_owner(h):
    h.set_codeowners(MIXED_EMAIL_CODEOWNERS)
    result = h.run(
        ["request-reviewer", "--app", "overseer", "--pr", "42", "--tier", "CRITICAL"],
        env_overrides={"PR_FILES": "README.md", "FAIL_REQUEST_REVIEWER": "1"},
    )
    assert result.returncode == 1, result.stderr
    record = _parse_stdout_json(result)
    assert record.get("resolved_reviewer") == "carol"
    assert "dev@example.com" not in result.stdout


# --------------------------------------------------------------------------- #
# W18 — MUST_FIX D (reliability, #1657 PR-1 review round 2): an ambiguous
# submit_pull_review failure (connection lost after the request was sent,
# response unparseable) cannot produce two review objects. The gh stub's
# GH_STUB always creates exactly one review server-side on a POST it
# accepts; AMBIGUOUS_THEN_FOUND simulates "the POST landed but the response
# was lost" by failing the POST once (ambiguous, no parseable status) while
# a matching review is already visible on the very next reviews GET — the
# real duplicate-risk scenario this fix exists to close.
# --------------------------------------------------------------------------- #


AMBIGUOUS_SUBMIT_GH_STUB = r"""#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"

HAS_INPUT=0
for a in "$@"; do
    if [[ "$a" == "--input" ]]; then HAS_INPUT=1; fi
done
BODY=""
if [[ "$HAS_INPUT" == "1" ]]; then
    BODY="$(cat)"
    echo "GH_STDIN_BODY:$BODY" >> "$CAPTURE_FILE"
fi

PATH_ARG=""
for a in "$@"; do
    if [[ "$a" == /repos/* ]]; then PATH_ARG="$a"; break; fi
done

METHOD="GET"
prev=""
for a in "$@"; do
    if [[ "$prev" == "--method" ]]; then METHOD="$a"; fi
    prev="$a"
done

emit() {
    printf 'HTTP/2 %s\r\n\r\n%s' "$1" "$2"
}

case "$PATH_ARG" in
  */pulls/*/reviews*)
    if [[ "$METHOD" == "POST" ]]; then
        # Simulate "request reached GitHub, response lost" — empty stdout,
        # no parseable HTTP status line, non-zero exit. This is exactly the
        # ambiguous case submit_pull_review is called with retries=0 for
        # (MUST_FIX D): before that fix, _run_gh's generic retry loop would
        # have retried this blindly and could have double-posted.
        exit 1
    else
        # The first reviews GET is the preamble read (before this write's
        # POST attempt); every subsequent GET is a post-failure recheck
        # (after it). PR_REVIEWS_JSON_RECHECK lets a test model the write
        # actually having landed server-side despite the ambiguous POST
        # response — served only from the second GET onward, so the G4
        # preamble skip-check still sees pre-write state and the ambiguous
        # POST path is genuinely exercised. Defaults to PR_REVIEWS_JSON so
        # tests that don't care about the distinction see one consistent
        # view, as before.
        COUNT_FILE="${CAPTURE_FILE}.reviews_get_count"
        N=0
        if [[ -f "$COUNT_FILE" ]]; then N="$(cat "$COUNT_FILE")"; fi
        N=$((N + 1))
        echo "$N" > "$COUNT_FILE"
        if [[ "$N" -gt 1 ]]; then
            emit 200 "${PR_REVIEWS_JSON_RECHECK:-${PR_REVIEWS_JSON:-[]}}"
        else
            emit 200 "${PR_REVIEWS_JSON:-[]}"
        fi
        exit 0
    fi
    ;;
  */pulls/*)
    json_out="$(python3 - <<'PYEOF2'
import json, os
print(json.dumps({
    "head": {"sha": os.environ.get("PR_HEAD_SHA", "sha-headabc123")},
    "user": {"login": os.environ.get("PR_AUTHOR", "hos-worker-hos[bot]")},
    "requested_reviewers": [],
    "review_comments": 0,
}))
PYEOF2
)"
    emit 200 "$json_out"
    exit 0
    ;;
  *)
    emit 404 '{"message":"not found"}'
    exit 1
    ;;
esac
"""


def test_w18_ambiguous_post_response_recovers_without_duplicate_post(h):
    """An ambiguous first POST (no parseable status, connection-lost shape)
    followed by a recheck that finds the review already landed — with the
    body byte-identical to what was just posted — must report success
    WITHOUT issuing a second POST — a second POST here is exactly what
    would create a duplicate review object.

    The preamble read (before the write) sees nothing yet, so G4 does not
    skip and the write is genuinely attempted; only the post-failure
    recheck (after the write) sees the landed review, via
    PR_REVIEWS_JSON_RECHECK — modelling the write having actually reached
    GitHub despite the lost response."""
    _write_exec(h.stub_bin / "gh", AMBIGUOUS_SUBMIT_GH_STUB)
    reviews_after = json.dumps(
        [
            {
                "id": 9001,
                "user": {"login": DEFAULT_BOT_LOGIN},
                "state": "COMMENTED",
                "commit_id": DEFAULT_HEAD_SHA,
                "body": VALID_OVERSEER_BODY,
                "html_url": "https://github.com/test-owner/test-repo/pull/1#pullrequestreview-9001",
            }
        ]
    )
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"PR_REVIEWS_JSON": "[]", "PR_REVIEWS_JSON_RECHECK": reviews_after},
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["posted"] is True
    assert record["review_id"] == 9001
    assert any("ambiguous" in nv for nv in record["not_verified"])
    cap = h.capture()
    posts = [line for line in cap.splitlines() if "GH_STDIN_BODY:" in line]
    # Exactly one POST body was ever sent — the ambiguous failure must not
    # have triggered a second POST once the recheck found the review.
    assert len(posts) == 1, cap


def test_w18_ambiguous_post_response_not_found_reports_failure_no_duplicate(h):
    """The complementary case: the recheck genuinely finds nothing (the
    ambiguous POST really did fail server-side too). This must report
    failure — never fabricate success — and must NOT retry the POST
    in-process (#1657 PR-1 review round 3): the recovery direction is a
    single recheck, then defer to the next cron cycle's preamble read, not
    an in-process retry loop."""
    _write_exec(h.stub_bin / "gh", AMBIGUOUS_SUBMIT_GH_STUB)
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"PR_REVIEWS_JSON": "[]"},
    )
    assert result.returncode == 1, result.stderr
    record = _parse_stdout_json(result)
    assert record.get("posted") in (None, False)
    assert "outcome indeterminate" in (record.get("error") or "")
    assert "next cron cycle" in (record.get("error") or "")
    cap = h.capture()
    posts = [line for line in cap.splitlines() if "GH_STDIN_BODY:" in line]
    # Exactly one POST attempt — no in-process retry.
    assert len(posts) == 1, cap


# --------------------------------------------------------------------------- #
# S — Finding 1 (#1657 codex adversarial-security second review, CWE-863),
# exercised end to end through the real bash wrapper: the acting identity
# (HOS_BOT_LOGIN, as get_app_token.sh actually minted it) not matching
# ctx.config.overseer_handle (BOT_OVERSEER_USERNAME) must refuse an approve,
# distinctly from the pre-existing --app-only G0 refusal. GET_APP_TOKEN_STUB
# always exports a fixed HOS_BOT_LOGIN (mirroring a real mint's own env
# export, which no caller-supplied env var can pre-empt), so the mismatch is
# constructed via Harness.set_overseer_handle() on the configured side
# instead — the two are equivalent from G0b's point of view, since it only
# ever compares them to each other.
# --------------------------------------------------------------------------- #


def test_s_approve_refuses_when_minted_identity_mismatches_overseer_handle(h):
    # GET_APP_TOKEN_STUB always exports a fixed HOS_BOT_LOGIN (mirroring a
    # real mint's own env export, which a caller-supplied env var cannot
    # pre-empt) — so the mismatch is constructed from the configured
    # overseer handle side instead.
    h.set_overseer_handle("some-other-bot[bot]")
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 3, result.stderr
    record = _parse_stdout_json(result)
    assert record["refusal_reason"] == "approve_requires_overseer_identity_match"
    assert record["commit_id"] == DEFAULT_HEAD_SHA
    cap = h.capture()
    stdin_lines = [line for line in cap.splitlines() if line.startswith("GH_STDIN_BODY:")]
    assert not stdin_lines, cap


def test_s_approve_succeeds_when_minted_identity_matches_overseer_handle(h):
    """The matching case, stated explicitly (complements
    test_overseer_app_can_still_approve_when_otherwise_eligible, which relies
    on the fixture's default minted HOS_BOT_LOGIN already matching
    BOT_OVERSEER_USERNAME without naming that as the thing under test)."""
    h.set_overseer_handle(DEFAULT_BOT_LOGIN)
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "approve",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["posted"] is True


def test_s_comment_unaffected_by_identity_mismatch(h):
    """G0b is gated on --event approve only — a mismatched configured
    overseer handle must not block a comment verdict."""
    h.set_overseer_handle("some-other-bot[bot]")
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ]
    )
    assert result.returncode == 0, result.stderr
    record = _parse_stdout_json(result)
    assert record["posted"] is True


# --------------------------------------------------------------------------- #
# SHOULD_FIX (added to the same #1657 batch, coordinator-relayed
# security-reviewer finding): bootstrap/pr_review.sh does its own bash-level
# argv scan to decide which --app value to mint a token for, entirely
# separate from pr_review_cli.py's argparse, which decides which identity is
# *authorized* (G0/G0b above). A divergence between the two would be a
# mint/authorize mismatch — exactly the vulnerability class Finding 1 closes.
# Today every constructible divergent case is safe by accident: argparse's
# own strictness refuses to parse before any handler (hence any POST) can
# run. This is a pinned regression test for that invariant, deliberately NOT
# a unification of the two parsers (out of scope for this change — see the
# coordinator's explicit instruction not to half-refactor the wrapper's
# argv contract in this pass).
#
# `_run_wrapper_capture_argv` replaces `python3` on PATH with a stub that
# records the exact argv pr_review.sh would have handed to the real CLI
# (never running it), and reads back which --app value (if any)
# GET_APP_TOKEN_STUB was invoked with — the two independent decisions this
# test compares.
# --------------------------------------------------------------------------- #

PYTHON_ARGV_CAPTURE_STUB = """#!/usr/bin/env bash
shift
printf '%s\\n' "$@" > "$PY_ARGV_CAPTURE"
echo '{"schema_version":1,"subcommand":null,"pr":null,"app_role":null,"not_verified":[],"error":null}'
exit 0
"""


def _run_wrapper_capture_argv(h, full_argv):
    """Run the real bootstrap/pr_review.sh with `full_argv` passed through
    verbatim (no automatic --repo injection, unlike Harness.run()), with
    `python3` shadowed by a stub that captures argv and never runs the real
    CLI. Returns (minted_app_or_None, py_argv_or_None) — `minted_app` is the
    --app value bash's own scan decided to mint a token for (None if it
    decided not to mint at all); `py_argv` is the exact argv that would have
    reached argparse.
    """
    py_stub_dir = h.tmp / "py_argv_stub_bin"
    py_stub_dir.mkdir(exist_ok=True)
    _write_exec(py_stub_dir / "python3", PYTHON_ARGV_CAPTURE_STUB)
    py_argv_capture = h.tmp / "py_argv_capture.txt"
    if py_argv_capture.exists():
        py_argv_capture.unlink()
    env = {
        "PATH": f"{py_stub_dir}:{h.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "CAPTURE_FILE": str(h.capture_file),
        "HOME": str(h.tmp / "home"),
        "PY_ARGV_CAPTURE": str(py_argv_capture),
    }
    subprocess.run(
        [BASH, str(h.repo_root / "bootstrap" / "pr_review.sh"), *full_argv],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )
    cap = h.capture()
    minted_app = None
    for line in cap.splitlines():
        if line.startswith("GET_APP_TOKEN_CALLED_WITH:--app "):
            minted_app = line[len("GET_APP_TOKEN_CALLED_WITH:--app ") :].strip()
    py_argv = py_argv_capture.read_text().splitlines() if py_argv_capture.exists() else None
    return minted_app, py_argv


def _assert_no_mint_authorize_divergence(minted_app, py_argv):
    """If bash never decided to mint, there is nothing to compare — no token
    means no privileged call is reachable. Otherwise, feed the exact same
    argv through the real argparse parser: either it refuses to parse at all
    (safe — no handler, hence no POST, is reachable), or it must resolve
    --app to the identical value bash minted for."""
    if minted_app is None:
        return
    assert py_argv is not None, "bash minted a token but python3 was never invoked"
    parser = cli._build_parser()
    try:
        args = parser.parse_args(py_argv)
    except cli._UsageExit:
        return
    assert args.app == minted_app, (minted_app, py_argv, args.app)


def test_app_role_agreement_equals_form(h):
    full_argv = [
        "submit-verdict",
        "--repo",
        "test-owner/test-repo",
        "--pr",
        "42",
        "--event",
        "comment",
        "--tier",
        "LOW",
        "--body-file",
        str(h.body_file),
        "--app=overseer",
    ]
    minted_app, py_argv = _run_wrapper_capture_argv(h, full_argv)
    assert minted_app == "overseer"
    _assert_no_mint_authorize_divergence(minted_app, py_argv)


def test_app_role_agreement_space_form(h):
    full_argv = [
        "submit-verdict",
        "--repo",
        "test-owner/test-repo",
        "--pr",
        "42",
        "--event",
        "comment",
        "--tier",
        "LOW",
        "--body-file",
        str(h.body_file),
        "--app",
        "overseer",
    ]
    minted_app, py_argv = _run_wrapper_capture_argv(h, full_argv)
    assert minted_app == "overseer"
    _assert_no_mint_authorize_divergence(minted_app, py_argv)


def test_app_role_agreement_missing_value_never_mints(h):
    """A dangling --app with no following value: bash's `_prev_arg` check
    only fires on the *next* iteration, so a trailing --app is never picked
    up — bash correctly declines to mint, and argparse independently refuses
    to parse ('expected one argument')."""
    full_argv = [
        "submit-verdict",
        "--repo",
        "test-owner/test-repo",
        "--pr",
        "42",
        "--event",
        "comment",
        "--tier",
        "LOW",
        "--body-file",
        str(h.body_file),
        "--app",
    ]
    minted_app, py_argv = _run_wrapper_capture_argv(h, full_argv)
    assert minted_app is None
    _assert_no_mint_authorize_divergence(minted_app, py_argv)


def test_app_role_agreement_repeated_flag_last_wins_both_sides(h):
    full_argv = [
        "submit-verdict",
        "--repo",
        "test-owner/test-repo",
        "--pr",
        "42",
        "--event",
        "comment",
        "--tier",
        "LOW",
        "--body-file",
        str(h.body_file),
        "--app",
        "worker",
        "--app",
        "overseer",
    ]
    minted_app, py_argv = _run_wrapper_capture_argv(h, full_argv)
    assert minted_app == "overseer"
    parser = cli._build_parser()
    args = parser.parse_args(py_argv)
    assert args.app == "overseer"
    _assert_no_mint_authorize_divergence(minted_app, py_argv)


def test_app_role_agreement_after_double_dash_argparse_refuses(h):
    """`--app overseer` appearing after a `--` positional-separator: bash's
    naive scan has no concept of `--` and still picks it up (mints
    'overseer'), but argparse never saw a --app before `--` (required-
    argument error) and treats the tokens after `--` as unrecognized
    positionals — a usage error either way, so no handler (hence no POST)
    is ever reachable despite bash's mint. This is the exact
    divergence-risk shape the security-reviewer's finding named; pinned so a
    future argparse behaviour change cannot silently make this shape
    resolve successfully in a way that disagrees with bash's mint."""
    full_argv = [
        "submit-verdict",
        "--repo",
        "test-owner/test-repo",
        "--pr",
        "42",
        "--event",
        "comment",
        "--tier",
        "LOW",
        "--body-file",
        str(h.body_file),
        "--",
        "--app",
        "overseer",
    ]
    minted_app, py_argv = _run_wrapper_capture_argv(h, full_argv)
    assert minted_app == "overseer"
    parser = cli._build_parser()
    with pytest.raises(cli._UsageExit):
        parser.parse_args(py_argv)
    _assert_no_mint_authorize_divergence(minted_app, py_argv)


def test_w18_stale_content_review_does_not_short_circuit_as_success(h):
    """A same-bot, same-head, same-state review from a PRIOR cycle with
    DIFFERENT body content must not be mistaken for the write that just
    failed ambiguously (#1657 PR-1 review round 3, MUST_FIX). G4
    deliberately permits multiple distinct COMMENT reviews on the same head
    SHA across cycles — its own comparison is byte-identical — so a stale-
    content review here is an entirely ordinary object to find, not proof
    this write landed. Reproduces the exact scenario code-reviewer verified
    live against the pre-fix code: cycle N posts body A (review R1), cycle
    N+1 computes updated body B (new findings) on the same head and its
    POST fails ambiguously; the recheck must not treat R1 as a match for
    body B."""
    _write_exec(h.stub_bin / "gh", AMBIGUOUS_SUBMIT_GH_STUB)
    stale_reviews = json.dumps(
        [
            {
                "id": 8001,
                "user": {"login": DEFAULT_BOT_LOGIN},
                "state": "COMMENTED",
                "commit_id": DEFAULT_HEAD_SHA,
                "body": "stale verdict body from a prior cycle, not what was just posted\n",
                "html_url": "https://github.com/test-owner/test-repo/pull/1#pullrequestreview-8001",
            }
        ]
    )
    result = h.run(
        [
            "submit-verdict",
            "--app",
            "overseer",
            "--pr",
            "42",
            "--event",
            "comment",
            "--tier",
            "LOW",
            "--body-file",
            str(h.body_file),
        ],
        env_overrides={"PR_REVIEWS_JSON": stale_reviews},
    )
    assert result.returncode == 1, result.stderr
    record = _parse_stdout_json(result)
    assert record.get("posted") in (None, False)
    assert record.get("review_id") != 8001
    assert "outcome indeterminate" in (record.get("error") or "")
    cap = h.capture()
    posts = [line for line in cap.splitlines() if "GH_STDIN_BODY:" in line]
    # Exactly one POST attempt — no in-process retry, and the stale review
    # must not have short-circuited a second POST either.
    assert len(posts) == 1, cap
