# Technical Design — GitHub Copilot as Panel Oversight Reviewer

**Document type:** Technical design (coder-ready)
**Status:** Draft — awaiting architect review
**Spec:** `docs/specs/SPEC-255-copilot-panel-integration.md`
**Issue:** #255
**Author:** technical-design
**Date:** 2026-06-16

---

## Self-flag (HOS authoring protocol)

**RISK:** MEDIUM — modifies `run_panel.sh` (the outer-loop release-gate panel), the
`require_human_approval.py` bot-identity set, `machine-accounts.env`, and `token_tracker.py`. The
panel is on the release path; a regression here affects the merge gate. The change is **additive and
fail-open** (every Copilot failure mode degrades to SKIPPED/TIMEOUT and continues), and Copilot's
verdict is **advisory** (equal weight to agy/codex; never a sole blocker). The one safety-critical
edge — Copilot's approval must never satisfy the human-approval gate — is handled by adding
`copilot[bot]` to `BOT_ACCOUNTS`, which **strengthens** the gate (one more identity excluded from
counting as human). This change makes the human gate stricter, never looser.

**CONFIDENCE:** HIGH on the arbiter integration, the `BOT_ACCOUNTS` change, and the audit/token
schemas (all directly specified). MEDIUM on the exact GitHub Copilot reviewer-request API surface
(O-1: `gh api … requested_reviewers` with `reviewers[]=copilot` vs. a `copilot[bot]` slug — the
accepted reviewer identifier is GitHub-side and version-dependent) and on Copilot's review `state`
vocabulary mapping (O-2).

**BLAST RADIUS:** `scripts/run_panel.sh` (one new function + one gated call + summary/context
append), `scripts/framework/machine-accounts.env` (one line + comment),
`scripts/framework/require_human_approval.py` (BOT_ACCOUNTS already env-sourced — see §6, likely
**no code change**), `scripts/oversight/token_tracker.py` (`--review-event` + `--outcome` flags,
review-event ledger path, report rendering). No change to the arbiter's weighting/dedup logic, the
sign-off register, the second-review tier, or branch protection.

**Change classification:** `additive`. No `structural` change. No new human gate introduced by the
authoring protocol beyond standard architect review; the change tightens an existing human gate.

---

## Reconciliation note — task brief vs. spec vs. actual script

The task brief uses variable names `OWNER`, `REPO`, `PR_NUMBER`, `TIER_RANK`, `MEDIUM_RANK` and a
parallel-vs-sequential framing. The **actual `run_panel.sh`** uses `PR`, `RISK`, and the `rank()`
helper (`LOW=0 MEDIUM=1 HIGH=2 CRITICAL=3`); there is no `OWNER`/`REPO` variable (the script uses
`gh api repos/{owner}/{repo}/…`, letting `gh` resolve owner/repo from auth context — see existing
`post_thread`, L457). The **spec (REQ-255-*)** matches the actual script. **This design follows the
spec and the actual script:** gating is `rank(RISK) >= 1`; the API uses the `{owner}/{repo}`
placeholder form `gh` resolves; the function takes `pr_number` only. Where the task brief and spec
diverge on timing (brief §"Timing": sequential after both fan-outs; spec REQ-255-05/11: request
Copilot, then run fan-out, then poll after the fan-out roster completes), **the spec governs** — the
request is issued before the fan-out and the poll runs after it, which is functionally the
"request → other work → poll" sequence the brief intends (the request and the fan-out overlap; only
the poll is sequential-after). See §2 for the exact placement.

---

## Component map

| Component | Type | New / Changed | Section |
|---|---|---|---|
| `request_copilot_review(pr_number)` | new bash function in `run_panel.sh` | new | §2 |
| Risk-gated Copilot call | inserted after triage, before fan-out | new | §3.1 |
| `COPILOT_VERDICT` shell var | panel state | new | §3.x |
| `COPILOT_POLL_INTERVAL_SEC` / `COPILOT_POLL_TIMEOUT_SEC` | env tunables | new | §3.2 |
| Copilot finding → `ALL_FINDINGS` | arbiter feed | new | §4 |
| Summary-comment Copilot line | `## Oversight panel — verdict` | changed | §5 |
| `panel-context.md` Copilot section append | post-verdict write | new | §6 |
| `COPILOT_BOT_LOGIN` / `BOT_ACCOUNTS` | `machine-accounts.env` | changed | §7 |
| `require_human_approval.py` BOT_ACCOUNTS load | bot-identity set | confirm (likely no change) | §7.2 |
| `token_tracker.py` `--review-event` / `--outcome` | record path + report | changed | §8 |

