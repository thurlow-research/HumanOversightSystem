"""
Shared GitHub REST-by-id wrapper for the HOS automation loop.

All correctness-path reads MUST go through this module.
The GitHub Search API is NOT exposed here — it is eventually-consistent
and rate-limited (~30/min) and MUST NOT be used on any correctness path.
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote


class GitHubError(Exception):
    """Raised when a GitHub API call fails after retries."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message, status_code)
        self.status_code = status_code


class RateLimitError(GitHubError):
    """Raised when the rate limit is hit and retry budget is exhausted."""


class ListTruncatedError(GitHubError):
    """A paginated read returned a malformed page or exceeded its page cap, so
    the list cannot be returned as complete (#2209)."""


# Bounded wall-clock budget for a single `gh api` subprocess call (MUST_FIX
# C, #1657 PR-1 review round 2). Without this, `gh` stalling on DNS, TLS, or
# a proxy blocks the calling process forever — every read AND write this
# module makes (get_pull, list_pull_reviews, list_pull_files,
# submit_pull_review, request_reviewers) goes through here, and on
# Worker/Overseer's unattended cron there is nothing to interrupt a hang
# (CLAUDE.md "Shell usage under the sandbox": this is a genuine timeout, not
# a permission event — no rule catches it).
_GH_SUBPROCESS_TIMEOUT_SECONDS = 30

# Bounded budget for the one-shot token re-mint on HTTP 401 (#2171); mirrors
# hos-cron's HOS_TOKEN_REFRESH_TIMEOUT_SECS default.
_REMINT_TIMEOUT_SECONDS = 90
_REMINT_ROLES = ("worker", "overseer", "human")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXPORT_RE = re.compile(r"^export (GH_TOKEN|HOS_BOT_LOGIN)='([^']*)'$")

# After a failed re-mint, skip further mint attempts for this long so a
# persistently bad credential costs one mint timeout, not one per call.
_REMINT_COOLDOWN_SECONDS = 300
_last_remint_failure: Optional[float] = None  # time.monotonic() of last failed mint

# Number of `_run_gh` invocations made by this process (one per logical call,
# not per retry). Callers read deltas via `gh_call_count()` to report API cost.
_gh_call_count = 0


def gh_call_count() -> int:
    """Logical `gh api` calls made so far by this process (monotonic)."""
    return _gh_call_count


def _remint_token() -> bool:
    """
    Re-mint the GitHub App installation token once (#2171).

    Installation tokens expire after 1h but cron cycles run 1-4h. Runs
    bootstrap/get_app_token.sh for the role in HOS_TOKEN_APP_ROLE, parses its
    `export NAME='VALUE'` lines strictly (never eval), and accepts the result
    only if the minted bot login equals the current HOS_BOT_LOGIN (identity
    pin). On success sets GH_TOKEN in this process's env only. Returns False
    on any failure. The token value is never logged or put in a message.

    A failed mint is memoised per process: for _REMINT_COOLDOWN_SECONDS the
    function returns False immediately without spawning the mint. A
    successful mint clears the memo.
    """
    global _last_remint_failure
    now = time.monotonic()
    if _last_remint_failure is not None and now - _last_remint_failure < _REMINT_COOLDOWN_SECONDS:
        print(
            f"github: 401 — token re-mint skipped (failed {int(now - _last_remint_failure)}s ago)",
            file=sys.stderr,
        )
        return False
    if _spawn_remint():
        _last_remint_failure = None
        return True
    # A missing role never spawns a mint, so it is not worth memoising.
    if os.environ.get("HOS_TOKEN_APP_ROLE", "") in _REMINT_ROLES:
        _last_remint_failure = time.monotonic()
    return False


