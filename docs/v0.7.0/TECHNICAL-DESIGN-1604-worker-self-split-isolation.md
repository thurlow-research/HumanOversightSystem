# TECHNICAL DESIGN — ADR-1604: per-issue timeout isolation, bounded split-or-escalate, and the five slices that must not become one issue

**Status:** DRAFT-1 — awaiting `architect` review (iteration 1 of a 5-round cap). This document is the
implementation contract for ADR-1604. It **corrects two items in the ADR at the implementation level**
(§0 TD-VF-5 — one marker is not enough; §6 — the ADR's Phase 0 ships a counter with no reader) and
**re-derives every cited anchor against `origin/main`**, because both upstream documents cite a stale
copy of `bin/hos-cron` (§0 TD-VF-1). It contains no application code.
**Date:** 2026-09-13 (verification pass and drafting, 2026-09-12→13)
**Author:** technical-design
**Baseline:** `origin/main` = **`8129b321825539428930f20c448046f488809cc8`**. The §0 verification pass
was performed at `58b4785a`; `main` advanced to `8129b321` mid-session, and
`git diff 58b4785a..8129b321` touches **only** the two #1604 design documents — **zero code changes**,
so every §0 finding and every line number below stands unchanged at `8129b321`. All line numbers are
that commit's blob, verified by `git show origin/main:<path>` — **not** a working-tree read
(§0 TD-VF-1).
**Consumes:** `docs/v0.7.0/ADR-1604-worker-self-split-isolation.md` (architect, PR #1611, merged as
`88864968`); `docs/v0.7.0/REQUIREMENTS-1604-worker-self-split-isolation.md` (pm-agent, PR #1610,
merged as `12950279`) — both verified byte-identical to the branch copies this design was written
against; issue #1604 body and **all six** of its comments; #1601 body and **both** of its amendment
comments.
**Consumer:** the autonomous `worker`, via **five** `needs-ai` issues in v0.7.0 (§6). Never one issue.
**Scope note:** this document says *what the code must do*. It specifies contracts — file paths,
function signatures, grammars, state-file formats, orderings, exit codes, acceptance criteria — and
no implementation.

---

## Rulings taken as given, not re-litigated

Two decisions were made after the ADR was written and are binding here:

1. **Rung 2's consecutive-timeout threshold is 3** — the technical floor, chosen by the human over the
   architect's recommended 4 (#1604 comment 2026-09-12T23:47:29Z, resolving ESC-1). Default **and**
   floor are both 3 (§4.4).
2. **Worker-filed split sub-issues are NOT autonomously selectable yet** (same comment, resolving
   ESC-2). They are filed `needs-human` and stay there until ADR-1540's AD-2 enumerated
   machine-filing-marker framework lands. **No bespoke trust-inheritance mechanism is built here** —
   that would be a second implementation of the same concept, the #1574 shape. Phase 4 is gated on
   this; Phases 0–3 are not (§6).

Also not re-opened: role-scoped suspend (ruled: no, VF-3 closed); D-1/D-2/D-3; attribution belongs to
#1601 (Q1); a human clear resets the count (Q3). AD-1 through AD-12 bind except where §0 identifies a
premise that does not survive re-derivation, which is flagged as such and routed to the architect.

---

## 0. Verification findings — every ADR premise re-derived against `origin/main`

### TD-VF-1 (CRITICAL, process) — both upstream documents cite a `bin/hos-cron` that is 826 lines behind `origin/main`. Every line number in the ADR and the requirements is wrong.

`origin/main:bin/hos-cron` is **2159 lines**. The file this session's working tree carries — and which
every line number in both upstream documents resolves against exactly — is **1442 lines**, and
`git diff origin/main -- bin/hos-cron` reports **109 insertions, 826 deletions**. The working tree is
clean (`git status --short bin/` is empty), so this is not a local edit: the current branch's merge
base with `origin/main` is `62ee3de2`, and six commits touching `bin/hos-cron` have landed on `main`
since — `95438835` (#1265), `f4753e73` (#1526), `11dd0093` (#1522), `131f77bc` (#1510), `f6bf88ad`
(#1496), `159a7288` (#1498).

The pm-agent and architect anchors map as follows. **Use the right-hand column.**

| Anchor | Cited (stale, 1442-line file) | Actual (`origin/main`, 2159 lines) |
|---|---|---|
| `_SUSPEND_FILE` definition / early-exit check | `:199` / `:200` | **`:263` / `:264`** |
| `HOS_CYCLE_ID` mint + export | `:296` | **`:350` / `:359`** |
| `_audit()` helper | `:298-301` | **`:362-365`** |
| `_GATE_CANDIDATES` query (uses `next_candidates.jq`) | `:1199-1213` | **`:1134-1146`** |
| No-work-cycle early `exit 0` | `:797` | **`:1160-1164`** |
| Post-kill `exit 124` block | `:1237-1300` | **`:1935-1998`** |
| `_tb_state` / `_tb_max` | `:1248` / `:1249` | **`:1946` / `:1947`** |
| `_audit cycle-claude-timeout` | `:1239` | **`:1937`** |
| `_audit cycle-timeout-breaker-tripped` | `:1270` | **`:1968`** |
| #1435 rationale comment to update (ADR §5) | `:1241-1247` | **`:1939-1945`** |
| Clean-exit bookkeeping / `_tb_state` clear | `:1355` | **`:2072` / `:2077-2079`** |
| Usage-limit breaker | `:1306-1352` | **`:2004-2069`, and COMMENTED OUT — see TD-VF-2** |
| `_sync_audit_logs` call | `:1431` | **`:2148`** |
| `_build_context` | — | **`:1822-1904`** |
| `NEW WORK: ALLOWED` / `STOP —` directive lines | `:1190-1197` | **`:1864-1881`** |

**I re-derived every load-bearing *semantic* premise against the real blob and they all hold**:
the breaker's shape and its two-line state file (`:1946-1958`), the `hos-suspend --project` call with
no `--until` (`:1963`), fail-closed dedup on the filed issue (`:1976-1996`), the clean-exit clear +
auto-close (`:2072-2093`), `next_candidates.jq`'s single `needs-human` filter, and AF-4.1's ordering
(no-work `exit 0` at `:1163` precedes the `_tb_state` clear at `:2079`). **Only the coordinates moved.**

*Why this matters beyond tidiness:* this is CLAUDE.md's stale-base hazard occurring inside the design
chain rather than inside a PR, where no `git diff --stat origin/main...` check exists to catch it. An
implementer handed the ADR and told to "edit `bin/hos-cron:1248`" would edit the middle of the #1498
branch-reap sweep. **ESC-A** proposes the systemic fix.

### TD-VF-2 (HIGH) — the usage-limit breaker is **commented out**, so the ladder has two automatic project-wide brakes today, not three.

`origin/main:bin/hos-cron:2004-2069` is a `# ── DISABLED 2026-09-01 (operator request) ──` block. The
whole #1446 breaker is commented out, not deleted, because its detection is a case-insensitive grep
over the session's own transcript and "documenting the breaker can trip the breaker". ADR AD-6 says
"The usage-limit breaker (`:1306-1352`, #1446) is **untouched**" and treats it as a live third brake.
It is untouched — and inert.

**Design consequence, which strengthens rather than weakens the human's ruling:** after this change,
the only automatic project-wide stops are rung 2 (consecutive attribution-blind timeouts) and rung 3
(stuck-issue ceiling). Rung 2 is therefore the *sole* remaining automatic backstop for a systemically
broken worker that cannot even reach branch creation. That is a direct argument for the human's choice
of **3 over the architect's recommended 4**: every unit of headroom added to rung 2 is now unbacked by
any other first-detection brake. The ruling stands and is reinforced. **Nothing in this design
re-enables #1446**, and no phase touches that block.

### TD-VF-3 (HIGH) — AF-3 confirmed and sharpened: adding `issue=` is **not** a schema bump, and making it one would break PR submission.

`bootstrap/lib/branch_ownership.sh` confirmed: the record is five keys, `issue` is absent. But the
validity check in `hos_bo_verify` has two properties the ADR's phrase "schema bump" obscures:

1. **Unknown keys are not rejected.** The grammar loop accepts any line matching `^[a-z_]+=.*$`, and
   the required-key loop iterates a fixed list (`schema branch cycle_id role created_at`) asserting
   each appears *exactly once*. A sixth `issue=1604` line passes unchanged. Old records (no `issue`)
   and new records (with `issue`) are both valid under both old and new code.
2. **`schema` is hard-pinned to the literal `"1"`**: `if [[ "$schema_v" != "1" ]]; then
   HOS_BO_REASON="malformed"`. Writing `schema=2` while leaving that check makes **every** new record
   invalid, which breaks two things at once — `create_branch.sh`'s idempotent re-entry (Step 3,
   `:110-118`) and `bootstrap/submit_pr.sh:170`'s P2 refusal predicate. The worker would create
   branches and then be unable to open any PR.

**BINDING:** `issue=` is added as an **optional sixth key with `schema=1` unchanged**. It is written
on every new record and read as optional-absent. No `schema` value changes in this design, and no
phase touches the `schema_v != "1"` comparison. A test asserts a record without `issue=` still
verifies (records up to 30 days old predate the change and must not become refusals).

### TD-VF-4 (HIGH) — a `cycle_id` scan can match more than one record, and the ADR does not say what to do then.

AD-3.2 resolves the cycle's issue "by scanning the ownership store for the record whose `cycle_id`
equals the exported `HOS_CYCLE_ID`". Three facts make "the record" not necessarily singular:

- `create_branch.sh` may legitimately be called more than once per cycle. Nothing forbids it, and
  `--from <ref>` exists precisely to create a *second* branch at the tip of a prior one.
- Records persist for 30 days (`find ... -mtime +30 -delete`, written on every record write), so the
  store routinely holds hundreds.
- `HOS_CYCLE_ID` is `${ROLE}-${PROJECT}-${ts}-$$` (`:350`), second-precision plus PID. Collision
  across *different* cycles is improbable but not impossible, and the #1002 stale-lock reclaim can
  genuinely put two same-role cycles on one `REPO_ROOT`.

**BINDING resolution order** (§3.3): filter to records with `cycle_id == $HOS_CYCLE_ID`; then
(a) 0 matches → **unattributed**; (b) all matches carry the same `issue=` value → that value;
(c) matches carry *different* `issue=` values → **unattributed**, never a guess; (d) any match lacks
an `issue=` key → treat as a distinct value, so mixed old/new records land in (c) → unattributed.
"Unattributed" routes to rung 2 unchanged (AD-6, FR3). This satisfies FR1's "never a wrong issue
number" literally. The branch name is used only as a corroboration assertion in tests, never as a
fallback attribution source (AD-3.2: parsing a name is weaker than reading a field).

### TD-VF-5 (HIGH) — **AD-5's single marker is not sufficient: a successful split can trip rung 3.** Two markers are required.

AD-5 makes one narrow marker "the **sole** basis for the FR19 live count and the **sole** basis for
this mechanism's queue exclusion". AD-10 separately requires FR12's blocked children to be held out of
the queue. If both use the same marker, blocked children are counted by rung 3.

Reachable failure: one parent splits into four children with three dependencies → three children
carry the exclusion marker → rung 3's live count (threshold 3, D-2) reads 3 → **the project suspends
because a split succeeded.** Two splits with two dependencies each reach it as well. This is a
false-positive project-wide suspend produced by the mechanism working correctly, which is precisely
the harm #1604 exists to remove.

**BINDING correction:** two distinct markers with different semantics.

| Marker | Applied when | Excluded from queue | Counted by rung 3 | Cleared by |
|---|---|---|---|---|
| `timeout-stuck` | this mechanism concluded no further autonomous attempt should be made | **yes** | **yes** | a human removing it |
| `blocked` | a declared blocker sub-issue is still open | **yes** | **no** | the reconcile sweep, automatically |

Everything AD-5 says about the stuck marker — sole basis for the count, sole basis for clearing,
generic `needs-human` applied alongside as advisory and never counted, no spelling in policy logic —
applies unchanged to `timeout-stuck`. `blocked` is an exclusion-only marker with an automatic
clearer. **Routed to `architect` as an amendment to AD-5, not a unilateral change** (§8, ESC-B);
the design is written to the corrected form because the uncorrected form has a demonstrated
false-positive path.

### TD-VF-6 (MEDIUM) — AD-3 adds a network write to a script that today makes none; the token it needs is already in the environment.

`bootstrap/create_branch.sh` at `origin/main` is pure local git + filesystem: no `gh`, no `curl`, no
token. AD-3.1's "application of the active-work marker to that issue" makes it a GitHub writer.

Verified: `bin/hos-cron:833-841` sources `get_app_token.sh --app "$ROLE"` output into the cycle
environment, and `get_app_token.sh:211` emits `export GH_TOKEN='…'`. That export is inherited by the
headless `claude` subprocess and therefore by `create_branch.sh`, whose own Step-1 guard already
refuses to run outside a cron cycle. **So no new token mint is introduced** — the marker write uses
the cycle's existing credential.

**BINDING:** the marker write is **best-effort and never fails branch creation**. A branch the worker
cannot create is a cycle that does nothing; a marker it cannot apply costs only visibility, because
the ownership record — which is mandatory and local — is the primary attribution source (AD-3.2). On
failure: emit `branch-marker-failed` via `hos_bo_audit_refusal`'s existing best-effort path and
continue. The record write stays mandatory and unchanged.

### TD-VF-7 (MEDIUM) — **there is no inlined jq twin.** The worker prompt `cat`s the canonical filter, so AD-5's "lock-step" burden is smaller and differently shaped than stated.

AD-5 binds the new exclusion to `next_candidates.jq` "**and** its inlined twin in
`bootstrap/worker-cron-prompt.md`, in lock-step". `origin/main:bootstrap/worker-cron-prompt.md:100-101`
is:

```
gh api "repos/thurlow-research/HumanOversightSystem/issues?state=open&milestone=@@MILESTONE_NUMBER@@&labels=needs-ai&per_page=100" \
  --jq "$(cat scripts/automation/lib/next_candidates.jq)"
```

It reads the canonical file. There is no second copy of the filter to keep in step — only the **query
parameters** are written twice, and `tests/automation/test_next_candidates.py::TestBothSelectionPathsAgree`
pins exactly those (`state=open`, `labels=needs-ai`, `per_page=100`) plus a substring assertion that
both files name the filter path. It does **not** compare filter text, because there is no second text.

**BINDING consequence:** express both new exclusions **inside the `.jq` filter only**, and **do not
change the query parameters**. Both selection paths then inherit the exclusion with a one-file edit,
and the existing divergence test keeps guarding the only thing that can still diverge. A server-side
`labels=-timeout-stuck` exclusion is **forbidden** — it would require changing the query string in two
files and would leave the jq unable to defend itself.

### TD-VF-8 (MEDIUM) — the existing breaker's own issue carries `needs-ai`, so the stuck count must not be derived from the candidate query.

`bin/hos-cron:1985` files the breaker issue with `--label "needs-human,needs-ai"`. #1597 therefore
matches the candidate query (`labels=needs-ai`) and is removed only by the jq's `needs-human` filter.
**BINDING:** rung 3's live count is its own query — `issues?state=open&labels=timeout-stuck&per_page=100`,
unscoped by milestone — and is never derived from `_GATE_CANDIDATES`. Reusing the candidate query
would both miss stuck issues outside the target milestone and silently depend on `needs-ai` being
present.

### TD-VF-9 (MEDIUM) — #1601's title and body still describe the overturned design; only its comments carry the correction.

`#1601` reads, verbatim in its body today: *"matching the `bounce_count(cid) >= 2` pattern … reuse
that pattern's structure rather than inventing a new one"* and *"#1353's interim mitigation … is the
current minimum-viable form"*. Both are overturned — the first by AF-1 (`record_pr_bounce` has eight
test call sites and zero non-test callers), the second by VF-6 (the mitigation is not in the code).
The corrections exist only as two comments (2026-09-12T23:12:20Z and T23:24:12Z). The title still
reads *"reusing the bounce_count pattern (R3)"*.

An implementer who reads the body and skims the comments builds the dead pattern. **BINDING
precondition on Phase 0:** #1601's **body and title** must be rewritten (via
`bootstrap/edit_issue.sh --number 1601 --body-file …`) to state the AD-2/AD-3 mechanism before the
issue is picked up. §6 lists this as Phase 0's entry gate. Routed to the orchestrating session
(§8, ESC-C).

