#!/usr/bin/env python3
"""require_overseer_approval.py — server-side overseer-review gate.

Every PR must have an APPROVED review from the overseer bot before it may merge.
Human approval is additive (for protected surfaces or CRITICAL tier) — it does
not substitute for the overseer review.

Complements require-human-approval (protected-surface gate) and
require-tier-ceiling (ceiling gate). Together the three checks close the gap
where a human approval satisfied GitHub's "1 approving review" branch-protection
requirement without the overseer ever having looked at the PR (#621).

Interim sign-off (#2174, replaces the #1426 above-ceiling bypass): when the
overseer reaches HUMAN_REQUIRED or PROPOSE_ONLY it correctly does NOT assert
APPROVED authority (docs/FABERIX-ROLES.md §5: "Above OVERSEER_CEILING → record a review, but
never APPROVED"), which used to leave this gate unsatisfiable. The wrapper
(pr_review_cli.py submit-verdict) now appends a marker line to the overseer's
COMMENTED verdict. This gate passes when BOTH hold, each bound to the same
current head SHA: the overseer's latest non-empty verdict on that head is a
COMMENTED review carrying a valid marker, authored by the overseer Bot, AND a
designated human (HUMAN_REVIEWER plus individual code owners) has an
APPROVED review on that head. A human approval alone, with no overseer verdict
on the head, still fails (#621). The marker is read only from the overseer's
own reviews; the gate runs from the trusted base (pull_request_target).

Usage (CI):
  python3 require_overseer_approval.py --pr <number> [--repo owner/repo]

Exit codes:
  0 — overseer has approved this PR, or the interim sign-off path applies
  1 — FAIL: no overseer approval or valid interim sign-off plus human approval
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
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build a module spec for {path} — has it moved?")
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
        val = re.sub(r"\s+#.*$", "", val.strip())
        val = val.strip('"').strip("'")
        val = re.sub(r"\$\{?(\w+)\}?", lambda m: result.get(m.group(1), ""), val)
        result[key] = val
    return result


# Mirrors _GH_SUBPROCESS_TIMEOUT_SECONDS in scripts/automation/lib/github.py (not
# imported: this gate runs as a plain script without the repo root on sys.path).
# The workflow sets no timeout-minutes, so a stalled `gh` would hold the required
# check for up to 360 minutes.
GH_SUBPROCESS_TIMEOUT_SECONDS = 30


def _gh(*args: str) -> str:
    """Run `gh` with the given args, return stdout. Exit 2 on failure."""
    try:
        out = subprocess.run(
            ["gh"] + list(args),
            capture_output=True,
            text=True,
            check=True,
            timeout=GH_SUBPROCESS_TIMEOUT_SECONDS,
        ).stdout
    except subprocess.TimeoutExpired:
        print(
            f"require_overseer_approval: gh command timed out after "
            f"{GH_SUBPROCESS_TIMEOUT_SECONDS}s. No action is needed; re-run the check "
            "once GitHub responds.",
            file=sys.stderr,
        )
        sys.exit(2)
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


MARKER_PREFIX = "<!-- hos:overseer-interim-signoff"
INTERIM_DISPOSITIONS = ("HUMAN_REQUIRED", "PROPOSE_ONLY")
INTERIM_ACTIONS = ("APPROVE", "REQUEST_CHANGES", "DECIDE", "DO_NOT_MERGE", "OTHER")
INTERIM_MARKER_RE = re.compile(
    r"^<!-- hos:overseer-interim-signoff v=1 "
    r"disposition=(HUMAN_REQUIRED|PROPOSE_ONLY) "
    r"action=(APPROVE|REQUEST_CHANGES|DECIDE|DO_NOT_MERGE|OTHER) "
    r"head=([0-9a-f]{40}) -->$",
    re.MULTILINE,
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPO_ROOT = Path(__file__).resolve().parents[2]
_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
_VERDICT_STATES = ("COMMENTED", "APPROVED", "CHANGES_REQUESTED", "DISMISSED")
_DECISION_STATES = ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")


def render_interim_marker(disposition: str, action: str, head: str) -> str:
    """The one writer of the marker line (pr_review_cli.py loads this)."""
    if disposition not in INTERIM_DISPOSITIONS:
        raise ValueError(f"invalid interim disposition: {disposition!r}")
    if action not in INTERIM_ACTIONS:
        raise ValueError(f"invalid interim action: {action!r}")
    if not SHA_RE.match(head):
        raise ValueError(f"invalid head sha: {head!r}")
    return f"{MARKER_PREFIX} v=1 disposition={disposition} " f"action={action} head={head} -->"


def parse_interim_marker(body: str) -> tuple[str, str, str] | None:
    """(disposition, action, head) for exactly one valid marker line, else None.
    More than one marker fails closed."""
    matches = INTERIM_MARKER_RE.findall(body or "")
    if len(matches) != 1:
        return None
    return matches[0]


def latest_overseer_verdict_on_head(
    reviews: list[dict], overseer_login: str, head_sha: str
) -> dict | None:
    """The overseer Bot's latest non-empty verdict review on head_sha.

    Excludes PENDING, other commits, empty-bodied reviews (review-thread
    containers, ADR-1657 AD-5) and reviews with no submitted_at. DISMISSED is
    a candidate so a dismissed later verdict cannot resurrect an older
    sign-off. A missing user.type does not count (fail closed).
    """
    candidates = []
    for r in reviews:
        user = r.get("user") or {}
        if str(user.get("login", "")).lower() != overseer_login.lower():
            continue
        if user.get("type") != "Bot":
            continue
        if r.get("commit_id") != head_sha:
            continue
        if str(r.get("state", "")).upper() not in _VERDICT_STATES:
            continue
        if not str(r.get("body") or "").strip():
            continue
        if not r.get("submitted_at"):
            continue
        candidates.append(r)
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["submitted_at"], r.get("id") or 0))


def valid_interim_signoff(verdict: dict, head_sha: str) -> tuple[str, str, str] | None:
    """The parsed marker if `verdict` is a valid interim sign-off on head_sha."""
    if str(verdict.get("state", "")).upper() != "COMMENTED":
        return None
    parsed = parse_interim_marker(str(verdict.get("body") or ""))
    if parsed is None or parsed[2] != head_sha:
        return None
    return parsed


def codeowners_individual_owners(repo_root: Path) -> set[str]:
    """Individual code owners (the code-owners file) via requester_trust.codeowners_humans, the
    one shared parser of that file (test_requester_trust pins that no second
    parser exists). The module imports `scripts.framework.*`, so the trusted
    base checkout's root goes on sys.path first."""
    root = str(repo_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.framework.requester_trust import codeowners_humans

    return codeowners_humans(root)


def designated_humans(env: dict[str, str], codeowners_owners: set[str]) -> frozenset[str]:
    """HUMAN_REVIEWER plus every individual code owner (lowercase).

    `codeowners_owners` comes from the shared parser, which already drops
    @org/team owners; entries that are not a plausible GitHub login (email
    owners, a stray "#") are dropped here. No path matching: the question is
    "is this one of the project's oversight humans".
    """
    names = {o.lower() for o in codeowners_owners if _LOGIN_RE.match(o)}
    reviewer = env.get("HUMAN_REVIEWER", "").strip()
    if reviewer:
        names.add(reviewer.lower())
    return frozenset(names)


def eligible_human_approvals_on_head(
    reviews: list[dict],
    bot_accounts: set[str],
    designated: frozenset[str],
    head_sha: str,
) -> list[str]:
    """Designated, non-bot logins whose latest effective review on head_sha is APPROVED.

    Per login, only reviews bound to head_sha in state APPROVED,
    CHANGES_REQUESTED or DISMISSED count; COMMENTED and PENDING do not change
    a reviewer's decision. They are ordered by (submitted_at, id); a missing
    submitted_at sorts as "" (earliest), so an undated review can never
    override a dated one. The login is eligible only if its LATEST such review
    is APPROVED: a later CHANGES_REQUESTED withdraws the approval, and a later
    DISMISSED does not resurrect an earlier one (fail closed).
    """
    rha = _load_sibling_module("require_human_approval.py")
    latest: dict[str, tuple[tuple[str, int], str, str]] = {}
    for r in reviews:
        state = str(r.get("state", "")).upper()
        if state not in _DECISION_STATES:
            continue
        if r.get("commit_id") != head_sha:
            continue
        user = r.get("user") or {}
        login = str(user.get("login", ""))
        if not login or rha.is_bot_reviewer(login, user.get("type", ""), bot_accounts):
            continue
        if login.lower() not in designated:
            continue
        key = (str(r.get("submitted_at") or ""), int(r.get("id") or 0))
        seen = latest.get(login.lower())
        if seen is None or key > seen[0]:
            latest[login.lower()] = (key, state, login)
    return sorted(login for _, state, login in latest.values() if state == "APPROVED")


def _short(sha: str) -> str:
    return sha[:12]


def _fail(*lines: str) -> int:
    print("", file=sys.stderr)
    for line in lines:
        print(line, file=sys.stderr)
    return 1


def resolve_head(repo: str, pr: str) -> str | int:
    """The commit this check evaluates, or an exit code (1 stale, 2 error)."""
    live = _gh("api", f"repos/{repo}/pulls/{pr}", "--jq", ".head.sha").strip()
    if not SHA_RE.match(live):
        print(
            f"require_overseer_approval: could not resolve a valid PR head SHA (got {live!r})",
            file=sys.stderr,
        )
        return 2
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        return live
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        event_head = event["pull_request"]["head"]["sha"]
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "require_overseer_approval: GITHUB_EVENT_PATH is unreadable or has no "
            "pull_request.head.sha",
            file=sys.stderr,
        )
        return 2
    if not isinstance(event_head, str) or not SHA_RE.match(event_head):
        print(
            "require_overseer_approval: event head SHA is malformed",
            file=sys.stderr,
        )
        return 2
    if event_head != live:
        return _fail(
            f"This check belongs to commit {_short(event_head)}, but the PR head is now "
            f"{_short(live)}. The check on the new head decides; no action is needed."
        )
    return live


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
        print(f"✔ require-overseer-approval: {overseer_login} has approved — gate satisfied.")
        return 0

    head = resolve_head(repo, args.pr)
    if isinstance(head, int):
        return head

    verdict = latest_overseer_verdict_on_head(reviews, overseer_login, head)
    if verdict is None:
        return _fail(
            f"✘ require-overseer-approval: The overseer has not reviewed commit {_short(head)} yet. "
            "No action is needed; the overseer reviews it on its next cycle. "
            "A human approval on its own cannot satisfy this check (#621)."
        )
    signoff = valid_interim_signoff(verdict, head)
    if signoff is None:
        return _fail(
            f"✘ require-overseer-approval: The overseer's latest review of commit {_short(head)} "
            "is not a sign-off. Open that review on the PR's Conversation tab for the "
            "action it asks of you."
        )

    env_bots = {b for b in env.get("BOT_ACCOUNTS", "").split() if b}
    try:
        owners = codeowners_individual_owners(REPO_ROOT)
    except (OSError, UnicodeDecodeError, ImportError) as exc:
        print(
            "require_overseer_approval: could not read the code owners needed to "
            f"decide who may approve ({type(exc).__name__}: {exc}). No action is "
            "needed on the PR; this is a repository configuration problem and "
            "the check fails closed until it is fixed.",
            file=sys.stderr,
        )
        return 2
    designated = designated_humans(env, owners)
    if not env_bots:
        print(
            "require_overseer_approval: BOT_ACCOUNTS not set in machine-accounts.env (misconfigured)",
            file=sys.stderr,
        )
        return 2
    if not designated:
        print(
            "require_overseer_approval: no designated human (HUMAN_REVIEWER / code owner "
            "individual owner) configured (misconfigured)",
            file=sys.stderr,
        )
        return 2

    humans = eligible_human_approvals_on_head(reviews, env_bots, designated, head)
    if humans:
        print(
            f"✔ require-overseer-approval: {overseer_login} signed off commit {_short(head)} "
            f"(interim, disposition={signoff[0]}) and {', '.join(humans)} approved it — "
            "gate satisfied."
        )
        return 0
    return _fail(
        f"✘ require-overseer-approval: The overseer has signed off its side of commit "
        f"{_short(head)}, and this merge now waits only on a human. Approve the PR on GitHub "
        "(Files changed → Review changes → Approve). This check re-runs automatically when "
        "you approve.",
        f"  Approvals that count for this check: {', '.join(sorted(designated))}. "
        "Approvals from anyone else do not count here.",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"require_overseer_approval: unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)
