#!/usr/bin/env python3
"""rerun_gate_checks.py — review-triggered re-evaluation of the server-side gates.

Branch protection evaluates check runs anchored to the PR's HEAD SHA. A gate
that ran (and FAILED) before an approval landed leaves a stale FAILURE check
run on that SHA; nothing re-evaluates it, so overseer AUTO_MERGE stays blocked
after the approval (#1299). The earlier #795 fix (concurrency
cancel-in-progress) only cancels runs still IN PROGRESS — it cannot touch an
already-completed one. Re-triggering the gate workflow on pull_request_review
created a SECOND check run of the same name instead of clearing the first.

This script reruns the EXISTING workflow run in place
(POST /actions/runs/{id}/rerun), which updates the existing check run rather
than creating a duplicate, and replays the run's ORIGINAL pull_request_target
event so the check run stays anchored where it already was. The gate scripts
read reviews live via `gh` at run time, so a rerun re-evaluates current
approval state — that idempotence is the load-bearing assumption here.

Usage (CI):
  rerun_gate_checks.py --pr N --head-sha SHA --event-action submitted|dismissed
                       [--review-state STATE] [--repo owner/repo] [--dry-run]

Exit codes:
  0 — dispatched, or nothing to do, or partially degraded (see below)
  2 — usage/config error, or `gh` unavailable

There is deliberately NO failure exit code for "a rerun did not succeed". This
workflow is a DISPATCHER, not a gate: it is not in branch protection's
required-context list, and a red check run from it would add noise to the
exact PR check surface whose staleness we are fixing. Per-run failures are
reported as ::error::/::warning:: workflow annotations and in
$GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

GATE_WORKFLOWS: dict[str, str] = {
    "require-human-approval": ".github/workflows/require-human-approval.yml",
    "require-overseer-approval": ".github/workflows/require-overseer-approval.yml",
    "require-tier-ceiling": ".github/workflows/require-tier-ceiling.yml",
}
GATE_NAMES = frozenset(GATE_WORKFLOWS)
GATE_WORKFLOW_PATHS = frozenset(GATE_WORKFLOWS.values())

POLL_ATTEMPTS = 5
POLL_INTERVAL_SECONDS = 60
RERUN_ATTEMPTS = 4
RERUN_BACKOFF_SECONDS = (15, 30, 60)


class GhUnavailable(RuntimeError):
    """Raised when `gh` is not found on PATH."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _sleep(seconds: float) -> None:
    """Sole `time.sleep` call site — tests monkeypatch this, never real time."""
    time.sleep(seconds)


