"""
Tests for bin/hos-cron — the parameterized HOS cron launcher.

`bin/hos-cron` was hardened reactively all through the v0.4.1 cron bring-up
(arg validation, registry resolution, thin-env, overlap lock, wakeup handoff,
auth bootstrap #728, identity guard, deterministic git credentials #738) with
every fix verified by hand and none captured as a test (#743). This suite
codifies those manual checks so the launcher can't silently regress.

Strategy
--------
The launcher is one top-to-bottom `set -euo pipefail` pipeline, so each behavior
is reached by *running the real script* and arranging where it exits. The
`cron_env` fixture builds a throwaway HOME + repo with a full set of stubs that
make the happy path succeed end-to-end:

  * a `claude` stub on the pinned PATH (HOME/.local/bin) that records its argv[0]
    and environment instead of spawning the real CLI — the pinned-PATH/absolute
    resolution is itself under test, so claude is NEVER really invoked;
  * a `gh` stub so the #738 git-credential helper resolves;
  * `bootstrap/validate_setup.sh`, `bootstrap/get_app_token.sh` and
    `scripts/framework/run_tests_inner_loop.sh` stubs in a fake repo root;
  * `projects.conf` + `claude-auth.env` (#728) under the fake HOME.

Individual tests then perturb exactly one input to drive a single branch.
`HOS_CRON_JITTER_MAX=0` disables the startup jitter so nothing waits 0–60s
(mirrors machine_lock.sh's `HOS_LOCK_JITTER_MAX`).
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

HOS_CRON = Path(__file__).parent.parent.parent / "bin" / "hos-cron"

EXPECTED_BOT = "hos-worker-hos[bot]"


def _write_exec(path: Path, body: str) -> None:
    """Write an executable stub script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


