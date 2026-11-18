"""Pure logic of the new-code gate (#2304): 80% line coverage and 75% mutant score.

Design: docs/v0.7.0/TECHNICAL-DESIGN-2304-new-code-coverage-mutation-gate.md.

Everything here is a pure function over text, numbers and dictionaries. The CLI
(`new_code_gate.py`) does the git, coverage, mutmut and filesystem work and hands
the results to these functions. At module level this file imports only the
stdlib (ADR-2304 section 2b, condition 5); coverage is imported lazily inside
`statement_map`, and mutmut and libcst are never imported here.

The gate's own PR gates this file in full, so its module-level and class-level
statements hold no decision logic (TD 5.19): constants are literals, and the
classes are plain field containers.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import tokenize
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from io import StringIO
from typing import Any, NamedTuple

# ast node classes share few attributes in the stubs; the helpers below read
# lineno, body and similar fields guarded by isinstance checks.
Node = Any

GATE_VERSION = "2"
SCHEMA_RECORDS = "new-code-gate/2"
SCHEMA_META = "new-code-gate-meta/1"
SCHEMA_ENUM = "new-code-gate-enum/1"
SCHEMA_COLLECT = "new-code-gate-collect/1"
SCHEMA_PLAN = "new-code-gate-plan/1"
SCHEMA_FRAGMENT = "new-code-gate-fragment/1"

THRESHOLDS = {"coverage": 80, "mutant_score": 75}
# Per shard (S-4), measured from the job's first step when its start file is usable, else from
# process start; the plan has a shorter one. Job timeouts are 30 min (shard) and 15 min (plan).
BUDGET_SECONDS = 1500
PLAN_BUDGET_SECONDS = 600
# `meta` refuses a durations file this much older than the coverage data it pairs with (TD 5.20.4).
# The skew is slack only: pytest-cov saves .coverage before the writer runs, so a fresh file is
# newer than .coverage (ADR-2304 2i D-2).
DURATIONS_SKEW_SECONDS = 5

PINNED = {
    "mutmut": "3.8.1",
    "coverage": "7.17.2",
    "pytest-cov": "7.1.0",
    "libcst": "1.9.0",
    "pytest": "9.2.0",
    "pytest-rerunfailures": "16.7",
}

# The six --cov roots of scripts/framework/run_tests.sh, in order (R-S1a).
MEASURED_SOURCES = (
    "scripts/oversight",
    "scripts/automation/lib",
    "scripts/framework",
    "scripts",
    "bootstrap",
    "bin",
)

# The directories tests/conftest.py puts on sys.path (R-CONF). A gated file in
# one of them can be imported by its bare stem, which mutmut cannot attribute.
BARE_IMPORT_DIRS = ("scripts/oversight", "scripts/oversight/validators")

HARD_EXEMPT_SHELL_SUFFIX = "bootstrap/hos_bootstrap.sh"

KILLED_STATUSES = frozenset({"killed", "timeout"})
NOT_KILLED_STATUSES = frozenset(
    {
        "survived",
        "no tests",
        "suspicious",
        "skipped",
        "not checked",
        "segfault",
        "check was interrupted by user",
    }
)

MUTMUT_TRAMPOLINE_MESSAGE = "tests recorded trampoline hits but none match any mutant key"
MUTMUT_NO_TEST_CASE_MESSAGE = (
    "Stopping early, because we could not find any test case for any mutant."
)
MUTMUT_STATS_FAILED_MESSAGE = "failed to collect stats. runner returned "
MUTMUT_CLEAN_FAILED_MESSAGE = "Failed to run clean test"

# Fail codes in the fixed order of TD 5.14. Reasons on a file are listed in this order.
FAIL_ORDER = (
    "symlink_not_gateable",
    "mode_not_gateable",
    "not_measured",
    "path_loaded_module",
    "shell_decision_logic",
    "selected_test_fails_in_isolation",
    "unmarked_repo_copy",
    "mutation_timeout",
    "no_test_exercises",
    "zero_mutant_decision_logic",
    "unmutatable_decision_logic",
    "module_level_decision_logic",
    "class_level_decision_logic",
    "coverage_below_threshold",
    "mutant_score_below_threshold",
)
RULING_ELIGIBLE = frozenset({"coverage_below_threshold", "mutant_score_below_threshold"})

EXCEPTION_PATH_TEXT = (
    "unavailable until S5 (#2101 verifier); human admin merge is the only override"
)
TRUNCATION_SUFFIX = "…[truncated]"
MAX_PATH_CHARS = 1024
MAX_MESSAGE_CHARS = 2048
MAX_NODE_ID_CHARS = 1024
MAX_GATED_LINES = 5000
MAX_SELECTED_TESTS = 2000
MAX_LINES_IN_MESSAGE = 50
MAX_SIDECAR_PATHS = 20
MAX_TIMEOUT_FILES = 5
MAX_BLOB_MISMATCHES = 10

REGULAR_FILE_MODES = frozenset({"100644", "100755"})
SYMLINK_MODE = "120000"
MSG_SYMLINK = (
    "this path is a symlink; replace it with a regular file, "
    "or a module that re-exports the target"
)
MSG_MODE_TEMPLATE = (
    "this path is not a regular file in git (mode {mode}, for example a submodule); "
    "only regular files (100644, 100755) can be gated"
)

# The one way the gate is started by CI, run_tests.sh and its own child processes (RV2-1).
# `-I` keeps cwd, PYTHONPATH and the user site off sys.path; the pre-seeded `scripts`
# namespace module means no checkout path is ever on sys.path and scripts/__init__.py never runs.
ENTRY_SNIPPET = (
    "import os, sys, types; r = os.path.realpath(sys.argv[1]); "
    "p = types.ModuleType('scripts'); p.__path__ = [os.path.join(r, 'scripts')]; "
    "sys.modules['scripts'] = p; "
    "from scripts.framework.new_code_gate import main; sys.exit(main(sys.argv[2:]))"
)
MSG_NOT_MEASURED = (
    "file is outside the measured surface; add its top-level directory to "
    "run_tests.sh's --cov list"
)
MSG_TIMEOUT = "mutation budget exhausted; split the PR"
MSG_PLAN_TIMEOUT = "plan budget exhausted; split the PR"
MSG_SHELL = "move decision logic into tested Python (recommended home: scripts/automation/lib)"
MSG_PATH_LOAD_FIX = "convert to a canonical scripts.... import in this PR"

SHELL_SUFFIX = ".sh"

PRAGMA_NO_MUTATE_RE = re.compile(r"#\s*pragma:.*no mutate")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SUMMARY_HEADER_RE = re.compile(r"^=+ short test summary info =+$")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
# The only line terminators Python's parser, coverage and git's `\n` all agree on.
NEWLINE_RE = re.compile(r"\r\n|\n|\r")
LINE_WITH_END_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")
NODE_ID_RE = re.compile(r"tests/[\w./\-]+\.py(::\S+)?")
MODULE_ID_RE = re.compile(r"tests/[\w./\-]+\.py")
TABLE_HEADER_RE = re.compile(r"^\[\[?[A-Za-z0-9_.\"' -]+\]\]?\s*(#.*)?$")
MUTANT_KEY_RE = re.compile(r"^[\w.ǁ]+\.x[\wǁ]*__mutmut_\d+$")
FUNCTION_PREFIX_RE = re.compile(r"^[\w.ǁ]+\.x[\wǁ]*$")
MAX_KEY_CHARS = 512
OCTAL_ESCAPE_RE = re.compile(r"\\([0-7]{3}|.)")

LOADER_NAMES = frozenset(
    {
        "spec_from_file_location",
        "SourceFileLoader",
        "SourcelessFileLoader",
        "run_path",
        "load_module_from_path",
    }
)
SHARED_LOADER_FILES = (
    "tests/registry_guard.py",
    "tests/tmp_hygiene.py",
    "tests/automation/usage_support.py",
)
ENUM_BASE_NAMES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
ENUM_SPECIAL_DEFS = frozenset({"__init__", "_generate_next_value_"})
NEVER_MUTATE_DEFS = frozenset({"__getattribute__", "__setattr__", "__new__"})
NEVER_MUTATE_CALLS = frozenset({"len", "isinstance"})
SIMPLE_DECORATORS = frozenset({"staticmethod", "classmethod"})

PYTEST_ADD_CLI_ARGS = (
    "--no-header",
    "-rfE",
    "--reruns",
    "1",
    "-p",
    "no:cacheprovider",
    "-p",
    "no:randomly",
    "-p",
    "_ncg_tripwire",
    "-m",
    "not repo_copy",
)

TOP_LEVEL_FIELDS = (
    "schema",
    "gate_version",
    "phase",
    "mode",
    "pr",
    "gated_sha",
    "pr_head_sha",
    "base_sha",
    "gated_tree",
    "run_id",
    "run_attempt",
    "tool_versions",
    "python",
    "coverage_core",
    "budget_seconds",
    "thresholds",
    "files",
    "internal_errors",
    "records_sha256",
    "started_at",
    "finished_at",
    "seconds",
    "shards",
    "plan_hash",
    "plan_seconds",
    "plan_job_seconds",
    "merge_verdict_seconds",
    "runner_minutes_total",
)

FILE_FIELDS = (
    "path",
    "kind",
    "blob_sha",
    "pr_head_blob_sha",
    "gated_statements",
    "gated_lines",
    "gated_lines_truncated",
    "executed_gated",
    "coverage_pct",
    "mutation_ran",
    "mutation_reason",
    "mutants_total",
    "mutants_killed",
    "mutant_score_pct",
    "mutant_status_counts",
    "unmutatable_gated_lines",
    "decision_logic_findings",
    "decision_logic_findings_truncated",
    "selection_method",
    "selected_tests_count",
    "selected_tests",
    "selected_tests_truncated",
    "removed_repo_copy",
    "path_load_findings",
    "shell",
    "exception",
    "exception_path",
    "fail_reasons",
    "seconds",
    "enumerate_seconds",
    "workspace_seconds",
    "mutmut_seconds",
    "collect_seconds",
    "isolation_failure",
    "shards",
    "plan_hash",
    "N",
)

# Durations, the isolation evidence (temp paths, test output) and everything that describes the
# partition rather than the result: kept out of records_sha256 so two runs of one PR, and one PR
# at any shard count, hash alike (AC-29, AC-40; ADR-2304 sections 2g RV3-4 and 2h SH-10).
UNHASHED_FIELDS = frozenset(
    {
        "seconds",
        "enumerate_seconds",
        "workspace_seconds",
        "mutmut_seconds",
        "collect_seconds",
        "isolation_failure",
        "shards",
        "plan_hash",
        "N",
        "job_seconds",
        "plan_seconds",
        "plan_job_seconds",
        "merge_verdict_seconds",
        "runner_minutes_total",
    }
)
MUTMUT_ROOT_OUTPUTS = frozenset({"mutmut-stats.json", "mutmut-cicd-stats.json", "mutmut-debug.log"})
MUTMUT_OUTPUT_DIRS = frozenset({"__pycache__", ".pytest_cache"})
MAX_SUMMARY_LINES = 20
MAX_SUMMARY_LINE_CHARS = 2048
ISOLATION_TAIL_LINES = 60
ISOLATION_TAIL_CHARS = 8192
RUNNER_MINUTES_LABEL = (
    "job minutes from job start to fragment write; excludes queue time and the upload step; "
    "new-code-gate counts gate-process time only"
)

_DECISION_STMTS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.Match,
)
_DECISION_EXPRS = (ast.BoolOp, ast.Compare, ast.IfExp)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPOUND = _DECISION_STMTS + (ast.With, ast.AsyncWith, ast.FunctionDef, ast.AsyncFunctionDef)
_SIMPLE_DEFAULTS = (ast.Name, ast.Constant, ast.JoinedStr)


class GateError(Exception):
    """A gate-internal failure: the CLI maps it to exit 3 ("could not decide")."""


class ChangedPath(NamedTuple):
    status: str
    path: str
    old_path: str | None
    kind: str | None


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def bound_text(text: str, limit: int) -> str:
    """Truncate `text` to `limit` characters, ending in the truncation suffix."""
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


def split_lines(text: str) -> list[str]:
    """Lines as Python's parser and coverage count them: `\\n`, `\\r\\n` and `\\r` only.

    `str.splitlines` also breaks on form feed, vertical tab, NEL and U+2028/9, which
    shifts every later line number away from ast, coverage and git.
    """
    parts = NEWLINE_RE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts


def split_lines_keepends(text: str) -> list[str]:
    """`split_lines` with each line's terminator kept, so joining restores the text."""
    return LINE_WITH_END_RE.findall(text)


