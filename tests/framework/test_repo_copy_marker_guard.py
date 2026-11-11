"""Guard for the `repo_copy` marker (#2304, TD 5.18).

The new-code gate runs the selected tests inside a mutation workspace and never
runs a test that copies, clones, worktree-adds or archives the repository root.
Such tests must carry `@pytest.mark.repo_copy`, at test, class or module level.

This is a heuristic over the AST and is allowed to miss; the gate's tripwire plugin
is the backstop. It imports no gate code, so no coverage context selects it.
"""

import ast
import textwrap
import tomllib
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

ROOT_NAMES = frozenset({"REPO_ROOT", "_REPO_ROOT", "repo_root", "ROOT"})
PATH_WRAPPERS = frozenset({"str", "Path", "fspath"})


def _is_file_chain(node):
    """`Path(__file__)` optionally followed by `.resolve()` / `.absolute()`."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in ("resolve", "absolute") and _is_file_chain(node.func.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path":
        return any(isinstance(a, ast.Name) and a.id == "__file__" for a in node.args)
    return False


def _parent_depth(node):
    """Number of `.parent` hops over a `Path(__file__)` chain, or 0."""
    depth = 0
    while isinstance(node, ast.Attribute) and node.attr == "parent":
        depth += 1
        node = node.value
    return depth if _is_file_chain(node) else 0


def _is_root_expr(node):
    """A repo-root expression: exactly the root, never a path below it."""
    if isinstance(node, ast.Name):
        return node.id in ROOT_NAMES
    if isinstance(node, ast.Subscript):
        value = node.value
        return (
            isinstance(value, ast.Attribute)
            and value.attr == "parents"
            and _is_file_chain(value.value)
        )
    if isinstance(node, ast.Attribute):
        return _parent_depth(node) >= 2
    if isinstance(node, ast.JoinedStr):
        last = node.values[-1] if node.values else None
        return isinstance(last, ast.FormattedValue) and _is_root_expr(last.value)
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        constants = [c.value for c in ast.walk(node) if isinstance(c, ast.Constant)]
        if "--show-toplevel" in constants:
            return True
        return name in PATH_WRAPPERS and len(node.args) == 1 and _is_root_expr(node.args[0])
    return False


def _has_root_operand(call):
    """True when a root expression appears in the call, outside any `ROOT / "x"` join."""
    stack = list(call.args) + [kw.value for kw in call.keywords]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            continue
        if _is_root_expr(node):
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def _copies_repo(call):
    name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
    strings = [c.value for c in ast.walk(call) if isinstance(c, ast.Constant)]
    if name == "copytree":
        keywords = {kw.arg: kw.value for kw in call.keywords}
        src = call.args[0] if call.args else keywords.get("src")
        return src is not None and _is_root_expr(src)
    git_copy = "clone" in strings or "archive" in strings
    worktree_add = "worktree" in strings and "add" in strings
    return (git_copy or worktree_add) and _has_root_operand(call)


def _is_repo_copy_mark(node):
    target = node.func if isinstance(node, ast.Call) else node
    return isinstance(target, ast.Attribute) and target.attr == "repo_copy"


def _module_marked(tree):
    for node in tree.body:
        names = [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        if isinstance(node, ast.Assign) and "pytestmark" in names:
            marks = ast.walk(node.value)
            if any(_is_repo_copy_mark(m) for m in marks):
                return True
    return False


def find_unmarked_repo_copies(source: str) -> list[int]:
    """Line numbers of repo-copying calls that sit outside a `repo_copy`-marked scope."""
    tree = ast.parse(source)
    if _module_marked(tree):
        return []
    found = []

    def visit(node, marked):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            marked = marked or any(_is_repo_copy_mark(d) for d in node.decorator_list)
        if isinstance(node, ast.Call) and not marked and _copies_repo(node):
            found.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, marked)

    visit(tree, False)
    return sorted(found)


def _src(text):
    return textwrap.dedent(text)


@pytest.mark.parametrize(
    "body",
    [
        "shutil.copytree(REPO_ROOT, dst)",
        "shutil.copytree(ROOT, dst)",
        "shutil.copytree(src=ROOT, dst=dst)",
        "shutil.copytree(Path(__file__).resolve().parents[2], dst)",
        "shutil.copytree(Path(__file__).parent.parent, dst)",
        "subprocess.run(['git', 'clone', str(REPO_ROOT), str(dst)])",
        "subprocess.run(['git', 'clone', f'file://{ROOT}', str(dst)])",
        "subprocess.run(['git', 'archive', 'HEAD'], cwd=REPO_ROOT)",
        "_git(ROOT, 'worktree', 'add', '-q', str(dst))",
        "subprocess.run(['git', '-C', str(repo_root), 'archive', 'HEAD'])",
        "subprocess.run(['git', 'clone', subprocess.check_output(['git', 'rev-parse', "
        "'--show-toplevel']), str(dst)])",
    ],
)
def test_unmarked_repo_copy_is_flagged(body):
    source = f"def test_x(dst):\n    {body}\n"
    assert find_unmarked_repo_copies(source) == [2]


@pytest.mark.parametrize(
    "body",
    [
        "shutil.copytree(ROOT / 'bin', dst)",
        "shutil.copytree(src, dst)",
        "subprocess.run(['git', 'clone', str(origin), str(dst)])",
        "subprocess.run(['git', 'archive', 'HEAD'], cwd=origin)",
        "subprocess.run(['git', 'clone', str(ROOT / 'x'), str(dst)])",
        "_git(repo, 'worktree', 'add', '-q', str(dst))",
        "subprocess.run(['git', 'status'], cwd=REPO_ROOT)",
        "shutil.copytree()",
    ],
)
def test_subdirectory_and_fixture_copies_are_not_flagged(body):
    assert find_unmarked_repo_copies(f"def test_x(dst):\n    {body}\n") == []


def test_marks_at_test_class_and_module_level_clear_the_finding():
    call = "shutil.copytree(REPO_ROOT, dst)"
    function = f"@pytest.mark.repo_copy\ndef test_x(dst):\n    {call}\n"
    klass = f"@pytest.mark.repo_copy\nclass TestX:\n    def test_x(self, dst):\n        {call}\n"
    module = f"pytestmark = pytest.mark.repo_copy\n\ndef test_x(dst):\n    {call}\n"
    listed = (
        f"pytestmark = [pytest.mark.slow, pytest.mark.repo_copy]\n\ndef test_x(d):\n    {call}\n"
    )
    for source in (function, klass, module, listed):
        assert find_unmarked_repo_copies(source) == []
    other = f"@pytest.mark.slow\ndef test_x(dst):\n    {call}\n"
    assert find_unmarked_repo_copies(other) == [3]


def test_helper_outside_a_marked_test_is_flagged():
    source = _src(
        """
        def _helper(dst):
            shutil.copytree(REPO_ROOT, dst)

        @pytest.mark.repo_copy
        def test_x(dst):
            _helper(dst)
        """
    )
    assert find_unmarked_repo_copies(source) == [3]


def test_every_repo_copying_test_is_marked_repo_copy():
    offenders = {}
    for path in sorted(TESTS_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = find_unmarked_repo_copies(text)
        if lines:
            offenders[str(path.relative_to(TESTS_DIR))] = lines
    assert offenders == {}


def test_repo_copy_marker_is_registered_and_markers_are_strict():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    pytest_cfg = config["tool"]["pytest"]["ini_options"]
    assert "--strict-markers" in pytest_cfg["addopts"].split()
    registered = [m.split(":")[0].strip() for m in pytest_cfg["markers"]]
    assert "repo_copy" in registered
    description = next(m for m in pytest_cfg["markers"] if m.startswith("repo_copy"))
    assert "#2304" in description