---

## §1 — Resolved decisions (from the issue, carried as design constraints)

- **Position:** panel (release gate) only. Not added to `run_second_review.sh` (out of scope).
- **Trigger:** `POST /repos/{owner}/{repo}/pulls/{n}/requested_reviewers` with reviewer `copilot`.
- **Gating:** MEDIUM+ only (`rank(RISK) >= 1`). LOW skips entirely (REQ-255-01/03).
- **Timing:** request issued before the fan-out roster loop; poll after the roster loop, before the
  arbiter (REQ-255-05/11). Sequential poll, fail-open.
- **Poll:** 30 s interval, 300 s ceiling (10 polls), both env-overridable (REQ-255-08).
- **Verdict weight:** advisory, equal to agy/codex; never a sole blocker (REQ-255-16/17).
- **Human gate:** `copilot[bot]` in `BOT_ACCOUNTS`; its `APPROVED` never satisfies the human gate
  (REQ-255-22/23).
- **Cost model:** per-call; sequential poll is correct (wall-clock irrelevant).

---

## §2 — `request_copilot_review()` — function contract

**Signature (bash):**
```
request_copilot_review() {   # $1 = PR number
   # echoes the resolved Copilot verdict token to stdout:
   #   APPROVED | CHANGES_REQUESTED | COMMENTED | DISMISSED | TIMEOUT | SKIPPED
   # side effects: sets nothing global directly (caller captures stdout into COPILOT_VERDICT)
   #               + may write review body to a temp file for the finding extractor (see §4)
}
```

The function takes only the PR number (consistent with the script's owner/repo-via-`gh` pattern; no
`OWNER`/`REPO` args — the task brief's `(owner, repo, pr_number)` signature does not match the
script, which resolves owner/repo through `gh`). It returns the **verdict token** on stdout. The
caller assigns `COPILOT_VERDICT="$(request_copilot_review "$PR")"`.

### 2.1 Request step (REQ-255-04, REQ-255-06)

```
gh api "repos/{owner}/{repo}/pulls/$1/requested_reviewers" \
  --method POST --field 'reviewers[]=copilot' \
  >/dev/null 2>>"$RUN_DIR/errors.log"
```
- On non-zero exit / HTTP 4xx/5xx / Copilot-not-installed (notably HTTP 422 when the reviewer is not
  accepted): `warn "Copilot review could not be requested (HTTP <status if known>)"`, set verdict
  `SKIPPED`, record the token event (§8), and **return `SKIPPED` immediately** — no polling
  (REQ-255-06, fail-open). Capture the HTTP status from `gh api`'s stderr where available; if not
  parseable, omit it from the warn line.
- Under `--dry-run` (`DRY_RUN=1`): print
  `[dry-run] would POST requested_reviewers reviewers[]=copilot to PR #$1`, do **not** call the API,
  do **not** poll, return `SKIPPED` (AC-09). The token event is still recorded with outcome
  `skipped` so the dry-run is observable, OR skipped entirely — **recommend recording with
  `outcome=skipped`** so AC-07's "exactly one event per run" holds even in dry-run; flag O-3.

> **O-1 (architect):** the exact accepted reviewer identifier for Copilot in the
> `requested_reviewers` API is GitHub-side. The spec (REQ-255-04) and the resolved decision specify
> `reviewers[]=copilot`. If GitHub requires the bot slug form, this is a one-token change. The
> fail-open path (SKIPPED on 422) means a wrong identifier degrades gracefully, not fatally —
> acceptable for v1. Confirm the identifier against a live repo before merge (PRE-01).

### 2.2 Polling loop (REQ-255-07/08/09/10)