def safe_echo(text: str) -> str:
    """One line that cannot forge a workflow command: no CR or LF, no leading `::`."""
    one_line = text.replace("\r", "\\r").replace("\n", "\\n")
    if one_line.startswith("::"):
        return "\\" + one_line
    return one_line


def sanitize_node_ids(node_ids: Iterable[str]) -> list[str]:
    """Node IDs safe to hand to pytest as argv; a shape that is not safe falls back to its module.

    The IDs come from coverage contexts, which the PR's own tests wrote. An ID that
    is a plain `tests/...py[::name]` stays; one with whitespace in a parameter ID
    widens to its whole module (never narrows); anything else, such as an option
    like `--rootdir=/x`, is refused.
    """
    safe = set()
    for node_id in node_ids:
        module = node_id.split("::")[0]
        if not MODULE_ID_RE.fullmatch(module) or ".." in module.split("/"):
            raise GateError(
                f"unsafe test id in coverage contexts: {bound_text(repr(node_id), 200)}"
            )
        safe.add(node_id if NODE_ID_RE.fullmatch(node_id) else module)
    return sorted(safe)


def blob_mismatches(expected: Mapping[str, str], actual: Mapping[str, str]) -> list[str]:
    """Paths whose extracted content does not hash to the committed blob, sorted."""
    return sorted(p for p in expected if actual.get(p) != expected[p])


