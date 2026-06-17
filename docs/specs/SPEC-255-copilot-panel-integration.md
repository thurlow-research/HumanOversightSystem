# Requirements Spec — Issue #255: GitHub Copilot as Panel Oversight Reviewer

**Document type:** Requirements specification
**Status:** Draft
**Issue:** #255
**Date:** 2026-06-16
**Author:** pm-agent

---

## 1. Problem Statement

The panel (`run_panel.sh`) currently invokes agy and codex as cross-vendor reviewers but has no path for GitHub Copilot. Copilot can review a PR natively via the GitHub API (it is already a collaborator on the repository when the Copilot for Business/Enterprise subscription is active). Adding it as an advisory panel member broadens the reviewer pool without requiring a new CLI or a new subscription tier, and it produces a machine-readable review record in the PR's review thread.

---

## 2. Scope

This spec covers exactly what `run_panel.sh` must do to:

1. Request a Copilot review on the open PR
2. Poll until Copilot posts its review or a timeout elapses
3. Parse the review verdict and feed it into the arbiter as a named finding source
4. Record the event in the token-usage ledger (as a review event, not a token count)
5. Update `panel-context.md` with the Copilot outcome
6. Exclude Copilot's approval from ever satisfying the human-approval gate

Nothing in this spec changes the arbiter logic, the sign-off register schema, or the second-review tier.

---

## 3. Requirements

### 3.1 Risk Gating

**REQ-255-01.** The Copilot reviewer step MUST be invoked if and only if the resolved risk tier for the current panel run is MEDIUM, HIGH, or CRITICAL (i.e., `rank(RISK) >= 1` using the existing `rank()` helper). LOW-tier runs skip the Copilot step entirely, even when a LOW-tier run is executing under a random red-team audit selection.

**REQ-255-02.** The risk tier used to gate Copilot invocation is the same resolved `$RISK` value the panel already computes from the triage phase. No separate risk read is needed. The existing triage result is authoritative.

**REQ-255-03.** When `$RISK` is LOW, `run_panel.sh` MUST log a `skip` line noting that Copilot review is omitted at LOW tier, and MUST NOT make any GitHub API call to request a Copilot review.

### 3.2 Invocation

**REQ-255-04.** The Copilot review request MUST be issued using:

```
gh api repos/{owner}/{repo}/pulls/{PR}/requested_reviewers \
  --method POST --field 'reviewers[]=copilot'
```

where `{owner}`, `{repo}`, and `{PR}` resolve to the current repository and PR number. The `{owner}/{repo}` shorthand MUST use the `{owner}/{repo}` form that `gh api` resolves from the authenticated context, consistent with how `run_panel.sh` already calls `gh api repos/{owner}/{repo}/pulls/$PR/comments`.

**REQ-255-05.** The invocation step MUST be placed in `run_panel.sh` immediately after the second-review verdict is consumed (currently after the triage phase and before the reviewer fan-out loop). Copilot review runs in parallel with, not after, the agy/codex fan-out — the polling loop (REQ-255-07) executes while the rest of the roster is being collected.

**REQ-255-06.** If the `gh api` request-reviewer call fails (non-zero exit, HTTP 4xx/5xx, or Copilot not installed on the repository), the script MUST:
  - Emit a `warn` line stating Copilot review could not be requested and the reason (HTTP status if available)
  - Set the Copilot verdict to `SKIPPED`
  - Continue without blocking the rest of the panel (fail-open)

### 3.3 Polling

**REQ-255-07.** After requesting the Copilot review, `run_panel.sh` MUST poll for the Copilot review result using:

```
gh pr reviews $PR --json author,state,submittedAt
```

filtered to entries where `author.login` matches `copilot[bot]` (case-insensitive).

**REQ-255-08.** The polling interval MUST be 30 seconds. The polling ceiling MUST be 5 minutes (10 polls maximum). Both values MUST be overridable by environment variables `COPILOT_POLL_INTERVAL_SEC` (default 30) and `COPILOT_POLL_TIMEOUT_SEC` (default 300), consistent with the existing `OVERSIGHT_SAMPLE_LOW/MED` tunable pattern.