```
local _interval="${COPILOT_POLL_INTERVAL_SEC:-30}"
local _ceiling="${COPILOT_POLL_TIMEOUT_SEC:-300}"
local _elapsed=0
local _state=""
while (( _elapsed < _ceiling )); do
  sleep "$_interval"
  _elapsed=$(( _elapsed + _interval ))
  # poll; tolerate a failed poll (warn, keep looping until ceiling — REQ-255 failure table)
  _reviews="$(gh pr reviews "$1" --json author,state,submittedAt,body 2>>"$RUN_DIR/errors.log" || echo '[]')"
  _state="$(printf '%s' "$_reviews" | jq -r '
      [ .[] | select((.author.login // "") | ascii_downcase | test("copilot\\[bot\\]")) ]
      | sort_by(.submittedAt) | last | .state // empty')"
  case "$_state" in
    APPROVED|CHANGES_REQUESTED|COMMENTED|DISMISSED) break ;;   # REQ-255-09
    *) : ;;                                                    # keep polling
  esac
done
```
- Detection (REQ-255-07): filter reviews to `author.login` matching `copilot[bot]`
  case-insensitively. The jq `test("copilot\\[bot\\]")` on the lowercased login covers
  `copilot[bot]` and the spec's case-insensitive requirement. (Belt-and-braces against a future
  `user.type=="Bot"` shape: the task brief also mentions `review.user.type == "Bot"` with login
  containing "copilot"; `gh pr reviews` exposes `author.login`, not `user.type`, so the login match
  is authoritative for this API. See O-2.)
- Latest-wins: sort by `submittedAt`, take the last Copilot review (a re-review supersedes an earlier
  state).
