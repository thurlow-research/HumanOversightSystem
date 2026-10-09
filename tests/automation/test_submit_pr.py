"""Tests for bootstrap/submit_pr.sh (#1085).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH so
the argument-parsing, --confirmed human-proxy gate, and
mint/push/create/revoke flow are exercised without touching the network or a
real GitHub App.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUBMIT_PR_SH = REPO_ROOT / "bootstrap" / "submit_pr.sh"
CLOSING_KEYWORDS_PY = REPO_ROOT / "scripts" / "automation" / "closing_keywords.py"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='fake-bot[bot]'\\n"
"""

# rev-parse --abbrev-ref HEAD -> "current-branch"; rev-parse --verify -> honors
# GIT_VERIFY_FAIL; rev-parse --git-common-dir -> $GIT_COMMON_DIR (#967 ownership
# store resolution); remote get-url origin -> repo URL;
# fetch -> honors GIT_FETCH_FAIL; rev-list --count -> GIT_BEHIND_COUNT (default 0);
# merge -> honors GIT_MERGE_FAIL (merge --abort always succeeds);
# push <url> <refspec> -> captured, honors GIT_PUSH_FAIL;
# log -> prints $GIT_LOG_FILE (NUL-separated "<sha>\\n<message>" records, the
# `git log -z --format=%H%n%B` shape; default empty = zero commits), honors
# GIT_LOG_FAIL (#1856 closing-keyword guard, phase 2).
GIT_STUB = """#!/usr/bin/env bash
echo "GIT_CALLED_WITH:$*" >> "$CAPTURE_FILE"
i=0
if [[ "$1" == "-C" ]]; then i=2; fi
if [[ "${@:$((i+1)):1}" == "--no-replace-objects" ]]; then i=$((i+1)); fi
sub="${@:$((i+1)):1}"
case "$sub" in
  remote) echo "https://github.com/test-owner/test-repo.git" ;;
  rev-parse)
    if [[ "$*" == *"--git-common-dir"* ]]; then
        echo "${GIT_COMMON_DIR:?GIT_COMMON_DIR not set in test harness}"
    elif [[ "$*" == *"refs/remotes/origin/"* ]]; then
        echo "${GIT_BASE_SHA:-3333333333333333333333333333333333333333}"
    elif [[ "$*" == *"--verify"* ]]; then
        if [[ "${GIT_VERIFY_FAIL:-}" == "1" ]]; then exit 1; fi
        echo "${GIT_HEAD_SHA:-1111111111111111111111111111111111111111}"
    else
        echo "current-branch"
    fi
    ;;
  fetch) if [[ "${GIT_FETCH_FAIL:-}" == "1" ]]; then exit 1; fi ;;
  rev-list) echo "${GIT_BEHIND_COUNT:-0}" ;;
  merge)
    if [[ "$*" == *"--abort"* ]]; then exit 0; fi
    if [[ "${GIT_MERGE_FAIL:-}" == "1" ]]; then exit 1; fi
    ;;
  push) if [[ "${GIT_PUSH_FAIL:-}" == "1" ]]; then exit 1; fi ;;
  log)
    if [[ "${GIT_LOG_FAIL:-}" == "1" ]]; then exit 1; fi
    if [[ -n "${GIT_LOG_FILE:-}" ]]; then cat "$GIT_LOG_FILE"; fi
    ;;
esac
exit 0
"""

# "api repos/.../pulls/<N> --jq ..." -> the --update-pr authorship check (#967
# AD-4, T9): prints a TSV of state/head.ref/user.login/base.ref/html_url,
# honoring GH_API_PULL_* overrides and GH_API_PULL_FAIL.
# "api repos/.../pulls?state=open&head=... --jq ..." -> the open-mode
# duplicate-PR guard: prints a TSV of count/first-number, honoring
# GH_API_DUP_* overrides and GH_API_DUP_FAIL.
GH_STUB = """#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "$1" == "pr" && "$2" == "create" ]]; then
    if [[ "${GH_FAIL:-}" == "1" ]]; then exit 1; fi
    prev=""
    for a in "$@"; do
        if [[ "$prev" == "--body-file" ]]; then
            echo "GH_BODY_PATH:$a" >> "$CAPTURE_FILE"
            echo "GH_BODY_CONTENT:$(cat "$a")" >> "$CAPTURE_FILE"
        fi
        prev="$a"
    done
    echo "https://github.com/test-owner/test-repo/pull/999"
    exit 0
fi
if [[ "$1" == "api" ]]; then
    path="$2"
    if [[ "$path" == *"pulls?state=open"* ]]; then
        if [[ "${GH_API_DUP_FAIL:-}" == "1" ]]; then exit 1; fi
        printf '%s\\t%s\\n' "${GH_API_DUP_COUNT:-0}" "${GH_API_DUP_NUMBER:-}"
        exit 0
    elif [[ "$path" == *"/pulls/"* ]]; then
        if [[ "${GH_API_PULL_FAIL:-}" == "1" ]]; then exit 1; fi
        printf '%s\\t%s\\t%s\\t%s\\t%s\\n' \\
            "${GH_API_PULL_STATE:-open}" \\
            "${GH_API_PULL_HEAD_REF:-current-branch}" \\
            "${GH_API_PULL_USER_LOGIN:-fake-bot[bot]}" \\
            "${GH_API_PULL_BASE_REF:-main}" \\
            "${GH_API_PULL_HTML_URL:-https://github.com/test-owner/test-repo/pull/42}"
        exit 0
    fi
fi
exit 1
"""

CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


DEFAULT_CYCLE_ID = "test-cycle"
PINNED_BASE_SHA = "3333333333333333333333333333333333333333"
PINNED_SHA = "1111111111111111111111111111111111111111"


def _encode_branch(branch: str) -> str:
    """Mirror bootstrap/lib/branch_ownership.sh's hos_bo_encode (#967, §4.2)."""
    return branch.replace("%", "%25").replace("/", "%2F")


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bootstrap_dir = tmp_path / "bootstrap"
        self.bootstrap_dir.mkdir()
        self.script = self.bootstrap_dir / "submit_pr.sh"
        shutil.copy(SUBMIT_PR_SH, self.script)
        self.script.chmod(0o755)
        _write_exec(self.bootstrap_dir / "get_app_token.sh", GET_APP_TOKEN_STUB)

        self.lib_dir = self.bootstrap_dir / "lib"
        self.lib_dir.mkdir()
        shutil.copy(
            REPO_ROOT / "bootstrap" / "lib" / "branch_ownership.sh",
            self.lib_dir / "branch_ownership.sh",
        )

        # hos_bo_audit_refusal (#967, R9) sources <repo_dir>/scripts/oversight/lib/audit_log.sh.
        # repo_dir here is tmp_path (submit_pr.sh resolves it as "$SCRIPT_DIR/..").
        self.audit_lib_dir = tmp_path / "scripts" / "oversight" / "lib"
        self.audit_lib_dir.mkdir(parents=True)
        self.audit_log_path = self.audit_lib_dir / "audit_log.sh"
        _write_exec(
            self.audit_log_path,
            "#!/usr/bin/env bash\n"
            "audit_write_event() {\n"
            '    echo "AUDIT_EVENT:$1" >> "$CAPTURE_FILE"\n'
            "}\n",
        )

        # #1856 closing-keyword guard (submit_pr.sh resolves it relative to itself).
        self.ck_dir = tmp_path / "scripts" / "automation"
        self.ck_dir.mkdir(parents=True)
        self.ck_py = self.ck_dir / "closing_keywords.py"
        shutil.copy(CLOSING_KEYWORDS_PY, self.ck_py)

        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "git", GIT_STUB)
        _write_exec(self.stub_bin / "gh", GH_STUB)
        _write_exec(self.stub_bin / "curl", CURL_STUB)

        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

        self.body_file = tmp_path / "body.md"
        self.body_file.write_text("pr body\nwith a newline\n")

        self.git_common_dir = tmp_path / "gitdir"

    @staticmethod
    def _get_arg(args, flag):
        args = list(args)
        if flag in args:
            idx = args.index(flag)
            if idx + 1 < len(args):
                return args[idx + 1]
        return None

    def write_record(
        self,
        branch: str,
        *,
        cycle_id: str = DEFAULT_CYCLE_ID,
        role: str = "worker",
        branch_field: str | None = None,
        created_at: str = "2026-01-01T00:00:00Z",
        body: str | None = None,
    ) -> Path:
        """Write a branch-ownership record directly (§4.3), bypassing the bash
        writer, so tests can construct both valid and deliberately invalid
        records (wrong branch/cycle/role, malformed, oversized)."""
        store = self.git_common_dir / "hos" / "branch-ownership"
        store.mkdir(parents=True, exist_ok=True)
        path = store / f"{_encode_branch(branch)}.rec"
        if body is not None:
            path.write_text(body)
        else:
            path.write_text(
                "schema=1\n"
                f"branch={branch_field if branch_field is not None else branch}\n"
                f"cycle_id={cycle_id}\n"
                f"role={role}\n"
                f"created_at={created_at}\n"
            )
        return path

    def run(
        self, args, env_overrides=None, cycle_id=DEFAULT_CYCLE_ID, write_record=True, bash=BASH
    ):
        """Run submit_pr.sh. For --app worker, by default exports HOS_CYCLE_ID
        and writes a matching valid ownership record for the resolved --head
        branch (or "current-branch" if --head is omitted) so existing
        happy-path tests exercise the unchanged push/PR flow (T2) rather than
        incidentally hitting the new refusal path. Pass write_record=False
        and/or cycle_id=None to exercise the refusal path (T1, T3, T5)."""
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
            "GIT_COMMON_DIR": str(self.git_common_dir),
        }
        if self._get_arg(args, "--app") == "worker":
            if cycle_id:
                env["HOS_CYCLE_ID"] = cycle_id
                if write_record:
                    head = self._get_arg(args, "--head") or "current-branch"
                    self.write_record(head, cycle_id=cycle_id)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [bash, str(self.script), *args],
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


