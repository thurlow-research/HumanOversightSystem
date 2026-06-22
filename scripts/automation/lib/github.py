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
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(GitHubError):
    """Raised when the rate limit is hit and retry budget is exhausted."""


def _run_gh(
    args: list[str],
    retries: int = 3,
    backoff_base: float = 2.0,
    stdin_json: Optional[dict[str, Any]] = None,
) -> Any:
    """
    Run a `gh api` command and return the parsed JSON response.

    Retries on transient failures (5xx, network errors) with exponential
    backoff.  Raises RateLimitError on 429/403 rate-limit responses after
    honoring the Retry-After header.  Raises GitHubError on permanent 4xx.

    Never calls `gh search` — callers that need Search must go through a
    separate, explicitly-named surface (none exists here by design).

    stdin_json: if provided, serialised as JSON and piped via --input -.
    Use this for POST/PATCH bodies so that @path strings are NEVER expanded
    by the gh CLI's --field type-coercion (the root cause of #752).
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
                capture_output=True, text=True, check=False
            )
        except FileNotFoundError:
            raise GitHubError("gh CLI not found — ensure it is installed and on PATH")

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
                time.sleep(backoff_base ** attempt)
                continue
            raise GitHubError(
                f"gh command failed (rc={result.returncode}): {result.stderr.strip()}"
            )

        if status_code in (429, 403):
            retry_after = _parse_retry_after(headers)
            if attempt < retries:
                time.sleep(retry_after or (backoff_base ** attempt))
                continue
            raise RateLimitError(
                f"GitHub rate limit hit (HTTP {status_code})", status_code=status_code
            )

        if status_code is not None and status_code >= 500:
            if attempt < retries:
                time.sleep(backoff_base ** attempt)
                continue
            raise GitHubError(
                f"GitHub server error (HTTP {status_code})", status_code=status_code
            )

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
        batch = _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments"
            f"?per_page=100&page={page}"
        ])
        if not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return comments


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
            raise GitHubError(
                f"post_comment: read-back of comment {comment_id} returned None"
            )
        stored_body: str = readback.get("body", "")
        if stored_body.startswith("@/"):
            raise GitHubError(
                f"post_comment: comment {comment_id} body starts with '@/' — "
                "@path literal was stored instead of file content (#752)"
            )

    return result
