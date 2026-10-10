"""Static scans that keep the temp-hygiene contract from regressing (#2054, T7).

D10 / AC-14: tests may not create temp paths that outlive the test
(``tempfile.mkdtemp``, ``tempfile.mkstemp``, ``NamedTemporaryFile(delete=False)``),
under any import or alias form. They write into ``tmp_path`` instead. Also pins
the retention ini values, the empty leak allowlist, and the ban on neutralising
the TMPDIR redirect.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests import tmp_hygiene

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

# (relative path, reason). Starts empty; an entry needs a reason a reviewer accepted.
CREATION_ALLOWLIST: tuple[tuple[str, str], ...] = ()

_BANNED = {"mkdtemp", "mkstemp", "NamedTemporaryFile"}


def banned_temp_calls(source: str) -> list[tuple[int, str]]:
    """(line, description) for each banned temp-path creation in ``source``."""
    tree = ast.parse(source)
    module_aliases: set[str] = set()  # names bound to the tempfile module
    symbol_aliases: dict[str, str] = {}  # local name -> banned tempfile symbol
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tempfile":
                    module_aliases.add(alias.asname or "tempfile")
        elif isinstance(node, ast.ImportFrom) and node.module == "tempfile":
            for alias in node.names:
                if alias.name == "*":
                    hits.append((node.lineno, "from tempfile import *"))
                elif alias.name in _BANNED:
                    symbol_aliases[alias.asname or alias.name] = alias.name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        symbol = None
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in module_aliases and func.attr in _BANNED:
                symbol = func.attr
        elif isinstance(func, ast.Name) and func.id in symbol_aliases:
            symbol = symbol_aliases[func.id]
        if symbol is None:
            continue
        if symbol == "NamedTemporaryFile":
            delete_false = any(
                kw.arg == "delete"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is False
                for kw in node.keywords
            )
            if not delete_false:
                continue
            symbol = "NamedTemporaryFile(delete=False)"
        hits.append((node.lineno, symbol))
    return sorted(hits)


def neutralised_tmpdir(source: str) -> list[int]:
    """Lines that set TMPDIR to the literal "/tmp" via monkeypatch.setenv or os.environ."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setenv"
        ):
            if len(node.args) >= 2:
                key, value = node.args[0], node.args[1]
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(value, ast.Constant)
                    and key.value == "TMPDIR"
                    and value.value == "/tmp"
                ):
                    lines.append(node.lineno)
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and node.value.value == "/tmp"
        ):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "TMPDIR"
                ):
                    lines.append(node.lineno)
    return sorted(lines)


def _test_files() -> list[Path]:
    return sorted(p for p in TESTS.rglob("*.py") if ".venv" not in p.parts)


def test_no_test_creates_a_temp_path_that_outlives_it():
    allowed = {path for path, _ in CREATION_ALLOWLIST}
    offenders = []
    for path in _test_files():
        rel = str(path.relative_to(ROOT))
        if rel in allowed:
            continue
        offenders += [f"{rel}:{line}: {what}" for line, what in banned_temp_calls(path.read_text())]
    assert not offenders, "use tmp_path (tests/tmp_hygiene.named_temp / make_dir):\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        ("import tempfile\ntempfile.mkdtemp()\n", ["mkdtemp"]),
        ("import tempfile as t\nt.mkstemp()\n", ["mkstemp"]),
        ("from tempfile import mkdtemp as m\nm()\n", ["mkdtemp"]),
        ("from tempfile import mkstemp\nmkstemp()\n", ["mkstemp"]),
        (
            "from tempfile import NamedTemporaryFile\nNamedTemporaryFile(delete=False)\n",
            ["NamedTemporaryFile(delete=False)"],
        ),
        (
            "import tempfile as tf\ntf.NamedTemporaryFile(suffix='.py', delete=False)\n",
            ["NamedTemporaryFile(delete=False)"],
        ),
        ("from tempfile import *\n", ["from tempfile import *"]),
        ("import tempfile\ntempfile.NamedTemporaryFile()\n", []),
        ("import tempfile\ntempfile.NamedTemporaryFile(delete=True)\n", []),
        ("import tempfile\ntempfile.TemporaryDirectory()\n", []),
        ("import tempfile\ntempfile.gettempdir()\n", []),
        ("import os\nos.mkdtemp()\n", []),
        ("mkdtemp = lambda: 1\nmkdtemp()\n", []),
    ],
)
def test_scanner_resolves_every_import_and_alias_form(source, expected):
    assert [what for _, what in banned_temp_calls(source)] == expected


def test_pyproject_pins_the_retention_policy():
    text = (ROOT / "pyproject.toml").read_text()
    assert re.search(r'^tmp_path_retention_count = "1"$', text, re.M)
    assert re.search(r'^tmp_path_retention_policy = "failed"$', text, re.M)
    assert not re.search(r"^basetemp\s*=", text, re.M), "a fixed basetemp is wiped at session start"


def test_leak_allowlist_is_empty():
    assert tmp_hygiene.LEAK_ALLOWLIST == ()


def test_creation_allowlist_is_empty():
    assert CREATION_ALLOWLIST == ()


def test_no_test_neutralises_the_tmpdir_redirect():
    offenders = []
    for path in _test_files():
        offenders += [f"{path.relative_to(ROOT)}:{n}" for n in neutralised_tmpdir(path.read_text())]
    assert not offenders, "never set TMPDIR to /tmp in a test (#2054 §4.9):\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    "source,count",
    [
        ('monkeypatch.setenv("TMPDIR", "/tmp")\n', 1),
        ('import os\nos.environ["TMPDIR"] = "/tmp"\n', 1),
        ('monkeypatch.setenv("TMPDIR", str(tmp_path))\n', 0),
        ('monkeypatch.setenv("TMP", "/tmp")\n', 0),
    ],
)
def test_neutralisation_scanner(source, count):
    assert len(neutralised_tmpdir(source)) == count
