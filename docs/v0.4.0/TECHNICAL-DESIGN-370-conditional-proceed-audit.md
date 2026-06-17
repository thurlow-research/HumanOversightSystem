# Technical Design — Issue #370: CONDITIONAL_PROCEED PR Audit Script

**Status:** For implementation — architect GO
**Step:** v0.4.0
**Author:** technical-design agent
**Spec:** `docs/specs/SPEC-370-conditional-proceed-audit.md`
**Date:** 2026-06-16

RISK: LOW | CONFIDENCE: HIGH | Change class: additive

---

## Architect bindings (binding)

| # | Binding |
|---|---|
| B1 | Report only — no auto-filing of issues, no PR modification. |
| B2 | Multi-event PRs: anchor the heuristic to the **earliest** CONDITIONAL_PROCEED timestamp (resolves OQ-3). |
| B3 | Human reply = any non-bot comment after the anchor timestamp: `user.type != "Bot"` AND author not in the bot-account set. Include `github-actions[bot]` in the exclusion set. Use `gh api` to fetch and verify comment authors. |
| B4 | `jq` is a dependency (already used by oversight scripts) — add a startup check, exit non-zero if absent. |
| B5 | Add `--log <path>` optional override; default `<repo-root>/audit/oversight-log.jsonl` (resolves OQ-1). |

---

## Component map

| # | Artifact | Type |
|---|---|---|
| A | `scripts/oversight/audit_conditional_proceed.sh` | new script |

No other files touched. No unit tests required (`bash -n` is the gate per task).
The script is read-only against the audit log (R5) and makes no writes to GitHub (B1).

---

## CLI surface

```
audit_conditional_proceed.sh [--log <path>] [--help]
```

- `--log <path>` — override the audit-log path (B5). Default: `$REPO_ROOT/audit/oversight-log.jsonl`.
- `--help` / `-h` — usage and exit 0.
- Repo root via `git rev-parse --show-toplevel` (spec §3).

### Environment overrides (R3 / AC-8)

| Var | Default | Use |
|---|---|---|
| `OVERSIGHT_ACCOUNT` | `HOSOversightTutelare` | overseer bot login to exclude |
| `WORKER_ACCOUNT` | `HOSWorkerTutelare` | worker bot login to exclude |
| `GH_API_DELAY_MS` | `200` | inter-PR API delay (R4) |

Resolved account names are printed at startup (R3 / AC-8). The exclusion set is:
`{ $OVERSIGHT_ACCOUNT, $WORKER_ACCOUNT, "github-actions[bot]" }` plus any comment
whose `user.type == "Bot"` (B3).

---

## Prerequisite checks (R1 / AC-1, AC-2, B4) — fail-closed before any processing

1. `command -v jq` — else `die` "jq not found" (B4).
2. `command -v gh` — else `die` "gh CLI not found".
3. `git rev-parse --show-toplevel` succeeds — else `die` "not in a git repo".
4. Log file exists at resolved path — else `die` "audit log not found: <path>".
5. `gh auth status` exits 0 — else `die` "gh not authenticated".

Any failure → print clear message, exit non-zero, do not partially run (R1).

---

## Processing pipeline

### Step A — Parse CONDITIONAL_PROCEED events (spec §4.A, R2)

Read the log line by line with `jq` (B4). Select objects where:
- `.event` matches `CONDITIONAL_PROCEED` case-insensitively
  (`(.event // "" | ascii_downcase) == "conditional_proceed"`).
- `.pr_number` present and non-empty.

`jq` filter emits TSV: `pr_number \t timestamp \t conditional_items_count`.

- `conditional_items` tolerance (R2): use
  `(.conditional_items | if . == null then 0 elif type=="array" then length else 0 end)`.
  Absent / null / empty array → `0`, rendered later as "not logged". Never crash.
- Malformed JSON lines: `jq -c '. as $x | ...'` per line behind `|| continue` so a bad
  line is skipped, not fatal (consistent with R6 "continue per-PR on error").

**Aggregation (B2 — earliest anchor):** group candidate rows by `pr_number`; for each PR
retain the **minimum** timestamp (ISO-8601 lexical sort is chronological for UTC `Z`
stamps) as the anchor, and the items count from that earliest event. Implemented by
sorting the TSV by pr then timestamp and taking the first row per PR (`sort` + `awk`
first-seen).

`N` = total CONDITIONAL_PROCEED log lines (events, pre-dedup) for the report header.