### TD-VF-10 (LOW) — ESC-3's lost audit write is real and still has no issue; I could not root-cause it either.

`scripts/oversight/lib/audit_log.py` writes write-once, content-addressed records
(`<ts>-<event>-<sha256[:12]>.json`), with the filename timestamp derived from the event's own
`timestamp` field. Two *distinct* events cannot collide on a filename, so a hash collision is not the
explanation for the missing `cycle-timeout-breaker-tripped` record. Beyond excluding that, I did not
diagnose it. **AD-4 makes this design independent of the answer** — no decision reads an audit event —
and §8 ESC-D re-routes the issue-filing request.

### Verification gaps I could not close

- **Local state directories.** `~/.hos/timeout-breaker/`, `~/.hos/suspend/`, `~/.hos/issue-timeouts/`
  on the Worker clone were not inspected. All claims about them derive from the code.
- **Cron logs** under `.local/log/` remain outside read scope.
- **Whether the two #1597 cycles reached branch creation.** Unchanged from the ADR. AD-3's
  coverage on the exact historical incident is still unknown, which is why §4.4's rung 2 must
  survive as an attribution-blind counter.

---

## 1. Canonical names and grammars (binding — nothing below may re-spell these)

### 1.1 Labels

Defined **once**, in a new `scripts/automation/lib/hos_labels.sh`, as `readonly` shell variables:

| Variable | Value | Meaning |
|---|---|---|
| `HOS_LABEL_ACTIVE_WORK` | `in-progress` | a cycle opened a branch for this issue and has not cleanly finished (AD-3) |
| `HOS_LABEL_TIMEOUT_STUCK` | `timeout-stuck` | this mechanism concluded no further autonomous attempt (AD-5) |
| `HOS_LABEL_BLOCKED` | `blocked` | a declared blocker sub-issue is open (TD-VF-5, FR12) |
| `HOS_LABEL_HUMAN` | `needs-human` | the generic human-attention label — advisory here, never counted |
| `HOS_LABEL_AI` | `needs-ai` | the generic autonomous-selection label |

`scripts/automation/lib/labels.py` **parses that file** (regex `^readonly HOS_LABEL_([A-Z_]+)="([^"]+)"$`)
rather than restating the values, so Python and Bash cannot drift. FR25 is satisfied by one
authoritative definition plus **exactly one pinned mirror**:

- **`scripts/automation/lib/next_candidates.jq`** must hard-code the two exclusion spellings, because
  `gh api --jq` accepts no `--arg` and both call sites `cat` the file without one (TD-VF-7). A test
  (`test_next_candidates.py::test_jq_label_literals_match_hos_labels`) asserts the literals in the jq
  equal the values in `hos_labels.sh` and fails on divergence.

No other file may contain these string literals outside a test fixture. A grep-based test enforces it.
`#1520`'s `needs-ai` → `needs-worker`/`needs-overseer` rename becomes an edit to `hos_labels.sh` plus
the pinned jq mirror, and nothing else.

**`in-progress` is explicitly NOT an exclusion label.** A leftover marker means "one attempt did not
finish", which is below the D-3 threshold; excluding on it would park every issue on its *first*
timeout and silently make D-3 unreachable.

### 1.2 State files

Both under `_HOS_DIR = ${HOS_STATE_DIR:-$HOME/.hos}`.

- **Existing, rung 2:** `timeout-breaker/${ROLE}-${PROJECT}` — two lines (attempts, cap). Format and
  semantics unchanged; only `_tb_max`'s default changes (§4.4).
- **New, rung 1:** `issue-timeouts/${ROLE}-${PROJECT}-${ISSUE}` — **three** LF-terminated lines:

  ```
  <attempts>        integer >= 1
  <cap>             the HOS_CRON_MAX_SECONDS this was counted at
  <stuck>           "0" or "1" — has this issue ever been marked timeout-stuck
  ```

  Line 3 exists solely to make Q3's reset correct (§4.5). This is `_tb_state`'s proven shape re-keyed,
  per AD-2 — **not** derived from the audit stream. `${ISSUE}` is digits-only by construction.
  Directory created alongside the existing `mkdir -p` at `:243`.

  *Accepted and deliberate (AD-2):* per-clone, lost on clone rebuild, loss direction is "one extra
  attempt". Do not promote it to a cross-clone store.

### 1.3 The tracking block (AD-8, AD-10) — grammar

One HTML comment in the **parent** issue's body. Fail-closed: any deviation from this grammar means
the sweep does nothing for that issue.

```
<!-- hos:tracking-block v1
parent: 1354
child: r1-checkpoint = #1602
child: r2-streaming = #1603
child: r3-detection = #1601
child: r4-budget = -
dep: r3-detection blocks r4-budget
independent: r1-checkpoint, r2-streaming
-->
```

Rules (all mandatory; violation of any → **parse failure**):

1. Opening line exactly `<!-- hos:tracking-block v1`; closing line exactly `-->`. **Exactly one**
   block per body; two or more → parse failure.
2. `parent:` — exactly once, digits, must equal the issue's own number.
3. `child:` — **at least 2** occurrences, `child: <slug> = <#N | ->`. `-` means "not yet filed"
   (AD-8's resumability). Slugs match `^[a-z0-9][a-z0-9-]{0,39}$` and are unique within the block.
4. `dep:` — zero or more, `dep: <slug> blocks <slug>`. Both endpoints must be declared slugs; no
   self-dependency; the resulting graph must be **acyclic**.
5. `independent:` — **exactly once**, value `all`, `none`, or a comma-separated slug list. Absence is
   a parse failure, not an assertion of independence (AD-10). Every slug must appear in exactly one of
   `independent:` or at least one `dep:`.
6. Unknown keys → parse failure. No `eval`, no code path that executes block content.

**FR11's both-sidedness is satisfied by rendering, not by duplicate declaration.** One `dep:` line is
the single source; the reconcile sweep maintains a rendered statement on **both** issues — on the
dependent, "Blocked by #A until it closes"; on the blocker, "#B is waiting on this". Two independent
declarations could disagree; one declaration rendered twice cannot. This is a deliberate reading of
FR11 ("stated on B and on A") as a requirement about what a reader can find, not about where the
authority lives. Recorded here so a reviewer does not read it as non-compliance.

### 1.4 Audit events (AD-4 — emitted for observability; **no decision may read one**)

| Event | Fields (beyond `event`, `role`, `timestamp`) | Emitted by | Phase |
|---|---|---|---|
| `cycle-claude-timeout` | **`issue=<N|unknown>`** added to the existing `limit=` | `bin/hos-cron` post-kill | 0 |
| `issue-timeout-attributed` | `issue`, `attempts`, `cap` | `timeout_attribution.py` | 0 |
| `issue-timeout-unattributed` | `reason=no_record\|ambiguous` | `timeout_attribution.py` | 0 |
| `issue-marked-stuck` | `issue`, `attempts`, `decision=no_split`, `reason` | `timeout_policy.py` | 1 |
| `issue-stuck-cleared` | `issue` (Q3 reset observed) | `timeout_policy.py` | 1 |
| `cycle-stuck-ceiling-tripped` | `stuck_count`, `threshold`, `issues=<csv>` | `timeout_policy.py` | 1 |
| `tracking-parent-closed` | `parent`, `children=<csv>` | `reconcile.py` | 2 |
| `tracking-block-unparseable` | `issue`, `reason` | `tracking_block.py` | 2 |
| `sub-issue-unblocked` | `issue`, `blocker` | `reconcile.py` | 3 |
| `issue-split` | `parent`, `children=<csv>` | `split_plan.py` | 4 |
| `sub-issue-filed` | `parent`, `slug`, `issue` | `split_plan.py` | 4 |

All go through the existing `_audit` → `scripts.automation.lib.cycle_log` path (`:362-365`), which
already swallows errors. **FR22/AD-4's strengthened test requirement:** each phase ships at least one
test that drives one of its events through the **real** `audit_log.write_event` path and reads it back
**from a separate process** via `read_stream`, and that fails if the write is skipped. Mocking the
store does not satisfy it.

---

## 2. Component map

| # | Component | Path | Phase | Status |
|---|---|---|---|---|
| A | Label constants (shell) | `scripts/automation/lib/hos_labels.sh` | 0 | new |
| B | Label constants (Python view) | `scripts/automation/lib/labels.py` | 0 | new |
| C | Ownership record `issue=` key | `bootstrap/lib/branch_ownership.sh` | 0 | changed |
| D | Marker write + issue in record | `bootstrap/create_branch.sh` | 0 | changed |
| E | Attribution + per-issue counter | `scripts/automation/lib/timeout_attribution.py` | 0 | new |
| F | Post-kill + clean-exit wiring | `bin/hos-cron` | 0 | changed |
| G | Policy engine (three rungs, Q3) | `scripts/automation/lib/timeout_policy.py` | 1 | new |
| H | Queue exclusion | `scripts/automation/lib/next_candidates.jq` | 1 | changed |
| I | Pre-work policy gate + rung-2 default | `bin/hos-cron` | 1 | changed |
| J | Tracking-block parser | `scripts/automation/lib/tracking_block.py` | 2 | new |
| K | Reconcile sweep (auto-close half) | `scripts/automation/lib/reconcile.py` | 2 | new |
| L | Convention doc | `docs/TRACKING-BLOCK.md` | 2 | new |
| M | Reconcile sweep (unblock half) | `scripts/automation/lib/reconcile.py` | 3 | changed |
| N | Split plan validation + filing | `scripts/automation/lib/split_plan.py` | 4 | new |
| O | Split-assessment prose | `bootstrap/worker-cron-prompt.md`, `.claude/agents/worker.md` | 4 | changed |

**Every phase touches at least one protected surface** (`bin/**`, `bootstrap/**`, `.claude/agents/**`
per `scripts/framework/protected_surfaces.txt`), so **every phase's PR requires human approval**
regardless of computed risk tier. No phase can be bot-merged. This is a scheduling fact the filed
issues must state.

---

## 3. Phase 0 components — attribution, made visible

### 3.1 Component C — `bootstrap/lib/branch_ownership.sh`

- `hos_bo_write_record` gains a **sixth, optional** emitted line `issue=<N>`, written when
  `HOS_CYCLE_ISSUE` is set and matches `^[0-9]+$`. Placed after `role=` and before `created_at=`
  (ordering is cosmetic; nothing parses positionally).
- `schema=1` is **unchanged** (TD-VF-3). The `schema_v != "1"` comparison is **not touched**.
- `hos_bo_verify` is **unchanged**: the required-key loop still asserts the five original keys appear
  exactly once, and unknown keys are already tolerated. A record with `issue=` and a record without
  both verify.
- New reader `hos_bo_issue_for_cycle <repo_dir> <cycle_id>`: scans `*.rec` in the store, selects
  records whose `cycle_id=` line equals `<cycle_id>`, applies TD-VF-4's resolution order, and echoes
  either `<N>` (exit 0) or nothing (exit 1, `HOS_BO_REASON` ∈ `no_record|ambiguous`). It `grep`s
  record lines; it never sources or `eval`s a record, matching the library's existing contract.
- Header documentation updated: record format, the optional key, and an explicit note that `issue=`
  is **not** a resume/completion signal (the ADR-037 AD-2 anti-loophole must survive this change —
  the record still says "this cycle owns this branch", never "this work is done").

**Invariant the coder must preserve:** `branch_ownership.sh` remains a function-only library with no
top-level side effects and no network access.

### 3.2 Component D — `bootstrap/create_branch.sh`

Two forced side effects, both keyed off the already-mandatory `--issue <N>`:

1. Export `HOS_CYCLE_ISSUE="$ISSUE"` before the Step-4 `hos_bo_write_record` call, so the record
   carries the issue. **Record-first ordering is preserved exactly** (AF-5): record, then branch, then
   marker. If `git checkout -b` fails, the existing Step-5 rollback removes the record; the marker is
   applied only after a successful checkout, so a rolled-back branch leaves no marker.
2. After Step 5 succeeds, apply `$HOS_LABEL_ACTIVE_WORK` to issue N via
   `bash bootstrap/edit_issue.sh --number "$ISSUE" --add-label in-progress --app worker`, using the
   cycle's inherited `GH_TOKEN` (TD-VF-6). **Best-effort:** on failure, warn to stderr, emit
   `hos_bo_audit_refusal … "marker_write_failed"`, and **exit 0 with the branch intact**. The branch
   name remains the only stdout line (Step 6's contract is unchanged — a second stdout line would
   break every caller).

The Step-1 cycle-identity guard already prevents an interactive session reaching either side effect.

### 3.3 Component E — `scripts/automation/lib/timeout_attribution.py`

Pure, unit-testable, no agent in the path. CLI-invoked once per concern so the shell call sites stay
single, literal commands.

```
python3 -m scripts.automation.lib.timeout_attribution resolve \
    --repo-root <path> --cycle-id <id>
    → stdout: "<N>" | ""        exit: 0 attributed | 1 unattributed
      stderr: reason on exit 1  (no_record | ambiguous)

python3 -m scripts.automation.lib.timeout_attribution record-timeout \
    --state-dir <p> --role <r> --project <p> --issue <N> --cap <secs>
    → stdout: "<attempts>"      exit: 0
      Reads issue-timeouts/<role>-<project>-<N>; if line 2 == cap, attempts+1,
      else attempts=1 (the "raising --max-seconds is never a trap" property,
      copied from _tb_state's cap comparison at :1954-1958). Preserves line 3
      (stuck) across the write; creates it as "0".

python3 -m scripts.automation.lib.timeout_attribution clear-marker \
    --repo-slug <s> --issue <N>
    → removes the active-work label. Best-effort, exit 0 always.

python3 -m scripts.automation.lib.timeout_attribution read-count \
    --state-dir <p> --role <r> --project <p> --issue <N>
    → stdout: "<attempts> <cap> <stuck>"   exit: 0 (prints "0 0 0" if absent)
```

`resolve` re-implements TD-VF-4's order in Python (it is the reader used by `hos-cron`; the shell
`hos_bo_issue_for_cycle` in Component C is the same algorithm for callers already inside the shell
library). **A test asserts the two implementations agree on a shared fixture set** — two
implementations of one rule is the #1574 shape, and this test is the cost of paying it deliberately.
If the architect prefers a single implementation, the shell helper is the one to drop; the Python one
is needed for unit testing and for Phases 1–4.

