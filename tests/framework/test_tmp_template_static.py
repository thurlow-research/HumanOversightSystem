"""Static scan: no ``mktemp`` in the shipped scripts may pin a literal ``/tmp`` (#2054, T9).

AC-14 forms, all of which bypass the ``TMPDIR`` redirect that keeps scratch
off the RAM-backed ``/tmp``:

* a template operand beginning with ``/tmp/`` (including the operand after ``-t``)
* ``-p /tmp`` or ``-p/tmp``
* ``--tmpdir=/tmp`` or ``--tmpdir /tmp``

The compliant spelling is ``"${TMPDIR:-/tmp}/name.XXXXXX"``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("scripts", "bin", "bootstrap")
SKIP_PARTS = {".venv", "node_modules", "__pycache__"}

# (relative path, reason). An entry needs a reason a reviewer accepted.
TEMPLATE_ALLOWLIST: dict[str, str] = {
    "scripts/framework/run_tests_inner_loop.sh": (
        "#1903 by design: the failure log must survive a full or unwritable TMPDIR, "
        "so it is created on /tmp deliberately"
    ),
}

_MKTEMP = re.compile(r"(?<![\w$./-])mktemp\b(?P<args>[^)|;&`\n]*)")
_Q = r"""["']?"""
_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("template operand starting /tmp/", re.compile(rf"(?:^|\s){_Q}/tmp/")),
    ("-p /tmp", re.compile(rf"(?:^|\s)-p\s*{_Q}/tmp(?![\w.-])")),
    ("--tmpdir /tmp", re.compile(rf"(?:^|\s)--tmpdir(?:=|\s+){_Q}/tmp(?![\w.-])")),
)


def literal_tmp_mktemp(text: str) -> list[tuple[int, str]]:
    """(line, form) for each ``mktemp`` call in ``text`` that pins a literal /tmp."""
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for call in _MKTEMP.finditer(line):
            args = call.group("args")
            for form, pattern in _FORMS:
                if pattern.search(args):
                    hits.append((lineno, form))
    return hits


def _scanned_files() -> list[Path]:
    files = []
    for top in SCAN_DIRS:
        for path in sorted((ROOT / top).rglob("*")):
            if path.is_file() and not SKIP_PARTS & set(path.parts):
                files.append(path)
    return files


@pytest.mark.parametrize(
    "snippet, form",
    [
        ("f=$(mktemp /tmp/x.XXXX)", "template operand starting /tmp/"),
        ('f=$(mktemp "/tmp/x.XXXX")', "template operand starting /tmp/"),
        ("f=$(mktemp -p /tmp)", "-p /tmp"),
        ("f=$(mktemp -p/tmp x.XXXX)", "-p /tmp"),
        ('f=$(mktemp -d -p "/tmp" x.XXXX)', "-p /tmp"),
        ("f=$(mktemp --tmpdir=/tmp x.XXXX)", "--tmpdir /tmp"),
        ("f=$(mktemp --tmpdir /tmp x.XXXX)", "--tmpdir /tmp"),
        ("f=$(mktemp -t /tmp/x.XXXX)", "template operand starting /tmp/"),
    ],
)
def test_matcher_flags_each_ac14_form(snippet, form):
    assert [h[1] for h in literal_tmp_mktemp(snippet)] == [form]


@pytest.mark.parametrize(
    "snippet",
    [
        'f=$(mktemp "${TMPDIR:-/tmp}/x.XXXX")',
        'f=$(mktemp -d "${TMPDIR:-/tmp}/x.XXXX")',
        'f=$(mktemp -p "${TMPDIR:-/tmp}" x.XXXX)',
        "f=$(mktemp -t hos-idx.XXXXXX)",
        "f=$(mktemp)",
        'f=$(mktemp "$dir/x.XXXX")',
        "f=$(mktemp -p /tmpfoo)",
        "# mktemp /tmp/x.XXXX in a comment",
    ],
)
def test_matcher_accepts_compliant_forms(snippet):
    assert literal_tmp_mktemp(snippet) == []


def test_no_literal_tmp_mktemp_outside_allowlist():
    offenders = []
    for path in _scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in TEMPLATE_ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        offenders += [f"{rel}:{n} ({form})" for n, form in literal_tmp_mktemp(text)]
    assert not offenders, 'literal /tmp mktemp (use "${TMPDIR:-/tmp}/..."):\n' + "\n".join(
        offenders
    )


def test_allowlist_entries_are_live_and_justified():
    for rel, reason in TEMPLATE_ALLOWLIST.items():
        path = ROOT / rel
        assert path.is_file(), f"stale allowlist entry: {rel}"
        assert reason.strip()
        assert literal_tmp_mktemp(
            path.read_text(encoding="utf-8")
        ), f"{rel} no longer uses a literal /tmp mktemp; drop the allowlist entry"