def percent_floor(numerator: int, denominator: int) -> float:
    """floor(n * 1000 / d) / 10: one decimal, rounded down (TD 5.4)."""
    return (numerator * 1000 // denominator) / 10


def meets_threshold(numerator: int, denominator: int, threshold: int) -> bool:
    """Exact integer arithmetic: numerator/denominator >= threshold percent."""
    return numerator * 100 >= threshold * denominator


def fail_reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": bound_text(message, MAX_MESSAGE_CHARS)}


def canonical_name(rel_path: str) -> str:
    """Dotted import name of a repo-relative `.py` path (`__init__.py` -> package)."""
    dotted = rel_path.removesuffix(".py").replace("/", ".")
    return dotted.removesuffix(".__init__")


def module_stem(rel_path: str) -> str:
    """The stem a test-name match uses: the package directory for `__init__.py`."""
    parts = rel_path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        return parts[-2]
    return parts[-1]


def format_lines(lines: Iterable[int]) -> str:
    """Sorted, de-duplicated line numbers, capped at 50 then '…and N more'."""
    unique = sorted(set(lines))
    shown = ",".join(str(n) for n in unique[:MAX_LINES_IN_MESSAGE])
    extra = unique[MAX_LINES_IN_MESSAGE:]
    return shown + f" …and {len(extra)} more" if extra else shown


# ---------------------------------------------------------------------------
# Version and sidecar guards (TD 5.2 steps 1 to 3)
# ---------------------------------------------------------------------------


def check_pins(installed: Mapping[str, str]) -> str | None:
    """Return the first 'tool version mismatch' message, or None."""
    for name in sorted(PINNED):
        found = installed.get(name)
        if found != PINNED[name]:
            return f"tool version mismatch: {name} {found} != {PINNED[name]}"
    return None


def check_sidecar_environment(
    meta: Mapping[str, Any], installed: Mapping[str, str], python: str
) -> str | None:
    """The sidecar's tool versions and Python major.minor must equal this process's."""
    side = meta.get("tool_versions") or {}
    for name in sorted(PINNED):
        if side.get(name) != installed.get(name):
            return (
                "sidecar tool versions differ from measure environment: "
                f"{name} {side.get(name)} != {installed.get(name)}"
            )
    if meta.get("python") != python:
        return (
            "sidecar tool versions differ from measure environment: "
            f"python {meta.get('python')} != {python}"
        )
    return None


def _dirty_summary(meta: Mapping[str, Any]) -> str:
    paths = meta.get("dirty_paths")
    if not isinstance(paths, list) or not paths:
        return "no paths recorded"
    shown = [bound_text(str(p), MAX_PATH_CHARS) for p in paths[:MAX_SIDECAR_PATHS]]
    return ", ".join(shown)


def check_sidecar_head(
    meta: Mapping[str, Any], gated_sha: str, run_id: str | None = None
) -> str | None:
    """The sidecar must describe the gated commit, from a clean tree, under ctrace.

    In CI (`run_id` given) it must also have been written by this workflow run.
    The message names which conditions failed (head, clean, core, run).
    """
    failed = []
    if meta.get("head_sha") != gated_sha:
        seen = bound_text(str(meta.get("head_sha")), MAX_PATH_CHARS)
        failed.append(f"head: sidecar describes {seen}, gated commit is {gated_sha}")
    if meta.get("clean") is not True:
        failed.append(f"clean: tracked .py/.sh files were modified ({_dirty_summary(meta)})")
    if meta.get("coverage_core") != "ctrace":
        seen = bound_text(str(meta.get("coverage_core")), MAX_PATH_CHARS)
        failed.append(f"core: coverage_core is {seen}, not ctrace")
    if run_id is not None and meta.get("run_id") != run_id:
        seen = bound_text(str(meta.get("run_id")), MAX_PATH_CHARS)
        failed.append(f"run: sidecar was written by run {seen}, this is run {run_id}")
    if not failed:
        return None
    return "coverage data stale or from a dirty tree: " + "; ".join(failed)


def check_merge_parents(parents: Sequence[str], pr_head_sha: str) -> str | None:
    """CI guard (AR-1): exactly two parents, the second being the PR head."""
    if len(parents) != 2 or parents[1] != pr_head_sha:
        return "merge commit does not contain the PR head"
    return None


# ---------------------------------------------------------------------------
# Diff parsing and scope (TD 5.3)
# ---------------------------------------------------------------------------


def unquote_git_path(text: str) -> str:
    """Undo git's C-style quoting (core.quotePath=true): "…" with octal escapes."""
    if not (text.startswith('"') and text.endswith('"')):
        return text
    body = text[1:-1]
    raw = bytearray()
    pos = 0
    simple = {"n": 10, "t": 9, '"': 34, "\\": 92}
    while pos < len(body):
        match = OCTAL_ESCAPE_RE.match(body, pos)
        if match is None:
            raw.extend(body[pos].encode("utf-8"))
            pos += 1
            continue
        token = match.group(1)
        if token in simple:
            raw.append(simple[token])
        elif len(token) == 3:
            raw.append(int(token, 8))
        else:
            raw.extend(token.encode("utf-8"))
        pos = match.end()
    return raw.decode("utf-8", errors="replace")


def classify_status(status: str) -> str | None:
    """Map a `--name-status` code to 'new', 'changed' or None (not gated)."""
    if status.startswith("R"):
        return None if status == "R100" else "changed"
    kinds = {"A": "new", "C": "new", "M": "changed", "T": "changed"}
    return kinds.get(status[:1])


def classify_change(status: str, old_path: str | None, path: str) -> str | None:
    """`classify_status`, except a rename across scopes is a new file, never a clean move.

    A rename from outside the gated scope (a test, a `.txt`) into it has no gated
    history, so none of its lines may ride in as unchanged.
    """
    if status.startswith("R") and scope_of(old_path or path) != scope_of(path):
        return "new"
    return classify_status(status)


def parse_name_status(text: str) -> list[ChangedPath]:
    """Parse `git diff --name-status -M` output."""
    out = []
    for raw in text.split("\n"):
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        paths = [unquote_git_path(p) for p in parts[1:]]
        is_move = status[:1] in ("R", "C")
        old = paths[0] if is_move else None
        out.append(ChangedPath(status, paths[-1], old, classify_change(status, old, paths[-1])))
    return out


def parse_tree_modes(listing: str) -> dict[str, str]:
    """Git mode of every path in a `git ls-tree -r -z` listing (`<mode> <type> <sha>\\t<path>\\0`)."""
    modes = {}
    for entry in listing.split("\0"):
        head, tab, path = entry.partition("\t")
        if tab:
            modes[path] = head.split(" ")[0]
    return modes


def mode_fail_code(mode: str) -> str | None:
    """The fail code for a gated path's git mode, or None when it is a regular file."""
    if mode in REGULAR_FILE_MODES:
        return None
    return "symlink_not_gateable" if mode == SYMLINK_MODE else "mode_not_gateable"


def mode_message(mode: str) -> str:
    """The fixed message for a non-regular git mode (symlink or other)."""
    if mode == SYMLINK_MODE:
        return MSG_SYMLINK
    return MSG_MODE_TEMPLATE.format(mode=mode)


def parse_hunks(text: str) -> tuple[list[int], int]:
    """Head-side added or modified line numbers, and the hunk count, of one file's diff.

    `text` is the `--unified=0` output for a single path. Only `@@` lines are read:
    a body line always starts with `+`, `-` or a backslash, so no content line can
    pose as a hunk header, and the `---` and `+++` file headers (which a content
    line such as `++ b/x.py` could forge) are never consulted.
    """
    lines: list[int] = []
    hunks = 0
    for raw in text.split("\n"):
        match = HUNK_RE.match(raw)
        if match is None:
            continue
        hunks += 1
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        lines.extend(range(start, start + count))
    return lines, hunks


def check_diff_complete(path: str, base_blob: str, head_blob: str, hunks: int) -> None:
    """Fail closed when a file's content changed but its diff holds no hunk.

    A mode-only change keeps the blob and passes. A deletion-only change still has a
    hunk (`+N,0`), so it passes too.
    """
    if base_blob != head_blob and hunks == 0:
        raise GateError(f"diff for {path} changed content but produced no hunks")


def scope_of(path: str) -> str | None:
    """Which gate rule a path falls under: 'python', 'shell' or None."""
    if in_python_scope(path):
        return "python"
    if in_shell_scope(path):
        return "shell"
    return None


def in_python_scope(path: str) -> bool:
    """Tracked production Python: not tests, conftest or mutants."""
    parts = path.split("/")
    if not path.endswith(".py"):
        return False
    return parts[0] not in ("tests", "mutants") and parts[-1] != "conftest.py"


def in_shell_scope(path: str) -> bool:
    return path.endswith(SHELL_SUFFIX)


def in_measured_surface(path: str, measured_sources: Sequence[str]) -> bool:
    """True when the file's top-level directory is under a measured root (TD 5.3)."""
    top = path.split("/")[0]
    for root in measured_sources:
        if root.split("/")[0] == top:
            return True
    return False


def statement_map(source: str) -> tuple[set[int], dict[int, int]]:
    """Executable first lines and the first-line map of multi-line statements.

    Uses coverage's own parser with no exclusions, so `# pragma: no cover` removes
    nothing (H2). coverage is imported here, in the measure path only.
    """
    from coverage.parser import PythonParser

    parser = PythonParser(text=source, exclude=None)
    parser.parse_source()
    firsts = {n: parser.first_line(n) for n in parser.multiline_map}
    return set(parser.statements), firsts


def gated_statement_lines(
    changed_lines: Iterable[int],
    statements: set[int],
    multiline: Mapping[int, int],
    is_new: bool,
) -> list[int]:
    """The statement first lines that a change gates (all of them for a new file)."""
    if is_new:
        return sorted(statements)
    owners = {multiline.get(n, n) for n in changed_lines}
    return sorted(owners & statements)


def coverage_fields(gated: int, executed: int) -> dict[str, Any]:
    """Coverage numbers for one file; no requirement when nothing is gated."""
    if gated == 0:
        return {"gated_statements": 0, "executed_gated": 0, "coverage_pct": None}
    return {
        "gated_statements": gated,
        "executed_gated": executed,
        "coverage_pct": percent_floor(executed, gated),
    }


# ---------------------------------------------------------------------------
# Decision logic: definition, regions, carve-outs (TD 5.5, 5.10)
# ---------------------------------------------------------------------------


def _start_line(node: Node) -> int:
    decorators = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decorators])


def _start_pos(node: Node) -> tuple[int, int]:
    positions = [(node.lineno, node.col_offset)]
    for deco in getattr(node, "decorator_list", None) or []:
        positions.append((deco.lineno, deco.col_offset))
    return min(positions)


def _contains(outer: Node, inner: Node) -> bool:
    inner_start = (inner.lineno, inner.col_offset)
    inner_end = (inner.end_lineno, inner.end_col_offset)
    return _start_pos(outer) <= inner_start and inner_end <= (
        outer.end_lineno,
        outer.end_col_offset,
    )


def _in_list(items: Sequence[Node], item: Node) -> bool:
    return any(item is other for other in items)


def _first_block_line(node: Node) -> int:
    if isinstance(node, ast.Match):
        return node.cases[0].pattern.lineno
    return node.body[0].lineno


