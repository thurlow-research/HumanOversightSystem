"""The new-code gate CLI (#2304): 80% line coverage and 75% mutant score on new and changed code.

    python -m scripts.framework.new_code_gate meta | plan | shard | verdict | run

(`python -m` is for a developer's own tree. CI, run_tests.sh and the gate's child
processes start it as `python -I -c <ENTRY_SNIPPET> <checkout root> <phase> ...`, so no
checkout file can shadow an import; see ADR-2304 section 2f RV2-1.)

Design: docs/v0.7.0/TECHNICAL-DESIGN-2304-new-code-coverage-mutation-gate.md. The pure
decisions live in `new_code_gate_logic`; this module does the git, coverage, mutmut and
filesystem work and hands plain data to them.

`plan` does the cheap phase once and cuts the mutation work into N shards; each `shard`
mutates its share in its own CI job; `verdict` merges the fragments and decides (TD 5.20,
ADR-2304 section 2h). `run` does all of it locally, in one process.

Exit contract (AD-1): 0 = every file passes, 1 = a decided fail, 2 = usage error,
3 = could not decide. Every caller treats non-zero as a fail.

At module level this file imports only the stdlib, `new_code_gate_logic` and
`new_code_gate_shard` (ADR-2304 section 2b, condition 5, as amended by 2h SH-9). coverage is
read lazily inside the plan path, and mutmut and libcst only ever load inside the two hidden
child phases, `_enumerate` and `_collect`, which `plan` and `shard` start as subprocesses
(TD 5.9). The gate's own PR gates this file in full, so its module-level and class-level
statements hold no decision logic (TD 5.19).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from scripts.framework import new_code_gate_logic as ncg
from scripts.framework import new_code_gate_shard as ncs

GateError = ncg.GateError

PLUGIN_RELPATH = "scripts/framework/new_code_gate_pytest_plugin.py"
PLUGIN_MODULE = "_ncg_tripwire"
KILL_GRACE_SECONDS = 10.0
EXIT_SIGTERM = 143
OUTPUT_TAIL_LINES = 40
OUTPUT_TAIL_CHARS = 4000
MAX_BLOCKED_NAMES = 20
# The runner's file-command variables are stripped as partial hardening only: a child that
# finds those files by the runner's layout is not stopped (ADR-2304 section 2f RV2-3, R-9).
STRIPPED_ENV_NAMES = frozenset(
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_ENV",
        "GITHUB_PATH",
        "GITHUB_OUTPUT",
        "GITHUB_STATE",
        "GITHUB_STEP_SUMMARY",
        "HOS_TEST_DURATIONS_OUT",
    }
)
STRIPPED_ENV_PREFIXES = ("ACTIONS_", "NCG_")
ARCHIVE_EXCLUDE = ":(exclude,glob)**/.claude/**"
GIT_DIFF_PREFIX = [
    "--literal-pathspecs",
    "-c",
    "diff.algorithm=myers",
    "-c",
    "core.quotePath=true",
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--text",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--inter-hunk-context=0",
    "-M",
]

LINE_KEYS = ("start_line", "end_line")
PHASE_REPO_COPY = "repo_copy_collect"
PHASE_ENUMERATE = "enumerate"
PHASE_MUTMUT = "mutmut_run"
PHASE_COLLECT = "collect"

MSG_UPSTREAM = "upstream job not successful: "
MSG_NO_DURATIONS = "test durations missing from sidecar"
RECORDS_FILENAME = "new-code-records.json"
VERDICT_FILENAME = "new-code-verdict.json"
PLAN_FILENAME = "new-code-plan.json"
FRAGMENT_FILENAME = "new-code-fragment.json"
FRAGMENT_DIR_FORMAT = "new-code-fragment-{index}-of-{count}"


class BudgetExpired(Exception):
    """The 25-minute mutation budget ran out inside a subprocess phase (TD 5.13)."""


class ProcSpec(NamedTuple):
    argv: list[str]
    cwd: str
    env: dict[str, str]
    timeout: float


class ProcResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def as_text(raw: bytes | str | None) -> str:
    """Partial output off a `TimeoutExpired`, which carries bytes even for a text-mode child."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw


class Runner(Protocol):
    """The seam for the four subprocess phases (repo-copy collect, `_enumerate`, `mutmut run`, `_collect`)."""

    def run(self, phase: str, spec: ProcSpec) -> ProcResult:
        """Run one phase's subprocess and report how it ended."""


class SubprocessRunner:
    """The real runner: a new session per child, SIGTERM then SIGKILL on timeout or interrupt (TD 5.13)."""

    def __init__(self, grace: float = KILL_GRACE_SECONDS) -> None:
        self.grace = grace

    def run(self, phase: str, spec: ProcSpec) -> ProcResult:
        proc = subprocess.Popen(
            spec.argv,
            cwd=spec.cwd,
            env=spec.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=max(spec.timeout, 0.0))
        except subprocess.TimeoutExpired:
            self.terminate(proc)
            out, err = self.drain(proc)
            return ProcResult(self.exit_code(proc), out, err, True)
        except BaseException:
            # An interrupt (KeyboardInterrupt, the SIGTERM handler's SystemExit) leaves no
            # child group behind: the same bounded kill as a timeout, then the interrupt goes on.
            self.terminate(proc)
            self.drain(proc)
            raise
        return ProcResult(proc.returncode, out, err, False)

    def terminate(self, proc: subprocess.Popen) -> None:
        """SIGTERM the group, then SIGKILL it whether or not the leader has gone.

        A group member can ignore SIGTERM and keep the output pipe open after the
        leader exits, so the leader's state says nothing about the group.
        """
        self.signal_group(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=self.grace)
        except subprocess.TimeoutExpired:
            pass
        self.signal_group(proc.pid, signal.SIGKILL)

    def drain(self, proc: subprocess.Popen) -> tuple[str, str]:
        """Collect what the killed child wrote, without waiting on a pipe a stray process holds."""
        try:
            return proc.communicate(timeout=self.grace)
        except subprocess.TimeoutExpired as exc:
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    pipe.close()
            return as_text(exc.output), as_text(exc.stderr)

    def exit_code(self, proc: subprocess.Popen) -> int:
        code = proc.poll()
        return -signal.SIGKILL if code is None else code

    def signal_group(self, pid: int, sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return


class Clock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utc_iso(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def epoch(self) -> int:
        return int(time.time())


class PlanOptions(NamedTuple):
    repo: Path
    gated_sha: str
    pr_head_sha: str
    pr: int | None
    coverage_file: Path
    meta_path: Path
    tests_result: str | None
    run_id: str | None
    run_attempt: int | None
    mode: str
    base_ref: str | None
    installed: Mapping[str, str]
    python: str
    python_exe: str
    environ: Mapping[str, str]
    keep_workspace: bool
    job_start_file: Path | None
    github_output: Path | None


class ShardOptions(NamedTuple):
    repo: Path
    gated_sha: str
    pr: int | None
    run_id: str | None
    run_attempt: int | None
    mode: str
    index: int
    plan_dir: Path
    installed: Mapping[str, str]
    python: str
    python_exe: str
    environ: Mapping[str, str]
    keep_workspace: bool
    job_start_file: Path | None


class VerdictInputs(NamedTuple):
    plan_dir: Path
    fragments_dir: Path
    plan_result: str
    shard_result: str
    gated_sha: str
    pr: int
    run_id: str
    run_attempt: int


class Workspace(NamedTuple):
    root: Path
    tree: Path
    plugin_dir: Path
    events: Path


class FileRun:
    """The state of one gated Python file while `plan` or `shard` works through its phases."""

    def __init__(self, record: dict[str, Any], text: str) -> None:
        self.record = record
        self.path: str = record["path"]
        self.text = text
        self.gated: list[int] = []
        self.statements: set[int] = set()
        self.selected: list[str] = []
        self.method = "none"
        self.findings: list[dict[str, Any]] = []
        self.logic_free = True
        self.workspace: Workspace | None = None
        self.mutant_names: list[str] = []
        self.gated_names: list[str] = []
        self.foreign_names: list[str] = []
        self.functions: dict[str, tuple[int, int]] = {}
        self.cost: dict[str, Any] | None = None
        self.status_by_key: dict[str, str] = {}
        self.to_shards = False
        self.workspace_seconds = 0.0
        self.done = False

    def add_fail(self, code: str, message: str) -> None:
        self.record["fail_reasons"].append(ncg.fail_reason(code, message))

    def block(self, code: str, message: str, reason: str) -> None:
        self.add_fail(code, message)
        self.record["mutation_reason"] = reason
        self.done = True

    def spend(self, since: float, clock: Clock) -> None:
        self.record["seconds"] = round(self.record["seconds"] + clock.monotonic() - since, 3)


class Context:
    """Everything `plan` or `shard` resolved before it touches a file (TD 5.2, 5.20.7)."""

    def __init__(
        self,
        opts: PlanOptions | ShardOptions,
        runner: Runner,
        clock: Clock,
        budget_seconds: int,
    ) -> None:
        self.opts = opts
        self.repo = opts.repo
        self.runner = runner
        self.clock = clock
        self.deadline = clock.monotonic() + budget_seconds
        self.label = ""
        self.durations: dict[str, int] = {}
        self.gated_sha = opts.gated_sha
        self.base_sha = ""
        self.meta: dict[str, Any] = {}
        self.cov: CoverageView | None = None
        self.tracked: list[str] = []
        self.modes: dict[str, str] = {}
        self.workspaces: list[Workspace] = []
        self.sources: dict[str, str | None] = {}
        self.internal_errors: list[dict[str, Any]] = []
        self.phase_seconds: dict[str, float] = {}
        self.expired_phase = ""
        self.expired_file = ""

    def spend_phase(self, phase: str, since: float) -> None:
        elapsed = self.clock.monotonic() - since
        self.phase_seconds[phase] = round(self.phase_seconds.get(phase, 0.0) + elapsed, 3)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def run_git(repo: Path, args: Sequence[str], fail: str | None = None) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise GateError(fail or f"git {args[0]} failed: {' '.join(tail)}")
    return proc.stdout


def git_text(repo: Path, args: Sequence[str], fail: str | None = None) -> str:
    return run_git(repo, args, fail).decode("utf-8")


def rev_parse(repo: Path, spec: str) -> str:
    return git_text(repo, ["rev-parse", spec], f"could not resolve {spec}").strip()


def blob_text(repo: Path, sha: str, path: str) -> str:
    return git_text(repo, ["show", f"{sha}:{path}"], f"could not read {path} at {sha[:12]}")


def tracked_modes(repo: Path, sha: str) -> dict[str, str]:
    """Git mode of every tracked path at `sha`, read before any blob is parsed (symlinks: 120000)."""
    out = run_git(repo, ["ls-tree", "-r", "-z", sha], f"could not list files at {sha[:12]}")
    return ncg.parse_tree_modes(out.decode("utf-8"))


def dirty_paths(porcelain_z: str) -> list[str]:
    """`.py` and `.sh` paths a `git status --porcelain -z` listing reports as changed."""
    entries = porcelain_z.split("\0")
    found = []
    pos = 0
    while pos < len(entries):
        entry = entries[pos]
        pos += 1
        if len(entry) < 4:
            continue
        found.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            found.append(entries[pos] if pos < len(entries) else "")
            pos += 1
    return [p for p in found if p.endswith((".py", ".sh"))]


def tree_dirty_paths(repo: Path) -> list[str]:
    out = git_text(repo, ["status", "--porcelain", "-z", "--untracked-files=no"])
    return dirty_paths(out)


# ---------------------------------------------------------------------------
# Sidecar, environment, coverage data
# ---------------------------------------------------------------------------


def installed_versions() -> dict[str, str]:
    versions = {}
    for name in ncg.PINNED:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "missing"
    return versions


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def valid_durations(value: Any) -> bool:
    """A map of node ID to non-negative integer milliseconds (a bool is not an integer here)."""
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
        for k, v in value.items()
    )


def read_durations(path: Path | None) -> tuple[dict[str, int] | None, str | None]:
    """The `tests` job's per-test milliseconds, clamped, or None and the reason they are unusable.

    A missing or unparseable file is not an error of `meta`: `tests` keeps its meaning, and
    `plan` fails closed on the null it finds in the sidecar (TD 5.20.4, SH-2, C3).
    """
    if path is None:
        return None, "no durations file was given"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, "durations file missing or unreadable"
    except ValueError:
        return None, "durations file is not valid JSON"
    if not valid_durations(raw):
        return None, "durations file is not a JSON object of node ID to non-negative integer"
    return {k: ncs.clamp_ms(v) for k, v in raw.items()}, None


def build_meta(
    repo: Path, coverage_file: Path, environ: Mapping[str, str], durations: Path | None = None
) -> dict[str, Any]:
    """The `meta` sidecar: which commit and tools the coverage data describes (TD 5.1)."""
    if not coverage_file.is_file():
        raise GateError(f"coverage file missing: {coverage_file.name}")
    dirty = tree_dirty_paths(repo)
    seconds, reason = read_durations(durations)
    sidecar = {
        "schema": ncg.SCHEMA_META,
        "head_sha": rev_parse(repo, "HEAD"),
        "head_tree": rev_parse(repo, "HEAD^{tree}"),
        "checkout_root": str(repo.resolve()),
        "clean": dirty == [],
        "dirty_paths": dirty[: ncg.MAX_SIDECAR_PATHS],
        "coverage_core": environ.get("COVERAGE_CORE"),
        "run_id": environ.get("GITHUB_RUN_ID") or None,
        "measured_sources": list(ncg.MEASURED_SOURCES),
        "tool_versions": installed_versions(),
        "python": python_version(),
        "test_seconds_ms": seconds,
    }
    if reason is not None:
        sidecar["test_seconds_reason"] = reason
    return sidecar


def load_meta(path: Path) -> dict[str, Any]:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"coverage sidecar missing or unreadable: {path.name}") from exc
    if not isinstance(meta, dict) or meta.get("schema") != ncg.SCHEMA_META:
        raise GateError(f"coverage sidecar has the wrong schema: {path.name}")
    return meta


