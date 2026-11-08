"""label-swap.yml /approve|/decline CODEOWNERS parse strips inline '#' comments (#2202)."""

from __future__ import annotations

import subprocess
from pathlib import Path

LABEL_SWAP_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "label-swap.yml"

START_ANCHOR = "CODEOWNERS_USERS=$(awk '"
END_ANCHOR = "}' .github/CODEOWNERS"


def extract_awk_program() -> str:
    text = LABEL_SWAP_YML.read_text(encoding="utf-8")
    assert text.count(START_ANCHOR) == 1, f"anchor {START_ANCHOR!r} must appear exactly once"
    start = text.index(START_ANCHOR) + len(START_ANCHOR)
    end = text.index(END_ANCHOR, start)
    return text[start : end + 1]


def test_inline_comment_does_not_authorise(tmp_path: Path) -> None:
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("/x @alice # @mallory\n# @eve\n/y @org/team @bob\n", encoding="utf-8")
    result = subprocess.run(
        ["awk", extract_awk_program(), str(codeowners)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert sorted(set(result.stdout.split())) == ["alice", "bob"]