def _own_lines(node: Node) -> set[int]:
    """The lines whose expressions belong to this statement itself (TD 5.5.1)."""
    if not isinstance(node, _COMPOUND):
        return set(range(node.lineno, node.end_lineno + 1))
    end = max(node.lineno, _first_block_line(node) - 1)
    lines = set(range(_start_line(node), end + 1))
    for handler in getattr(node, "handlers", []):
        lines.update(range(handler.lineno, max(handler.lineno, handler.body[0].lineno - 1) + 1))
    for case in getattr(node, "cases", []):
        top = case.pattern.lineno
        lines.update(range(top, max(top, case.body[0].lineno - 1) + 1))
    return lines


def _parent_map(tree: Node) -> dict[Node, Node]:
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _chain(node: Node, parents: Mapping[Node, Node]) -> list[tuple[Node, Node]]:
    """(child, parent) pairs from `node` up to the module, innermost first."""
    pairs = []
    child = node
    while child in parents:
        parent = parents[child]
        pairs.append((child, parent))
        child = parent
    return pairs


def _is_decision_node(node: Node) -> bool:
    if isinstance(node, _DECISION_STMTS + _DECISION_EXPRS):
        return True
    if isinstance(node, _COMPREHENSIONS):
        return any(gen.ifs for gen in node.generators)
    return False


def _region(chain: Sequence[tuple[Node, Node]]) -> str:
    in_class = False
    for child, parent in chain:
        if isinstance(parent, _DEFS) and _in_list(parent.body, child):
            return "function"
        if isinstance(parent, ast.ClassDef) and _in_list(parent.body, child):
            in_class = True
    return "class" if in_class else "module"


def _enclosing_defs(chain: Sequence[tuple[Node, Node]]) -> list[Node]:
    """Every def that has the node inside its body, innermost first."""
    return [p for c, p in chain if isinstance(p, _DEFS) and _in_list(p.body, c)]


def _is_decorated(func: Node) -> bool:
    decorators = func.decorator_list
    if not decorators:
        return False
    only = decorators[0]
    single_simple = (
        len(decorators) == 1 and isinstance(only, ast.Name) and only.id in SIMPLE_DECORATORS
    )
    return not single_simple


def _is_enum_class(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id in ENUM_BASE_NAMES:
            return True
        if isinstance(base, ast.Attribute) and base.attr in ENUM_BASE_NAMES:
            return True
    return False


def _is_enum_special_def(func: Node, parents: Mapping[Node, Node]) -> bool:
    owner = parents.get(func)
    in_enum = isinstance(owner, ast.ClassDef) and _is_enum_class(owner)
    return in_enum and func.name in ENUM_SPECIAL_DEFS


def _in_never_mutate_call(chain: Sequence[tuple[Node, Node]]) -> bool:
    for child, parent in chain:
        if not isinstance(parent, ast.Call) or child is parent.func:
            continue
        if isinstance(parent.func, ast.Name) and parent.func.id in NEVER_MUTATE_CALLS:
            return True
    return False


def _is_mutated_unit(func: Node, parents: Mapping[Node, Node]) -> bool:
    """mutmut trampolines only top-level defs and methods of top-level classes."""
    owner = parents.get(func)
    if isinstance(owner, ast.Module):
        return True
    if not isinstance(owner, ast.ClassDef) or not isinstance(parents.get(owner), ast.Module):
        return False
    return owner.body[0].lineno > owner.lineno


def _is_definition_time(chain: Sequence[tuple[Node, Node]], outermost: Node) -> bool:
    """N sits in an annotation, nested decorator, or non-simple default (TD 5.5.2 reason 6)."""
    for child, parent in chain:
        if isinstance(parent, (ast.AnnAssign, ast.arg)) and child is parent.annotation:
            return True
        if isinstance(parent, _DEFS + (ast.ClassDef,)) and _in_list(parent.decorator_list, child):
            return True
        if isinstance(parent, _DEFS) and child is parent.returns:
            return True
        if isinstance(parent, ast.arguments):
            defaults = list(parent.defaults) + list(parent.kw_defaults)
            if _in_list(defaults, child) and not isinstance(child, _SIMPLE_DEFAULTS):
                return True
        if parent is outermost:
            return False
    return False


def _unmutatable_reason(
    chain: Sequence[tuple[Node, Node]],
    parents: Mapping[Node, Node],
    expression: bool,
) -> str | None:
    """The first reason mutmut leaves a function-region node unmutated, or None."""
    defs = _enclosing_defs(chain)
    if any(_is_decorated(d) for d in defs):
        return "decorated_function"
    if any(_is_enum_special_def(d, parents) for d in defs):
        return "enum_body"
    if any(d.name in NEVER_MUTATE_DEFS for d in defs):
        return "never_mutate_name"
    if expression and _in_never_mutate_call(chain):
        return "never_mutate_name"
    if not _is_mutated_unit(defs[-1], parents):
        return "non_top_level_function"
    if expression and _is_definition_time(chain, defs[-1]):
        return "definition_time_expression"
    return None


def _is_main_guard(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.If) or stmt.orelse:
        return False
    test = stmt.test
    shape = (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )
    only = stmt.body[0]
    return shape and len(stmt.body) == 1 and (_is_call_statement(only) or _is_system_exit(only))


def _is_call_statement(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)


def _is_system_exit(stmt: ast.stmt) -> bool:
    """`raise SystemExit(<call>)`: the one raise shape accepted as a main-guard body."""
    if not isinstance(stmt, ast.Raise) or stmt.cause is not None:
        return False
    exc = stmt.exc
    return (
        isinstance(exc, ast.Call)
        and isinstance(exc.func, ast.Name)
        and exc.func.id == "SystemExit"
        and len(exc.args) == 1
        and isinstance(exc.args[0], ast.Call)
        and not exc.keywords
    )


def _is_import_fallback(stmt: ast.stmt) -> bool:
    if type(stmt) is not ast.Try or stmt.orelse or stmt.finalbody or not stmt.handlers:
        return False
    imports_only = all(isinstance(s, (ast.Import, ast.ImportFrom)) for s in stmt.body)
    handlers_ok = all(
        isinstance(h.type, ast.Name) and h.type.id == "ImportError" for h in stmt.handlers
    )
    return imports_only and handlers_ok


def _is_type_checking(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.If)
        and not stmt.orelse
        and isinstance(stmt.test, ast.Name)
        and stmt.test.id == "TYPE_CHECKING"
    )


def carve_out_kind(stmt: ast.stmt) -> str | None:
    """Which of the three Q5 carve-outs a module-level statement matches, if any."""
    if _is_main_guard(stmt):
        return "main_guard"
    if _is_import_fallback(stmt):
        return "import_fallback"
    if _is_type_checking(stmt):
        return "type_checking"
    return None


def _carve_out_for(node: Node, chain: Sequence[tuple[Node, Node]]) -> str | None:
    """The carve-out that excuses `node` itself (module region only)."""
    top = node
    for child, parent in chain:
        if isinstance(parent, ast.Module):
            top = child
    kind = carve_out_kind(top) if isinstance(top, ast.stmt) else None
    if kind is None:
        return None
    if node is top:
        return kind
    if kind == "main_guard" and node is top.test:
        return kind
    return None


def _gated_statements(tree: Node, gated: set[int]) -> list[ast.stmt]:
    stmts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and (_start_line(node) in gated or node.lineno in gated):
            stmts.append(node)
    return stmts


def _owner_of(node: Node, statements: Sequence[Node]) -> Node | None:
    """The innermost gated statement that owns `node` (TD 5.5.1)."""
    if isinstance(node, ast.stmt):
        return node if _in_list(statements, node) else None
    best = None
    best_key = None
    for stmt in statements:
        if node.lineno not in _own_lines(stmt) or not _contains(stmt, node):
            continue
        key = (stmt.end_lineno - _start_line(stmt), stmt.end_col_offset - stmt.col_offset)
        if best_key is None or key < best_key:
            best, best_key = stmt, key
    return best