- A failed individual poll (`gh pr reviews` errors): the `|| echo '[]'` keeps the loop alive; the
  ceiling still governs (REQ-255 failure table: "warn on each failed poll; if ceiling reached →
  TIMEOUT"). Add `warn "Copilot poll attempt failed (will retry)"` on the error branch.
- **Timeout (REQ-255-10):** if the loop exits with no terminal `_state`,
  `warn "Copilot review timed out after $_ceiling seconds — continuing without it"`, set verdict
  `TIMEOUT`, return `TIMEOUT`. (The task brief's literal "after 5 minutes" message is rendered from
  the resolved `$_ceiling` so the env override stays truthful — AC-05/AC-10.)

### 2.3 Verdict mapping (REQ-255-12)

| GitHub `state` | Returned token | `COPILOT_VERDICT` | Finding emitted? |
|---|---|---|---|
| `APPROVED` | `APPROVED` | `copilot:approved` | no |
| `CHANGES_REQUESTED` | `CHANGES_REQUESTED` | `copilot:changes_requested` | yes (tier2, §4) |
| `COMMENTED` | `COMMENTED` | `copilot:commented` | yes (tier3, §4) |
| `DISMISSED` | `DISMISSED` | `copilot:dismissed` | no (treated as SKIPPED in summary) |
| timeout | `TIMEOUT` | `copilot:timeout` | no |
| request failed / not installed / dry-run | `SKIPPED` | `copilot:skipped` | no |

The function returns the **uppercase token**; the caller derives the `copilot:<lower>` form for the
summary and `panel-context.md`. On `CHANGES_REQUESTED`/`COMMENTED` the function also writes the
review **body** to `$RUN_DIR/copilot-review-body.txt` so §4's finding extractor can read it without
re-querying the API.

---

## §3 — Placement and risk gating in `run_panel.sh`

### 3.1 Where the call goes (REQ-255-05)

Insert immediately **after** the triage block computes `$RISK` and the red-team sampling resolves
(after L341 `info "roster (…)"`, before the fan-out `for spec in "${ROSTER[@]}"` loop at L402). The
request is issued here so it overlaps the fan-out; the **poll** is invoked after the fan-out roster
loop completes (after L420, before the arbiter at L423). Split the function so the request fires
early and the poll runs late — OR (simpler, and acceptable given the per-call cost model and
fail-open semantics) call the **whole** `request_copilot_review` after the fan-out, immediately
before the arbiter. **Recommend the simple form:** one call after the fan-out, before the arbiter.
Rationale: the per-call cost model makes wall-clock irrelevant (resolved decision), the fan-out is
synchronous bash anyway (no true parallelism to exploit), and a single call site is far less
error-prone than a split request/poll. Flag O-4 for the architect; if true overlap is required, split
into `request_copilot_review_async` (POST only) before the loop and `poll_copilot_review` after.

Gating (REQ-255-01/02/03):
```
COPILOT_VERDICT="copilot:skipped"
if (( DRY_RUN == 0 || 1 )) ; then : ; fi   # (dry-run handled inside the function)
if [[ "$(rank "$RISK")" -ge 1 ]]; then
  _cv_token="$(request_copilot_review "$PR")"
  COPILOT_VERDICT="copilot:$(printf '%s' "$_cv_token" | tr '[:upper:]' '[:lower:]')"
else
  skip "Copilot review omitted at LOW tier (panel reviewer floor not reached)"
  COPILOT_VERDICT="copilot:skipped"
fi
```
At LOW tier this emits a `skip` line and makes **no** GitHub API call (AC-02). Note the panel itself
already returns early for LOW-not-sampled (L321–325); the Copilot block is only reached when the
panel runs, and the `rank(RISK) >= 1` guard additionally skips Copilot for a **sampled LOW** run
(REQ-255-01: LOW skips Copilot even under red-team selection).

### 3.2 Tunables (REQ-255-08)

Add near the existing `SAMPLE_LOW`/`SAMPLE_MED` tunables (L68):
```
COPILOT_POLL_INTERVAL_SEC="${COPILOT_POLL_INTERVAL_SEC:-30}"   # poll cadence for the Copilot review
COPILOT_POLL_TIMEOUT_SEC="${COPILOT_POLL_TIMEOUT_SEC:-300}"    # ceiling (10 polls @ 30s)
```
Both consumed inside `request_copilot_review` (§2.2). Setting both low (AC-10) exhausts the loop
quickly and yields `TIMEOUT`.

---

## §4 — Arbiter integration (REQ-255-13/15/16/17)

After `request_copilot_review` returns, build the Copilot finding (only for
`CHANGES_REQUESTED`/`COMMENTED`) and merge it into `ALL_FINDINGS` **before** the arbiter step (L423),
using the same `jq` merge the roster loop uses (L418).

```
if [[ "$_cv_token" == "CHANGES_REQUESTED" || "$_cv_token" == "COMMENTED" ]]; then
  _cbody="$(cat "$RUN_DIR/copilot-review-body.txt" 2>/dev/null || echo '')"
  _csev="tier3"; [[ "$_cv_token" == "CHANGES_REQUESTED" ]] && _csev="tier2"
  _ctitle="$(printf '%s' "$_cbody" | sed -e 's/^[[:space:]]*//' | head -c 80)"
  _cfinding="$(jq -cn --arg t "$_ctitle" --arg d "$_cbody" --arg s "$_csev" \
     '[{reviewer:"copilot", lens:"general", severity:$s, title:$t, detail:$d,
        file:"", line:0, end_line:0, suggestion:""}]')"
  ALL_FINDINGS="$(jq -cn --argjson a "$ALL_FINDINGS" --argjson b "$_cfinding" '$a + $b')"
fi
```

Finding shape (REQ-255-13):
- `reviewer`: `"copilot"`; `lens`: `"general"`.
- `severity`: `tier2` for CHANGES_REQUESTED, `tier3` for COMMENTED.
- `title`: first 80 chars of the body, leading whitespace stripped.
- `detail`: full review body.
- `file`/`line`/`end_line`: empty/0 — line-level Copilot comments are **not** individually parsed in
  this release (Out of Scope). With `line=0`, the existing post loop folds the finding into the
  summary's "could not be anchored" block (L482), which is the correct unanchored treatment.

The arbiter (L423–451) processes this entry exactly like agy/codex output — same dedup, same
severity weighting, **no** Copilot-specific weight (REQ-255-16). A Copilot `CHANGES_REQUESTED` alone
does not block the panel or the PR (REQ-255-17): the panel always proceeds to post; merge-blocking is
governed by the human gate and branch policy, unchanged.

---

## §5 — Summary comment (REQ-255-18/19)

In the summary assembly (L489–496), the `Reviewers:` line must be supplemented with a Copilot status
**without** adding `copilot` to `$ROSTER` (REQ-255-19 — `$ROSTER` drives the fan-out loop; Copilot is
invoked via the GitHub API, not a vendor CLI). Render a Copilot status string from `$_cv_token`:

| token | summary line |
|---|---|
| APPROVED | `Copilot: APPROVED` |
| CHANGES_REQUESTED | `Copilot: CHANGES_REQUESTED` |
| COMMENTED | `Copilot: COMMENTED` |
| DISMISSED | `Copilot: SKIPPED (review dismissed)` |
| TIMEOUT | `Copilot: TIMEOUT (no review within 5 min)` |
| SKIPPED | `Copilot: SKIPPED (<reason>)` (LOW tier / not installed / request failed / dry-run) |

Append to `SUMMARY_BODY` after the `**Risk:** … **Reviewers:** …` line, e.g.:
```
SUMMARY_BODY="${SUMMARY_BODY/$'\n\n'/$'  ·  '"Copilot: ${_copilot_status}"$'\n\n'}"
```
(or, simpler and less fragile, add an explicit `**Copilot:** ${_copilot_status}` line beneath the
Reviewers line — **recommend** the explicit-line form to avoid string-surgery on `$SUMMARY_BODY`).
The `<reason>` for SKIPPED comes from why the function returned SKIPPED (LOW tier vs. request
failure); pass it back via a second stdout token or a global `COPILOT_SKIP_REASON` — recommend a
`COPILOT_SKIP_REASON` global set inside the function.

---

## §6 — `panel-context.md` update (REQ-255-20/21)

The orchestrator writes `.claudetmp/oversight/step{N}-panel-context.md` (the panel already globs for
it at L222–226). **After** the verdict is known and **before** the summary comment is posted, append:
```
## Copilot Review
Requested: <ISO-8601 timestamp>
Verdict: <copilot:approved | copilot:changes_requested | copilot:commented | copilot:dismissed | copilot:timeout | copilot:skipped>
Notes: <one sentence>
```
- `Requested` = the `date -u +%FT%TZ` captured at the moment the POST is issued (store in a global
  `COPILOT_REQUESTED_AT` inside the function).
- `Notes` examples: `"Review posted 42s after request."` / `"Timed out after 300s."` /
  `"Copilot not installed on this repository."` / `"Skipped at LOW tier."`
- Target file: the same `step{N}-panel-context.md` the panel resolved at startup (capture the matched
  path into a global when the L222–236 block runs; if none matched, REQ-255-21 applies).
- **REQ-255-21:** if no `panel-context.md` exists, write the `## Copilot Review` section to
  `$RUN_DIR/copilot-verdict.txt` instead. The existing warn-and-continue for a missing context file
  is unchanged (AC-08).

This append is gated on `DRY_RUN == 0` (dry-run posts/writes nothing to the PR; the context-file
append is a local write — recommend still skipping it under dry-run to keep dry-run side-effect-free,
consistent with how the summary is only printed, not posted, under dry-run).

---

## §7 — Human-approval gate (REQ-255-22/23/24)

### 7.1 `machine-accounts.env` (REQ-255-22/24)

Add the Copilot login and fold it into `BOT_ACCOUNTS`. Per the task brief, introduce a named var:
```
# copilot[bot] is GitHub's native AI reviewer. Its APPROVED review is advisory only and MUST NOT
# satisfy the human-approval gate — so it is a BOT identity here, never counted as human.
COPILOT_BOT_LOGIN="copilot[bot]"
BOT_ACCOUNTS="${BOT_WORKER_USERNAME} ${BOT_OVERSEER_USERNAME} ${COPILOT_BOT_LOGIN}"
```
This updates the existing `BOT_ACCOUNTS=` line (L22 of `machine-accounts.env`) and adds the comment
REQ-255-24 requires. The spec REQ-255-22 shows the literal `copilot[bot]` inline; the task brief asks
for the `COPILOT_BOT_LOGIN` indirection. **Use the `COPILOT_BOT_LOGIN` var** (task brief) — it is
the single source the token tracker / any future reader can reference, and it expands to the same
`copilot[bot]` string in `BOT_ACCOUNTS`.

### 7.2 `require_human_approval.py` (REQ-255-23) — likely NO code change

`require_human_approval.py` already loads `BOT_ACCOUNTS` from the **environment**
(`os.environ.get("BOT_ACCOUNTS", "").split()`, L182) and excludes any approver whose login is in
that set (`human_approval_present`, L139). Therefore, **once `machine-accounts.env` is sourced into
the environment before the gate runs**, `copilot[bot]` is excluded automatically — no change to the
Python is required for REQ-255-23.

The one thing to verify (build note B-1): the caller that runs `require_human_approval.py`
(the branch-protection status check / `setup_branch_protection.sh` / CI job) must `source`
`machine-accounts.env` so `BOT_ACCOUNTS` (now including `copilot[bot]`) is exported into the
environment the Python reads. If that sourcing already happens for the existing two bot accounts, the
Copilot addition is transparent. **Confirm the env-export path; do not duplicate the bot set in
Python.** (The task brief's "extend BOT_ACCOUNTS loading to also include COPILOT_BOT_LOGIN" is
satisfied at the env layer, not in `require_human_approval.py` — flag O-5 to confirm there is no
second, hardcoded bot list anywhere.)

Login-form match: `copilot[bot]` contains `[` and `]`. `human_approval_present` does exact-string
set membership on `author.login`; GitHub returns the bot login as `copilot[bot]`, so exact match
holds. No regex, no normalization needed. (AC-06: a simulated `copilot[bot]` APPROVED is rejected as
non-human.)

---

## §8 — `token_tracker.py` extension (REQ-255-25/26/27/28)

### 8.1 `record` subcommand — new flags

`copilot` is **already** a valid `--vendor` choice (L199). Add to the `record` parser (L198–205):
```
rec.add_argument("--review-event", action="store_true",
                 help="record a review event (no token count); requires --outcome")
rec.add_argument("--outcome",
                 choices=["approved","changes_requested","commented","timeout","skipped","dismissed"],
                 help="review outcome (required with --review-event)")
```
> Note: the spec REQ-255-25 outcome enum lists `approved|changes_requested|commented|timeout|skipped`.
> `dismissed` is added to cover the DISMISSED verdict (§2.3) so the tracker never rejects a real
> verdict; flag O-6 if the architect wants `dismissed` collapsed to `skipped` at the call site
> instead (then drop it from the enum).

### 8.2 `record()` behavior (REQ-255-25/26)

In `record()` (L56): when `args.review_event` is set, **require** `args.outcome` (error to stderr,
exit non-zero if absent), and write a ledger entry conforming to REQ-255-25 **without** computing
tokens:
```json
{
  "ts": "<ISO-8601>",
  "vendor": "copilot",
  "stage": "panel",
  "step": <int or 0>,
  "prompt_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "estimated": false,
  "review_event": true,
  "outcome": "<approved|changes_requested|commented|timeout|skipped|dismissed>"
}
```
- `prompt_tokens`/`output_tokens`/`total_tokens` hard-zero; `estimated: false`; `review_event: true`
  is the discriminator that keeps these out of token subtotals.
- `step` is `0` when `--step` is empty/unparseable (REQ-255-25: "step number or 0 if unknown").
- Non-review-event records are unchanged (the existing token-estimate path runs only when
  `--review-event` is absent — `--prompt-chars`/`--output-chars` are not required in the
  review-event path, REQ-255-26).

The append target is the existing token-usage ledger (`token-usage.jsonl`) that `record()` already
writes to — same file, one extra discriminated record type.

### 8.3 `report()` rendering (REQ-255-27)

In `report()` (L85), in the "By vendor" section: when the vendor is `copilot` (or, generally, for any
vendor whose records are all `review_event: true`), render `copilot (review events: N)` where `N` is
the count of review-event records, and show the token subtotal as `0` (or omit it). Review-event
records MUST NOT contribute to any token total or estimated-token sum.

### 8.4 Call site in `run_panel.sh` (REQ-255-28)

Immediately after `COPILOT_VERDICT` is determined (any outcome), call:
```
python3 "<token_tracker path>" record \
  --vendor copilot --stage panel --review-event \
  --outcome "${_cv_token,,}" --step "${STEP:-0}" \
  >/dev/null 2>>"$RUN_DIR/errors.log" || warn "token_tracker copilot record failed (non-fatal)"
```
- `${_cv_token,,}` lowercases the token to the outcome vocabulary
  (`approved`/`changes_requested`/`commented`/`timeout`/`skipped`/`dismissed`).
- Exactly one record per panel run (AC-07): the call is made once, after the single
  `request_copilot_review` invocation, on every path including LOW-skip and dry-run (so AC-07's
  "exactly one record per run" holds). For the LOW-tier skip path (where the function is not called),
  still emit one `--outcome skipped` record so the invariant holds — OR scope AC-07 to "panel runs
  that reach the Copilot step" — flag O-3 for the architect to pick. **Recommend: one record per
  panel run that actually executes the panel body** (i.e. not the LOW-early-return at L321–325), with
  `outcome=skipped` for the LOW-but-sampled case.
- A failed `token_tracker` call is non-fatal (REQ-255 failure table; warn + continue).

---

## §9 — Failure modes (all fail-open — REQ-255 §3.10)

| Failure | Behavior | Blocking? |
|---|---|---|
| request-review call fails (any reason) | warn + verdict=SKIPPED + record + continue | no |
| Copilot not installed (HTTP 422) | warn + verdict=SKIPPED + continue | no |
| no review within ceiling | warn + verdict=TIMEOUT + continue | no |
| individual `gh pr reviews` poll fails | warn that attempt; loop continues; ceiling → TIMEOUT | no |
| `token_tracker` record fails | warn; do not abort | no |
| `panel-context.md` absent | write section to `$RUN_DIR/copilot-verdict.txt` (REQ-255-21) | no |

---

## §10 — Acceptance-criteria trace

| AC | Satisfied by |
|---|---|
| AC-01 | §2.1 single POST, §3.1 MEDIUM+ gate |
| AC-02 | §3.1 LOW skip line, no API call |
| AC-03 | §4 tier2 finding, arbiter processes, panel does not abort |
| AC-04 | §4 (no finding on APPROVED), §5 summary line |
| AC-05 | §2.2 timeout → §5 `Copilot: TIMEOUT` |
| AC-06 | §7.1 BOT_ACCOUNTS, §7.2 env exclusion |
| AC-07 | §8.4 one record per run, `review_event:true`, matching outcome |
| AC-08 | §6 panel-context append / copilot-verdict.txt fallback |
| AC-09 | §2.1 dry-run: no POST, no poll, clean exit |
| AC-10 | §3.2 env tunables; both-low → §2.2 TIMEOUT |

---

## §11 — Open questions for the architect

| ID | Question | Recommendation |
|---|---|---|
| O-1 | Exact Copilot reviewer identifier in `requested_reviewers` (`copilot` vs. bot slug)? (§2.1) | Use `reviewers[]=copilot` per spec; fail-open on 422; confirm on a live repo. |
| O-2 | Detect Copilot review by `author.login ~ copilot[bot]` only, or also `user.type==Bot`? (§2.2) | `author.login` match — that is what `gh pr reviews` exposes. |
| O-3 | One token record per panel run including LOW-skip, or only when the Copilot step runs? (§8.4) | One per panel-body run; `outcome=skipped` for LOW-but-sampled. |
| O-4 | True request/poll overlap (split function) vs. single call after fan-out? (§3.1) | Single call after fan-out (per-call cost ⇒ wall-clock irrelevant; simpler/safer). |
| O-5 | Any hardcoded bot list besides env `BOT_ACCOUNTS`? (§7.2) | None expected; confirm `machine-accounts.env` is sourced before the gate runs. |
| O-6 | Keep `dismissed` in the outcome enum or collapse to `skipped`? (§8.1) | Keep `dismissed`; never reject a real verdict. |

**Status:** DRAFT — requesting architect review. Not handed to the coder. Round 1 of 5.
