"""requester_trust.py — the requester-trust primitive (S1 of #1540, fix path for #1539).

Protected surface. Answers exactly one question: "is the author of this GitHub
record trusted enough that its content needs no live human-authorization act?"
It never decides whether a record is *authorized* to be worked — that is
`select_work_candidates.py`'s job (S2) — and it never confers approver
authority: trust here is a statement about who may FILE work without a human
act, never about who may APPROVE it.

Binding constraints (AD-1, §1.1 of TECHNICAL-DESIGN-1540):
  - MUST NOT import from scripts/automation/** or scripts/oversight/** — those
    are not protected surfaces, and importing either would let a bot widen
    the gate's dependencies without a human-approval gate on the change.
    Permitted imports: the standard library, and
    scripts.framework.require_human_approval.is_bot_reviewer.
  - No predicate performs network I/O or reads the environment (except the
    union-only BOT_ACCOUNTS read in load_bot_accounts). The one fetch wrapper
    (fetch_collaborators) is the module's only network call, and it returns
    data for the caller to pass into load_trusted_set — it decides nothing.
  - Every loader is fail-closed by construction: an absent source yields the
    EMPTIES category, which can only ever REDUCE who is trusted. An
    unreadable-but-present source propagates the exception (§1.3.1) — a
    caller (the S2 gate) is the one that turns that into exit 2.

Every bounded list fetch in this module issues ONE `gh api` invocation PER
PAGE, with `page=` and `per_page=100` literally in the endpoint's query
string — never `--paginate` (which on gh 2.45.0 fetches every page with no
cap and hides the `Link` header a bound needs) and never `-f`/`-F` (which
silently switches the request method to POST). A page shorter than 100 raw
items ends the history (§1.4's per-page fetch rule, revision 8 / RP5-1).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from scripts.framework.require_human_approval import is_bot_reviewer

# ---------------------------------------------------------------------------
# Paths (relative to repo_root)
# ---------------------------------------------------------------------------

_CODEOWNERS_RELATIVE = ".github/CODEOWNERS"
_MACHINE_ACCOUNTS_RELATIVE = "scripts/framework/machine-accounts.env"
_TRUSTED_REQUESTERS_RELATIVE = "scripts/framework/trusted-requesters.txt"

# Bounded wall-clock budget for a single `gh api` subprocess call, matching
# scripts/automation/lib/github.py's own rationale: without a bound, `gh`
# stalling on DNS/TLS/a proxy blocks the caller forever, and on Worker's
# unattended cron there is nothing to interrupt a hang.
_GH_SUBPROCESS_TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Data types (§1.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterPolicy:
    """The two halves `load_trusted_requesters` records from the roster file."""

    logins: frozenset[str]  # explicit named users, lowercased
    tiers: frozenset[str]  # tier TOKENS, verbatim (lowercased) from PERMISSION_TIERS


@dataclass(frozen=True)
class TrustedSet:
    codeowners: frozenset[str]  # AD-1(a) — lowercased logins, '@' stripped
    roster: frozenset[str]  # AD-1(c) — EXPLICIT logins from the roster file
    tier_members: frozenset[str]  # AD-1(c) via H3 — logins RESOLVED from the
    # roster's tier tokens against the live collaborator-permission API.
    # EMPTY when no tier token is listed, and EMPTY when resolution failed.
    # NEVER a snapshot read from a file.
    tier_of: Mapping[str, str]  # login -> the ONE tier token that admitted it.
    # Read ONLY to build the `roster-tier:<tier>` reason token; never
    # consulted for membership.
    tiers: frozenset[str]  # the tier TOKENS the roster listed, verbatim —
    # carried for reporting only, NEVER consulted for membership
    apps: frozenset[str]  # AD-1(b) — lowercased logins, COPILOT excluded
    bots: frozenset[str]  # BOT_ACCOUNTS, lowercased — EXCLUSION input only

    def __post_init__(self) -> None:
        if frozenset(self.tier_of) != self.tier_members:
            raise ValueError(
                "TrustedSet.tier_of keys must equal tier_members exactly "
                f"(tier_of={sorted(self.tier_of)!r}, "
                f"tier_members={sorted(self.tier_members)!r})"
            )


@dataclass(frozen=True)
class MachineFilingMarker:
    marker_id: str  # stable audit id, e.g. "hos-cron/baseline-red"
    title_prefix: str  # anchored match against issue.title
    title_contains: Optional[str]  # optional second required substring
    emitting_site: str  # "path::symbol" — drives the conformance test
    status: str  # "active" | "dormant"


@dataclass(frozen=True)
class RequesterVerdict:
    trusted: bool
    reason: str  # stable machine-readable token, never prose
    category: Optional[str]  # "codeowner" | "roster" | "trusted-app" | None
    marker_id: Optional[str]


# ---------------------------------------------------------------------------
# Module constants (§5)
# ---------------------------------------------------------------------------

# GitHub's OWN permission-level names, used directly — no mapping table, and
# there must never be one (the human's ruling, 2026-09-16T19:56:58Z addendum).
PERMISSION_TIERS = ("read", "triage", "write", "maintain", "admin")

COLLABORATOR_PAGE_BOUND = 3  # 300 collaborators. NOT a flag (§1.3.2).

# The real enumeration of deterministic-code issue-filing sites (§1.5.1/1.5.2).
# Closed against sub-issue filing (AM-10/D-7): entries are REMOVED, never
# relaxed, the moment an emitting site becomes LLM-composed (D-6 trigger 2).
MACHINE_FILING_MARKERS: tuple[MachineFilingMarker, ...] = (
    MachineFilingMarker(
        "hos-cron/agent-unavailable",
        "[BLOCKED] agent unavailable",
        None,
        "bin/hos-cron",
        "active",
    ),
    MachineFilingMarker(
        "hos-cron/main-diverged",
        "[BLOCKED] local main diverged on ",
        None,
        "bin/hos-cron::_dm_title_prefix",
        "active",
    ),
    MachineFilingMarker(
        "hos-cron/baseline-red",
        "[BLOCKED] inner-loop tests failing on ",
        None,
        "bin/hos-cron::_bs_title_prefix",
        "active",
    ),
    MachineFilingMarker(
        "hos-cron/timeout-breaker",
        "[SUSPENDED] ",
        " timeout breaker tripped on ",
        "bin/hos-cron::_TIMEOUT_BREAKER_TITLE_PREFIX",
        "active",
    ),
    MachineFilingMarker(
        "hos-cron/usage-limit-breaker",
        "[SUSPENDED] ",
        " usage-limit breaker tripped on ",
        "bin/hos-cron::_USAGE_LIMIT_BREAKER_TITLE_PREFIX",
        "dormant",
    ),
    MachineFilingMarker(
        "self-review/finding",
        "[AI: self-review] ",
        None,
        "scripts/automation/lib/self_review_source.py::file_finding_as_issue",
        "active",
    ),
    MachineFilingMarker(
        "review-self/design-concern",
        "[AI: ",
        " design-concern: ",
        "scripts/review_self.sh",
        "active",
    ),
)

# Reason tokens (closed set, §1.2). Downstream (S6 audit) parses these; they
# are an interface, not a log message.
_REASON_TOKENS = frozenset(
    {
        "codeowner",
        "roster",
        "trusted-app",
        "not-in-trusted-set",
        "no-login",
        "bot-in-human-category",
        "trusted-app-no-machine-filing-marker",
    }
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _codeowners_path(repo_root: str) -> Path:
    return Path(repo_root) / _CODEOWNERS_RELATIVE


def _machine_accounts_path(repo_root: str) -> Path:
    return Path(repo_root) / _MACHINE_ACCOUNTS_RELATIVE


def _trusted_requesters_path(repo_root: str) -> Path:
    return Path(repo_root) / _TRUSTED_REQUESTERS_RELATIVE


def machine_accounts_file_absent(repo_root: str = ".") -> bool:
    """True iff `scripts/framework/machine-accounts.env` does not exist.

    S1 support for RP6-3 / condition C3 (PANEL-1540 run 6). The S2 gate's
    Step B1/B3 must emit `machine-accounts-file-absent` when the file is
    absent and a DIFFERENT token (`bot-accounts-empty` / `trusted-apps-empty`)
    when it is present but yields nothing after the env union — but
    `load_bot_accounts` and `load_trusted_apps` both stay pinned at
    `-> set[str]` (§5's interface summary), so neither can carry that
    distinction in its return value without breaking the contract a coder
    implements against. This function is the S1-side primitive that lets a
    caller make the distinction without re-deriving this module's own path.
    S2 (`select_work_candidates.py`) is the one that calls it; that call
    site is out of this slice's scope.
    """
    return not _machine_accounts_path(repo_root).is_file()


def _diagnostic(message: str) -> None:
    print(f"requester_trust: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# .env line parser — NEVER `source`d (§1.3): shell-executing a config file on
# an authorization path turns a config edit into code execution.
# ---------------------------------------------------------------------------


def _parse_env_file(path: Path) -> dict[str, str]:
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
        result[key] = val
    return result


# ---------------------------------------------------------------------------
# 1.3 Loaders
# ---------------------------------------------------------------------------


def codeowners_humans(repo_root: str = ".") -> set[str]:
    """Individual human logins (lowercased, '@' stripped) named anywhere in
    .github/CODEOWNERS. Team patterns (org/team) are not individual humans
    and are skipped (AF-2). Empty if the file is missing. Promoted verbatim
    from probe.py:_codeowners_humans (byte-identical behaviour, AD-1)."""
    path = _codeowners_path(repo_root)
    if not path.is_file():
        return set()
    humans: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        for owner in parts[1:]:
            owner = owner.lstrip("@")
            if "/" in owner:
                continue  # team pattern, not an individual human
            humans.add(owner.lower())
    return humans


def load_trusted_apps(repo_root: str = ".") -> set[str]:
    """The three HOS App identities from machine-accounts.env — never
    COPILOT_BOT_LOGIN (FR2(b): a third-party reviewer is not an HOS role) and
    never the composite BOT_ACCOUNTS. Missing file -> empty set."""
    path = _machine_accounts_path(repo_root)
    if not path.is_file():
        return set()
    env = _parse_env_file(path)
    apps: set[str] = set()
    for key in ("BOT_WORKER_USERNAME", "BOT_OVERSEER_USERNAME", "BOT_HUMAN_USERNAME"):
        val = env.get(key, "").strip()
        if val:
            apps.add(val.lower())
    return apps


def load_bot_accounts(repo_root: str = ".") -> set[str]:
    """The exclusion input for is_bot_reviewer. Baseline = the four logins in
    machine-accounts.env; if BOT_ACCOUNTS is non-empty, the result is the
    UNION of baseline and env — never the env alone (AD-13): a larger
    denylist is strictly stricter, and letting the environment REPLACE would
    let a compromised cron environment shrink the denylist and promote a bot
    to "human"."""
    path = _machine_accounts_path(repo_root)
    baseline: set[str] = set()
    if path.is_file():
        env = _parse_env_file(path)
        for key in (
            "BOT_WORKER_USERNAME",
            "BOT_OVERSEER_USERNAME",
            "BOT_HUMAN_USERNAME",
            "COPILOT_BOT_LOGIN",
        ):
            val = env.get(key, "").strip()
            if val:
                baseline.add(val.lower())
    env_accounts = {b.lower() for b in os.environ.get("BOT_ACCOUNTS", "").split() if b}
    return baseline | env_accounts


_PROVENANCE_REQUIRED = ("added-by:", "added:", "why:")


def _has_provenance(comment: str) -> bool:
    return all(token in comment for token in _PROVENANCE_REQUIRED)


def load_trusted_requesters(repo_root: str = ".") -> RosterPolicy:
    """Read trusted-requesters.txt and return BOTH halves of the policy it
    records: explicit logins (AD-1(c)) and tier tokens (H3). Two entry
    forms, both requiring FR3 per-entry provenance:

        <login>          # added-by: <login> added: <YYYY-MM-DD> why: <text>
        tier:<name>      # added-by: <login> added: <YYYY-MM-DD> why: <text>

    Missing file -> RosterPolicy(frozenset(), frozenset()) (FR3: the
    mechanism must still function with CODEOWNERS + apps as the trusted
    set). A read error that is not FileNotFoundError propagates."""
    path = _trusted_requesters_path(repo_root)
    if not path.is_file():
        return RosterPolicy(frozenset(), frozenset())

    bots = load_bot_accounts(repo_root)
    logins: set[str] = set()
    tiers: set[str] = set()

    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        value, has_hash, comment = line.partition("#")
        value = value.strip()
        if not value or not has_hash or not _has_provenance(comment):
            _diagnostic(
                f"trusted-requesters.txt:{lineno}: malformed entry "
                "(missing added-by/added/why provenance), skipped"
            )
            continue

        if value.startswith("tier:"):
            tier_name = value[len("tier:") :].strip().lower()
            if tier_name not in PERMISSION_TIERS:
                _diagnostic(
                    f"trusted-requesters.txt:{lineno}: unrecognised tier "
                    f"'{tier_name}' — legal values are {', '.join(PERMISSION_TIERS)}"
                )
                continue
            tiers.add(tier_name)
            continue

        login = value.lower()
        if is_bot_reviewer(login, "", bots):
            _diagnostic(
                f"trusted-requesters.txt:{lineno}: bot login '{login}' "
                "rejected — the roster is for people"
            )
            continue
        logins.add(login)

    return RosterPolicy(frozenset(logins), frozenset(tiers))


def load_trusted_set(repo_root: str = ".", collaborators: Any = None) -> TrustedSet:
    """Compose the five trust categories. The ONLY constructor production
    code uses. Performs NO network I/O: `collaborators` is an
    ALREADY-FETCHED payload (or None), exactly as verify_codeowner_actor
    takes an already-fetched events list. `collaborators=None` means "no
    tier resolution was performed", yielding tier_members = frozenset() —
    the same fail-closed value as a failed resolution, which is why
    probe.py needs no change to keep working."""
    codeowners = codeowners_humans(repo_root)
    bots = load_bot_accounts(repo_root)
    apps = load_trusted_apps(repo_root)
    policy = load_trusted_requesters(repo_root)
    tier_members, tier_of = _resolve_tier_membership(policy.tiers, collaborators, bots)
    return TrustedSet(
        codeowners=frozenset(codeowners),
        roster=frozenset(policy.logins),
        tier_members=tier_members,
        tier_of=MappingProxyType(dict(tier_of)),
        tiers=frozenset(policy.tiers),
        apps=frozenset(apps),
        bots=frozenset(bots),
    )


def _resolve_tier_membership(
    tiers: frozenset[str],
    collaborators: Any,
    bots: set[str],
) -> tuple[frozenset[str], dict[str, str]]:
    """Match collaborator records' `role_name` (NOT the `permissions`
    object — a different vocabulary entirely, §1.3.2) against the roster's
    tier tokens, EXACTLY, never hierarchically. `collaborators=None` or any
    non-list payload yields empty (no tier listed, or a failed resolution
    already collapsed by the caller to None — §1.3.2/F35)."""
    if not tiers or not isinstance(collaborators, list):
        return frozenset(), {}
    tier_of: dict[str, str] = {}
    for record in collaborators:
        if not isinstance(record, dict):
            continue
        login = record.get("login", "")
        if not login:
            continue
        role_name = str(record.get("role_name", "")).lower()
        if role_name not in tiers:
            continue
        if is_bot_reviewer(login, record.get("type", ""), bots):
            continue  # F37 — a GitHub App can appear in the collaborator list
        tier_of.setdefault(login.lower(), role_name)
    return frozenset(tier_of), tier_of


# ---------------------------------------------------------------------------
# 1.3.2 The permission-tier resolver's fetch wrapper (H3)
# ---------------------------------------------------------------------------


class _FetchFailure(Exception):
    """Internal signal: one page's `gh` invocation could not be parsed."""