class CoverageView:
    """Executed lines and test contexts, keyed by repo-relative path."""

    def __init__(self, data: Any, checkout_root: str) -> None:
        self.data = data
        prefix = checkout_root.rstrip("/") + "/"
        self.files = {f[len(prefix) :]: f for f in data.measured_files() if f.startswith(prefix)}

    def lines(self, rel: str) -> set[int]:
        found = self.files.get(rel)
        if found is None:
            return set()
        return set(self.data.lines(found) or [])

    def contexts_by_line(self, rel: str) -> dict[int, list[str]]:
        found = self.files.get(rel)
        if found is None:
            return {}
        return dict(self.data.contexts_by_lineno(found))


def open_coverage(path: Path, checkout_root: str) -> CoverageView:
    from coverage import CoverageData

    missing = "coverage data missing contexts"
    if not path.is_file():
        raise GateError(missing)
    data = CoverageData(basename=str(path))
    try:
        data.read()
        contexts = data.measured_contexts()
    except Exception as exc:
        raise GateError(missing) from exc
    if not any(contexts):
        raise GateError(missing)
    return CoverageView(data, checkout_root)


def fetch_rulings(pr: Any, head_sha: str, paths: Sequence[str]) -> list[dict[str, Any]]:
    """The single exception seam. S2 has no ruling input, so it is always empty (TD 5.12)."""
    return []


# ---------------------------------------------------------------------------
# Subprocess plumbing
# ---------------------------------------------------------------------------


def scrubbed_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The inherited environment minus CI credentials and any NCG_* variable."""
    return {
        k: v
        for k, v in environ.items()
        if k not in STRIPPED_ENV_NAMES and not k.startswith(STRIPPED_ENV_PREFIXES)
    }


def run_phase(
    ctx: Context, phase: str, argv: list[str], cwd: Path, env: dict[str, str]
) -> ProcResult:
    started = ctx.clock.monotonic()
    remaining = ctx.deadline - started
    if remaining <= 0:
        ctx.expired_phase = phase
        raise BudgetExpired(phase)
    result = ctx.runner.run(phase, ProcSpec(argv, str(cwd), env, remaining))
    ctx.spend_phase(phase, started)
    if result.timed_out:
        ctx.expired_phase = phase
        raise BudgetExpired(phase)
    return result


def child_env(ctx: Context) -> dict[str, str]:
    return scrubbed_env(ctx.opts.environ)


def child_argv(ctx: Context, phase: str, rel: str, extra: Sequence[str] = ()) -> list[str]:
    """The `-I -c ENTRY_SNIPPET` form (RV2-1): no checkout path is on the child's sys.path."""
    root = str(ctx.repo.resolve())
    return [ctx.opts.python_exe, "-I", "-c", ncg.ENTRY_SNIPPET, root, phase, "--file", rel, *extra]


def output_tail(output: str) -> str:
    return ncg.tail_text(output, OUTPUT_TAIL_LINES, OUTPUT_TAIL_CHARS)


def check_gate_file(gate_file: Any, ws: Workspace, ctx: Context) -> None:
    """R3-A: the child must have imported the gate from the checkout, never the workspace."""
    shown = str(gate_file)
    resolved = Path(shown).resolve()
    inside_checkout = resolved.is_relative_to(ctx.repo.resolve())
    inside_workspace = resolved.is_relative_to(ws.tree.resolve())
    if not inside_checkout or inside_workspace:
        raise GateError(f"gate subprocess imported from the workspace: {shown}")


def parse_child_json(result: ProcResult, schema: str, rel: str, failure: str) -> dict[str, Any]:
    try:
        doc = json.loads(result.stdout)
    except ValueError as exc:
        raise GateError(failure) from exc
    if result.returncode != 0 or not isinstance(doc, dict):
        raise GateError(failure)
    if doc.get("schema") != schema or doc.get("file") != rel:
        raise GateError(failure)
    return doc


def valid_names(names: Any, failure: str) -> list[str]:
    ok = isinstance(names, list) and all(
        isinstance(n, str) and ncg.check_mutant_key(n) for n in names
    )
    if not ok:
        raise GateError(failure)
    return list(names)


# ---------------------------------------------------------------------------
# Workspace (TD 5.8)
# ---------------------------------------------------------------------------


def contaminated(tree: Path) -> str | None:
    if (tree / "mutants").exists():
        return "mutants"
    for current, dirs, _files in os.walk(tree):
        if ".claude" in dirs:
            return str(Path(current, ".claude").relative_to(tree))
    return None


def extract_archive(ctx: Context, root: Path, tree: Path) -> None:
    tar_path = root / "tree.tar"
    run_git(
        ctx.repo,
        [
            "archive",
            "--format=tar",
            f"--output={tar_path}",
            ctx.gated_sha,
            "--",
            ".",
            ARCHIVE_EXCLUDE,
        ],
        "could not archive the gated tree",
    )
    tree.mkdir()
    with tarfile.open(tar_path) as tar:
        tar.extractall(tree, filter="data")
    tar_path.unlink()


def verify_extracted(ctx: Context, work: FileRun, tree: Path) -> None:
    """`git archive` honours export-ignore and export-subst, so check what the mutation run will execute.

    The gated file, the selected test modules and their conftests must hash to the
    committed blobs; a missing or rewritten one is a refusal, not a measurement.
    """
    tracked = set(ctx.tracked)
    paths = sorted(({work.path} | set(wanted_test_paths(work.selected))) & tracked)
    committed = git_text(ctx.repo, ["rev-parse", *[f"{ctx.gated_sha}:{p}" for p in paths]]).split()
    hashed = run_git(
        ctx.repo,
        ["hash-object", "--no-filters", "--", *[str(tree / p) for p in paths]],
        "could not hash the extracted workspace",
    )
    bad = ncg.blob_mismatches(
        dict(zip(paths, committed)), dict(zip(paths, hashed.decode().split()))
    )
    if bad:
        shown = ", ".join(bad[: ncg.MAX_BLOB_MISMATCHES])
        raise GateError(f"extracted workspace differs from the gated commit: {shown}")