BASE_ARGS = ["--title", "t", "--base", "main"]


# --------------------------------------------------------------------------- #
# Argument validation
# --------------------------------------------------------------------------- #


def test_missing_title(h):
    result = h.run(["--body-file", str(h.body_file), "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "--title" in result.stderr


def test_missing_body_file_flag(h):
    result = h.run(["--title", "t", "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


def test_body_file_does_not_exist(h):
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.tmp / "missing.md"),
            "--base",
            "main",
            "--app",
            "worker",
        ]
    )
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_missing_base(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--app", "worker"])
    assert result.returncode != 0
    assert "--base" in result.stderr


def test_missing_app(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_app_value(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "bogus"]
    )
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_rejects_inline_body(h):
    result = h.run(["--title", "t", "--body", "inline text", "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


# --------------------------------------------------------------------------- #
# Human-proxy authorization gate
# --------------------------------------------------------------------------- #


def test_app_human_without_confirmed_fails(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "human"]
    )
    assert result.returncode != 0
    assert "--confirmed" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


def test_app_human_with_confirmed_proceeds(h):
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--app",
            "human",
            "--confirmed",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "GET_APP_TOKEN_CALLED_WITH:--app human" in h.capture()


def test_app_worker_does_not_require_confirmed(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"]
    )
    assert result.returncode == 0, result.stderr


def test_app_overseer_does_not_require_confirmed(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "overseer"]
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_head_defaults_to_current_branch(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    push_line = [
        ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "x-access-token" in ln
    ][0]
    assert f"{PINNED_SHA}:refs/heads/current-branch" in push_line


def test_explicit_head_used_over_current_branch(h):
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "explicit-branch",
            "--app",
            "worker",
        ]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    push_line = [
        ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "x-access-token" in ln
    ][0]
    assert f"{PINNED_SHA}:refs/heads/explicit-branch" in push_line
    # #1166 regression guard: the push source must be the named branch, never
    # the working-tree HEAD (current-branch != explicit-branch in this test).
    assert "HEAD:refs/heads/" not in push_line


def test_gh_pr_create_receives_private_snapshot_of_scanned_body(h):
    """Body is copied once; gh gets the private copy (same content), removed on exit."""
    h.body_file.write_text("single-line body\n")
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "feature-x",
            "--app",
            "worker",
        ]
    )
    assert result.returncode == 0, result.stderr
    lines = h.capture().splitlines()
    path = [ln for ln in lines if ln.startswith("GH_BODY_PATH:")][0].split(":", 1)[1]
    assert path != str(h.body_file)
    assert "GH_BODY_CONTENT:single-line body" in lines
    assert not Path(path).exists()


def test_happy_path_pushes_creates_pr_and_revokes_token(h):
    result = h.run(
        [
            "--title",
            "My PR",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "feature-x",
            "--app",
            "worker",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/test-owner/test-repo/pull/999"

    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app worker" in cap
    push_line = [
        ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "x-access-token" in ln
    ][0]
    assert "x-access-token:fake-token-worker@github.com/test-owner/test-repo.git" in push_line
    assert f"{PINNED_SHA}:refs/heads/feature-x" in push_line
    gh_line = [ln for ln in cap.splitlines() if ln.startswith("GH_CALLED_WITH:pr create")][0]
    assert "--repo test-owner/test-repo" in gh_line
    assert "--base main" in gh_line
    assert "--head feature-x" in gh_line
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


def test_token_mint_failure_aborts_before_push(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "push" not in cap


def test_push_failure_aborts_before_pr_create_but_revokes(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_PUSH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    # The open-mode duplicate-PR guard (#967 AD-4) now runs before the push,
    # so it is expected to have fired; `gh pr create` must not have.
    assert "GH_CALLED_WITH:pr create" not in cap
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


def test_gh_pr_create_failure_still_revokes_token(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


# --------------------------------------------------------------------------- #
# Merge-from-base guard (#1162)
# --------------------------------------------------------------------------- #


def test_fetches_base_before_pushing(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"]
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    fetch_line = [
        ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and " fetch " in ln
    ][0]
    assert "fetch origin main" in fetch_line


def test_up_to_date_base_does_not_merge(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "0"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "merge" not in cap


def test_behind_base_merges_before_push(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "3"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    calls = cap.splitlines()
    merge_line = [ln for ln in calls if ln.startswith("GIT_CALLED_WITH") and " merge " in ln][0]
    assert "origin/main" in merge_line
    push_idx = [i for i, ln in enumerate(calls) if "x-access-token" in ln][0]
    merge_idx = calls.index(merge_line)
    assert merge_idx < push_idx, "merge must happen before push"


def test_merge_conflict_aborts_and_does_not_push(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "3", "GIT_MERGE_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "conflict" in result.stderr.lower()
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert not any("x-access-token" in ln for ln in cap.splitlines())
    assert any("--abort" in ln for ln in cap.splitlines())


def test_stale_base_merge_emits_audit_event(h):
    """A successful merge-from-base fires the #1198 Stage 0 item 6 audit
    event, previously only a warn()."""
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "3"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "AUDIT_EVENT:" in cap
    assert '"event":"stale-base-merged"' in cap


def test_up_to_date_base_does_not_emit_audit_event(h):
    """No merge needed (BEHIND_COUNT=0) → no stale-base-merged audit event."""
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "0"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert '"event":"stale-base-merged"' not in cap


def test_merge_conflict_does_not_emit_audit_event(h):
    """A merge conflict aborts before the audit call is reached — no event."""
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "3", "GIT_MERGE_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert '"event":"stale-base-merged"' not in cap


# --------------------------------------------------------------------------- #
# Push-source correctness for a non-checked-out branch (#1166)
# --------------------------------------------------------------------------- #


def test_missing_local_branch_fails_closed(h):
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "no-such-branch",
            "--app",
            "worker",
        ],
        env_overrides={"GIT_VERIFY_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "no-such-branch" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert not any("x-access-token" in ln for ln in cap.splitlines())


def test_stale_non_checked_out_head_refuses_instead_of_merging(h):
    # explicit-branch != the stub's "current-branch": this is exactly the
    # build-without-checkout shape (scripts/dev/commit_onto_base.sh) that
    # produced the 11k-deletion incident when submit_pr.sh pushed the
    # checked-out HEAD under the named branch instead of refusing.
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "explicit-branch",
            "--app",
            "worker",
        ],
        env_overrides={"GIT_BEHIND_COUNT": "3"},
    )
    assert result.returncode != 0
    assert "not the checked-out branch" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert not any("x-access-token" in ln for ln in cap.splitlines())
    assert not any(
        ln.startswith("GIT_CALLED_WITH") and " merge " in ln and "--abort" not in ln
        for ln in cap.splitlines()
    )


def test_fetch_failure_aborts_before_token_mint(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_FETCH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


# --------------------------------------------------------------------------- #
# Branch-ownership enforcement (#967, ADR-037, R4/R5/R6) — T1-T5
# --------------------------------------------------------------------------- #


def _assert_fully_refused_before_network(cap: str):
    """No fetch, no token mint, no push, no PR create — the refusal must
    precede all network access (R4, ADR §6.1)."""
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert not any("x-access-token" in ln for ln in cap.splitlines())
    assert not any(ln.startswith("GIT_CALLED_WITH") and " fetch " in ln for ln in cap.splitlines())
    assert "GH_CALLED_WITH" not in cap


def test_worker_refuses_pr_for_branch_without_ownership_record(h):
    """T1 — the #967 regression scenario: a foreign branch with no ownership
    record must never reach fetch, token mint, push, or gh pr create. This
    test MUST fail against pre-fix behaviour."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "foreign-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    assert "foreign-branch" in result.stderr
    assert "#967" in result.stderr
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_when_no_cycle_id_set(h):
    """T3 — no_cycle_id: the checking process itself was not launched with a
    cycle identity, e.g. a session not started by bin/hos-cron."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        cycle_id=None,
    )
    assert result.returncode != 0
    assert "HOS_CYCLE_ID" in result.stderr
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_record_from_a_different_cycle(h):
    """T3 — wrong_cycle: a record exists but was written by a prior/different
    cycle. Ownership does not transfer (ADR-037 AD-1)."""
    h.write_record("current-branch", cycle_id="some-other-cycle")
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        write_record=False,
        cycle_id="this-cycle",
    )
    assert result.returncode != 0
    assert "current-branch" in result.stderr
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_record_naming_a_different_branch(h):
    """T3 — wrong_branch: the record file at this branch's path asserts a
    different branch name inside it (no prefix/glob match is ever honoured)."""
    h.write_record("current-branch", branch_field="someone-elses-branch")
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_record_with_non_worker_role(h):
    """T3 — wrong_role: a record cannot be produced incidentally by a
    non-worker session per R2; this is the fail-closed check on that value."""
    h.write_record("current-branch", role="human")
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_malformed_record(h):
    """T3 — malformed: content doesn't match the key=value grammar."""
    h.write_record("current-branch", body="this is not a valid record\n")
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_unreadable_record(h):
    """T3 — unreadable: chmod 000 makes the file exist but unreadable."""
    path = h.write_record("current-branch")
    path.chmod(0o000)
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_oversized_record(h):
    """T3 — oversized (> 4096 bytes): treated as no_record, not parsed."""
    oversized_body = (
        "schema=1\nbranch=current-branch\ncycle_id=test-cycle\nrole=worker\n"
        f"created_at={'x' * 5000}\n"
    )
    h.write_record("current-branch", body=oversized_body)
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_worker_refuses_pr_for_absent_record(h):
    """T3 — no_record: nothing at all was written for this branch."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "never-created-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_worker_with_valid_record_reaches_unchanged_push_pr_path(h):
    """T2 — happy path, run alongside T1's refusal so both directions of the
    fail-open/fail-closed risk are covered by one proof obligation (SPEC §10).
    A branch with a valid current-cycle record still reaches the unchanged
    push/PR flow."""
    result = h.run(
        [
            "--title",
            "My PR",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "worker-owned-branch",
            "--app",
            "worker",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/test-owner/test-repo/pull/999"
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app worker" in cap
    assert any("x-access-token" in ln for ln in cap.splitlines())


def test_app_human_confirmed_ignores_ownership_state(h):
    """T4 — role isolation. A stale/foreign record and no HOS_CYCLE_ID at all
    must not affect --app human --confirmed: it never consults the store."""
    h.write_record("current-branch", cycle_id="not-this-session")
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--app",
            "human",
            "--confirmed",
        ],
        cycle_id=None,
    )
    assert result.returncode == 0, result.stderr


def test_app_overseer_ignores_ownership_state(h):
    """T4 — role isolation. Same as above for --app overseer."""
    h.write_record("current-branch", cycle_id="not-this-session")
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "overseer"],
        cycle_id=None,
    )
    assert result.returncode == 0, result.stderr


def test_confirmed_flag_does_not_bypass_worker_ownership_check(h):
    """T5 — no override. --confirmed is a human-proxy authorization flag; it
    must not let --app worker skip the ownership check."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "foreign-branch",
            "--app",
            "worker",
            "--confirmed",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_hos_state_dir_env_var_is_not_consulted_for_ownership(h):
    """T5 — no override. HOS_STATE_DIR is the launcher's unrelated state-dir
    idiom; R5 forbids any environment escape hatch for the ownership check."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "foreign-branch",
            "--app",
            "worker",
        ],
        write_record=False,
        env_overrides={"HOS_STATE_DIR": str(h.tmp / "fake-state-dir")},
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_hos_bo_reason_env_var_cannot_fake_a_valid_record(h):
    """T5 — no override. Pre-setting the library's own out-parameter must not
    influence the outcome; it is only ever an output, never an input."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "foreign-branch",
            "--app",
            "worker",
        ],
        write_record=False,
        env_overrides={"HOS_BO_REASON": ""},
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_refusal_emits_audit_event(h):
    """R9 — a refusal is observable via the standard audit-log writer."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "foreign-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "AUDIT_EVENT:" in cap
    assert '"event":"branch-ownership-refused"' in cap
    assert '"branch":"foreign-branch"' in cap
    assert '"reason":"no_record"' in cap


def test_audit_sink_failure_does_not_mask_refusal(h):
    """R9 — an audit-sink failure must never convert a refusal into a pass."""
    h.audit_log_path.unlink()
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "foreign-branch",
            "--app",
            "worker",
        ],
        write_record=False,
    )
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


# --------------------------------------------------------------------------- #
# --update-pr mode (#967 AD-4, §7, T9)
# --------------------------------------------------------------------------- #


def test_update_pr_rejects_non_worker_app(h):
    result = h.run(
        [
            "--update-pr",
            "42",
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "human",
            "--confirmed",
        ],
    )
    assert result.returncode != 0
    assert "--update-pr requires --app worker" in result.stderr


def test_update_pr_rejects_title(h):
    result = h.run(
        [
            "--update-pr",
            "42",
            "--title",
            "t",
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
    )
    assert result.returncode != 0
    assert "--title" in result.stderr


def test_update_pr_rejects_body_file(h):
    result = h.run(
        [
            "--update-pr",
            "42",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
    )
    assert result.returncode != 0
    assert "--body-file" in result.stderr


def test_update_pr_rejects_non_numeric_pr_number(h):
    result = h.run(
        [
            "--update-pr",
            "not-a-number",
            "--base",
            "main",
            "--head",
            "current-branch",
            "--app",
            "worker",
        ],
    )
    assert result.returncode != 0
    assert "--update-pr" in result.stderr


def test_update_pr_does_not_consult_ownership_record(h):
    """§7 — update mode requires no branch-ownership record; authority comes
    from the server-side PR-authorship check instead (AD-4)."""
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/test-owner/test-repo/pull/42"


def test_update_pr_pushes_without_opening_new_pr(h):
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert any(ln.startswith("GIT_CALLED_WITH") and " push " in ln for ln in cap.splitlines())
    assert "pulls/42" in cap
    assert "GH_CALLED_WITH:pr create" not in cap


def test_update_pr_refuses_on_pr_fetch_failure(h):
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
        env_overrides={"GH_API_PULL_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "Could not fetch PR #42" in result.stderr
    cap = h.capture()
    assert not any(ln.startswith("GIT_CALLED_WITH") and " push " in ln for ln in cap.splitlines())
    assert "CURL_CALLED_WITH" in cap


def test_update_pr_refuses_when_pr_closed(h):
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
        env_overrides={"GH_API_PULL_STATE": "closed"},
    )
    assert result.returncode != 0
    assert "does not match this push" in result.stderr


def test_update_pr_refuses_on_head_mismatch(h):
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
        env_overrides={"GH_API_PULL_HEAD_REF": "some-other-branch"},
    )
    assert result.returncode != 0
    assert "does not match this push" in result.stderr


def test_update_pr_refuses_on_base_mismatch(h):
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
        env_overrides={"GH_API_PULL_BASE_REF": "develop"},
    )
    assert result.returncode != 0
    assert "does not match this push" in result.stderr


def test_update_pr_refuses_on_author_mismatch(h):
    """The core AD-4 case: someone else's PR for the same head/base is never
    treated as this bot's to push to."""
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        write_record=False,
        env_overrides={"GH_API_PULL_USER_LOGIN": "someone-else[bot]"},
    )
    assert result.returncode != 0
    assert "does not match this push" in result.stderr
    cap = h.capture()
    assert not any(ln.startswith("GIT_CALLED_WITH") and " push " in ln for ln in cap.splitlines())


# --------------------------------------------------------------------------- #
# Open-mode duplicate-PR guard (#967 AD-4)
# --------------------------------------------------------------------------- #


def test_open_mode_worker_refuses_when_open_pr_already_exists(h):
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "worker-owned-branch",
            "--app",
            "worker",
        ],
        env_overrides={"GH_API_DUP_COUNT": "1", "GH_API_DUP_NUMBER": "77"},
    )
    assert result.returncode != 0
    assert "#77" in result.stderr
    assert "--update-pr 77" in result.stderr
    cap = h.capture()
    assert not any(ln.startswith("GIT_CALLED_WITH") and " push " in ln for ln in cap.splitlines())


def test_open_mode_worker_proceeds_when_no_existing_pr(h):
    """Default stub returns zero existing PRs — the unchanged happy path."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "worker-owned-branch",
            "--app",
            "worker",
        ],
    )
    assert result.returncode == 0, result.stderr


def test_open_mode_worker_refuses_when_duplicate_check_query_fails(h):
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--head",
            "worker-owned-branch",
            "--app",
            "worker",
        ],
        env_overrides={"GH_API_DUP_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "Could not check for an existing open PR" in result.stderr
    cap = h.capture()
    assert not any(ln.startswith("GIT_CALLED_WITH") and " push " in ln for ln in cap.splitlines())


def test_open_mode_human_unaffected_by_duplicate_guard(h):
    """R6 — --app human sees no behaviour change; the duplicate guard is
    scoped to --app worker only."""
    result = h.run(
        [
            "--title",
            "t",
            "--body-file",
            str(h.body_file),
            "--base",
            "main",
            "--app",
            "human",
            "--confirmed",
        ],
        env_overrides={"GH_API_DUP_COUNT": "1", "GH_API_DUP_NUMBER": "77"},
    )
    assert result.returncode == 0, result.stderr


def test_open_mode_overseer_unaffected_by_duplicate_guard(h):
    """R6 — --app overseer sees no behaviour change."""
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "overseer"],
        env_overrides={"GH_API_DUP_COUNT": "1", "GH_API_DUP_NUMBER": "77"},
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Closing-keyword guard (#1856)
# --------------------------------------------------------------------------- #

OPEN_ARGS = ["--base", "main", "--head", "current-branch", "--app", "worker"]
RULING_BODY = "\n".join(f"line {i}" for i in range(1, 60)) + (
    "\n> H6 \u2014 yes. S2 is the fix that closes #1539.\n"
)


def _body(h, text):
    h.body_file.write_text(text)
    return ["--title", "t", "--body-file", str(h.body_file)]


def _commit_log(h, message, sha="abcdef0000000000000000000000000000000000"):
    path = h.tmp / "git_log.bin"
    path.write_text(f"{sha}\n{message}\n\0")
    return {"GIT_LOG_FILE": str(path)}


def _git_calls(cap, sub):
    return [ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and f" {sub} " in ln]


def _assert_no_mint_no_push(cap):
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert not any("x-access-token" in ln for ln in cap.splitlines())
    assert "GH_CALLED_WITH:pr create" not in cap


def test_ck_body_ruling_refused_before_network(h):
    result = h.run([*_body(h, RULING_BODY), *OPEN_ARGS])
    assert result.returncode == 1
    assert "#1539" in result.stderr
    assert "body line 60" in result.stderr
    _assert_fully_refused_before_network(h.capture())


def test_ck_title_refused_before_network(h):
    h.body_file.write_text("clean\n")
    result = h.run(["--title", "fix: closes #42", "--body-file", str(h.body_file), *OPEN_ARGS])
    assert result.returncode == 1
    assert "title" in result.stderr
    assert "#42" in result.stderr
    _assert_fully_refused_before_network(h.capture())


def test_ck_commit_refused_after_fetch_with_range_and_ordering(h):
    result = h.run(
        [*_body(h, "clean body\n"), *OPEN_ARGS],
        env_overrides=_commit_log(h, "subject\n\nfixes #77"),
    )
    assert result.returncode == 1
    assert "commit abcdef0" in result.stderr
    assert "#77" in result.stderr
    cap = h.capture()
    _assert_no_mint_no_push(cap)
    calls = cap.splitlines()
    fetch_idx = calls.index(_git_calls(cap, "fetch")[0])
    log_line = _git_calls(cap, "log")[0]
    assert fetch_idx < calls.index(log_line)
    assert log_line.split()[-1] == f"{PINNED_BASE_SHA}..{PINNED_SHA}"


def test_ck_declared_closes_allows_pr(h):
    result = h.run([*_body(h, RULING_BODY), *OPEN_ARGS, "--closes", "1539"])
    assert result.returncode == 0, result.stderr
    assert "GH_CALLED_WITH:pr create" in h.capture()


def test_ck_clean_pr_proceeds_silently(h):
    result = h.run([*_body(h, "clean body\n"), *OPEN_ARGS])
    assert result.returncode == 0, result.stderr
    assert "closing" not in result.stderr.lower()


def test_ck_declared_but_unmatched_warns_only(h):
    result = h.run([*_body(h, "clean body\n"), *OPEN_ARGS, "--closes", "99"])
    assert result.returncode == 0, result.stderr
    assert "--closes 99 declared but no closing keyword" in result.stderr


def test_ck_update_pr_refuses_keyword_commit_before_mint(h):
    args = ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"]
    env = _commit_log(h, "subject\n\nresolves #55")
    result = h.run(args, env_overrides=env, write_record=False)
    assert result.returncode == 1
    assert "force-push" in result.stderr
    _assert_no_mint_no_push(h.capture())

    result = h.run([*args, "--closes", "55"], env_overrides=env, write_record=False)
    assert result.returncode == 0, result.stderr
    assert any("x-access-token" in ln for ln in h.capture().splitlines())


def test_ck_applies_to_overseer(h):
    result = h.run([*_body(h, RULING_BODY), "--base", "main", "--app", "overseer"])
    assert result.returncode == 1
    _assert_fully_refused_before_network(h.capture())


def test_ck_applies_to_human_confirmed(h):
    result = h.run([*_body(h, RULING_BODY), "--base", "main", "--app", "human", "--confirmed"])
    assert result.returncode == 1
    _assert_fully_refused_before_network(h.capture())


def test_ck_refusal_emits_audit_event(h):
    result = h.run([*_body(h, RULING_BODY), *OPEN_ARGS])
    assert result.returncode == 1
    cap = h.capture()
    assert '"event":"closing-keyword-refused"' in cap
    assert '"phase":"text"' in cap
    assert '"refs":"1539"' in cap
    assert '"app":"worker"' in cap


def test_ck_full_phase_audit_event(h):
    h.run(
        [*_body(h, "clean\n"), *OPEN_ARGS],
        env_overrides=_commit_log(h, "s\n\ncloses #8"),
    )
    assert '"phase":"full"' in h.capture()


def test_ck_audit_sink_failure_does_not_mask_refusal(h):
    h.audit_log_path.unlink()
    result = h.run([*_body(h, RULING_BODY), *OPEN_ARGS])
    assert result.returncode == 1
    _assert_fully_refused_before_network(h.capture())


def test_ck_module_missing_fails_closed(h):
    h.ck_py.unlink()
    result = h.run([*_body(h, "clean body\n"), *OPEN_ARGS])
    assert result.returncode != 0
    assert "closing-keyword guard unavailable" in result.stderr
    _assert_fully_refused_before_network(h.capture())


def test_ck_invalid_closes_value_fails_before_network(h):
    result = h.run([*_body(h, "clean body\n"), *OPEN_ARGS, "--closes", "abc"])
    assert result.returncode != 0
    _assert_fully_refused_before_network(h.capture())


def test_ck_git_log_failure_fails_closed(h):
    result = h.run(
        [*_body(h, "clean body\n"), *OPEN_ARGS],
        env_overrides={"GIT_LOG_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "guard failed" in result.stderr
    _assert_no_mint_no_push(h.capture())


def _bash32():
    for cand in (
        "/bin/bash",
        "/usr/bin/bash",
        shutil.which("bash3") or "",
        shutil.which("bash-3.2") or "",
    ):
        if not cand or not os.path.exists(cand):
            continue
        out = subprocess.run([cand, "-c", "echo $BASH_VERSINFO"], capture_output=True, text=True)
        if out.stdout.strip() == "3":
            return cand
    return None


def test_ck_empty_closes_array_under_bash32(h):
    bash32 = _bash32()
    if bash32 is None:
        pytest.skip("no bash 3.x available")
    result = h.run([*_body(h, "clean body\n"), *OPEN_ARGS], bash=bash32)
    assert result.returncode == 0, result.stderr


def test_push_source_is_pinned_sha_not_branch_name(h):
    """#1856 CWE-367: scan and push the same immutable commit."""
    other = "2222222222222222222222222222222222222222"
    result = h.run(
        [*_body(h, "clean body\n"), *OPEN_ARGS],
        env_overrides={"GIT_HEAD_SHA": other},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    push_line = [
        ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "x-access-token" in ln
    ][0]
    assert push_line.endswith(f" {other}:refs/heads/current-branch")
    assert "refs/heads/current-branch:refs/heads/" not in push_line
    assert _git_calls(cap, "log")[0].split()[-1] == f"{PINNED_BASE_SHA}..{other}"
    assert any("--no-replace-objects" in ln and "rev-parse" in ln for ln in cap.splitlines())


def test_scan_range_starts_at_pinned_base_sha(h):
    """#1856 CWE-367: the scanned range uses the base SHA pinned after fetch."""
    base = "4444444444444444444444444444444444444444"
    result = h.run(
        [*_body(h, "clean body\n"), *OPEN_ARGS],
        env_overrides={"GIT_BASE_SHA": base},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert _git_calls(cap, "log")[0].split()[-1] == f"{base}..{PINNED_SHA}"
    assert any(base in ln for ln in _git_calls(cap, "rev-list"))
    calls = cap.splitlines()
    pin = [i for i, ln in enumerate(calls) if "refs/remotes/origin/main" in ln][0]
    assert calls.index(_git_calls(cap, "fetch")[0]) < pin


def test_update_pr_scan_range_uses_pinned_shas(h):
    base = "4444444444444444444444444444444444444444"
    result = h.run(
        ["--update-pr", "42", "--base", "main", "--head", "current-branch", "--app", "worker"],
        env_overrides={"GIT_BASE_SHA": base},
    )
    assert result.returncode == 0, result.stderr
    assert _git_calls(h.capture(), "log")[0].split()[-1] == f"{base}..{PINNED_SHA}"


def test_merge_from_base_uses_pinned_base_sha(h):
    base = "4444444444444444444444444444444444444444"
    result = h.run(
        [*_body(h, "clean body\n"), *OPEN_ARGS],
        env_overrides={"GIT_BASE_SHA": base, "GIT_BEHIND_COUNT": "2"},
    )
    assert result.returncode == 0, result.stderr
    assert _git_calls(h.capture(), "merge")[0].split()[-1] == base