def decision_logic_findings(source: str, gated_statements: Iterable[int]) -> list[dict[str, Any]]:
    """One finding per gated decision node (TD 5.5.4)."""
    tree = ast.parse(source)
    parents = _parent_map(tree)
    statements = _gated_statements(tree, set(gated_statements))
    findings = []
    for walked in ast.walk(tree):
        node: Node = walked
        if not _is_decision_node(node):
            continue
        owner = _owner_of(node, statements)
        if owner is None:
            continue
        chain = _chain(node, parents)
        region = _region(chain)
        reason = None
        carve = None
        if region == "function":
            reason = _unmutatable_reason(chain, parents, True)
        elif region == "module":
            carve = _carve_out_for(node, chain)
        findings.append(
            {
                "line": _start_line(owner),
                "node_line": node.lineno,
                "construct": type(node).__name__,
                "region": region,
                "unmutatable_reason": reason,
                "carve_out": carve,
            }
        )
    findings.sort(key=lambda f: (f["line"], f["node_line"], f["construct"]))
    return findings


def is_decision_logic(finding: Mapping[str, Any]) -> bool:
    """True unless a Q5 carve-out excuses the finding (the one reader of `carve_out`)."""
    return finding["carve_out"] is None


def has_decision_logic(source: str, gated_statements: Iterable[int]) -> bool:
    """True iff any gated decision node is not excused by a carve-out (NQ-1)."""
    return any(is_decision_logic(f) for f in decision_logic_findings(source, gated_statements))


def unmutatable_gated_lines(source: str, gated_statements: Iterable[int]) -> list[dict[str, Any]]:
    """Gated statements that mutmut will not mutate by construction (TD 5.10)."""
    gated = set(gated_statements)
    tree = ast.parse(source)
    parents = _parent_map(tree)
    statements = _gated_statements(tree, gated)
    logic_lines = {
        f["line"] for f in decision_logic_findings(source, gated) if is_decision_logic(f)
    }
    entries = {}
    for stmt in statements:
        chain = _chain(stmt, parents)
        region = _region(chain)
        reason = None
        if region == "function":
            reason = _unmutatable_reason(chain, parents, False)
        elif region == "class":
            reason = _class_body_reason(stmt, parents)
        if reason is None:
            continue
        line = _start_line(stmt)
        entries[(line, reason)] = {
            "line": line,
            "reason": reason,
            "region": region,
            "has_decision_logic": line in logic_lines,
        }
    return [entries[key] for key in sorted(entries)]


def _class_body_reason(stmt: ast.stmt, parents: Mapping[Node, Node]) -> str | None:
    owner = parents.get(stmt)
    if not isinstance(owner, ast.ClassDef) or not _in_list(owner.body, stmt):
        return None
    if _is_enum_class(owner):
        return "enum_body"
    if owner.body[0].lineno == owner.lineno:
        return "single_line_class"
    return None