### Step B — Merged status (spec §4.B / AC-4)

Per candidate PR, `gh api "repos/{owner}/{repo}/pulls/<pr>" --jq '.merged'`.
- `true` → merged, proceed to Step C.
- `false` / closed-without-merge / not found (`gh` non-zero) → STATUS `NO_MERGE`,
  output row "no / SKIPPED — NOT MERGED", skip Step C.
- The `{owner}/{repo}` slug comes from `gh repo view --json nameWithOwner -q .nameWithOwner`.

### Step C — Human-actioning heuristic (spec §4.C, B2, B3)

For each merged PR, fetch issue comments AND review comments via `gh api` (paginated):
`gh api "repos/{slug}/issues/<pr>/comments" --paginate`.

For each comment evaluate (B3):
- `created_at > anchor_timestamp` (strict after the earliest CP event).
- `user.type != "Bot"`.
- `user.login` ∉ `{ $OVERSIGHT_ACCOUNT, $WORKER_ACCOUNT, "github-actions[bot]" }`.

A single `jq` expression over the comments array returns the count of qualifying comments:

```
jq --arg ts "$anchor" --argjson bots "$BOTS_JSON" '
  [ .[] | select(.created_at > $ts)
        | select(.user.type != "Bot")
        | select(.user.login as $l | ($bots | index($l)) | not) ]
  | length'
```

- count ≥ 1 → `LIKELY_ACTIONED`.
- count == 0 → `NEEDS_REVIEW`.
- `gh api` error / 429 → `warn` and STATUS `UNKNOWN` for that PR (R4), continue.

**Rate limiting (R4):** sleep `GH_API_DELAY_MS` ms between per-PR iterations
(`sleep "$(awk "BEGIN{print $GH_API_DELAY_MS/1000}")"`). On HTTP 429 (detected via
`gh api` stderr / non-zero), warn and mark the PR `UNKNOWN` rather than crashing.

### Step D — Report (spec §4.D / AC-7)

Per task, output is **tab-separated**: `PR_NUMBER \t STATUS \t DETAILS` where STATUS ∈
`{LIKELY_ACTIONED, NEEDS_REVIEW, NO_MERGE, UNKNOWN}`. DETAILS carries the human-readable
context (merged flag, qualifying-comment count or reason, conditional-items count or
"not logged").

A header, a column legend, and the summary block from spec §4.D framing are printed
around the TSV rows. The report is written to **stdout** and to
`.claudetmp/audit/conditional_proceed_audit_<ISO-8601-date>.txt` (mkdir -p; same-day
re-run overwrites, R7 / AC-7).

Summary block: total CP events (N), merged PRs examined, NEEDS_REVIEW count,
LIKELY_ACTIONED count, plus the "heuristic — manually verify" NOTE (spec §4.D).

---

## Exit codes (R6 / AC-10)

- `0` — script ran to completion, including when `NEEDS_REVIEW` PRs exist (findings are
  human work items, not script failures), and including when zero CP events are found.
- non-zero — only a prerequisite failure (missing jq / gh / log / auth / not-a-repo) or
  an unrecoverable error. Per-PR API failures degrade to `UNKNOWN` and keep exit 0.

---

## Boundaries

- **Read-only** against `audit/oversight-log.jsonl` — no append/modify/truncate (R5 / AC-9).
- **No** issue filing, **no** PR reopen/close/modify, **no** posting review threads (B1, §6).
- Heuristic is explicitly non-definitive — output labels it as heuristic and instructs
  manual verification for `NEEDS_REVIEW` (spec §4.C, §4.D NOTE).
- Anchor is the **earliest** CP event per PR (B2) — never the most recent.
- Out of scope: audit logs larger than shell-pipeline memory (§6).

---

## Acceptance trace

| AC | Satisfied by |
|---|---|
| AC-1 | prereq check 4 (log exists) |
| AC-2 | prereq check 5 (`gh auth status`) |
| AC-3 | Step A jq selection over all lines |
| AC-4 | Step B `gh api .merged` |
| AC-5 | Step C count == 0 → NEEDS_REVIEW |
| AC-6 | Step C count ≥ 1 → LIKELY_ACTIONED |
| AC-7 | Step D stdout + `.claudetmp/audit/` file |
| AC-8 | env overrides + startup print |
| AC-9 | read-only; no write path to the log |
| AC-10 | exit 0 with NEEDS_REVIEW present |
| AC-11 | `bash -n` |
