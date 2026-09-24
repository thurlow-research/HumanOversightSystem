"""
Shared GitHub REST-by-id wrapper for the HOS automation loop.

All correctness-path reads MUST go through this module.
The GitHub Search API is NOT exposed here — it is eventually-consistent
and rate-limited (~30/min) and MUST NOT be used on any correctness path.
"""

import json
import subprocess
import time
from typing import Any, Optional


class GitHubError(Exception):
    """Raised when a GitHub API call fails after retries."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message, status_code)
        self.status_code = status_code


class RateLimitError(GitHubError):
    """Raised when the rate limit is hit and retry budget is exhausted."""


# Bounded wall-clock budget for a single `gh api` subprocess call (MUST_FIX
# C, #1657 PR-1 review round 2). Without this, `gh` stalling on DNS, TLS, or
# a proxy blocks the calling process forever — every read AND write this
# module makes (get_pull, list_pull_reviews, list_pull_files,
# submit_pull_review, request_reviewers) goes through here, and on
# Worker/Overseer's unattended cron there is nothing to interrupt a hang
# (CLAUDE.md "Shell usage under the sandbox": this is a genuine timeout, not
# a permission event — no rule catches it).
_GH_SUBPROCESS_TIMEOUT_SECONDS = 30


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
    """
    stdin_input: Optional[str] = None
    base_cmd = ["gh", "api", "--include"]
    if stdin_json is not None:
        base_cmd += ["--input", "-"]
        stdin_input = json.dumps(stdin_json)

    for attempt in range(retries + 1):
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


def list_pulls(
    owner: str,
    repo: str,
    head: Optional[str] = None,
    state: str = "all",
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/pulls (filtered by head and state).

    head should be in '{owner}:{branch}' form.
    Returns a list of PR objects (may be empty).
    """
    params = f"state={state}"
    if head:
        params += f"&head={head}"
    result = _run_gh([f"/repos/{owner}/{repo}/pulls?{params}"])
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def list_issue_comments(
    owner: str,
    repo: str,
    issue_number: int,
) -> list[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/issues/{number}/comments (all pages).

    Returns a list of comment objects ordered oldest-first.
    Paginates automatically — uses REST-by-id, never Search.
    """
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _run_gh(
            [f"/repos/{owner}/{repo}/issues/{issue_number}/comments" f"?per_page=100&page={page}"]
        )
        if not batch:
            break
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


def get_branch_protection(
    owner: str,
    repo: str,
    branch: str,
) -> Optional[dict[str, Any]]:
    """
    GET /repos/{owner}/{repo}/branches/{branch}/protection

    Returns the protection object or None if unprotected / not found.
    Used by merge_authority.py detect_server_side_gate (O3).
    """
    return _run_gh([f"/repos/{owner}/{repo}/branches/{branch}/protection"])


def get_repo(owner: str, repo: str) -> Optional[dict[str, Any]]:
    """GET /repos/{owner}/{repo} — basic repo metadata."""
    return _run_gh([f"/repos/{owner}/{repo}"])


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