def read_exact(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def write_exact(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def top_level_entries(tree: Path) -> tuple[list[str], list[str]]:
    dirs, files = [], []
    with os.scandir(tree) as scan:
        entries = sorted(scan, key=lambda e: e.name)
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            dirs.append(entry.name)
        elif entry.is_file(follow_symlinks=False):
            files.append(entry.name)
    return dirs, files


def write_mutmut_config(ctx: Context, work: FileRun, tree: Path) -> None:
    py_dirs = {p.split("/")[0] for p in ctx.tracked if p.endswith(".py") and "/" in p}
    source_paths = ncg.mutmut_source_paths(py_dirs, work.path)
    dirs, files = top_level_entries(tree)
    also_copy = ncg.mutmut_also_copy(dirs, files, source_paths)
    table = ncg.mutmut_table(source_paths, work.path, also_copy, work.selected)
    pyproject = tree / "pyproject.toml"
    head_text = read_exact(pyproject) if pyproject.exists() else ""
    write_exact(pyproject, ncg.compose_pyproject(head_text, table))


def make_workspace(ctx: Context, work: FileRun) -> Workspace:
    environ = ctx.opts.environ
    base = environ.get("RUNNER_TEMP") or environ.get("TMPDIR") or None
    root = Path(tempfile.mkdtemp(prefix="ncg-", dir=base)).resolve()
    tree = root / "workspace"
    plugin_dir = root / "ncg-plugin"
    ws = Workspace(root, tree, plugin_dir, plugin_dir / "events.jsonl")
    ctx.workspaces.append(ws)
    work.workspace = ws
    extract_archive(ctx, root, tree)
    bad = contaminated(tree)
    if bad is not None:
        raise GateError(f"workspace contaminated: {bad}")
    verify_extracted(ctx, work, tree)
    plugin_dir.mkdir()
    shutil.copyfile(ctx.repo / PLUGIN_RELPATH, plugin_dir / f"{PLUGIN_MODULE}.py")
    target = tree / work.path
    write_exact(target, ncg.strip_no_mutate_pragmas(read_exact(target)))
    write_mutmut_config(ctx, work, tree)
    return ws


def cleanup_workspaces(ctx: Context) -> None:
    if ctx.opts.keep_workspace:
        for ws in ctx.workspaces:
            print(f"kept workspace: {ws.root}", file=sys.stderr)
        return
    for ws in ctx.workspaces:
        shutil.rmtree(ws.root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Child phases: `_enumerate` and `_collect` (the only code that loads mutmut and libcst)
# ---------------------------------------------------------------------------


def require_mutmut_config(cwd: Path, rel: str) -> None:
    """A child refuses to run unless cwd is a generated workspace for exactly this file."""
    try:
        parsed = tomllib.loads((cwd / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GateError("child phase needs a workspace pyproject.toml") from exc
    if parsed.get("tool", {}).get("mutmut", {}).get("only_mutate") != [rel]:
        raise GateError(f"workspace only_mutate is not [{rel}]")


def find_original(module: Any, func_name: str, class_name: str | None) -> Any:
    """The top-level function, or the method of the named top-level class, in a libcst module."""
    import libcst as cst

    for child in module.body:
        if (
            class_name is None
            and isinstance(child, cst.FunctionDef)
            and child.name.value == func_name
        ):
            return child
        if (
            class_name is not None
            and isinstance(child, cst.ClassDef)
            and child.name.value == class_name
        ):
            if not isinstance(child.body, cst.IndentedBlock):
                return None
            for member in child.body.body:
                if isinstance(member, cst.FunctionDef) and member.name.value == func_name:
                    return member
    return None


def mutant_lines(original: str, name: str, orig_module: Any, mutated_module: Any) -> list[int]:
    """Original-side lines a mutant changes: swap its function into the original and diff (TD 5.9.2)."""
    from mutmut.mutation.diff_apply import read_mutant_function
    from mutmut.utils.format_utils import orig_function_and_class_names_from_key

    func_name, class_name = orig_function_and_class_names_from_key(name)
    target = find_original(orig_module, func_name.rpartition(".")[2], class_name)
    if target is None:
        return []
    replaced = orig_module.deep_replace(target, read_mutant_function(mutated_module, name))
    return ncg.changed_original_lines(original, replaced.code)


def scoped_mutant_lines(
    name: str,
    orig_module: Any,
    mutated_module: Any,
    positions: Any,
    rendered: dict[Any, tuple[int, str]],
) -> list[int]:
    """The same lines as `mutant_lines`, from diffing only the mutated function (ADR-2304 RV3-1).

    Every module line outside the target's rendering is identical in the two whole-module texts,
    so diffing the target's own rendering and offsetting by its first line gives the same set.
    `positions` must include the node's leading lines, as `code_for_node` renders them.
    """
    from mutmut.mutation.diff_apply import read_mutant_function
    from mutmut.utils.format_utils import orig_function_and_class_names_from_key

    func_name, class_name = orig_function_and_class_names_from_key(name)
    target = find_original(orig_module, func_name.rpartition(".")[2], class_name)
    if target is None:
        return []
    if target not in rendered:
        rendered[target] = (positions[target].start.line, orig_module.code_for_node(target))
    start, orig_text = rendered[target]
    mut_text = orig_module.code_for_node(read_mutant_function(mutated_module, name))
    return [start - 1 + n for n in ncg.changed_original_lines(orig_text, mut_text)]


def function_span(name: str, orig_module: Any, positions: Any) -> tuple[int, int] | None:
    """The 1-based original line span of the function a mutant belongs to (TD 5.9 step 2, C4).

    The start is the line `code_for_node` starts on, which includes leading blank and comment
    lines; the end is the last line of the function. Positions are end-exclusive when the
    function ends at a line break, which is the usual case.
    """
    from mutmut.utils.format_utils import orig_function_and_class_names_from_key

    func_name, class_name = orig_function_and_class_names_from_key(name)
    target = find_original(orig_module, func_name.rpartition(".")[2], class_name)
    if target is None:
        return None
    where = positions[target]
    end = where.end.line - 1 if where.end.column == 0 else where.end.line
    return where.start.line, end


class Generated(NamedTuple):
    """One file's mutmut output, parsed once: its text, mutant keys and both libcst trees."""

    original: str
    names: list[str]
    orig_module: Any
    mutated_module: Any
    positions: Any


def generate_mutants(rel: str, cwd: Path) -> Generated:
    """Run mutmut's own generation on the workspace copy of `rel` and parse both versions (TD 5.9.1)."""
    require_mutmut_config(cwd, rel)
    import libcst as cst
    from libcst.metadata import MetadataWrapper, WhitespaceInclusivePositionProvider
    from mutmut.configuration import reset_config
    from mutmut.mutation.file_mutation import mutate_file_contents
    from mutmut.utils.format_utils import get_mutant_name

    reset_config()
    original = read_exact(cwd / rel)
    mutated = mutate_file_contents(rel, original, covered_lines=None, coverage_excluded_lines=None)
    names = sorted(get_mutant_name(Path(rel), n) for n in mutated.mutant_names)
    orig_module = cst.parse_module(original)
    positions = MetadataWrapper(orig_module, unsafe_skip_copy=True).resolve(
        WhitespaceInclusivePositionProvider
    )
    return Generated(original, names, orig_module, cst.parse_module(mutated.code), positions)


def enumerate_child(rel: str, gated_lines: Sequence[int], cwd: Path) -> dict[str, Any]:
    """`_enumerate`: the file's full mutant set, and which mutants touch gated lines (TD 5.9.1-2)."""
    made = generate_mutants(rel, cwd)
    original, names, orig_module = made.original, made.names, made.orig_module
    statements, multiline = ncg.statement_map(original)
    rendered: dict[Any, tuple[int, str]] = {}
    gated, line_map, unmappable = [], {}, []
    spans: dict[str, tuple[int, int]] = {}
    for name in names:
        prefix = ncs.mutant_prefix(name)
        if prefix not in spans:
            span = function_span(name, orig_module, made.positions)
            if span is not None:
                spans[prefix] = span
        changed = scoped_mutant_lines(
            name, orig_module, made.mutated_module, made.positions, rendered
        )
        # A non-empty scoped result is final; an empty one falls back to the whole-module diff.
        changed = changed or mutant_lines(original, name, orig_module, made.mutated_module)
        lines = ncg.map_mutant_lines(changed, statements, multiline)
        line_map[name] = lines
        if not lines:
            unmappable.append(name)
        elif ncg.is_gated_mutant(lines, gated_lines):
            gated.append(name)
    return {
        "schema": ncg.SCHEMA_ENUM,
        "file": rel,
        "gate_file": str(Path(__file__).resolve()),
        "mutant_names": names,
        "gated_mutant_names": gated,
        "line_map": line_map,
        "unmappable": unmappable,
        "functions": [
            {"prefix": p, "start_line": a, "end_line": b} for p, (a, b) in sorted(spans.items())
        ],
    }


def collect_child(rel: str, cwd: Path) -> dict[str, Any]:
    """`_collect`: read `mutants/<rel>.meta` the way mutmut does (TD 5.9.7)."""
    require_mutmut_config(cwd, rel)
    from mutmut.configuration import reset_config
    from mutmut.mutation.data import SourceFileMutationData
    from mutmut.stats import status_by_exit_code

    reset_config()
    data = SourceFileMutationData(path=rel)
    if not data.meta_path.is_file():
        raise GateError(f"mutmut wrote no meta file for {rel}")
    data.load()
    codes = data.exit_code_by_key
    statuses = {k: (None if v is None else status_by_exit_code[v]) for k, v in codes.items()}
    return {
        "schema": ncg.SCHEMA_COLLECT,
        "file": rel,
        "gate_file": str(Path(__file__).resolve()),
        "exit_code_by_key": codes,
        "status_by_key": statuses,
    }


# ---------------------------------------------------------------------------
# plan: guards (TD 5.2)
# ---------------------------------------------------------------------------


def resolve_base(opts: PlanOptions) -> str:
    """CI gates the merge commit against its first parent; local runs use the merge base."""
    failed = "diff could not be computed"
    if opts.mode == "ci":
        return git_text(opts.repo, ["rev-parse", f"{opts.gated_sha}^1"], failed).strip()
    return git_text(opts.repo, ["merge-base", str(opts.base_ref), opts.gated_sha], failed).strip()


def require_regular_inputs(opts: PlanOptions) -> None:
    """The coverage data and sidecar must be regular files, never a link to somewhere else (RV-7)."""
    for path in (opts.coverage_file, opts.meta_path):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise GateError("coverage data missing contexts")


def build_context(opts: PlanOptions, runner: Runner, clock: Clock) -> Context:
    ctx = Context(opts, runner, clock, ncg.PLAN_BUDGET_SECONDS)
    message = ncg.check_pins(opts.installed)
    if message is None:
        require_regular_inputs(opts)
        ctx.meta = load_meta(opts.meta_path)
        if not valid_durations(ctx.meta.get("test_seconds_ms")):
            raise GateError(MSG_NO_DURATIONS)
        ctx.durations = ctx.meta["test_seconds_ms"]
        message = ncg.check_sidecar_environment(ctx.meta, opts.installed, opts.python)
    if message is None:
        ci_run = (opts.run_id or "") if opts.mode == "ci" else None
        message = ncg.check_sidecar_head(ctx.meta, opts.gated_sha, ci_run)
    if message is None and opts.mode == "ci":
        listing = git_text(opts.repo, ["rev-list", "--parents", "-n", "1", opts.gated_sha]).split()
        message = ncg.check_merge_parents(listing[1:], opts.pr_head_sha)
    if message is not None:
        raise GateError(message)
    ctx.cov = open_coverage(opts.coverage_file, ctx.meta["checkout_root"])
    ctx.base_sha = resolve_base(opts)
    ctx.modes = tracked_modes(opts.repo, opts.gated_sha)
    ctx.tracked = list(ctx.modes)
    return ctx


# ---------------------------------------------------------------------------
# measure: per-file phases
# ---------------------------------------------------------------------------


def blob_shas(ctx: Context, path: str) -> tuple[str, str | None]:
    blob = rev_parse(ctx.repo, f"{ctx.gated_sha}:{path}")
    try:
        head_blob: str | None = rev_parse(ctx.repo, f"{ctx.opts.pr_head_sha}:{path}")
    except GateError:
        head_blob = None
    return blob, head_blob


def changed_lines(ctx: Context, change: ncg.ChangedPath) -> list[int]:
    """Head-side changed lines of one file, from a diff limited to that file (and its rename source).

    One diff per file means the parser sees only `@@` lines of a single patch: a
    content line cannot forge the next file's header (F1). A changed file whose diff
    has no hunk is refused instead of read as "nothing changed".
    """
    paths = [change.path]
    if change.kind == "changed" and change.old_path:
        paths.insert(0, change.old_path)
    patch = git_text(
        ctx.repo,
        [*GIT_DIFF_PREFIX, "--unified=0", ctx.base_sha, ctx.gated_sha, "--", *paths],
        "diff could not be computed",
    )
    lines, hunks = ncg.parse_hunks(patch)
    if change.kind == "changed":
        base_blob = rev_parse(ctx.repo, f"{ctx.base_sha}:{change.old_path or change.path}")
        head_blob = rev_parse(ctx.repo, f"{ctx.gated_sha}:{change.path}")
        ncg.check_diff_complete(change.path, base_blob, head_blob, hunks)
    return lines


def prepare_python(ctx: Context, change: ncg.ChangedPath) -> FileRun:
    """Diff, statements and coverage for one gated Python file (TD 5.3, 5.4)."""
    assert ctx.cov is not None
    text = blob_text(ctx.repo, ctx.gated_sha, change.path)
    record = ncg.blank_file_record(change.path, str(change.kind))
    record["blob_sha"], record["pr_head_blob_sha"] = blob_shas(ctx, change.path)
    work = FileRun(record, text)
    statements, multiline = ncg.statement_map(text)
    work.statements = statements
    work.gated = ncg.gated_statement_lines(
        changed_lines(ctx, change), statements, multiline, change.kind == "new"
    )
    record.update(ncg.gated_lines_fields(work.gated))
    if not ncg.in_measured_surface(change.path, ctx.meta["measured_sources"]):
        record.update(ncg.coverage_fields(0, 0))
        work.block("not_measured", ncg.MSG_NOT_MEASURED, "blocked_by:not_measured")
        return work
    executed = len(ctx.cov.lines(change.path) & set(work.gated))
    record.update(ncg.coverage_fields(len(work.gated), executed))
    return work


def prepare_non_regular(ctx: Context, change: ncg.ChangedPath, scope: str, mode: str) -> FileRun:
    """A gated path that is not a regular file in git (a symlink, a gitlink) fails closed.

    Its content is never read as source (RV-2, RV2-4a): only the object ids are resolved.
    """
    code = str(ncg.mode_fail_code(mode))
    kind = "shell" if scope == "shell" else str(change.kind)
    record = ncg.blank_file_record(change.path, kind)
    record["blob_sha"], record["pr_head_blob_sha"] = blob_shas(ctx, change.path)
    work = FileRun(record, "")
    work.block(code, ncg.mode_message(mode), f"blocked_by:{code}")
    return work


def load_shell_rules() -> tuple[Any, Any]:
    """Import the shell counter without leaving its sys.path edit behind (RV2-2a).

    shell_logic_check puts its own directory at sys.path[0], and that directory holds
    unprotected files; restoring the path keeps a later top-level import (coverage) from
    resolving there.
    """
    saved = list(sys.path)
    try:
        from scripts.oversight.validators.shell_logic_check import decision_lines, is_hard_exempt
    finally:
        sys.path[:] = saved
    return decision_lines, is_hard_exempt


def prepare_shell(ctx: Context, change: ncg.ChangedPath) -> FileRun:
    """The shell rule (H1, H4): no added or edited counted decision construct (TD 5.11)."""
    decision_lines, is_hard_exempt = load_shell_rules()
    record = ncg.blank_file_record(change.path, "shell")
    record["blob_sha"], record["pr_head_blob_sha"] = blob_shas(ctx, change.path)
    record["mutation_reason"] = "not_python"
    work = FileRun(record, "")
    work.done = True
    head = ncg.split_lines(blob_text(ctx.repo, ctx.gated_sha, change.path))
    base: list[str] = []
    if change.kind != "new":
        base = ncg.split_lines(blob_text(ctx.repo, ctx.base_sha, change.old_path or change.path))
    shell, reasons = ncg.shell_gate(
        change.path,
        is_hard_exempt(change.path),
        decision_lines(head),
        decision_lines(base),
        changed_lines(ctx, change),
    )
    record["shell"] = shell
    record["fail_reasons"].extend(reasons)
    return work


def select_tests(ctx: Context, work: FileRun) -> None:
    """Coverage-context selection, with the name-match fallback (TD 5.6 steps 1-2)."""
    assert ctx.cov is not None
    ids = ncg.select_by_context(ctx.cov.contexts_by_line(work.path), work.gated)
    work.method = "context"
    if not ids:
        ids = ncg.name_fallback_ids(work.path, ctx.tracked)
        work.method = "name_fallback"
    ids = ncg.sanitize_node_ids(ids)
    work.selected = ids
    if not ids:
        work.method = "none"


def collect_repo_copy(ctx: Context, works: Sequence[FileRun]) -> None:
    """One collect-only run over every selection removes the tests that copy the repo (TD 5.6 step 3)."""
    union = sorted({n for w in works for n in w.selected})
    if not union:
        return
    argv = [ctx.opts.python_exe, "-m", "pytest", "--collect-only", "-q", "-m", "repo_copy"]
    argv += ["-o", "addopts=", "-p", "no:cacheprovider", "--", *union]
    result = run_phase(ctx, PHASE_REPO_COPY, argv, ctx.repo, scrubbed_env(ctx.opts.environ))
    collected = ncg.parse_repo_copy_collect(result.returncode, result.stdout)
    for work in works:
        work.selected, work.record["removed_repo_copy"] = ncg.remove_repo_copy(
            work.selected, collected
        )


def wanted_test_paths(selected: Sequence[str]) -> list[str]:
    """The selected test modules and every conftest above them."""
    wanted = []
    for node in selected:
        module = node.split("::")[0]
        wanted.append(module)
        parts = module.split("/")[:-1]
        wanted.extend("/".join([*parts[:i], "conftest.py"]) for i in range(len(parts) + 1))
    return wanted


def test_sources(ctx: Context, work: FileRun) -> dict[str, str]:
    """The selected test modules, their conftests and the shared loaders, read from the gated tree."""
    wanted = list(ncg.SHARED_LOADER_FILES) + wanted_test_paths(work.selected)
    found = {}
    for path in sorted(set(wanted)):
        if path not in ctx.sources:
            ctx.sources[path] = (
                blob_text(ctx.repo, ctx.gated_sha, path) if path in ctx.tracked else None
            )
        text = ctx.sources[path]
        if text is not None:
            found[path] = text
    return found


def analyze_python(ctx: Context, work: FileRun) -> None:
    """Decision logic, then the static path-load pre-check (TD 5.5, 5.7.1, 5.10)."""
    record = work.record
    work.findings = ncg.decision_logic_findings(work.text, work.gated)
    work.logic_free = not any(ncg.is_decision_logic(f) for f in work.findings)
    record.update(ncg.findings_fields(work.findings))
    record["unmutatable_gated_lines"] = ncg.unmutatable_gated_lines(work.text, work.gated)
    for reason in ncg.decision_fail_reasons(work.path, work.findings):
        work.add_fail(reason["code"], reason["message"])
    record.update(ncg.selection_fields(work.method, work.selected))
    if not work.selected:
        return
    found = ncg.static_path_load_findings(work.path, test_sources(ctx, work))
    if found:
        record["path_load_findings"] = found
        messages = [
            ncg.path_load_message(f["importer"], work.path, f["loaded_as"], f["via"]) for f in found
        ]
        work.block("path_loaded_module", "; ".join(messages), "path_load")


def build_workspace(ctx: Context, work: FileRun) -> Workspace:
    """A fresh workspace for the file, with its build time kept apart (TD 5.8)."""
    started = ctx.clock.monotonic()
    try:
        return make_workspace(ctx, work)
    finally:
        work.workspace_seconds = round(ctx.clock.monotonic() - started, 3)
        work.record["workspace_seconds"] = work.workspace_seconds
        ctx.spend_phase("workspace", started)


def parse_functions(raw: Any, failure: str) -> dict[str, tuple[int, int]]:
    """`_enumerate`'s function spans, as untrusted data: shaped prefixes and ordered positive lines."""
    if not isinstance(raw, list):
        raise GateError(failure)
    spans = {}
    for item in raw:
        ok = (
            isinstance(item, dict)
            and isinstance(item.get("prefix"), str)
            and ncg.check_function_prefix(item["prefix"])
            and all(
                isinstance(item.get(k), int) and not isinstance(item.get(k), bool)
                for k in LINE_KEYS
            )
            and 0 < item["start_line"] <= item["end_line"]
        )
        if not ok:
            raise GateError(failure)
        spans[item["prefix"]] = (item["start_line"], item["end_line"])
    return spans


def enumerate_file(ctx: Context, work: FileRun) -> None:
    """Build the workspace and list the file's gated mutants in a per-file subprocess (TD 5.9.1)."""
    ws = build_workspace(ctx, work)
    lines_file = ws.root / "gated-lines.json"
    lines_file.write_text(json.dumps(work.gated), encoding="utf-8")
    argv = child_argv(ctx, "_enumerate", work.path, ["--gated-lines-json", str(lines_file)])
    enum_started = ctx.clock.monotonic()
    try:
        result = run_phase(ctx, PHASE_ENUMERATE, argv, ws.tree, child_env(ctx))
    finally:
        work.record["enumerate_seconds"] = round(ctx.clock.monotonic() - enum_started, 3)
    failure = f"mutant enumeration failed: {work.path}"
    doc = parse_child_json(result, ncg.SCHEMA_ENUM, work.path, failure)
    check_gate_file(doc.get("gate_file"), ws, ctx)
    names = valid_names(doc.get("mutant_names"), failure)
    gated = valid_names(doc.get("gated_mutant_names"), failure)
    unmappable = valid_names(doc.get("unmappable"), failure)
    work.functions = parse_functions(doc.get("functions"), failure)
    if unmappable:
        raise GateError(f"mutant could not be mapped: {unmappable[0]}")
    if not set(gated) <= set(names):
        raise GateError(failure)
    work.mutant_names = names
    work.gated_names = sorted(gated)


def settle_selection(work: FileRun) -> None:
    """NQ-1: an empty selection passes only for a file with no gated mutants and no decision logic."""
    record = work.record
    zero = not work.gated_names
    reason = ncg.selection_reason(work.selected, zero, work.logic_free)
    if reason == "no_test_exercises":
        work.block(reason, f"no selected test exercises {work.path}", "selection_empty")
    elif reason == "zero_mutant_decision_logic":
        zero_reason = ncg.zero_mutant_reason(work.path, work.findings)
        assert zero_reason is not None
        work.add_fail(zero_reason["code"], zero_reason["message"])
        record["mutation_ran"] = True
        work.done = True
    elif zero:
        if not work.selected:
            record.update(ncg.selection_fields("not_required_zero_mutants", []))
        record["mutation_ran"] = True
        work.done = True


# ---------------------------------------------------------------------------
# measure: the mutation run (TD 5.9 steps 4-9)
# ---------------------------------------------------------------------------


def read_events(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def mutation_env(ctx: Context, work: FileRun, ws: Workspace) -> dict[str, str]:
    env = scrubbed_env(ctx.opts.environ)
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([str(ws.plugin_dir)] + ([inherited] if inherited else []))
    env["NCG_GATED_FILE"] = work.path
    env["NCG_CANONICAL"] = ncg.canonical_name(work.path)
    env["NCG_WORKSPACE"] = str(ws.tree)
    env["NCG_LOG"] = str(ws.events)
    return env


def plugin_path_ok(raw: Any, ws: Workspace) -> bool:
    resolved = Path(str(raw)).resolve()
    expected = (ws.plugin_dir / f"{PLUGIN_MODULE}.py").resolve()
    return resolved == expected and not resolved.is_relative_to(ws.tree.resolve())


def under_selection(node: str, selected: Sequence[str]) -> bool:
    return any(node == s or node.startswith(s + "::") for s in selected)


def check_integrity(
    events: Sequence[Mapping[str, Any]], ws: Workspace, selected: Sequence[str]
) -> None:
    """TD 5.9 step 5: nothing from the run is evidence unless these three checks hold."""
    loaded = [e for e in events if e.get("event") == "plugin_loaded"]
    if not loaded or not all(plugin_path_ok(e.get("path"), ws) for e in loaded):
        raise GateError("tripwire plugin not loaded from outside the workspace")
    if any(e.get("event") == "observer_error" for e in events):
        raise GateError("path-load recorder failed")
    ran = {str(e.get("node")) for e in events if e.get("event") == "executed"}
    stray = sorted(n for n in ran if not under_selection(n, selected))
    if stray:
        raise GateError(
            "mutation run executed unselected tests: " + ", ".join(stray[:MAX_BLOCKED_NAMES])
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def same_file(mutant: Path, original: Path) -> bool:
    """A copy equals its original: both are files (links followed) of one size and one sha256."""
    if not (mutant.is_file() and original.is_file()):
        return False
    if mutant.stat().st_size != original.stat().st_size:
        return False
    return sha256_file(mutant) == sha256_file(original)


def tree_files(root: Path, skip_top: str | None) -> dict[str, Path]:
    """Relative POSIX path -> path of every file or link under `root`, minus interpreter and pytest caches."""
    found = {}
    for current, dirs, files in os.walk(root):
        base = Path(current)
        pruned = [d for d in dirs if not ncg.is_mutmut_output_dir(d)]
        dirs[:] = [d for d in pruned if base != root or d != skip_top]
        for name in files + [d for d in dirs if (base / d).is_symlink()]:
            path = base / name
            found[path.relative_to(root).as_posix()] = path
    return found


def workspace_changes(tree: Path, gated: str) -> list[str]:
    """Paths whose copy under `<tree>/mutants/` was added, changed or removed (RV3-7b), sorted.

    mutmut copies every file of the workspace into `mutants/` (source paths, `also_copy`, tests,
    config), so each regular original must have an equal copy and every copy an original.
    """
    root = tree / "mutants"
    if root.is_symlink():
        return ["mutants"]
    if not root.exists():
        # mutmut stopped before it made `mutants/`: nothing ran, so nothing was corrupted, and the
        # exit code and output say why it stopped (TD 5.9 step 6, rule 7).
        return []
    skip = ncg.mutmut_output_paths(gated)
    copies = tree_files(root, None)
    originals = tree_files(tree, "mutants")
    changed = {
        rel for rel, path in copies.items() if rel not in skip and not same_file(path, tree / rel)
    }
    missing = {
        rel
        for rel, path in originals.items()
        if rel not in skip and not path.is_symlink() and rel not in copies
    }
    return sorted(changed | missing)


def check_workspace_unchanged(ws: Workspace, gated: str) -> None:
    """TD 5.9 step 5.4: a mutant that writes into `mutants/` corrupts every later mutant's tests.

    A failing test reads as `killed`, so a corrupted tree inflates the score (a false pass):
    the run is refused, never scored.
    """
    changed = workspace_changes(ws.tree, gated)
    if changed:
        shown = ", ".join(
            ncg.bound_text(p, ncg.MAX_PATH_CHARS) for p in changed[:MAX_BLOCKED_NAMES]
        )
        raise GateError(f"mutation run modified the workspace: {shown}")


def runtime_findings(events: Sequence[Mapping[str, Any]], work: FileRun) -> list[dict[str, str]]:
    found = []
    for event in events:
        if event.get("event") != "path_load":
            continue
        found.append(
            {
                "importer": ncg.bound_text(str(event.get("importer")), ncg.MAX_PATH_CHARS),
                "loaded_as": ncg.bound_text(str(event.get("loaded_as")), ncg.MAX_PATH_CHARS),
                "canonical": ncg.canonical_name(work.path),
                "via": f"runtime:{event.get('kind')}",
                "phase": ncg.bound_text(str(event.get("phase")), ncg.MAX_PATH_CHARS),
            }
        )
    return found


def trampoline_message(work: FileRun, found: Sequence[Mapping[str, str]]) -> str:
    if found:
        return "; ".join(
            ncg.path_load_message(f["importer"], work.path, f["loaded_as"], f["via"]) for f in found
        )
    modules = sorted({n.split("::")[0] for n in work.selected})
    return (
        f"mutmut found trampoline hits that match no mutant key, so a selected test loads {work.path} under a "
        f"non-canonical name; candidate importers: {', '.join(modules)} — {ncg.MSG_PATH_LOAD_FIX}"
    )


def isolation_stage(output: str) -> str | None:
    if ncg.MUTMUT_STATS_FAILED_MESSAGE in output:
        return "stats"
    if ncg.MUTMUT_CLEAN_FAILED_MESSAGE in output:
        return "clean"
    return None


def fail_run(work: FileRun, code: str, message: str) -> None:
    work.block(code, message, f"blocked_by:{code}")


def attribute_failure(ctx: Context, work: FileRun, result: ProcResult, output: str) -> None:
    """TD 5.9 step 6, rules 4 to 7: what a non-zero mutmut exit means."""
    if ncg.MUTMUT_NO_TEST_CASE_MESSAGE in output:
        record_mutants(ctx, work, True)
        return
    stage = isolation_stage(output)
    failed = ncg.parse_short_summary(output)
    if stage is not None and failed and all(ncg.is_attributable(n, work.selected) for n in failed):
        work.record["isolation_failure"] = ncg.isolation_failure(stage, failed, output)
        fail_run(
            work,
            "selected_test_fails_in_isolation",
            f"{', '.join(failed)} failed in the {stage} run: this test fails when run alone in the mutation workspace",
        )
        return
    entry = {"code": "mutmut_failed", "message": f"mutmut exited {result.returncode}"}
    if stage is not None:
        entry = {
            "code": "clean_run_unattributed",
            "message": "clean run failed and no selected test could be identified",
            "stage": stage,
        }
    ctx.internal_errors.append({**entry, "file": work.path, "output_tail": output_tail(output)})
    work.record["mutation_reason"] = "internal_error"
    work.done = True


def record_mutants(ctx: Context, work: FileRun, expect_unrun: bool) -> None:
    """Read mutmut's results back in a `_collect` subprocess and classify them (TD 5.9 steps 7, 8).

    The gated names here are the shard's own; the file is scored by the merge, over every shard.
    """
    ws = work.workspace
    assert ws is not None
    started = ctx.clock.monotonic()
    try:
        result = run_phase(
            ctx, PHASE_COLLECT, child_argv(ctx, "_collect", work.path), ws.tree, child_env(ctx)
        )
    finally:
        work.record["collect_seconds"] = round(ctx.clock.monotonic() - started, 3)
    unreadable = f"mutation results could not be read: {work.path}"
    doc = parse_child_json(result, ncg.SCHEMA_COLLECT, work.path, unreadable)
    check_gate_file(doc.get("gate_file"), ws, ctx)
    codes = doc.get("exit_code_by_key")
    statuses = doc.get("status_by_key")
    if not isinstance(codes, dict) or not isinstance(statuses, dict):
        raise GateError(unreadable)
    valid_names(list(codes), unreadable)
    drift = f"{ctx.label}: mutant enumeration drift: {work.path}"
    if set(codes) != set(work.mutant_names) or set(statuses) != set(codes):
        raise GateError(drift)
    for key in work.gated_names:
        if (codes[key] is None) != expect_unrun:
            raise GateError(drift)
    if any(codes[key] is not None for key in work.foreign_names):
        raise GateError(f"{ctx.label}: a mutant of another shard ran: {work.path}")
    by_key = {k: "no tests" for k in work.gated_names} if expect_unrun else statuses
    work.status_by_key = {k: by_key[k] for k in work.gated_names}
    work.record.update(ncg.classify_statuses(by_key, work.gated_names))
    work.record["mutation_ran"] = True
    work.done = True


def mutate_file(ctx: Context, work: FileRun) -> None:
    """One `mutmut run` for the file, then every check that interprets it (TD 5.9 steps 4 to 8)."""
    ws = work.workspace
    assert ws is not None
    argv = [ctx.opts.python_exe, "-m", "mutmut", "run", *work.gated_names]
    started = ctx.clock.monotonic()
    try:
        result = run_phase(ctx, PHASE_MUTMUT, argv, ws.tree, mutation_env(ctx, work, ws))
    finally:
        work.record["mutmut_seconds"] = round(ctx.clock.monotonic() - started, 3)
    events = read_events(ws.events)
    check_integrity(events, ws, work.selected)
    check_workspace_unchanged(ws, work.path)
    output = ncg.ANSI_RE.sub("", result.stdout + "\n" + result.stderr)
    copies = sorted({str(e.get("node")) for e in events if e.get("event") == "repo_copy"})
    found = runtime_findings(events, work)
    if copies:
        fail_run(
            work,
            "unmarked_repo_copy",
            f"{', '.join(copies)} copies the repository; mark it @pytest.mark.repo_copy",
        )
    elif found or ncg.MUTMUT_TRAMPOLINE_MESSAGE in output:
        work.record["path_load_findings"] = found
        work.block("path_loaded_module", trampoline_message(work, found), "path_load")
    elif result.returncode != 0:
        attribute_failure(ctx, work, result, output)
    else:
        record_mutants(ctx, work, False)


# ---------------------------------------------------------------------------
# Orchestration shared by plan and shard
# ---------------------------------------------------------------------------


def mark_timeout(work: FileRun, message: str) -> None:
    work.record["mutation_ran"] = False
    work.record["mutation_reason"] = "timeout"
    work.add_fail("mutation_timeout", message)
    work.done = True


def release_workspace(ctx: Context, work: FileRun) -> None:
    """Delete (or, with --keep-workspace, report) a file's workspace as soon as the file is finished."""
    ws = work.workspace
    if ws is None:
        return
    work.workspace = None
    ctx.workspaces.remove(ws)
    if ctx.opts.keep_workspace:
        print(f"kept workspace: {ws.root}", file=sys.stderr)
        return
    shutil.rmtree(ws.root, ignore_errors=True)


def release_if_done(ctx: Context, work: FileRun) -> None:
    if work.done:
        release_workspace(ctx, work)


def error_text(exc: Exception) -> str:
    if isinstance(exc, GateError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def guarded(ctx: Context, work: FileRun, step: Any) -> None:
    """Run one per-file step; a gate-internal failure is recorded and the other files carry on."""
    started = ctx.clock.monotonic()
    try:
        step(ctx, work)
    except BudgetExpired:
        ctx.expired_file = work.path
        work.spend(started, ctx.clock)
        raise
    except Exception as exc:
        ctx.internal_errors.append(
            {"code": "internal_error", "message": error_text(exc), "file": work.path}
        )
        work.record["mutation_reason"] = "internal_error"
        work.done = True
    work.spend(started, ctx.clock)
    release_if_done(ctx, work)


def job_start_seconds(path: Path | None) -> int | None:
    """The epoch second a job's first step wrote, or None when the file is missing or not a number (SH-11)."""
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(text) if text.isascii() and text.isdigit() else None


def job_seconds(path: Path | None, clock: Clock) -> int | None:
    """This process's finish time minus the job's start time: display data, never an error (SH-11)."""
    start = job_start_seconds(path)
    return None if start is None else clock.epoch() - start


def sole_file(directory: Path, filename: str) -> Path | None:
    """`directory/filename` when it is the directory's only entry and a regular file, else None."""
    try:
        names = sorted(entry.name for entry in directory.iterdir())
    except OSError:
        return None
    path = directory / filename
    if names != [filename] or path.is_symlink() or not path.is_file():
        return None
    return path


def read_json_file(path: Path) -> Any:
    """Parsed JSON, or None when the file cannot be read or parsed (the caller reports it)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# plan: the cheap phase, the cost model and the plan document (TD 5.20.1 to 5.20.6)
# ---------------------------------------------------------------------------


def cheap_phase(ctx: Context, works: Sequence[FileRun]) -> None:
    for work in [w for w in works if not w.done]:
        guarded(ctx, work, select_tests)
    py = [w for w in works if not w.done]
    collect_repo_copy(ctx, py)
    for work in py:
        guarded(ctx, work, analyze_python)
    for work in [w for w in py if not w.done]:
        guarded(ctx, work, enumerate_file)
        if not work.done:
            settle_selection(work)
            work.to_shards = not work.done
            release_workspace(ctx, work)


def prepare_files(ctx: Context) -> list[FileRun]:
    repo, gated, base = ctx.repo, ctx.gated_sha, ctx.base_sha
    names = git_text(
        repo, [*GIT_DIFF_PREFIX, "--name-status", base, gated], "diff could not be computed"
    )
    works = []
    for change in sorted(ncg.parse_name_status(names), key=lambda c: c.path):
        scope = ncg.scope_of(change.path)
        if change.kind is None or scope is None:
            continue
        mode = ctx.modes.get(change.path)
        if mode is None:
            shown = ncg.bound_text(change.path, ncg.MAX_PATH_CHARS)
            raise GateError(f"tree listing and diff disagree: {shown}")
        if ncg.mode_fail_code(mode) is not None:
            works.append(prepare_non_regular(ctx, change, scope, mode))
        elif scope == "python":
            works.append(prepare_python(ctx, change))
        else:
            works.append(prepare_shell(ctx, change))
    return works


def plan_timeout_message(ctx: Context, works: Sequence[FileRun]) -> str:
    """Where the plan's budget went: the phase and file that ran out, then phase and file totals (M6)."""
    where = ctx.expired_phase or "an unrecorded phase"
    if ctx.expired_file:
        where += f" of {ctx.expired_file}"
    seconds = {w.path: (w.record["seconds"], w.workspace_seconds) for w in works}
    return ncg.timeout_message(ctx.phase_seconds, seconds, where, ncg.MSG_PLAN_TIMEOUT)


def plan_files(ctx: Context) -> list[FileRun]:
    """The cheap phase for every file. A file it did not reach is not sent to a shard (TD 5.20.10)."""
    works: list[FileRun] = []
    try:
        works = prepare_files(ctx)
        cheap_phase(ctx, works)
    except BudgetExpired:
        pass
    message = plan_timeout_message(ctx, works)
    for work in works:
        if not work.done and not work.to_shards:
            mark_timeout(work, message)
        work.record["fail_reasons"].sort(key=lambda r: ncg.FAIL_ORDER.index(r["code"]))
    return works


def lines_by_context(contexts_by_line: Mapping[int, Sequence[str]]) -> dict[str, set[int]]:
    """Invert the coverage contexts: for each test ID, the file lines it executed."""
    found: dict[str, set[int]] = {}
    for line, contexts in contexts_by_line.items():
        for test_id in ncg.contexts_to_node_ids(contexts):
            found.setdefault(test_id, set()).add(line)
    return found


def cost_files(ctx: Context, works: Sequence[FileRun]) -> None:
    """The per-function fan-in cost of every file that goes to a shard (TD 5.20.4)."""
    assert ctx.cov is not None
    for work in [w for w in works if w.to_shards]:
        executed = ncs.executed_by_selected(
            work.selected, lines_by_context(ctx.cov.contexts_by_line(work.path))
        )
        try:
            work.cost = ncs.file_cost(
                work.path,
                work.selected,
                work.method,
                ctx.durations,
                work.functions,
                work.gated_names,
                executed,
            )
        except GateError as exc:
            ctx.internal_errors.append(
                {"code": "internal_error", "message": str(exc), "file": work.path}
            )


def plan_record(work: FileRun, sharded: bool) -> dict[str, Any]:
    """A file's cheap-phase record plus what the shards and the merge need (TD 5.20.6)."""
    rec = dict(work.record)
    cost = work.cost or {"function_cost_ms": {}, "W_F_ms": 0, "fixed_est_ms": 0, "cost_ms": 0}
    rec.update(
        mutant_names=list(work.mutant_names),
        gated_mutant_names=list(work.gated_names),
        selection_full=list(work.selected),
        to_shards=sharded and work.to_shards,
        **cost,
    )
    return rec


def plan_document(
    opts: PlanOptions,
    ctx: Context | None,
    works: Sequence[FileRun],
    errors: list[dict[str, Any]],
    timing: dict[str, Any],
) -> dict[str, Any]:
    """The plan: binding, cost, N and the assignment. With any internal error nothing is sharded."""
    files = sorted((plan_record(w, not errors) for w in works), key=lambda r: r["path"])
    lay = ncs.layout(files)
    gated_tree = rev_parse(opts.repo, f"{opts.gated_sha}^{{tree}}") if ctx is not None else None
    doc = {
        "schema": ncg.SCHEMA_PLAN,
        "gate_version": ncg.GATE_VERSION,
        "binding": {
            "mode": opts.mode,
            "gated_sha": opts.gated_sha,
            "pr_head_sha": opts.pr_head_sha,
            "base_sha": ctx.base_sha if ctx is not None else None,
            "gated_tree": gated_tree,
            "pr": opts.pr,
            "run_id": opts.run_id,
            "run_attempt": opts.run_attempt,
        },
        "tool_versions": dict(opts.installed),
        "python": opts.python,
        "coverage_core": ctx.meta.get("coverage_core") if ctx is not None else None,
        "constants": ncs.plan_constants(),
        "files": files,
        "W_ms": lay["W_ms"],
        "W_ci_minutes": ncs.ci_minutes(lay["W_ms"]),
        "N": lay["N"],
        "capped": lay["capped"],
        "assignment": lay["assignment"],
        "internal_errors": errors,
        **timing,
    }
    doc["plan_hash"] = ncs.plan_hash(doc)
    return doc


def plan(opts: PlanOptions, runner: Runner, clock: Clock) -> tuple[dict[str, Any], int]:
    """The cheap phase once, then the cost, N and the assignment. Exit 0 when the plan is complete, else 3."""
    started_at = clock.utc_iso()
    t0 = clock.monotonic()
    ctx: Context | None = None
    works: list[FileRun] = []
    errors: list[dict[str, Any]] = []
    if opts.tests_result not in (None, "success"):
        errors.append({"code": "upstream", "message": MSG_UPSTREAM + str(opts.tests_result)})
    else:
        try:
            # The plan's workspaces are throwaway; --keep-workspace keeps the shards' only.
            ctx = build_context(opts._replace(keep_workspace=False), runner, clock)
            works = plan_files(ctx)
            cost_files(ctx, works)
            errors = list(ctx.internal_errors)
        except Exception as exc:
            errors = [] if ctx is None else list(ctx.internal_errors)
            errors.append({"code": "internal_error", "message": error_text(exc)})
        finally:
            if ctx is not None:
                cleanup_workspaces(ctx)
    timing = {
        "started_at": started_at,
        "finished_at": clock.utc_iso(),
        "seconds": round(clock.monotonic() - t0, 3),
        "job_seconds": job_seconds(opts.job_start_file, clock),
    }
    return plan_document(opts, ctx, works, errors, timing), 3 if errors else 0


def write_job_outputs(path: Path, doc: Mapping[str, Any]) -> None:
    """Append `count` and `shards` to the runner's job-output file, after the plan is written (TD 5.20.1)."""
    count = doc["N"]
    if not 1 <= count <= ncs.N_MAX:
        raise GateError(f"shard count {count} is outside 1..{ncs.N_MAX}")
    shards = json.dumps(list(range(1, count + 1)), separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"count={count}\nshards={shards}\n")


# ---------------------------------------------------------------------------
# shard: one share of the mutation run (TD 5.20.7, 5.20.8)
# ---------------------------------------------------------------------------


def load_shard_plan(opts: ShardOptions) -> dict[str, Any]:
    """The plan this shard runs, after every check that proves it is this run's and untouched (TD 5.20.7)."""
    where = f"shard {opts.index}"
    path = sole_file(opts.plan_dir, PLAN_FILENAME)
    if path is None:
        raise GateError(
            f"{where}: the plan directory must hold exactly {PLAN_FILENAME}, as a regular file"
        )
    plan_doc = read_json_file(path)
    error = ncs.plan_shape_error(plan_doc)
    if error is not None:
        raise GateError(f"{where}: {error}")
    where = f"shard {opts.index} of {plan_doc['N']}"
    unbound = ncg.check_records_binding(
        plan_doc["binding"], opts.mode, opts.gated_sha, opts.pr, opts.run_id, opts.run_attempt
    )
    refusals = [
        (plan_doc["plan_hash"] != ncs.plan_hash(plan_doc), "plan_hash does not match the plan"),
        (bool(plan_doc["internal_errors"]), "the plan has internal errors"),
        (unbound is not None, str(unbound)),
        (not 1 <= opts.index <= plan_doc["N"], "the shard index is outside the plan"),
        (rev_parse(opts.repo, "HEAD") != opts.gated_sha, "HEAD is not the gated commit"),
        (dict(opts.installed) != plan_doc["tool_versions"], "tool versions differ from the plan's"),
        (opts.python != plan_doc["python"], "python differs from the plan's"),
    ]
    for refused, message in refusals:
        if refused:
            raise GateError(f"{where}: {message}")
    return plan_doc


def assigned_works(plan_doc: Mapping[str, Any], index: int) -> list[FileRun]:
    """One file run per file with mutants assigned to this shard, in path order."""
    by_path = {f["path"]: f for f in plan_doc["files"]}
    assignment = plan_doc["assignment"]
    if (
        len(assignment) != plan_doc["N"]
        or not 1 <= index <= len(assignment)
        or assignment[index - 1]["index"] != index
    ):
        raise GateError(
            f"plan assignment does not hold shard {index} at position {index} of {plan_doc['N']}"
        )
    shard = assignment[index - 1]
    works = []
    for member in sorted(shard["members"], key=lambda m: m["path"]):
        rec = by_path.get(member["path"])
        if rec is None or not rec["to_shards"]:
            raise GateError(
                f"plan assigns shard {index} a file it does not shard: {member['path']}"
            )
        work = FileRun(ncg.blank_file_record(rec["path"], rec["kind"]), "")
        work.selected = list(rec["selection_full"])
        work.method = rec["selection_method"]
        work.mutant_names = list(rec["mutant_names"])
        work.gated_names = sorted(member["names"])
        work.foreign_names = sorted(set(rec["gated_mutant_names"]) - set(member["names"]))
        works.append(work)
    return works


def shard_file(ctx: Context, work: FileRun) -> None:
    """A fresh workspace, then the file's assigned mutants (TD 5.8 per (shard, file))."""
    build_workspace(ctx, work)
    mutate_file(ctx, work)


def run_assigned(ctx: Context, works: Sequence[FileRun]) -> bool:
    """Mutate each assigned file in turn; True if the shard's budget ran out first."""
    try:
        for work in works:
            guarded(ctx, work, shard_file)
    except BudgetExpired:
        return True
    return False


def fragment_entry(work: FileRun, errored: set[str]) -> dict[str, Any]:
    """One assigned file's result in the fragment. Only the shard-time reasons travel (TD 5.20.8)."""
    rec = work.record
    reasons = [r for r in rec["fail_reasons"] if r["code"] in ncs.SHARD_FAIL_CODES]
    finished = work.done and work.path not in errored
    scored = finished and not reasons
    reason = rec["mutation_reason"]
    return {
        "path": work.path,
        "assigned": len(work.gated_names),
        "status_by_key": dict(work.status_by_key) if scored else {},
        "killed": rec["mutants_killed"] if scored else 0,
        "total": rec["mutants_total"] if scored else 0,
        "mutant_status_counts": dict(rec["mutant_status_counts"]) if scored else {},
        "fail_reasons": reasons,
        "mutation_reason": reason if reason in ncs.SHARD_REASONS else None,
        "path_load_findings": rec["path_load_findings"],
        "isolation_failure": rec["isolation_failure"],
        "workspace_seconds": rec["workspace_seconds"],
        "mutmut_seconds": rec["mutmut_seconds"],
        "collect_seconds": rec["collect_seconds"],
        "seconds": rec["seconds"],
        "finished": finished,
    }


def shard_timeout(ctx: Context, works: Sequence[FileRun]) -> dict[str, str]:
    where = ctx.expired_phase or "an unrecorded phase"
    seconds = {w.path: (w.record["seconds"], w.workspace_seconds) for w in works}
    text = ncg.timeout_message(ctx.phase_seconds, seconds, where, f"{ctx.label} overran its budget")
    return {
        "phase": ctx.expired_phase,
        "file": ctx.expired_file,
        "message": ncg.bound_text(text, ncg.MAX_MESSAGE_CHARS),
    }


def fragment_document(
    opts: ShardOptions,
    plan_doc: Mapping[str, Any] | None,
    entries: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    timeout: dict[str, str] | None,
    timing: dict[str, Any],
) -> dict[str, Any]:
    doc = {
        "schema": ncg.SCHEMA_FRAGMENT,
        "binding": {
            "gated_sha": opts.gated_sha,
            "pr": opts.pr,
            "run_id": opts.run_id,
            "run_attempt": opts.run_attempt,
            "index": opts.index,
            "N": plan_doc["N"] if plan_doc is not None else None,
            "plan_hash": plan_doc["plan_hash"] if plan_doc is not None else None,
        },
        "status": "internal_error" if errors else "timeout" if timeout else "complete",
        "timeout": None if errors else timeout,
        "internal_errors": errors,
        "files": entries,
        **timing,
    }
    doc["fragment_sha256"] = ncs.fragment_hash(doc)
    return doc


def run_shard(opts: ShardOptions, runner: Runner, clock: Clock) -> tuple[dict[str, Any], int]:
    """Mutate this shard's assigned mutants. Exit 0 for a complete or timed-out fragment, 3 on an internal error."""
    started_at = clock.utc_iso()
    t0 = clock.monotonic()
    plan_doc: dict[str, Any] | None = None
    ctx: Context | None = None
    works: list[FileRun] = []
    errors: list[dict[str, Any]] = []
    timeout = None
    try:
        plan_doc = load_shard_plan(opts)
        ctx = Context(opts, runner, clock, ncg.BUDGET_SECONDS)
        ctx.deadline = t0 + ncg.BUDGET_SECONDS
        ctx.label = f"shard {opts.index} of {plan_doc['N']}"
        ctx.modes = tracked_modes(opts.repo, opts.gated_sha)
        ctx.tracked = list(ctx.modes)
        works = assigned_works(plan_doc, opts.index)
        if run_assigned(ctx, works):
            timeout = shard_timeout(ctx, works)
        errors = list(ctx.internal_errors)
    except Exception as exc:
        errors = [] if ctx is None else list(ctx.internal_errors)
        errors.append({"code": "internal_error", "message": error_text(exc)})
    finally:
        if ctx is not None:
            cleanup_workspaces(ctx)
    errored = {e["file"] for e in errors if e.get("file")}
    timing = {
        "started_at": started_at,
        "finished_at": clock.utc_iso(),
        "seconds": round(clock.monotonic() - t0, 3),
        "job_seconds": job_seconds(opts.job_start_file, clock),
    }
    entries = [fragment_entry(w, errored) for w in works]
    doc = fragment_document(opts, plan_doc, entries, errors, timeout, timing)
    return doc, 3 if errors else 0


# ---------------------------------------------------------------------------
# verdict: merge the fragments and decide (TD 5.14, 5.20.9)
# ---------------------------------------------------------------------------


def read_fragments(fragments_dir: Path) -> dict[str, Any]:
    """Each entry of the fragments directory: its document, None if unreadable, or why the entry is wrong."""
    try:
        entries = sorted(fragments_dir.iterdir(), key=lambda e: e.name)
    except OSError:
        return {}
    found: dict[str, Any] = {}
    for entry in entries:
        path = (
            None
            if entry.is_symlink() or not entry.is_dir()
            else sole_file(entry, FRAGMENT_FILENAME)
        )
        if path is None:
            found[entry.name] = f"must be a directory holding exactly {FRAGMENT_FILENAME}"
        else:
            found[entry.name] = read_json_file(path)
    return found


def merge_records(
    plan_dir: Path,
    fragments_dir: Path,
    results: tuple[str, str],
    binding: Mapping[str, Any],
    clock: Clock,
) -> dict[str, Any]:
    """Read the plan and the fragments, merge them, and stamp the gate's own seconds (TD 5.20.11)."""
    started_at = clock.utc_iso()
    t0 = clock.monotonic()
    plan_path = sole_file(plan_dir, PLAN_FILENAME)
    plan_doc = None if plan_path is None else read_json_file(plan_path)
    records, _problems = ncs.merge(
        plan_doc, read_fragments(fragments_dir), results[0], results[1], binding
    )
    seconds = round(clock.monotonic() - t0, 3)
    records.update(
        started_at=started_at,
        finished_at=clock.utc_iso(),
        seconds=seconds,
        merge_verdict_seconds=seconds,
    )
    records["runner_minutes_total"] = ncs.runner_minutes_total(records, seconds)
    return records


def build_verdict(records: Mapping[str, Any]) -> tuple[dict[str, Any], str, int]:
    paths = [f["path"] for f in records["files"]]
    rulings = fetch_rulings(records.get("pr"), str(records.get("pr_head_sha")), paths)
    decision = ncg.decide(records, rulings, ncg.THRESHOLDS)
    doc = ncg.verdict_document(records, decision)
    return doc, ncg.render_summary(doc), decision["exit_code"]


def verdict(
    inputs: VerdictInputs, records_out: Path, out: Path, summary: Path, clock: Clock
) -> int:
    binding = {
        "mode": "ci",
        "gated_sha": inputs.gated_sha,
        "pr": inputs.pr,
        "run_id": inputs.run_id,
        "run_attempt": inputs.run_attempt,
    }
    results = (inputs.plan_result, inputs.shard_result)
    records = merge_records(inputs.plan_dir, inputs.fragments_dir, results, binding, clock)
    doc, text, code = build_verdict(records)
    write_json(records_out, records)
    write_json(out, doc)
    write_text_atomic(summary, text)
    return code


def write_text_atomic(path: Path, text: str) -> None:
    """Write `path` through a temp file in its directory and `os.replace` (RV2-4c).

    The parent is created. An existing symlink at `path` is replaced, never followed,
    and a reader never sees a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def write_json(path: Path, doc: Mapping[str, Any]) -> None:
    write_text_atomic(path, json.dumps(doc, indent=2, ensure_ascii=True) + "\n")


# ---------------------------------------------------------------------------
# run: the whole pipeline in one local process (TD 5.20.2)
# ---------------------------------------------------------------------------


class ShardRun(NamedTuple):
    """The plan and the fragments `run_shards` wrote, laid out as the CI downloads are."""

    plan: dict[str, Any]
    plan_code: int
    fragments: list[dict[str, Any]]
    shards_ok: bool


class LocalRun(NamedTuple):
    records: dict[str, Any]
    verdict: dict[str, Any]
    summary: str
    code: int
    shard_run: ShardRun


def shard_options(opts: PlanOptions, index: int, plan_dir: Path) -> ShardOptions:
    return ShardOptions(
        repo=opts.repo,
        gated_sha=opts.gated_sha,
        pr=opts.pr,
        run_id=opts.run_id,
        run_attempt=opts.run_attempt,
        mode=opts.mode,
        index=index,
        plan_dir=plan_dir,
        installed=opts.installed,
        python=opts.python,
        python_exe=opts.python_exe,
        environ=opts.environ,
        keep_workspace=opts.keep_workspace,
        job_start_file=None,
    )


def run_shards(
    opts: PlanOptions, runner: Runner, clock: Clock, out_dir: Path, only: int | None = None
) -> ShardRun:
    """`plan`, then `shard` for each index in order (or just `only`), through the same functions as CI."""
    plan_dir = out_dir / "plan"
    plan_doc, plan_code = plan(opts, runner, clock)
    write_json(plan_dir / PLAN_FILENAME, plan_doc)
    count = plan_doc["N"]
    if only is not None and not 1 <= only <= count:
        raise GateError(f"--only-shard {only} is outside 1..{count}")
    indices = range(1, count + 1) if only is None else [only]
    fragments: list[dict[str, Any]] = []
    ok = plan_code == 0
    for index in indices if plan_code == 0 else []:
        fragment, code = run_shard(shard_options(opts, index, plan_dir), runner, clock)
        name = FRAGMENT_DIR_FORMAT.format(index=index, count=count)
        write_json(out_dir / "fragments" / name / FRAGMENT_FILENAME, fragment)
        fragments.append(fragment)
        ok = ok and code == 0
    return ShardRun(plan_doc, plan_code, fragments, ok)


def run_local(opts: PlanOptions, runner: Runner, clock: Clock, out_dir: Path) -> LocalRun:
    """Plan, every shard, then the merge and the decision, as `verdict` does them in CI."""
    shard_run = run_shards(opts, runner, clock, out_dir)
    binding = {
        "mode": opts.mode,
        "gated_sha": opts.gated_sha,
        "pr": opts.pr,
        "run_id": opts.run_id,
        "run_attempt": opts.run_attempt,
    }
    results = ("success" if shard_run.plan_code == 0 else "failure",) + (
        "success" if shard_run.shards_ok else "failure",
    )
    records = merge_records(out_dir / "plan", out_dir / "fragments", results, binding, clock)
    doc, text, code = build_verdict(records)
    return LocalRun(records, doc, text, code, shard_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def exit_on_sigterm(signum: int, frame: Any) -> None:
    """Turn SIGTERM into SystemExit so the `finally` cleanup and the runner's child kill both run."""
    raise SystemExit(EXIT_SIGTERM)


def install_sigterm_handler() -> None:
    """Only `plan`, `shard` and `run` install it: never at import, never in the hidden child phases."""
    signal.signal(signal.SIGTERM, exit_on_sigterm)


def optional_path(value: str | None) -> Path | None:
    return None if value is None else Path(value)


def command_meta(args: argparse.Namespace) -> int:
    durations = optional_path(args.durations)
    write_json(
        Path(args.out), build_meta(Path.cwd(), Path(args.coverage_file), os.environ, durations)
    )
    return 0


def command_plan(args: argparse.Namespace) -> int:
    opts = PlanOptions(
        repo=Path.cwd(),
        gated_sha=args.gated_sha,
        pr_head_sha=args.pr_head_sha,
        pr=args.pr,
        coverage_file=Path(args.coverage_file),
        meta_path=Path(args.meta),
        tests_result=args.tests_result,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        mode="ci",
        base_ref=None,
        installed=installed_versions(),
        python=python_version(),
        python_exe=sys.executable,
        environ=dict(os.environ),
        keep_workspace=False,
        job_start_file=optional_path(args.job_start_file),
        github_output=optional_path(args.github_output),
    )
    install_sigterm_handler()
    doc, code = plan(opts, SubprocessRunner(), Clock())
    write_json(Path(args.out), doc)
    if code == 0 and opts.github_output is not None:
        write_job_outputs(opts.github_output, doc)
    return code


def command_shard(args: argparse.Namespace) -> int:
    opts = ShardOptions(
        repo=Path.cwd(),
        gated_sha=args.gated_sha,
        pr=args.pr,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        mode="ci",
        index=args.index,
        plan_dir=Path(args.plan_dir),
        installed=installed_versions(),
        python=python_version(),
        python_exe=sys.executable,
        environ=dict(os.environ),
        keep_workspace=False,
        job_start_file=optional_path(args.job_start_file),
    )
    install_sigterm_handler()
    doc, code = run_shard(opts, SubprocessRunner(), Clock())
    write_json(Path(args.out), doc)
    return code


def command_verdict(args: argparse.Namespace) -> int:
    inputs = VerdictInputs(
        plan_dir=Path(args.plan_dir),
        fragments_dir=Path(args.fragments_dir),
        plan_result=args.plan_result,
        shard_result=args.shard_result,
        gated_sha=args.gated_sha,
        pr=args.pr,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )
    out, summary, records_out = Path(args.out), Path(args.summary), Path(args.records_out)
    return verdict(inputs, records_out, out, summary, Clock())


def local_options(args: argparse.Namespace, repo: Path) -> PlanOptions:
    """`run`: gate HEAD against the merge base, after the same sidecar checks CI does (TD 5.1)."""
    dirty = tree_dirty_paths(repo)
    if dirty:
        raise GateError(
            "tracked .py/.sh files are modified: " + ", ".join(dirty[:MAX_BLOCKED_NAMES])
        )
    head = rev_parse(repo, "HEAD")
    meta_path = repo / "coverage-meta.json"
    message = ncg.check_sidecar_head(load_meta(meta_path), head)
    if message is not None:
        raise GateError(message)
    return PlanOptions(
        repo=repo,
        gated_sha=head,
        pr_head_sha=head,
        pr=None,
        coverage_file=repo / ".coverage",
        meta_path=meta_path,
        tests_result=None,
        run_id=None,
        run_attempt=None,
        mode="local",
        base_ref=args.base,
        installed=installed_versions(),
        python=python_version(),
        python_exe=sys.executable,
        environ=dict(os.environ),
        keep_workspace=args.keep_workspace,
        job_start_file=None,
        github_output=None,
    )


def command_run_partial(opts: PlanOptions, only: int, out_dir: Path) -> int:
    """`--only-shard`: plan and one shard, printed, and never a gate result (REQ-3)."""
    shard_run = run_shards(opts, SubprocessRunner(), Clock(), out_dir, only)
    for fragment in shard_run.fragments:
        print(ncs.fragment_summary(fragment))
    for entry in shard_run.plan["internal_errors"]:
        print(ncg.safe_echo(f"plan: {entry.get('code')}: {entry.get('message')}"))
    count = shard_run.plan["N"]
    print(f"partial run: shard {only} of {count} is not a gate result", file=sys.stderr)
    return 3


def command_run(args: argparse.Namespace) -> int:
    opts = local_options(args, Path.cwd())
    install_sigterm_handler()
    out_dir = Path(tempfile.mkdtemp(prefix="ncg-run-"))
    if args.only_shard is not None:
        return command_run_partial(opts, args.only_shard, out_dir)
    result = run_local(opts, SubprocessRunner(), Clock(), out_dir)
    write_json(out_dir / RECORDS_FILENAME, result.records)
    write_json(out_dir / VERDICT_FILENAME, result.verdict)
    print(result.summary)
    print(f"records and verdict written to {out_dir}", file=sys.stderr)
    return result.code


def command_enumerate(args: argparse.Namespace) -> int:
    lines = json.loads(Path(args.gated_lines_json).read_text(encoding="utf-8"))
    print(json.dumps(enumerate_child(args.file, lines, Path.cwd())))
    return 0


def command_collect(args: argparse.Namespace) -> int:
    print(json.dumps(collect_child(args.file, Path.cwd())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="new_code_gate", description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    meta = sub.add_parser("meta", help="write the coverage sidecar")
    meta.add_argument("--coverage-file", required=True)
    meta.add_argument("--out", required=True)
    meta.add_argument("--durations")
    plan_p = sub.add_parser("plan", help="cheap phase, cost, shard count and assignment")
    plan_p.add_argument("--gated-sha", required=True)
    plan_p.add_argument("--pr-head-sha", required=True)
    plan_p.add_argument("--pr", type=int, required=True)
    plan_p.add_argument("--coverage-file", required=True)
    plan_p.add_argument("--meta", required=True)
    plan_p.add_argument("--out", required=True)
    plan_p.add_argument("--tests-result", required=True)
    plan_p.add_argument("--run-id", required=True)
    plan_p.add_argument("--run-attempt", type=int, required=True)
    plan_p.add_argument("--github-output")
    plan_p.add_argument("--job-start-file")
    shard_p = sub.add_parser("shard", help="mutate one shard's assigned mutants")
    shard_p.add_argument("--index", type=int, required=True)
    shard_p.add_argument("--plan-dir", required=True)
    shard_p.add_argument("--gated-sha", required=True)
    shard_p.add_argument("--pr", type=int, required=True)
    shard_p.add_argument("--run-id", required=True)
    shard_p.add_argument("--run-attempt", type=int, required=True)
    shard_p.add_argument("--out", required=True)
    shard_p.add_argument("--job-start-file")
    verdict_p = sub.add_parser("verdict", help="merge the fragments and decide pass or fail")
    verdict_p.add_argument("--plan-dir", required=True)
    verdict_p.add_argument("--fragments-dir", required=True)
    verdict_p.add_argument("--plan-result", required=True)
    verdict_p.add_argument("--shard-result", required=True)
    verdict_p.add_argument("--gated-sha", required=True)
    verdict_p.add_argument("--pr", type=int, required=True)
    verdict_p.add_argument("--run-id", required=True)
    verdict_p.add_argument("--run-attempt", type=int, required=True)
    verdict_p.add_argument("--records-out", required=True)
    verdict_p.add_argument("--out", required=True)
    verdict_p.add_argument("--summary", required=True)
    run_p = sub.add_parser("run", help="local: plan, every shard, merge and verdict on HEAD")
    run_p.add_argument("--base", default="origin/main")
    run_p.add_argument("--keep-workspace", action="store_true")
    run_p.add_argument("--only-shard", type=int)
    enum_p = sub.add_parser("_enumerate", help=argparse.SUPPRESS)
    enum_p.add_argument("--file", required=True)
    enum_p.add_argument("--gated-lines-json", required=True)
    collect_p = sub.add_parser("_collect", help=argparse.SUPPRESS)
    collect_p.add_argument("--file", required=True)
    return parser


HANDLERS = {
    "meta": command_meta,
    "plan": command_plan,
    "shard": command_shard,
    "verdict": command_verdict,
    "run": command_run,
    "_enumerate": command_enumerate,
    "_collect": command_collect,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return HANDLERS[args.phase](args)
    except GateError as exc:
        print(ncg.safe_echo(f"new_code_gate: {exc}"), file=sys.stderr)
        return 3
    except Exception as exc:
        line = f"new_code_gate: internal error: {type(exc).__name__}: {exc}"
        print(ncg.safe_echo(line), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