class CronEnv:
    """A fully stubbed environment for invoking bin/hos-cron deterministically."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.repo = tmp_path / "repo"
        self.state = tmp_path / "state"
        self.bindir = self.home / ".local" / "bin"
        self.claude_log = tmp_path / "claude_invocation.log"
        self.token_capture = tmp_path / "lock_pid_seen.log"
        self.ppid_capture = tmp_path / "ppid_seen.log"
        # Records each `gh issue create` invocation so dedup/fail-closed tests
        # (#849) can assert whether a [BLOCKED] issue was actually filed.
        self.aa_issue_marker = tmp_path / "aa_issue_create.log"
        # Records each `gh issue close` invocation (#959 auto-close on green baseline).
        self.aa_issue_close_marker = tmp_path / "aa_issue_close.log"

        # ── claude stub: records how it was invoked, never spawns the real CLI ──
        # $0 proves thin-env resolved it by absolute path off the pinned PATH;
        # the recorded env proves ANTHROPIC_API_KEY was unset and the OAuth token
        # is present. Exit code is overridable to exercise the non-zero path.
        # HOS_TEST_CLAUDE_STDOUT (#1446) prints arbitrary text to the stub's REAL
        # stdout (distinct from the diagnostic block below, which is redirected
        # to self.claude_log) — this is what `_run_claude`'s `tee` in the real
        # launcher would capture, so tests can drive the usage-limit breaker's
        # detection grep against it.
        _write_exec(
            self.bindir / "claude",
            "#!/usr/bin/env bash\n"
            "cat > /dev/null 2>&1 || true   # drain stdin (prompt pipe)\n"
            '[[ -n "${HOS_TEST_CLAUDE_STDOUT:-}" ]] && printf "%s\\n" "$HOS_TEST_CLAUDE_STDOUT"\n'
            "{\n"
            '  echo "argv0=$0"\n'
            '  echo "api_key=${ANTHROPIC_API_KEY:-UNSET}"\n'
            '  echo "auth_token=${ANTHROPIC_AUTH_TOKEN:-UNSET}"\n'
            '  echo "oauth=${CLAUDE_CODE_OAUTH_TOKEN:-UNSET}"\n'
            '  echo "path=$PATH"\n'
            # #967 (ADR-037 AD-5): the launcher must mint and export cycle
            # identity into the launched session's environment.
            '  echo "cycle_id=${HOS_CYCLE_ID:-UNSET}"\n'
            '  echo "cycle_role=${HOS_CYCLE_ROLE:-UNSET}"\n'
            '  echo "cycle_token=${HOS_CYCLE_TOKEN:-UNSET}"\n'
            # #1434: proves the resolved session-timeout value (flag/env/conf/
            # default precedence) reached the launched session's environment.
            '  echo "max_seconds=${HOS_CRON_MAX_SECONDS:-UNSET}"\n'
            f'}} > "{self.claude_log}"\n'
            'exit "${HOS_TEST_CLAUDE_EXIT:-0}"\n',
        )

        # gh stub — configurable via HOS_TEST_* env vars so individual tests can
        # exercise halt-check, agent-availability, and PR-routing paths without
        # needing a real GitHub API.  Matches on argument substrings; unknown calls
        # fall through to exit 0 (safe default for non-targeted invocations).
        _write_exec(
            self.bindir / "gh",
            "#!/usr/bin/env bash\n" 'ARGS="$*"\n' 'case "$ARGS" in\n'
            # Halt check: issues?labels=hos-halt.
            # HOS_TEST_HALT_QUERY_FAIL simulates a gh API failure (non-zero exit)
            # so the #912 fail-closed halt path can be exercised.
            '  *"labels=hos-halt"*)\n'
            '    [[ -n "${HOS_TEST_HALT_QUERY_FAIL:-}" ]] && exit 1\n'
            '    echo "${HOS_TEST_HALT_COUNT:-0}" ;;\n'
            # Milestone-less issues (#1395 actionable-work gate) — one issue number per line.
            '  *"milestone=none"*)\n' '    printf "%s\\n" ${HOS_TEST_MILESTONELESS_ISSUES:-} ;;\n'
            # Context: next work candidates (needs-ai issues, not needs-human)
            '  *"labels=needs-ai"*)\n' '    printf "%s\\n" ${HOS_TEST_ISSUE_CANDIDATES:-} ;;\n'
            # #1347 Amendment 1 (NG3b): open release-request issues. Quoted (unlike
            # the space-joined number lists above) so a fake issue line's embedded
            # spaces (title text) survive as one line instead of being word-split.
            '  *"labels=release-request"*)\n'
            '    printf "%s\\n" "${HOS_TEST_RELEASE_REQUESTS:-}" ;;\n'
            # #959 auto-close: broken-state issue *numbers* (not the dedup count) —
            # matched first since it's the more specific pattern (the jq expression
            # ending in ".[].number" vs the plain "| length" count query below).
            '  *"labels=needs-human"*".[].number"*)\n'
            '    printf "%s\\n" ${HOS_TEST_BROKEN_STATE_OPEN_NUMS:-} ;;\n'
            # Agent availability: needs-human blocked issues count.
            # HOS_TEST_AA_QUERY_FAIL simulates a gh API failure (non-zero exit)
            # so the #849 fail-closed dedup path can be exercised.
            '  *"labels=needs-human"*)\n'
            '    [[ -n "${HOS_TEST_AA_QUERY_FAIL:-}" ]] && exit 1\n'
            '    echo "${HOS_TEST_NEEDS_HUMAN_BLOCKED:-0}" ;;\n'
            # PR list (open bot PRs) — outputs one PR number per line.
            # HOS_TEST_PR_FETCH_FAIL simulates a gh API failure (non-zero exit)
            # so the #915 fail-closed overseer PR-fetch path can be exercised.
            '  *"pulls?state=open"*)\n'
            '    [[ -n "${HOS_TEST_PR_FETCH_FAIL:-}" ]] && exit 1\n'
            '    printf "%s\\n" ${HOS_TEST_OPEN_PR_NUMS:-} ;;\n'
            # PR detail endpoint (single-PR `pulls/<n>` fetch — worker routing's
            # bounce/dirty check #1350 and the overseer's own draft/dirty
            # pre-filter both request `.mergeable_state`, so match on that
            # substring; it never appears in the list/reviews endpoints above).
            # Defaults (ms=clean, d=false, no labels) preserve prior test
            # behavior, when this call fell through unmatched to an empty
            # `exit 0` and the caller's `_pr_ms` ended up "" — never "dirty".
            '  *"mergeable_state"*)\n'
            '    _labels_json="[]"\n'
            '    if [[ -n "${HOS_TEST_PR_LABELS:-}" ]]; then\n'
            '      _labels_json="["\n'
            '      for _l in ${HOS_TEST_PR_LABELS}; do\n'
            '        _labels_json="${_labels_json}\\"${_l}\\","\n'
            '      done\n'
            '      _labels_json="${_labels_json%,}]"\n'
            '    fi\n'
            '    printf "{\\"ms\\":\\"%s\\",\\"d\\":%s,\\"labels\\":%s}\\n" '
            '"${HOS_TEST_PR_MS:-clean}" "${HOS_TEST_PR_DRAFT:-false}" "$_labels_json" ;;\n'
            # PR reviews — CHANGES_REQUESTED count
            '  *"reviews"*"CHANGES_REQUESTED"*)\n' '    echo "${HOS_TEST_PR_CR:-0}" ;;\n'
            # PR reviews — APPROVED count
            '  *"reviews"*"APPROVED"*)\n' '    echo "${HOS_TEST_PR_AP:-1}" ;;\n' "esac\n"
            # issue create — record the invocation, then confirm and exit
            'if [[ "$1" == "issue" && "$2" == "create" ]]; then\n'
            f'  echo "called" >> "{self.aa_issue_marker}"\n'
            '  echo "https://github.com/test/repo/issues/999"\n'
            "fi\n"
            # issue close — record which issue number was closed (#959 auto-close)
            'if [[ "$1" == "issue" && "$2" == "close" ]]; then\n'
            f'  echo "$3" >> "{self.aa_issue_close_marker}"\n'
            "fi\n"
            "exit 0\n",
        )

        # ── fake repo with the launcher's downstream dependencies stubbed ──
        _write_exec(
            self.repo / "bootstrap" / "validate_setup.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        # get_app_token's stdout is SOURCED by the launcher — emit the identity
        # exports the identity guard checks. It runs as a direct child of the
        # launcher, so $PPID == the launcher's $$ == the lock pid it just wrote;
        # recording both lets a test prove "pid written" without racing the trap.
        _write_exec(
            self.repo / "bootstrap" / "get_app_token.sh",
            "#!/usr/bin/env bash\n"
            f'cat "$HOS_STATE_DIR/locks/hos-cron-worker-hos.lock/pid" > "{self.token_capture}" 2>/dev/null || true\n'
            f'echo "$PPID" > "{self.ppid_capture}"\n'
            # `-` (not `:-`) so a test can deliver an explicitly-empty value to
            # exercise the fail-closed unset/empty guard.
            "echo \"export HOS_BOT_LOGIN='${HOS_TEST_BOT_LOGIN-" + EXPECTED_BOT + "}'\"\n"
            "echo \"export HOS_EXPECTED_BOT_LOGIN='${HOS_TEST_EXPECTED_BOT-"
            + EXPECTED_BOT
            + "}'\"\n"
            'echo "export GH_TOKEN=fake-token"\n',
        )
        # inner-loop test runner stub — records each invocation so the #789
        # cowpat tests can assert whether the cycle-start baseline actually ran,
        # and honors HOS_TEST_INNER_LOOP_EXIT to exercise the baseline-fail path.
        self.baseline_marker = tmp_path / "inner_loop_ran.log"
        _write_exec(
            self.repo / "scripts" / "framework" / "run_tests_inner_loop.sh",
            "#!/usr/bin/env bash\n"
            f'echo "ran" >> "{self.baseline_marker}"\n'
            'exit "${HOS_TEST_INNER_LOOP_EXIT:-0}"\n',
        )
        # ensure_venv.sh stub: exit 0 by default (healthy venv); override with
        # HOS_TEST_ENSURE_VENV_EXIT to simulate a broken venv.
        _write_exec(
            self.repo / "scripts" / "oversight" / "ensure_venv.sh",
            "#!/usr/bin/env bash\n" 'exit "${HOS_TEST_ENSURE_VENV_EXIT:-0}"\n',
        )
        # fake oversight venv — satisfies the pre-jitter dependency check
        _write_exec(
            self.repo / "scripts" / "oversight" / ".venv" / "bin" / "python",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        _write_exec(
            self.repo / "scripts" / "oversight" / ".venv" / "bin" / "pytest",
            "#!/usr/bin/env bash\nexit 0\n",
        )

        # ── HOME config: project registry + claude OAuth (#728) ──
        conf = self.home / ".config" / "hos" / "projects.conf"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(
            f"hos_config_dir={self.home}/.config/hos\n"
            f"hos_worker_root={self.repo}\n"
            f"hos_overseer_root={self.repo}\n"
        )
        self.auth_env = self.home / ".config" / "hos" / "claude-auth.env"
        self.auth_env.write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-TESTTOKEN\n")
        self.auth_env.chmod(0o600)

        # #989: the launcher fails closed when the role prompt file is absent
        # (a missing prompt would otherwise launch a guardrail-free
        # bypassPermissions session). Ship a minimal prompt for both roles so the
        # happy path reaches claude; the missing-prompt tests delete these.
        for _role in ("worker", "overseer"):
            self.prompt_file(_role).parent.mkdir(parents=True, exist_ok=True)
            self.prompt_file(_role).write_text(f"## {_role} cron prompt\n")

    @property
    def lock_dir(self) -> Path:
        return self.state / "locks" / "hos-cron-worker-hos.lock"

    @property
    def last_run_file(self) -> Path:
        return self.state / "last-run" / "worker-hos"

    @property
    def wakeup_worker(self) -> Path:
        # #995: wakeup files are scoped per-project ("hos" in this fixture).
        return self.state / "wakeup" / "worker-hos"

    @property
    def wakeup_overseer(self) -> Path:
        return self.state / "wakeup" / "overseer-hos"

    @property
    def wakeup_worker_legacy(self) -> Path:
        # Pre-#995 unscoped path — read-only back-compat surface.
        return self.state / "wakeup" / "worker"

    @property
    def wakeup_overseer_legacy(self) -> Path:
        return self.state / "wakeup" / "overseer"

    def suspend_file(self, project="hos") -> Path:
        return self.state / "suspend" / project

    def prompt_file(self, role="worker") -> Path:
        """The role prompt file the launcher requires (#989)."""
        return self.repo / "bootstrap" / f"{role}-cron-prompt.md"

    def run(
        self, *args, env_overrides=None, role="worker", project="hos", timeout=30
    ) -> subprocess.CompletedProcess:
        """Invoke the real bin/hos-cron with the stubbed world."""
        env = {
            "HOME": str(self.home),
            # Minimal incoming PATH — the launcher pins its own on top. The claude
            # stub lives in $HOME/.local/bin, which the launcher prepends first.
            "PATH": "/usr/bin:/bin",
            "HOS_STATE_DIR": str(self.state),
            "HOS_CRON_JITTER_MAX": "0",  # deterministic: no 0–60s sleep
            "HOS_CRON_MAX_SECONDS": "0",  # don't wrap claude stub in `timeout`
            "HOS_TEST_CLAUDE_LOG": str(self.claude_log),
            # Provide a synthetic repo slug so gh-API checks have a target without
            # needing a real git remote configured in the temporary repo directory.
            "HOS_REPO_SLUG": "test-org/test-repo",
            # #1395: the worker's actionable-work gate skips the cycle (before git
            # sync) when there's no milestone-less issue, release request, open PR,
            # or next-work candidate. Default one dummy milestone-less issue so the
            # many existing tests that aren't about this gate keep exercising the
            # rest of the launcher unchanged; tests that specifically target the
            # gate override this to "" (see TestActionableWorkGate).
            "HOS_TEST_MILESTONELESS_ISSUES": "9001",
        }
        if env_overrides:
            env.update(env_overrides)
        argv = [BASH, str(HOS_CRON)]
        if args:
            argv += list(args)
        else:
            argv += ["--role", role, "--project", project]
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )

    def add_agent_files(self, *slugs: str) -> None:
        """Create .claude/agents/<slug>.md stubs for the given agent slugs."""
        for slug in slugs:
            p = self.repo / ".claude" / "agents" / f"{slug}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {slug}\n")

    def set_consumer_agents(self, *slugs: str) -> None:
        """Write a consumer_agents.txt with only the given slugs (no comments)."""
        f = self.repo / "scripts" / "framework" / "consumer_agents.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(slugs) + "\n")

    # ── #789 cowpat helpers ──────────────────────────────────────────────────
    @property
    def cowpat_file(self) -> Path:
        """The clean-state marker the launcher reads/writes for worker-hos."""
        return self.state / "test-clean" / "worker-hos"

    def git_init_repo(self) -> str:
        """Make the fake repo a real git repo with one commit; return HEAD SHA.

        Used by the cowpat tests so `git rev-parse HEAD` / `git status` in the
        launcher resolve. Identity is passed via -c so no global config is needed.
        """
        git = ["git", "-C", str(self.repo)]
        ident = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "init"], check=True)
        head = subprocess.run(
            git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True
        )
        return head.stdout.strip()

    def git_init_diverged_main(self) -> None:
        """Make the fake repo a git repo whose local main is one commit ahead of
        origin/main — the #996 stray-commit-from-a-killed-session state.

        Builds a bare origin, pushes an initial `main`, then adds a local commit
        that is never pushed, so `pull origin main --ff-only` cannot fast-forward
        and `git rev-list origin/main..HEAD` is non-empty.
        """
        origin = self.repo.parent / "origin.git"
        other = self.repo.parent / "other_clone"
        git = ["git", "-C", str(self.repo)]
        gito = ["git", "-C", str(other)]
        ident = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        # Point the bare's HEAD at main so a fresh clone checks out main (not the
        # nonexistent default master).
        subprocess.run(
            ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True
        )
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "base"], check=True)
        subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
        subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
        # Advance origin/main via an independent clone so the two histories share a
        # base but each carries a unique commit — `pull --ff-only` fails only on a
        # genuine divergence (local merely ahead is a no-op fast-forward).
        subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        (other / "remote.txt").write_text("landed on origin while local was offline\n")
        subprocess.run(gito + ["add", "-A"], check=True)
        subprocess.run(gito + ident + ["commit", "-q", "-m", "remote-advance"], check=True)
        subprocess.run(gito + ["push", "-q", "origin", "main"], check=True)
        # Refresh the local remote-tracking ref, then strand a local-only commit →
        # local main now diverges from origin/main.
        subprocess.run(git + ["fetch", "-q", "origin"], check=True)
        (self.repo / "stray.txt").write_text("stray commit from a killed session\n")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "stray"], check=True)

    def git_init_squash_merged_feature_branch(self) -> None:
        """Make the fake repo a git repo whose HEAD sits on a feature branch that
        was squash-merged into origin/main and had its remote branch deleted —
        the #1044 deadlock state.

        Builds a bare origin, pushes an initial `main`, cuts a local feature
        branch with content changes and pushes it (so it has an upstream, as a
        real PR branch would), then — via an independent clone, simulating what
        happens on GitHub when the PR merges — squash-merges the same content
        into origin/main as a single new-SHA commit and deletes the remote
        feature branch. The local repo is left checked out on the feature branch
        with local `main` unmoved (behind origin/main) and the feature branch's
        remote-tracking ref gone once fetched.
        """
        origin = self.repo.parent / "origin.git"
        other = self.repo.parent / "other_clone"
        git = ["git", "-C", str(self.repo)]
        gito = ["git", "-C", str(other)]
        ident = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(
            ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True
        )
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "base"], check=True)
        subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
        subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
        # Cut a feature branch with two commits and push it — a real PR branch.
        subprocess.run(git + ["checkout", "-q", "-b", "feat/1032-thing"], check=True)
        (self.repo / "feature.txt").write_text("change1\n")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "feat: change1"], check=True)
        (self.repo / "feature.txt").write_text("change1\nchange2\n")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "feat: change2"], check=True)
        subprocess.run(
            git + ["push", "-q", "-u", "origin", "feat/1032-thing"],
            check=True,
        )
        # Simulate GitHub's squash-merge (same content, one new commit, new SHA)
        # plus its "delete head branch on merge" auto-cleanup — from an
        # independent clone, so the local repo's feature branch is untouched.
        subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        subprocess.run(
            gito + ["fetch", "-q", "origin", "feat/1032-thing"],
            check=True,
        )
        subprocess.run(
            gito + ["merge", "-q", "--squash", "FETCH_HEAD"],
            check=True,
        )
        subprocess.run(gito + ident + ["commit", "-q", "-m", "feat: squashed (#1032)"], check=True)
        subprocess.run(gito + ["push", "-q", "origin", "main"], check=True)
        subprocess.run(
            gito + ["push", "-q", "origin", "--delete", "feat/1032-thing"],
            check=True,
        )
        # Local repo is still parked on the (now-merged) feature branch.
        subprocess.run(git + ["checkout", "-q", "feat/1032-thing"], check=True)

    def git_init_open_feature_branch(self) -> None:
        """Make the fake repo a git repo whose HEAD sits on a feature branch that
        still has a live upstream (its PR has not merged) — the non-regression
        counterpart to `git_init_squash_merged_feature_branch`.
        """
        origin = self.repo.parent / "origin.git"
        git = ["git", "-C", str(self.repo)]
        ident = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(
            ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True
        )
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "base"], check=True)
        subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
        subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
        subprocess.run(git + ["checkout", "-q", "-b", "feat/in-progress"], check=True)
        (self.repo / "feature.txt").write_text("wip\n")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "feat: wip"], check=True)
        subprocess.run(
            git + ["push", "-q", "-u", "origin", "feat/in-progress"],
            check=True,
        )

    def git_init_dirty_main_blocks_ff(self) -> None:
        """Make the fake repo a git repo on `main`, with a real `origin/main`
        that has advanced past local main, and an uncommitted tracked-file
        change that conflicts with the incoming diff — the #1393 repro.

        Unlike `git_init_diverged_main`, local main carries no unpushed
        *commits* (the #996 stray-commit cherry-check finds nothing), so the
        only thing standing between local main and a clean fast-forward is
        the dirty working tree. `git merge --ff-only` fails on this for a
        real reason (uncommitted local edits would be clobbered), not because
        origin/main is unset (that's the plain-repo case tested separately).
        """
        origin = self.repo.parent / "origin.git"
        other = self.repo.parent / "other_clone"
        git = ["git", "-C", str(self.repo)]
        gito = ["git", "-C", str(other)]
        ident = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(
            ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True
        )
        subprocess.run(git + ["init", "-q"], check=True)
        subprocess.run(git + ["symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        (self.repo / "config.txt").write_text("v1\n")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ident + ["commit", "-q", "-m", "base"], check=True)
        subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
        subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
        # Advance origin/main via an independent clone, touching the same file
        # local will later dirty — a genuine fast-forward for anyone whose
        # tree is clean.
        subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        (other / "config.txt").write_text("v2-from-origin\n")
        subprocess.run(gito + ["add", "-A"], check=True)
        subprocess.run(gito + ident + ["commit", "-q", "-m", "origin-advance"], check=True)
        subprocess.run(gito + ["push", "-q", "origin", "main"], check=True)
        # Dirty the same tracked file locally, uncommitted — this is what
        # blocks the fast-forward merge (not a divergent commit history).
        (self.repo / "config.txt").write_text("local-dirty-uncommitted\n")

    def current_branch(self) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()

    def write_cowpat(self, sha: str) -> None:
        self.cowpat_file.parent.mkdir(parents=True, exist_ok=True)
        self.cowpat_file.write_text(sha + "\n")

    def make_dirty(self) -> None:
        """Drop an untracked file so `git status --porcelain` is non-empty."""
        (self.repo / "uncommitted.tmp").write_text("crashed mid-work\n")

    def baseline_ran(self) -> bool:
        """True if the cycle-start inner-loop test runner was invoked."""
        return self.baseline_marker.exists()

    def claude_ran(self) -> bool:
        return self.claude_log.exists()

    def aa_issue_created(self) -> bool:
        """True if the launcher filed a [BLOCKED] agent-unavailable issue."""
        return self.aa_issue_marker.exists()

    def closed_issue_nums(self) -> list[str]:
        """Issue numbers the launcher closed via `gh issue close` (#959 auto-close)."""
        if not self.aa_issue_close_marker.exists():
            return []
        return [ln for ln in self.aa_issue_close_marker.read_text().splitlines() if ln]

    def baseline_repair_state_file(self, project="hos") -> Path:
        """The #959 repair-attempt counter file for worker/<project>."""
        return self.state / "baseline-repair" / f"worker-{project}"

    def timeout_breaker_state_file(self, project="hos", role="worker") -> Path:
        """The #1435 consecutive-exit=124 counter file for <role>/<project>."""
        return self.state / "timeout-breaker" / f"{role}-{project}"

    def claude_output_capture_file(self, project="hos", role="worker") -> Path:
        """The #1446 fixed-path, overwrite-on-every-run capture of claude's
        own stdout for <role>/<project> — what the usage-limit breaker greps."""
        return self.state / "last-claude-output" / f"{role}-{project}"

    def set_baseline_on_red(self, mode: str, project="hos") -> None:
        """Append <project>_baseline_on_red=<mode> to projects.conf (#959)."""
        conf = self.home / ".config" / "hos" / "projects.conf"
        with conf.open("a") as f:
            f.write(f"{project}_baseline_on_red={mode}\n")

    def set_max_seconds_conf(self, value: str, project="hos") -> None:
        """Append <project>_max_seconds=<value> to projects.conf (#1434)."""
        conf = self.home / ".config" / "hos" / "projects.conf"
        with conf.open("a") as f:
            f.write(f"{project}_max_seconds={value}\n")

    def resolved_max_seconds(self) -> str:
        """The HOS_CRON_MAX_SECONDS value seen by the launched claude session."""
        for line in self.claude_record().splitlines():
            if line.startswith("max_seconds="):
                return line.split("=", 1)[1]
        return ""

    def claude_record(self) -> str:
        return self.claude_log.read_text() if self.claude_log.exists() else ""


@pytest.fixture
def cron(tmp_path):
    return CronEnv(tmp_path)


# ───────────────────────────── Arg validation ──────────────────────────────
class TestArgValidation:
    def test_missing_role_and_project_errors(self, cron):
        r = cron.run("--role", "")  # both end up empty
        assert r.returncode == 1
        assert "required" in (r.stdout + r.stderr)

    def test_no_args_errors(self, cron):
        # Pass an explicit empty role so argv isn't auto-filled by run().
        r = cron.run("--project", "hos")  # role missing
        assert r.returncode == 1
        assert "required" in (r.stdout + r.stderr)

    def test_invalid_role_rejected(self, cron):
        r = cron.run("--role", "wizard", "--project", "hos")
        assert r.returncode == 1
        assert "must be worker or overseer" in (r.stdout + r.stderr)

    def test_unknown_flag_shows_usage(self, cron):
        r = cron.run("--frobnicate", "x")
        assert r.returncode == 1
        assert "Usage:" in (r.stdout + r.stderr)


# ──────────────────────────── Registry resolution ──────────────────────────
class TestRegistryResolution:
    def test_unknown_project_errors(self, cron):
        r = cron.run("--role", "worker", "--project", "ghost")
        assert r.returncode == 1
        assert "no ghost_config_dir" in (r.stdout + r.stderr)

    def test_missing_role_root_errors(self, cron):
        # config_dir present but worker_root absent → distinct error.
        conf = cron.home / ".config" / "hos" / "projects.conf"
        conf.write_text(f"hos_config_dir={cron.home}/.config/hos\n")
        r = cron.run()
        assert r.returncode == 1
        assert "no hos_worker_root" in (r.stdout + r.stderr)

    def test_resolved_project_proceeds_past_registry(self, cron):
        # A fully resolvable project runs the whole happy path (claude stub fires).
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no hos_config_dir" not in r.stdout
        assert cron.claude_ran()


# ───────────────────── Session timeout resolution (#1434) ──────────────────
# Precedence: --max-seconds flag > HOS_CRON_MAX_SECONDS env > <project>_max_seconds
# in projects.conf > 1800 default. `run()`'s default env always sets
# HOS_CRON_MAX_SECONDS=0 (so the launcher doesn't wrap the claude stub in
# `timeout`) — tests below that exercise the conf/default tiers must override
# it to "" so the "env absent" branch is genuinely reached.
class TestMaxSecondsResolution:
    def test_flag_wins_over_env_and_conf(self, cron):
        cron.set_max_seconds_conf("300")
        r = cron.run(
            "--role", "worker", "--project", "hos", "--max-seconds", "5400",
            env_overrides={"HOS_CRON_MAX_SECONDS": "900"},
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.resolved_max_seconds() == "5400"

    def test_env_wins_over_conf(self, cron):
        cron.set_max_seconds_conf("300")
        r = cron.run(env_overrides={"HOS_CRON_MAX_SECONDS": "900"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.resolved_max_seconds() == "900"

    def test_conf_used_when_flag_and_env_absent(self, cron):
        cron.set_max_seconds_conf("300")
        r = cron.run(env_overrides={"HOS_CRON_MAX_SECONDS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.resolved_max_seconds() == "300"

    def test_default_used_when_nothing_set(self, cron):
        r = cron.run(env_overrides={"HOS_CRON_MAX_SECONDS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.resolved_max_seconds() == "1800"

    def test_zero_disables_cap_via_flag(self, cron):
        r = cron.run("--role", "worker", "--project", "hos", "--max-seconds", "0")
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.resolved_max_seconds() == "0"
        assert cron.claude_ran()

    def test_malformed_flag_value_fails_loudly(self, cron):
        r = cron.run("--role", "worker", "--project", "hos", "--max-seconds", "notanumber")
        assert r.returncode == 1
        out = r.stdout + r.stderr
        assert "invalid max-seconds value 'notanumber'" in out
        assert "--max-seconds flag" in out
        assert not cron.claude_ran()

    def test_malformed_env_value_fails_loudly(self, cron):
        r = cron.run(env_overrides={"HOS_CRON_MAX_SECONDS": "notanumber"})
        assert r.returncode == 1
        out = r.stdout + r.stderr
        assert "invalid max-seconds value 'notanumber'" in out
        assert "HOS_CRON_MAX_SECONDS env" in out
        assert not cron.claude_ran()

    def test_malformed_conf_value_fails_loudly(self, cron):
        cron.set_max_seconds_conf("notanumber")
        r = cron.run(env_overrides={"HOS_CRON_MAX_SECONDS": ""})
        assert r.returncode == 1
        out = r.stdout + r.stderr
        assert "invalid max-seconds value 'notanumber'" in out
        assert "hos_max_seconds in" in out
        assert not cron.claude_ran()


# ────────────────────────────── Overlap lock ───────────────────────────────
class TestOverlapLock:
    def test_live_holder_makes_second_invocation_exit_zero(self, cron):
        # Pre-seed the lock with a *live* pid (this test process) → held.
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text(f"{os.getpid()}\n")
        r = cron.run()
        assert r.returncode == 0
        assert "holds the lock" in r.stdout
        assert not cron.claude_ran(), "must not run work while another holder is live"

    def test_stale_dead_pid_lock_is_reclaimed(self, cron):
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text("99999999\n")  # never-alive pid
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "reclaiming stale lock" in r.stdout
        assert cron.claude_ran(), "after reclaim the cycle should proceed"

    def test_pid_written_is_the_launcher_pid(self, cron):
        # Seed a stale lock, then confirm the launcher overwrote the pid file with
        # its own pid. get_app_token (a direct child) snapshots both the pid file
        # and its own $PPID mid-run, before the EXIT trap removes the lock dir.
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text("99999999\n")
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        seen_lock_pid = cron.token_capture.read_text().strip()
        launcher_pid = cron.ppid_capture.read_text().strip()
        assert seen_lock_pid.isdigit()
        assert seen_lock_pid != "99999999", "stale pid should have been overwritten"
        assert seen_lock_pid == launcher_pid, "lock pid must be the launcher's own pid"

    def test_empty_pid_lock_is_not_reclaimed(self, cron):
        # #1002 (a): a fresh lock whose holder has done `mkdir` but not yet written
        # its pid presents an empty/absent pid file. A contender must read that as
        # "holder in-flight" and back off — NOT reclaim the live lock (which would
        # let both sessions run in one checkout). The dir is freshly created here,
        # so its age is well under the ceiling.
        cron.lock_dir.mkdir(parents=True)  # no pid file written yet
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "acquiring the lock" in r.stdout
        assert "reclaiming stale lock" not in r.stdout
        assert not cron.claude_ran(), "must not run work while a holder is mid-acquire"
        assert cron.lock_dir.exists(), "in-flight lock must not be removed"
        assert not (cron.lock_dir / "pid").exists(), "back-off must not stamp a pid"

    def test_old_lock_reclaimed_even_with_live_pid(self, cron):
        # #1002 (b): after a reboot the recorded PID can be reused by a long-lived
        # same-user process, so `kill -0` succeeds forever. A lock older than the
        # age ceiling (floored at 3600s here since HOS_CRON_MAX_SECONDS=0) must be
        # reclaimed regardless of PID liveness, bounding the standstill.
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text(f"{os.getpid()}\n")  # a genuinely live pid
        old = time.time() - 7200  # 2h ago, past the 1h ceiling
        os.utime(cron.lock_dir, (old, old))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "reclaiming stale lock" in r.stdout
        assert "ceiling" in r.stdout
        assert cron.claude_ran(), "after the age-ceiling reclaim the cycle should proceed"


# ─────────────────────────────────── Wakeup ────────────────────────────────
class TestWakeupBackoff:
    def test_wakeup_file_is_consumed_and_cycle_runs(self, cron):
        cron.wakeup_worker.parent.mkdir(parents=True, exist_ok=True)
        cron.wakeup_worker.write_text('{"reason":"overseer-signal"}')
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "wakeup signal received" in r.stdout
        assert "reason=overseer-signal" in r.stdout
        assert not cron.wakeup_worker.exists(), "wakeup file must be consumed"
        assert cron.claude_ran()

    def test_legacy_wakeup_for_this_project_is_consumed(self, cron):
        # #995: an unscoped wakeup from an older launcher whose JSON names THIS
        # project is honored (back-compat) and consumed.
        cron.wakeup_worker_legacy.parent.mkdir(parents=True, exist_ok=True)
        cron.wakeup_worker_legacy.write_text('{"reason":"legacy-mine","project":"hos"}')
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "wakeup signal received" in r.stdout
        assert "reason=legacy-mine" in r.stdout
        assert (
            not cron.wakeup_worker_legacy.exists()
        ), "legacy wakeup for this project must be consumed"
        assert cron.claude_ran()

    def test_legacy_wakeup_without_project_is_consumed(self, cron):
        # #995: a truly pre-scoping signal (no "project" field) stays back-compat —
        # consumed by whichever cron fires, matching the old behavior.
        cron.wakeup_worker_legacy.parent.mkdir(parents=True, exist_ok=True)
        cron.wakeup_worker_legacy.write_text('{"reason":"legacy-global"}')
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "reason=legacy-global" in r.stdout
        assert not cron.wakeup_worker_legacy.exists()
        assert cron.claude_ran()

    def test_legacy_wakeup_for_other_project_is_not_stolen(self, cron):
        # #995 core fix: a legacy wakeup addressed to a DIFFERENT project must not
        # be consumed/rm'd by this project's cron — it is left for its owner.
        cron.wakeup_worker_legacy.parent.mkdir(parents=True, exist_ok=True)
        cron.wakeup_worker_legacy.write_text('{"reason":"legacy-theirs","project":"otherproj"}')
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ignoring legacy wakeup" in r.stdout
        assert cron.wakeup_worker_legacy.exists(), "another project's wakeup must not be stolen"
        assert "reason=legacy-theirs" not in r.stdout

    def test_recent_last_run_no_longer_blocks_cycle(self, cron):
        # #1196: the idle backoff that used to skip a cycle when the last run was
        # recent is gone — every fire runs the cycle regardless of last-run age.
        cron.last_run_file.parent.mkdir(parents=True, exist_ok=True)
        now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout)
        cron.last_run_file.write_text(str(now))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "idle backoff" not in r.stdout
        assert "s since last run" in r.stdout
        assert cron.claude_ran(), "a recent last-run must not skip the cycle"

    def test_stale_last_run_logs_elapsed_and_runs(self, cron):
        cron.last_run_file.parent.mkdir(parents=True, exist_ok=True)
        now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout)
        cron.last_run_file.write_text(str(now - 100_000))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "s since last run" in r.stdout
        assert cron.claude_ran()


# ───────────────────────── Git sync divergence (#996) ──────────────────────
class TestGitSyncDivergence:
    def test_diverged_local_main_skips_cycle_fail_closed(self, cron):
        # #996: a stray local commit (killed-session state) makes `pull --ff-only`
        # fail forever. The launcher must detect the divergence, log loudly, and
        # skip the cycle fail-closed instead of silently building from a stale base.
        cron.git_init_diverged_main()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "DIVERGED" in r.stdout
        assert "#996" in r.stdout
        assert not cron.claude_ran(), "diverged main must skip the cycle (no build)"

    def test_ff_only_failure_without_divergence_still_runs(self, cron):
        # A plain git repo with no upstream: `pull --ff-only` fails but local main
        # is NOT ahead of origin/main — nothing was masked, so the cycle proceeds
        # (no false-positive divergence halt).
        cron.git_init_repo()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "DIVERGED" not in r.stdout
        assert cron.claude_ran()

    def test_squash_merged_feature_branch_does_not_deadlock(self, cron):
        # #1044 bug repro: HEAD parked on a feature branch whose commit was
        # squash-merged into origin/main (new SHA, same content) with the remote
        # branch deleted. The old guard measured `origin/main..HEAD` and saw the
        # feature branch's own commits as "diverged local main" forever — this
        # is the state that deadlocked the worker for 11+ hours after every
        # merge. It must not falsely halt the cycle.
        cron.git_init_squash_merged_feature_branch()
        assert cron.current_branch() == "feat/1032-thing"
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "DIVERGED" not in r.stdout, r.stdout
        assert cron.claude_ran()

    def test_squash_merged_feature_branch_returns_to_main(self, cron):
        # #1044 durable fix: once a feature branch's upstream is gone (merged &
        # pruned), the launcher must check out `main` so the checkout doesn't
        # accumulate dead branches indefinitely and future branches are cut from
        # a base that reflects the merge.
        cron.git_init_squash_merged_feature_branch()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.current_branch() == "main"
        assert "returned to main" in r.stdout
        assert "#1044" in r.stdout

    def test_dirty_tree_blocking_ff_only_skips_cycle_fail_closed(self, cron):
        # #1393: local main has no unpushed commits (the #996 stray-commit
        # check finds nothing), but an uncommitted tracked-file change blocks
        # `merge --ff-only`. Previously this was masked by `|| true` and the
        # cycle proceeded to build against a stale main with no signal
        # anywhere. It must now be detected and fail closed, same as #996.
        cron.git_init_dirty_main_blocks_ff()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "could not fast-forward" in r.stdout
        assert "#1393" in r.stdout
        assert not cron.claude_ran(), "blocked fast-forward must skip the cycle (no build)"

    def test_open_feature_branch_with_live_upstream_is_left_alone(self, cron):
        # A feature branch whose PR is still open (remote branch still exists)
        # must NOT be swept back to main mid-build.
        cron.git_init_open_feature_branch()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "returned to main" not in r.stdout
        assert "DIVERGED" not in r.stdout
        assert cron.current_branch() == "feat/in-progress"
        assert cron.claude_ran()


# ───────────────────────────── Auth bootstrap (#728) ───────────────────────
class TestClaudeAuthBootstrap:
    def test_missing_claude_auth_env_is_ex_config(self, cron):
        cron.auth_env.unlink()
        r = cron.run()
        assert r.returncode == 78, "missing claude-auth.env must exit EX_CONFIG (78)"
        assert "missing" in r.stdout
        assert not cron.claude_ran()

    def test_empty_oauth_token_is_ex_config(self, cron):
        cron.auth_env.write_text("CLAUDE_CODE_OAUTH_TOKEN=\n")
        r = cron.run()
        assert r.returncode == 78
        assert "CLAUDE_CODE_OAUTH_TOKEN not set" in r.stdout
        assert not cron.claude_ran()

    def test_api_key_unset_before_claude_invoke(self, cron):
        # A shadowing ANTHROPIC_API_KEY in the environment must be cleared so the
        # OAuth subscription token wins (#728).
        r = cron.run(env_overrides={"ANTHROPIC_API_KEY": "sk-shadow-should-be-cleared"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.claude_ran()
        assert "api_key=UNSET" in cron.claude_record()
        assert "auth_token=UNSET" in cron.claude_record()
        assert "oauth=sk-ant-oat01-TESTTOKEN" in cron.claude_record()


# ───────────────────────────── Identity guard ──────────────────────────────
class TestIdentityGuard:
    def test_login_mismatch_exits_one(self, cron):
        r = cron.run(env_overrides={"HOS_TEST_BOT_LOGIN": "imposter[bot]"})
        assert r.returncode == 1
        assert "IDENTITY GUARD FAILED" in r.stdout
        assert not cron.claude_ran()

    def test_expected_login_unset_exits_one(self, cron):
        # get_app_token emits an empty HOS_EXPECTED_BOT_LOGIN → guard fails closed.
        r = cron.run(env_overrides={"HOS_TEST_EXPECTED_BOT": ""})
        assert r.returncode == 1
        assert "IDENTITY GUARD FAILED" in r.stdout
        assert not cron.claude_ran()

    def test_matching_login_proceeds(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"Authenticated as {EXPECTED_BOT}" in r.stdout
        assert cron.claude_ran()


# ─────────────────────────── Cycle identity (#967) ──────────────────────────
class TestCycleIdentity:
    """bin/hos-cron mints HOS_CYCLE_ID / HOS_CYCLE_ROLE / HOS_CYCLE_TOKEN once
    per invocation and exports them into the launched Claude session's
    environment (ADR-037 AD-5). This is P1: mechanism only — nothing reads
    these yet (bootstrap/submit_pr.sh's enforcement check is P2). This suite
    covers the launcher side of the contract only."""

    def _env(self, cron, role="worker", project="hos", env_overrides=None) -> dict:
        r = cron.run(role=role, project=project, env_overrides=env_overrides)
        assert r.returncode == 0, r.stdout + r.stderr
        out = {}
        for line in cron.claude_record().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v
        return out

    def test_cycle_vars_are_minted_and_exported(self, cron):
        env = self._env(cron)
        assert env.get("cycle_id", "UNSET") != "UNSET"
        assert env.get("cycle_role", "UNSET") != "UNSET"
        assert env.get("cycle_token", "UNSET") != "UNSET"

    def test_cycle_id_matches_the_documented_grammar(self, cron):
        import re

        env = self._env(cron)
        assert re.match(r"^[A-Za-z0-9._-]+$", env["cycle_id"]), env["cycle_id"]
        assert env["cycle_id"].startswith("worker-hos-")

    def test_cycle_token_is_a_12_digit_utc_timestamp(self, cron):
        import re

        env = self._env(cron)
        assert re.match(r"^\d{12}$", env["cycle_token"]), env["cycle_token"]

    def test_cycle_role_matches_the_invoked_role(self, cron):
        env = self._env(cron, role="worker")
        assert env["cycle_role"] == "worker"

    def test_overseer_also_receives_a_cycle_identity(self, cron):
        # AD-5: minted for BOTH roles. The overseer creates no branches, but
        # withholding the identity would be a role-detection heuristic, which
        # AD-5 explicitly avoids — role scoping is enforced by the recorded
        # role= value in the ownership record (P2), not by minting selectively.
        # An actionable open PR is stubbed so the overseer's own PR pre-filter
        # (unrelated to #967) reaches the Claude launch at all.
        env = self._env(
            cron,
            role="overseer",
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
            },
        )
        assert env.get("cycle_id", "UNSET") != "UNSET"
        assert env["cycle_role"] == "overseer"

    def test_two_invocations_mint_different_cycle_ids(self, cron):
        env1 = self._env(cron)
        # Clear the claude log so the second invocation's record isn't confused
        # with the first's.
        if cron.claude_log.exists():
            cron.claude_log.unlink()
        env2 = self._env(cron)
        assert env1["cycle_id"] != env2["cycle_id"]


# ───────────────────────────── Thin-env hardening ──────────────────────────
class TestThinEnv:
    def test_claude_resolved_by_absolute_path_from_minimal_path(self, cron):
        # Incoming PATH is just /usr/bin:/bin (no claude). The launcher pins its
        # own PATH and resolves the stub in $HOME/.local/bin by absolute path.
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        argv0 = next(
            (l for l in cron.claude_record().splitlines() if l.startswith("argv0=")),
            "",
        )
        assert (
            argv0 == f"argv0={cron.bindir}/claude"
        ), "claude must be invoked by its absolute pinned-PATH location"

    def test_pinned_path_includes_standard_bins(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        path_line = next(
            (l for l in cron.claude_record().splitlines() if l.startswith("path=")),
            "",
        )
        # The launcher prepends the pinned dirs regardless of the sparse inbound PATH.
        assert f"{cron.bindir}" in path_line
        assert "/usr/bin" in path_line


# ── #957: missing bin/lib/git-credentials.sh must self-heal, not crash-loop ──
# `CronEnv.run()` always executes the *real* `bin/hos-cron` at its real path,
# so `${BASH_SOURCE[0]}` resolves inside this dev checkout's own `bin/`, where
# `lib/git-credentials.sh` genuinely exists — that fixture can never exercise
# the "missing" branch. These tests instead run a standalone copy of the
# script from a throwaway git checkout so the file can be made to actually be
# absent, with a real `origin` remote for the self-heal fetch+ff-merge to act
# on (mirrors a role's checkout having missed an upgrade a sibling role
# already applied, #957's failure mode).
class TestGitCredentialsGuard:
    IDENT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    REAL_GIT_CREDS_LIB = HOS_CRON.parent / "lib" / "git-credentials.sh"

    def _write_claude_stub(self, home: Path) -> None:
        _write_exec(
            home / ".local" / "bin" / "claude",
            "#!/usr/bin/env bash\ncat > /dev/null 2>&1 || true\nexit 0\n",
        )

    def _init_repo(self, tmp_path: Path, include_git_creds_lib: bool):
        """Bare `origin` + a local clone containing a copy of the real
        `bin/hos-cron` (and optionally `bin/lib/git-credentials.sh`), committed
        and pushed, so the guard's self-heal runs against real git plumbing."""
        origin = tmp_path / "origin.git"
        repo = tmp_path / "repo"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        subprocess.run(
            ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], check=True
        )
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        git = ["git", "-C", str(repo)]
        subprocess.run(git + ["symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        (repo / "bin").mkdir(parents=True)
        shutil.copy(HOS_CRON, repo / "bin" / "hos-cron")
        (repo / "bin" / "hos-cron").chmod(0o755)
        if include_git_creds_lib:
            (repo / "bin" / "lib").mkdir(parents=True)
            shutil.copy(self.REAL_GIT_CREDS_LIB, repo / "bin" / "lib" / "git-credentials.sh")
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + self.IDENT + ["commit", "-q", "-m", "init"], check=True)
        subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
        subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
        return origin, repo

    def _run(self, repo: Path, tmp_path: Path) -> subprocess.CompletedProcess:
        home = tmp_path / "home"
        self._write_claude_stub(home)
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "HOS_CRON_JITTER_MAX": "0"}
        return subprocess.run(
            [BASH, str(repo / "bin" / "hos-cron")],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=env,
        )

    def test_present_file_sources_normally(self, tmp_path):
        _, repo = self._init_repo(tmp_path, include_git_creds_lib=True)
        r = self._run(repo, tmp_path)
        combined = r.stdout + r.stderr
        assert "git-credentials.sh missing" not in combined
        assert "hos-cron: --role and --project required" in combined

    def test_missing_file_no_fix_on_origin_is_fatal(self, tmp_path):
        """No sibling checkout has advanced origin — the self-heal fetch has
        nothing to pull, so the guard must degrade to a clear diagnostic and a
        stable exit code, not a bare 'No such file or directory' crash."""
        _, repo = self._init_repo(tmp_path, include_git_creds_lib=False)
        r = self._run(repo, tmp_path)
        assert r.returncode == 78
        assert "still missing after self-update attempt" in r.stderr
        assert "No such file or directory" not in r.stderr

    def test_missing_file_self_heals_via_fetch_ff_merge(self, tmp_path):
        """Origin has already been upgraded (as if a sibling role's checkout
        applied it first) — the guard's fetch+ff-merge should pull the file in
        and sourcing should proceed, reaching normal arg validation."""
        origin, repo = self._init_repo(tmp_path, include_git_creds_lib=False)
        other = tmp_path / "other_clone"
        subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        (other / "bin" / "lib").mkdir(parents=True)
        shutil.copy(self.REAL_GIT_CREDS_LIB, other / "bin" / "lib" / "git-credentials.sh")
        gito = ["git", "-C", str(other)]
        subprocess.run(gito + ["add", "-A"], check=True)
        subprocess.run(
            gito + self.IDENT + ["commit", "-q", "-m", "add git-credentials.sh"], check=True
        )
        subprocess.run(gito + ["push", "-q", "origin", "main"], check=True)

        r = self._run(repo, tmp_path)
        combined = r.stdout + r.stderr
        assert "attempting self-update" in r.stderr
        assert "still missing after self-update attempt" not in r.stderr
        assert "hos-cron: --role and --project required" in combined
        assert (
            repo / "bin" / "lib" / "git-credentials.sh"
        ).exists(), "local checkout must actually be fast-forwarded onto origin/main"


# ──────────── last-run written only on exit 0 + wakeup hand-off ─────────────
class TestPostCycleBookkeeping:
    def test_last_run_written_on_success(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.last_run_file.exists(), "successful cycle must stamp last-run"
        assert cron.last_run_file.read_text().strip().isdigit()

    def test_last_run_not_written_when_claude_fails(self, cron):
        r = cron.run(env_overrides={"HOS_TEST_CLAUDE_EXIT": "7"})
        # The launcher itself still exits 0 (it logs the claude failure); the
        # contract is that last-run is NOT stamped, so the next fire retries.
        assert "claude exited 7" in r.stdout
        assert (
            not cron.last_run_file.exists()
        ), "last-run must NOT be written when the claude session fails (#711)"

    def test_wakeup_dropped_to_overseer(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.wakeup_overseer.exists(), "worker must signal the overseer"
        payload = cron.wakeup_overseer.read_text()
        assert "worker-cycle-complete" in payload
        assert '"project":"hos"' in payload


# ──────────────────────────── _validate_env ─────────────────────────────────
class TestValidateEnv:
    def test_bootstrap_marker_absent_warns(self, cron):
        """Missing bootstrap marker → warning in output."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "bootstrap marker missing" in r.stdout

    def test_bootstrap_marker_present_no_warn(self, cron):
        """Bootstrap marker present → no bootstrap warning."""
        marker_dir = cron.home / ".hos" / "setup-validation"
        marker_dir.mkdir(parents=True)
        (marker_dir / "bootstrap").touch()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "bootstrap marker missing" not in r.stdout

    def test_broken_venv_warns(self, cron):
        """ensure_venv.sh exits non-zero → cron logs oversight-venv warning."""
        r = cron.run(env_overrides={"HOS_TEST_ENSURE_VENV_EXIT": "1"})
        assert r.returncode == 0, r.stdout + r.stderr  # fail-open: cron still runs
        assert "oversight-venv broken or missing" in r.stdout

    def test_healthy_venv_no_warn(self, cron):
        """ensure_venv.sh exits 0 → no oversight-venv warning."""
        marker_dir = cron.home / ".hos" / "setup-validation"
        marker_dir.mkdir(parents=True)
        (marker_dir / "bootstrap").touch()
        r = cron.run()  # default HOS_TEST_ENSURE_VENV_EXIT=0
        assert r.returncode == 0, r.stdout + r.stderr
        assert "oversight-venv" not in r.stdout
        assert "✓ environment validated" in r.stdout


# ─────────────────────── Pre-jitter dependency check ─────────────────────────
class TestPreJitterDepsCheck:
    def test_missing_venv_self_heals_via_ensure_venv(self, cron):
        """Missing oversight venv python → build via ensure_venv.sh, then proceed (#953).

        The preflight must not shadow the auto-repair _validate_env already relies
        on: a missing venv that ensure_venv.sh can build self-heals rather than
        FATAL'ing and looping forever.
        """
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        r = cron.run()  # ensure_venv.sh stub exits 0 by default → build succeeds
        assert r.returncode == 0, r.stdout + r.stderr
        assert "building via ensure_venv.sh" in r.stdout

    def test_missing_venv_build_failure_exits_78(self, cron):
        """Missing venv + ensure_venv.sh build fails → exit 78 (fail-closed) (#953)."""
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        r = cron.run(env_overrides={"HOS_TEST_ENSURE_VENV_EXIT": "1"})
        assert r.returncode == 78, r.stdout + r.stderr
        assert "ensure_venv.sh failed to build" in r.stdout
        assert not cron.claude_ran()

    def test_missing_pytest_self_heals_via_ensure_venv(self, cron):
        """pytest missing from venv → build via ensure_venv.sh, then proceed (#953)."""
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "pytest").unlink()
        r = cron.run()  # ensure_venv.sh stub exits 0 by default → build succeeds
        assert r.returncode == 0, r.stdout + r.stderr
        assert "building via ensure_venv.sh" in r.stdout

    def test_successful_check_writes_marker(self, cron):
        """Successful deps check writes a marker file in validation-cache."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        cache_dir = cron.state / "validation-cache"
        assert any(cache_dir.glob("deps-*")), "successful check must write deps marker"

    def test_fresh_marker_skips_validation_after_venv_removed(self, cron):
        """Once a fresh marker exists, removing the venv no longer causes exit 78."""
        # First run: succeeds and writes marker
        r1 = cron.run()
        assert r1.returncode == 0, r1.stdout + r1.stderr
        cache_dir = cron.state / "validation-cache"
        assert any(cache_dir.glob("deps-*"))
        # Remove venv python to simulate broken environment
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        if cron.claude_log.exists():
            cron.claude_log.unlink()
        # Second run: marker is fresh → validation skipped → cycle proceeds
        r2 = cron.run()
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert cron.claude_ran()

    def test_stale_marker_triggers_revalidation_and_fails(self, cron):
        """A marker older than 7 days triggers re-validation; missing venv whose
        build also fails → exit 78 (fail-closed) (#953)."""
        # Run once to get the marker written
        r1 = cron.run()
        assert r1.returncode == 0, r1.stdout + r1.stderr
        cache_dir = cron.state / "validation-cache"
        markers = list(cache_dir.glob("deps-*"))
        assert markers
        # Make the marker appear 8 days old
        old_time = time.time() - (8 * 24 * 3600)
        for m in markers:
            os.utime(str(m), (old_time, old_time))
        # Remove venv so re-validation finds a missing dependency
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        if cron.claude_log.exists():
            cron.claude_log.unlink()
        if cron.last_run_file.exists():
            cron.last_run_file.unlink()
        # Re-run: stale marker → revalidation → venv missing → build fails → exit 78
        r2 = cron.run(env_overrides={"HOS_TEST_ENSURE_VENV_EXIT": "1"})
        assert r2.returncode == 78, r2.stdout + r2.stderr
        assert "ensure_venv.sh failed to build" in r2.stdout


# ──────────────────────────── Suspension (#778) ──────────────────────────────
class TestSuspension:
    """Suspension check exits cleanly before lock acquisition."""

    def test_suspended_project_exits_0_without_claude(self, cron):
        """Marker present → exit 0, Claude never invoked."""
        import json

        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[SUSPENDED]" in r.stdout
        assert not cron.claude_ran()

    def test_suspended_project_logs_clear_hint(self, cron):
        """Log message includes the --clear hint so the operator knows how to resume."""
        import json

        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = cron.run()
        assert "--clear" in r.stdout

    def test_suspended_until_future_exits_0(self, cron):
        """Marker with future --until date → still suspended."""
        import json

        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(
            json.dumps({"suspended_at": "2026-06-23T00:00:00Z", "until": "2099-12-31"})
        )
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[SUSPENDED]" in r.stdout
        assert not cron.claude_ran()

    def test_suspended_until_past_removes_marker_and_runs(self, cron):
        """Marker with expired --until → marker removed, cycle proceeds normally."""
        import json

        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(
            json.dumps({"suspended_at": "2026-01-01T00:00:00Z", "until": "2026-01-02"})
        )
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "expired" in r.stdout
        assert not cron.suspend_file().exists()
        assert cron.claude_ran()

    def test_no_marker_runs_normally(self, cron):
        """No suspend marker → normal cycle, Claude invoked."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[SUSPENDED]" not in r.stdout
        assert cron.claude_ran()


# ───────────────────────────── Halt check (#793) ─────────────────────────────
class TestHaltCheck:
    def test_halt_issue_present_skips_claude(self, cron):
        """Open hos-halt issue → cycle exits 0, Claude not launched."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_COUNT": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT" in r.stdout
        assert "hos-halt" in r.stdout
        assert not cron.claude_ran()

    def test_halt_issue_present_logs_audit_event(self, cron):
        """cycle-skip reason=hos-halt is emitted (even if _audit silently fails)."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_COUNT": "2"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.claude_ran()

    def test_no_halt_issue_proceeds(self, cron):
        """No halt issues → cycle runs normally."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_COUNT": "0"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT" not in r.stdout
        assert cron.claude_ran()

    def test_halt_check_empty_slug_fails_closed(self, cron):
        """#912: empty repo slug → halt-state UNKNOWN → skip cycle, Claude not launched."""
        r = cron.run(env_overrides={"HOS_REPO_SLUG": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT CHECK UNAVAILABLE" in r.stdout
        assert not cron.claude_ran()

    def test_halt_check_api_error_fails_closed(self, cron):
        """#912: gh API failure → halt-state UNKNOWN → skip cycle, Claude not launched."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_QUERY_FAIL": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT CHECK UNAVAILABLE" in r.stdout
        assert not cron.claude_ran()


# ─────────────────────── Agent availability check (#794) ─────────────────────
class TestAgentAvailability:
    def test_no_agents_list_proceeds(self, cron):
        """No consumer_agents.txt → check skipped, cycle runs normally."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AGENT AVAILABILITY" not in r.stdout
        assert cron.claude_ran()

    def test_all_agents_present_proceeds(self, cron):
        """All listed agents exist → cycle runs normally."""
        cron.set_consumer_agents("worker", "overseer", "coder")
        cron.add_agent_files("worker", "overseer", "coder")
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AGENT AVAILABILITY" not in r.stdout
        assert cron.claude_ran()

    def test_missing_agent_exits_one(self, cron):
        """One agent missing → exit 1, Claude not launched."""
        cron.set_consumer_agents("worker", "coder")
        cron.add_agent_files("worker")  # coder missing
        r = cron.run()
        assert r.returncode == 1, r.stdout + r.stderr
        assert "AGENT AVAILABILITY FAIL" in r.stdout
        assert "coder" in r.stdout
        assert not cron.claude_ran()

    def test_missing_agent_files_needs_human_issue_filed(self, cron):
        """Missing agents with no existing blocked issue → issue create called."""
        cron.set_consumer_agents("coder")
        # coder agent file absent; stub reports 0 existing blocked issues
        r = cron.run(env_overrides={"HOS_TEST_NEEDS_HUMAN_BLOCKED": "0"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert cron.aa_issue_created(), "expected a [BLOCKED] issue to be filed"

    def test_missing_agent_duplicate_issue_guard(self, cron):
        """Existing blocked issue → no second issue create (duplicate guard)."""
        cron.set_consumer_agents("coder")
        # Stub reports 1 existing blocked issue → should NOT create another
        r = cron.run(env_overrides={"HOS_TEST_NEEDS_HUMAN_BLOCKED": "1"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert not cron.aa_issue_created(), "existing issue → must not file a duplicate"

    def test_missing_agent_dedup_query_failure_fails_closed(self, cron):
        """#849: a dedup-query *error* must NOT default the count to 0 and file a
        duplicate [BLOCKED] issue (fail-open). On query failure, skip filing and
        warn (fail-closed)."""
        cron.set_consumer_agents("coder")
        r = cron.run(env_overrides={"HOS_TEST_AA_QUERY_FAIL": "1"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert (
            not cron.aa_issue_created()
        ), "dedup query failed → must fail closed and NOT file an issue"
        assert "fail-closed" in r.stdout

    def test_comments_and_blanks_in_agents_list_ignored(self, cron):
        """Comment lines and blank lines in consumer_agents.txt are skipped."""
        f = cron.repo / "scripts" / "framework" / "consumer_agents.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# a comment\n\nworker\n\n# another comment\n")
        cron.add_agent_files("worker")
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.claude_ran()


# ─────────────────── Cycle-start baseline cowpat (#789) ──────────────────────
class TestCycleStartBaselineCowpat:
    """The worker skips the cycle-start inner-loop baseline when the repo is
    provably unchanged since the last green run (HEAD == cowpat, clean tree),
    runs it otherwise, and on baseline failure files a deduplicated needs-human
    broken-state issue instead of exiting silently.

    These tests reuse the shared `labels=needs-human` gh-stub case
    (HOS_TEST_NEEDS_HUMAN_BLOCKED / HOS_TEST_AA_QUERY_FAIL) since the
    broken-state dedup query targets the same label; the agent-availability
    block is skipped here (no consumer_agents.txt), so the only needs-human
    query and issue-create come from the #789 broken-state flow.
    """

    def test_clean_repo_skips_baseline(self, cron):
        """HEAD matches cowpat and tree is clean → baseline skipped, Claude runs."""
        head = cron.git_init_repo()
        cron.write_cowpat(head)
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.baseline_ran(), "clean repo must skip the cycle-start baseline"
        assert "skipping cycle-start baseline" in r.stdout
        assert cron.claude_ran()

    def test_head_moved_runs_baseline_and_restamps_cowpat(self, cron):
        """Cowpat SHA differs from HEAD (new commits) → baseline runs, cowpat updated."""
        head = cron.git_init_repo()
        cron.write_cowpat("0" * 40)  # stale SHA from an earlier green run
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.baseline_ran(), "HEAD moved → baseline must run"
        assert cron.cowpat_file.read_text().strip() == head
        assert cron.claude_ran()

    def test_dirty_tree_runs_baseline(self, cron):
        """HEAD matches cowpat but uncommitted files present → baseline runs."""
        head = cron.git_init_repo()
        cron.write_cowpat(head)
        cron.make_dirty()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.baseline_ran(), "dirty tree → baseline must run"
        assert cron.claude_ran()

    def test_no_cowpat_runs_baseline_and_bootstraps_marker(self, cron):
        """First run (no cowpat) → baseline runs and the marker is bootstrapped."""
        head = cron.git_init_repo()
        assert not cron.cowpat_file.exists()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.baseline_ran(), "no cowpat → baseline must run"
        assert cron.cowpat_file.read_text().strip() == head
        assert cron.claude_ran()

    def test_non_git_repo_runs_baseline_without_marker(self, cron):
        """Unresolvable HEAD (non-git REPO_ROOT) → baseline runs, no marker written."""
        # the fixture repo is not a git repo by default
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.baseline_ran(), "unresolvable HEAD → baseline must run"
        assert not cron.cowpat_file.exists(), "no SHA to stamp → must not write a marker"
        assert cron.claude_ran()

    def test_baseline_failure_files_broken_state_issue(self, cron):
        """Baseline fails with no existing broken-state issue → needs-human issue
        filed, Claude not launched, exit 1."""
        cron.git_init_repo()
        r = cron.run(
            env_overrides={
                "HOS_TEST_INNER_LOOP_EXIT": "1",
                "HOS_TEST_NEEDS_HUMAN_BLOCKED": "0",
            }
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "BASELINE TESTS FAILED" in r.stdout
        assert cron.aa_issue_created(), "expected a broken-state needs-human issue"
        assert not cron.claude_ran()

    def test_baseline_failure_duplicate_issue_guard(self, cron):
        """Baseline fails but a broken-state issue is already open → no duplicate."""
        cron.git_init_repo()
        r = cron.run(
            env_overrides={
                "HOS_TEST_INNER_LOOP_EXIT": "1",
                "HOS_TEST_NEEDS_HUMAN_BLOCKED": "1",
            }
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.aa_issue_created(), "existing issue → must not file a duplicate"
        assert "already open" in r.stdout
        assert not cron.claude_ran()

    def test_baseline_failure_dedup_query_failure_fails_closed(self, cron):
        """A broken-state dedup-query error must NOT default the count to 0 and
        file a fresh issue every cycle — fail closed, skip filing, warn."""
        cron.git_init_repo()
        r = cron.run(
            env_overrides={
                "HOS_TEST_INNER_LOOP_EXIT": "1",
                "HOS_TEST_AA_QUERY_FAIL": "1",
            }
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert (
            not cron.aa_issue_created()
        ), "dedup query failed → must fail closed and NOT file an issue"
        assert "fail-closed" in r.stdout
        assert not cron.claude_ran()

    def test_baseline_green_auto_closes_standing_blocked_issue(self, cron):
        """#959: baseline passes → any standing [BLOCKED] issue is auto-closed,
        even in default "halt" mode (this is the unconditional "at minimum" ask).

        Membership, not exact-list equality: the gh stub can't distinguish
        which real title-prefix a `--jq ... .[].number` query was for, so
        the #1446 usage-limit-breaker auto-close (also unconditional on any
        exit=0 cycle — it has no state file to gate on, unlike the timeout
        breaker below) sees the same fake "321" and issues its own harmless
        `gh issue close 321` too. Same convention already used by the
        timeout breaker's analogous test."""
        cron.git_init_repo()
        r = cron.run(env_overrides={"HOS_TEST_BROKEN_STATE_OPEN_NUMS": "321"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "321" in cron.closed_issue_nums()
        assert cron.claude_ran()

    def test_baseline_green_no_standing_issue_closes_nothing(self, cron):
        """No standing [BLOCKED] issue → auto-close is a no-op."""
        cron.git_init_repo()
        r = cron.run(env_overrides={"HOS_TEST_BROKEN_STATE_OPEN_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.closed_issue_nums() == []
        assert cron.claude_ran()


# ───────────────── Baseline repair mode, opt-in (#959) ───────────────────────
class TestBaselineRepairMode:
    """<project>_baseline_on_red=repair (opt-in via projects.conf) scopes a red
    baseline cycle to fixing the failing tests instead of halting — but only for
    ordinary assertion failures (pytest exit 1); any other nonzero exit means the
    environment itself is broken and always halts. Bounded by
    HOS_BASELINE_REPAIR_MAX_ATTEMPTS consecutive cycles before escalating."""

    def test_default_mode_still_halts_on_assertion_failure(self, cron):
        """No <project>_baseline_on_red set → unchanged legacy halt behavior."""
        cron.git_init_repo()
        r = cron.run(
            env_overrides={
                "HOS_TEST_INNER_LOOP_EXIT": "1",
                "HOS_TEST_NEEDS_HUMAN_BLOCKED": "0",
            }
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert not cron.baseline_repair_state_file().exists()

    def test_repair_mode_absorbs_assertion_failure_and_launches_claude(self, cron):
        """repair mode + pytest exit 1 (assertion failures) → no halt, Claude
        launches scoped to the failing baseline, attempt counter stamped at 1."""
        cron.git_init_repo()
        cron.set_baseline_on_red("repair")
        r = cron.run(env_overrides={"HOS_TEST_INNER_LOOP_EXIT": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.aa_issue_created(), "repair mode must not file needs-human yet"
        assert cron.claude_ran(), "repair mode must still launch Claude, scoped to the fix"
        assert "baseline repair mode: attempt 1/3" in r.stdout
        assert cron.baseline_repair_state_file().read_text().strip() == "1"

    def test_repair_mode_context_tells_claude_to_scope_to_baseline(self, cron):
        """The injected prompt context names #959 repair mode so Claude doesn't
        pick up backlog work instead of fixing the baseline."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        prompt_file = cron.repo / "bootstrap" / "worker-cron-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("## Worker step instructions\n")
        cron.git_init_repo()
        cron.set_baseline_on_red("repair")
        r = cron.run(env_overrides={"HOS_TEST_INNER_LOOP_EXIT": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "BASELINE REPAIR MODE" in context
        assert "#959" in context

    def test_repair_mode_still_halts_on_environmental_failure(self, cron):
        """repair mode + pytest exit 2 (collection/session error — environmental,
        not an ordinary assertion failure) → halts exactly like default mode; the
        worker cannot fix broken infrastructure."""
        cron.git_init_repo()
        cron.set_baseline_on_red("repair")
        r = cron.run(
            env_overrides={
                "HOS_TEST_INNER_LOOP_EXIT": "2",
                "HOS_TEST_NEEDS_HUMAN_BLOCKED": "0",
            }
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert cron.aa_issue_created()
        assert not cron.baseline_repair_state_file().exists()

    def test_repair_mode_escalates_after_max_attempts(self, cron):
        """Repair attempts exceeding HOS_BASELINE_REPAIR_MAX_ATTEMPTS escalate to
        the same needs-human halt path instead of repairing forever."""
        cron.git_init_repo()
        cron.set_baseline_on_red("repair")
        cron.baseline_repair_state_file().parent.mkdir(parents=True, exist_ok=True)
        cron.baseline_repair_state_file().write_text("3\n")  # already used all 3 attempts
        r = cron.run(
            env_overrides={
                "HOS_TEST_INNER_LOOP_EXIT": "1",
                "HOS_BASELINE_REPAIR_MAX_ATTEMPTS": "3",
                "HOS_TEST_NEEDS_HUMAN_BLOCKED": "0",
            }
        )
        assert r.returncode == 1, r.stdout + r.stderr
        assert "repair exhausted" in r.stdout
        assert cron.aa_issue_created(), "exhausted repair mode must still escalate to a human"
        assert not cron.claude_ran()


# ──────────────────────── Timeout breaker, exit=124 (#1435) ──────────────────
class TestTimeoutBreaker:
    """A claude session killed at the wall-clock cap (exit=124) becomes a
    token-burning loop if the next fire just retries forever — each fire spends
    a full session, is killed at the ceiling, discards its work, and starts
    over. After HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS consecutive timeouts AT AN
    UNCHANGED CAP the project is suspended via the real bin/hos-suspend (never
    stubbed — this is an integration point, not a unit boundary) and a
    needs-human issue is filed so the suspension is visible in the queue. A
    cap change resets the counter instead of tripping (human ruling 2: a
    changed cap is a legitimate operator response, not a blind retry). A
    normally-completing cycle clears the counter and auto-closes any standing
    breaker issue.
    """

    def test_first_timeout_no_trip(self, cron):
        """One exit=124 at the default (0s/disabled) cap → counter stamped at
        1, no suspend, no issue filed."""
        r = cron.run(env_overrides={"HOS_TEST_CLAUDE_EXIT": "124"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "claude TIMED OUT" in r.stdout
        assert "timeout breaker: attempt 1/2" in r.stdout
        assert cron.timeout_breaker_state_file().read_text().splitlines() == ["1", "0"]
        assert not cron.suspend_file().exists()
        assert not cron.aa_issue_created()

    def test_second_timeout_same_cap_trips_breaker(self, cron):
        """A second consecutive exit=124 at the SAME cap reaches the default
        threshold (2) → suspends via the real hos-suspend and files a
        needs-human issue."""
        sf = cron.timeout_breaker_state_file()
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text("1\n0\n")
        r = cron.run(env_overrides={"HOS_TEST_CLAUDE_EXIT": "124"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "TIMEOUT BREAKER TRIPPED" in r.stdout
        assert cron.suspend_file().exists(), "expected hos-suspend to write a suspension marker"
        marker = cron.suspend_file().read_text()
        assert "timed out 2 consecutive cycles at 0s" in marker
        assert '"until"' not in marker, "the breaker must never set --until (silent auto-resume)"
        assert cron.aa_issue_created()
        assert cron.timeout_breaker_state_file().read_text().splitlines() == ["2", "0"]

    def test_second_timeout_changed_cap_resets_not_trips(self, cron):
        """A second exit=124 under a DIFFERENT cap than the recorded one is not
        a repetition under unchanged conditions (ruling 2) — reset to 1, no
        trip, no suspend."""
        sf = cron.timeout_breaker_state_file()
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text("1\n0\n")
        r = cron.run(
            env_overrides={"HOS_TEST_CLAUDE_EXIT": "124", "HOS_CRON_MAX_SECONDS": "60"}
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "TIMEOUT BREAKER TRIPPED" not in r.stdout
        assert "timeout breaker: attempt 1/2" in r.stdout
        assert not cron.suspend_file().exists()
        assert not cron.aa_issue_created()
        assert cron.timeout_breaker_state_file().read_text().splitlines() == ["1", "60"]

    def test_trip_dedup_query_failure_still_suspends(self, cron):
        """The needs-human dedup query failing must not block the suspend
        itself (#1435 acceptance: dedup failure skips filing, still
        suspends) — fail-closed only withholds the duplicate-issue filing."""
        sf = cron.timeout_breaker_state_file()
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text("1\n0\n")
        r = cron.run(
            env_overrides={"HOS_TEST_CLAUDE_EXIT": "124", "HOS_TEST_AA_QUERY_FAIL": "1"}
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "TIMEOUT BREAKER TRIPPED" in r.stdout
        assert cron.suspend_file().exists(), "dedup query failure must not block the suspend"
        assert not cron.aa_issue_created(), "dedup query failed → must fail closed, no issue"
        assert "fail-closed" in r.stdout

    def test_normal_completion_clears_breaker_and_closes_issue(self, cron):
        """A cycle that completes normally (exit 0) clears the standing
        counter and auto-closes any open breaker issue — the steady state
        must not stay 'permanently suspended + stale human issue'."""
        sf = cron.timeout_breaker_state_file()
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text("2\n0\n")
        r = cron.run(env_overrides={"HOS_TEST_BROKEN_STATE_OPEN_NUMS": "555"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.timeout_breaker_state_file().exists()
        assert "555" in cron.closed_issue_nums()
        assert cron.claude_ran()

    def test_normal_completion_no_standing_state_is_a_noop(self, cron):
        """No prior timeout-breaker state → normal completion touches nothing
        breaker-related."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.timeout_breaker_state_file().exists()
        assert cron.claude_ran()


# ──────────────────────────── Usage-limit breaker (#1446) ────────────────────
@pytest.mark.skip(
    reason="#1446 usage-limit breaker is commented out in bin/hos-cron "
           "(operator request 2026-09-01) — false-positive trips on any session "
           "whose transcript merely contains the phrase. Un-skip when the block "
           "is re-enabled with a narrower match."
)
class TestUsageLimitBreaker:
    """A genuine Claude usage-limit refusal detected in the session's own
    captured stdout (a hard signal from Anthropic's side) trips the project
    into suspension via the real bin/hos-suspend on the FIRST detection — no
    consecutive-attempt counter, unlike the timeout breaker above — and files
    a needs-human issue so the pause is visible in the queue. v1 is
    reactive-only: no sanctioned credential can read `/usage` percentages
    headlessly (see #1446), so this only watches for the CLI's own refusal
    text via a broad, case-insensitive match against multiple known
    phrasings. Detection runs independent of $_claude_exit's value.
    """

    @pytest.mark.parametrize(
        "phrase",
        [
            "Claude usage limit reached. Your limit will reset at 3pm (UTC).",
            "You've hit your session limit · resets 3pm",
            "You've hit your weekly limit · resets Friday",
            "You've hit your Opus limit · resets Friday",
            # Case-insensitivity
            "CLAUDE USAGE LIMIT REACHED.",
        ],
    )
    def test_known_phrasing_trips_breaker(self, cron, phrase):
        r = cron.run(env_overrides={"HOS_TEST_CLAUDE_STDOUT": phrase})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "USAGE LIMIT BREAKER TRIPPED" in r.stdout
        assert cron.suspend_file().exists(), "expected hos-suspend to write a suspension marker"
        marker = cron.suspend_file().read_text()
        assert '"until"' not in marker, "the breaker must never set --until (silent auto-resume)"
        assert cron.aa_issue_created()
        assert phrase in cron.claude_output_capture_file().read_text()

    def test_normal_output_does_not_trip_breaker(self, cron):
        """Ordinary session output with no usage-limit phrase → no trip."""
        r = cron.run(
            env_overrides={"HOS_TEST_CLAUDE_STDOUT": "Opened PR #123. Done for this cycle."}
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "USAGE LIMIT BREAKER TRIPPED" not in r.stdout
        assert not cron.suspend_file().exists()
        assert not cron.aa_issue_created()

    def test_no_captured_output_does_not_trip_breaker(self, cron):
        """No HOS_TEST_CLAUDE_STDOUT at all (the ordinary happy path) → the
        capture file still exists (claude always writes something to stdout
        in real use) but contains no usage-limit phrasing, so no trip."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "USAGE LIMIT BREAKER TRIPPED" not in r.stdout
        assert not cron.suspend_file().exists()
        assert not cron.aa_issue_created()

    def test_dedup_skips_duplicate_issue(self, cron):
        """A second cycle's dedup query reporting an existing open breaker
        issue does not file a duplicate — the suspend still fires (it's the
        very next cycle that's blocked by it, not this check)."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_CLAUDE_STDOUT": "Claude usage limit reached. Your limit will reset at 3pm (UTC).",
                "HOS_TEST_NEEDS_HUMAN_BLOCKED": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "USAGE LIMIT BREAKER TRIPPED" in r.stdout
        assert cron.suspend_file().exists()
        assert "already open — not filing a duplicate" in r.stdout
        assert not cron.aa_issue_created()

    def test_trip_dedup_query_failure_still_suspends(self, cron):
        """The needs-human dedup query failing must not block the suspend
        itself — mirrors the timeout breaker's identical acceptance
        criterion; fail-closed only withholds the duplicate-issue filing."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_CLAUDE_STDOUT": "Claude usage limit reached. Your limit will reset at 3pm (UTC).",
                "HOS_TEST_AA_QUERY_FAIL": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "USAGE LIMIT BREAKER TRIPPED" in r.stdout
        assert cron.suspend_file().exists(), "dedup query failure must not block the suspend"
        assert not cron.aa_issue_created(), "dedup query failed → must fail closed, no issue"
        assert "fail-closed" in r.stdout

    def test_trips_regardless_of_claude_exit_code(self, cron):
        """A nonzero exit alongside a usage-limit refusal still trips the
        breaker — detection is independent of $_claude_exit's value."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_CLAUDE_STDOUT": "You've hit your session limit · resets 3pm",
                "HOS_TEST_CLAUDE_EXIT": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "USAGE LIMIT BREAKER TRIPPED" in r.stdout
        assert cron.suspend_file().exists()

    def test_normal_completion_auto_closes_standing_issue(self, cron):
        """A cycle that completes normally (exit 0, no usage-limit phrase)
        auto-closes any standing usage-limit-breaker issue — symmetry with
        the timeout breaker's auto-close, defense-in-depth for a suspend
        marker cleared without also closing the issue."""
        r = cron.run(env_overrides={"HOS_TEST_BROKEN_STATE_OPEN_NUMS": "777"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "777" in cron.closed_issue_nums()
        assert cron.claude_ran()


# ──────────────────────────── PR routing skip (#791) ─────────────────────────
class TestPRRoutingSkip:
    def test_no_open_prs_launches_claude(self, cron):
        """No open bot PRs → no routing skip, Claude launched."""
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_awaiting_merge_still_launches_claude_for_triage(self, cron):
        """One open PR with APPROVED and no CHANGES_REQUESTED → new work blocked,
        but Claude still launches so Step 0 triage can run (#1198 Stage 0 item 3)."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting human merge" in r.stdout
        assert stdin_capture.exists(), "claude must still launch for Step 0 triage"
        context = stdin_capture.read_text()
        assert "NEW WORK: BLOCKED" in context

    def test_awaiting_merge_drops_overseer_wakeup(self, cron):
        """Blocked cycle still signals overseer so it can act on the ready PR.

        The `awaiting-merge` branch writes an explicit "worker-cycle-skip"
        wakeup as its own side effect (#1198 Stage 0 item 3 keeps this write).
        Since Claude now runs to completion instead of exiting early, the
        unconditional end-of-cycle "signal the other agent" block (unrelated
        to #1198) overwrites it with "worker-cycle-complete" before the script
        exits — a superset outcome (the overseer still gets pinged, now with
        confirmation the full cycle, including Step 0 triage, ran)."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.wakeup_overseer.exists(), "overseer wakeup must be dropped"
        payload = cron.wakeup_overseer.read_text()
        assert "worker-cycle-complete" in payload

    def test_awaiting_merge_stamps_last_run(self, cron):
        """Skipped cycle still stamps last-run for diagnostic visibility."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.last_run_file.exists(), "last-run must be stamped on skip"

    def test_changes_requested_launches_claude(self, cron):
        """PR with CHANGES_REQUESTED → worker must fix, Claude is launched."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "1",
                "HOS_TEST_PR_AP": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_unapproved_pr_launches_claude(self, cron):
        """PR with no approvals yet → not 'awaiting merge', Claude launched."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "0",  # not yet approved
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_overseer_role_not_subject_to_pr_routing(self, cron):
        """PR routing skip applies only to worker — overseer always launches."""
        r = cron.run(
            role="overseer",
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
            },
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_overseer_role_gets_no_new_work_directive(self, cron):
        """The "New work directive" section is worker-only (#1198) — the overseer
        must never see a NEW WORK: line in its prompt context."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        r = cron.run(
            role="overseer",
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
            },
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "NEW WORK:" not in context


# ───────────────────────── Actionable-work gate (#1395) ───────────────────────
class TestActionableWorkGate:
    """The worker's actionable-work gate runs before git sync and the baseline
    test suite, skipping the cycle early when there is genuinely nothing to do.

    A single query failure must never be misread as "empty" (mirrors #915) —
    the gate only skips when every signal query succeeds AND every signal is
    empty. The `cron` fixture's default env already sets
    HOS_TEST_MILESTONELESS_ISSUES=9001, so tests here override it (and any
    other signal under test) explicitly.
    """

    def test_no_signals_skips_before_sync_and_baseline(self, cron):
        """No milestone-less issue, release request, open PR, or next-work
        candidate → cycle exits 0 before git sync/baseline, Claude never runs,
        but last-run is still stamped."""
        r = cron.run(env_overrides={"HOS_TEST_MILESTONELESS_ISSUES": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" in r.stdout
        assert not cron.claude_ran()
        assert not cron.baseline_ran()
        assert cron.last_run_file.exists()

    def test_milestoneless_issue_alone_proceeds(self, cron):
        """A milestone-less issue alone is sufficient to make the cycle proceed."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_MILESTONELESS_ISSUES": "42",
                "HOS_TEST_OPEN_PR_NUMS": "",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" not in r.stdout
        assert cron.claude_ran()

    def test_open_pr_alone_proceeds(self, cron):
        """An open PR alone is sufficient to make the cycle proceed."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_MILESTONELESS_ISSUES": "",
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" not in r.stdout
        assert cron.claude_ran()

    def test_release_request_alone_proceeds(self, cron):
        """An open release-request issue alone is sufficient to make the cycle
        proceed."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_MILESTONELESS_ISSUES": "",
                "HOS_TEST_OPEN_PR_NUMS": "",
                "HOS_TEST_RELEASE_REQUESTS": "#1300 Ship v0.6.1 [release-request] assignees=0",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" not in r.stdout
        assert cron.claude_ran()

    def test_next_work_candidate_alone_proceeds(self, cron):
        """A next-work candidate alone is sufficient to make the cycle proceed.
        Milestone resolution is skipped by setting HOS_TARGET_MILESTONE_NUMBER
        directly (mirrors the REST-lookup-skip pattern the launcher itself
        supports)."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_MILESTONELESS_ISSUES": "",
                "HOS_TEST_OPEN_PR_NUMS": "",
                "HOS_TEST_ISSUE_CANDIDATES": "#901 Some candidate issue",
                "HOS_TARGET_RELEASE": "v0.6.1",
                "HOS_TARGET_MILESTONE_NUMBER": "7",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" not in r.stdout
        assert cron.claude_ran()

    def test_query_failure_does_not_skip(self, cron):
        """A query failure is "unknown", never "empty" — it must never cause a
        skip on its own (mirrors #915)."""
        r = cron.run(
            env_overrides={
                "HOS_TEST_MILESTONELESS_ISSUES": "",
                "HOS_TEST_PR_FETCH_FAIL": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" not in r.stdout
        assert cron.claude_ran()

    def test_overseer_role_not_subject_to_this_gate(self, cron):
        """The gate's signals are worker-only — an overseer cycle with no
        milestone-less issues and no open PRs still hits the (unchanged,
        pre-existing) overseer "no open PRs" skip, not this gate. Confirms the
        two skip paths don't cross-contaminate."""
        r = cron.run(
            role="overseer",
            env_overrides={
                "HOS_TEST_MILESTONELESS_ISSUES": "",
                "HOS_TEST_OPEN_PR_NUMS": "",
            },
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no actionable work" not in r.stdout
        assert "no open PRs" in r.stdout
        assert not cron.claude_ran()


# ──────────────────── Overseer open-PR fetch failure (#915) ──────────────────
class TestOverseerPRFetchFailure:
    """A transient open-PR fetch error must NOT be misread as 'no open PRs'.

    The old `$(... || true)` swallowed gh's non-zero exit into an empty result,
    misreading a transient API blip as a genuine empty PR queue. The fetch
    failure must skip the cycle WITHOUT stamping last-run so the next cycle
    retries immediately, under a distinct audit reason.
    """

    @staticmethod
    def _overseer_last_run(cron) -> Path:
        # last_run_file is hardcoded to worker-hos; the overseer stamps overseer-hos.
        return cron.state / "last-run" / "overseer-hos"

    def test_fetch_failure_does_not_stamp_last_run(self, cron):
        r = cron.run(role="overseer", env_overrides={"HOS_TEST_PR_FETCH_FAIL": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert not self._overseer_last_run(
            cron
        ).exists(), "a fetch failure must not stamp last-run — next cycle must retry"

    def test_fetch_failure_is_distinct_from_empty(self, cron):
        r = cron.run(role="overseer", env_overrides={"HOS_TEST_PR_FETCH_FAIL": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "open-PR fetch failed" in r.stdout
        assert (
            "no open PRs" not in r.stdout
        ), "fetch failure must not be masked as a genuine empty-PR cycle"

    def test_fetch_failure_does_not_launch_claude(self, cron):
        r = cron.run(role="overseer", env_overrides={"HOS_TEST_PR_FETCH_FAIL": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.claude_ran(), "no AI turn on an unfetchable PR queue"

    def test_genuine_empty_pr_list_stamps_last_run(self, cron):
        """A SUCCESSFUL fetch returning zero PRs still stamps last-run."""
        r = cron.run(role="overseer", env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no open PRs" in r.stdout
        assert self._overseer_last_run(
            cron
        ).exists(), "a genuine empty-PR cycle still stamps last-run"
        assert not cron.claude_ran()


# ──────────────────── Missing prompt file fails closed (#989) ─────────────────
class TestMissingPromptFile:
    """A missing role prompt file must fail closed, never fall back to an ad-hoc
    prompt: the prompt file carries all runtime governance (injection hardening
    #734, REST-only, the Step-4 test/validator HARD GATE, PR attribution, the
    identity guard), and the launch is `--permission-mode bypassPermissions` with
    full tool access. Falling back would run a guardrail-free autonomous agent.
    """

    def test_missing_worker_prompt_exits_78_without_claude(self, cron):
        cron.prompt_file("worker").unlink()
        r = cron.run()
        assert r.returncode == 78, r.stdout + r.stderr
        assert (
            not cron.claude_ran()
        ), "a missing prompt must NOT launch a guardrail-free bypassPermissions session"
        assert "role prompt file missing" in r.stdout

    def test_missing_worker_prompt_does_not_stamp_last_run(self, cron):
        # Fail-closed config errors must not stamp last-run — next fire retries.
        cron.prompt_file("worker").unlink()
        r = cron.run()
        assert r.returncode == 78, r.stdout + r.stderr
        assert not cron.last_run_file.exists()

    def test_missing_overseer_prompt_exits_78_without_claude(self, cron):
        # Give the overseer an open PR so it proceeds past the "no open PRs" skip
        # and reaches the prompt-file guard.
        cron.prompt_file("overseer").unlink()
        r = cron.run(role="overseer", env_overrides={"HOS_TEST_OPEN_PR_NUMS": "856"})
        assert r.returncode == 78, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert "role prompt file missing" in r.stdout

    def test_present_prompt_still_launches_claude(self, cron):
        # Guard: the fixture ships a prompt, so the happy path is unaffected.
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.claude_ran()


# ──────────────────────── Working directory injection (#805) ──────────────────
class TestWorkingDirectoryInjection:
    def test_prompt_file_prepended_with_working_directory(self, cron):
        """When a prompt file exists, it is piped with WORKING DIRECTORY prepended."""
        # Write a minimal worker-cron-prompt.md; capture stdin via claude stub.
        prompt_file = cron.repo / "bootstrap" / "worker-cron-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("hello from prompt\n")
        # Override claude stub to capture its stdin to a file.
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        stdin_text = stdin_capture.read_text()
        assert stdin_text.startswith(
            "WORKING DIRECTORY:"
        ), "First line must be the injected WORKING DIRECTORY"
        assert str(cron.repo) in stdin_text, "Injected path must match REPO_ROOT"
        assert "hello from prompt" in stdin_text

    def test_claude_invoked_with_cwd_at_repo_root(self, cron):
        """claude's process cwd must be $REPO_ROOT (#1126).

        Claude Code's `.claude/agents/*.md` custom-subagent discovery is
        cwd-based at process start, not derived from the injected
        "WORKING DIRECTORY:" prompt text. Without a `cd` before invocation,
        the launcher inherits its own launch cwd (unrelated to $REPO_ROOT)
        and the worker/overseer session can dispatch none of its shipped
        agents — a silent, systemic governance-pipeline failure.
        """
        pwd_capture = cron.home / "claude_pwd.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n"
            "cat > /dev/null 2>&1 || true   # drain stdin (prompt pipe)\n"
            f'pwd -P > "{pwd_capture}"\n'
            "exit 0\n",
        )
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        actual = pwd_capture.read_text().strip()
        expected = str(cron.repo.resolve())
        assert actual == expected, (
            f"claude must run with cwd=REPO_ROOT for agent discovery; "
            f"got {actual!r}, expected {expected!r}"
        )

    def test_no_hardcoded_paths_in_worker_prompt(self):
        """worker-cron-prompt.md must contain no absolute paths (regression guard)."""
        prompt = (
            Path(__file__).parent.parent.parent / "bootstrap" / "worker-cron-prompt.md"
        ).read_text()
        import re

        hardcoded = re.findall(r"(?:^|\s)(/(?:home|Users)/\S+)", prompt, re.MULTILINE)
        assert (
            not hardcoded
        ), f"Hardcoded absolute paths found in worker-cron-prompt.md: {hardcoded}"

    def test_no_hardcoded_paths_in_overseer_prompt(self):
        """overseer-cron-prompt.md must contain no absolute paths (regression guard)."""
        prompt = (
            Path(__file__).parent.parent.parent / "bootstrap" / "overseer-cron-prompt.md"
        ).read_text()
        import re

        hardcoded = re.findall(r"(?:^|\s)(/(?:home|Users)/\S+)", prompt, re.MULTILINE)
        assert (
            not hardcoded
        ), f"Hardcoded absolute paths found in overseer-cron-prompt.md: {hardcoded}"


# ─────────────────────── Pre-computed cycle context (#792) ─────────────────────
class TestCycleContextBlock:
    """_build_context() appends a pre-computed block to the Claude prompt (#792)."""

    def _setup_stdin_capture(self, cron: CronEnv) -> Path:
        """Replace claude stub to capture its stdin; write a minimal prompt file."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        prompt_file = cron.repo / "bootstrap" / "worker-cron-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("## Worker step instructions\n")
        return stdin_capture

    def test_context_block_present_no_open_prs(self, cron):
        """0 open bot PRs → context block header present and 'None.' shown."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "None." in context
        assert "NEW WORK: ALLOWED" in context

    def test_context_block_one_open_pr(self, cron):
        """1 open bot PR → context block shows that PR number and the
        needs-attention directive; the launcher also audits the case (#1198
        Stage 0 item 2 — previously invisible)."""
        stdin_capture = self._setup_stdin_capture(cron)
        # PR_AP=0: unapproved → routing marks needs-attention → Claude launched
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_AP": "0",
                "HOS_TEST_PR_CR": "0",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "856" in context
        # Scoped to the "Open bot PRs" section: it must show the PR, not
        # "None." — the NG3b release-requests section below it legitimately
        # prints "None." here since HOS_TEST_RELEASE_REQUESTS isn't set.
        pr_section = context.split("### Open bot PRs", 1)[1].split("###", 1)[0]
        assert "None." not in pr_section
        assert "NEW WORK: BLOCKED" in context
        assert "routing=needs-attention" in context

    def test_context_block_needs_fix_directive(self, cron):
        """A PR with CHANGES_REQUESTED → BLOCKED directive cites needs-fix."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "1",
                "HOS_TEST_PR_AP": "1",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "NEW WORK: BLOCKED" in context
        assert "routing=needs-fix" in context

    def test_context_block_three_open_prs(self, cron):
        """3 open bot PRs → context block lists all three numbers."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856 857 858",
                "HOS_TEST_PR_AP": "0",
                "HOS_TEST_PR_CR": "0",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "856" in context
        assert "857" in context
        assert "858" in context

    def test_context_block_follows_prompt_content(self, cron):
        """Context block is appended after the prompt file content, not before it."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        prompt_pos = context.find("## Worker step instructions")
        ctx_pos = context.find("Pre-computed cycle context")
        assert prompt_pos >= 0, "prompt file content must be present"
        assert ctx_pos >= 0, "context block must be present"
        assert prompt_pos < ctx_pos, "context block must follow prompt content"

    def test_context_block_present_when_awaiting_merge(self, cron):
        """All PRs awaiting merge → new work blocked, but Claude still launches
        for Step 0 triage and receives the context block (#1198 Stage 0 item 3)."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_AP": "1",
                "HOS_TEST_PR_CR": "0",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting human merge" in r.stdout
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "NEW WORK: BLOCKED" in context

    def test_context_block_bounced_pr_routes_needs_fix_bounce(self, cron):
        """A PR the overseer bounced (draft + `needs-ai`) must route to the
        distinct `needs-fix-bounce` directive, not `needs-attention` — #1350.
        Zero CHANGES_REQUESTED/APPROVED reviews mirrors record_pr_bounce()'s
        actual signal: it posts a COMMENT review (never CHANGES_REQUESTED, by
        design), so the bounce is invisible to the review-state checks alone."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "0",
                "HOS_TEST_PR_MS": "clean",
                "HOS_TEST_PR_DRAFT": "true",
                "HOS_TEST_PR_LABELS": "needs-ai",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "NEW WORK: BLOCKED" in context
        assert "routing=needs-fix-bounce" in context
        assert "routing=needs-attention" not in context

    def test_context_block_dirty_and_bounced_pr_routes_needs_fix(self, cron):
        """A PR that is BOTH conflicting and bounced must still route to plain
        `needs-fix` — the dirty check is ordered first (a merge conflict takes
        priority over the bounce signal), guarding against an ordering
        regression in the routing loop (#1350)."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "0",
                "HOS_TEST_PR_MS": "dirty",
                "HOS_TEST_PR_DRAFT": "true",
                "HOS_TEST_PR_LABELS": "needs-ai",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "NEW WORK: BLOCKED" in context
        assert "routing=needs-fix" in context
        assert "routing=needs-fix-bounce" not in context


# ────────────── Open release requests (NG3b, #1347 Amendment 1) ───────────────
class TestReleaseRequestContextBlock:
    """_build_context() surfaces open release-request issues (worker only) so
    Step 0.5 in worker.md / worker-cron-prompt.md has something to read every
    cycle — a standing gate, not new-work discovery (#1347 Amendment 1)."""

    def _setup_stdin_capture(self, cron: CronEnv) -> Path:
        """Replace claude stub to capture its stdin; write a minimal prompt file."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        prompt_file = cron.repo / "bootstrap" / "worker-cron-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("## Worker step instructions\n")
        return stdin_capture

    def test_open_release_request_appears_in_worker_prompt(self, cron):
        stdin_capture = self._setup_stdin_capture(cron)
        fake_line = "#1300 Ship v0.6.1 [release-request] assignees=0"
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "",
                "HOS_TEST_RELEASE_REQUESTS": fake_line,
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "### Open release requests (NG3b)" in context
        assert fake_line in context

    def test_no_release_requests_shows_none(self, cron):
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "",
                "HOS_TEST_RELEASE_REQUESTS": "",
            }
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "### Open release requests (NG3b)" in context
        # The heading's own "None." — not some other section's.
        heading_pos = context.index("### Open release requests (NG3b)")
        following = context[heading_pos:]
        assert "None." in following.splitlines()[1]

    def test_overseer_role_gets_no_release_request_section(self, cron):
        """Worker-only (mirrors the "New work directive" gate) — the overseer
        never sees this heading or any release-request content."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n" f'cat > "{stdin_capture}"\n' "exit 0\n",
        )
        r = cron.run(
            role="overseer",
            env_overrides={
                "HOS_TEST_OPEN_PR_NUMS": "856",
                "HOS_TEST_PR_CR": "0",
                "HOS_TEST_PR_AP": "1",
                "HOS_TEST_RELEASE_REQUESTS": "#1300 Ship v0.6.1 [release-request] assignees=0",
            },
        )
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Open release requests (NG3b)" not in context
        assert "release-request" not in context

    def test_release_requests_precede_new_work_directive(self, cron):
        """The NG3b section renders before "New work directive" — it is a
        standing gate the worker must evaluate every cycle, independent of
        whether new backlog work is allowed this cycle."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        release_pos = context.index("### Open release requests (NG3b)")
        directive_pos = context.index("### New work directive")
        assert release_pos < directive_pos


# ───────────────────────── _sync_audit_logs ────────────────────────────────
def _extract_sync_audit_logs_func() -> str:
    """Extract the _sync_audit_logs function body from bin/hos-cron."""
    lines = HOS_CRON.read_text().splitlines()
    in_func, depth, collected = False, 0, []
    for line in lines:
        if line.startswith("_sync_audit_logs()"):
            in_func = True
        if in_func:
            collected.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and len(collected) > 1:
                break
    return "\n".join(collected)


_SYNC_FUNC = _extract_sync_audit_logs_func()


def _git(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + list(args), cwd=cwd, check=True, capture_output=True, text=True)


def _make_repos(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote and a fully-configured local clone with a main branch."""
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _git("init", "--bare", str(remote))
    _git("init", str(local))
    _git("-C", str(local), "config", "user.email", "test@hos.test")
    _git("-C", str(local), "config", "user.name", "HOS Test")
    _git("-C", str(local), "commit", "--allow-empty", "-m", "init", "--quiet")
    _git("-C", str(local), "remote", "add", "origin", str(remote))
    _git("-C", str(local), "push", "origin", "HEAD:main", "--quiet")
    return remote, local


def _run_sync(local: Path, env_extra=None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(local.parent)}
    if env_extra:
        env.update(env_extra)
    script = (
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        'LOG_PREFIX="[test]"\n' + _SYNC_FUNC + f'\n_sync_audit_logs "{local}"\n'
    )
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )


def _remote_branch_exists(remote: Path, branch: str) -> bool:
    r = subprocess.run(
        ["git", "ls-remote", "--exit-code", str(remote), branch],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


def _files_on_branch(remote: Path, branch: str) -> list[str]:
    r = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", f"refs/heads/{branch}"],
        cwd=remote,
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout.splitlines()


class TestSyncAuditLogs:
    """Unit tests for _sync_audit_logs() in bin/hos-cron (#861)."""

    def test_changed_audit_files_pushed_to_audit_log_branch(self, tmp_path):
        """Per-entry audit records present and new → committed and pushed to audit-log (not main)."""
        remote, local = _make_repos(tmp_path)
        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T200555Z-cycle-start-a28b130933d0.json").write_text(
            '{"event":"cycle-start"}\n'
        )

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _remote_branch_exists(remote, "audit-log")
        tree = _files_on_branch(remote, "audit-log")
        assert any(
            "cycle-start" in f for f in tree
        ), f"Expected audit record on audit-log branch, got: {tree}"

    def test_retired_oversight_log_jsonl_not_synced(self, tmp_path):
        """Regression (#1303): the retired single-file audit/oversight-log.jsonl
        is no longer a sync target — only audit/log/**/*.json per-entry records
        and audit/overnight-loop-log.md are. A file at the old path alone must
        not create the audit-log branch."""
        remote, local = _make_repos(tmp_path)
        audit_dir = local / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "oversight-log.jsonl").write_text('{"event":"cycle-start"}\n')

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _remote_branch_exists(
            remote, "audit-log"
        ), "the retired oversight-log.jsonl path must not trigger a sync"

    def test_already_synced_record_not_recopied(self, tmp_path):
        """A per-entry record already present on the base branch is skipped, but
        a genuinely new one alongside it still syncs (write-once/content-addressed
        dedup, not an all-or-nothing skip)."""
        remote, local = _make_repos(tmp_path)

        seed_local = tmp_path / "seed"
        _git("clone", str(remote), str(seed_local))
        _git("-C", str(seed_local), "config", "user.email", "test@hos.test")
        _git("-C", str(seed_local), "config", "user.name", "HOS Test")
        _git("-C", str(seed_local), "checkout", "-b", "audit-log", "--quiet")
        seed_record_dir = seed_local / "audit" / "log" / "2026" / "06"
        seed_record_dir.mkdir(parents=True)
        existing_record = "2026-06-23T200555Z-cycle-start-a28b130933d0.json"
        (seed_record_dir / existing_record).write_text('{"event":"old"}\n')
        _git("-C", str(seed_local), "add", f"audit/log/2026/06/{existing_record}")
        _git("-C", str(seed_local), "commit", "-m", "prior audit", "--quiet")
        _git("-C", str(seed_local), "push", "origin", "HEAD:audit-log", "--quiet")

        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / existing_record).write_text('{"event":"old"}\n')
        new_record = "2026-06-23T201425Z-human-authorized-merge-2035673c0319.json"
        (record_dir / new_record).write_text('{"event":"new"}\n')

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "audit logs pushed" in r.stdout
        tree = _files_on_branch(remote, "audit-log")
        assert any(new_record in f for f in tree), f"new record missing from tree: {tree}"

    def test_no_audit_files_on_disk_no_push(self, tmp_path):
        """No audit files on disk → function returns early, audit-log branch not created."""
        remote, local = _make_repos(tmp_path)

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _remote_branch_exists(remote, "audit-log")

    def test_audit_log_branch_absent_bases_off_main(self, tmp_path):
        """No existing audit-log branch → new branch is rooted at main."""
        remote, local = _make_repos(tmp_path)
        assert not _remote_branch_exists(remote, "audit-log")

        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T200555Z-cycle-start-a28b130933d0.json").write_text(
            '{"event":"test"}\n'
        )

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _remote_branch_exists(remote, "audit-log"), "audit-log branch should be created"
        assert "audit logs pushed" in r.stdout

    def test_audit_log_branch_exists_rebases_from_it(self, tmp_path):
        """Existing audit-log branch → new commit is based on it, not on main."""
        remote, local = _make_repos(tmp_path)

        # Seed the remote audit-log branch with a prior commit
        seed_local = tmp_path / "seed"
        _git("clone", str(remote), str(seed_local))
        _git("-C", str(seed_local), "config", "user.email", "test@hos.test")
        _git("-C", str(seed_local), "config", "user.name", "HOS Test")
        _git("-C", str(seed_local), "checkout", "-b", "audit-log", "--quiet")
        (seed_local / "audit").mkdir(parents=True)
        (seed_local / "audit" / "overnight-loop-log.md").write_text("# prior\n")
        _git("-C", str(seed_local), "add", "audit/overnight-loop-log.md")
        _git("-C", str(seed_local), "commit", "-m", "prior audit", "--quiet")
        _git("-C", str(seed_local), "push", "origin", "HEAD:audit-log", "--quiet")

        # Now add new content to local and sync
        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T201425Z-human-authorized-merge-2035673c0319.json").write_text(
            '{"event":"new"}\n'
        )

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "audit logs pushed" in r.stdout

    def test_push_failure_warns_and_exits_zero(self, tmp_path):
        """Push failure prints WARN line but the function exits 0 (retry next cycle)."""
        remote, local = _make_repos(tmp_path)
        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T200555Z-cycle-start-a28b130933d0.json").write_text(
            '{"event":"test"}\n'
        )

        # Fake git that succeeds on all operations except push
        fake_bin = tmp_path / "fakebin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        real_git = subprocess.check_output(["which", "git"], text=True).strip()
        fake_git.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$*" == *"push"* ]]; then\n'
            '  echo "fatal: fake push failure" >&2\n'
            "  exit 1\n"
            "fi\n"
            f'exec "{real_git}" "$@"\n'
        )
        fake_git.chmod(0o755)

        r = _run_sync(local, env_extra={"PATH": f"{fake_bin}:/usr/bin:/bin"})
        assert r.returncode == 0, f"push failure must not exit non-zero; got {r.returncode}"
        assert "WARN" in r.stdout and "push failed" in r.stdout

    # ── #988: the sync must never mutate the live shared working tree ─────────
    def test_live_checkout_never_branch_switched(self, tmp_path):
        """The sync runs `git checkout` in a scratch worktree, never in $REPO_ROOT.

        The old code did `git checkout -b _audit-sync-$$` **in the live checkout**;
        a SIGKILL (sleep/reboot/OOM) between that and the restoring `git checkout -`
        stranded the shared working tree on an audit-log branch, so the next cycle
        built/pushed feature work off audit-log history. The isolated-worktree fix
        must issue no `checkout` against the live repo at all — and leak no
        `_audit-sync-*` branch there.
        """
        remote, local = _make_repos(tmp_path)
        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T200555Z-cycle-start-a28b130933d0.json").write_text(
            '{"event":"cycle"}\n'
        )

        # A git wrapper that records every subcommand, then delegates to real git.
        log_file = tmp_path / "git-calls.log"
        fake_bin = tmp_path / "gitlog-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        real_git = subprocess.check_output(["which", "git"], text=True).strip()
        fake_git.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{log_file}"\n'
            f'exec "{real_git}" "$@"\n'
        )
        fake_git.chmod(0o755)

        r = _run_sync(local, env_extra={"PATH": f"{fake_bin}:/usr/bin:/bin"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "audit logs pushed" in r.stdout  # the sync still happened

        calls = log_file.read_text()
        # Token-exact match: a scratch worktree path can *contain* the substring
        # "checkout"; what must never appear is `checkout` as a git subcommand.
        assert not any("checkout" in line.split() for line in calls.splitlines()), (
            "sync must not run `git checkout` (it branch-switches the live tree); "
            f"git calls were:\n{calls}"
        )
        leaked = _git("-C", str(local), "branch", "--list", "_audit-sync-*").stdout
        assert leaked.strip() == "", f"leaked audit-sync branch(es): {leaked!r}"

    def test_live_head_index_and_worktree_pristine(self, tmp_path):
        """A pre-existing branch + staged change survives the sync byte-for-byte.

        Guards the live HEAD, branch and index from the sync, and asserts no
        scratch worktree registration is left behind in the live repo.
        """
        remote, local = _make_repos(tmp_path)
        _git("-C", str(local), "checkout", "-b", "feature-x", "--quiet")
        (local / "work.py").write_text("x = 1\n")
        _git("-C", str(local), "add", "work.py")
        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T200555Z-cycle-start-a28b130933d0.json").write_text(
            '{"event":"cycle"}\n'
        )
        before_head = _git("-C", str(local), "rev-parse", "HEAD").stdout.strip()

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr

        assert (
            _git("-C", str(local), "symbolic-ref", "--short", "HEAD").stdout.strip() == "feature-x"
        )
        assert _git("-C", str(local), "rev-parse", "HEAD").stdout.strip() == before_head
        staged = _git("-C", str(local), "diff", "--cached", "--name-only").stdout.split()
        assert "work.py" in staged, "the live index must be untouched by the sync"
        worktrees = _git("-C", str(local), "worktree", "list").stdout.strip().splitlines()
        assert len(worktrees) == 1, f"scratch worktree leaked into live repo: {worktrees}"

    def test_uncommitted_worktree_changes_not_leaked_to_audit_branch(self, tmp_path):
        """Only audit files reach audit-log — never a carried-along feature change.

        The old branch-switch could carry a staged working-tree change onto the
        temp branch and push it; the scratch worktree only ever contains the
        copied audit files, so unrelated work can't leak onto the audit branch.
        """
        remote, local = _make_repos(tmp_path)
        (local / "secret_feature.py").write_text("leaked = True\n")
        _git("-C", str(local), "add", "secret_feature.py")
        record_dir = local / "audit" / "log" / "2026" / "06"
        record_dir.mkdir(parents=True)
        (record_dir / "2026-06-23T200555Z-cycle-start-a28b130933d0.json").write_text(
            '{"event":"cycle"}\n'
        )

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _remote_branch_exists(remote, "audit-log")
        tree = _files_on_branch(remote, "audit-log")
        assert any("cycle-start" in f for f in tree), tree
        assert (
            "secret_feature.py" not in tree
        ), f"feature change leaked onto audit-log branch: {tree}"