def _spawn_remint() -> bool:
    """Run the mint once and apply the result; see _remint_token."""
    role = os.environ.get("HOS_TOKEN_APP_ROLE", "")
    if role not in _REMINT_ROLES:
        print("github: 401 — token re-mint failed (no valid HOS_TOKEN_APP_ROLE)", file=sys.stderr)
        return False
    try:
        proc = subprocess.run(
            [str(_REPO_ROOT / "bootstrap" / "get_app_token.sh"), "--app", role],
            capture_output=True,
            text=True,
            check=False,
            timeout=_REMINT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        print("github: 401 — token re-mint failed (mint did not run)", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(f"github: 401 — token re-mint failed (exit {proc.returncode})", file=sys.stderr)
        return False
    values: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        match = _EXPORT_RE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2)
    token = values.get("GH_TOKEN", "")
    login = values.get("HOS_BOT_LOGIN", "")
    current_login = os.environ.get("HOS_BOT_LOGIN", "")
    if not token or not login or not current_login or login != current_login:
        print("github: 401 — token re-mint failed (identity check)", file=sys.stderr)
        return False
    os.environ["GH_TOKEN"] = token
    print(f"github: 401 — re-minted {role} token, retrying once", file=sys.stderr)
    return True


def _run_gh(
    args: list[str],
    retries: int = 3,
    backoff_base: float = 2.0,
    stdin_json: Optional[dict[str, Any]] = None,
) -> Any:
    """
    Run a `gh api` command and return the parsed JSON response.

    Retries on transient failures (5xx, network errors, a subprocess
    timeout) with exponential backoff.  Raises RateLimitError on 429/403
    rate-limit responses after honoring the Retry-After header.  Raises
    GitHubError on permanent 4xx.

    Never calls `gh search` — callers that need Search must go through a
    separate, explicitly-named surface (none exists here by design).

    stdin_json: if provided, serialised as JSON and piped via --input -.
    Use this for POST/PATCH bodies so that @path strings are NEVER expanded
    by the gh CLI's --field type-coercion (the root cause of #752).

    A timeout is never treated as a retryable-and-then-silently-successful
    outcome: each attempt is independent (a fresh `subprocess.run` call), so
    a timed-out attempt that is retried and a later attempt that succeeds is
    an ordinary retry, not a masked failure — but a non-idempotent write
    (`submit_pull_review`) is called with `retries=0` specifically so this
    generic loop never retries it at all (MUST_FIX D); a POST that times out
    may have already reached GitHub, and only the call site — which can
    re-fetch and check whether the write landed — is positioned to decide
    that safely.

    HTTP 401 (#2171): an expired installation token. On the first 401 the
    token is re-minted once (`_remint_token`) and the same request is re-sent
    immediately. That retry is outside the `retries` budget and applies even
    with retries=0: a 401 means GitHub rejected the request, so re-sending a
    write is safe. If the re-mint fails or the retry is 401 again, raises
    GitHubError(status_code=401) — a 401 is never backed off, parsed as
    data, or returned as None.
    """
    global _gh_call_count
    _gh_call_count += 1
    stdin_input: Optional[str] = None
    reminted = False
    base_cmd = ["gh", "api", "--include"]
    if stdin_json is not None:
        base_cmd += ["--input", "-"]
        stdin_input = json.dumps(stdin_json)

    attempt = -1
    while attempt < retries:
        attempt += 1
        try:
            result = subprocess.run(
                base_cmd + args,
                input=stdin_input,
                capture_output=True,
                text=True,
                check=False,
                timeout=_GH_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            raise GitHubError("gh CLI not found — ensure it is installed and on PATH")
        except subprocess.TimeoutExpired:
            if attempt < retries:
                time.sleep(backoff_base**attempt)
                continue
            raise GitHubError(
                f"gh command timed out after {_GH_SUBPROCESS_TIMEOUT_SECONDS}s "
                f"(attempt {attempt + 1}/{retries + 1})"
            )

        headers, _, body = result.stdout.partition("\r\n\r\n")
        if not body and "\n\n" in result.stdout:
            headers, _, body = result.stdout.partition("\n\n")

        # Parse status from the HTTP/2 status line in `--include` output.
        status_code = None
        for line in headers.splitlines():
            if line.startswith("HTTP/"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        status_code = int(parts[1])
                    except ValueError:
                        pass
                break

        stderr_401 = (
            status_code is None
            and result.returncode != 0
            and ("HTTP 401" in result.stderr or "Bad credentials" in result.stderr)
        )
        if status_code == 401 or stderr_401:
            if reminted:
                raise GitHubError(
                    "GitHub authentication failed (HTTP 401); still 401 after token re-mint",
                    status_code=401,
                )
            reminted = True
            if not _remint_token():
                raise GitHubError(
                    "GitHub authentication failed (HTTP 401); token re-mint unavailable or failed",
                    status_code=401,
                )
            attempt -= 1  # the 401 re-send does not consume the retry budget
            continue

        if status_code is None and result.returncode != 0:
            # gh uses non-zero exit for API errors; no parseable header.
            if attempt < retries:
                time.sleep(backoff_base**attempt)
                continue
            raise GitHubError(
                f"gh command failed (rc={result.returncode}): {result.stderr.strip()}"
            )

        if status_code in (429, 403):
            retry_after = _parse_retry_after(headers)
            if attempt < retries:
                time.sleep(retry_after or (backoff_base**attempt))
                continue
            raise RateLimitError(
                f"GitHub rate limit hit (HTTP {status_code})", status_code=status_code
            )

        if status_code is not None and status_code >= 500:
            if attempt < retries:
                time.sleep(backoff_base**attempt)
                continue
            raise GitHubError(f"GitHub server error (HTTP {status_code})", status_code=status_code)

        if status_code == 404:
            return None  # Caller checks for None = resource does not exist.

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Could not resolve to a Repository" in stderr or "HTTP 404" in stderr:
                return None
            raise GitHubError(
                f"GitHub API error (rc={result.returncode}): {stderr}",
                status_code=status_code,
            )

        if not body.strip():
            return None

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"Could not parse GitHub response: {exc}") from exc

    raise GitHubError("Exhausted retries with no terminal response")


def _parse_retry_after(headers: str) -> Optional[float]:
    for line in headers.splitlines():
        if line.lower().startswith("retry-after:"):
            try:
                return float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# REST-by-id reads (the only public surface — no Search)
# ---------------------------------------------------------------------------


def get_ref(owner: str, repo: str, ref: str) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/git/ref/{ref}

    Returns the ref object or None if it does not exist.
    Never uses Search.
    """
    return _run_gh([f"/repos/{owner}/{repo}/git/ref/{ref}"])


def get_branch(owner: str, repo: str, branch: str) -> Optional[dict[str, Any]]:
    """
    Convenience wrapper for get_ref for a branch head.
    Returns the ref object or None.
    """
    return get_ref(owner, repo, f"heads/{branch}")


def _pulls_path(
    owner: str,
    repo: str,
    head: Optional[str],
    state: str,
    base: Optional[str],
) -> str:
    params = f"state={state}"
    if head:
        params += f"&head={quote(head, safe=':')}"
    if base:
        params += f"&base={quote(base, safe='')}"
    return f"/repos/{owner}/{repo}/pulls?{params}"


def list_pulls(
    owner: str,
    repo: str,
    head: Optional[str] = None,
    state: str = "all",
    base: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/pulls (filtered by head, base and state).

    head should be in '{owner}:{branch}' form; base is a bare branch name.
    Returns a list of PR objects (may be empty).
    """
    result = _run_gh([_pulls_path(owner, repo, head, state, base)])
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def list_pulls_strict(
    owner: str,
    repo: str,
    head: Optional[str] = None,
    state: str = "all",
    base: Optional[str] = None,
) -> Optional[list[dict[str, Any]]]:
    """
    Same request as list_pulls, but an indeterminate answer is not an empty list.

    Returns the list only when the API returned a genuine JSON list (possibly
    empty); None for a 404/empty body (``_run_gh`` None) or any non-list payload.
    For callers that must fail closed (#2298).
    """
    result = _run_gh([_pulls_path(owner, repo, head, state, base)])
    return result if isinstance(result, list) else None


def list_all_pulls(
    owner: str,
    repo: str,
    *,
    state: str = "all",
    max_pages: int = 40,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/pulls (all pages, oldest first).

    Never returns a partial list: a non-list page (a None on page 1 is a 404),
    more than ``max_pages`` full pages, or an empty ``state="all"`` listing
    (this repo always has PRs, so empty means a bad read) raises. Ascending
    creation order means a PR opened during pagination is appended after the
    existing ones and can never shift an item off a page (#2286).
    """
    pulls: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = _run_gh(
            [
                f"/repos/{owner}/{repo}/pulls?state={state}&sort=created&direction=asc"
                f"&per_page=100&page={page}"
            ]
        )
        if batch is None and page == 1:
            raise GitHubError(f"pulls for {owner}/{repo} not found", status_code=404)
        if not isinstance(batch, list):
            raise ListTruncatedError(
                f"unexpected pulls payload for {owner}/{repo}: expected list, "
                f"got {type(batch).__name__}"
            )
        pulls.extend(batch)
        if len(batch) < 100:
            if state == "all" and not pulls:
                raise ListTruncatedError(f"empty pull-request listing for {owner}/{repo}")
            return pulls
    raise ListTruncatedError(f"pulls for {owner}/{repo} exceeded {max_pages} pages")


def list_all_issue_states(
    owner: str,
    repo: str,
    *,
    max_pages: int = 60,
) -> dict[int, str]:
    """
    GET /repos/{owner}/{repo}/issues?state=all (all pages, oldest first) as
    ``{number: "open" | "closed"}``. Includes PR numbers (harmless: keyed by number).

    Same fail-closed contract as ``list_all_pulls``. Issues can be deleted or
    transferred mid-pagination, which can skip one item, so a caller must treat
    a number absent from the map as unknown, never as closed (#2286).
    """
    states: dict[int, str] = {}
    for page in range(1, max_pages + 1):
        batch = _run_gh(
            [
                f"/repos/{owner}/{repo}/issues?state=all&sort=created&direction=asc"
                f"&per_page=100&page={page}"
            ]
        )
        if batch is None and page == 1:
            raise GitHubError(f"issues for {owner}/{repo} not found", status_code=404)
        if not isinstance(batch, list):
            raise ListTruncatedError(
                f"unexpected issues payload for {owner}/{repo}: expected list, "
                f"got {type(batch).__name__}"
            )
        for item in batch:
            number = item.get("number") if isinstance(item, dict) else None
            state = item.get("state") if isinstance(item, dict) else None
            if not isinstance(number, int) or state not in ("open", "closed"):
                raise ListTruncatedError(f"malformed issue entry in {owner}/{repo} listing")
            states[number] = state
        if len(batch) < 100:
            return states
    raise ListTruncatedError(f"issues for {owner}/{repo} exceeded {max_pages} pages")


def list_issue_comments(
    owner: str,
    repo: str,
    issue_number: int,
    *,
    max_pages: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/issues/{number}/comments (all pages).

    Returns a list of comment objects ordered oldest-first.
    Paginates automatically — uses REST-by-id, never Search.

    With ``max_pages``, a non-list page (including None) or a non-empty page beyond ``max_pages``
    raises ListTruncatedError rather than returning a partial list (#2263).
    """
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/issues/{issue_number}/comments" f"?per_page=100&page={page}"]
        )
        if max_pages is not None and not isinstance(batch, list):
            # None is a 404 or an empty body (an empty thread is a "[]" body, a list):
            # a partial read could hide a comment, so fail closed.
            raise ListTruncatedError(
                f"unexpected comments payload for {owner}/{repo}#{issue_number}: "
                f"expected list, got {type(batch).__name__}"
            )
        if not batch:
            break
        if max_pages is not None and page > max_pages:
            raise ListTruncatedError(
                f"comments for {owner}/{repo}#{issue_number} exceeded {max_pages} pages"
            )
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


def list_check_runs_for_ref(
    owner: str,
    repo: str,
    ref: str,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/commits/{ref}/check-runs (all pages).

    Returns check-run objects in GitHub's own order (most recently created
    first). Used by merge_authority.py's required-content-checks bounce gate
    (#1580) to read each required check's current conclusion for a head SHA.
    """
    runs: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/commits/{ref}/check-runs" f"?per_page=100&page={page}"]
        )
        check_runs = (batch or {}).get("check_runs") or []
        if not check_runs:
            break
        runs.extend(check_runs)
        if len(check_runs) < 100:
            break
        page += 1
    return runs


def list_check_suites_for_ref(
    owner: str,
    repo: str,
    ref: str,
    *,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/commits/{ref}/check-suites (all pages).

    Returns the concatenated ``check_suites`` lists. A page that is not a
    dict with a list ``check_suites``, or more than ``max_pages`` full pages,
    raises ListTruncatedError: a truncated list is never returned as complete (#2209).
    """
    suites: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/commits/{ref}/check-suites" f"?per_page=100&page={page}"]
        )
        page_suites = batch.get("check_suites") if isinstance(batch, dict) else None
        if not isinstance(page_suites, list):
            raise ListTruncatedError(
                f"unexpected check-suites payload for {owner}/{repo}@{ref}: "
                "expected a dict with a list 'check_suites'"
            )
        suites.extend(page_suites)
        if len(page_suites) < 100:
            return suites
    raise ListTruncatedError(f"check-suites for {owner}/{repo}@{ref} exceeded {max_pages} pages")


def list_issue_events(
    owner: str,
    repo: str,
    number: int,
    *,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/issues/{number}/events (all pages, oldest first).

    A non-list page, or more than ``max_pages`` full pages, raises GitHubError
    rather than returning a truncated list (#2209).
    """
    events: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/issues/{number}/events" f"?per_page=100&page={page}"]
        )
        if batch is None:
            if page == 1:
                raise GitHubError(
                    f"issue events for {owner}/{repo}#{number} not found (404 or empty body)",
                    status_code=404,
                )
            batch = []
        page_events = batch
        if not isinstance(page_events, list):
            raise ListTruncatedError(
                f"unexpected issue-events payload for {owner}/{repo}#{number}: "
                f"expected list, got {type(page_events).__name__}"
            )
        events.extend(page_events)
        if len(page_events) < 100:
            return events
    raise ListTruncatedError(f"events for {owner}/{repo}#{number} exceeded {max_pages} pages")


def get_contents(owner: str, repo: str, path: str, *, ref: str) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/contents/{path}?ref={ref}

    None on 404. A list payload (a directory) raises GitHubError. Decoding the
    base64 ``content`` is the caller's job (#2209).
    """
    result = _run_gh([f"/repos/{owner}/{repo}/contents/{quote(path)}?ref={quote(ref, safe='')}"])
    if isinstance(result, list):
        raise GitHubError(f"contents of {owner}/{repo}:{path}@{ref} is a directory, not a file")
    return result


def get_branch_protection(
    owner: str,
    repo: str,
    branch: str,
    *,
    retries: int = 3,
) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/branches/{branch}/protection

    Returns the protection object or None if unprotected / not found.
    Used by merge_authority.py detect_server_side_gate (O3). ``retries`` is
    passed to _run_gh; callers that treat a failed read as a soft degrade
    (check_required_content_checks, #1731) pass 0 to skip 403 backoff.
    """
    return _run_gh([f"/repos/{owner}/{repo}/branches/{branch}/protection"], retries=retries)


_RULES_MAX_PAGES = 10


def list_branch_rules(owner: str, repo: str, branch: str) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/rules/branches/{branch} (all pages).

    Returns every rule object that applies to the branch (each carries its
    ``type``, ``parameters`` and ``ruleset_id``). GitHubError propagates,
    including on a non-list payload and when more than _RULES_MAX_PAGES full
    pages come back (#2213: a truncated rule list is the fail-open direction).
    """
    all_rules: list[dict[str, Any]] = []
    for page in range(1, _RULES_MAX_PAGES + 1):
        batch = _run_gh([f"/repos/{owner}/{repo}/rules/branches/{branch}?per_page=100&page={page}"])
        rules = [] if batch is None else batch
        if not isinstance(rules, list):
            raise GitHubError(
                f"unexpected rules payload for {owner}/{repo}@{branch}: "
                f"expected list, got {type(rules).__name__}"
            )
        all_rules.extend(rules)
        if len(rules) < 100:
            return all_rules
    raise GitHubError(f"rules for {owner}/{repo}@{branch} exceeded {_RULES_MAX_PAGES} pages")


def _required_contexts_from_rules(rules: Any) -> list[str]:
    """
    Pure: the de-duplicated required status-check contexts (first-seen order)
    from every ``required_status_checks`` rule in ``rules``; malformed
    elements are ignored (#2213 TD-D17, extracted from
    get_ruleset_required_checks).
    """
    contexts: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters")
        checks = params.get("required_status_checks") if isinstance(params, dict) else None
        if not isinstance(checks, list):
            continue
        for check in checks:
            context = check.get("context") if isinstance(check, dict) else None
            if isinstance(context, str) and context and context not in contexts:
                contexts.append(context)
    return contexts


def get_ruleset_required_checks(
    owner: str,
    repo: str,
    branch: str,
) -> list[str]:
    """
    GET /repos/{owner}/{repo}/rules/branches/{branch} (all pages).

    Returns the de-duplicated required status-check contexts (first-seen
    order) from every ``required_status_checks`` rule that applies to the
    branch, or [] if none / not found. Repository rulesets are where this
    repo's required checks live, and the overseer App gets 403 on the classic
    protection endpoint (#1731, #1588). Used by merge_authority.py
    check_required_content_checks. GitHubError propagates to the caller,
    including when more than _RULES_MAX_PAGES full pages come back.
    """
    return _required_contexts_from_rules(list_branch_rules(owner, repo, branch))


def get_ruleset(owner: str, repo: str, ruleset_id: int) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/rulesets/{ruleset_id} (#2213 AD-5).

    Returns the ruleset object (``enforcement``, ``current_user_can_bypass``)
    or None on a 404. Raises GitHubError on a non-dict payload.
    """
    result = _run_gh([f"/repos/{owner}/{repo}/rulesets/{ruleset_id}"])
    if result is not None and not isinstance(result, dict):
        raise GitHubError(
            f"unexpected ruleset payload for {owner}/{repo} #{ruleset_id}: "
            f"expected object, got {type(result).__name__}"
        )
    return result


_THREADS_MAX_PAGES = 10
_REVIEW_THREADS_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!,$cursor:String){"
    "repository(owner:$owner,name:$name){pullRequest(number:$number){"
    "reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor} "
    "nodes{id isResolved isOutdated comments(first:1){nodes{author{login}}}}}}}}"
)


def list_review_threads(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """
    GraphQL: every review thread on a PR (id, isResolved, isOutdated, first
    comment author), bounded to _THREADS_MAX_PAGES pages (#2213 AD-2).

    Raises GitHubError on a GraphQL ``errors`` key, a null ``pullRequest``, a
    missing ``pageInfo``, and when ``hasNextPage`` is still true after the
    page cap: an incomplete thread list could hide an unresolved thread.
    """
    nodes: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    for _ in range(_THREADS_MAX_PAGES):
        args = [
            "graphql",
            "-f",
            f"query={_REVIEW_THREADS_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={repo}",
            "-F",
            f"number={pr_number}",
        ]
        if cursor:
            args += ["-f", f"cursor={cursor}"]
        result = _run_gh(args)
        if not isinstance(result, dict):
            raise GitHubError("review threads: GraphQL returned no usable response")
        if result.get("errors"):
            raise GitHubError("review threads: GraphQL returned errors")
        data = result.get("data")
        repository = data.get("repository") if isinstance(data, dict) else None
        pull = repository.get("pullRequest") if isinstance(repository, dict) else None
        if not isinstance(pull, dict):
            raise GitHubError(f"review threads: pull request {owner}/{repo}#{pr_number} not found")
        threads = pull.get("reviewThreads")
        page_info = threads.get("pageInfo") if isinstance(threads, dict) else None
        page_nodes = threads.get("nodes") if isinstance(threads, dict) else None
        if not isinstance(page_info, dict) or not isinstance(page_nodes, list):
            raise GitHubError("review threads: malformed reviewThreads payload")
        nodes.extend(n for n in page_nodes if isinstance(n, dict))
        if not page_info.get("hasNextPage"):
            return nodes
        cursor = page_info.get("endCursor")
        if not isinstance(cursor, str) or not cursor:
            raise GitHubError("review threads: hasNextPage without an endCursor")
    raise GitHubError(
        f"review threads for {owner}/{repo}#{pr_number} exceeded {_THREADS_MAX_PAGES} pages"
    )


def get_file_text(owner: str, repo: str, path: str, ref: str) -> Optional[str]:
    """
    GET /repos/{owner}/{repo}/contents/{path}?ref={ref}, decoded as UTF-8 (#2213 AF-9).

    Returns None on a 404. Raises GitHubError if the response is not a file
    object with base64 encoding or if the content does not decode.
    """
    result = _run_gh([f"/repos/{owner}/{repo}/contents/{path}?ref={quote(ref, safe='')}"])
    if result is None:
        return None
    if (
        not isinstance(result, dict)
        or result.get("type") != "file"
        or result.get("encoding") != "base64"
        or not isinstance(result.get("content"), str)
    ):
        raise GitHubError(f"unexpected contents payload for {owner}/{repo}:{path}")
    try:
        return base64.b64decode(result["content"], validate=False).decode("utf-8")
    except ValueError as exc:  # includes UnicodeDecodeError and binascii.Error
        raise GitHubError(f"could not decode {owner}/{repo}:{path}: {exc}") from exc


def get_repo(owner: str, repo: str) -> Optional[dict[str, Any]]:
    """GET /repos/{owner}/{repo} — basic repo metadata."""
    return _run_gh([f"/repos/{owner}/{repo}"])


def get_issue(owner: str, repo: str, issue_number: int) -> Optional[dict[str, Any]]:
    """GET /repos/{owner}/{repo}/issues/{issue_number} — None if not found."""
    return _run_gh([f"/repos/{owner}/{repo}/issues/{issue_number}"])


def get_pull(owner: str, repo: str, pr_number: int) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/pulls/{pr_number}

    Returns the PR object or None if it does not exist. Used by
    merge_authority_cli.human-approval / hold-directive / protected-surface /
    security-surface / codeowners (#1357) to resolve head.sha and other
    PR-level fields it needs before calling an L1 primitive.
    """
    return _run_gh([f"/repos/{owner}/{repo}/pulls/{pr_number}"])


def list_pull_reviews(
    owner: str,
    repo: str,
    pr_number: int,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/pulls/{pr_number}/reviews (all pages).

    Returns a list of review objects (may be empty). Used by
    merge_authority_cli.human-approval (#1357) to fetch the reviews
    has_human_approval / _find_human_approval evaluate.
    """
    reviews: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews" f"?per_page=100&page={page}"]
        )
        if not batch:
            break
        reviews.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return reviews


def list_pull_files(
    owner: str,
    repo: str,
    pr_number: int,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/pulls/{pr_number}/files (all pages).

    Returns a list of file objects (may be empty), each with at least
    'filename'. Used by merge_authority_cli.protected-surface /
    security-surface / codeowners (#1357) to build the changed-files list
    those L1 functions match against. Must paginate: a PR near the 15-file
    budget fits in one page, but a silently-truncated file list would
    under-report a protected-surface match — the fail-open direction.
    """
    files: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/pulls/{pr_number}/files" f"?per_page=100&page={page}"]
        )
        if not batch:
            break
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return files


def get_commit(owner: str, repo: str, ref: str) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/commits/{ref}

    Returns the commit object or None if it does not exist. Used by
    merge_authority_cli.hold-directive (#1357) to read
    commit.committer.date as head_committed_at (a rebase updates
    committer.date but not author.date, matching the library's
    "pushed/committed" semantics).
    """
    return _run_gh([f"/repos/{owner}/{repo}/commits/{ref}"])


def post_comment(
    owner: str,
    repo: str,
    issue_or_pr_number: int,
    body: str,
    *,
    verify: bool = True,
) -> dict[str, Any]:
    """
    POST a comment to an issue or PR thread, safe against @path expansion (#752).

    Uses JSON-encoded body via --input - (stdin) so that a body string starting
    with '@/' is never misinterpreted by gh's --field type-coercion as a file
    path.  This is the canonical helper for all escalation / finding comments.

    If verify=True (default), reads back the posted comment and raises
    GitHubError if the stored body starts with '@/' — catching any future
    regression where an @path literal slips through instead of file content.

    Returns the created comment object (contains at least 'id' and 'html_url').
    Raises GitHubError on any failure, including a failed read-back.
    """
    result = _run_gh(
        [f"/repos/{owner}/{repo}/issues/{issue_or_pr_number}/comments", "--method", "POST"],
        stdin_json={"body": body},
    )
    if result is None:
        raise GitHubError("post_comment: GitHub returned no response for POST")

    if verify:
        comment_id = result.get("id")
        if comment_id is None:
            raise GitHubError("post_comment: response missing 'id' — cannot verify")
        readback = _run_gh([f"/repos/{owner}/{repo}/issues/comments/{comment_id}"])
        if readback is None:
            raise GitHubError(f"post_comment: read-back of comment {comment_id} returned None")
        stored_body: str = readback.get("body", "")
        if stored_body.startswith("@/"):
            raise GitHubError(
                f"post_comment: comment {comment_id} body starts with '@/' — "
                "@path literal was stored instead of file content (#752)"
            )

    return result


def submit_pull_review(
    owner: str,
    repo: str,
    pr_number: int,
    event: str,
    body: str,
    commit_id: str,
) -> dict[str, Any]:
    """
    POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews (#1657).

    event must be "APPROVE" or "COMMENT" (uppercase, validated here) —
    REQUEST_CHANGES is never emitted by this primitive (ADR-1657 AD-2;
    bootstrap/post_review_thread.sh owns blocking, resolvable findings).
    commit_id is required: it pins the verdict to the exact diff reviewed,
    so a worker push between the caller's read and this write surfaces as a
    422 from GitHub rather than silently approving a different diff.

    Uses JSON-encoded body via --input - (stdin) so a body string starting
    with '@/' is never misinterpreted by gh's --field type-coercion as a
    file path (#752), the same reason post_comment does.

    Called with retries=0 (MUST_FIX D, #1657 PR-1 review round 2): this POST
    is not idempotent and carries no idempotency key, so every successful
    call creates a new review object. `_run_gh`'s generic retry loop treats
    "no parseable status, non-zero exit" (the connection-reset-after-send
    case) as retryable — correct for an idempotent GET, but for this POST it
    risks creating a duplicate review that no downstream dedup guard can
    catch, since those guards read the reviews list once at the start of
    the caller's own invocation and have no visibility into a duplicate
    created inside a single call's own retry loop. The caller
    (pr_review_cli.py's _cmd_submit_verdict) handles an ambiguous failure
    from this function explicitly: it re-fetches list_pull_reviews filtered
    to this head_sha and bot login to determine whether the write actually
    landed before deciding whether to report success or retry.

    Returns the created review object (at least id, state, body, commit_id,
    html_url). Raises GitHubError on an invalid event or a null response.
    """
    if event not in ("APPROVE", "COMMENT"):
        raise GitHubError(
            f"submit_pull_review: event must be 'APPROVE' or 'COMMENT', got: {event!r}"
        )
    result = _run_gh(
        [f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews", "--method", "POST"],
        retries=0,
        stdin_json={"event": event, "body": body, "commit_id": commit_id},
    )
    if result is None:
        raise GitHubError("submit_pull_review: GitHub returned no response for POST")
    return result


def request_reviewers(
    owner: str,
    repo: str,
    pr_number: int,
    logins: list[str],
) -> dict[str, Any]:
    """
    POST /repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers (#1657).

    logins: a non-empty list of user logins. Team reviewers are NOT
    supported by this function — a team request needs the separate
    `team_reviewers` field and org membership a personal-repo install may
    not have; see docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md
    §4.5 step 5. Any login containing "/" — "@org/team" or the un-prefixed
    "org/team" alike (SHOULD_FIX 4, #1657 PR-1 review round 4) — raises
    ValueError rather than being silently posted as a user login and 422ing.

    Uses JSON-encoded body via --input - (stdin) for the same #752 reason as
    post_comment / submit_pull_review.

    Unlike submit_pull_review, this call keeps `_run_gh`'s default retries:
    POST .../requested_reviewers IS idempotent at the API level (re-adding
    an already-requested login is a no-op), so a retry after an ambiguous
    failure carries none of submit_pull_review's duplicate-object risk
    (MUST_FIX D, #1657 PR-1 review round 2 — do not copy that change here).

    Returns the updated PR object. Raises GitHubError on a null response.
    """
    if not logins:
        raise GitHubError("request_reviewers: logins must be non-empty")
    for login in logins:
        if "/" in login:
            raise ValueError(f"request_reviewers: team reviewers are not supported, got: {login!r}")
    result = _run_gh(
        [f"/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers", "--method", "POST"],
        stdin_json={"reviewers": logins},
    )
    if result is None:
        raise GitHubError("request_reviewers: GitHub returned no response for POST")
    return result


# ---------------------------------------------------------------------------
# Label helpers (#2157 — hos-in-progress visibility)
# ---------------------------------------------------------------------------


def get_label(owner: str, repo: str, name: str) -> Optional[dict[str, Any]]:
    """GET /repos/{owner}/{repo}/labels/{name}; None if the label does not exist."""
    return _run_gh([f"/repos/{owner}/{repo}/labels/{name}"])


def create_label(
    owner: str, repo: str, name: str, color: str, description: str
) -> Optional[dict[str, Any]]:
    """POST /repos/{owner}/{repo}/labels. Raises GitHubError (status 422 if it already exists)."""
    return _run_gh(
        [f"/repos/{owner}/{repo}/labels", "--method", "POST"],
        stdin_json={"name": name, "color": color, "description": description},
    )


def list_issues_with_label(owner: str, repo: str, label: str) -> list[dict[str, Any]]:
    """GET open issues (and PRs — the issues endpoint returns both) carrying `label`, all pages."""
    found: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/issues?labels={label}&state=open&per_page=100&page={page}"]
        )
        if not batch:
            break
        found.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return found


def add_issue_label(owner: str, repo: str, issue_number: int, label: str) -> None:
    """POST /repos/{owner}/{repo}/issues/{number}/labels (adds; never replaces)."""
    _run_gh(
        [f"/repos/{owner}/{repo}/issues/{issue_number}/labels", "--method", "POST"],
        stdin_json={"labels": [label]},
    )


def remove_issue_label(owner: str, repo: str, issue_number: int, label: str) -> None:
    """DELETE one label from an issue; a 404 (already removed) is success."""
    _run_gh([f"/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}", "--method", "DELETE"])


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def merge_pull(owner: str, repo: str, pr_number: int, sha: str) -> dict[str, Any]:
    """
    PUT /repos/{owner}/{repo}/pulls/{pr_number}/merge (#2213).

    The merge method is fixed to squash and is deliberately not a parameter,
    so nothing can widen it. ``sha`` pins the merge to the exact head that was
    approved: if the head moved, GitHub answers 409. Called with retries=0
    (same reasoning as submit_pull_review): a write that may have reached
    GitHub is re-read by the caller, never blindly re-sent.

    Raises ValueError (no call made) unless ``sha`` is a 40-char lowercase hex
    SHA, and GitHubError on a null response.
    """
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise ValueError(f"merge_pull: sha must be a 40-char lowercase hex SHA, got: {sha!r}")
    result = _run_gh(
        [f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", "--method", "PUT"],
        retries=0,
        stdin_json={"merge_method": "squash", "sha": sha},
    )
    if result is None:
        # No status: an empty 2xx body is not a definite refusal, so callers
        # must treat it as ambiguous and re-read the PR.
        raise GitHubError("merge_pull: GitHub returned no response for PUT")
    return result