def decision_fail_reasons(path: str, findings: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The NQ-2 and Q5 fail reasons for a file, in the fixed TD 5.14 order."""
    logic = [f for f in findings if is_decision_logic(f)]
    nq2 = [f["line"] for f in logic if f["region"] == "function" and f["unmutatable_reason"]]
    module = [f["line"] for f in logic if f["region"] == "module"]
    klass = [f["line"] for f in logic if f["region"] == "class"]
    reasons = []
    if nq2:
        reasons.append(
            fail_reason(
                "unmutatable_decision_logic",
                f"unmutatable decision logic at {path}:{format_lines(nq2)} — "
                "move the logic into an undecorated helper so it can be mutated",
            )
        )
    if module:
        reasons.append(
            fail_reason(
                "module_level_decision_logic",
                f"module-level decision logic at {path}:{format_lines(module)} — "
                "move the logic into a function so it can be mutated",
            )
        )
    if klass:
        reasons.append(
            fail_reason(
                "class_level_decision_logic",
                f"class-level decision logic at {path}:{format_lines(klass)} — "
                "move the logic into a function so it can be mutated",
            )
        )
    return reasons


def zero_mutant_reason(path: str, findings: Sequence[Mapping[str, Any]]) -> dict[str, str] | None:
    """NQ-1: a zero-mutant, empty-selection file may not hold decision logic."""
    logic = [f for f in findings if is_decision_logic(f)]
    if not logic:
        return None
    lines = format_lines(f["line"] for f in logic)
    return fail_reason(
        "zero_mutant_decision_logic",
        f"decision logic at {path}:{lines} — move logic into a function so it can be mutated",
    )


# ---------------------------------------------------------------------------
# Test selection (TD 5.6)
# ---------------------------------------------------------------------------


def contexts_to_node_ids(contexts: Iterable[str]) -> list[str]:
    """Drop the phase suffix (`|run`, `|setup`, `|teardown`) and the empty context."""
    ids = {c.rpartition("|")[0] for c in contexts}
    ids.discard("")
    return sorted(ids)


def select_by_context(
    contexts_by_line: Mapping[int, Iterable[str]], gated_lines: Iterable[int]
) -> list[str]:
    """The union of the tests that executed any gated statement."""
    found: list[str] = []
    for line in gated_lines:
        found.extend(contexts_by_line.get(line, ()))
    return contexts_to_node_ids(found)


def name_fallback_ids(rel_path: str, tracked_paths: Iterable[str]) -> list[str]:
    """Whole-module IDs of every tracked `tests/**/test_<stem>.py`."""
    wanted = f"test_{module_stem(rel_path)}.py"
    return sorted(p for p in tracked_paths if p.startswith("tests/") and p.split("/")[-1] == wanted)


def remove_repo_copy(
    selected: Sequence[str], collected: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Drop exact repo_copy IDs from a selection; list containers' repo_copy children too."""
    collected_ids = sorted(set(collected))
    kept = [s for s in selected if s not in collected_ids]
    removed = []
    for cid in collected_ids:
        exact = cid in selected
        child = any(cid.startswith(s + "::") for s in selected)
        if exact or child:
            removed.append(cid)
    return kept, removed


def parse_repo_copy_collect(returncode: int, stdout: str) -> list[str]:
    """Parse the collect-only run (TD 5.6 step 3): exit 5 is an empty set."""
    if returncode == 5:
        return []
    if returncode != 0:
        raise GateError(f"repo_copy collection failed: pytest exited {returncode}")
    ids = []
    for line in stdout.splitlines():
        if line == "":
            break
        if "::" not in line or not line.startswith("tests/"):
            raise GateError("repo_copy collection failed: unparseable output")
        ids.append(line)
    return ids


def selection_reason(node_ids: Sequence[str], zero_mutants: bool, logic_free: bool) -> str | None:
    """Name the fail an empty selection earns, or None when NQ-1 lets it through."""
    if node_ids:
        return None
    if zero_mutants and logic_free:
        return None
    if zero_mutants:
        return "zero_mutant_decision_logic"
    return "no_test_exercises"


def selection_fields(method: str, node_ids: Sequence[str]) -> dict[str, Any]:
    """The selection part of a record, with the 2,000-ID cap."""
    shown = [bound_text(n, MAX_NODE_ID_CHARS) for n in node_ids[:MAX_SELECTED_TESTS]]
    return {
        "selection_method": method,
        "selected_tests_count": len(node_ids),
        "selected_tests": shown,
        "selected_tests_truncated": len(node_ids) > MAX_SELECTED_TESTS,
    }


def is_attributable(node_id: str, selected: Iterable[str]) -> bool:
    """A failed ID is attributable when it equals, lies under, or is the module of a selection."""
    for sel in selected:
        if node_id == sel or node_id.startswith(sel + "::") or sel.split("::")[0] == node_id:
            return True
    return False


# ---------------------------------------------------------------------------
# Path-loaded and bare-imported modules (TD 5.7)
# ---------------------------------------------------------------------------


def path_load_message(importer: str, gated: str, loaded_as: str, via: str) -> str:
    """The fixed finding text (TD 5.7)."""
    return (
        f"{importer} loads {gated} as module '{loaded_as}' ({via}) instead of the "
        f"canonical 'import {canonical_name(gated)}' — {MSG_PATH_LOAD_FIX}"
    )


def _literal_strings(node: Node) -> list[str]:
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def static_path_load_findings(gated_path: str, sources: Mapping[str, str]) -> list[dict[str, str]]:
    """Static pre-check over test modules, conftests and the shared loaders (TD 5.7.1)."""
    names = {gated_path, gated_path.split("/")[-1], module_stem(gated_path)}
    stem = module_stem(gated_path)
    bare_ok = "/".join(gated_path.split("/")[:-1]) in BARE_IMPORT_DIRS
    findings = []
    for importer in sorted(sources):
        try:
            tree = ast.parse(sources[importer])
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            loaded_as, kind = _loaded_name(node, names, stem, bare_ok)
            if kind is None:
                continue
            findings.append(
                {
                    "importer": importer,
                    "loaded_as": loaded_as,
                    "canonical": canonical_name(gated_path),
                    "via": f"static:{kind}",
                    "phase": "static",
                }
            )
    return findings


def _loaded_name(node: Node, names: set[str], stem: str, bare_ok: bool) -> tuple[str, str | None]:
    if isinstance(node, ast.Call) and _call_name(node) in LOADER_NAMES:
        literals = _literal_strings(node)
        parts = {seg for lit in literals for seg in lit.replace("\\", "/").split("/")}
        if names.intersection(literals) or names.intersection(parts):
            first = literals[0] if literals else stem
            return first, _call_name(node)
    if isinstance(node, ast.Import) and bare_ok:
        for alias in node.names:
            if alias.name.split(".")[0] == stem:
                return alias.name, "bare_import"
    if isinstance(node, ast.ImportFrom) and bare_ok and node.level == 0 and node.module:
        if node.module.split(".")[0] == stem:
            return node.module, "bare_import"
    return "", None


# ---------------------------------------------------------------------------
# Mutation workspace configuration (TD 5.8)
# ---------------------------------------------------------------------------


def _tokens_without_comments(source: str) -> list[tuple[int, str]]:
    tokens = tokenize.generate_tokens(StringIO(source).readline)
    return [(t.type, t.string) for t in tokens if t.type not in (tokenize.COMMENT, tokenize.NL)]


def _pragma_cuts(source: str) -> list[tuple[int, int, int]]:
    """(0-based row, start column, end column) of every no-mutate pragma comment token."""
    cuts = []
    for tok in tokenize.generate_tokens(StringIO(source).readline):
        if tok.type == tokenize.COMMENT and PRAGMA_NO_MUTATE_RE.search(tok.string):
            cuts.append((tok.start[0] - 1, tok.start[1], tok.end[1]))
    return cuts


def strip_no_mutate_pragmas(source: str) -> str:
    """Remove every `# pragma: ... no mutate` comment token, leaving the line otherwise intact.

    The result must tokenize to the same non-comment tokens as the source; if the
    cuts landed anywhere but on comments, the line arithmetic was wrong and the
    result is refused rather than mutated.
    """
    lines = split_lines_keepends(source)
    for row, begin, end in sorted(_pragma_cuts(source), reverse=True):
        lines[row] = lines[row][:begin] + lines[row][end:]
    stripped = "".join(lines)
    if _pragma_cuts(stripped):
        raise GateError("a no-mutate pragma survived stripping")
    if _tokens_without_comments(stripped) != _tokens_without_comments(source):
        raise GateError("stripping no-mutate pragmas changed more than comments")
    return stripped


def generated_pytest_args() -> list[str]:
    return list(PYTEST_ADD_CLI_ARGS)


def mutmut_source_paths(top_dirs_with_python: Iterable[str], gated_path: str) -> list[str]:
    """Sorted top-level tracked directories with production `.py`, plus a top-level gated file."""
    entries = {d.rstrip("/") + "/" for d in top_dirs_with_python if d != "tests"}
    if "/" not in gated_path:
        entries.add(gated_path)
    return sorted(entries)


def mutmut_also_copy(
    top_dirs: Iterable[str], top_files: Iterable[str], source_paths: Sequence[str]
) -> list[str]:
    """Top-level directories and files only; never `.claude/` or a nested path (R6)."""
    own = {s.rstrip("/") for s in source_paths}
    dirs = {
        d.rstrip("/") + "/"
        for d in top_dirs
        if d.rstrip("/") not in own and d.rstrip("/") not in ("tests", ".claude")
    }
    files = {f for f in top_files if f not in ("pyproject.toml", "setup.cfg") and f not in own}
    return sorted(dirs) + sorted(files)


def mutmut_output_paths(gated_path: str) -> frozenset[str]:
    """Paths under `mutants/` that mutmut 3.8.1 itself writes during a run (ADR-2304 RV3-7b).

    The trampolined copy of the gated file and its two index files, plus the run's stats, CI stats
    and debug log. Pinned against mutmut's source by a test, so a mutmut bump is a red build.
    """
    return MUTMUT_ROOT_OUTPUTS | {gated_path, f"{gated_path}.meta", f"{gated_path}.spans"}


def is_mutmut_output_dir(name: str) -> bool:
    """`__pycache__` and `.pytest_cache`: written by the interpreter and pytest inside `mutants/`."""
    return name in MUTMUT_OUTPUT_DIRS


def mutmut_table(
    source_paths: Sequence[str],
    gated_path: str,
    also_copy: Sequence[str],
    selected: Sequence[str],
) -> dict[str, Any]:
    """The generated `[tool.mutmut]` table, keys per TD 5.8."""
    return {
        "source_paths": list(source_paths),
        "only_mutate": [gated_path],
        "do_not_mutate": [],
        "do_not_mutate_patterns": [],
        "type_check_command": [],
        "cache_invalidation_files": [],
        "also_copy": list(also_copy),
        "pytest_add_cli_args": generated_pytest_args(),
        "pytest_add_cli_args_test_selection": list(selected),
        "use_git_change_detection": False,
        "mutate_only_covered_lines": False,
        "track_dependencies": False,
        "timeout_multiplier": 15.0,
        "timeout_constant": 1.0,
        "max_stack_depth": -1,
        "process_isolation": "fork",
        "debug": False,
        "log_to_file": False,
    }


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    items = ", ".join(_toml_value(v) for v in value)
    return f"[{items}]"


def render_mutmut_table(table: Mapping[str, Any]) -> str:
    rows = [f"{key} = {_toml_value(value)}" for key, value in table.items()]
    return "[tool.mutmut]\n" + "\n".join(rows) + "\n"


def strip_tool_mutmut(text: str) -> str:
    """Remove the `[tool.mutmut]` table (header to the next table header)."""
    kept = []
    skipping = False
    for line in text.splitlines(keepends=True):
        header = TABLE_HEADER_RE.match(line.strip())
        if header and line.strip().startswith("[tool.mutmut]"):
            skipping = True
            continue
        if skipping and header:
            skipping = False
        if not skipping:
            kept.append(line)
    return "".join(kept)


def compose_pyproject(head_text: str, table: Mapping[str, Any]) -> str:
    """Head `pyproject.toml` with `[tool.mutmut]` replaced; proven by a tomllib round-trip."""
    out = strip_tool_mutmut(head_text).rstrip("\n") + "\n\n" + render_mutmut_table(table)
    before = tomllib.loads(head_text)
    after = tomllib.loads(out)
    before.get("tool", {}).pop("mutmut", None)
    got = after.get("tool", {}).pop("mutmut", None)
    if before != after or got != dict(table):
        raise GateError("generated mutmut config failed round-trip")
    return out


# ---------------------------------------------------------------------------
# Mutant mapping, classification and score (TD 5.9)
# ---------------------------------------------------------------------------


def changed_original_lines(original: str, mutated: str) -> list[int]:
    """1-based original-side lines that differ between a module and its mutant."""
    changed: set[int] = set()
    matcher = difflib.SequenceMatcher(None, split_lines(original), split_lines(mutated), False)
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed.update(range(i1 + 1, max(i2, i1 + 1) + 1))
    return sorted(changed)


def map_mutant_lines(
    changed: Iterable[int], statements: set[int], multiline: Mapping[int, int]
) -> list[int]:
    """Normalise changed lines to statement first lines (TD 5.3)."""
    return sorted({multiline.get(n, n) for n in changed} & statements)


def is_gated_mutant(mutant_lines: Iterable[int], gated: Iterable[int]) -> bool:
    return bool(set(mutant_lines) & set(gated))


def check_mutant_key(name: str) -> bool:
    """Bounded, mutmut-shaped key (untrusted child output)."""
    return len(name) <= MAX_KEY_CHARS and MUTANT_KEY_RE.match(name) is not None


def check_function_prefix(prefix: str) -> bool:
    """Bounded, mutmut-shaped mangled function prefix: a mutant key without `__mutmut_<n>`."""
    return len(prefix) <= MAX_KEY_CHARS and FUNCTION_PREFIX_RE.match(prefix) is not None


def classify_statuses(
    status_by_key: Mapping[str, str], gated_keys: Iterable[str]
) -> dict[str, Any]:
    """Count statuses over the gated mutants; timeout is a kill (H3)."""
    counts: dict[str, int] = {}
    killed = 0
    total = 0
    for key in sorted(gated_keys):
        status = status_by_key[key]
        if status not in KILLED_STATUSES and status not in NOT_KILLED_STATUSES:
            raise GateError("unexpected mutant status")
        counts[status] = counts.get(status, 0) + 1
        killed += status in KILLED_STATUSES
        total += 1
    return {"mutants_total": total, "mutants_killed": killed, "mutant_status_counts": counts}


def mutant_score_pct(killed: int, total: int) -> float | None:
    if total == 0:
        return None
    return percent_floor(killed, total)


def short_summary_lines(output: str) -> list[str]:
    """The FAILED/ERROR lines of the LAST pytest short-summary section, verbatim (TD 5.9 step 6)."""
    lines = ANSI_RE.sub("", output).splitlines()
    headers = [i for i, line in enumerate(lines) if SUMMARY_HEADER_RE.match(line.strip())]
    if not headers:
        return []
    section = []
    for line in lines[headers[-1] + 1 :]:
        if not line.startswith(("FAILED ", "ERROR ")):
            break
        section.append(line)
    return section


def parse_short_summary(output: str) -> list[str]:
    """Node IDs from the LAST pytest short-summary section only (TD 5.9 step 6)."""
    return [
        line.split(" ", 1)[1].split(" - ", 1)[0].strip() for line in short_summary_lines(output)
    ]


def tail_text(output: str, max_lines: int, max_chars: int) -> str:
    """The last `max_lines` lines of `output`, bounded to `max_chars` characters."""
    lines = output.strip().splitlines()
    return bound_text("\n".join(lines[-max_lines:]), max_chars)


def isolation_failure(stage: str, node_ids: Sequence[str], output: str) -> dict[str, Any]:
    """The evidence kept for `selected_test_fails_in_isolation` (ADR-2304 RV3-4a)."""
    return {
        "stage": stage,
        "node_ids": [bound_text(n, MAX_NODE_ID_CHARS) for n in node_ids],
        "summary_lines": [
            bound_text(line, MAX_SUMMARY_LINE_CHARS)
            for line in short_summary_lines(output)[:MAX_SUMMARY_LINES]
        ],
        "output_tail": tail_text(output, ISOLATION_TAIL_LINES, ISOLATION_TAIL_CHARS),
    }


# ---------------------------------------------------------------------------
# Shell (TD 5.11)
# ---------------------------------------------------------------------------


def shell_gate(
    path: str,
    exempt: bool,
    head_lines: Sequence[int],
    base_lines: Sequence[int],
    changed_head_lines: Iterable[int],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The shell record and fail reasons for one gated `.sh` file (H1, H4)."""
    if exempt:
        return {"exempt": "hos_bootstrap"}, []
    changed = set(changed_head_lines)
    counted = sorted({n for n in head_lines if n in changed})
    record = {
        "exempt": None,
        "base_count": len(base_lines),
        "head_count": len(head_lines),
        "counted_on_changed_lines": counted,
    }
    if not counted and len(head_lines) <= len(base_lines):
        return record, []
    shown = counted or sorted(set(head_lines))
    message = f"shell decision logic at {path}:{format_lines(shown)} — {MSG_SHELL}"
    return record, [fail_reason("shell_decision_logic", message)]


# ---------------------------------------------------------------------------
# Records, verdict and rendering (TD 5.14 to 5.16)
# ---------------------------------------------------------------------------


def blank_file_record(path: str, kind: str) -> dict[str, Any]:
    """A per-file record with every TD 5.15.2 field at its neutral value."""
    return {
        "path": bound_text(path, MAX_PATH_CHARS),
        "kind": kind,
        "blob_sha": None,
        "pr_head_blob_sha": None,
        "gated_statements": 0,
        "gated_lines": [],
        "gated_lines_truncated": False,
        "executed_gated": 0,
        "coverage_pct": None,
        "mutation_ran": False,
        "mutation_reason": None,
        "mutants_total": 0,
        "mutants_killed": 0,
        "mutant_score_pct": None,
        "mutant_status_counts": {},
        "unmutatable_gated_lines": [],
        "decision_logic_findings": [],
        "decision_logic_findings_truncated": False,
        "selection_method": "none",
        "selected_tests_count": 0,
        "selected_tests": [],
        "selected_tests_truncated": False,
        "removed_repo_copy": [],
        "path_load_findings": [],
        "shell": None,
        "exception": None,
        "exception_path": EXCEPTION_PATH_TEXT,
        "fail_reasons": [],
        "seconds": 0.0,
        "enumerate_seconds": 0.0,
        "workspace_seconds": 0.0,
        "mutmut_seconds": 0.0,
        "collect_seconds": 0.0,
        "isolation_failure": None,
        "shards": [],
        "plan_hash": None,
        "N": None,
    }


def gated_lines_fields(lines: Sequence[int]) -> dict[str, Any]:
    return {
        "gated_lines": list(lines[:MAX_GATED_LINES]),
        "gated_lines_truncated": len(lines) > MAX_GATED_LINES,
    }


def findings_fields(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "decision_logic_findings": [dict(f) for f in findings[:MAX_GATED_LINES]],
        "decision_logic_findings_truncated": len(findings) > MAX_GATED_LINES,
    }


def without_unhashed(value: Any) -> Any:
    """`value` with every UNHASHED_FIELDS key removed at any depth."""
    if isinstance(value, dict):
        return {k: without_unhashed(v) for k, v in value.items() if k not in UNHASHED_FIELDS}
    if isinstance(value, list):
        return [without_unhashed(v) for v in value]
    return value


def canonical_sha256(value: Any) -> str:
    """sha256 of the canonical JSON (sorted, compact, ASCII) of `value` minus UNHASHED_FIELDS."""
    canonical = json.dumps(
        without_unhashed(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def records_sha256(files: Sequence[Mapping[str, Any]]) -> str:
    """sha256 of the canonical JSON of `files` with every timing field removed (AC-29)."""
    return canonical_sha256(list(files))


def threshold_reasons(
    record: Mapping[str, Any], thresholds: Mapping[str, int]
) -> list[dict[str, str]]:
    """Coverage and score fails, computed from the record's numbers with exact arithmetic."""
    reasons = []
    path = record["path"]
    gated = record["gated_statements"]
    if gated and not meets_threshold(record["executed_gated"], gated, thresholds["coverage"]):
        pct = percent_floor(record["executed_gated"], gated)
        reasons.append(
            fail_reason(
                "coverage_below_threshold",
                f"{path}: gated line coverage {pct}% is below {thresholds['coverage']}% "
                f"({record['executed_gated']}/{gated})",
            )
        )
    total = record["mutants_total"]
    if record["mutation_ran"] and total:
        if not meets_threshold(record["mutants_killed"], total, thresholds["mutant_score"]):
            pct = percent_floor(record["mutants_killed"], total)
            reasons.append(
                fail_reason(
                    "mutant_score_below_threshold",
                    f"{path}: mutant score {pct}% is below {thresholds['mutant_score']}% "
                    f"({record['mutants_killed']}/{total})",
                )
            )
    return reasons


def ordered_reasons(reasons: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for reason in reasons:
        unique.setdefault(reason["code"], dict(reason))
    rank = {code: i for i, code in enumerate(FAIL_ORDER)}
    return sorted(unique.values(), key=lambda r: rank.get(r["code"], len(FAIL_ORDER)))


def ruling_applies(record: Mapping[str, Any], rulings: Sequence[Mapping[str, Any]]) -> bool:
    """S5: a ruling binds to the file's gated-tree blob and is void on any content change."""
    for ruling in rulings:
        if ruling.get("path") == record["path"] and ruling.get("blob_sha") == record["blob_sha"]:
            return True
    return False


def decide(
    records: Mapping[str, Any],
    rulings: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, int],
    upstream_errors: Sequence[str] = (),
) -> dict[str, Any]:
    """Pure verdict: per-file outcomes and the overall exit code (AD-1). Reads no environment."""
    internal = list(records.get("internal_errors") or [])
    internal.extend({"code": "upstream", "message": m} for m in upstream_errors)
    flagged = {e["file"] for e in internal if e.get("file")}
    files = []
    for record in sorted(records["files"], key=lambda r: r["path"]):
        reasons = ordered_reasons(
            list(record["fail_reasons"]) + threshold_reasons(record, thresholds)
        )
        codes = {r["code"] for r in reasons}
        outcome = "pass"
        if reasons or record["path"] in flagged:
            outcome = "fail"
        if reasons and codes <= RULING_ELIGIBLE and ruling_applies(record, rulings):
            outcome = "excepted"
        files.append({"path": record["path"], "outcome": outcome, "fail_reasons": reasons})
    failed = any(f["outcome"] == "fail" for f in files)
    exit_code = 3 if internal else 1 if failed else 0
    overall = "pass" if exit_code == 0 else "fail"
    return {"files": files, "overall": overall, "exit_code": exit_code, "internal_errors": internal}


def verdict_document(records: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    """The verdict artifact: the measure records plus outcomes (TD 5.15.1)."""
    by_path = {f["path"]: f for f in decision["files"]}
    files = []
    for record in records["files"]:
        merged = dict(record)
        merged["fail_reasons"] = by_path[record["path"]]["fail_reasons"]
        merged["outcome"] = by_path[record["path"]]["outcome"]
        files.append(merged)
    doc = {k: v for k, v in records.items() if k != "files"}
    doc.update(
        phase="verdict",
        files=files,
        internal_errors=decision["internal_errors"],
        overall=decision["overall"],
        exit_code=decision["exit_code"],
        measure_records_sha256=records.get("records_sha256"),
        records_sha256=records_sha256(files),
    )
    return doc


def attempt_number(value: Any) -> int | None:
    """A run attempt as an integer, or None when the value is not an integer or a digit string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def not_bound(name: str, got: Any, want: str) -> str:
    return (
        f"records not bound to this run: {name} is {bound_text(str(got), MAX_PATH_CHARS)}, {want}"
    )


def check_records_binding(
    records: Mapping[str, Any],
    mode: str,
    gated_sha: str,
    pr: int | None,
    run_id: str | None,
    run_attempt: int | None,
) -> str | None:
    """The one run-binding check, shared by `verdict` (CI) and `run` (local, no run id).

    The records must carry the mode, gated commit, PR and run id of this run, and an
    attempt no greater than the current one: a verdict-only re-run reads the records
    an earlier attempt wrote, while a record from a later attempt, another run or
    another commit is refused (RV-7).
    """
    expected = {"mode": mode, "gated_sha": gated_sha, "pr": pr, "run_id": run_id}
    for name, want in expected.items():
        if records.get(name) != want:
            return not_bound(name, records.get(name), f"expected {want}")
    written = records.get("run_attempt")
    if run_attempt is None:
        return None if written is None else not_bound("run_attempt", written, "expected none")
    attempt = attempt_number(written)
    if attempt is None or attempt > run_attempt:
        return not_bound("run_attempt", written, f"expected an integer of at most {run_attempt}")
    return None


def timeout_message(
    phase_seconds: Mapping[str, float],
    file_seconds: Mapping[str, tuple[float, float]],
    where: str,
    lead: str = MSG_TIMEOUT,
) -> str:
    """`lead` plus where the budget went: per phase, and per file (total, workspace)."""
    phases = ", ".join(f"{name} {secs:.1f}s" for name, secs in sorted(phase_seconds.items()))
    ranked = sorted(file_seconds.items(), key=lambda item: (-item[1][0], item[0]))
    files = ", ".join(
        f"{path} {total:.1f}s (workspace {setup:.1f}s)"
        for path, (total, setup) in ranked[:MAX_TIMEOUT_FILES]
    )
    return f"{lead} (ran out in {where}; phases: {phases}; slowest files: {files})"


def _cell(value: Any) -> str:
    """One Markdown-safe value: HTML-escaped, then backslash-escaped, then single-line (RV2-4b)."""
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\\", "\\\\")
    for char in "|`[]":
        text = text.replace(char, "\\" + char)
    return text.replace("\r", " ").replace("\n", " ")


def _fraction(pct: Any, num: int, den: int) -> str:
    if pct is None:
        return "n/a"
    return f"{pct}% ({num}/{den})"


def _error_lines(verdict: Mapping[str, Any]) -> list[str]:
    errors = verdict.get("internal_errors") or []
    if not errors:
        return []
    return ["", "Internal errors:"] + [
        f"- {_cell(e['code'])}: {_cell(e['message'])}" for e in errors
    ]


def _isolation_lines(rec: Mapping[str, Any]) -> list[str]:
    """The first parsed short-summary line of an isolation failure, escaped (RV3-4a)."""
    failure = rec.get("isolation_failure")
    lines = failure.get("summary_lines") if isinstance(failure, dict) else None
    if not isinstance(lines, list) or not lines:
        return []
    return [f"- {_cell(lines[0])}"]


def _shard_indices(rec: Mapping[str, Any]) -> str:
    return ",".join(str(s["index"]) for s in rec.get("shards") or []) or "-"


def _not_final_lines(rec: Mapping[str, Any]) -> list[str]:
    """Partial per-shard results of a file whose score is not final (REQ-42)."""
    rows = rec.get("shards") or []
    if rec.get("mutants_total") is not None or not rows:
        return []
    lines = []
    for row in rows:
        counts = "n/a" if row["total"] is None else f"{row['killed']}/{row['total']} killed"
        lines.append(
            f"- {_cell(rec['path'])}: shard {row['index']} ({_cell(row['status'])}): "
            f"{counts} (not final)"
        )
    return lines


def _runner_minutes_line(shards: Mapping[str, Any], verdict: Mapping[str, Any]) -> str:
    total = verdict.get("runner_minutes_total")
    if total is not None:
        return f"Runner minutes: {total} ({RUNNER_MINUTES_LABEL})"
    lacking = []
    if verdict.get("plan_job_seconds") is None:
        lacking.append("plan")
    lacking.extend(f"shard {s['index']}" for s in shards["per_shard"] if s["job_seconds"] is None)
    return f"Runner minutes: n/a (no job-start time for: {', '.join(lacking) or 'unknown'})"


def _shard_lines(verdict: Mapping[str, Any]) -> list[str]:
    """The "Shards" line, one row per shard, and the runner-minutes line (REQ-42, REQ-44)."""
    shards = verdict.get("shards")
    if not isinstance(shards, dict):
        return []
    work = f"estimated work {shards['W_ci_minutes']} CI-min"
    if shards["capped"]:
        work += f" exceeds {shards['N_max']} x {shards['T_minutes']}; running {shards['N']} shards"
    else:
        work += f" against {shards['T_minutes']} CI-min per shard"
    out = ["", f"Shards: {shards['N']}, capped {str(shards['capped']).lower()}, {work}.", ""]
    out.append(
        "| Shard | Status | Files | est_mutation_ms | est_fixed_ms | job_seconds | Attempt |"
    )
    out.append("|---|---|---|---|---|---|---|")
    for row in shards["per_shard"]:
        job = "n/a" if row["job_seconds"] is None else row["job_seconds"]
        files = ", ".join(row["files"]) or "-"
        cells = [row["index"], row["status"], files, row["est_mutation_ms"]]
        cells += [row["est_fixed_ms"], job, row["run_attempt"]]
        out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    out.extend(["", _runner_minutes_line(shards, verdict)])
    return out


def render_summary(verdict: Mapping[str, Any]) -> str:
    """The Markdown check summary (TD 5.16, 5.20.9)."""
    files = verdict["files"]
    if not files:
        lines = ["No gated files in this PR.", *_shard_lines(verdict), *_error_lines(verdict)]
        return "\n".join(lines) + "\n"
    out = [
        "| File | Kind | Coverage (covered/gated) | Mutant score (killed/total) | Shards "
        "| Selection | Outcome | Reasons |",
        "|---|---|---|---|---|---|---|---|",
    ]
    details: list[str] = []
    for rec in files:
        cov = _fraction(rec["coverage_pct"], rec["executed_gated"], rec["gated_statements"])
        score = _fraction(rec["mutant_score_pct"], rec["mutants_killed"], rec["mutants_total"])
        codes = ", ".join(r["code"] for r in rec["fail_reasons"])
        row = [rec["path"], rec["kind"], cov, score, _shard_indices(rec), rec["selection_method"]]
        row += [rec["outcome"], codes]
        out.append("| " + " | ".join(_cell(c) for c in row) + " |")
        details.extend(f"- {_cell(r['message'])}" for r in rec["fail_reasons"])
        details.extend(_isolation_lines(rec))
        details.extend(_not_final_lines(rec))
    passed = sum(1 for r in files if r["outcome"] == "pass")
    out.append("")
    out.append(f"{len(files)} gated file(s): {passed} pass, overall {verdict['overall']}.")
    out.extend(_shard_lines(verdict))
    if details:
        out.append("")
        out.extend(details)
    out.extend(_error_lines(verdict))
    return "\n".join(out) + "\n"
