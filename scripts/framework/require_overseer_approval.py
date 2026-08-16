#!/usr/bin/env python3
"""require_overseer_approval.py — server-side overseer-review gate.

Every PR must have an APPROVED review from the overseer bot before it may merge.
Human approval is additive (for protected surfaces or CRITICAL tier) — it does
not substitute for the overseer review.

Complements require-human-approval (protected-surface gate) and
require-tier-ceiling (ceiling gate). Together the three checks close the gap
where a human approval satisfied GitHub's "1 approving review" branch-protection
requirement without the overseer ever having looked at the PR (#621).

Above-ceiling bypass (#1426): when the PR's computed tier exceeds
OVERSEER_CEILING, the overseer correctly does NOT assert APPROVED authority
(docs/FABERIX-ROLES.md §5: "MEDIUM and HIGH tier → recommend, do NOT
approve") — but that left require-overseer-approval and require-tier-ceiling
jointly unsatisfiable: an overseer APPROVED review is required here, while
require-tier-ceiling FAILS any PR the overseer approved above its ceiling.
This gate now also passes when ALL of the following hold: the overseer
posted *some* review (any state — it looked at the PR and deliberately
withheld APPROVED authority), the PR's computed tier exceeds
OVERSEER_CEILING, and a human (non-bot, per BOT_ACCOUNTS) has an APPROVED
review present. The bypass never fires when the overseer review is absent
entirely — a human approval alone still fails this gate (#621).

Usage (CI):
  python3 require_overseer_approval.py --pr <number> [--repo owner/repo]

Exit codes:
  0 — overseer has approved this PR, or the above-ceiling bypass applies
  1 — FAIL: no overseer approval present (and the bypass does not apply)
  2 — error (missing config or tooling failure — fail-closed)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ENV_FILE = Path(__file__).with_name("machine-accounts.env")


def _load_sibling_module(name: str):
    """Load a sibling script module by file path (no sys.path mutation),
    matching the idiom used by tests/framework/test_require_tier_ceiling.py.
    """
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        print(
            f"require_overseer_approval: machine-accounts.env not found at {path}",
            file=sys.stderr,
        )
        sys.exit(2)
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = re.sub(r'\s+#.*$', '', val.strip())
        val = val.strip('"').strip("'")
        val = re.sub(r"\$\{?(\w+)\}?", lambda m: result.get(m.group(1), ""), val)
        result[key] = val
    return result


def _gh(*args: str) -> str:
    """Run `gh` with the given args, return stdout. Exit 2 on failure."""
    try:
        out = subprocess.run(
            ["gh"] + list(args),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError:
        print("require_overseer_approval: `gh` not found on PATH", file=sys.stderr)
        sys.exit(2)
    except subprocess.CalledProcessError as exc:
        print(
            f"require_overseer_approval: gh command failed: {exc.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    return out


def get_reviews(repo: str, pr: str) -> list[dict]:
    raw = _gh("api", "--paginate", f"repos/{repo}/pulls/{pr}/reviews")
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        # --paginate may concatenate arrays: "]\n[" → ","
        return json.loads(re.sub(r"\]\s*\[", ",", raw))


def overseer_has_approved(reviews: list[dict], overseer_login: str) -> bool:
    """Return True if the overseer has a current APPROVED review.

    GitHub's dismiss_stale_reviews setting transitions old APPROVED reviews to
    DISMISSED when new commits are pushed, so checking for any APPROVED review
    from the overseer reliably reflects the current approval state.
    """
    for review in reviews:
        if str(review.get("state", "")).upper() != "APPROVED":
            continue
        login = (review.get("user") or {}).get("login", "")
        if login.lower() == overseer_login.lower():
            return True
    return False


def overseer_posted_any_review(reviews: list[dict], overseer_login: str) -> bool:
    """Return True if the overseer authored a review in any state.

    Used by the above-ceiling bypass (#1426): distinguishes "the overseer
    looked at this PR and deliberately withheld APPROVED authority above its
    ceiling" from "the overseer never reviewed this PR at all" — only the
    former may bypass, preserving the #621 property that a human approval
    alone (no overseer review whatsoever) still fails this gate.
    """
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        if login.lower() == overseer_login.lower():
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Overseer approval required gate")
    ap.add_argument("--pr", required=True, help="PR number")
    ap.add_argument("--repo", default="", help="owner/repo (defaults to GITHUB_REPOSITORY env)")
    args = ap.parse_args()

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print(
            "require_overseer_approval: --repo or GITHUB_REPOSITORY required",
            file=sys.stderr,
        )
        return 2

    env = load_env(ENV_FILE)
    overseer_login = env.get("BOT_OVERSEER_USERNAME", "").strip()
    if not overseer_login:
        print(
            "require_overseer_approval: BOT_OVERSEER_USERNAME not set in machine-accounts.env",
            file=sys.stderr,
        )
        return 2

    reviews = get_reviews(repo, args.pr)
    if overseer_has_approved(reviews, overseer_login):
        print(
            f"✔ require-overseer-approval: {overseer_login} has approved — gate satisfied."
        )
        return 0

    # Above-ceiling bypass (#1426): the overseer may have deliberately withheld
    # APPROVED authority because the PR's tier exceeds its ceiling — that is
    # correct behavior (docs/FABERIX-ROLES.md §5), not a missing review. If so,
    # and a human has approved instead, the gate is satisfied.
    if overseer_posted_any_review(reviews, overseer_login):
        ceiling = env.get("OVERSEER_CEILING", "").strip().upper()
        rtc = _load_sibling_module("require_tier_ceiling.py")
        if ceiling in rtc.TIER_ORDER:
            tier = rtc.compute_tier_for_pr(repo, args.pr)
            if tier is not None and rtc.tier_exceeds_ceiling(tier, ceiling):
                bot_accounts = {b for b in env.get("BOT_ACCOUNTS", "").split() if b}
                if bot_accounts:
                    rha = _load_sibling_module("require_human_approval.py")
                    humans = rha.human_approval_present(reviews, bot_accounts)
                    if humans:
                        print(
                            f"✔ require-overseer-approval: {overseer_login} reviewed this PR "
                            f"(tier={tier} exceeds ceiling={ceiling}, so it did not assert "
                            f"APPROVED authority above its ceiling — see docs/FABERIX-ROLES.md "
                            f"§5) and a human ({', '.join(humans)}) approved instead — gate "
                            "satisfied."
                        )
                        return 0

    print("", file=sys.stderr)
    print(
        f"✘ require-overseer-approval: FAIL — {overseer_login} has not approved this PR.",
        file=sys.stderr,
    )
    print(
        "  Every PR must have an overseer approval before merge (#621).",
        file=sys.stderr,
    )
    print(
        "  Human approval satisfies the human gate (protected surfaces, CRITICAL tier)",
        file=sys.stderr,
    )
    print(
        "  but does NOT substitute for the overseer review.",
        file=sys.stderr,
    )
    print(
        "  Above-ceiling bypass: if the overseer reviewed this PR (any state) and",
        file=sys.stderr,
    )
    print(
        "  its computed tier exceeds OVERSEER_CEILING, a human APPROVED review",
        file=sys.stderr,
    )
    print(
        "  satisfies this gate instead (#1426, docs/FABERIX-ROLES.md §5).",
        file=sys.stderr,
    )
    print(
        "  Admin bypass: the repo admin (ScottThurlow) may merge via GitHub's",
        file=sys.stderr,
    )
    print(
        "  'Merge without waiting for requirements' admin override.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"require_overseer_approval: unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)
