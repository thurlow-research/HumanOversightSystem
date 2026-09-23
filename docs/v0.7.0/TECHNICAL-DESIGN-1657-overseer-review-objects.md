# TECHNICAL DESIGN — #1657: the overseer posts review objects, and requests the CODEOWNERS human where (and only where) the ruling says

**Issue:** #1657 (`bug`, `process-gap`, `priority:critical`, milestone `v0.7.0`)
**Author:** `technical-design`
**Date:** 2026-09-23
**Status:** DRAFT — awaiting `architect` review (see §12 for the two items routed to the architect and §13 for the self-flag)
**Branch:** `worker-1657-overseer-review-objects-260923185002-4111264`

**Document location note.** The task brief named `docs/design/TECHNICAL-DESIGN-1657-…`. No `docs/design/` directory exists; this repo's established convention is `docs/<milestone>/TECHNICAL-DESIGN-<issue>-<slug>.md` (`docs/v0.7.0/` holds TD-1340, TD-1357, TD-1540, TD-1604, TD-1643, TD-1759). #1657 is milestoned `v0.7.0`, so the design lands there. Per the brief's own instruction to follow the existing convention, convention governs.

---

## 0. What this design is bound by, and what it may not re-open

**The human ruling of 2026-09-14, recorded verbatim in #1657, is the spec.** It is not re-litigated anywhere below:

> For a PR needing human approval, the overseer requests the CODEOWNERS human as a required reviewer, and then approves if the change is ready for approval. Merge authority is unchanged — it stays with the human gate, the CODEOWNERS gate, and the tier matrix.
>
> **Scoping — the human reviewer request is NOT universal.** A human is requested as reviewer on exactly two conditions: (1) the PR's computed tier exceeds `OVERSEER_CEILING` (and the existing CRITICAL-tier path), and (2) the PR touches a path in `scripts/framework/protected_surfaces.txt`. For everything else — LOW/MEDIUM tier, non-protected — no human reviewer is requested.

Two consequences bind every section below:

1. **Widening the trigger set is a failure, not a nicety.** `research/sessions/2026-08-04-controls-that-never-fire.md` records the calibration failure this scoping prevents. §4.4 implements the trigger set as a **refusal in code** (exit 3), not as prose, precisely so widening it requires changing a tested predicate rather than drifting a sentence.
2. **The other four entries in `overseer.md`'s NEVER list stay.** In particular `:54` — *"Approve anything above `OVERSEER_CEILING`"* — is untouched, which is what determines the review **event** on the above-ceiling path (§3.3). This design never lets the overseer record `APPROVE` above its ceiling.

**Verified premises** (re-checked against the working tree at `42bd24a2e`, not from the brief):