def _gh_api(path: str, *, method: str = "GET") -> tuple[int, Any]:
    """Run `gh api --include [--method M] <path>`, return (status_code, payload).

    Never raises on an HTTP error status — callers branch on the returned
    status code. Raises GhUnavailable if `gh` itself is not on PATH.
    """
    args = ["gh", "api", "--include"]
    if method != "GET":
        args += ["--method", method]
    args.append(path)
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise GhUnavailable("gh not found on PATH") from exc

    out = proc.stdout
    if "\r\n\r\n" in out:
        header_block, _, body = out.partition("\r\n\r\n")
    else:
        header_block, _, body = out.partition("\n\n")

    status_line = header_block.splitlines()[0] if header_block else ""
    match = re.match(r"HTTP/\S+\s+(\d+)", status_line)
    if not match:
        print(
            f"::warning::rerun_gate_checks: could not parse HTTP status for "
            f"{path}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return 0, None

    status = int(match.group(1))
    payload = None
    body = body.strip()
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
    return status, payload


# ---------------------------------------------------------------------------
# Dispatch decision
# ---------------------------------------------------------------------------

def should_dispatch(event_action: str, review_state: str) -> bool:
    """False only for a plain "commented" review — every other case dispatches
    (including dismissed and empty/unknown states — fail toward dispatching)."""
    if event_action == "submitted" and review_state.upper() == "COMMENTED":
        return False
    return True


# ---------------------------------------------------------------------------
# Gate check-run discovery
# ---------------------------------------------------------------------------

def list_gate_check_runs(repo: str, head_sha: str) -> list[dict]:
    """Every check run on head_sha whose name is a gate name (filter=all is
    REQUIRED — the endpoint defaults to filter=latest, which would hide the
    duplicate check-runs this fix targets)."""
    path = f"repos/{repo}/commits/{head_sha}/check-runs?per_page=100&filter=all"
    status, payload = _gh_api(path)
    if status != 200 or not isinstance(payload, dict):
        print(
            f"rerun_gate_checks: list_gate_check_runs: non-200 status {status} "
            f"for head SHA {head_sha}",
            file=sys.stderr,
        )
        return []

    all_runs = payload.get("check_runs") or []
    total_count = payload.get("total_count", len(all_runs))
    gate_runs = [r for r in all_runs if r.get("name") in GATE_NAMES]

    counts: dict[str, int] = {}
    for r in gate_runs:
        counts[r["name"]] = counts.get(r["name"], 0) + 1
    print(
        f"rerun_gate_checks: list_gate_check_runs: {len(all_runs)} check run(s) "
        f"returned for {head_sha}, {len(gate_runs)} gate-named"
    )
    for name, count in counts.items():
        print(f"rerun_gate_checks: gate '{name}': {count} check run(s)")
        if count > 1:
            print(f"rerun_gate_checks: duplicate check runs for {name}: {count}")

    if total_count > len(all_runs):
        print(
            f"::warning::rerun_gate_checks: check-runs listing truncated "
            f"({len(all_runs)} of {total_count} returned) for {head_sha}"
        )

    return gate_runs


def wait_for_completion(
    repo: str,
    check_run_id: int,
    *,
    attempts: int = POLL_ATTEMPTS,
    interval: int = POLL_INTERVAL_SECONDS,
) -> dict | None:
    """Poll a check run until status == "completed". Bounded: at most `attempts`
    GETs, at most `attempts - 1` sleeps. None if the budget is exhausted."""
    for i in range(attempts):
        status, payload = _gh_api(f"repos/{repo}/check-runs/{check_run_id}")
        if status == 200 and isinstance(payload, dict):
            if payload.get("status") == "completed":
                return payload
        else:
            print(
                f"rerun_gate_checks: wait_for_completion: non-200 status "
                f"{status} for check run {check_run_id}",
                file=sys.stderr,
            )
        if i < attempts - 1:
            _sleep(interval)
    return None


def resolve_workflow_run_id(repo: str, check_run: dict) -> int | None:
    """Resolve the workflow run backing a check run, restricted to gate paths.

    Both `path == expected path for this check-run name` AND
    `path in GATE_WORKFLOW_PATHS` are checked with plain `if`/`continue` (never
    `assert` — asserts strip under -O and this is a security guard).
    """
    name = check_run.get("name")
    suite_id = (check_run.get("check_suite") or {}).get("id")
    if suite_id is None:
        print(
            f"::error::rerun_gate_checks: check run {check_run.get('id')} "
            f"({name}) has no check_suite.id",
            file=sys.stderr,
        )
        return None

    status, payload = _gh_api(
        f"repos/{repo}/actions/runs?check_suite_id={suite_id}&per_page=100"
    )
    if status != 200 or not isinstance(payload, dict):
        print(
            f"::error::rerun_gate_checks: could not list workflow runs for "
            f"check_suite {suite_id} (status {status})",
            file=sys.stderr,
        )
        return None

    expected_path = GATE_WORKFLOWS.get(name)
    runs = payload.get("workflow_runs") or []
    survivors = []
    for run in runs:
        path = run.get("path")
        if path != expected_path:
            continue
        if path not in GATE_WORKFLOW_PATHS:
            continue
        survivors.append(run)

    if not survivors:
        rejected = sorted({r.get("path") for r in runs})
        print(
            f"::error::rerun_gate_checks: no workflow run for check-run "
            f"'{name}' (suite {suite_id}) matched expected path "
            f"{expected_path!r}; rejected paths seen: {rejected}",
            file=sys.stderr,
        )
        return None

    if len(survivors) > 1:
        print(
            f"rerun_gate_checks: ambiguous workflow runs for check-run "
            f"'{name}' (suite {suite_id}): "
            f"{sorted(r.get('id') for r in survivors)} — using highest id"
        )

    chosen = max(survivors, key=lambda r: r.get("id", 0))
    return chosen.get("id")


def pr_head_sha(repo: str, pr: int) -> str | None:
    status, payload = _gh_api(f"repos/{repo}/pulls/{pr}")
    if status != 200 or not isinstance(payload, dict):
        return None
    return (payload.get("head") or {}).get("sha")


def rerun_workflow_run(
    repo: str,
    run_id: int,
    *,
    attempts: int = RERUN_ATTEMPTS,
    backoff: tuple[int, ...] = RERUN_BACKOFF_SECONDS,
    dry_run: bool = False,
) -> bool:
    """POST /actions/runs/{run_id}/rerun. 403/5xx retry with backoff; 404 does
    not retry; other 4xx does not retry. dry_run makes zero API calls."""
    if dry_run:
        print(f"rerun_gate_checks: [dry-run] would POST rerun for run {run_id}")
        return True

    for i in range(attempts):
        status, _ = _gh_api(
            f"repos/{repo}/actions/runs/{run_id}/rerun", method="POST"
        )
        if 200 <= status < 300:
            print(
                f"rerun_gate_checks: rerun dispatched for run {run_id} "
                f"(status {status})"
            )
            # Log-only readback; its failure does not affect the result.
            _gh_api(f"repos/{repo}/actions/runs/{run_id}")
            return True

        if status == 404:
            print(
                f"::warning::rerun_gate_checks: rerun failed for run "
                f"{run_id}: 404 not found (no retry)"
            )
            return False

        if status == 403 or 500 <= status < 600:
            print(
                f"rerun_gate_checks: rerun for run {run_id} got status "
                f"{status} (attempt {i + 1}/{attempts})"
            )
            if i < attempts - 1:
                _sleep(backoff[i])
                continue
            print(
                f"::warning::rerun_gate_checks: rerun for run {run_id} "
                f"exhausted {attempts} attempts (last status {status})"
            )
            return False

        print(
            f"::warning::rerun_gate_checks: rerun for run {run_id} failed "
            f"with status {status}, not retrying"
        )
        return False

    return False


def fallback_gate_runs_for_pr(repo: str, pr: int) -> list[int]:
    """PR-scoped fallback used ONLY when list_gate_check_runs finds nothing on
    the head SHA (covers review-triggered check runs that aren't anchored to
    head SHA at all). NEVER enumerates check-runs on base.sha (shared across
    all open PRs) — the PR-number filter on pull_requests[] below is the
    safety property that stops this from ever touching another PR's runs."""
    status, payload = _gh_api(
        f"repos/{repo}/actions/runs?event=pull_request_target&per_page=100"
    )
    if status != 200 or not isinstance(payload, dict):
        print(
            f"::warning::rerun_gate_checks: fallback workflow-run listing "
            f"failed (status {status})",
            file=sys.stderr,
        )
        return []

    runs = payload.get("workflow_runs") or []
    best_by_path: dict[str, dict] = {}
    for run in runs:
        path = run.get("path")
        if path not in GATE_WORKFLOW_PATHS:
            continue
        prs = run.get("pull_requests") or []
        if not any(p.get("number") == pr for p in prs):
            continue
        existing = best_by_path.get(path)
        if existing is None or run.get("id", 0) > existing.get("id", 0):
            best_by_path[path] = run

    return [r["id"] for r in best_by_path.values()]


def process_pull_request(
    repo: str, pr: int, head_sha: str, *, dry_run: bool = False
) -> tuple[int, int]:
    """Orchestrate discovery + rerun for one PR. Returns (attempted, succeeded)."""
    check_runs = list_gate_check_runs(repo, head_sha)

    seen_ids: set = set()
    deduped: list[dict] = []
    for cr in check_runs:
        cid = cr.get("id")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        deduped.append(cr)

    run_ids: set[int] = set()
    if deduped:
        for cr in deduped:
            completed = wait_for_completion(repo, cr.get("id"))
            if completed is None:
                print(
                    f"::warning::rerun_gate_checks: check run {cr.get('id')} "
                    f"({cr.get('name')}) did not complete within the poll "
                    "budget — skipping",
                    file=sys.stderr,
                )
                continue
            run_id = resolve_workflow_run_id(repo, completed)
            if run_id is None:
                continue
            run_ids.add(run_id)
    else:
        print(
            f"::warning:: rerun_gate_checks: no gate check runs on head SHA "
            f"{head_sha} — using PR-scoped workflow-run fallback (#1299 "
            "root-cause signal)"
        )
        run_ids = set(fallback_gate_runs_for_pr(repo, pr))

    # Moved-head abort: after polling, before any POST, re-check the PR's
    # current head SHA — never rerun stale-SHA runs.
    current_sha = pr_head_sha(repo, pr)
    if current_sha is not None and current_sha != head_sha:
        print(
            f"rerun_gate_checks: PR #{pr} head SHA moved from {head_sha} to "
            f"{current_sha} — aborting to avoid rerunning stale-SHA runs",
            file=sys.stderr,
        )
        return 0, 0

    attempted = 0
    succeeded = 0
    rows: list[tuple[int, str]] = []
    for run_id in sorted(run_ids):
        attempted += 1
        ok = rerun_workflow_run(repo, run_id, dry_run=dry_run)
        succeeded += 1 if ok else 0
        rows.append((run_id, "success" if ok else "failed"))

    if rows:
        table_lines = ["| Workflow run ID | Rerun result |", "| --- | --- |"]
        table_lines += [f"| {run_id} | {result} |" for run_id, result in rows]
        table = "\n".join(table_lines)
    else:
        table = "No gate workflow runs found to rerun."
    print(table)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(table + "\n")
        except OSError as exc:
            print(
                f"::warning::rerun_gate_checks: could not write "
                f"GITHUB_STEP_SUMMARY: {exc}",
                file=sys.stderr,
            )

    return attempted, succeeded


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Rerun the gate workflow runs a PR review event may have made stale (#1299)"
    )
    ap.add_argument("--pr", type=int, required=True, help="PR number")
    ap.add_argument("--head-sha", required=True, help="PR head SHA at review time")
    ap.add_argument(
        "--event-action",
        required=True,
        choices=["submitted", "dismissed"],
        help="pull_request_review event action",
    )
    ap.add_argument("--review-state", default="", help="review.state (e.g. APPROVED, COMMENTED)")
    ap.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/repo (defaults to GITHUB_REPOSITORY env)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print(
            "rerun_gate_checks: --repo or GITHUB_REPOSITORY required",
            file=sys.stderr,
        )
        return 2

    if not should_dispatch(args.event_action, args.review_state):
        print(
            "rerun_gate_checks: review state COMMENTED — no gate-relevant "
            "change, nothing to dispatch"
        )
        return 0

    try:
        attempted, succeeded = process_pull_request(
            repo, args.pr, args.head_sha, dry_run=args.dry_run
        )
    except GhUnavailable as exc:
        print(f"rerun_gate_checks: gh unavailable: {exc}", file=sys.stderr)
        return 2

    print(
        f"rerun_gate_checks: dispatched {succeeded}/{attempted} gate "
        f"rerun(s) for PR #{args.pr}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"rerun_gate_checks: unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)