### 3.4 Component F — `bin/hos-cron` (Phase 0 edits, three sites)

1. **Post-kill, inside `if [[ $_claude_exit -eq 124 ]]` — immediately after `:1936`'s log line and
   *before* `:1937`'s `_audit cycle-claude-timeout`.** Call `resolve`; capture the issue or empty.
   Then emit `cycle-claude-timeout` with the added `issue=` field (`<N>` or `unknown`). If attributed:
   call `record-timeout`, emit `issue-timeout-attributed`, and post a comment on the issue via
   `bootstrap/post_comment.sh --number <N> --body-file <path> --app worker` naming the cap, the
   attempt count, and that no work was committed. If unattributed: emit
   `issue-timeout-unattributed`. **The existing `_tb_state` block at `:1946-1958` is not touched in
   Phase 0** — rung 2 continues to behave exactly as today, at its current default of 2.
2. **Clean exit, inside `if [[ $_claude_exit -eq 0 ]]` at `:2072`, before the existing `_tb_state`
   clear.** Resolve this cycle's issue the same way and call `clear-marker`. Deterministic code, never
   the agent (AD-3.3). If unattributed, do nothing — there is nothing to clear.
3. **`mkdir -p` at `:243`** gains `"$_HOS_DIR/issue-timeouts"`.

No other `bin/hos-cron` line changes in Phase 0. In particular `_GATE_CANDIDATES`, the no-work exit,
and `_build_context` are untouched.

---

## 4. Phase 1 components — isolation

### 4.1 Component G — `scripts/automation/lib/timeout_policy.py`

One subcommand, invoked once per cycle from the new pre-work gate:

```
python3 -m scripts.automation.lib.timeout_policy evaluate \
    --repo-slug <s> --state-dir <p> --role <r> --project <p> \
    [--stuck-threshold <n>] [--dry-run]
  → stdout: the directive block (§4.3), possibly empty
  → exit 0  : proceed with the cycle
  → exit 10 : STOP — the caller must suspend the project and exit 0
```

Steps, in order, all deterministic:

1. **Fetch the stuck set.** `issues?state=open&labels=timeout-stuck&per_page=100` (TD-VF-8). On
   **query failure → exit 0 with an empty directive and no state change.** An API blip must never
   suspend a project, and must never clear a counter; the next cycle re-resolves. (Deliberately
   *fail-open* here, unlike the candidate gate's fail-closed dedup — the failure direction of a
   spurious suspend is the harm this whole issue exists to remove.)
2. **Q3 reset (§4.5)** against that set.
3. **Rung 1:** for each `issue-timeouts/<role>-<project>-*` file with `attempts >= D3` and `stuck == 0`,
   mark that issue stuck (§4.2).
4. **Rung 3:** recompute the live count (step-1 set plus anything just marked in step 3). If
   `>= threshold` → emit `cycle-stuck-ceiling-tripped`, return the ceiling directive, **exit 10**.
5. Otherwise return the informational directive and exit 0.

`--dry-run` performs every read and no write, so the whole engine is exercisable against the live
repo without side effects. Required for the test plan and for human inspection.

### 4.2 Rung 1 — marking an issue stuck (FR5, FR8, FR14, FR23)

In Phase 1 there is no split assessment, so AD-7's *"if the judgment errors, times out, returns
anything unparseable, or is skipped, the deterministic code treats it as `NO_SPLIT`"* is the **only**
reachable branch. That is not a gap in Phase 1 — it is AD-7's safe default being the entire behaviour,
which is exactly why Phase 1 ships before Phase 4. Actions, in order:

1. `edit_issue.sh --number <N> --add-label timeout-stuck,needs-human --app worker`.
2. `post_comment.sh` with the **FR23 three facts**: attributed-timeout count and the cap they occurred
   at; *"split assessment: not attempted (not yet implemented — #1604 Phase 4)"*; and whether this
   issue is a sub-issue (Phase 1: always "unknown — tracking blocks not yet implemented"; Phase 2
   upgrades this to a real answer from the parent-side block, per AD-10's split-origin durability).
3. Write `stuck=1` to line 3 of the counter file.
4. Emit `issue-marked-stuck`.

Ordering matters: **label first, comment second.** A crash between them leaves an isolated issue with
a thin explanation (safe); the reverse leaves an explained issue still in the queue (unsafe).

### 4.3 The directive block (AD-1) — `bin/hos-cron` `_build_context`

A new section rendered for `ROLE == worker` only, immediately after the existing
`### New work directive (#1198)` section at `:1881` and before `### Next work candidates` at `:1889`:

```
### Timeout policy (#1604) — deterministic; already applied, do not re-derive
Stuck issues (excluded from selection): #A, #B      [or "None."]
Marked stuck this cycle: #B (2 attributed timeouts at 1800s)
Stuck-issue ceiling: 2/3
```

Register matches the existing `NEW WORK: ALLOWED` / `STOP —` lines. **The agent is never asked to
check a counter, apply a threshold, or decide anything** (AD-1). Phase 4 extends this section with the
split directive; the section name is bound now so Phase 4 extends rather than invents.

### 4.4 Rung 2 — the existing breaker, re-defaulted

At `origin/main:bin/hos-cron:1947`, `_tb_max="${HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS:-2}"` becomes
**default 3**, with an explicit **floor of 3**: a configured value below 3 is clamped to 3 and a
warning is logged naming the configured value. A floor that can be configured away is not a floor —
below 3, rung 2 fires before rung 1 can ever act and the entire mechanism is dead code (FR20, VF-2).

Everything else about rung 2 is unchanged: the two-line state file, the cap-change reset, the
`hos-suspend --project` call with no `--until`, fail-closed dedup on the filed issue, the clean-exit
clear and auto-close. **It stays attribution-blind** — that is what catches every unattributable
timeout (FR3) and the *N distinct issues, once each* hole (AD-6).

The #1435 rationale comment at **`:1939-1945`** is rewritten to state the two thresholds' relationship
in the file: rung 1 acts at 2 attributed timeouts on one issue; rung 2 at 3 consecutive
claude-invoking timeout cycles regardless of attribution; the cheap Phase-4 decision cycle exits 0 and
therefore clears rung 2, so in the working case rung 2 never approaches its threshold.

**Recorded, not fixed (AF-4.1, re-derived at `:1163` vs `:2079`):** a no-work cycle `exit 0`s before
the bookkeeping that clears `_tb_state`, so "consecutive" means *consecutive claude-invoking cycles*
and can span arbitrary idle wall-clock — the two timeouts behind #1597 were ~10 hours apart. The
architect declined to fix it here and I concur; it is a separate behavioural change to a shipped
control. **The new per-issue counter must not reproduce it**, and by construction it does not: the
per-issue counter is keyed on the issue, so idle time between two attempts on the *same* issue is
exactly the signal D-3 intends to catch. §8 ESC-E proposes filing the rung-2 case separately.

### 4.5 Rung 3 and the Q3 reset

**Rung 3.** Threshold `HOS_STUCK_ISSUES_MAX`, **default 3, floor 2** (D-2), clamped like rung 2. On
trip: call `bash "$_HOS_CRON_DIR/hos-suspend" --project "$PROJECT" --reason "<N> issues stuck …"`,
file a `needs-human` issue with **fail-closed dedup** on a new title prefix
`[SUSPENDED] ${ROLE} stuck-issue ceiling reached on ${PROJECT}` (mirroring `:1976-1996` exactly — only
file when the query *succeeds* and returns zero), emit `cycle-stuck-ceiling-tripped`, and **`exit 0`
for this cycle** before any work. Doing work and *then* suspending would burn the session the brake
exists to save.

**Rung 3 does not decay** (D-1, affirmed by AD-6). No staleness rule, no time window.

**Auto-close asymmetry, bound because the existing pattern does not transfer:** the clean-exit block
at `:2072` auto-closes the *timeout-breaker* issue unconditionally once `_tb_state` existed. The
stuck-ceiling issue must **not** do that — the condition is a live count, and a cycle completing
normally says nothing about whether three issues are still stuck. Bind: the stuck-ceiling issue is
auto-closed on a clean cycle **only if** the live stuck count is now strictly below the threshold.

**Q3 reset.** For each counter file with `stuck == 1` whose issue is **absent** from the freshly
fetched stuck set, delete the counter file and emit `issue-stuck-cleared`. Files with `stuck == 0`
are never reset by this rule — an issue that timed out once has no marker to remove, and resetting it
would make D-3 unreachable. Costs zero extra API calls (the set is already fetched). **A human
therefore clears a stuck issue by removing one label, edits no state file, and posts no magic
string** (FR24, AD-5).

Counter files are pruned by mtime at 30 days, best-effort, mirroring `branch_ownership.sh`'s prune.

### 4.6 Component H — `scripts/automation/lib/next_candidates.jq`

The single eligibility `select` gains two exclusions, expressed in the filter only (TD-VF-7); query
parameters are **not** changed:

```
select((.labels // []) | map(.name)
       | (index("needs-human") | not)
         and (index("timeout-stuck") | not)
         and (index("blocked") | not))
```

`blocked` is excluded from Phase 1 onward even though nothing applies it until Phase 3. Shipping the
exclusion ahead of its producer is deliberate and safe: an unproduced label excludes nothing, and it
means Phase 3 needs no edit to the work-selection single-source-of-truth — the one file where a
mistake changes what *every* autonomous cycle picks up. The header comment is updated to name all
three exclusions and their owners.

### 4.7 Component I — `bin/hos-cron` (Phase 1 edits)

**One new section**, inserted between the end of milestone resolution (`:1001`) and the start of the
actionable-work gate (`:1003`), guarded `if [[ "$ROLE" == "worker" && -n "$_REPO_SLUG" ]]`:

```
# ── Timeout policy gate (#1604) ──
_TIMEOUT_DIRECTIVE="$(python3 -m scripts.automation.lib.timeout_policy evaluate …)" || _tp_exit=$?
if [[ ${_tp_exit:-0} -eq 10 ]]; then   # rung 3
    hos-suspend --project …; file the needs-human issue; _audit; exit 0
fi
```

The position is load-bearing and must not move:

- **Before** `_GATE_CANDIDATES` (`:1134`), so an issue marked stuck this cycle is already excluded
  from *this* cycle's candidate query — no special-casing needed anywhere downstream.
- **Before** the no-work early exit (`:1163`), so the policy runs on every worker cycle that gets this
  far, not only on cycles that find work.
- **Before** the git sync (`:1222`) and the inner-loop baseline (`:1464`), so the gate is cheap: two
  GitHub reads and some local file stats, no git and no test run.
- **After** auth (`:833`), the identity guard (`:843`), and milestone resolution (`:974`), so
  `GH_TOKEN` and `_REPO_SLUG` are available.

`$_TIMEOUT_DIRECTIVE` is consumed by `_build_context` (§4.3). Plus the `:1947` default change and the
`:1939-1945` comment rewrite (§4.4).

---

## 5. Phases 2–4 components (contracts; these phases are gated — see §6)

### 5.1 Component J — `scripts/automation/lib/tracking_block.py`

`parse(body: str) -> TrackingBlock | ParseError`. Implements §1.3's grammar exactly. Pure: takes a
string, returns a structure or a typed error, performs no I/O and no network call. Never raises on
malformed input — a `ParseError` carrying a reason class is a normal return value, because
"unparseable" is a state the sweep must handle, not an exception.

`render_block(block) -> str` produces the canonical serialization, so Phase 4's writer and Phase 2's
reader cannot disagree. A round-trip property test (`parse(render(b)) == b`) pins it.

### 5.2 Component K/M — `scripts/automation/lib/reconcile.py`

```
python3 -m scripts.automation.lib.reconcile sweep --repo-slug <s> [--dry-run]
```

One pass per cycle, invoked from the same pre-work gate as §4.7 (immediately after
`timeout_policy evaluate`), over every open issue whose body contains the opening delimiter.

**Phase 2 — auto-close half (FR14, FR15, the 2026-09-12T22:12:14Z requirement).** For each parseable
block: resolve every `child:` with a number; if **all** are `closed` and at least one exists, close the
parent via `edit_issue.sh --state closed` and post a comment naming the children that closed it out.
Do not close if any child is open, if any `child:` is `-`, or if any child number fails to resolve.
**Parenthood is recognised only from the block** — never from prose, cross-references, or titles
(AD-10). Any parse failure → do nothing for that issue, emit `tracking-block-unparseable` once per
`(issue, body-sha256)` so a permanently malformed block cannot spam the trail.

**Phase 3 — unblock half (FR11, FR12).** For each `dep: A blocks B` where A is open: ensure B carries
`blocked` and that both rendered statements are present. Where A is closed: remove `blocked` from B
**unless** some other `dep: * blocks B` is still open, and emit `sub-issue-unblocked`. Ensure
`independent:`-declared children never carry `blocked`. "When A closes, B becomes selectable without
human action" (FR12) is satisfied by the next cycle's sweep.

**AD-10's generalization:** the sweep keys on the block's presence, not on how it got there. A human
pasting a block into #1354 or #1358 gets the behaviour with no code change. One convention, not two.

### 5.3 Component N — `scripts/automation/lib/split_plan.py` (Phase 4)

`validate(plan) -> Plan | Rejection`. **Every rejection is a `NO_SPLIT`** (AD-7). Reject when: the plan
has fewer than 2 children; any child restates the parent (title or body normalized-equal); the block
would not parse; the dependency graph is cyclic; `independent:` is absent (FR11/AD-10); the parent
already carries a tracking block; **or** the plan contains a dependency while Phase 3 is not deployed
(FR13 — split-and-hope is unreachable).

`file(plan)` implements **AD-8's record-first order, non-negotiable**:

1. Write the complete block to the **parent** body, every child `= -`, via
   `edit_issue.sh --body-file`.
2. For each slug with `-`: `create_issue.sh --title … --body-file … --app worker --milestone <parent's>`
   with labels `needs-human` + the parent's `priority:*` (FR14), **and not `needs-ai`** — per the
   ESC-2 ruling, sub-issues are not autonomously selectable. Immediately rewrite the parent's block
   with the new number before filing the next child.
3. Mark the parent: `timeout-stuck` + `needs-human`, removing it from the queue (FR14).

A cycle interrupted anywhere resumes by re-reading the block and filing only the `-` slugs. A block
with no children filed is inert. **No second overlapping set is reachable** (FR9).

Each child body carries a derivation link to the parent (AD-9.1) and the context needed to be worked
without re-reading the parent's history (FR14). **No trust-inheritance mechanism is built** — the
link is a machine-readable fact for #1540's framework to consume later, and confers nothing on its own
(the ESC-2 ruling).

**A sub-issue is never split** (FR15, AD-10): "is this issue a sub-issue?" is answered by its
appearance in some parent's block — parent-side, so relabelling or editing the child cannot erase it
(FR16). A sub-issue reaching D-3 is marked stuck. **No path creates a grandchild.**

### 5.4 Component O — the assessment prose (Phase 4)

The only judgment in the mechanism, and it holds no authority. It runs from the directive block
(§4.3), reads the issue, its comments, and (when present) #1602's checkpoint and #1603's session
record, and returns exactly `SPLIT(<block>)` or `NO_SPLIT(<reason>)`. It may not invoke the
design/review chain, open branches, or run builds (FR6). Anything else it returns — including nothing —
is `NO_SPLIT` and the issue is marked stuck (AD-7).

---

## 6. Build order — five issues, and why the boundaries move slightly

**This section is this document's primary deliverable.** Filing "implement ADR-1604" as one `needs-ai`
issue reproduces #1354 exactly: four requirements bundled into one task, two timeouts, zero commits, a
project-wide suspension.

### 6.1 The correction: the ADR's Phase 0 ships a counter with no reader

ADR §3's Phase 0 is *"`issue=` in the ownership record; `create_branch.sh` applies the active-work
marker; deterministic clear on clean exit; per-issue counter file; resolution of the cycle's issue"* —
and Phase 1 holds every threshold and every consumer. As drawn, **Phase 0 merges a counter that
nothing reads.**

That is the mirror of AF-1, and it matters for the same reason. AF-1's lesson is stated as *"a counter
whose write is an instruction to an agent reads zero forever"*. The general form is: **a counter whose
writer and first reader are separated cannot be shown to work.** Phase 0's counter would be unit-tested
and merged, and its first contact with live data would arrive in Phase 1's PR — where a reviewer sees
only the read side and has no live evidence the write side ever produced a non-zero value. This repo
has already paid that bill twice (#1356's missing caller, AF-2's lost write).

**Correction:** Phase 0 gains a reader **inside its own slice** — a comment posted on the attributed
issue naming the timeout and the running count, plus `issue=<N>` on the `cycle-claude-timeout` audit
event. Both are produced by *reading back* the record and the counter, so the whole write→read→display
path executes on every real timeout from Phase 0's merge onward. Phase 0 becomes observable in
production before any policy depends on it — and it independently delivers #1353's "comment +
attribution on the triggering issue" mitigation, which VF-6 showed was never actually built.

### 6.2 The correction: Phase 1 alone is **not** a working fix for #1597

The task brief asks for an order in which "Phase 1 alone (isolation only) is a complete, mergeable,
working fix for #1597 by itself". **It cannot be, and no re-drawing of the boundary makes it so.**

#1597's harm is that a stuck issue suspended the whole project. Isolating an issue means removing
*that issue* from the queue. Removing that issue requires knowing which issue it was — and
`bin/hos-cron` cannot name it: work selection happens inside the killed Claude session and is written
nowhere the cron can read (VF-6, re-confirmed against `origin/main`). **There is no isolation without
attribution.** The ADR states this correctly ("Phase 0 … **Blocks everything below**"); the brief's
restatement of it does not hold.

The honest answer: **#1597's fix is Phase 0 + Phase 1, two issues, in that order.** Phase 0 is small
and independently valuable; Phase 1 is small and completes the fix. Merging them into one issue to
satisfy "one complete fix" would recreate the bundling this issue exists to prevent. I record the
divergence rather than paper over it.

*One genuinely standalone alternative was considered and rejected:* AF-4.1 means rung 2's "consecutive"
spans arbitrary idle time, so clearing `_tb_state` on a no-work cycle would have reduced #1597's
likelihood with no attribution at all. It is not proposed as Phase 1 because the architect explicitly
declined it here and it changes a shipped control's semantics for reasons unrelated to #1604. §8 ESC-E
routes it separately.

### 6.3 The phases

Each is one `needs-ai` issue, states its dependencies **on both sides** (FR11), and carries a
**pre-declared split seam** — where to cut it if it times out twice — so the mechanism's own
implementation has the answer #1604 is building.

---

#### Phase 0 — attribution, made visible. *(Issue: #1601, rescoped.)*

**Entry gate:** #1601's **title and body** rewritten per TD-VF-9 before pickup.
**Depends on:** nothing. **Blocks:** Phases 1, 4.
**Components:** A, B, C, D, E, F. ~8 files + tests.

**Acceptance criteria**

1. A worker cycle that calls `create_branch.sh --issue N` produces an ownership record containing
   `issue=N` with `schema=1`, and issue N carries `in-progress`.
2. A record **without** `issue=` still passes `hos_bo_verify` (TD-VF-3), and `submit_pr.sh --app worker`
   still opens PRs for both record shapes.
3. A cycle killed with `exit 124` after branch creation emits `cycle-claude-timeout` with `issue=N`,
   increments `issue-timeouts/<role>-<project>-N` to 1, and posts a comment on N naming the cap and
   the count.
4. A second such kill on the same issue at the same cap makes the counter read **2** when read by a
   **separate process** — the FR2 end-to-end test, which must fail if the write is skipped and must
   not pass by mocking the store.
5. A kill **before** branch creation emits `cycle-claude-timeout` with `issue=unknown` and
   `issue-timeout-unattributed`; **no issue is labelled or commented** (FR1, FR3).
6. Two ownership records in one cycle naming different issues → unattributed, not a guess (TD-VF-4).
7. A cycle exiting 0 removes `in-progress` from the resolved issue.
8. A cap change resets the per-issue counter to 1 (the "raising `--max-seconds` is never a trap"
   property).
9. `edit_issue.sh` failing inside `create_branch.sh` leaves the branch created and exit status 0, with
   the branch name as the only stdout line.
10. **No threshold, no exclusion, no suspend behaviour changes.** `_tb_state`'s default is still 2;
    `next_candidates.jq` is untouched; nothing is removed from any queue.

**Independent mergeability:** yes. Purely additive and observable; work selection is unchanged.
**Pre-declared split seam:** 0a = Components A–D (write side: label constants, `issue=` key, marker
application) — independently mergeable and acceptance-testable by criteria 1, 2, 9. 0b = Components
E, F (read side: resolution, counter, comment, audit field) — criteria 3–8, 10.

---

#### Phase 1 — isolation. **This is #1597's fix.**

**Depends on:** Phase 0 (hard — §6.2). **Blocks:** Phase 3 (the `blocked` exclusion seam), Phase 4.
**Components:** A (+2 labels), G, H, I. ~7 files + tests.

**Acceptance criteria**

1. An issue reaching **2** attributed timeouts at an unchanged cap is labelled `timeout-stuck` +
   `needs-human`, receives the FR23 comment, and emits `issue-marked-stuck`.
2. In the same cycle, that issue is **absent** from `_GATE_CANDIDATES`, and the next cycle selects the
   next eligible candidate and completes normally. **`hos-suspend` was not called.** The overseer's
   cycle is unaffected (FR17).
3. Both selection paths exclude it — verified by running the real jq over a fixture and by the
   existing `TestBothSelectionPathsAgree` params test still passing unchanged (TD-VF-7).
4. **Two** simultaneously stuck issues do not suspend the project; a **third** does, via
   `hos-suspend --project` with no `--until`, one fail-closed-deduped `needs-human` issue, and
   `exit 0` before any work.
5. Resolving one stuck issue below the threshold restores normal operation on the next cycle with no
   manual counter reset.
6. **Two timeouts attributed to two different issues do not suspend the project** (FR20) — the single
   assertion that proves this mechanism is not dead code.
7. **Three** consecutive timeout cycles with attribution disabled **do** suspend the project (FR3,
   FR21) — the single assertion that proves the brake was not removed.
8. `HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS=2` is clamped to 3 with a logged warning.
9. Removing `timeout-stuck` returns the issue to the candidate set on the next cycle and resets its
   counter (Q3); an issue with `attempts=1` and no marker is **not** reset.
10. The stuck-set query failing leaves all state unchanged and does not suspend (§4.1 step 1).
11. Three `blocked` issues do **not** count toward rung 3 (TD-VF-5) — asserted now, before Phase 3
    can produce them.

**Independent mergeability:** yes, given Phase 0. Delivers #1597's fix in full.
**Pre-declared split seam:** 1a = Components H + I's `:1947` default/floor change + the `:1939-1945`
comment (rungs 2 and the exclusion filter; criteria 3, 7, 8). 1b = Component G + the pre-work gate
(rungs 1 and 3, Q3; criteria 1, 2, 4–6, 9–11).

---

#### Phase 2 — tracking block + parent auto-close.

**Depends on:** nothing. **Blocks:** Phases 3, 4. **Components:** J, K, L + one `bin/hos-cron` call.
~5 files + tests.

**Acceptance criteria**

1. A parent carrying a valid block whose children are **all** closed is closed on the next cycle, with
   a comment naming them (`tracking-parent-closed`).
2. One open child → **not** closed. A `child: … = -` → **not** closed. An unresolvable child number →
   **not** closed.
3. Every §1.3 grammar violation yields no action, one `tracking-block-unparseable` event per
   `(issue, body-sha)`, and no label or state change (AD-10's "any parse ambiguity → do nothing").
4. An issue with children linked only in prose is **never** closed — parenthood comes from the block
   alone.
5. A block hand-added to #1354 by a human produces the behaviour with no code change (AD-10's
   generalization).
6. `parse(render(b)) == b` for a generated block corpus.
7. `--dry-run` performs zero writes.

**Independent mergeability:** yes — independent of Phases 0 and 1, and independently valuable
(closes #1354/#1358 automatically once a human adds a block). **Zero split behaviour.**
**Pre-declared split seam:** 2a = Components J + L (parser + convention doc; criteria 3, 6). 2b =
Component K + the wiring (sweep; criteria 1, 2, 4, 5, 7).

---

#### Phase 3 — dependency unblock half.

**Depends on:** Phase 2 (grammar + sweep), Phase 1 (`blocked` exclusion already in the jq, and the
labels module). **Blocks:** Phase 4's dependent splits only — **not** Phase 4 itself (§6.4).
**Components:** M + A (`blocked` is already defined in Phase 1). ~4 files + tests.

**Acceptance criteria**

1. With blocker A open, dependent B carries `blocked` and is absent from **every** work-selection path.
2. When A closes, B loses `blocked` on the next sweep and becomes selectable **without human action**
   (FR12).
3. B with two blockers loses `blocked` only when **both** are closed.
4. Both rendered dependency statements are present and are maintained idempotently — re-running the
   sweep posts no duplicates (FR11).
5. A child declared `independent:` never acquires `blocked`.
6. A cyclic `dep:` graph is a parse failure → no action (§1.3 rule 4).
7. `blocked` issues still do not count toward rung 3 (re-asserted against a real producer).

**Independent mergeability:** yes, given Phases 1 and 2.
**Pre-declared split seam:** 3a = `blocked` application/removal + the jq behaviour under a real
producer (criteria 1–3, 5, 7). 3b = the rendered both-side statements (criterion 4).

---

#### Phase 4 — split assessment and filing. **HELD.**

**Depends on:** Phase 2 (block writer), Phase 1 (the stuck marker). **Held by the human's ESC-2 ruling
of 2026-09-12: sub-issues are filed `needs-human` and are not autonomously selectable until ADR-1540's
AD-2 enumerated machine-filing-marker framework lands (#1540, PR #1598).** No bespoke
trust-inheritance mechanism is built here.
**Components:** N, O. ~6 files + tests.

**Acceptance criteria**

1. FR7's fixture set — #1354 (cleanly decomposable; the human's manual split into #1600–#1603 is the
   reference answer), a single-function bug fix (atomic), and an ambiguous issue — produces
   split / no-split / no-split.
2. The ambiguous fixture yields a **stuck** issue and **zero** new issues; no code path can emit a
   child set of size 1 or one whose members restate the parent (FR8).
3. A plan with a dependency, with Phase 3 absent, is `NO_SPLIT` — split-and-hope is unreachable
   (FR13).
4. A split interrupted after the first child is filed resumes and produces **no duplicate** children;
   the end state is a completed split or a clean retry of the same one (FR9).
5. Every child is filed `needs-human` (**not** `needs-ai`), inherits the parent's milestone and
   `priority:*`, and carries a derivation link to the parent. **No child is autonomously selectable**
   (ESC-2).
6. The parent is marked `timeout-stuck` and is never selected again (FR14).
7. A sub-issue driven to D-3 is marked stuck, **never split**. A test asserts **no reachable path
   creates a grandchild** (FR15, AD-11).
8. Relabelling or editing a child does not make it split-eligible — the answer is parent-side (FR16).
9. A decision-only cycle completes well inside the cap with **no build agents invoked**, and exits 0
   (so it clears rung 2) (FR6).
10. An assessment that errors, times out, or returns anything unparseable produces `NO_SPLIT` + stuck
    (AD-7).

**Independent mergeability:** yes, given Phases 1 and 2 — but gated on the ESC-2 hold.
**Pre-declared split seam:** 4a = Component N (`validate` + `file`, driven by a fixture plan; criteria
2–8). 4b = Component O + the directive wiring (the assessment itself; criteria 1, 9, 10).

### 6.4 One permitted relaxation of the ADR's ordering, routed rather than taken

ADR §3 says Phase 4 is *"Gated on Phase 3"*. AD-7 and FR13 already provide the alternative: with
enforcement unavailable, a plan containing a dependency is `NO_SPLIT`. So Phase 4 **could** ship before
Phase 3 in independence-only mode, fail-closed, and #1354's own reference split is
independence-only (VF-12: the four siblings declare no ordering among themselves).

I am **not binding this** — it deviates from a binding build order, and the ESC-2 hold makes it moot in
practice. Recorded for the architect (§8, ESC-F) so the option is visible if Phase 3 slips.

---

## 7. Test plan

Each phase ships its own tests and may not rely on a later phase's.

| File | Phase | Covers |
|---|---|---|
| `tests/automation/test_branch_ownership.py` (extend) | 0 | `issue=` written; record **without** `issue=` still verifies; `schema=1` unchanged; `hos_bo_issue_for_cycle` resolution order incl. 0/1/N/ambiguous (TD-VF-3, TD-VF-4) |
| `tests/automation/test_submit_pr.py` (extend) | 0 | P2 refusal predicate unaffected by the new key, both record shapes |
| `tests/automation/test_timeout_attribution.py` | 0 | counter increment, cap-change reset, `stuck` line preserved; **FR2 end-to-end: two real kills → separate process reads 2** |
| `tests/automation/test_create_branch_marker.py` | 0 | marker applied after checkout; `edit_issue.sh` failure leaves branch + exit 0 + single stdout line; record-first ordering preserved |
| `tests/automation/test_hos_labels.py` | 0 | `labels.py` agrees with `hos_labels.sh`; **no other non-test file hard-codes the spellings** |
| `tests/automation/test_timeout_policy.py` | 1 | all three rungs; the FR20 assertion (two issues, once each → no suspend); the FR3 assertion (attribution off → suspend at 3); Q3 reset incl. the `stuck=0` non-reset; clamping; query-failure no-op; **`blocked` not counted** (TD-VF-5) |
| `tests/automation/test_next_candidates.py` (extend) | 1 | `timeout-stuck` and `blocked` excluded; `in-progress` **not** excluded; jq literals equal `hos_labels.sh`; existing params test unchanged |
| `tests/automation/test_hos_cron.py` (extend) | 1 | the gate sits before `_GATE_CANDIDATES`, before the no-work exit, after auth/milestone resolution; rung 3 exits 0 before work |
| `tests/automation/test_tracking_block.py` | 2 | every grammar rule, positive and negative; round-trip property |
| `tests/automation/test_reconcile.py` | 2, 3 | auto-close positives/negatives; prose-only linkage never closes; unblock on blocker close; multi-blocker; idempotent rendered statements; `--dry-run` writes nothing |
| `tests/automation/test_split_plan.py` | 4 | FR7 fixture set; size-1 and restating rejections; dependency-without-Phase-3 rejection; FR9 interruption/resume; `needs-human` labelling; **AD-11: no grandchild reachable, and no path retries an unchanged issue a third time** |

**Cross-cutting, one per phase (AD-4/FR22):** an audit round-trip test that writes one of that phase's
events through the real `audit_log.write_event` path and reads it back from a **separate process** via
`read_stream`, failing if the write is skipped. Mocking does not satisfy it.

**AD-11's worst-case bound, asserted as a number:** per parent, 2 attempts → 1 cheap decision cycle →
2 attempts per child → human. Per project, at most **3** consecutive timeout cycles before a full stop
(rung 2, per the human's ESC-1 ruling — **not** the ADR's 4), and at most **3** concurrently stuck
issues before a full stop (rung 3). Tests assert there is no reachable state in which the worker
retries an unchanged issue a third time, and none in which it splits a sub-issue.

---

## 8. Escalations

### ESC-A — the design chain has no stale-base check. (Process — **human**.)

TD-VF-1: two consecutive design documents cited a `bin/hos-cron` 826 deletions behind `origin/main`,
and nothing caught it. CLAUDE.md's `git diff --stat origin/main...<branch>` discipline is a *PR-time*
control; a design document is authored from reads, opens no PR, and touches no code, so it never runs.
The failure is quiet and downstream-fatal: a coder handed "edit `:1248`" edits the wrong function.
Recommend a cheap convention — every design document states the `origin/main` SHA it was derived from
in its header (this one does), and every consumer re-checks that SHA before acting on a line number.
Needs a human ruling on whether to make it a contract requirement.

### ESC-B — AD-5's single marker permits a false-positive project suspend. (Architecture — **`architect`**.)

TD-VF-5: with one marker for both the count and the exclusion, a *successful* split of one parent into
four children with three dependencies trips rung 3. This design is written to the two-marker
correction (`timeout-stuck` counted + excluded; `blocked` excluded only). Requesting AD-5 be amended,
or the correction be overturned with a reason.

### ESC-C — #1601's title and body still describe the overturned design. (Action — **orchestrating session**.)

TD-VF-9. The corrections live only in comments; the body still instructs the implementer to copy
`bounce_count` and to build on an interim mitigation that does not exist. Rewrite via
`bootstrap/edit_issue.sh --number 1601 --body-file …` before pickup. Phase 0's entry gate.

### ESC-D — ESC-3 still has no issue. (Action — **orchestrating session**.)

The architect raised it and was design-only; I am too. I excluded filename collision as a cause
(TD-VF-10) and got no further. It needs its own issue, or an explicit annotation on #1356
distinguishing "missing caller" from "missing record from a caller that demonstrably ran". AD-4 means
no phase here depends on the fix.

### ESC-E — rung 2's counter spans arbitrary idle time. (Architecture — **`architect`**, then an issue.)

AF-4.1, re-derived at `:1163` vs `:2079`. A no-work cycle exits before the bookkeeping that clears
`_tb_state`, so "3 consecutive timeouts" can span days. The architect declined to fix it here and I
concur — but after TD-VF-2 (the usage-limit breaker is inert), rung 2 is the *only* remaining
first-line attribution-blind brake, which raises the value of its threshold meaning what it says.
Recommend a separate v0.7.0 issue; not a blocker for any phase.

### ESC-F — may Phase 4 ship before Phase 3 in independence-only mode? (Build order — **`architect`**.)

§6.4. AD-7/FR13 already make it fail-closed and #1354's own reference split is independence-only.
Not taken unilaterally; moot while the ESC-2 hold stands.

---

## 9. Startup-gap analysis and affected sign-offs

**"Should this have been settled in the initial technical design, before any code was written against
it?"** — applied to each §0 finding.

- **TD-VF-3, TD-VF-4, TD-VF-5, TD-VF-7** all correct or refine design inputs for work that is
  **not yet built**. #1600–#1603 are all open, `needs-ai`, unstarted (verified 2026-09-12). **No
  design or code exists against the superseded forms, so no prior sign-off is orphaned.** These are
  startup gaps caught in time — which is the whole point of the chain running before implementation.
- **TD-VF-9 is a live startup-artifact gap.** #1601's body would have led an implementer to build the
  overturned design. It is caught before pickup only because nothing has picked it up yet; the
  correction (ESC-C) must land before Phase 0 is filed. No sign-off is affected, but a `startup-artifact-gap`
  annotation on #1601 is warranted.
- **Phase 1 re-defaults a shipped control** (`HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS`, shipped in
  #1435/#1439, 2026-08-15). Affirming the ADR §5 analysis: the code and its sign-off **stand**; only a
  default changes, in service of a rule (FR20) that did not exist when it was written. **No re-review
  of #1435 is required**, but its tests must be re-run against the new default and the rationale
  comment at **`:1939-1945`** (not the ADR's `:1241-1247`) updated so the two thresholds' relationship
  is legible in the file.
- **TD-VF-2 invalidates a factual premise in AD-6, not a sign-off.** The usage-limit breaker's own
  sign-off (#1446/#1450) is untouched; it was later disabled by operator request, which is recorded in
  the file. No re-review.
- **No other prior sign-off is affected.** Phases 0–4 are all new build. `bootstrap/create_branch.sh`
  and `branch_ownership.sh` carry #967/ADR-037 sign-offs; §3.1–3.2 are strictly additive and preserve
  every invariant those sign-offs rest on (record-first ordering, function-only library, the AD-2
  anti-loophole, the single-stdout-line contract). The coder must not weaken any of them, and the
  Phase 0 acceptance criteria assert each.

---

## Human Review Required

**RISK: HIGH.** This design relaxes a safety brake on purpose and moves where several controls live.
Getting it wrong yields an autonomous worker that burns sessions without stopping — and per AF-1/AF-2
this repo already contains one control that never fires and one deterministic write that vanished, so
"we specified a brake" is not evidence of a brake. The routes to that failure are closed positively,
each with a named acceptance criterion rather than a caution: every count, threshold, exclusion and
suspend is deterministic code with no agent in the path (§3.4, §4.7); the counter reuses `_tb_state`'s
proven shape rather than the audit-derived one (§1.2); no decision reads an audit event (§1.4); the
existing brake survives attribution-blind at a floor that cannot fire before rung 1 acts
(§4.4, Phase 1 criteria 6 and 7 — the two assertions that prove, respectively, that the mechanism is
not dead code and that the brake was not removed). Three failure paths the upstream documents did not
name are closed here: a `schema=2` bump would have broken PR submission (TD-VF-3); an ambiguous
`cycle_id` scan could have labelled the wrong issue (TD-VF-4); and a single marker let a *successful*
split suspend the project (TD-VF-5).

**CONFIDENCE: HIGH** on §0 — every anchor was re-derived from `origin/main` (`58b4785a`) this session,
including TD-VF-1, which shows both upstream documents' line numbers resolve against a file 826
deletions stale. **HIGH** on §1–§4 (Phases 0 and 1): they touch code I read in full and reuse
mechanisms with field evidence of working. **MEDIUM-HIGH** on §5 (Phases 2–4) — the block grammar and
the sweep are sound and copy proven shapes, but they are the parts with the least existing code to
verify against, and the split assessment has no precedent in this repo at all. **LOWER** on anything
downstream of the stated gaps: the uninspected local state directories, and whether the two #1597
cycles reached branch creation (which still sets AD-3's real-world coverage on the historical
incident).

**BLAST RADIUS:** `bin/hos-cron`'s timeout, escalation, pre-work gate and context-building paths;
`hos-suspend` entry conditions; `bootstrap/create_branch.sh` and the branch-ownership record schema
(and therefore, via `submit_pr.sh`'s P2 predicate, **the worker's ability to open any PR at all** —
TD-VF-3 is the reason that is a caution and not an outage); `next_candidates.jq`, i.e. work selection
for every autonomous cycle; and the issue graph itself, since the worker gains authority to create and
to close issues. Every phase touches a protected surface, so **every phase's PR is human-gated**.
Indirectly ADR-1540, whose AD-2 enumeration Phase 4 waits on, and the overseer, which stops being
halted by a single worker timeout.

**Change classification: STRUCTURAL** — new authority (the machine creates and closes its own work
items), a changed safety-brake threshold, two new issue states, and an additive change to a shipped
durable record. Per the product-boundary checkpoint this requires human clearance before Phase 4
binds. **ESC-1 and ESC-2 are already ruled** (rung 2 = 3; Phase 4 held behind #1540's AD-2), so
**Phases 0–3 are unblocked on the product side** and wait only on architect review of this document
and on ESC-B.