| # | Premise | Verified at |
|---|---|---|
| VP-1 | `require_overseer_approval.py` passes only on an `APPROVED` **review record**, or on the #1426 bypass whose first condition is `overseer_posted_any_review()` — also a review-record lookup. A conversation comment satisfies neither. | `scripts/framework/require_overseer_approval.py:110-145, 168-196` |
| VP-2 | `require_tier_ceiling.py` keys **only** on tier vs. ceiling and trivially passes when the overseer has not approved. It does not consider protected-surface status. So an overseer `APPROVE` on a **protected-surface PR at or below ceiling** does not fail it. | `require_tier_ceiling.py:412-448` |
| VP-3 | `require_human_approval.py::is_bot_reviewer()` rejects on `user.type == "Bot"`, a `[bot]` login suffix, and `BOT_ACCOUNTS` membership. An overseer `APPROVE` can never satisfy the human gate. | `machine-accounts.env` (`BOT_ACCOUNTS`), `require_human_approval.py` |
| VP-4 | `.github/CODEOWNERS` is **generated** from `protected_surfaces.txt` by `gen_codeowners.sh` and assigns every protected path to `@ScottThurlow`. No machine account appears in it. | `.github/CODEOWNERS:1-3` |
| VP-5 | `decide_merge_authority()` has a **requested-reviewer gate** (#761) at `merge_authority.py:585-596`: if `requested_reviewers` contains `human_reviewer`, it returns HUMAN_REQUIRED **before** checking for a human approval. | `merge_authority.py:585-596` |
| VP-6 | `post_review_thread.sh`'s header forbids it from asserting a verdict: it submits its implicitly-created review as `COMMENT`, *"never APPROVE/REQUEST_CHANGES: it must not assert a verdict on the poster's behalf"* (#1248). It is **not** the verdict primitive. | `bootstrap/post_review_thread.sh:48-55` |
| VP-7 | No script in `bootstrap/` or `scripts/` posts a top-level review verdict, and none requests a reviewer. `overseer.md:658` says so in the document's own words: *"Request reviewer: no wrapper yet"*. | grep over `bootstrap/`, `scripts/` |
| VP-8 | `bootstrap/merge_authority.sh` → `scripts/automation/merge_authority_cli.py` is an existing, shipped L3→L2 wrapper pair for this exact agent and domain, with a fixed argv shape, a JSON envelope, and a documented exit-code contract reserving **exit 3 for "the mutation wrappers a later slice adds."** | `bootstrap/merge_authority.sh:15-40` |
| VP-9 | `scripts/automation/lib/github.py::_run_gh(..., stdin_json=…)` is the canonical @path-safe write path (serialises the body as JSON over `--input -`), with retry/backoff and rate-limit handling. | `github.py:27-76`, `post_comment():335-380` |
| VP-10 | VP-1's defect has a sibling **already live**: `overseer.md`'s #1215 duplicate-comment precheck and #761 `prior_overseer_decision` guard both scan `/issues/{n}/comments` for `**Decision: HUMAN_REQUIRED**`, but since #1207 that marker is written into a **review thread**, not an issues comment. Same producer/consumer class, third instance. | `overseer.md:331-340, 376-390` vs. `:408` |

---

## 1. Root-cause restatement (one paragraph, so the contract below is readable)

The gate `require-overseer-approval` consumes **review objects**. The overseer produces **issues comments**. `post_review_thread.sh` produces a review object as a side effect, but deliberately carries no verdict (VP-6), and nothing in the repository produces a verdict-bearing review at all (VP-7). The fix is therefore not a behavioural nudge in prose — prose is exactly what failed twice (#1207, and this) — it is a **committed write primitive that can only emit a review object**, invoked from every disposition, with a regression test that fails if any disposition's verdict path routes to `/issues/{n}/comments` again.

---

## 2. Decision: one wrapper with two subcommands, over two separate scripts

**Decision: ONE L3 shell wrapper — `bootstrap/pr_review.sh` — with two closed-enum subcommands (`submit-verdict`, `request-reviewer`), backed by ONE new L2 Python CLI module, `scripts/automation/pr_review_cli.py`.**

Justification, against the alternative of two independent bash scripts in the `post_comment.sh` family:

1. **The argv shape stays fixed either way.** The objection to a combined script is normally that flags become conditionally valid (`--body-file` required for one operation, meaningless for the other). `argparse` subparsers make each subcommand its own parser with its own required set — the pattern `merge_authority_cli.py` already uses for `--step` vs. `--cid` vs. `--pr`. The subcommand token is a positional keyword from a closed enum carrying no content, so the command remains statically allowlistable (VP-8, and CLAUDE.md "Shell usage under the sandbox").
2. **The two operations share almost all of their inputs.** Both resolve the repo slug, resolve config from `machine-accounts.env`, fetch the PR object for `head.sha` and the author login, fetch `/pulls/{n}/reviews` for idempotency, and compare against `OVERSEER_CEILING`. Two scripts means two copies of that, or a third shared library — which is the #1135 duplicate-authority class this repo has already paid for.
3. **Config resolution forces Python, and Python forces a wrapper pair.** Both subcommands must read `OVERSEER_CEILING` and `HUMAN_REVIEWER`. ADR-1357 **AD-9 is binding**: *"Do not coin a third env parser."* The canonical resolver is `scripts/automation/lib/merge_config.resolve_config()` (which itself reuses `require_tier_ceiling.load_env`). A bash-only script cannot call it without an inline `python3 -c`, which is forbidden. So the L3→L2 shape is not a choice; given it, one CLI module is cheaper than two.
4. **`request-reviewer` must not re-implement CODEOWNERS or protected-surface matching in bash** (§4.3, §4.4). It has to be Python regardless.
5. **The precedent is exact.** `bootstrap/merge_authority.sh` is the same agent, the same domain, the same sandbox constraint, and the same subcommand shape (VP-8). Matching it costs the coder nothing to learn and makes §12's slice-4 absorption a rename rather than a rewrite.

What the decision explicitly does **not** do: it does not overload `post_review_thread.sh` (VP-6 — its contract forbids carrying a verdict) and it does not add a subcommand to `merge_authority_cli.py` (that module's header declares it read-only: *"performs no GitHub write, applies no label, posts no comment, and can merge nothing"* — and ADR-1357 §4 assigns mutations to slice 4).

---

## 3. The verdict contract — which event, on which disposition

### 3.1 The event enum is `APPROVE` and `COMMENT`. `REQUEST_CHANGES` is excluded.

`--event` accepts exactly `approve` and `comment`. `request_changes` is rejected at argument-parsing time (exit 2) with a message naming `bootstrap/post_review_thread.sh`.

Rationale, stated because it is a reading of "the appropriate event" rather than a transcription of the ruling (see §12, ambiguity **A2**):

- A `CHANGES_REQUESTED` review from a bot blocks merge until that same bot approves or the review is dismissed. `dismiss_stale_reviews_on_push` dismisses stale **approvals**; it is not a reliable release valve for a change request. This repo has already hit the class: the operator-memory note *"Stale CHANGES_REQUESTED blocks cycles — needs-fix routing re-fires on a satisfied human review."*
- The blocking function `REQUEST_CHANGES` would serve is **already served**, by `post_review_thread.sh`'s resolvable thread under `required_conversation_resolution` (#1207). Adding a second, harder-to-clear blocker for the same job creates a new deadlock class for no new gate coverage.
- Nothing in #1657's acceptance criteria requires `REQUEST_CHANGES`; every criterion is satisfied by the existence of a review **record** plus the correct `APPROVED` state on the approval path.

### 3.2 APPROVE-eligibility predicate (this is "sound on the merits", made decidable)

The overseer posts `--event approve` **iff all five hold**; otherwise `--event comment`.

| # | Condition |
|---|---|
| E1 | The disposition is `AUTO_MERGE`, **or** it is `HUMAN_REQUIRED` and every decisive reason recomputed this cycle is **gate-type** (below). |
| E2 | `tier <= OVERSEER_CEILING` (mechanically re-checked by the wrapper, §4.3 guard G1). |
| E3 | The PR is not security-relevant, **or** it is and a verified human approval already exists on the current head SHA. (`overseer.md:56`, unchanged.) |
| E4 | The oversight verdict is `PROCEED`; there are no unresolved DIRTY findings, no bounce condition, no out-of-scope commits, and no human hold directive (#902). |
| E5 | The PR was not authored by this overseer App. (`overseer.md:53`, unchanged; mechanically re-checked by guard G2.) |

**Gate-type reasons** (E1-eligible — the PR is fine, a human's signature is simply required):
protected surface (#1325); CODEOWNERS-human-owned path (SPEC-303b); CRITICAL tier or above-ceiling tier *when E2 also holds* — note E2 makes above-ceiling ineligible, so in practice this row only ever admits CRITICAL when a future ceiling is raised to CRITICAL, which `machine-accounts.env` forbids.

**Merits-type reasons** (never approve): findings unresolved; evaluator `CONDITIONAL`/`ESCALATE`; human hold directive (#902); release-related (NG3b); `hos-halt` label; an active worker bounce.

**Derived markers are not reasons.** The `needs-human` label, `prior_overseer_decision == "HUMAN_REQUIRED"`, and a pending entry in `requested_reviewers` are markers the overseer itself (or a prior cycle) wrote as a *consequence* of some condition. Classify by **the condition recomputed this cycle**, never by the marker — otherwise a protected-surface PR would be permanently merits-type because the overseer labelled it `needs-human` on cycle 1, and the gate would be unsatisfiable for a second, new reason. `hos-halt` is the one exception: it is a human kill switch and is always merits-type.

### 3.3 Disposition → verdict table (authoritative)

`C` = OVERSEER_CEILING. Every row posts **exactly one verdict review**.

| Disposition | Tier | Protected / CODEOWNERS-owned | `--event` | `request-reviewer`? | Merge this cycle? |
|---|---|---|---|---|---|
| AUTO_MERGE | ≤ C | No (by definition of the row) | `approve` | **No** — trigger set not met | Yes (existing path, unchanged) |
| HUMAN_REQUIRED — protected surface / CODEOWNERS-owned | ≤ C | Yes | `approve` if §3.2 holds, else `comment` | **Yes** (protected condition) | Only once a verified human approval on the current head exists |
| HUMAN_REQUIRED — above ceiling | > C | Any | `comment` (never `approve` — `overseer.md:54`) | **Yes** (above-ceiling condition) | Per the existing CRITICAL/above-ceiling rule |
| HUMAN_REQUIRED — CRITICAL tier | CRITICAL | Any | `comment` | **Yes** | On the next cycle after the human approves |
| HUMAN_REQUIRED — merits-type (DIRTY, hold, bounce, ESCALATE, release, `hos-halt`) | Any | Any | `comment` | Only if a *gate* condition also holds | No |
| PROPOSE_ONLY | ≤ C | No | `comment` | No | No |

**Why the above-ceiling row is `comment`, not `approve`.** `overseer.md:54` is one of the four NEVER entries #1657 leaves untouched, and `require_tier_ceiling.py` **fails** any PR the overseer approved above its ceiling (VP-2). `comment` is correct and sufficient: once a real review record exists, `require_overseer_approval.py`'s #1426 bypass fires (`overseer_posted_any_review` + tier > ceiling + a human `APPROVED`) — which is exactly acceptance criterion 2 of #1657.

**Why the protected-surface row is `approve` and does not break anything.** VP-2: `require_tier_ceiling` ignores protected-surface status, so an at-or-below-ceiling approval passes it. VP-3: the approval cannot satisfy `require-human-approval`. VP-4: the overseer is not a code owner, so `require_code_owner_review` is untouched. Net: `require-overseer-approval` turns green, `require-human-approval` stays red until the human acts, and the PR merges through normal branch protection — acceptance criterion 1.

### 3.4 Where the narrative goes

| Disposition | Verdict review body | Separate artifact |
|---|---|---|
| AUTO_MERGE, PROPOSE_ONLY | The **full** per-cycle findings narrative, opening with `**Executive summary:**` per `overseer.md` §Executive summary. **The separate `post_comment.sh` call for these dispositions is removed.** | none |
| HUMAN_REQUIRED, DIRTY, bounce | `**Executive summary:**` paragraph + the canonical `**Decision: HUMAN_REQUIRED**` header (where applicable) + one pointer line: `Full escalation: see the unresolved review thread on this PR.` | The §8.2 five-element escalation stays in the resolvable review thread via `post_review_thread.sh`, **unchanged** |

The body is **not duplicated** between the two artifacts, and the format contract (`bootstrap/lib/comment_format_check.sh`) is satisfied by both bodies independently — a short verdict body can and must still carry the leading `**Executive summary:**` heading, exactly one bolded enum value, and a "not verified" clause.

**Consequence that must be implemented, not merely noted.** Once the `**Decision: HUMAN_REQUIRED**` marker lives in a review body, the two consumers that scan for it must read review bodies. See §6.4. This also repairs VP-10, which is live today and unrelated to whether this design ships — it is recorded as a startup-gap in §11.

---

## 4. The new primitive — `bootstrap/pr_review.sh` + `scripts/automation/pr_review_cli.py`

### 4.0 Layering and contract inherited wholesale from ADR-1357 AD-2

- **L3** `bootstrap/pr_review.sh`: mint → (format-check, §4.6) → invoke L2 with argv passed through verbatim and unreordered → revoke, via an `EXIT` trap. It computes no exit code of its own and never writes JSON to stdout.
- **L2** `scripts/automation/pr_review_cli.py`: sole author of the record schema and the exit code. Importing it performs no I/O (`sys.path` bootstrap only), mirroring `merge_authority_cli.py:29-41`.
- **stdout is exactly one JSON object on every path, including every failure and refusal.** Never suppress stderr.

**Envelope** — identical shape to `merge_authority_cli._envelope()`, with the subcommand's payload keys merged flat into it (never colliding with an envelope key):

```
schema_version, subcommand, computed_at, repo, repo_root, pr,
config_source, app_role, not_verified[], error
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | The requested mutation was performed, **or** was a verified no-op (`skipped: true`) |
| `1` | Operational failure — auth, API error, malformed data, missing/invalid config, an unevaluable input |
| `2` | Usage error — unknown subcommand/flag, missing required flag, invalid enum value, unreadable `--body-file` |
| `3` | **Refusal** — the request was well-formed but the wrapper is not permitted to perform it. A first-class, expected outcome (ADR-1357 AD-5), with the full reason in the payload. Nothing is written. |

`skipped: true` is exit **0**, not 3: "already true" is success, "not allowed" is refusal. The caller distinguishes them without parsing prose.

### 4.1 CLI surface

```
bash bootstrap/pr_review.sh submit-verdict    --app <worker|overseer|human> --pr <N> \
                                              --event <approve|comment> --tier <SAFE|LOW|MEDIUM|HIGH|CRITICAL> \
                                              --body-file <path> [--repo <owner/repo>]

bash bootstrap/pr_review.sh request-reviewer  --app <worker|overseer|human> --pr <N> \
                                              --tier <SAFE|LOW|MEDIUM|HIGH|CRITICAL> \
                                              [--reviewer <login>] [--repo <owner/repo>]
```

- `--app` accepts both `--app overseer` and `--app=overseer` (mirrors `merge_authority.sh`).
- `--body` is **rejected explicitly** at L3 with the same message `post_comment.sh` uses: write the body to a file and pass `--body-file`.
- `--tier` is required on **both** subcommands, uniformly — no conditionally-valid flag. The overseer always holds the computed tier by the time it reaches a disposition. Tier is validated against `require_tier_ceiling.TIER_ORDER`; an unknown value is exit 2 (it is **not** silently coerced to CRITICAL — a typo must be loud, not merely conservative).
- `--reviewer` is an explicit override for `request-reviewer`. It **does not** bypass the scope check (§4.4) or the bot guard (§4.3 G5); it only bypasses CODEOWNERS resolution.

### 4.2 Shared preamble (both subcommands)

1. Resolve `repo_root` from the script's own location (cwd-immune, `merge_authority_cli.py:37`).
2. `merge_config.resolve_config(repo_root)` → `overseer_ceiling`, `human_reviewer`, `bot_accounts`, `config_source`. `ConfigError` → exit 1, envelope carries the message. **Never fall back to a library default** (AD-9).
3. `merge_config.resolve_repo_slug(repo_root, explicit=args.repo)` → exit 1 on failure.
4. Read `HOS_BOT_LOGIN` from the environment (exported by `get_app_token.sh` and inherited through L3). Absent or empty → **exit 1**. The identity of the acting bot is load-bearing for guards G2/G3 and must never be inferred: GitHub App installation tokens return an error on `GET /user`, so there is no recovery path.
5. `github.get_pull(owner, repo, pr)` → `head.sha`, `user.login` (author), `requested_reviewers[].login`, `draft`. `None` or `GitHubError` → exit 1.
6. `github.list_pull_reviews(owner, repo, pr)` → the reviews list, used by both subcommands' idempotency guards. `GitHubError` → exit 1.

### 4.3 `submit-verdict` — behaviour

Guards, evaluated in this order. Each produces a terminal outcome; none is skippable.

| # | Condition | Outcome |
|---|---|---|
| G1 | `event == approve` **and** `tier_exceeds_ceiling(tier, overseer_ceiling)` | **exit 3**, `refusal_reason: "above_ceiling_approve"`. Mechanises `overseer.md:54`. |
| G2 | `event == approve` **and** `pr.user.login` equals `HOS_BOT_LOGIN` (case-insensitive) | **exit 3**, `refusal_reason: "self_authored"`. Mechanises `overseer.md:53`. |
| G3 | `event == approve` **and** the reviews list contains an `APPROVED` review by `HOS_BOT_LOGIN` with `commit_id == head.sha` | **exit 0**, `skipped: true`, `skip_reason: "already_approved_on_head"`, `review_id` of the existing review. No POST. |
| G4 | `event == comment` **and** the reviews list contains a `COMMENTED` review by `HOS_BOT_LOGIN` with `commit_id == head.sha` whose `body` is byte-identical to the body file | **exit 0**, `skipped: true`, `skip_reason: "identical_comment_verdict_on_head"`. No POST. |
| G5 | body file absent, unreadable, or empty after stripping whitespace | **exit 2** |

`tier_exceeds_ceiling` is imported from `scripts/framework/require_tier_ceiling.py` by file path, using the same `importlib` idiom `require_overseer_approval.py:48-55` and `merge_config._load_require_tier_ceiling()` already use. **Do not re-implement tier ordering.**

G4 is a *second* line of defence behind the agent-level #1215 precheck, deliberately narrow (byte-identical bodies on the same head SHA). It never suppresses an approval and never suppresses a body that differs by so much as a character, so it cannot hide new information.

**The write:**

```
POST /repos/{owner}/{repo}/pulls/{pr}/reviews
body: {"event": "APPROVE"|"COMMENT", "body": <file contents>, "commit_id": <head.sha>}
```

via a **new** `github.submit_pull_review(owner, repo, pr_number, event, body, commit_id)` in `scripts/automation/lib/github.py`, using `_run_gh(..., stdin_json=…)` (VP-9). The body is never passed as a `gh` field value, so `@path` expansion is structurally impossible (#752/#1155).

`commit_id` is **required, not optional**: it pins the verdict to the exact diff the overseer reviewed. If the worker pushed between the overseer's read and its write, GitHub returns 422 (`commit_id is not part of the pull request`); the wrapper maps that to **exit 1** with an `error` naming the race, and posts nothing. Approving a diff that was not the one reviewed is precisely the failure this pinning prevents.

**Read-back verification:** the POST response's `state` must be `APPROVED` (for `approve`) or `COMMENTED` (for `comment`), and its `body` must not begin with `@/`. Either check failing → exit 1, `error` naming the mismatch. A verdict that did not land as requested must never report success.

**Payload keys:** `posted`, `skipped`, `skip_reason`, `refused`, `refusal_reason`, `event_requested`, `review_id`, `review_state`, `review_url`, `commit_id`, `tier`, `overseer_ceiling`, `pr_author`, `body_bytes`.

**`not_verified[]` entries:** emitted when `commit_id` could not be resolved from the PR object (then the call is refused, not degraded); and when the reviews list came back empty while the PR has a non-zero `review_comments` count (an inconsistent read).

### 4.4 `request-reviewer` — behaviour, and where the scoping ruling becomes code

**Step 1 — changed files.** `github.list_pull_files(owner, repo, pr)` → `changed_files = [f["filename"] for f in files if f.get("filename")]`.

**Step 2 — the trigger predicate.** Implemented as a pure function `evaluate_reviewer_trigger(tier, ceiling, changed_files, repo_root) -> TriggerResult` in `pr_review_cli.py`, with no I/O of its own beyond the L1 call:

```
above_ceiling    = require_tier_ceiling.tier_exceeds_ceiling(tier, ceiling)
critical_tier    = tier.upper() == "CRITICAL"
protected_surface= merge_authority.touches_protected_surface(changed_files, repo_root)
triggered        = above_ceiling or critical_tier or protected_surface
```

`critical_tier` is retained as its own term even though it is currently implied by `above_ceiling` (ceiling is `HIGH`). The ruling names the CRITICAL path separately and `machine-accounts.env` permits the ceiling to be re-tuned; folding the terms together would let a future ceiling change silently drop the CRITICAL trigger.

**Step 3 — refusal when not triggered.** `triggered == False` → **exit 3**, `refusal_reason: "no_qualifying_trigger"`, payload carrying all three booleans and `changed_file_count`. **No write of any kind occurs.** This is the ruling's scoping implemented as a mechanism: on a LOW/MEDIUM, non-protected PR the wrapper *cannot* request a reviewer, and widening the trigger set requires editing a predicate that §8's test table pins cell by cell.

Exit 3 here is **expected and non-fatal for the caller**. `overseer.md` (§6.2) states explicitly that on the AUTO_MERGE path the overseer does not call this subcommand at all, and that if it is called and refuses, the refusal is logged and the cycle continues.

**Step 4 — fail-closed on an unevaluable trigger.** If `changed_files` is empty **and** `triggered` is False, the result is **exit 1** (operational failure: *"0 changed files reported — the protected-surface trigger could not be evaluated"*), never exit 3. `touches_protected_surface([])` returns `False`, and a false "not triggered" would silently skip a human gate. A read that did not see the PR's content is not a clean result. (`merge_authority_cli._cmd_surface` records the same condition in `not_verified[]`; here it is escalated to a hard failure because the consequence is a skipped gate rather than an under-informed report.)

**Step 5 — resolve the reviewer.** §4.5.

**Step 6 — idempotency and the livelock guard.**

| # | Condition | Outcome |
|---|---|---|
| I1 | resolved login is already in `pr.requested_reviewers[].login` (case-insensitive) | **exit 0**, `skipped: true`, `skip_reason: "already_requested"`. No POST. |
| I2 | resolved login has **any** review whose `commit_id == head.sha` | **exit 0**, `skipped: true`, `skip_reason: "already_reviewed_head"`. No POST. |

**I2 is not an optimisation — it is the guard against a merge livelock, and must be implemented exactly as written.** `POST /pulls/{n}/requested_reviewers` for a user who has already submitted a review is GitHub's *re-request review* operation: it adds the user **back** into `requested_reviewers`. `decide_merge_authority()` reads `requested_reviewers` and, if it contains `human_reviewer`, returns HUMAN_REQUIRED **before** it ever checks for a human approval (VP-5, `merge_authority.py:585-596`). So an unguarded per-cycle re-request on a PR the human has already approved would flip the disposition back to HUMAN_REQUIRED on every cycle, forever, with the human's approval sitting right there. The existing prose at `overseer.md:407` — *"idempotent — a repeat call against an already-requested reviewer is harmless, so run it every cycle"* — is true only for the *pending* case (I1) and is **false** for the already-reviewed case; I2 is what makes the per-cycle instruction safe.

**Step 7 — the write.**

```
POST /repos/{owner}/{repo}/pulls/{pr}/requested_reviewers
body: {"reviewers": ["<resolved-login>"]}
```

via a **new** `github.request_reviewers(owner, repo, pr_number, logins)` using `_run_gh(..., stdin_json=…)`.

**422 handling:** GitHub 422s when the requested user is the PR author, is not a collaborator, or lacks push access. Map to **exit 1**, with GitHub's message verbatim in `error` and `resolved_reviewer` / `resolution_source` in the payload so the operator can see who was attempted and why that login was chosen. **Never silently fall back to another login after a 422** — that would mask a misconfigured CODEOWNERS and make the gate look satisfied when the wrong person was asked.

**Payload keys:** `requested`, `skipped`, `skip_reason`, `refused`, `refusal_reason`, `resolved_reviewer`, `resolution_source`, `codeowners_owners[]`, `codeowners_team_owners[]`, `trigger: {above_ceiling, critical_tier, protected_surface}`, `matched_protected_paths[]`, `changed_file_count`, `head_sha`.

**Redaction contract on `codeowners_owners[]` (MUST_FIX A, #1657 PR-1 review round 2).** This payload — including `codeowners_owners[]` — is written verbatim into the overseer's committed audit record on every disposition (`audit/automation/<customer>/runs/`), so it MUST NEVER carry a raw e-mail-shaped owner token (CODEOWNERS permits `/path/** dev@example.com`, and that pattern is common). `resolve_human_reviewer` excludes any owner classified as e-mail (§4.5 step 3) from `codeowners_owners[]` before returning it — on **every** return path, not only the e-mail-only fallback — while `note` (surfaced into `not_verified[]`) remains the record that an e-mail owner was present and was not requestable. This applies even when an e-mail owner is co-listed with a usable human/team owner on the same CODEOWNERS line: the human/team owner is still resolved and returned normally, only the e-mail token is withheld.

`matched_protected_paths[]` is derived with the same per-file idiom `merge_authority_cli._cmd_surface` uses — `[f for f in changed_files if touches_protected_surface([f], repo_root)]` — calling the same L1 function. No second matcher is written.

### 4.5 Reviewer resolution — which CODEOWNERS module is canonical, and the full fallback chain

**Canonical module: `scripts/oversight/codeowners.py`.** Stated explicitly, because the repo has two parsers:

| Module | Verdict for this use | Why |
|---|---|---|
| `scripts/oversight/codeowners.py` (`load_codeowners`, `parse_codeowners`, `get_owners_for_path`) | **USE THIS** | It is already the overseer-side module in production: `merge_authority_cli._cmd_codeowners` loads it by file path, and `overseer.md`'s pre-matrix CODEOWNERS gate calls its `check_pr_files`. Its matcher handles `**`, trailing-slash directories, and GitHub's no-slash-matches-any-depth rule (#975). Its documented fail direction is **conservative — over-match → more human involvement**, which is the correct direction for "who should be asked to look at this." |
| `scripts/automation/lib/codeowners.py` (`find_owners`, `actor_is_codeowner`) | **DO NOT USE** | Its own docstring records that it has **no production callers** and that *"any future wiring into a live authorization path requires a product-boundary checkpoint (architect ruling on #559)"*; its documented fail direction is the **opposite** (over-match → unearned authorization); and it explicitly forbids cross-importing with the oversight module. Wiring it here would trip #559's checkpoint for no benefit. |

The task brief suggested reusing `find_owners`. That suggestion is **superseded** for the reasons in the table: the brief's underlying instruction — *"do not write a second CODEOWNERS parser"* — is honoured, by using the parser that is already live on this side of the trust boundary.

**`resolve_human_reviewer(changed_files, repo_root, bot_accounts, human_reviewer) -> Resolution`** — a new **pure** function added to `scripts/oversight/codeowners.py` (no network, no subprocess; `load_codeowners`'s file read is its only I/O). `Resolution` carries `login`, `source`, `codeowners_owners`, `codeowners_team_owners`, `note`.

1. `text = load_codeowners(repo_root)`. `None` → step 6 with `note="no CODEOWNERS file"`.
2. `entries = parse_codeowners(text)`. For each file in `sorted(changed_files)`, `get_owners_for_path(entries, f)`; accumulate the union, preserving first-seen order over the sorted file list (deterministic across runs and across `list_pull_files` page ordering).
3. Partition the owner tokens:
   - **team** — matches `@org/team` (a slash after the leading `@`);
   - **email** — contains `@` after stripping one leading `@` (CODEOWNERS permits email owners; they cannot be passed to `requested_reviewers`);
   - **bot** — login is in `bot_accounts` (case-insensitive) or ends with `[bot]`;
   - **user** — everything else.
4. First **user** in accumulation order, with the leading `@` stripped → `login`, `source="codeowners"`. Done.
5. No user candidate:
   - team owners present → step 6 with `note="CODEOWNERS owner is a team (<name>); team review requests are not made"`, and `codeowners_team_owners` populated. **Teams are deliberately not requested**: a team request needs the separate `team_reviewers` field and org membership a personal-repo install may not have (a guaranteed 422 on a non-org repo), and `decide_merge_authority`'s #761 gate compares `requested_reviewers` against the single `human_reviewer` login, so a team entry would never satisfy it. The fact is surfaced in the payload and in `not_verified[]` rather than silently dropped. Follow-up is named in §12 (**A3**).
   - only bots → step 6 with `note="bot-only CODEOWNERS entry"`.
   - only emails → step 6 with `note="CODEOWNERS owners are e-mail addresses; not requestable"`.
   - no owners matched → step 6 with `note="no CODEOWNERS entry matched the changed files"`.
6. **Fallback:** `login = human_reviewer` (from `machine-accounts.env`), `source="machine-accounts.env"`.
7. **Fail-closed terminal checks**, applied to whichever login came out of 4 or 6, and also to an explicit `--reviewer`:
   - empty / whitespace-only → **exit 1** (`machine-accounts.env`'s own comment: *"Fail-closed if absent: the orchestrator must not skip the reviewer request"*);
   - login is in `bot_accounts` or ends with `[bot]` → **exit 1**. Requesting a bot as "the human reviewer" would look like a satisfied gate and be none;
   - login equals the PR author login → **exit 1** (GitHub would 422 anyway; failing here names the cause).

`--reviewer <login>` sets `source="explicit-flag"` and skips steps 1–6 only.

**Why the fallback is correct and not a silent default.** `HUMAN_REVIEWER` is already the configured, documented identity of the reviewer this gate exists for, is already what `decide_merge_authority` compares `requested_reviewers` against, and is absent-is-fatal by design. The fallback is therefore a resolution *to the configured value*, and every use of it is recorded in `resolution_source` + `not_verified[]`, so "CODEOWNERS did not answer" is visible in the artifact rather than inferable from behaviour.

### 4.6 L3 responsibilities, and one named deviation

`bootstrap/pr_review.sh` does, in order:

1. Extract the subcommand token and the `--app` value **without validating them** (ARCH-3a: an unrecognised value simply means no token is minted; L2's argparse remains the sole author of the exit-2 envelope).
2. Reject `--body` with a readable error (exit 2) — this is a message-quality choice, not a decision: L2's argparse would reject it as an unknown flag regardless.
3. For `submit-verdict` only, source `bootstrap/lib/comment_format_check.sh` and run `hos_cfc_check_at_path_literal` (unconditional) and `hos_cfc_enforce_overseer_format "$BODY_FILE" "$APP_ROLE" warn` (mode-gated, advisory by default) — byte-identical usage to `post_comment.sh:79-86` and `post_review_thread.sh:103-112`.
4. Mint the token via `get_app_token.sh --app "$APP_ROLE"` into a `mktemp` file, source it, delete the file immediately (#549). Register revocation as an `EXIT` trap so it fires on every path.
5. `python3 "$REPO_ROOT/scripts/automation/pr_review_cli.py" "$@"`, argv verbatim and unreordered. No `jq`, no capture, no reformatting of stdout; stderr not redirected.
6. `exit` with the child's code unmodified.

**Named deviation from ADR-1357 ARCH-3a** (*"no decision reachable only through bash"*): step 3 can refuse in `HOS_COMMENT_FORMAT_MODE=enforce`. This is deliberate and matches both sibling wrappers exactly. The alternative — reimplementing the `#1270` format contract in Python — forks a validator whose entire purpose is that the two write paths *cannot* drift apart. Keeping one bash implementation and adding a third caller is the lesser evil. Recorded for the architect in §12 (**A4**).

### 4.7 Failure-mode summary

| Failure | Code | Written? |
|---|---|---|
| Token mint fails | 1 | No — L2's GitHub fetch fails and emits the envelope naming the cause (mirrors `merge_authority.sh`'s handling) |
| `machine-accounts.env` missing / `OVERSEER_CEILING`, `HUMAN_REVIEWER`, or `BOT_ACCOUNTS` absent | 1 | No |
| `HOS_BOT_LOGIN` unset | 1 | No |
| PR fetch / reviews fetch / files fetch fails | 1 | No |
| Approve above ceiling | 3 | No |
| Approve own PR | 3 | No |
| `request-reviewer`, trigger set not met | 3 | No |
| `request-reviewer`, 0 changed files and not otherwise triggered | 1 | No |
| Resolved reviewer empty / bot / PR author | 1 | No |
| `commit_id` stale (422) | 1 | No |
| Review posted but read-back state wrong | 1 | **Yes, and reported as a failure** — `error` names the mismatch; the caller must halt |
| Reviewer request 422 | 1 | No |
| Already approved on head / already requested / already reviewed head | 0 | No (`skipped: true`) |

---

## 5. Changes to `scripts/automation/lib/github.py`

Two additions, both using `_run_gh(..., stdin_json=…)`. No existing function changes.

```
submit_pull_review(owner, repo, pr_number, event, body, commit_id) -> dict
    POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews
    event must be "APPROVE" or "COMMENT" (uppercase, validated); commit_id required.
    Returns the created review object (at least id, state, body, commit_id, html_url).
    Raises GitHubError on a null response.

request_reviewers(owner, repo, pr_number, logins) -> dict
    POST /repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers
    logins: a non-empty list of user logins. Team reviewers are NOT supported by
    this function (see §4.5 step 5); passing an "@org/team" token raises ValueError.
    Returns the updated PR object. Raises GitHubError on a null response.
```

Docstrings must state, as `post_comment`'s does, that the body travels as JSON over stdin specifically so a body beginning with `@/` is never coerced by `gh`'s `--field` type handling (#752).

---

## 6. Changes to `.claude/agents/overseer.md` (exact locations and replacement wording)

All line numbers are against the file at `42bd24a2e`. **Every other line of the file is unchanged.** `.claude/agents/**` is a protected surface: a human approves the merge; that does not block authoring.

### 6.1 Line 55 — the NEVER-list entry (#1657 required change 4)

The list at `:50-59` has eight bullets. **Only `:55` changes.** `:52`, `:53`, `:54`, `:56`, `:57`, `:58`, `:59` stay byte-identical.

**Current `:55`:**

```
- Approve anything touching a protected surface (read from `scripts/framework/protected_surfaces.txt`)
```

**Replacement `:55`:**

```
- Merge anything touching a protected surface on your own authority, or treat your own approval on one as sufficient to merge (protected surfaces are read from `scripts/framework/protected_surfaces.txt`). Recording an `APPROVE` review verdict on such a PR when the change is sound on the merits is **expected**, not forbidden — it is *necessary-not-sufficient* (`docs/FABERIX-ROLES.md` §5), and the merge still waits on the human's CODEOWNERS approval (#1657)
```

Rationale to carry in the PR description, not the file: `:55` previously collapsed *"may not unilaterally merge a protected surface"* into *"may not record a review verdict on one,"* which made `require-overseer-approval` unsatisfiable for that entire class and forced admin override on every such PR.

### 6.2 Line 406 — AUTO_MERGE

**Replacement:**

```
   - **AUTO_MERGE** → (1) post the approval verdict as a real review object: `bash bootstrap/pr_review.sh submit-verdict --pr <n> --event approve --tier <TIER> --body-file <path> --app overseer`. The body IS this cycle's findings narrative — it opens with the executive summary, Expected action `NO ACTION`; there is no separate `post_comment.sh` call on this path. The wrapper refuses (exit 3) if the tier exceeds `OVERSEER_CEILING` or you authored the PR; treat a refusal as a disposition bug and halt, never as a reason to downgrade the event. (2) Only after the wrapper reports `posted` or `skipped`, merge via `PUT /repos/{o}/{r}/pulls/{n}/merge` with `{"merge_method":"squash"}`. Both steps are required — approving without merging leaves the PR open. **Do NOT request a human reviewer on this path** — the trigger set is deliberately narrow (#1657); `request-reviewer` would refuse it anyway. Log all actions to ledger. If merge fails, post a comment explaining the failure (`bootstrap/post_comment.sh`) and label `needs-human` (`bash bootstrap/edit_issue.sh --number <n> --add-label needs-human --app overseer`).
```

### 6.3 Lines 407–408 — the HUMAN_REQUIRED paths (#1657 required changes 2 and 3)

**Replacement `:407`:**

```
   - **HUMAN_REQUIRED (CRITICAL tier)** → (1) `bash bootstrap/pr_review.sh request-reviewer --pr <n> --tier CRITICAL --app overseer` — the reviewer login is resolved from `.github/CODEOWNERS` for this PR's touched paths, falling back to `HUMAN_REVIEWER` in `scripts/framework/machine-accounts.env`; never pass a hardcoded login. Run it every cycle: the wrapper is idempotent and skips (exit 0, `skipped`) when the reviewer is already requested or has already reviewed the current head. (2) Post the verdict as `--event comment` (never `approve` — `:54` forbids approving above `OVERSEER_CEILING`, and `require-tier-ceiling` would fail the PR); once a real review record exists, `require-overseer-approval`'s #1426 above-ceiling bypass can fire. (3) If `HUMAN_REVIEWER` has approved on the current head SHA, merge immediately — unconditional; a fresh approval must never be missed because a stale precheck suppressed this cycle's verdict. Posting the verdict body (executive summary, Expected action `APPROVE`) is subject to the §1215 duplicate-verdict precheck above.
```

**Replacement `:408`:**

```
   - **HUMAN_REQUIRED (other reasons)** → (1) label `needs-human` (`bash bootstrap/edit_issue.sh --number <n> --add-label needs-human --app overseer`; idempotent, run every cycle). (2) `bash bootstrap/pr_review.sh request-reviewer --pr <n> --tier <TIER> --app overseer`. The wrapper applies the #1657 scoping itself: it requests a reviewer only when the tier exceeds `OVERSEER_CEILING`, the tier is CRITICAL, or the PR touches `scripts/framework/protected_surfaces.txt`. On any other PR it refuses with exit 3 and `refusal_reason: "no_qualifying_trigger"` — **that refusal is the expected, correct outcome; log it and continue.** Do not work around it, and do not add trigger conditions of your own: requesting a human on every PR is the calibration failure this scoping exists to prevent (`research/sessions/2026-08-04-controls-that-never-fire.md`). (3) Post the verdict via `bash bootstrap/pr_review.sh submit-verdict --pr <n> --event <approve|comment> --tier <TIER> --body-file <path> --app overseer`, choosing the event by the APPROVE-eligibility rule in § Verdict events below — `approve` when the only thing standing between this PR and merge is a human's signature and the change is sound on the merits; `comment` whenever a merits-type blocker exists. (4) If the reason is a **human hold directive (#902)** and this overseer App has a standing `APPROVED` review on the PR, **dismiss it** (`PUT /repos/{o}/{r}/pulls/{n}/reviews/{review_id}/dismissals` with a short reason) so no bot approval stands against the human's bounce-back decision — also unconditional. (5) The §8.2 escalation (executive summary + problem + options + recommendation) is posted as a resolvable review thread (`bootstrap/post_review_thread.sh` — #1207, see "Posting comments" below) and is subject to the §1215 duplicate-verdict precheck above.
```

### 6.4 Lines 331–340 and 376–390 — the prior-decision marker now lives in review bodies

Both the #761 `prior_overseer_decision` derivation (`:331-340`) and the #1215 duplicate-comment precheck (`:376-390`) currently scan **only** `GET /repos/{o}/{r}/issues/{n}/comments`. Since #1207 the `**Decision: HUMAN_REQUIRED**` marker has been written into a **review thread**, and under this design the canonical copy moves into the **verdict review body**. Both scans must read both surfaces or they match nothing — VP-10, which is live today.

**Insert a new named subsection immediately before `:331`**, and have both sites cite it rather than each restating the fetch:

```
   **§ Where your own prior decision is recorded (#1207, #1657).** Your canonical
   `**Decision: HUMAN_REQUIRED**` marker lives in the body of the verdict *review*
   you post via `bootstrap/pr_review.sh submit-verdict`, not in a conversation
   comment. Any scan for a prior decision of your own must therefore read the
   union of two lists, never just one:

   ```
   GET /repos/{o}/{r}/issues/{n}/comments      # conversation comments (author: .user.login,      timestamp: .created_at)
   GET /repos/{o}/{r}/pulls/{n}/reviews        # review verdicts      (author: .user.login,      timestamp: .submitted_at)
   ```

   Merge the two, sort by timestamp, and treat `HOS_BOT_LOGIN`-authored entries
   from either list identically. A scan of only one list is the #1207/#1657
   producer/consumer mismatch repeating for a third time: the artifact type the
   control reads must match the artifact type the governed actor emits.
```

`:331-340` (`prior_overseer_decision`) and `:376-390` (the precheck) are then edited to say *"scan the union defined in § Where your own prior decision is recorded"* in place of their current single `GET /issues/{n}/comments` instruction. The precheck's rename from "duplicate-comment" to "duplicate-verdict" follows through to `:366` and `:407-408`.

`human_hold_directive` (`:344-359`) is **unchanged**: it scans for the *human's* comments, which still live on the issues-comments surface.

Line `:352`'s `human_reviewer="ScottThurlow"` is replaced with `human_reviewer=<HUMAN_REVIEWER from scripts/framework/machine-accounts.env>` — same class of bug as `:407`'s hardcoded login (#1657 required change 3), in the same file, and fixing only one of the two would leave the consumer-install defect half-open. The parenthetical glosses at `:315`, `:323`, `:329` that read "HUMAN_REVIEWER (ScottThurlow)" are left alone: they name the variable first and illustrate second.

### 6.5 New subsection "§ Verdict events" — insert immediately after the merge-authority matrix (after `:507`)

```
## Verdict events (#1657 — every disposition posts a review object)

Every disposition you reach posts **exactly one** verdict review, via
`bootstrap/pr_review.sh submit-verdict`. A conversation comment is not a verdict:
`require-overseer-approval` and the #1426 above-ceiling bypass both read
`/pulls/{n}/reviews`, so a verdict posted anywhere else leaves those gates
unsatisfiable and the PR merges only by admin override (#1657).

Two events exist. `REQUEST_CHANGES` is not available: the wrapper rejects it, and
blocking is the job of a resolvable review thread (`post_review_thread.sh`, #1207),
which clears on resolution rather than requiring a dismissal.

Post `--event approve` **only when all five hold**; otherwise post `--event comment`:

1. The disposition is AUTO_MERGE, or it is HUMAN_REQUIRED and every decisive reason
   recomputed **this cycle** is gate-type (protected surface, CODEOWNERS-human-owned
   path) rather than merits-type.
2. The computed tier does not exceed `OVERSEER_CEILING`.
3. The change is not security-relevant, or it is and a verified human sign-off
   already exists on the current head SHA.
4. The oversight verdict is PROCEED, with no unresolved findings, no bounce
   condition, no out-of-scope commits, and no human hold directive.
5. You did not author the PR.

**Derived markers are not reasons.** The `needs-human` label, a prior
`HUMAN_REQUIRED` decision, and a pending entry in `requested_reviewers` are things
you (or a previous cycle) wrote *because of* some condition. Classify by the
condition you recomputed this cycle, never by the marker — otherwise a
protected-surface PR stays permanently ineligible because cycle 1 labelled it, and
the gate becomes unsatisfiable for a second, new reason. `hos-halt` is the one
exception: it is a human kill switch and always forces `comment`.

An `approve` verdict on a protected surface asserts *"I reviewed this and it is
sound on the merits."* It cannot merge the PR: your approval is a bot approval
(`require_human_approval.py::is_bot_reviewer` rejects it three independent ways),
you are not a CODEOWNER, and the tier matrix still binds. That is exactly the
*necessary-not-sufficient* position `docs/FABERIX-ROLES.md` §5 describes.

**Ordering within step 6, and halt-on-failure.** `request-reviewer` first, then
`submit-verdict`, then the blocking review thread (if any), then the audit event,
then finalize (label / merge). If `submit-verdict` exits 1 or 2, **halt** — do not
append the audit event, do not merge, do not treat the disposition as recorded. If
it exits **3**, halt and report: a refusal means you asked for an authority you do
not have, which is a disposition bug, not a cue to silently retry as `comment`. An
exit 3 from `request-reviewer` with `refusal_reason: "no_qualifying_trigger"` is
the opposite: expected, correct, logged, and the cycle continues.
```

### 6.6 Lines 630–635 — the tooling table

Insert one row after `:635`, leaving the five existing rows untouched:

```
| `pr_review.sh` | `submit-verdict --pr <N> --event <approve\|comment> --tier <TIER> --body-file <path> --app overseer` — post the cycle's verdict as a real review object; `request-reviewer --pr <N> --tier <TIER> --app overseer [--reviewer <login>]` — request the CODEOWNERS human, scoped to above-ceiling/CRITICAL/protected-surface only (#1657) |
```

### 6.7 Line 658 — the operations protocol

**Current:**

```
- **Request reviewer:** no wrapper yet — use `POST /repos/{o}/{r}/pulls/{n}/requested_reviewers` with `{"reviewers": ["ScottThurlow"]}` for human-required PRs.
```

**Replacement:**

```
- **Request reviewer:** `bash bootstrap/pr_review.sh request-reviewer --pr <N> --tier <TIER> --app overseer`. Never call `POST /pulls/{n}/requested_reviewers` directly and never name a login literally — the wrapper resolves the reviewer from `.github/CODEOWNERS` (falling back to `HUMAN_REVIEWER` in `machine-accounts.env`), enforces the #1657 trigger scoping, and skips the call when the reviewer is already requested or has already reviewed the current head. That last guard is load-bearing: re-requesting a reviewer who already reviewed re-adds them to `requested_reviewers`, which `decide_merge_authority()`'s #761 gate reads as "human review pending", flipping the PR back to HUMAN_REQUIRED every cycle even after the human approved.
- **Post a verdict:** `bash bootstrap/pr_review.sh submit-verdict …` — see "§ Verdict events". Never `POST /pulls/{n}/reviews` directly, and never route a verdict through `post_comment.sh`.
```

`:659` (**Merge:** no wrapper yet) is **unchanged** — merge remains out of scope here and belongs to #1357 slice 4.

### 6.8 § "Posting comments" (`:661`ff)

Retitle to **"Posting verdicts, findings, and comments (#752, #1155, #1207, #1657 — mandatory)"** and restructure the "two wrappers" list into three, with the first added and the other two unchanged in substance:

- **Verdicts** (every disposition, approving or not) → `bash bootstrap/pr_review.sh submit-verdict --pr <n> --event <approve|comment> --tier <TIER> --body-file <path> --app overseer`. *"A conversation comment is not a verdict. `require-overseer-approval` and the #1426 bypass read `/pulls/{n}/reviews`; a verdict posted to `/issues/{n}/comments` leaves zero review records and both gates unsatisfiable (#1657). `post_review_thread.sh` is not an alternative — it deliberately submits its implicit review as COMMENT and must not assert a verdict on your behalf (#1248)."*
- **Blocking findings** → `post_review_thread.sh` (unchanged).
- **Narrative-only output** → `post_comment.sh`, with its scope narrowed by one sentence: *"On a PR, this is for output that is not this cycle's verdict — merge-failure notices, release-gate clearance, worker-facing summaries. This cycle's findings narrative now travels in the verdict review body."*

Add to the existing **Never use** list: *"`bootstrap/post_comment.sh` for a disposition's verdict — it posts to `/issues/{n}/comments`, which carries no review record (#1657)."*

The paragraph about `comment_format_check.sh` gains `pr_review.sh` as a third caller; the check's behaviour is unchanged.

---

## 7. Changes to `docs/FABERIX-ROLES.md`

Three edits in §5, all minimal. `docs/FABERIX-ROLES.md` is a protected surface.

**E1 — the LOW-tier bullet.** Append a clarifying parenthetical; the sentence is otherwise unchanged:

> **LOW tier → auto-approve — and only in a repo Faberix owns.** … no governance/contract/gate/security/privacy **or any protected surface** (`AGENT-IDENTITY.md §9.0`). *(This exclusion scopes auto-approve-**and-merge**. It does not forbid recording an approval verdict on a protected-surface PR — see the determination-honesty boundary below, and #1657.)*

**E2 — the MEDIUM/HIGH bullet.** It is stale in two ways: it predates the 2026-06-19 authorization (#598/#600) that set `OVERSEER_CEILING=HIGH`, and it is the text `require_overseer_approval.py` quotes. Replace with a ceiling-relative statement:

> **Above `OVERSEER_CEILING` → record a review, but never `APPROVED`.** Faberix posts a structured review recommendation (`COMMENT` event, with rationale) and routes to a human (`needs-human`); the human makes the call. It does not assert `APPROVED` authority above its ceiling — `require-tier-ceiling` fails any PR it does. The ceiling itself is configuration (`scripts/framework/machine-accounts.env`), raised only by deliberate human decision; it was raised to `HIGH` on 2026-06-19 (#598/#600).

**E3 — the determination-honesty paragraph.** Append one sentence making the direction explicit, so §5 and `overseer.md:55` agree in both directions rather than only one:

> *Necessary-not-sufficient means the approval is **given**, not withheld: on a protected path Faberix records its `APPROVED` verdict when the change is sound on the merits, and the merge still waits on the human's CODEOWNERS approval. `overseer.md`'s NEVER list forbids **merging** such a PR on its own authority, not reviewing one (#1657).*

**Knock-on edit (in scope, same defect):** `require_overseer_approval.py`'s module docstring (`:16-18`) and its bypass success message (`:180-187`) both quote the old §5 wording — *"MEDIUM and HIGH tier → recommend, do NOT approve"*. Update both to quote E2's replacement. Leaving a gate quoting a sentence that no longer exists in the document it cites is the same stale-citation class the issue is about.

---

## 8. Tests

All three files run without network access, following the harness idiom already in the repo.

### 8.1 `tests/automation/test_pr_review_wrapper.py` — shell-level

Mirror `tests/automation/test_post_review_thread.py` exactly: copy the real script into `tmp_path/bootstrap/`, copy `bootstrap/lib/comment_format_check.sh` alongside it, and put executable `git` / `gh` / `curl` / `get_app_token.sh` stubs on `PATH`, each appending its argv to `$CAPTURE_FILE`. The `gh` stub serves `pr view`, `api …/pulls/<n>`, `api …/pulls/<n>/reviews`, `api …/pulls/<n>/files` from fixtures keyed by env vars, and records any POST.

| ID | Assertion |
|---|---|
| **W1** | **The #1657 regression, `--event comment`.** `$CAPTURE_FILE` contains a POST to `repos/test-owner/test-repo/pulls/123/reviews`, **and** contains no `gh issue comment` invocation **and** no `/issues/123/comments` substring. Both directions asserted; the negative half is the one that fails if the defect returns. |
| **W2** | Same as W1 for `--event approve`, additionally asserting the request body carried `"event":"APPROVE"` and a `"commit_id"` equal to the stubbed head SHA. |
| **W3** | `--body <text>` → non-zero exit, stderr names `--body-file`. |
| **W4** | Missing `--tier` → exit 2. Missing `--body-file` on `submit-verdict` → exit 2. |
| **W5** | `--event request_changes` → exit 2, stderr names `post_review_thread.sh`. |
| **W6** | `get_app_token.sh` was called with the `--app` value passed, and `curl` was invoked with `DELETE …/installation/token` — on the success path **and** on an exit-1 path (trap fires regardless). |
| **W7** | On each of exit 0, 1, 2 and 3, stdout parses as exactly one JSON object carrying `schema_version`, `subcommand`, `pr`, `app_role`, `not_verified`, `error`. |
| **W8** | **The "must not widen" pin, script level.** `request-reviewer --tier LOW` with changed files `["README.md"]` → exit 3, payload `refusal_reason == "no_qualifying_trigger"`, and `$CAPTURE_FILE` contains **no** POST to `requested_reviewers`. |
| **W9** | `request-reviewer --tier LOW` with changed files `[".claude/agents/overseer.md"]` → POST to `requested_reviewers` whose body is `{"reviewers":["ScottThurlow"]}` as resolved from the fixture CODEOWNERS; payload `resolution_source == "codeowners"`. |
| **W10** | `request-reviewer --tier CRITICAL` with `["README.md"]` → POST occurs (the above-ceiling/CRITICAL condition, independent of protected surface). |
| **W11** | Reviewer already present in the stubbed `requested_reviewers` → exit 0, `skipped: true`, `skip_reason == "already_requested"`, no POST. |
| **W12** | **The livelock guard.** Reviewer has an `APPROVED` review with `commit_id == head.sha` and is absent from `requested_reviewers` → exit 0, `skip_reason == "already_reviewed_head"`, **no POST**. Docstring must state why: a re-request re-populates `requested_reviewers`, which `decide_merge_authority`'s #761 gate reads as HUMAN_REQUIRED, livelocking the merge. |
| **W13** | `submit-verdict --event approve --tier CRITICAL` with ceiling `HIGH` → exit 3, `refusal_reason == "above_ceiling_approve"`, no POST. |
| **W14** | `request-reviewer --tier LOW` with an **empty** changed-files response → exit **1** (not 3), `error` naming the unevaluable trigger, no POST. |

### 8.2 `tests/automation/test_pr_review_resolution.py` — pure-Python unit

Loads `scripts/oversight/codeowners.py` by file path (the `importlib` idiom of `merge_authority_cli._load_codeowners_module`) and `pr_review_cli.py` the same way; CODEOWNERS fixtures written into `tmp_path`.

| ID | Assertion |
|---|---|
| **R1** | Protected path → the CODEOWNERS user login, `source == "codeowners"`. |
| **R2** | `@org/team`-only owner → falls back to `HUMAN_REVIEWER`; `codeowners_team_owners` is populated; `source == "machine-accounts.env"`. |
| **R3** | Bot-only owner → falls back; the bot login is never returned. |
| **R4** | No CODEOWNERS file → falls back, `note == "no CODEOWNERS file"`. |
| **R5** | No entry matches the changed files → falls back. |
| **R6** | Email-form owner (`dev@example.com`) → not returned; falls back. |
| **R7** | Empty/whitespace `HUMAN_REVIEWER` with no CODEOWNERS answer → error (exit 1 at the CLI boundary); never returns `""`. |
| **R8** | A resolved login that is in `BOT_ACCOUNTS` or ends with `[bot]` → error; never returned. |
| **R9** | Resolved login equal to the PR author → error. |
| **R10** | Last-match-wins: two CODEOWNERS entries matching one path → the later entry's owner is chosen (delegated to `get_owners_for_path`; asserted here so a future refactor cannot lose it). |
| **R11** | Determinism: the same changed-file set in three different input orders yields the same login. |
| **R12** | **The "must not widen" pin, predicate level.** `evaluate_reviewer_trigger` over the full cross product `{SAFE, LOW, MEDIUM, HIGH, CRITICAL} × {protected file, non-protected file}` with `ceiling == "HIGH"` — ten explicit rows, each asserting `triggered` **and** which of the three booleans caused it. The six non-protected, at-or-below-ceiling cells must all be `triggered == False`. This table is the mechanical statement of the ruling's scoping; changing a cell requires editing the test, which is the point. |

### 8.3 `tests/framework/test_overseer_verdict_artifact.py` — document-level

Mirrors `tests/framework/test_agent_invocation_migration.py`'s style: read the agent definition, look only at instruction lines, assert structure.

| ID | Assertion |
|---|---|
| **D1** | Each of the four step-6 disposition bullets in `.claude/agents/overseer.md` names `pr_review.sh submit-verdict`, and no disposition bullet names `post_comment.sh` as its verdict artifact. |
| **D2** | `.claude/agents/overseer.md` contains no `"reviewers"` JSON literal and no occurrence of `ScottThurlow` inside a JSON payload, a `--reviewer` argument, or a `human_reviewer=` assignment. (Prose glosses of the form ``HUMAN_REVIEWER (`ScottThurlow`)`` are permitted and matched explicitly.) |
| **D3** | The "What you may NEVER do" list has exactly eight bullets; the seven not being changed are byte-identical to a pinned tuple; the protected-surface bullet contains `Merge` and does **not** match the retired string `Approve anything touching a protected surface`. |
| **D4** | **The "must not widen" pin, doc level.** The AUTO_MERGE bullet contains no `request-reviewer` invocation, and contains the explicit "Do NOT request a human reviewer on this path" sentence. |
| **D5** | **The contradiction test.** `docs/FABERIX-ROLES.md` §5's determination-honesty paragraph contains `necessary-not-sufficient` **and** the phrase asserting the approval is given; `overseer.md`'s protected-surface NEVER bullet contains `Merge`. Fails if either document drifts back toward the other's opposite. |
| **D6** | `overseer.md` no longer contains the string `Request reviewer:** no wrapper yet`, and its GitHub-workflow tooling table contains a `pr_review.sh` row. |
| **D7** | `require_overseer_approval.py` does not contain the retired FABERIX quote `MEDIUM and HIGH tier → recommend, do NOT approve` (it must quote the live §5 wording). |

### 8.4 `tests/automation/test_github.py` — two added cases

| ID | Assertion |
|---|---|
| **G1** | `submit_pull_review` calls `_run_gh` with `stdin_json` carrying `event`/`body`/`commit_id`, and with **no** `-f`/`-F`/`--field`/`--raw-field` argument containing `body` — the #752/#1155 `@path` class cannot recur. |
| **G2** | `request_reviewers` likewise; and raises `ValueError` on an `@org/team` token. |

### 8.5 What is NOT tested, and why

No test drives the live GitHub API. Acceptance criteria 1 and 2 of #1657 ("on a protected-surface PR, `require-overseer-approval` passes…") are **observational**, verifiable only on the first real protected-surface PR after this lands. The issue itself notes that this PR will be the last one needing an admin override; the verification step is to confirm on the *next* protected-surface PR that the override was genuinely unnecessary. That belongs in the PR description as a named post-merge check, not in `tests/`.

---

## 9. What must NOT change — stated so a reviewer can check it

1. **The LOW/MEDIUM, non-protected auto-merge path is byte-for-byte unchanged in behaviour.** No reviewer is requested (mechanically impossible — §4.4 step 3 refuses), no new gate is introduced, no new label is applied, the merge call is untouched. The only change on that path is *where the findings narrative is posted* (review body instead of issues comment), which is required by change 1 of the issue and changes no gate. Pinned by **W8**, **R12**, **D4**.
2. **`protected_surfaces.txt`, `.github/CODEOWNERS`, `security_surfaces.txt`, and the merge-authority matrix are untouched.** Which PRs require a human does not change.
3. **`decide_merge_authority()` and every function in `merge_authority.py` are untouched.** The 157 existing library tests stay green and are not modified.
4. **`require_overseer_approval.py`'s logic is untouched** — only the two stale FABERIX quotations in its prose change (§7). Its existing tests stay green.
5. **`require_tier_ceiling.py`, `require_human_approval.py`, `gen_codeowners.sh`, `protected_surfaces.txt` are untouched.**
6. **`post_comment.sh` and `post_review_thread.sh` are untouched.** Only their *documented scope* in `overseer.md` narrows.
7. **`scripts/automation/lib/codeowners.py` is untouched** (§4.5 — the #559 checkpoint is not tripped).
8. **The other seven NEVER-list bullets** in `overseer.md` are byte-identical. Pinned by **D3**.
9. **Merge authority is unchanged.** No new merge path, no new bypass, no change to `OVERSEER_CEILING`, and nothing in this design lets a bot approval satisfy `require-human-approval`.

---

## 10. Ship-set and index maintenance

- `bootstrap/post_comment.sh` and `bootstrap/post_review_thread.sh` are **not** installed into consumer repos today — `hos_install.sh:1882-1894` copies only `get_app_token.sh`, `hos_repo_sync.sh`, `validate_setup.sh`, `apps.env.template`, `sync_apps_env.sh`, and the cron prompts, and `framework_consumer_files.txt` lists neither. `bootstrap/pr_review.sh` and `scripts/automation/pr_review_cli.py` **follow their siblings: not added to the ship-set in this issue.** TD-1357 §8 already owns closing that gap for this whole family in slice 6; adding one file to a ship-set that omits its two peers would produce a consumer install whose `overseer.md` names three wrappers of which one exists. Recorded in §12 (**A5**).
- `SCRIPTS-INDEX.md` must be regenerated: `bash scripts/framework/regen_all.sh`.
- `CLAUDE.md` § "Canonical entry points by task" gains one row — *"Posting an overseer PR verdict or requesting the CODEOWNERS human reviewer → `bootstrap/pr_review.sh`"*. `CLAUDE.md` is a protected surface.
- `bootstrap/overseer-cron-prompt.md:60` currently reads *"Post findings as a PR comment."* → *"Post findings as a PR review verdict (`bootstrap/pr_review.sh submit-verdict`); see `overseer.md` § Verdict events."* A cron prompt that still says "comment" is exactly how the prose/behaviour gap reproduced.

---

## 11. Startup-gap analysis and affected sign-offs

Per the CORE startup-gap rule, every reactive contract change is tested against *"should this have been settled before any code was written against it?"*

| Item | Should it have been settled up front? | Disposition |
|---|---|---|
| The overseer's verdict artifact type | **Yes.** `research/findings/an-enabled-control-can-still-not-cover-its-target.md` (2026-08-02) prescribed the general remedy — *"for each control, enumerate the artifact type it acts on, then enumerate the artifact types each governed actor emits"* — and nobody re-ran it against the approval gate. | This design **is** that reconciliation for the approval gate. #1657 is already labelled `process-gap`; no new `startup-artifact-gap` issue is opened — annotate #1657 instead. |
| `overseer.md:55` vs. `FABERIX-ROLES.md` §5 | **Yes.** Two governance documents have directly contradicted each other since #152's machine-account work, and the contradiction is what made the gate unsatisfiable. | Resolved here by human ruling (§0), with **D5** pinning the resolution mechanically so it cannot silently drift back. |
| VP-10 (the #1215 / #761 marker scans reading the wrong surface) | **Yes**, and it is a *live* defect independent of this design — the third instance of the same class. | Repaired as part of §6.4 rather than deferred; deferring would ship a design that *depends* on a scan which currently matches nothing. |
| The hardcoded `ScottThurlow` in a consumer-facing agent definition | **Yes** — HOS ships `overseer.md` to consumer repos with a different owner. | Fixed at `:352`, `:407`, `:658`; pinned by **D2**. |

**Affected sign-offs.** No prior sign-off is orphaned by this design:
- No code has been approved against the *old* `overseer.md:55` contract in the sense that matters — `:55` governs agent behaviour, not a reviewed artifact, and no merged code asserts the prohibition it removes.
- `require_overseer_approval.py`'s #1426 bypass was approved against a contract this design **satisfies for the first time** rather than changes: its `overseer_posted_any_review()` precondition is unchanged; it simply begins to find records. That prior sign-off **stands**.
- `post_review_thread.sh`'s #1248 sign-off (the "never assert a verdict" constraint) **stands and is reinforced**: this design adds the missing verdict primitive rather than relaxing that constraint.
- `merge_authority.py` and `require_tier_ceiling.py` are untouched; their sign-offs **stand**.
- The one sign-off that does require re-review is `overseer.md`'s own most recent approval, which is re-reviewed as part of this PR by construction (protected surface → human approval).

---

## 12. Items routed elsewhere, and ambiguities flagged rather than silently resolved

**Routed to `architect` — I do not bind these:**

- **A1 — Ownership overlap with ADR-1357 slice 4.** ADR-1357 assigns *"any mutation, any GitHub write, … any refusal path (exit 3)"* to slice 4, and **AD-7** specifies `overseer_merge.sh` performing `POST /pulls/{n}/reviews` (APPROVE) → merge as one atomic unit. Slice 4 is **blocked on ESC-1**, a human escalation with no recorded answer. #1657 is `priority:critical` and every protected-surface PR currently merges by admin override, so waiting is not an option. **My design call:** ship `pr_review.sh` now as a single-purpose write primitive, adopting AD-2's envelope and AD-5's exit-3 refusal semantics verbatim, and record a **forward constraint on slice 4**: `overseer_merge.sh` and `overseer_escalate.sh` must call this primitive (or `pr_review_cli`'s functions in-process) for their approve/comment legs rather than re-implementing the POST — one invocation site, D41. Because AD-7's atomicity is about what the *agent* issues as one command, an internal call preserves it exactly. **What I need from the architect:** confirmation that this is an authorised early landing of a slice-4-adjacent surface rather than a slice violation, and that the forward constraint is recorded against slice 4.
- **A4 — the ARCH-3a deviation** in §4.6 step 3 (the comment-format check can refuse from bash). Deliberate, to avoid forking `comment_format_check.sh`. Confirm or direct otherwise.

**Ambiguities in the ruling — flagged, with the reading I took and why. Each is reversible without redesign:**

- **A2 — "the appropriate event" does not enumerate the events.** I read it as `{APPROVE, COMMENT}` and exclude `REQUEST_CHANGES` (§3.1: a bot `CHANGES_REQUESTED` needs an explicit dismissal to clear, the blocking job is already done by resolvable review threads, and no acceptance criterion needs it). If the architect wants `REQUEST_CHANGES` on the DIRTY path, it is an added enum value plus a dismissal protocol — additive, not structural.
- **A3 — the ruling names two trigger conditions, but three things force HUMAN_REQUIRED.** A **CODEOWNERS-human-owned path that is not on `protected_surfaces.txt`** (SPEC-303b) is a HUMAN_REQUIRED trigger the ruling does not name. I did **not** widen the trigger set to include it, on two grounds: the ruling says "exactly two conditions" and names widening as the failure mode; and GitHub's own `require_code_owner_review` auto-requests the owner on such PRs, so there is no functional gap. If the architect disagrees, it is one extra term in `evaluate_reviewer_trigger` plus one row in **R12** — but it must be a *decision*, not a drift.
- **A3b — CODEOWNERS teams are not requested** (§4.5 step 5). In this repo CODEOWNERS is generated with a single user owner (VP-4), so the path is unreachable here; it is reachable in a consumer install. The fact is surfaced in the payload and `not_verified[]`, and a follow-up issue should be filed for `team_reviewers` support. Named rather than silently handled.
- **A5 — the consumer ship-set** (§10). Deferred to TD-1357 slice 6, consistent with this wrapper's two siblings. If the architect wants it shipped now, all three should ship together.

**Routed to `pm-agent`:** nothing. The one product question — *may the overseer approve a protected-surface PR?* — was answered by the human on 2026-09-14 and is §0.

---

## 13. Self-flag (AGENTS.md Layer 1)

**RISK: HIGH**
**CONFIDENCE: MEDIUM-HIGH**
**BLAST RADIUS:** `.claude/agents/overseer.md`, `docs/FABERIX-ROLES.md`, `CLAUDE.md`, `bootstrap/overseer-cron-prompt.md`, `scripts/framework/require_overseer_approval.py` (prose only), `scripts/oversight/codeowners.py` (one added pure function), `scripts/automation/lib/github.py` (two added functions), two new files, three new test files. Four of these are protected surfaces.

**Change classification: `structural`.** It alters which review verdicts the overseer may record on the highest-risk class of change in the repository. Per CORE, a structural design change is escalated to a human before writing — **that escalation has already occurred and been answered**: the human's 2026-09-14 ruling recorded in #1657 authorises exactly this change and explicitly forecloses re-litigation. This document implements the ruling; it does not extend it. Every place where implementation required a reading beyond the ruling's text is enumerated in §12 rather than absorbed.

**Where confidence is not HIGH:** A1 (slice ownership, needs the architect), A2 (the event enum is my reading), and the §6.4 marker-surface repair, which is a live-defect fix bundled into this change because the design depends on it — a reviewer should check that judgement rather than assume it.

## Human Review Required

1. **A1 — ADR-1357 slice-4 ownership.** Is landing `bootstrap/pr_review.sh` now an authorised early landing of a mutation surface that slice 4 nominally owns, given slice 4 is blocked on the unanswered ESC-1 and #1657 is `priority:critical`? (Architect first; human if the architect declines to bind.)
2. **A2 — the event enum.** Confirm `{APPROVE, COMMENT}` with `REQUEST_CHANGES` excluded, per §3.1.
3. **A3 — the trigger set.** Confirm that a CODEOWNERS-human-owned path that is *not* on `protected_surfaces.txt` does **not** trigger a reviewer request. This is the one place where the ruling's "exactly two conditions" and the system's three HUMAN_REQUIRED triggers do not line up, and getting it wrong in either direction is a calibration error.
4. **Merge of this issue's own fix** touches four protected surfaces and will need the admin override one final time, as #1657 itself anticipates. The named post-merge verification — confirm on the *next* protected-surface PR that the override was genuinely unnecessary — must be carried in the PR description.

---

## 14. Architect ruling (2026-09-23, iteration 1 of 5) — RESOLVED; see ADR-1657

Every item routed in §12 is ruled on in **`docs/v0.7.0/ADR-1657-overseer-review-objects.md`**, which
is **binding** and governs wherever it differs from this document. The cross-ADR consequence for
#1357 build slice 4 is recorded in
**`docs/v0.7.0/ADR-1357-AMENDMENT-1-pr-review-primitive.md`**.

**Status: CLEARED FOR THE CODER, subject to the eleven binding conditions ARCH-1 … ARCH-11
(ADR-1657 §3).** No further `technical-design` iteration is required; the conditions are mechanical.
`code-reviewer` must verify each before sign-off.

Summary of the rulings, with the sections of this document each one amends:

| §12 item | Ruling | Amends |
|---|---|---|
| **A1** — slice-4 ownership | **PROCEED.** Not blocked. **ESC-1 was resolved by the human on 2026-09-11**; §12 A1's premise is false and must be corrected. Slice 4's live gates are ESC-4/ESC-5, both disjoint from this surface. Authorised early landing; forward constraints FC-1/FC-2 recorded in `ADR-1357-AMENDMENT-1`. | §12 |
| **A2** — event enum | **CONFIRMED.** `{APPROVE, COMMENT}`; enum closed. Decisive added ground: above ceiling the wrapper cannot `APPROVE` (G1), so a bot `CHANGES_REQUESTED` there has **no autonomous clearing actor**. | §3.1 stands |
| **A3** — trigger set | **CONFIRMED — do not widen.** In this repo the unnamed third trigger is the **empty set** (CODEOWNERS is generated from `protected_surfaces.txt`). Plus **ARCH-3**: the refusal payload must record `codeowners_human_owned` (observability, not a trigger). | §4.4 |
| **A3b** — teams | **CONFIRMED.** Fold `team_reviewers` follow-up into the same issue ARCH-4 files. | §4.5 |
| **A4** — ARCH-3a deviation | **CONFIRMED.** Recorded as a named exemption in `ADR-1357-AMENDMENT-1` §4. | §4.6 |
| **A5** — ship-set | **CONFIRMED deferred** to TD-1357 slice 6; the PR description must name the gap as pre-existing. | §10 |
| **CODEOWNERS module** | **CONFIRMED `scripts/oversight/codeowners.py`.** The architect's contrary suggestion is **overruled**; verified at `merge_authority_cli.py:659-665`. Consolidation filed as follow-up (**ARCH-4**), not a blocker. | §4.5 |
| **VP-10** | **SPLIT.** The #1215 precheck repair is **in scope** (**ARCH-5**, **ARCH-6**). Reviving the **#761 `prior_overseer_decision`** guard is **out of scope** (**ARCH-7**, **ARCH-8**) — it would add a human gate to the LOW/MEDIUM non-protected path, which acceptance criterion 3 pins as byte-for-byte unchanged. | §3.4, §6.4, §9, §11 |
| **Finding 1** | **VERIFIED REAL** at `merge_authority.py:585-593` vs. `:658`. **I2 is the right fix and is sufficient**, with **ARCH-9/10/11**. | §4.4 |
| **PR shape** | **ARCH-2: two sequential PRs**, wrappers before prose. 16 files exceeds `docs/PR-SIZE-POLICY.md`'s 15-file split trigger. | §10 |

**Corrections required to this document before coding** (mechanical; no new iteration):
§12 A1's ESC-1 premise (ARCH-1); **§9 claim 1 and §11's VP-10 row, which are false as written once
ARCH-7 applies**; §3.4's `"(where applicable)"` (ARCH-6); the `:407`/`:408` precheck clause (ARCH-5);
§4.4 I2 and test W12 (ARCH-9); §10's PR shape (ARCH-2). One factual correction with no ruling
attached: the #1426 bypass "can never fire" is overstated — see ADR-1657 §3.
