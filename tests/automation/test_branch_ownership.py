"""Tests for bootstrap/create_branch.sh and bootstrap/lib/branch_ownership.sh
(#967, ADR-037 — P1: mechanism only, no enforcement yet).

Unlike the other bootstrap/*.sh tests, this suite runs against a REAL temp git
repository rather than stubs: the store location (<git-common-dir>/hos/...),
the not-tracked property (T7), and cross-clone isolation (T8) are only
meaningful against real git plumbing (technical-design §11.1).

`create_branch.sh` resolves its own repo root from its own script location
(`$SCRIPT_DIR/..`), not from argv or cwd — so exercising it against a
throwaway repo means installing a COPY of the real script (and its library)
under <tmp-repo>/bootstrap/, mirroring the harness pattern already used by
tests/automation/test_submit_pr.py for the same reason.

Covers:
  T7  — the record is not committed (store lives under .git/, invisible to
        git status/ls-files).
  T8  — AD-7 cross-clone isolation: a record written in one clone's store is
        never valid when checked against a different clone, even with an
        identical branch name and cycle id.
  T11 — AD-3 branch-name cycle-uniqueness: different cycle tokens produce
        different branch names; a second run in the SAME cycle is idempotent;
        an existing same-named branch with no valid record is refused, never
        adopted.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CREATE_BRANCH = REPO_ROOT / "bootstrap" / "create_branch.sh"
REAL_BRANCH_OWNERSHIP_LIB = REPO_ROOT / "bootstrap" / "lib" / "branch_ownership.sh"

GIT_IDENT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def _git(repo: Path, *args, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, check=check,
    )


def _current_branch(repo: Path) -> str:
    return _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()


class Repo:
    """A real, throwaway git repository with a real copy of create_branch.sh
    (and its library) installed at <root>/bootstrap/, so the script's own
    SCRIPT_DIR/REPO_DIR resolution lands inside this repo, not the dev
    checkout running the test suite."""

    def __init__(self, tmp_path: Path, name: str = "repo"):
        self.root = tmp_path / name
        self.root.mkdir(parents=True, exist_ok=True)
        _git(self.root, "init", "-q")
        _git(self.root, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.root / "README.md").write_text("init\n")

        # Install the scripts under test BEFORE the initial commit, so they
        # are tracked content — otherwise the harness's own installation step
        # would itself show up as an untracked file in every T7 assertion,
        # unrelated to whether the ownership record leaks into git status.
        bootstrap = self.root / "bootstrap"
        (bootstrap / "lib").mkdir(parents=True, exist_ok=True)
        shutil.copy(REAL_CREATE_BRANCH, bootstrap / "create_branch.sh")
        (bootstrap / "create_branch.sh").chmod(0o755)
        shutil.copy(REAL_BRANCH_OWNERSHIP_LIB, bootstrap / "lib" / "branch_ownership.sh")

        _git(self.root, "add", "-A")
        _git(self.root, *GIT_IDENT, "commit", "-q", "-m", "init")

    def create_branch(
        self, *args,
        cycle_id: str = "worker-hos-260101000000-999",
        cycle_token: str = "260101000000",
        cycle_role: str = "worker",
        env_overrides: dict | None = None,
        timeout: int = 15,
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update({
            "HOS_CYCLE_ID": cycle_id,
            "HOS_CYCLE_TOKEN": cycle_token,
            "HOS_CYCLE_ROLE": cycle_role,
        })
        if env_overrides:
            env.update(env_overrides)
        argv = [BASH, str(self.root / "bootstrap" / "create_branch.sh")] + list(args)
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False, env=env,
        )


def _verify(repo: Path, branch: str, cycle_id: str | None) -> subprocess.CompletedProcess:
    """Call hos_bo_verify directly by sourcing the real library.

    P1 has no chokepoint yet that reads the record (that lands in P2's
    submit_pr.sh integration) — this is the library's own test surface until
    then.
    """
    env = dict(os.environ)
    if cycle_id is None:
        env.pop("HOS_CYCLE_ID", None)
    else:
        env["HOS_CYCLE_ID"] = cycle_id
    script = (
        f'source "{REAL_BRANCH_OWNERSHIP_LIB}"\n'
        f'hos_bo_verify "{repo}" "{branch}"\n'
        'rc=$?\n'
        'printf "rc=%s reason=%s\\n" "$rc" "${HOS_BO_REASON:-}"\n'
        'exit "$rc"\n'
    )
    return subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, timeout=10, env=env, check=False,
    )


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path)


# ─────────────────────────── T7 — record is not committed ──────────────────
class TestRecordNotCommitted:
    def test_record_lives_under_git_common_dir(self, repo):
        r = repo.create_branch("--issue", "967", "--slug", "branch ownership")
        assert r.returncode == 0, r.stdout + r.stderr
        branch = r.stdout.strip()
        assert branch

        common_dir_raw = _git(repo.root, "rev-parse", "--git-common-dir").stdout.strip()
        common_dir = Path(common_dir_raw)
        if not common_dir.is_absolute():
            common_dir = repo.root / common_dir
        common_dir = common_dir.resolve()

        store_dir = common_dir / "hos" / "branch-ownership"
        records = list(store_dir.glob("*.rec"))
        assert len(records) == 1, f"expected exactly one record under {store_dir}, found {records}"
        assert records[0].read_text().splitlines()[1] == f"branch={branch}"

    def test_record_invisible_to_git_status(self, repo):
        r = repo.create_branch("--issue", "967", "--slug", "invisible")
        assert r.returncode == 0, r.stdout + r.stderr

        status = _git(repo.root, "status", "--porcelain").stdout
        assert status.strip() == "", f"ownership record leaked into git status: {status!r}"

    def test_record_never_appears_in_ls_files(self, repo):
        r = repo.create_branch("--issue", "967", "--slug", "untracked")
        assert r.returncode == 0, r.stdout + r.stderr

        tracked = _git(repo.root, "ls-files").stdout
        assert "branch-ownership" not in tracked
        assert ".rec" not in tracked


# ─────────────────────── T8 — AD-7 cross-clone isolation ───────────────────
class TestCrossCloneIsolation:
    def test_record_in_one_clone_is_not_valid_in_another(self, tmp_path):
        repo_a = Repo(tmp_path, "repo_a")
        repo_b = Repo(tmp_path, "repo_b")
        cycle_id = "worker-hos-260802000000-4242"

        r = repo_a.create_branch(
            "--issue", "967", "--slug", "cross-clone",
            cycle_id=cycle_id, cycle_token="260802000000",
        )
        assert r.returncode == 0, r.stdout + r.stderr
        branch = r.stdout.strip()

        # Never created in clone B — refused, even with the exact matching
        # cycle_id: the (clone, branch) pair is the key, not the branch name
        # alone (AD-7 amends R2's "keyed by branch name").
        v_b = _verify(repo_b.root, branch, cycle_id)
        assert v_b.returncode == 1
        assert "reason=no_record" in v_b.stdout, v_b.stdout

        # Valid in its own clone.
        v_a = _verify(repo_a.root, branch, cycle_id)
        assert v_a.returncode == 0, v_a.stdout

    def test_same_named_branch_in_second_project_is_isolated(self, tmp_path):
        # Two projects on one machine can produce identically-named branches
        # (ADR-037 AD-7's motivating case). Mirror that here with two clones
        # sharing an identical branch name AND cycle id.
        repo_a = Repo(tmp_path, "proj_a")
        repo_b = Repo(tmp_path, "proj_b")
        cycle_id = "worker-hos-260802000001-1"

        ra = repo_a.create_branch(
            "--issue", "12", "--slug", "fix-x", cycle_id=cycle_id, cycle_token="260802000001",
        )
        rb = repo_b.create_branch(
            "--issue", "12", "--slug", "fix-x", cycle_id=cycle_id, cycle_token="260802000001",
        )
        assert ra.returncode == 0, ra.stdout + ra.stderr
        assert rb.returncode == 0, rb.stdout + rb.stderr
        assert ra.stdout.strip() == rb.stdout.strip(), "branch names should collide by construction here"

        # Each clone's own record is valid only in that clone.
        assert _verify(repo_a.root, ra.stdout.strip(), cycle_id).returncode == 0
        assert _verify(repo_b.root, rb.stdout.strip(), cycle_id).returncode == 0


# ─────────────────── T11 — AD-3 branch-name cycle-uniqueness ───────────────
class TestCycleUniqueBranchNames:
    def test_different_cycle_tokens_produce_different_branch_names(self, repo):
        r1 = repo.create_branch(
            "--issue", "967", "--slug", "thing",
            cycle_token="260802000001", cycle_id="worker-hos-260802000001-1",
        )
        r2 = repo.create_branch(
            "--issue", "967", "--slug", "thing",
            cycle_token="260802000002", cycle_id="worker-hos-260802000002-2",
        )
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert r2.returncode == 0, r2.stdout + r2.stderr
        b1, b2 = r1.stdout.strip(), r2.stdout.strip()
        assert b1 != b2
        assert b1.endswith("260802000001")
        assert b2.endswith("260802000002")

    def test_second_run_in_same_cycle_is_idempotent(self, repo):
        cid = "worker-hos-260802000003-3"
        tok = "260802000003"
        r1 = repo.create_branch("--issue", "967", "--slug", "thing", cycle_token=tok, cycle_id=cid)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        _git(repo.root, "checkout", "-q", "main")

        r2 = repo.create_branch("--issue", "967", "--slug", "thing", cycle_token=tok, cycle_id=cid)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert r1.stdout.strip() == r2.stdout.strip()
        assert _current_branch(repo.root) == r1.stdout.strip()

        # Idempotent re-entry, not a second record write — exactly one record
        # file exists for this branch.
        common_dir = (repo.root / ".git").resolve()
        records = list((common_dir / "hos" / "branch-ownership").glob("*.rec"))
        assert len(records) == 1

    def test_existing_samename_branch_without_valid_record_is_refused(self, repo):
        cid = "worker-hos-260802000004-4"
        tok = "260802000004"
        branch_name = f"worker-967-thing-{tok}"
        _git(repo.root, "branch", branch_name)  # exists, but no ownership record

        r = repo.create_branch("--issue", "967", "--slug", "thing", cycle_token=tok, cycle_id=cid)
        assert r.returncode != 0
        combined = (r.stdout + r.stderr).lower()
        assert "never adopt" in combined or "adopt" in combined
        assert "no_record" in combined