**REQ-255-09.** If a Copilot review appears before the ceiling is reached, polling MUST stop immediately upon detection of any review entry with state `APPROVED`, `CHANGES_REQUESTED`, or `COMMENTED`.

**REQ-255-10.** If the ceiling elapses with no Copilot review posted, the script MUST:
  - Emit a `warn` line stating the Copilot review did not arrive within the timeout
  - Set the Copilot verdict to `TIMEOUT`
  - Continue without blocking the rest of the panel (fail-open)

**REQ-255-11.** Polling MUST NOT block the posting of agy/codex findings. The polling loop executes after the fan-out roster loop completes and before the arbiter step, so agy/codex reviews proceed without waiting for the Copilot poll.

### 3.4 Verdict Parsing

**REQ-255-12.** The Copilot review state from the GitHub reviews API MUST be mapped to the panel's verdict vocabulary as follows:

| GitHub review state | Panel verdict | Arbiter treatment |
|---|---|---|
| `APPROVED` | `copilot:approved` | Noted in summary; no finding emitted |
| `CHANGES_REQUESTED` | `copilot:changes_requested` | Treated as a named finding source; body text extracted and added to `ALL_FINDINGS` as reviewer=`copilot`, lens=`general` |
| `COMMENTED` | `copilot:commented` | Treated as advisory; body text extracted and added to `ALL_FINDINGS` as reviewer=`copilot`, lens=`general` |
| `DISMISSED` | `copilot:dismissed` | Treated as `SKIPPED`; noted in summary |
| Timeout | `copilot:timeout` | Noted in summary; no finding emitted |
| Skipped (bot not installed / request failed) | `copilot:skipped` | Noted in summary; no finding emitted |

**REQ-255-13.** When the Copilot review state is `CHANGES_REQUESTED` or `COMMENTED`, the review body text MUST be extracted from the API response and injected into `ALL_FINDINGS` as a single finding entry with:
  - `reviewer`: `"copilot"`
  - `lens`: `"general"`
  - `severity`: `"tier2"` for `CHANGES_REQUESTED`; `"tier3"` for `COMMENTED`
  - `title`: first 80 characters of the review body (stripped of leading whitespace)
  - `detail`: full review body
  - `file`, `line`, `end_line`: omitted (or zero) — Copilot review comments on specific lines are NOT individually parsed in this release; only the top-level review verdict and body are consumed

**REQ-255-14.** The Copilot verdict string MUST be stored in a shell variable `COPILOT_VERDICT` for use in the summary comment and `panel-context.md` update.

### 3.5 Arbiter Integration

**REQ-255-15.** The Copilot finding (when present) MUST be appended to `ALL_FINDINGS` before the arbiter step executes, using the same `jq -cn '$a + $b'` merge pattern the existing reviewer loop uses. The arbiter synthesizes it as any other reviewer output — it deduplicates, weighs severity, and writes the summary.

**REQ-255-16.** The arbiter receives Copilot findings as `reviewer="copilot"` entries. The arbiter MUST NOT give Copilot findings higher or lower inherent weight than agy or codex findings. The arbiter's existing deduplication and severity-weighting logic applies unchanged.

**REQ-255-17.** A `REQUEST_CHANGES` verdict from Copilot alone MUST NOT block the panel from completing or the PR from proceeding. It is advisory input to the arbiter, consistent with how any other reviewer's findings are advisory (the human and the branch policy gate are the merge blockers).

### 3.6 Panel Summary Comment

**REQ-255-18.** The panel summary comment posted to the PR (`## Oversight panel — verdict`) MUST include a Copilot line in the Reviewers section. Format:

- If Copilot ran: `Copilot: {verdict}` (e.g., `Copilot: CHANGES_REQUESTED`, `Copilot: APPROVED`)
- If Copilot timed out: `Copilot: TIMEOUT (no review within 5 min)`
- If Copilot was skipped (LOW tier or install failure): `Copilot: SKIPPED ({reason})`

**REQ-255-19.** The existing roster line in the summary (`Reviewers: ${ROSTER[*]}`) MUST be supplemented with the Copilot status. Copilot MUST NOT be added to the `$ROSTER` array (which drives the fan-out loop); it is reported separately because it is invoked via a different mechanism (GitHub API, not a vendor CLI).

### 3.7 panel-context.md Update

**REQ-255-20.** The oversight-orchestrator agent produces `step{N}-panel-context.md`. After the Copilot verdict is known, `run_panel.sh` MUST append a Copilot section to that file (in-place, after the panel completes but before the summary comment is posted). The appended section MUST contain:

```
## Copilot Review
Requested: {ISO-8601 timestamp}
Verdict: {copilot:approved | copilot:changes_requested | copilot:commented | copilot:timeout | copilot:skipped}
Notes: {one sentence — e.g. "Review posted 42s after request." or "Timed out after 300s." or "Copilot not installed on this repository."}
```

**REQ-255-21.** If `panel-context.md` does not exist (orchestrator did not produce it), the Copilot section MUST be written to `$RUN_DIR/copilot-verdict.txt` instead. The warn-and-continue behavior for missing `panel-context.md` already in the script is unchanged.

### 3.8 BOT_ACCOUNTS — Human-Approval Gate

**REQ-255-22.** The string `copilot[bot]` MUST be appended to the `BOT_ACCOUNTS` variable in `scripts/framework/machine-accounts.env`. The existing space-separated format is used:

```
BOT_ACCOUNTS="${BOT_WORKER_USERNAME} ${BOT_OVERSEER_USERNAME} copilot[bot]"
```

**REQ-255-23.** `require_human_approval.py` (and any other script that reads `BOT_ACCOUNTS`) MUST treat `copilot[bot]` as a bot identity. A PR review from `copilot[bot]` with state `APPROVED` MUST NOT count toward the human-approval requirement on protected branches, regardless of risk tier.

**REQ-255-24.** The comment in `machine-accounts.env` above `BOT_ACCOUNTS` MUST be updated to note that `copilot[bot]` is included and why (it is a GitHub-native AI reviewer whose approval must not satisfy the human gate).

### 3.9 token_tracker.py Extension

**REQ-255-25.** Copilot usage MUST be recorded in the token-usage ledger as a review event, not as a token count. The record schema for a Copilot event is:

```json
{
  "ts": "<ISO-8601>",
  "vendor": "copilot",
  "stage": "panel",
  "step": <step number or 0 if unknown>,
  "prompt_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "estimated": false,
  "review_event": true,
  "outcome": "approved | changes_requested | commented | timeout | skipped"
}
```

The `prompt_tokens`, `output_tokens`, and `total_tokens` fields MUST be recorded as `0` because Copilot reviews are not token-based from the HOS perspective. The `review_event: true` field distinguishes this record from token-consumption records. The `outcome` field is mandatory.

**REQ-255-26.** `token_tracker.py` MUST accept a new `--review-event` flag on the `record` subcommand. When `--review-event` is passed, `prompt_chars` and `output_chars` are not required; `--outcome` is required. The resulting ledger entry MUST conform to the schema in REQ-255-25.

**REQ-255-27.** The `report` subcommand of `token_tracker.py` MUST display Copilot events in the "By vendor" section as `copilot (review events: N)` rather than a token count. Token totals for Copilot MUST be shown as `0` or omitted from the token subtotal.

**REQ-255-28.** `run_panel.sh` MUST call `token_tracker.py record --vendor copilot --stage panel --review-event --outcome {verdict}` immediately after the Copilot verdict is determined (whether `approved`, `changes_requested`, `commented`, `timeout`, or `skipped`).

### 3.10 Failure Modes (Summary)

