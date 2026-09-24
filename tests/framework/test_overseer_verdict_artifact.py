"""Document-level acceptance tests for #1657 part 2 — the overseer posts real
review objects, and requests the CODEOWNERS human only where the ruling says
(docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md §8.3 D1-D7;
docs/v0.7.0/ADR-1657-overseer-review-objects.md).

These are prose-structure tests in the style of
`tests/framework/test_agent_invocation_migration.py`: read the governance
document, look only at instruction lines, assert structure. They exist because
this defect class has now shipped twice — #1207's `required_review_thread_resolution`
case and #1657's `require-overseer-approval` case — both times as a
producer/consumer mismatch between the artifact type a control reads and the
artifact type the governed actor emits. A prose rule alone did not hold; the
guard belongs in code.

D4 and D5 in particular are pins, not descriptions: D4 fails if the reviewer-request
trigger set gets widened onto the auto-merge path (the calibration failure
`research/sessions/2026-08-04-controls-that-never-fire.md` records), and D5 fails
if `overseer.md` and `docs/FABERIX-ROLES.md` drift back toward contradicting each
other on whether the overseer may approve a protected-surface PR.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OVERSEER = ROOT / ".claude" / "agents" / "overseer.md"
FABERIX = ROOT / "docs" / "FABERIX-ROLES.md"
GATE = ROOT / "scripts" / "framework" / "require_overseer_approval.py"


def _read(path: Path) -> str:
    assert path.exists(), f"{path} is missing — has it moved?"
    return path.read_text(encoding="utf-8")


# ── Step-6 disposition bullets ────────────────────────────────────────────────
#
# Step 6 ("Act on decision") lists exactly four dispositions, each as a
# top-level `   - **<NAME>** →` bullet. DIRTY is not among them: it is handled
# in the merge-authority summary above step 6, and its artifact is a resolvable
# review thread rather than a disposition bullet.
_DISPOSITIONS = (
    "AUTO_MERGE",
    "HUMAN_REQUIRED (CRITICAL tier)",
    "HUMAN_REQUIRED (other reasons)",
    "PROPOSE_ONLY",
)


def _step6_bullets() -> dict:
    """Return {disposition: bullet_text} for step 6's four disposition bullets.

    A bullet runs from its `   - **<NAME>**` marker to the next line starting a
    new list item or a new numbered step.
    """
    text = _read(OVERSEER)
    lines = text.splitlines()

    # Anchor on step 6 itself so a same-named bullet elsewhere in the file
    # (e.g. the v0.4.0 rules summary above it) cannot be picked up instead.
    start = None
    for i, line in enumerate(lines):
        if line.startswith("6. **Act on decision**"):
            start = i
            break
    assert start is not None, "step 6 ('Act on decision') not found in overseer.md"

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^6b\.|^7\. ", lines[i]):
            end = i
            break

    bullets = {}
    current = None
    for line in lines[start:end]:
        marker = re.match(r"^   - \*\*(.+?)\*\*", line)
        if marker:
            current = marker.group(1)
            bullets[current] = line
        elif current is not None and line.startswith("     "):
            bullets[current] += "\n" + line
    return bullets


def test_d1_every_disposition_posts_a_verdict_review():
    """D1 — each of the four step-6 disposition bullets names
    `pr_review.sh submit-verdict`, and none names `post_comment.sh` as its
    verdict artifact."""
    bullets = _step6_bullets()
    for name in _DISPOSITIONS:
        assert name in bullets, (
            f"step-6 disposition bullet '{name}' not found; found: " f"{sorted(bullets)}"
        )
        body = bullets[name]
        assert "pr_review.sh submit-verdict" in body, (
            f"disposition '{name}' does not name `pr_review.sh submit-verdict` — "
            "a conversation comment is not a verdict (#1657)"
        )

    # `post_comment.sh` may still appear on the AUTO_MERGE bullet, but only for
    # the merge-FAILURE notice, never as the verdict artifact. Assert that the
    # only bullet naming it is AUTO_MERGE and that it does so in that context.
    for name, body in bullets.items():
        if "post_comment.sh" not in body:
            continue
        assert name == "AUTO_MERGE", (
            f"disposition '{name}' names post_comment.sh; only AUTO_MERGE's "
            "merge-failure notice may (#1657)"
        )
        assert "If merge fails" in body, (
            "AUTO_MERGE names post_comment.sh outside the merge-failure notice — "
            "the verdict must go through pr_review.sh (#1657)"
        )


def test_d2_no_hardcoded_reviewer_login_in_an_instruction():
    """D2 — `overseer.md` contains no `"reviewers"` JSON literal and no
    `ScottThurlow` inside a JSON payload, a `--reviewer` argument, or a
    `human_reviewer=` assignment. Prose glosses naming the variable first
    (``HUMAN_REVIEWER (`ScottThurlow`)``) are permitted."""
    text = _read(OVERSEER)

    assert '"reviewers"' not in text, (
        'overseer.md still contains a `"reviewers"` JSON literal — reviewer '
        "requests go through `bootstrap/pr_review.sh request-reviewer`, which "
        "resolves the login from CODEOWNERS (#1657)"
    )

    forbidden = (
        re.compile(r'"reviewers"\s*:\s*\[[^\]]*ScottThurlow'),
        re.compile(r"--reviewer\s+ScottThurlow"),
        re.compile(r'human_reviewer\s*=\s*"?ScottThurlow'),
    )
    for pattern in forbidden:
        match = pattern.search(text)
        assert match is None, (
            f"overseer.md hardcodes the maintainer login: {match.group(0)!r} — "
            "resolve it from CODEOWNERS / HUMAN_REVIEWER instead (#1657)"
        )


# The seven NEVER-list bullets that #1657 does NOT change, pinned byte-for-byte.
_NEVER_UNCHANGED = (
    "- Open a new branch, commit code, or create a new PR — that is the worker's role",
    "- Approve a PR you authored or that the worker authored under the same credentials",
    "- Approve anything above `OVERSEER_CEILING` (read from `scripts/framework/machine-accounts.env`)",
    "- Approve a security-relevant change without human sign-off "
    "(read from `scripts/framework/security_surfaces.txt`, #1253)",
    "- Cut or tag a release — releases are always human-approved (NG3b)",
    "- Remove or disable the `hos-halt` file",
    "- Modify governance config (`PROJECT/hos-coordination.yaml`)",
)

_RETIRED_NEVER_BULLET = "Approve anything touching a protected surface"


def _never_list_bullets() -> list:
    lines = _read(OVERSEER).splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## What you may NEVER do"):
            start = i
            break
    assert start is not None, "'What you may NEVER do' heading not found"

    bullets = []
    for line in lines[start + 1 :]:
        if line.startswith("- "):
            bullets.append(line)
        elif bullets and line.strip() == "":
            continue
        elif bullets:
            break
    return bullets


def test_d3_never_list_changed_exactly_one_bullet():
    """D3 — the NEVER list has exactly eight bullets; the seven not being
    changed are byte-identical; the protected-surface bullet forbids MERGING,
    not approving."""
    bullets = _never_list_bullets()
    assert len(bullets) == 8, (
        f"the NEVER list has {len(bullets)} bullets, expected 8 — #1657 changes "
        "exactly one of them and adds none"
    )

    for pinned in _NEVER_UNCHANGED:
        assert pinned in bullets, (
            f"NEVER-list bullet drifted or was removed:\n  {pinned}\n"
            "#1657 changes only the protected-surface bullet"
        )

    protected = [b for b in bullets if b not in _NEVER_UNCHANGED]
    assert len(protected) == 1, f"expected exactly one changed NEVER bullet, found {len(protected)}"
    bullet = protected[0]
    assert bullet.startswith("- Merge anything touching a protected surface"), (
        "the protected-surface NEVER bullet must forbid MERGING on the "
        f"overseer's own authority, not reviewing; got:\n  {bullet}"
    )
    assert _RETIRED_NEVER_BULLET not in bullet, (
        "the retired wording is back — forbidding an APPROVE verdict on a "
        "protected surface is what made `require-overseer-approval` "
        "unsatisfiable and forced admin override on every such PR (#1657)"
    )


def test_d4_auto_merge_path_requests_no_human_reviewer():
    """D4 — the 'must not widen' pin, doc level. The AUTO_MERGE bullet contains
    no `request-reviewer` invocation and carries the explicit prohibition."""
    bullet = _step6_bullets()["AUTO_MERGE"]
    # An *invocation*, not a mention: the bullet legitimately names the
    # subcommand while explaining that it would refuse this path.
    assert "pr_review.sh request-reviewer" not in bullet, (
        "the AUTO_MERGE path invokes `request-reviewer` — the #1657 trigger set "
        "is deliberately narrow, and widening it pushes the human gate toward "
        "the rubber-stamping failure recorded in "
        "research/sessions/2026-08-04-controls-that-never-fire.md"
    )
    assert "Do NOT request a human reviewer on this path" in bullet, (
        "the AUTO_MERGE bullet lost its explicit 'Do NOT request a human "
        "reviewer on this path' prohibition (#1657)"
    )


def test_d5_the_two_documents_do_not_contradict_each_other():
    """D5 — the contradiction test. FABERIX-ROLES.md §5's determination-honesty
    paragraph says the approval is GIVEN; overseer.md's protected-surface NEVER
    bullet forbids MERGING. Fails if either drifts toward the other's
    opposite."""
    faberix = _read(FABERIX)
    assert "necessary-not-sufficient" in faberix, (
        "FABERIX-ROLES.md §5 lost its determination-honesty boundary — it is the "
        "authority overseer.md's protected-surface bullet cites (#1657)"
    )
    assert (
        "Faberix records its `APPROVED` verdict when the change is sound on the merits" in faberix
    ), (
        "FABERIX-ROLES.md §5 no longer states that the approval is GIVEN on a "
        "protected path — necessary-not-sufficient read as 'withheld' is the "
        "contradiction #1657 resolved"
    )

    protected = [b for b in _never_list_bullets() if b not in _NEVER_UNCHANGED][0]
    assert protected.startswith("- Merge anything touching a protected surface"), (
        "overseer.md's protected-surface NEVER bullet drifted back toward "
        "forbidding approval, contradicting FABERIX-ROLES.md §5 (#1657)"
    )


def test_d6_reviewer_request_has_a_wrapper():
    """D6 — `overseer.md` no longer says the reviewer request has no wrapper,
    and its tooling table lists `pr_review.sh`."""
    text = _read(OVERSEER)
    assert "Request reviewer:** no wrapper yet" not in text, (
        "overseer.md still says reviewer requests have no wrapper — "
        "`bootstrap/pr_review.sh request-reviewer` shipped in #1657"
    )
    assert re.search(r"^\| `pr_review\.sh` \|", text, re.MULTILINE), (
        "the GitHub-workflow tooling table has no `pr_review.sh` row — an "
        "agent that cannot find the wrapper falls back to a raw API call (#1657)"
    )


def test_d7_gate_does_not_quote_the_retired_faberix_wording():
    """D7 — `require_overseer_approval.py` must quote the live §5 wording, not
    the sentence that no longer exists in the document it cites."""
    # Whitespace-blind: the retired quote is docstring-wrapped across two source
    # lines, so a literal single-line substring test never matched it and would
    # have passed against a full revert of this change.
    text = _read(GATE)
    collapsed = " ".join(text.split())
    assert "MEDIUM and HIGH tier → recommend, do NOT approve" not in collapsed, (
        "require_overseer_approval.py still quotes the retired FABERIX-ROLES.md "
        "§5 sentence — a gate citing text that no longer exists is the same "
        "stale-citation class #1657 is about"
    )
    assert "docs/FABERIX-ROLES.md" in collapsed, (
        "require_overseer_approval.py no longer cites FABERIX-ROLES.md at all; "
        "it should quote the live §5 wording, not drop the citation"
    )
    # Absence of the retired quote is not enough on its own — a gate that
    # dropped the quotation entirely would satisfy it. Pin the live §5 wording.
    assert "Above OVERSEER_CEILING → record a review, but never APPROVED" in collapsed, (
        "require_overseer_approval.py does not quote the LIVE FABERIX-ROLES.md §5 "
        "wording — the E2 replacement is what the #1426 bypass's own rationale "
        "rests on (#1657)"
    )
