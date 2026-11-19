"""Structural validity of every GraphQL literal shipped in the repo (#2377).

`_CLOSER_QUERY` once shipped with 11 `{` and 10 `}`; GitHub rejected every call
and the selector failed closed on every closed blocker. These tests need no
network and no GraphQL library: a small self-contained validator checks
delimiter balance, non-empty selection sets and a single complete document.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from scripts.automation.lib import github as gh_lib
from scripts.framework import select_work_candidates as swc

REPO_ROOT = Path(__file__).resolve().parents[2]
_PAIRS = {")": "(", "]": "[", "}": "{"}
_NAME = re.compile(r"[_A-Za-z][_0-9A-Za-z]*")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")


def tokenize_graphql(text: str) -> list[str]:
    """Tokens of a GraphQL document; strings, comments, commas and whitespace
    are skipped (a string literal becomes a single `"` token)."""
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n,﻿":
            i += 1
        elif ch == "#":
            while i < n and text[i] not in "\r\n":
                i += 1
        elif text.startswith('"""', i):
            end = text.find('"""', i + 3)
            while end != -1 and text[end - 1] == "\\":
                end = text.find('"""', end + 1)
            if end == -1:
                raise ValueError("unterminated block string")
            tokens.append('"')
            i = end + 3
        elif ch == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] in "\r\n":
                    raise ValueError("newline in string literal")
                i += 2 if text[i] == "\\" else 1
            if i >= n:
                raise ValueError("unterminated string")
            tokens.append('"')
            i += 1
        elif text.startswith("...", i):
            tokens.append("...")
            i += 3
        elif ch in "!$:=@&|(){}[]":
            tokens.append(ch)
            i += 1
        elif m := _NAME.match(text, i):
            tokens.append(m.group())
            i = m.end()
        elif m := _NUMBER.match(text, i):
            tokens.append(m.group())
            i = m.end()
        else:
            raise ValueError(f"unexpected character {ch!r} at offset {i}")
    return tokens


def validate_graphql(text: str) -> None:
    """Raise ValueError unless `text` is a structurally valid single-operation
    document: balanced and correctly nested delimiters (never negative), every
    selection set non-empty, a selection set opening only where one can
    legally open, and nothing trailing the operation's closing brace."""
    tokens = tokenize_graphql(text)
    if not tokens:
        raise ValueError("empty document")
    stack: list[str] = []
    closed_top_level = False
    for idx, tok in enumerate(tokens):
        if closed_top_level:
            raise ValueError(f"trailing tokens after the operation: {tokens[idx:]}")
        if tok in "({[":
            stack.append(tok)
            if tok == "{" and idx + 1 < len(tokens) and tokens[idx + 1] == "}":
                raise ValueError("empty selection set")
        elif tok in _PAIRS:
            if not stack:
                raise ValueError(f"unbalanced {tok!r}: nesting went negative")
            if stack.pop() != _PAIRS[tok]:
                raise ValueError(f"mismatched {tok!r}")
            if tok == "}" and not stack:
                closed_top_level = True
    if stack:
        raise ValueError(f"unclosed delimiters: {stack}")
    if not closed_top_level:
        raise ValueError("document has no selection set")


def delimiter_counts(text: str) -> dict[str, int]:
    tokens = tokenize_graphql(text)
    return {d: tokens.count(d) for d in "{}[]()"}


def _bash_query_literal() -> str:
    source = (REPO_ROOT / "bootstrap" / "post_review_thread.sh").read_text()
    literals = re.findall(r"-f query='([^']*)'", source)
    assert len(literals) == 1, literals
    return literals[0]


def _merge_authority_mutation() -> str:
    path = REPO_ROOT / "scripts" / "automation" / "lib" / "merge_authority.py"
    tree = ast.parse(path.read_text())
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "_convert_pr_to_draft":
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "mutation" for t in node.targets)
                    and isinstance(node.value, ast.Constant)
                ):
                    return str(node.value.value)
    raise AssertionError("mutation literal not found in _convert_pr_to_draft")


def _literals() -> dict[str, str]:
    return {
        "_CLOSER_QUERY": swc._CLOSER_QUERY,
        "_REVIEW_THREADS_QUERY": gh_lib._REVIEW_THREADS_QUERY,
        "merge_authority mutation": _merge_authority_mutation(),
        "post_review_thread.sh mutation": _bash_query_literal(),
    }


@pytest.mark.parametrize("name", list(_literals()))
def test_graphql_literal_is_structurally_valid(name):
    validate_graphql(_literals()[name])


def test_closer_query_braces_are_balanced():
    counts = delimiter_counts(swc._CLOSER_QUERY)
    assert counts["{"] == counts["}"], counts
    assert counts["["] == counts["]"] and counts["("] == counts[")"], counts


class TestValidatorItself:
    @pytest.mark.parametrize(
        "doc",
        [
            "{ a }",
            "query($x:Int!){ a(n:$x){ b ... on T{ c } } }",
            '{ a(s:"}{") } # }',
            '{ a(s:"""}""") }',
        ],
    )
    def test_accepts_valid(self, doc):
        validate_graphql(doc)

    @pytest.mark.parametrize(
        "doc",
        [
            "",
            "{ a",
            "{ a } }",
            "} {",
            "{ a(x:1 }",
            "{ a(x:[1) }",
            "{ }",
            "{ a } { b }",
            "query",
            '{ a(s:"unterminated) }',
        ],
    )
    def test_rejects_invalid(self, doc):
        with pytest.raises(ValueError):
            validate_graphql(doc)