| Failure | Behavior | Blocking? |
|---|---|---|
| `gh api` request-review call fails (any reason) | warn + set verdict=SKIPPED + continue | No |
| Copilot not installed on repository (HTTP 422 or reviewer not accepted) | warn + set verdict=SKIPPED + continue | No |
| No review posted within timeout ceiling | warn + set verdict=TIMEOUT + continue | No |
| `gh pr reviews` API unavailable during poll | warn on each failed poll attempt; if ceiling reached → TIMEOUT | No |
| `token_tracker.py` record call fails | warn; do not abort | No |

All failure modes are fail-open, consistent with how the panel handles missing agy/codex CLIs.

---

## 4. Acceptance Criteria

**AC-01.** At MEDIUM+ risk, `run_panel.sh` issues exactly one `POST` to the GitHub requested-reviewers API per panel run, targeting `reviewers[]=copilot`.

**AC-02.** At LOW risk (not in a red-team audit), no GitHub API call for a Copilot review is made, and the log contains a `skip` line mentioning Copilot.

**AC-03.** When Copilot posts `CHANGES_REQUESTED`, a finding with `reviewer=copilot` and `severity=tier2` appears in `ALL_FINDINGS` and is processed by the arbiter. The arbiter summary includes the Copilot finding. The panel does not abort.

**AC-04.** When Copilot posts `APPROVED`, no finding is added to `ALL_FINDINGS`, and the summary comment includes `Copilot: APPROVED`.

**AC-05.** When the 5-minute ceiling elapses without a Copilot review, the script emits a `warn` line, sets verdict to `TIMEOUT`, continues to the arbiter and summary-posting steps, and the summary comment includes `Copilot: TIMEOUT`.

**AC-06.** `copilot[bot]` is present in `BOT_ACCOUNTS` in `machine-accounts.env`. A simulated approval from `copilot[bot]` is rejected by `require_human_approval.py` as a non-human approval.

**AC-07.** After a panel run (any outcome), exactly one Copilot event record appears in `token-usage.jsonl` with `"review_event": true`, `"vendor": "copilot"`, and an `"outcome"` field matching the actual verdict.

**AC-08.** `panel-context.md` (or `$RUN_DIR/copilot-verdict.txt` if `panel-context.md` is absent) contains a `## Copilot Review` section with `Requested`, `Verdict`, and `Notes` fields populated.

**AC-09.** A dry-run (`--dry-run`) panel execution does NOT post a review request to GitHub and does NOT poll; it prints what would have been requested and exits cleanly.

**AC-10.** The polling interval and ceiling are overridable via `COPILOT_POLL_INTERVAL_SEC` and `COPILOT_POLL_TIMEOUT_SEC` environment variables. Setting both to low values in a test environment causes the poll to exhaust quickly and report TIMEOUT.

---

## 5. Out of Scope

- Parsing individual Copilot line-level review comments (only the top-level review verdict and body are consumed; line comments are left to the human to read in the PR UI)
- Configuring or installing the GitHub Copilot for Business/Enterprise subscription — this is a pre-condition, not something `run_panel.sh` manages
- Changing the arbiter's weighting logic — Copilot findings enter as equal-weight advisory input
- Adding Copilot to the second-review tier (`run_second_review.sh`) — position is panel only, per decisions already made
- Changing the branch protection rules — human approval remains required as governed by `require_human_approval.py` and the existing branch policy

---

## 6. Pre-conditions

**PRE-01.** The repository has GitHub Copilot for Business or Enterprise enabled and the Copilot bot has been added as a reviewer collaborator (this is a GitHub-side configuration step, outside HOS).

**PRE-02.** `gh` is authenticated with a token that has `pull_requests:write` scope (already required by the existing panel for posting comments).

**PRE-03.** `jq` and `python3` are on the PATH (already required by the existing panel).

If PRE-01 is not met, the request-reviewer call will fail and the Copilot step degrades to SKIPPED per REQ-255-06.
