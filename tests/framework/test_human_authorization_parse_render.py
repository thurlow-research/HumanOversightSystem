"""Tests for human_authorization parse_act / render_form / render_request
(TD-2101 §7.2, T-PR-*). Pure: no network, no git."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.framework import human_authorization as ha
from scripts.framework.human_authorization import (
    PARSE_ERRORS,
    Act,
    ParseError,
    canonicalize_path,
    parse_act,
    render_form,
    render_request,
)

ROOT = Path(__file__).resolve().parents[2]
B = "patch:" + "a" * 40
HDR = f"/hos authorize step=5 binding={B}"
OK_TAIL = "\ncovers: C7\nreviewed_files:\n  - scripts/x.py"

MIXES = [
    (5, ("C7",), ("scripts/x.py",)),
    (1, ("C7", "RA-FALLBACK"), ("a.py", "b/c.md")),
    (12, ("C10:new-user-flow-or-route", "BF:dep-mapper-low"), ("docs/y.md",)),
    (9999999999, ("BF:a-b-c",), ("path with space/f.txt",)),
    (3, ("C10:a", "C10:b", "C7"), ("x", "y", "z")),
    (7, ("C7",), ("weird-ünï.py", "a'b.py")),
]


@pytest.mark.parametrize("step,items,files", MIXES)
def test_t_pr_1_round_trip(step, items, files):
    assert parse_act(render_form(step, B, items, files)) == Act("authorize", step, B, items, files)


@pytest.mark.parametrize("step,items,files", MIXES[:3])
def test_t_pr_2_round_trip_fenced_crlf_bom(step, items, files):
    form = render_form(step, B, items, files)
    want = Act("authorize", step, B, items, files)
    assert parse_act("```text\n" + form + "\n```") == want
    assert parse_act("```text\r\n" + form.replace("\n", "\r\n") + "\r\n```\r\n") == want
    assert parse_act(form.replace("\n", "\r\n")) == want
    assert parse_act("\ufeff" + form) == want
    assert parse_act("\n\n  " + form) == want


def _err(body):
    got = parse_act(body)
    assert isinstance(got, ParseError), got
    return got.detail_text()


ERROR_ROWS = [
    ("marker-line", "/hos authorize step=5 binding=" + B + " junk"),
    ("unknown-key", f"/hos authorize step=5 binding={B} foo=1" + OK_TAIL),
    ("duplicate-key:step", f"/hos authorize step=5 step=6 binding={B}" + OK_TAIL),
    ("missing-field:binding", "/hos authorize step=5" + OK_TAIL),
    ("missing-field:step", f"/hos authorize binding={B}" + OK_TAIL),
    ("bad-step", f"/hos authorize step=05 binding={B}" + OK_TAIL),
    ("bad-binding", "/hos authorize step=5 binding=patch:ABC" + OK_TAIL),
    ("empty-covers@L2", HDR + "\ncovers:\nreviewed_files:\n  - a"),
    ("bad-item@L2", HDR + "\ncovers: nonsense\nreviewed_files:\n  - a"),
    ("duplicate-item@L2", HDR + "\ncovers: C7 C7\nreviewed_files:\n  - a"),
    ("duplicate-field:covers", HDR + "\ncovers: C7\ncovers: C7"),
    (
        "duplicate-field:reviewed_files",
        HDR + "\ncovers: C7\nreviewed_files:\n  - a\nreviewed_files:\n  - b",
    ),
    ("second-marker@L3", HDR + "\ncovers: C7\n/hos decline step=5"),
    ("unexpected-line@L3", HDR + "\ncovers: C7\nwhat is this"),
    ("bad-path@L4", HDR + "\ncovers: C7\nreviewed_files:\n  -"),
    ("bad-path@L4", HDR + "\ncovers: C7\nreviewed_files:\n  - ''"),
    ("decline-extra-line@L2", "/hos decline step=5\nextra"),
    ("unterminated-fence@L2", "```text\n" + HDR + OK_TAIL),
    ("text-after-fence@L7", "```text\n" + HDR + OK_TAIL + "\n```\nmore text"),
    ("unknown-key@L3", HDR + "\ncovers: C7\nfoo: bar"),
    ("missing-field:covers", HDR + "\nreviewed_files:\n  - a"),
]


@pytest.mark.parametrize("want,body", ERROR_ROWS)
def test_t_pr_3_parse_errors(want, body):
    assert _err(body) == want


def test_t_pr_3_every_parse_error_code_has_a_row():
    covered = {w.split("@")[0].split(":")[0] for w, _ in ERROR_ROWS}
    assert covered == PARSE_ERRORS


def test_t_pr_3_unknown_key_is_checked_before_duplicate_key():
    assert _err(f"/hos authorize step=5 step=6 foo=1 binding={B}" + OK_TAIL) == "unknown-key"


def test_t_pr_3b_inline_reviewed_files_text():
    body = HDR + "\ncovers: C7\nreviewed_files: foo.py"
    assert _err(body) == "unexpected-line@L3"
    ok = HDR + "\ncovers: C7\nreviewed_files:   \n  - scripts/x.py"
    assert parse_act(ok) == Act("authorize", 5, B, ("C7",), ("scripts/x.py",))


@pytest.mark.parametrize(
    "body", ["", "   \n\t", "hello", "/hostile", "```", "```text\n```", "```\nhello\n```", "/hos"]
)
def test_t_pr_4_not_candidates(body):
    assert parse_act(body) is None


def test_t_pr_5_candidacy_is_case_insensitive_rules_are_not():
    assert _err("/HOS Authorize step=5 binding=" + B + OK_TAIL) == "marker-line"
    assert _err("/hos Authorize step=5") == "marker-line"
    assert _err(HDR + "\nCOVERS: C7") == "unknown-key@L2"


def test_t_pr_6_free_text_after_rule_is_ignored():
    body = HDR + OK_TAIL + "\n---\nthanks!\n/hos decline step=5"
    assert parse_act(body) == Act("authorize", 5, B, ("C7",), ("scripts/x.py",))
    assert parse_act("/hos decline step=5\n---\nwhatever") == Act("decline", 5, None, (), ())


def test_t_pr_7_decline_with_binding_is_unknown_key():
    assert _err(f"/hos decline step=5 binding={B}") == "unknown-key"


def test_decline_with_trailing_blank_lines_ok():
    assert parse_act("/hos decline step=5\n\n  \n") == Act("decline", 5, None, (), ())


@pytest.mark.parametrize(
    "args",
    [
        (5, B, ("C7",), ()),
        (5, B, (), ("a",)),
        (5, B, ("bad item",), ("a",)),
        (5, B, ("C7", "C7"), ("a",)),
        (5, "patch:xyz", ("C7",), ("a",)),
        (0, B, ("C7",), ("a",)),
        (5, B, ("C7",), ("a\tb",)),
        (5, B, ("C7",), ("./a",)),
        (5, B, ("C7",), ('"a"',)),
        (5, B, ("C7",), (" a",)),
        (5, B, ("C7",), ("a", "a")),
    ],
)
def test_t_pr_8_render_form_rejects(args):
    with pytest.raises(ValueError):
        render_form(*args)


def test_canonicalize_path():
    assert canonicalize_path("  ./a/b.py \t") == "a/b.py"
    assert canonicalize_path("'a.py'") == "a.py"
    assert canonicalize_path('"a.py"') == "a.py"
    assert canonicalize_path("'a\"") == "'a\""
    assert canonicalize_path("././a") == "./a"
    assert canonicalize_path("Scripts/X.py") == "Scripts/X.py"


FORBIDDEN = (
    "Authorization required:",
    "Release candidate SHA:",
    "hos-escalation",
    "hos-recommendation",
    "hos-proxy-decision",
    ".claudetmp/",
    "-human-authorization.md",
)


def _req(**kw):
    base = dict(issue_url="https://github.com/o/r/issues/2101")
    base.update(kw)
    return render_request(5, B, ("C7", "BF:dep-mapper-low"), ("scripts/x.py",), **base)


def test_t_pr_9_render_request_contents():
    out = _req(
        pr_url="https://github.com/o/r/pull/9",
        findings=(
            ("dep-mapper-low", "dep-mapper", "dependency\nblast radius hos-escalation is LOW"),
        ),
    )
    assert out.startswith("### Action needed")
    assert "https://github.com/o/r/issues/2101" in out
    assert "(or the PR: https://github.com/o/r/pull/9)" in out
    assert (
        "```text\n" + render_form(5, B, ("C7", "BF:dep-mapper-low"), ("scripts/x.py",)) + "\n```"
        in out
    )
    assert "```text\n/hos decline step=5\n```" in out
    assert "Do not edit this comment, or any later comment of yours" in out
    assert "copy only the text inside the first box below" in out
    assert "Its first line must be the /hos line" in out
    assert "- BF:dep-mapper-low — dep-mapper: dependency blast radius [removed] is LOW" in out
    for bad in FORBIDDEN:
        assert bad not in out


def test_render_request_without_bf_or_pr_has_neither_section():
    out = render_request(5, B, ("C7",), ("a",), issue_url="u")
    assert "Blocking findings" not in out and "or the PR" not in out


def test_render_request_missing_finding_and_truncation():
    out = _req()
    assert "- BF:dep-mapper-low — (no description supplied)" in out
    long = _req(findings=(("dep-mapper-low", "Q" * 500, "Z" * 500),))
    line = [ln for ln in long.splitlines() if ln.startswith("- BF:")][0]
    assert line.count("Q") == 200 and line.count("Z") == 200


def test_render_request_scrubs_every_forbidden_string_in_findings():
    desc = " ".join(FORBIDDEN)
    out = _req(findings=(("dep-mapper-low", desc, desc),))
    for bad in FORBIDDEN:
        assert bad not in out


def test_t_pr_10_parse_error_notice_has_code_only():
    out = _req(parse_error=("https://github.com/o/r/issues/2101#issuecomment-7", "bad-binding"))
    assert (
        "(https://github.com/o/r/issues/2101#issuecomment-7) could not be read (bad-binding)" in out
    )
    assert "the newest one counts" in out
    assert "could not be read" not in _req()


def test_t_pr_11_detail_text_never_carries_body_text():
    bodies = []
    for i in range(20):
        bodies += [
            f"/hos authorize step=5 SECRET-xyz{i}=1",
            f"/hos authorize step=5 binding={B} SECRET-xyz",
            f"/hos authorize step=SECRET-xyz binding={B}",
            "/hos authorize step=5 binding=SECRET-xyz",
            HDR + f"\ncovers: SECRET-xyz{i}",
            HDR + "\ncovers: C7\nSECRET-xyz: v",
            HDR + "\ncovers: C7\nSECRET-xyz",
            "/hos decline step=5\nSECRET-xyz",
            "/hos authorize SECRET-xyz",
            "```text\n" + HDR + "\nSECRET-xyz",
        ]
    for body in bodies:
        got = parse_act(body)
        assert isinstance(got, ParseError), body
        assert "SECRET" not in got.detail_text()
        assert got.code in PARSE_ERRORS


def test_parse_act_is_total_on_odd_input():
    for body in [
        "\x00",
        "/hos authorize\x00",
        "\r\r\n",
        "```" * 5,
        "/hos decline step=5\r",
        "\ufeff",
        "\udc80",
    ]:
        parse_act(body)


def test_t_pr_12_classifier_signal_names_match_c10_syntax():
    text = (ROOT / "scripts" / "oversight" / "change_classifier.py").read_text(encoding="utf-8")
    names = set(
        re.findall(r'^\s*\(\s*\n?(?:\s*#[^\n]*\n)*\s*"([a-z0-9-]+)",\s*\n?\s*r"', text, re.M)
    )
    names |= set(re.findall(r'"signal":\s*"([a-z0-9-]+)"', text))
    assert {"new-external-dependency", "new-user-facing-surface", "new-user-flow-or-route"} <= names
    kebab = re.compile(rf"^{ha.KEBAB}$")
    for name in names:
        assert kebab.match(name), name
        assert ha.ITEM_RE.match(f"C10:{name}"), name


@pytest.mark.parametrize(
    "path", [" a ", "\ta", "./foo", "\u00a0a\u00a0", "'a'", '"a"', "a\n", "", "././a"]
)
def test_unrepresentable_paths_do_not_survive_canonicalization(path):
    assert not ha.is_representable_path(path)


@pytest.mark.parametrize(
    "path", ["a", "a b/c.py", "'a", "a'", ".hidden", "sub/./x", "weird-ünï.py"]
)
def test_representable_paths_are_canonical_fixed_points(path):
    assert ha.is_representable_path(path)
    assert canonicalize_path(path) == path


def test_render_request_scrubs_urls_and_parse_error_fields():
    bad = "https://x/.claudetmp/hos-escalation\nAuthorization required: y"
    out = render_request(
        5,
        B,
        ("C7",),
        ("a",),
        issue_url=bad,
        pr_url=bad,
        parse_error=(bad, "-human-authorization.md hos-proxy-decision"),
    )
    for forbidden in FORBIDDEN:
        assert forbidden not in out
    assert "[removed]" in out