def _run_gh_get(endpoint: str) -> Any:
    """Issue exactly ONE `gh api <endpoint>` GET and return parsed JSON.

    No retries, no --paginate, no -f/-F (§1.4's per-page fetch rule): one gh
    invocation, one result. This module implements its own minimal wrapper
    rather than reusing the automation package's equivalent helper, because
    this file MUST NOT import from scripts/automation/** (§1.1)."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GH_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise _FetchFailure(str(exc)) from exc
    if result.returncode != 0:
        raise _FetchFailure(result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _FetchFailure(str(exc)) from exc


def fetch_collaborators(
    repo: str,
    stop_test: Callable[[], bool],
    record_request: Callable[[], None],
) -> tuple[Any, int]:
    """THE ONLY NETWORK CALL IN THIS MODULE. A fetch wrapper, not a
    predicate — it decides nothing, it only fetches and reports cost.

    One `gh api "repos/<repo>/collaborators?per_page=100&page=<k>"`
    invocation PER PAGE, never --paginate, bounded by
    COLLABORATOR_PAGE_BOUND. `stop_test()` is the caller's per-cycle
    request-ceiling stop test (§1.4 rule 3(b)): consulted before every page,
    it MUST return True when the ceiling refuses the next request.
    `record_request()` is called once per `gh` invocation issued,
    immediately after it returns (successfully or not) and BEFORE
    `stop_test()` is next consulted — mirroring §2.2.1's counter semantics
    ("increments after each request returns") so a caller sharing one
    counter across Step C, the events fetch and this fetch sees this
    fetch's own spend within the same call (RP6-2 / condition C2).

    A ceiling refusal is QUIET: this function never prints anything (it is
    a fetch wrapper; the WARN is the S2 gate's to emit, or not — a ceiling
    refusal here resolves to tier_members = frozenset() with NO WARN,
    unlike a genuine transport failure's `WARN tier-resolution-failed`;
    that classification is the caller's, since only the caller knows which
    case it is from `payload is None`).

    Returns (payload, requests_spent). payload is the concatenated list of
    collaborator records from every page fetched, or None on ANY failure
    (a ceiling refusal at any page, a non-zero exit, non-JSON output, or a
    non-list result) — a partial fetch is discarded wholesale on failure,
    same as any other resolution failure (F35). requests_spent counts every
    `gh` invocation issued, including ones that failed.
    """
    requests_spent = 0
    collected: list = []
    for page in range(1, COLLABORATOR_PAGE_BOUND + 1):
        if stop_test():
            return None, requests_spent
        endpoint = f"repos/{repo}/collaborators?per_page=100&page={page}"
        try:
            batch = _run_gh_get(endpoint)
        except _FetchFailure:
            record_request()
            requests_spent += 1
            return None, requests_spent
        record_request()
        requests_spent += 1
        if not isinstance(batch, list):
            return None, requests_spent
        collected.extend(batch)
        if len(batch) < 100:
            return collected, requests_spent  # COMPLETE
    return collected, requests_spent  # BOUND-REACHED: page 3 was full


# ---------------------------------------------------------------------------
# 1.4 Predicates
# ---------------------------------------------------------------------------


def is_trusted_requester(login: str, user_type: str, trusted_set: TrustedSet) -> tuple[bool, str]:
    """The ADR-bound signature (AD-1). Pure: no network, no filesystem, no
    environment. Evaluation order is fixed and total (§1.4)."""
    if not login:
        return False, "no-login"
    low = login.lower()
    if (
        low in trusted_set.codeowners
        or low in trusted_set.roster
        or low in trusted_set.tier_members
    ):
        if is_bot_reviewer(login, user_type, set(trusted_set.bots)):
            return False, "bot-in-human-category"
        if low in trusted_set.codeowners:
            return True, "codeowner"
        if low in trusted_set.roster:
            return True, "roster"
        return True, f"roster-tier:{trusted_set.tier_of[low]}"
    if low in trusted_set.apps:
        return True, "trusted-app"
    return False, "not-in-trusted-set"


def machine_filing_marker(title: str) -> Optional[MachineFilingMarker]:
    """Pure. Returns the first table entry for which the title matches
    (prefix + optional required substring). Case-sensitive. Dormant entries
    match (a dormant emitting site that is re-enabled must not silently
    break)."""
    for marker in MACHINE_FILING_MARKERS:
        if title.startswith(marker.title_prefix) and (
            marker.title_contains is None or marker.title_contains in title
        ):
            return marker
    return None


def requester_verdict(record: Mapping[str, Any], trusted_set: TrustedSet) -> RequesterVerdict:
    """The ONLY composition any consumer may use to decide eligibility.
    Reads only record["user"]["login"], record["user"]["type"] and
    record["title"] (FR5) — never the body, never a label."""
    user = record.get("user") or {}
    login = user.get("login", "")
    user_type = user.get("type", "")
    trusted, reason = is_trusted_requester(login, user_type, trusted_set)
    if not trusted:
        return RequesterVerdict(False, reason, None, None)
    if reason == "trusted-app":
        marker = machine_filing_marker(record.get("title") or "")
        if marker is None:
            return RequesterVerdict(
                False, "trusted-app-no-machine-filing-marker", "trusted-app", None
            )
        return RequesterVerdict(
            True, f"trusted-app:{marker.marker_id}", "trusted-app", marker.marker_id
        )
    return RequesterVerdict(True, reason, reason, None)


def verify_codeowner_actor(
    events: Any,
    codeowners_humans: set[str],
    bot_accounts: set[str],
    label_name: str,
) -> Optional[str]:
    """AD-4's live authorization test, over an ALREADY-FETCHED events list
    (AD-1: no network inside the predicate). FOUR ARGUMENTS —
    `expected_milestone_title` is DELETED, not defaulted and not
    sentinelled (AR-7 / AM-35): there is ONE authorizing signal, a
    `labeled` event for `label_name` whose GitHub-reported actor is a
    verified individual human CODEOWNER. There is no second arm — a
    `milestoned` event never authorizes.

    A bot actor is `continue`, not `return None`: a bot relabelling after a
    CODEOWNER does not erase the CODEOWNER's earlier authorizing act
    (residual R-3)."""
    if not isinstance(events, list):
        return None
    relevant: list = []
    for event in events:
        if event.get("event") == "labeled" and (event.get("label") or {}).get("name") == label_name:
            relevant.append(event.get("actor") or {})
    for actor in reversed(relevant):
        login = actor.get("login", "")
        if not login:
            continue
        if is_bot_reviewer(login, actor.get("type", ""), bot_accounts):
            continue
        if login.lower() in codeowners_humans:
            return login
    return None
