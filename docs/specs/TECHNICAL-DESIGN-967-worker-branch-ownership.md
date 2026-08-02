# Technical Design — #967: Worker Branch Ownership (PRs only for branches the worker created)

**Issue:** #967
**Spec:** `docs/specs/SPEC-967-worker-branch-ownership.md` (pm-agent, 2026-08-02)
**ADR:** `docs/v0.6.0/ADR-037-worker-branch-ownership.md` (architect, 2026-08-02 — **ACCEPTED/GO**, AD-1…AD-8 binding)
**Status:** For implementation (phased — P1 → P2 → P3, order load-bearing)
**Milestone:** v0.6.0 as labelled (re-triage is ADR §3 N3, not a blocker)
**Risk tier:** **HIGH** (confirmed — SPEC §10, ADR §4)
**Date:** 2026-08-02
**Author:** technical-design

---

## 1. Overview

The worker inferred "this branch is my finished work" from the fact that a branch/commit
existed. This design replaces that inference with a **recorded, per-cycle ownership fact**
and enforces it at the single PR-opening chokepoint.

Four seams carry the whole design:

1. **`bin/hos-cron` mints cycle identity** (`HOS_CYCLE_ID`, `HOS_CYCLE_ROLE`,
   `HOS_CYCLE_TOKEN`) once per invocation and exports it into the Claude session (AD-5).
   Its **absence** is the fail-closed hinge and is what scopes the record to the worker
   role without any role-detection heuristic.
2. **`bootstrap/create_branch.sh` is the only branch-creation seam** in the worker's
   autonomous flow. It writes the ownership record and creates the branch as one
   operation (R1), and produces a **cycle-unique** branch name (AD-3).
3. **`bootstrap/submit_pr.sh --app worker` verifies the record** before it touches the
   network, mints a token, or pushes (R4/R5). Failure is refusal with a named reason
   class plus an audit event (R9). `--app human` and `--app overseer` never reach the
   check (R6).
4. **The old inference is deleted** from `correlation.py`, the worker agent prose, and
   the cron prompt (R7, AD-2) — not wrapped, not demoted.

The organizing constraint from ADR §1 governs every seam below: **the record is a
NECESSARY precondition for opening a PR, never a SUFFICIENT one, and never evidence that
work is finished.** Nothing in this design reads the record for control flow, resume, or
completion. It is read in exactly one place: the refusal predicate in `submit_pr.sh`.

---

## 2. Empirical findings (obligations discharged before design)

ADR §5 makes four things empirical obligations on this document. All four were checked
against the working tree at `/home/scott/Code/HumanOversightSystem/Worker`.

**EF-1 — How the bounce push happens today (AD-4's explicit obligation; this is the
lockout risk).** `grep -rn "git push" scripts/ bin/ bootstrap/` returns exactly one
executing site: `bootstrap/submit_pr.sh:146`. `bin/lib/git-credentials.sh` and
`provision_agent_account.sh` mention pushes only in comments. There is **no push-only
wrapper** in `bootstrap/`. `bootstrap/worker-cron-prompt.md:47,59` ("CHANGES_REQUESTED →
fix, push, STOP") and `.claude/agents/worker.md:240` name no script.

**Conclusion: the bounce push is a raw `git push` typed by the agent and does NOT traverse
`submit_pr.sh` today.** Therefore placing R4 inside `submit_pr.sh`'s *open* path cannot
capture the bounce path — AD-4's lockout is avoided by the existing shape, not by a guard
we have to get right. pm-agent's OQ-2 premise is confirmed rejected. The missing push
wrapper is ADR §3 N2 (pre-existing gap, separate issue) and is **not** absorbed here; §7
below adds an explicit `--update-pr` mode so a wrapper, when it is built, has a correct
mode to route through.

**EF-2 — `submit_pr.sh` is not shipped to consumer repos (distribution gap, new).**
`bootstrap/hos_install.sh` copies exactly five bootstrap files (`:1812-1820`:
`get_app_token.sh`, `hos_repo_sync.sh`, `validate_setup.sh`, `apps.env.template`,
`sync_apps_env.sh`) plus the generated cron prompts. `submit_pr.sh`, `create_issue.sh`,
`post_comment.sh` are **absent** from the install, and `scripts/framework/framework_consumer_files.txt`
does not list them. `scripts/automation/` is not shipped either (only `scripts/oversight/`
is rsynced, `:1792-1795`) — so `correlation.py` is HOS-only.

Consequence for AD-6 ("framework-wide, no opt-out"): the chokepoint does not currently
*exist* in a consumer repo, so enforcement cannot reach the deployment where #967 actually
fired (CondoParkShare). §10 handles this: the new files and `submit_pr.sh` are added to
the consumer ship-set so the shipped `worker.md` prose is true where it lands. **Routed to
the architect** (§15, TD-N1) because it widens what a consumer install contains.

**EF-3 — REQ-034 survives AD-2 (ADR §3 startup-gap analysis asked me to confirm, not
assume).** `docs/v0.6.0/REQUIREMENTS-034-sandbox-hang-detection.md:129-132` FR5 requires
that termination leave state resumable by "`correlation.py` `ResumeState`, `claim.py`
stale-claim reclamation". Read in full: FR5 names no specific state and its verification
criterion is "a later cycle for the same cid resumes at the correct `ResumeState` and
completes the task without duplicate work." The states that carry that guarantee are
`CLAIM_PRESENT`, `PR_EXISTS`, `GATES_COMPLETE`, `MERGED` — all retained by AD-2. FR5's
second sentence ("MUST NOT leave a half-written durable artifact that a resuming cycle
would read as complete") is *strengthened*, not weakened, by deleting `BRANCH_EXISTS`.
**Confirmed: REQ-034 needs no amendment and no sign-off against it is orphaned.**

**EF-4 — one further inference site beyond SPEC R7's floor.**
`docs/specs/UNATTENDED-WORKER-TECH-DESIGN.md:371-383` documents the precheck algorithm
step "1. `GET /…/git/ref/heads/hos/auto/<cid>` → branch exists?" and the cold-start table
row "| After branch, before PR | open PR (branch exists) |". That is the inference in
documentation form; R7 is a floor, not a ceiling. §8.4 edits it.

**EF-5 — the state-dir idiom and the `.git` alternative.** `bin/hos-cron:124-133,182`
namespaces per-cycle machine-local state under `${HOS_STATE_DIR:-$HOME/.hos}` by
`(role, project)`. That idiom cannot be reused for the record's key: `submit_pr.sh` has no
`--project`, never reads `projects.conf`, and resolves only `REPO_SLUG` from the origin
remote (`:121-124`) — confirmed. §4 therefore takes the architect's flagged alternative
(store inside the repository's own git directory), which discharges R8, T7 and AD-7's
clone-scoping by construction.

---

## 3. Cycle identity — `bin/hos-cron` (AD-5)

### 3.1 Minting

Insert immediately after the overlap lock is acquired and the pid recorded — i.e. after
`bin/hos-cron:209-210` (`echo "$$" > "$_LOCK_DIR/pid"` and its `trap`), before the
`_audit` helper definition at `:213`. Placing it under the lock ties the identifier to the
one-run-per-(role,project) guarantee.

```
_cycle_ts="$(date -u +%y%m%d%H%M%S)"          # 12 digits, e.g. 260802191500
HOS_CYCLE_TOKEN="$_cycle_ts"
HOS_CYCLE_ROLE="$ROLE"
HOS_CYCLE_ID="${ROLE}-${PROJECT}-${_cycle_ts}-$$"
export HOS_CYCLE_ID HOS_CYCLE_ROLE HOS_CYCLE_TOKEN
```

**Contracts:**

- The clock is read **once**; `HOS_CYCLE_TOKEN` and `HOS_CYCLE_ID` share that instant.
- `PROJECT` is sanitized before use: replace every character not in `[A-Za-z0-9._-]` with
  `-`. After sanitization the launcher MUST assert
  `[[ "$HOS_CYCLE_ID" =~ ^[A-Za-z0-9._-]+$ ]]` and `exit 78` (EX_CONFIG) with a named
  message if it does not. A malformed identifier must never reach the session.
- Minted for **both** roles. The overseer creates no branches; giving it an identity costs
  nothing and keeps one code path. Role scoping is enforced by the recorded
  `role=` value (§4.3), not by withholding the identifier.
- Uniqueness argument (AD-5's requirement, stated so a reviewer can check it): `role` and
  `project` separate concurrent cycles on one machine; the second-resolution UTC timestamp
  separates sequential cycles of the same (role, project) — which the `mkdir` mutex already
  serializes — and survives reboots; `$$` is a third discriminator and is never relied on
  alone (#1002 PID reuse). Timestamp-only and PID-only are both explicitly rejected by AD-5.
- **No default and no fallback anywhere else.** Nothing downstream may derive, invent, or
  persist a cycle id. `HOS_CYCLE_ID` unset/empty ⇒ no record can be written and none can be
  valid (§4.3, §6.2).

### 3.2 Observability

Extend the existing cycle-start event at `bin/hos-cron:831`:

```
_audit cycle-start "bot=$HOS_BOT_LOGIN project=$PROJECT cycle_id=$HOS_CYCLE_ID"
```

This is what lets an operator join a refusal event (§6.3) to the cycle that produced it.

### 3.3 Export reaches the session

`_run_claude` (`:859-875`) launches `claude` as a child of this shell, so plain `export`
suffices — the same mechanism `GH_TOKEN`/`HOS_BOT_LOGIN` already rely on. No prompt-file
substitution is needed and none is added; cycle identity must never be textual content the
model can restate (AD-5 reason 3).

---

## 4. The ownership record

### 4.1 Storage location (mine to choose — R2, R8, AD-7)

```
<git-common-dir>/hos/branch-ownership/<encoded-branch>.rec
```

`<git-common-dir>` is `git -C <repo> rev-parse --git-common-dir`; if the result is
relative, it is resolved against `<repo>`. Both ends derive it identically and from
information each already has — no new argument, no `projects.conf`, no `$PROJECT`.

**Why here rather than under `${HOS_STATE_DIR:-$HOME/.hos}`:**

- **R8/T7 by construction.** Nothing under `.git/` is a repo-tracked file; it cannot appear
  in a PR diff and cannot travel between machines in a diff. T7 becomes a trivially
  provable property rather than a `.gitignore` promise.
- **AD-7's key shape by construction.** One store per clone. A record written for branch
  `B` in clone P is unreachable from clone Q, including the Worker/Human two-clones-one-slug
  case the ADR flagged — no slug hashing, no realpath agreement between two scripts.
- **Linked worktrees do the right thing.** `--git-common-dir` returns the main `.git` from a
  linked worktree, so a branch created in `.claude/worktrees/…` and submitted from the main
  checkout resolves to one store.
- **Self-provisioning (AD-6).** The writer `mkdir -p`s the two directories on first write.
  The installer provisions nothing, so correct operation never depends on install history.

`HOS_STATE_DIR` is **not** consulted and there is **no** store-location override — R5
forbids environment escape hatches, and tests use a real temp git repo or a stubbed
`rev-parse --git-common-dir` rather than a production override (§11).

### 4.2 Key and filename encoding

The lookup key is the **(clone, branch)** pair: the clone is the store's location, the
branch is the filename. Cycle identity is a **checked value**, never part of the key —
AD-7 requires "no record" and "wrong cycle" to remain distinguishable for R9.

Encoding, applied in this order (both ends, identical):

1. `%` → `%25`
2. `/` → `%2F`

Then the result MUST match `^[A-Za-z0-9._%+-]{1,200}$`; if it does not, the writer refuses
to write and the checker refuses to validate (reason `malformed`). Git ref names cannot
contain `..`, spaces, or control characters, so no traversal is reachable; the regex closes
the case regardless. The encoding is injective, so two distinct branches can never share a
record file.

### 4.3 Record format

A strict `key=value` text file, one pair per line, LF-terminated, UTF-8, no comments, no
blank lines, no quoting. Deliberately **not** JSON: the reader is Bash inside
`submit_pr.sh`, and a hand-rolled JSON parse is the fragile path — `jq` is not a framework
dependency and adding a `python3` call to the human/overseer-shared chokepoint is
unnecessary surface.

```
schema=1
branch=<exact branch name, verbatim>
cycle_id=<HOS_CYCLE_ID>
role=<HOS_CYCLE_ROLE>
created_at=<UTC, date -u +%Y-%m-%dT%H:%M:%SZ>
```

- Key order is fixed as above (writer contract) but the reader MUST NOT depend on order.
- `repo_slug` is deliberately **absent**: it is not needed (the store is clone-scoped) and
  a remote-URL-derived value would be a validity condition that changes when a remote
  changes. Adding fields later requires a `schema` bump.
- Values are single-line by construction; the writer asserts each value matches
  `^[A-Za-z0-9._/+-]+$` (branch, cycle_id, role) or the timestamp grammar, and refuses
  otherwise.
- Written atomically: write to `<path>.tmp.$$` in the same directory, `mv` into place.

**Validity (R3) — a record authorizes opening a PR on branch `B` if and only if ALL hold:**

| # | Condition | Reason class on failure |
|---|---|---|
| 1 | Store dir resolvable | `no_store` |
| 2 | `HOS_CYCLE_ID` set and non-empty in the checking process | `no_cycle_id` |
| 3 | The record file for the encoded `B` exists and is a regular file ≤ 4096 bytes | `no_record` |
| 4 | File is readable, every line matches `^[a-z_]+=.*$`, each required key appears **exactly once** | `unreadable` / `malformed` |
| 5 | `schema` == `1` | `malformed` |
| 6 | `branch` == `B` **byte-for-byte** (no prefix, glob, or pattern match) | `wrong_branch` |
| 7 | `cycle_id` == `$HOS_CYCLE_ID` | `wrong_cycle` |
| 8 | `role` == `worker` | `wrong_role` |

`created_at` is recorded for audit and diagnosis and is **not** a validity condition:
condition 7 (cycle equality) is strictly stronger than any age threshold, and adding a
second staleness rule would create a lockout direction with no benefit. Recording it still
satisfies R2's "timestamped, so staleness is decidable" — staleness *is* decidable from it;
authority simply does not depend on it.

There is **no** override flag, no environment escape, and no "open anyway" path (R5).

### 4.4 Retention

On each write, `create_branch.sh` prunes records in the store older than 30 days
(`find <store> -maxdepth 1 -name '*.rec' -mtime +30 -delete`, failures ignored). Pruning
can only remove records that are already invalid under condition 7, so it cannot create a
lockout. This is hygiene, not correctness.

---

## 5. New files

### 5.1 `bootstrap/lib/branch_ownership.sh` (new — sourced library, single owner of the format)

No side effects at source time, no `set -e` leakage, safe to source twice. It is the only
place the store path, the encoding, and the record grammar are defined; the writer and the
checker both go through it, so they cannot drift.

```
hos_bo_store_dir <repo_dir>
    # echoes "<git-common-dir>/hos/branch-ownership"; returns 1 if git cannot resolve it.

hos_bo_encode <branch>
    # echoes the encoded filename stem (§4.2); returns 1 if the result fails the regex.

hos_bo_record_path <repo_dir> <branch>
    # echoes "<store_dir>/<encoded>.rec"; returns 1 if either component fails.

hos_bo_write_record <repo_dir> <branch>
    # Requires HOS_CYCLE_ID and HOS_CYCLE_ROLE non-empty (else returns 1 with
    # HOS_BO_REASON=no_cycle_id). mkdir -p the store, write the §4.3 record
    # atomically (tmp + mv), prune per §4.4, return 0.
    # Overwrites an existing record for the same branch ONLY if that record is
    # valid for this cycle (idempotent re-run); otherwise returns 1 with
    # HOS_BO_REASON=foreign_record — never silently adopts another cycle's record.

hos_bo_verify <repo_dir> <branch>
    # Evaluates §4.3's eight conditions in order. Returns 0 on valid.
    # On failure returns 1 and sets HOS_BO_REASON to exactly one reason class.
    # Never prints to stdout; diagnostics go to the caller.

hos_bo_audit_refusal <repo_dir> <branch> <reason>
    # Best-effort R9 event (§6.3). Sources <repo_dir>/scripts/oversight/lib/audit_log.sh
    # if present and calls audit_write_event. If the helper is absent or fails, returns 0
    # WITHOUT output — an audit-sink failure must never convert a refusal into a pass, and
    # must never mask the refusal message. Always returns 0.
```

`HOS_BO_REASON` is the single out-parameter; every failure sets exactly one of:
`no_store`, `no_cycle_id`, `no_record`, `unreadable`, `malformed`, `wrong_branch`,
`wrong_cycle`, `wrong_role`, `foreign_record`.

Value extraction is `sed -n "s/^${k}=//p" "$f"` with a mandatory `wc -l` == 1 check per
key (duplicate key ⇒ `malformed`). Nothing is `eval`'d or sourced from the record file.

### 5.2 `bootstrap/create_branch.sh` (new — the R1 branch-creation seam)

Named to match the `bootstrap/create_issue.sh` / `post_comment.sh` / `submit_pr.sh` family.
It is a **single allowlistable command** at the call site: no command substitution, no
heredoc, no loop, no variable-expanded path (CLAUDE.md sandbox rules).

```
usage: bash bootstrap/create_branch.sh --issue <N> --slug <text> [--prefix <p>] [--from <ref>]
```

| Arg | Required | Contract |
|---|---|---|
| `--issue <N>` | yes | digits only; refuse otherwise |
| `--slug <text>` | yes | lowercased; every char not in `[a-z0-9]` → `-`; collapse repeats; strip leading/trailing `-`; truncate to 40 chars; refuse if empty after sanitization |
| `--prefix <p>` | no | default `worker`; must match `^[a-z][a-z0-9-]{0,15}$` |
| `--from <ref>` | no | default: current `HEAD`. See §5.3. |

**Branch name (AD-3 — cycle-unique by construction):**

```
<prefix>-<issue>-<slug>-<HOS_CYCLE_TOKEN>
e.g. worker-967-branch-ownership-260802191500
```

Binding the cycle token into the name makes the "rebuild after a crashed cycle collides
with the orphan" class structurally impossible (AD-3's preferred form), rather than
detect-and-suffix.

**Sequence (record-first — deliberate):**

1. Refuse unless `HOS_CYCLE_ID`, `HOS_CYCLE_TOKEN` are non-empty and
   `HOS_CYCLE_ROLE == worker`. Message names the missing variable and states that this
   script is for autonomous worker cycles only; an interactive session uses `git` directly
   and does not create records. Exit non-zero.
2. Compute the branch name.
3. If `refs/heads/<name>` already exists locally: if `hos_bo_verify` passes for it (same
   cycle, same role), `git checkout <name>`, print the name, exit 0 (idempotent re-run
   within one cycle). Otherwise **refuse** — never adopt an existing branch (AD-3).
4. `hos_bo_write_record`. On failure, print the reason and exit non-zero.
5. `git -C <repo> checkout -b <name> <from>`. On failure, **delete the record just
   written** and exit non-zero.
6. Print the branch name to **stdout as the only stdout line**; human-readable confirmation
   goes to stderr.

Record-first, not branch-first: a record with no branch is inert (nothing can be pushed —
`submit_pr.sh:94` already requires `refs/heads/<name>` to exist), whereas a branch with no
record is a confusing fail-closed refusal later. Step 5's rollback keeps the pair coherent
in the common case; the residual failure mode is the harmless one.

The single stdout line exists so the agent can read the branch name from the transcript and
type it literally into the next command — **no command substitution at the call site**.

### 5.3 `--from` and the timed-out-cycle path (design point beyond the ADR — see §15 TD-N2)

`HOS_CRON_MAX_SECONDS` defaults to 1800s, so a cycle can be killed mid-build with commits
on an unsubmitted branch. Under AD-1 that branch is **foreign** to the next cycle and can
never be pushed. `--from <ref>` lets the next cycle create *its own* branch at the orphan's
tip and submit that — AD-3's "rebuilt fresh," at lower cost than redoing the work.

This is content adoption, not authority transfer, and it is only safe under one rule, which
§9 writes into the worker prose in the affirmative:

> Adopting a prior cycle's commits via `--from` means the **full review chain re-runs in
> this cycle** (steps 8 → 8.9). The ownership record says only "this cycle created this
> branch." It never says the commits on it were reviewed.

Without that rule, `--from` would re-admit exactly the #967 harm (a PR opened on code whose
review status the opening cycle has no knowledge of) — which is why it is prose-bound here
and routed to the architect rather than assumed.

---

## 6. Enforcement — `bootstrap/submit_pr.sh` (R4, R5, R6)

### 6.1 Insertion point

Immediately **after** the `refs/heads/${HEAD}` existence check (`submit_pr.sh:94-97`) and
**before** the `#1162` fetch/merge block (`:99`). Justification:

- `HEAD` is fully resolved by then (defaulting to the current branch has happened at `:83`),
  so the check keys on the real branch name.
- It precedes `git fetch` (`:105`), so a refusal **never touches the network** (ADR AD-8).
- It precedes the base merge (`:114`), so a doomed submit never mutates the working tree.
- It precedes the token mint (`:131`) and the push (`:146`), which R4 requires.
- It precedes the point where the running script's own file could be modified by the base
  merge, so the library is sourced from a stable tree.

### 6.2 Shape

```
if [[ "$APP_ROLE" == "worker" && "$UPDATE_PR" == "" ]]; then
    source "$SCRIPT_DIR/lib/branch_ownership.sh" \
        || err "branch-ownership library missing (bootstrap/lib/branch_ownership.sh) — refusing to open a PR"
    if ! hos_bo_verify "$SCRIPT_DIR/.." "$HEAD"; then
        hos_bo_audit_refusal "$SCRIPT_DIR/.." "$HEAD" "$HOS_BO_REASON"
        err "<message, see below>"
    fi
fi
```

Everything is inside the `worker` branch of that condition. `--app human` (with its
`--confirmed` gate) and `--app overseer` never source the library, never read the store,
and see **no** change in argument parsing, ordering, output, or exit codes (R6, SPEC §6).
A missing library is itself a refusal for the worker — fail-closed, and diagnosable.

### 6.3 Refusal message and audit event (R9, AD-6)

Both failure directions of SPEC §10 look identical in a cron log, so the message is a
requirement, not a nicety. It MUST name the branch and the reason class, and the
`no_cycle_id` case MUST say so explicitly — that case is the signature of
launcher/chokepoint version skew (ADR VF-7) and is otherwise near-undiagnosable:

- `no_cycle_id` → *"HOS_CYCLE_ID is not set in this environment. Branch ownership cannot be
  verified, so `--app worker` cannot open a PR for '`<branch>`'. This session was not
  launched by `bin/hos-cron`, or the launcher predates #967 (upgrade `bin/hos-cron` and
  `bootstrap/` together)."*
- `no_record` → *"No ownership record for branch '`<branch>`'. The worker opens PRs only for
  branches it created in this cycle via `bootstrap/create_branch.sh`. A branch created by
  another session — whatever its commits or issue label — is never this cycle's to submit
  (#967)."*
- `wrong_cycle` → *"…record was written by cycle `<recorded>`, not this cycle `<current>`.
  Ownership does not decay; authority does not transfer (ADR-037 AD-1). Create this cycle's
  own branch (`create_branch.sh --from <branch>`) and submit that."*
- `wrong_role`, `wrong_branch`, `malformed`, `unreadable`, `no_store` → name branch, reason,
  and the record path.

Audit event, written through the standard `audit/log/` writer (#888) via
`scripts/oversight/lib/audit_log.sh`:

```json
{"event":"branch-ownership-refused","branch":"<b>","role":"worker",
 "reason":"<reason class>","cycle_id":"<HOS_CYCLE_ID or empty>",
 "timestamp":"<UTC ISO-8601 Z>"}
```

Emission is best-effort **in the write direction only**: if the audit helper is absent or
fails, the refusal still happens and still exits non-zero. An audit-sink failure must never
be able to turn a refusal into a pass.

### 6.4 What is deliberately NOT added

- No sign-off/register/readiness check here. Ownership is an independent precondition, not a
  merge into #317's gate (SPEC §6).
- No signing, no HMAC, no trusted-writer mechanism (SPEC §9, ADR AD-8 — this is a
  correctness guard, not a security boundary).
- No record read anywhere else in the codebase. In particular **not** inside
  `already_exists()` — that would make the record a resume signal, i.e. a completion signal
  (ADR AD-2 anti-loophole).

---

## 7. Update mode — `--update-pr <N>` (AD-4)

EF-1 establishes the bounce path does not traverse this script today, so §6's check cannot
capture it. This section exists to satisfy AD-4's binding constraints for the mode that
*will* be routed here, and to close AD-4 constraint 3 on the open path.

**Mode declaration is explicit and caller-declared. Try-create-then-fall-back-on-error is
forbidden** — inferring "this must be mine" from a `gh pr create` error string is the same
inference class the human deleted, rebuilt out of stderr.

`--update-pr <N>`:

- Requires `--app worker` (other roles: `err`). Requires `--base` and `--head` semantics
  unchanged so the #1162 stale-base guard still runs. `--title`/`--body-file` are rejected
  in this mode (`err`) — the modes stay disjoint.
- **Does not consult the ownership record.** Authority comes from server-side PR authorship,
  which is a stronger recorded fact (AD-4).
- After the token mint, before the push, `gh api repos/<slug>/pulls/<N>` and require **all**:
  `.state == "open"`, `.head.ref == "$HEAD"`, `.user.login == "$HOS_BOT_LOGIN"`,
  `.base.ref == "$BASE"`. Any mismatch, any non-zero exit, any unparseable response ⇒
  revoke the token and `err` (R5 applies to this predicate exactly as to R4). A
  caller-supplied "this is mine" assertion is worth nothing and none is accepted.
- Pushes `refs/heads/$HEAD` and prints the PR's `html_url`. **No `gh pr create`.**
- **No `--force`.** A non-fast-forward push fails loudly. Force-push over a PR head is a
  destructive form of the #967 defect (AD-4 constraint 4); if it is ever added it MUST carry
  this same server-side author check, and that is a separate issue.

**Open-mode duplicate guard (AD-4 constraint 3):** in open mode, after the mint and before
the push, query `gh api "repos/<slug>/pulls?state=open&head=<owner>:<HEAD>"`. If non-empty,
revoke and `err` naming the existing PR number and directing the caller to `--update-pr`.
This converts a confused caller into a clean refusal instead of a `gh` error string an agent
might route around. Query failure ⇒ refusal (fail-closed).

---

## 8. Inference removal (R7, AD-2) — concrete diff plan

### 8.1 `scripts/automation/lib/correlation.py`

| Lines (current) | Change |
|---|---|
| `5-8` (docstring) | Rewrite. Delete the claim that "the cid is the ONLY mechanism that prevents duplicate work". Replace with: deduplication rests on the **claim protocol** and on **remote PR/merge state** (`PR_EXISTS`/`MERGED`); the cid is the naming/correlation key. Add one line: branch existence is not evidence of anything — PR-opening authority is the per-cycle ownership record checked at `bootstrap/submit_pr.sh` (#967, ADR-037). |
| `17-21` (import) | Remove `get_branch` from the `scripts.automation.lib.github` import list. Keep `list_issue_comments`, `list_pulls`. `get_branch` must not remain imported — the lookup **is** the inference (AD-2). |
| `31` | Delete `BRANCH_EXISTS = auto()`. |
| `30` | Amend the `CLAIM_PRESENT` comment: "Claim envelope posted but no PR." ("no branch" is no longer a distinction the module makes.) |
| `143-144` | **Keep.** `branch = branch_name(cid)` still feeds `head_filter`. |
| `146-148` | Delete the `# 1. Does the branch exist?` comment, the `branch_ref = get_branch(...)` call, and `branch_found = branch_ref is not None`. |
| `150`, `164` | Renumber the remaining comments `# 1.` (PR) and `# 2.` (claim envelope). |
| `161-162` | Delete `if branch_found: return ResumeState.BRANCH_EXISTS`. |
| `196` | Delete `ResumeState.BRANCH_EXISTS: "Branch exists — open PR …"` from `COLD_START_TABLE`. |

Explicitly **kept, unchanged**: `derive_cid`, `_normalize_issue_url`, `branch_name`
(remains the single naming owner), `pr_title`, `envelope_cid_line`, `_has_claim_envelope`,
`_check_merged`, `_check_gates_complete`, and the `NOT_STARTED / CLAIM_PRESENT / PR_EXISTS /
GATES_COMPLETE / MERGED` states with their table rows (AD-2, SPEC §6).

`scripts/automation/lib/github.py` is **not** modified — `get_branch` stays as a library
function; only this caller is removed.

### 8.2 `tests/automation/test_correlation.py`

| Lines | Change |
|---|---|
| `147-152` `_mock_get_branch` helper | Delete — patching a symbol the module no longer imports would silently pass and hide a re-wire. |
| `171, 181, 190, 200, 210, 220, 231, 242, 255` | Remove every `_mock_get_branch(...)` from the `with` blocks; keep the `list_pulls`/`list_comments` mocks. |
| `188-195` `test_branch_exists_no_pr` | Replace with `test_branch_without_pr_is_not_started`: no PR, no claim envelope ⇒ `NOT_STARTED`. This is the unit-level statement of AD-1. |
| `238-247` `test_pr_beats_branch` | Rename to `test_open_pr_returns_pr_exists` and drop the branch premise. |
| `267-274` `TestColdStartTable` | **Keep as-is.** The `for state in ResumeState` invariant must survive over the reduced enum — that is the point. |
| new | `test_no_branch_inference_sites` (T6): assert `"BRANCH_EXISTS"`, `"get_branch"`, and `"Branch exists"` do not appear in `scripts/automation/lib/correlation.py`. A grep-style guard is acceptable per SPEC T6, and AD-2 requires it to cover the removed `get_branch` call, not only the enum member. |

### 8.3 `bootstrap/worker-cron-prompt.md`

- **Step 5** (`:95`) — replace *"Open PR (≤15 files, ≤10 commits), then STOP."* with the
  affirmative rule plus the sanctioned command: PR opening goes through
  `bash bootstrap/submit_pr.sh --title <t> --body-file <path> --base main --head <branch> --app worker`;
  the worker opens a PR **only** for a branch it created in this cycle via
  `bootstrap/create_branch.sh`; ownership is recorded, never inferred; size limits retained.
- **New Step 2b** (between Step 2 and Step 3) — *"Create this cycle's working branch:
  `bash bootstrap/create_branch.sh --issue <N> --slug <short-slug>`. This is the only
  sanctioned way to create a branch. Never `git checkout -b` directly. Never continue work on
  a branch you did not create in this cycle — whatever commits are on it, whatever issue it
  names."*
- **Step 1** (`:47`, `:59`) — leave the "fix, push, STOP" wording *functionally* unchanged
  (EF-1: it is a raw push and must not be routed into `submit_pr.sh` by this change) but add
  one clarifying clause: this path updates a PR **this bot already authored**; it is never a
  path to open a new PR, and it does not make the branch this cycle's to submit.
- **Step 1 fallback (`:58`)** — the conflict recovery says "cherry-pick onto a new local
  branch cut from current main, then force-push to the same remote branch name." Leave the
  remote-branch behaviour alone (that is the update path), but the *local* branch creation
  in that instruction becomes `bootstrap/create_branch.sh` so no path in the prompt still
  says `git checkout -b`.

### 8.4 `docs/specs/UNATTENDED-WORKER-TECH-DESIGN.md` (EF-4)

- `:371-373` precheck algorithm — delete numbered step 1 (`GET …/git/ref/heads/…` → branch
  exists?), renumber 2→1, 3→2.
- `:383` cold-start table — delete the row `| After branch, before PR | open PR (branch
  exists) |`.
- Add a one-line superseded note under the table: *"Superseded in part by #967 / ADR-037
  AD-1/AD-2: branch existence is no longer a resume state. PR-opening authority is the
  per-cycle ownership record."*

This is documentation-reality drift (#1123) if skipped: the doc would keep prescribing the
behaviour the code deletes.

---

## 9. Governance docs (R10)

### 9.1 `.claude/agents/worker.md`

| Location | Change |
|---|---|
| `:256` (per-task chain step 1) | "Idempotency precheck (`correlation.py:already_exists`) — resume from the furthest-progressed state" stays, plus: *"`BRANCH_EXISTS` no longer exists; a branch with no PR is `NOT_STARTED` for this cycle (#967)."* |
| new step `7b` (before the build chain at `:263`) | *"**Create this cycle's branch** — `bash bootstrap/create_branch.sh --issue <N> --slug <slug>`. This writes the branch-ownership record and is the only sanctioned branch-creation path in autonomous mode."* |
| `:275` (step 9, Open draft PR) | Prepend the affirmative rule: *"You open a PR only for a branch you created in **this** cycle via `bootstrap/create_branch.sh`. Ownership is **recorded, never inferred** — a commit on a branch, an issue label, or a matching branch name is not evidence that the work is yours or that it is finished. PR opening goes through `bootstrap/submit_pr.sh --app worker`, which refuses without a valid record (#967)."* |
| `:304` (What you do NOT do) | Replace the `git checkout -b`-implying guidance with: *"Create a working branch by any means other than `bootstrap/create_branch.sh` (autonomous mode)"*, and add: *"Open a PR for, push to, or continue work on a branch created by another session or a previous cycle — whatever commits it carries or issue it names."* Keep the existing protected/release-branch prohibition. |
| `:311-319` (Re-entry after a bounce) | Add: pushing a fix to a PR **this bot already authored** is an update, not an open; it is a different, explicitly-declared operation and never becomes authority to open a new PR (AD-4). |
| new, after `:319` | The `--from` rule from §5.3, in the affirmative: a prior cycle's unsubmitted branch is foreign; create this cycle's branch at its tip with `--from` and **re-run the full review chain (8 → 8.9) in this cycle** before submitting. |

### 9.2 `contract/OVERSIGHT-CONTRACT.md`

- Add one row to the audit-event table (§ the table at `:418-433`, format
  `| event | description | writer | fields |`):

  `| `branch-ownership-refused` | `submit_pr.sh --app worker` refused to open a PR because no valid per-cycle branch-ownership record existed for the head branch (#967) | `submit_pr.sh` (worker) | `branch`, `role`, `reason` (`no_store\|no_cycle_id\|no_record\|unreadable\|malformed\|wrong_branch\|wrong_cycle\|wrong_role`), `cycle_id`, `timestamp` |`

- If (and only if) the contract's role/obligation prose states the worker's PR-opening
  obligations elsewhere, add the one-sentence affirmative rule there too. The audit-event
  row is the required change; the rest is conditional on what the implementer finds (R10).

---

## 10. Distribution (EF-2, AD-6)

Add to `scripts/framework/framework_consumer_files.txt` (the single source of truth for both
the install copy-loop and `.hos-manifest`):

```
bootstrap/lib/branch_ownership.sh
bootstrap/create_branch.sh
bootstrap/submit_pr.sh
```

Rationale: `worker.md` ships to consumers via `consumer_agents.txt`, and after §9 it names
both scripts. Shipping prose that references files an install does not contain is a
guaranteed consumer breakage. `submit_pr.sh` already depends only on `get_app_token.sh`
(shipped) and `gh`/`git`/`curl`, and any consumer running `hos-cron --role worker` already
has `--app worker` credentials configured, so shipping it adds no new setup requirement.

The copy-loop at `hos_install.sh:1833-1843` is generic over paths, so **no installer code
change is required** — only the list. `cp_framework_file` chmods `.sh` files; both new files
are `.sh`. AD-6's "installer provisions nothing" holds: the store is created on first write,
never at install time.

Not shipped and deliberately unchanged: `scripts/automation/` (so `correlation.py` remains
HOS-only). Making the consumer worker *route* its PR creation through `submit_pr.sh` is the
ADR §3 N2 class of pre-existing gap and is **out of scope** here — filed separately (§15).

---

## 11. Tests

| ID | Test | File | Mechanism |
|---|---|---|---|
| **T1** | **Regression (load-bearing).** A foreign branch with a commit for a `needs-ai` issue exists, no record ⇒ `submit_pr.sh --app worker` exits non-zero, mints **no** token, performs **no** fetch/merge/push, no `gh pr create`, and emits the refusal event. MUST fail against pre-fix behaviour. | `tests/automation/test_submit_pr.py` | existing stub harness + audit stub |
| **T2** | **Happy path.** A branch created by `create_branch.sh` in the current cycle passes and reaches the unchanged push/PR path. Run T1 and T2 **together** (SPEC §10's proof obligation covers both directions). | `test_submit_pr.py` (chokepoint) + `test_branch_ownership.py` (seam) | real temp git repo for the seam |
| **T3** | **Stale/foreign variants** — one case per reason class: `no_record`, `wrong_branch`, `wrong_cycle` (explicitly the AD-1 prior-cycle case), `wrong_role`, `malformed`, `unreadable` (chmod 000), `no_cycle_id`, oversized file. Each asserts refusal **and** the reason class in stderr. | `test_submit_pr.py` | parametrized |
| **T4** | **Role isolation.** `--app human --confirmed` and `--app overseer` succeed with **no** record present and **no** `HOS_CYCLE_ID`, and their captured call sequences are identical before and after the change. | `test_submit_pr.py` | existing tests at `:186-202` extended with an explicit no-record assertion |
| **T5** | **No override.** No flag, argv combination, or environment variable opens a PR for `--app worker` without a valid record. Enumerate: `--confirmed`, unknown flags, `HOS_STATE_DIR`, `HOS_BO_*`, `HOS_CYCLE_ID` set to a value not matching the record. | `test_submit_pr.py` | |
| **T6** | **Inference removal (structural).** `BRANCH_EXISTS`, `get_branch`, and "Branch exists" absent from `correlation.py`; `COLD_START_TABLE` complete over the reduced enum. | `test_correlation.py` | grep guard (§8.2) |
| **T7** | **Record is not committed.** After `create_branch.sh` in a real temp repo: the record path is inside `git rev-parse --git-common-dir`; `git status --porcelain` is empty; `git ls-files` does not list it. | `test_branch_ownership.py` | real git repo |
| **T8** | **AD-7 cross-clone.** Two temp clones, same branch name, record written in clone A ⇒ verify fails in clone B (`no_record`). | `test_branch_ownership.py` | |
| **T9** | **AD-4 update path is not captured by R4.** `--update-pr N` with **no** ownership record present succeeds when the server-side check passes, and refuses when `state`/`head.ref`/`user.login`/`base.ref` mismatch. | `test_submit_pr.py` | gh stub returns a PR JSON |
| **T10** | **Cycle identity is minted and exported.** `HOS_CYCLE_ID`, `HOS_CYCLE_ROLE`, `HOS_CYCLE_TOKEN` are non-empty in the launched session's environment, match the documented grammar, and differ between two invocations. | `tests/automation/test_hos_cron.py` | add `echo "cycle_id=${HOS_CYCLE_ID:-UNSET}"` (and siblings) to the existing `claude` stub, which already dumps env to `claude_log` |
| **T11** | **Branch-name cycle-uniqueness (AD-3).** Two `create_branch.sh` runs with different `HOS_CYCLE_TOKEN` and identical `--issue/--slug` produce different branch names; a second run in the *same* cycle is idempotent; an existing same-named branch without a valid record is refused. | `test_branch_ownership.py` | |

### 11.1 Harness notes (concrete, so the coder does not rediscover them)

- **`tests/automation/test_submit_pr.py` is a stub harness** (`GIT_STUB`, `GH_STUB`,
  `CURL_STUB`, a `get_app_token.sh` stub, and a copy of `submit_pr.sh` under
  `tmp_path/bootstrap/`). Three additions:
  1. `Harness.__init__` must also copy `bootstrap/lib/branch_ownership.sh` into
     `tmp_path/bootstrap/lib/`.
  2. `GIT_STUB`'s `rev-parse` case must handle `--git-common-dir` **before** the `--verify`
     branch, echoing `${GIT_COMMON_DIR:-<tmp>/gitdir}`.
  3. A `Harness.write_record(branch, cycle_id=..., role="worker", body=None)` helper that
     writes a §4.3 record (or arbitrary bytes, for the malformed cases).
- **Existing worker-path tests will fail without a fixture change** — `test_happy_path_…`,
  `test_head_defaults_to_current_branch`, `test_explicit_head_used_over_current_branch`,
  `test_app_worker_does_not_require_confirmed`, the #1162 merge tests and the #1166 tests all
  use `--app worker`. The fixture must, by default, export a `HOS_CYCLE_ID` and write a
  matching valid record for the branch under test. This is expected, not a regression; the
  negative cases are then explicit rather than incidental.
- **Audit assertion without the real repo tree:** the harness creates
  `tmp_path/scripts/oversight/lib/audit_log.sh` as a stub defining `audit_write_event` to
  append its argument to `CAPTURE_FILE`. One test asserts the JSON event; one test asserts
  that **removing** that stub still produces a non-zero refusal (audit failure never masks or
  softens a refusal).
- **`tests/automation/test_branch_ownership.py` (new) uses a real temp git repo**
  (`git init`, one commit) rather than stubs — the store location, `--git-common-dir`
  resolution, and T7's not-tracked property are only meaningful against real git.

All tests run under `scripts/framework/run_tests_inner_loop.sh`; validators via
`scripts/oversight/run_validators.sh`.

---

## 12. Phasing (order is load-bearing)

Each phase is one PR, within the ≤15-file / ≤10-commit budget.

| Phase | Deliverable | Files |
|---|---|---|
| **P0** | SPEC-967 + ADR-037 + this document | 1 (this doc) |
| **P1 — mechanism (no enforcement)** | `bin/hos-cron` cycle identity; `bootstrap/lib/branch_ownership.sh`; `bootstrap/create_branch.sh`; ship-set entry; the **branch-creation** prose in `worker.md` + `worker-cron-prompt.md`; `test_branch_ownership.py`; `test_hos_cron.py` (T10) | 7 |
| **P2 — enforcement + removal** | `submit_pr.sh` §6 check; `test_submit_pr.py` (T1–T5); `correlation.py` §8.1; `test_correlation.py` §8.2 (T6); the **ownership-rule/PR-opening** prose in `worker.md` + `worker-cron-prompt.md`; `contract/OVERSIGHT-CONTRACT.md`; `UNATTENDED-WORKER-TECH-DESIGN.md` | 8 |
| **P3 — update mode** | `submit_pr.sh` `--update-pr` + open-mode duplicate guard (§7); `test_submit_pr.py` (T9); `worker.md` re-entry prose | 3 |

**Why P1 strictly precedes P2 (this is the lockout):** if the check lands before the
branch-creation seam and its prose, every cycle builds and none can submit — SPEC §10 failure
mode 2, which looks exactly like an idle worker. P1 is inert on its own: records are written
and nothing reads them, so P1 can sit in `main` indefinitely with zero behavioural change.

**Transition safety:** the cycle that *builds* P2 created its own branch under P1 prose
(record present) and pushes with the P1 copy of `submit_pr.sh` (no check) — no self-lockout.
The first cycle after P2 merges creates its branch with `create_branch.sh` and passes. P3 is
purely additive.

**Rollback:** revert the §6 block in `submit_pr.sh` — one hunk at one chokepoint. The store,
the launcher exports, and `create_branch.sh` are inert if nothing reads them.

---

## 13. Risks

| Risk | Mitigation |
|---|---|
| **Fail-open** — check silently passes when the store is missing (restores #967 while looking fixed) | Eight explicit conditions, each with a reason class (§4.3); `no_store`/`no_cycle_id`/`unreadable` are refusals, not skips; T3 asserts every class; the check is unconditional for `--app worker` with no override (T5) |
| **Fail-closed lockout** — worker builds every cycle, submits none | P1-before-P2 phasing; T2 run with T1; `create_branch.sh` is the single seam and is prose-mandated in P1; refusal messages name the cause; `--from` recovery for timed-out cycles (§5.3) |
| Bounce path captured by R4 ⇒ worker can never answer review feedback | EF-1 establishes the bounce push does not traverse `submit_pr.sh`; the check is additionally scoped to open mode only (`$UPDATE_PR == ""`), and T9 asserts it |
| Branch-name collision with a crashed cycle's orphan ⇒ non-fast-forward push | Cycle token in the branch name (AD-3); existing-branch-without-valid-record is refused, never adopted (T11) |
| Record becomes a resume/completion signal | Read in exactly one place (§6); AD-2 anti-loophole restated in `correlation.py`'s docstring; T6 guards the removal; `--from` carries an explicit re-review rule (§5.3) |
| Launcher/chokepoint version skew (consumer points cron at another checkout) | `no_cycle_id` message names the cause explicitly (AD-6); both files move together in one install (ADR VF-7) and are listed in the same ship-set (§10) |
| Existing `--app worker` tests break on the new precondition | Called out explicitly in §11.1 — fixture writes a valid record by default |
| Store grows unbounded | 30-day prune on write (§4.4); pruned records are already invalid |
| Orphaned branches from crashed cycles | Accepted by AD-1; ADR §3 N1 sweep is a separate low-priority issue and is **not** absorbed here |

---

## 14. Requirements traceability

| Req | Where satisfied | Test |
|---|---|---|
| R1 branch creation writes a record, one operation | §5.2 (record-first, rollback on failure); §9.1 prose makes it the only seam | T2, T11 |
| R2 keyed by branch, cycle-scoped, role-scoped, timestamped, durable, machine-local | §4.1–4.3 | T2, T7, T8 |
| R3 validity conditions | §4.3 table | T3 |
| R4 refusal before mint and push | §6.1 insertion point | T1 |
| R5 fail-closed, no override | §4.3, §6.2, §6.3 | T3, T5 |
| R6 worker-only enforcement | §6.2 (`APP_ROLE == worker` scoping) | T4 |
| R7 inference deleted, not guarded | §8.1–8.4 | T6 |
| R8 not a committed artifact | §4.1 (`.git/`) | T7 |
| R9 refusal observable | §6.3 + contract row §9.2 | T1, T3 |
| R10 governance docs state the rule | §8.3, §9 | (review) |
| R11 branch deletion on merge | already satisfied by repo settings; **no code** | verification checkbox only |
| AD-1 per-cycle authority | §4.3 condition 7 | T3 (`wrong_cycle`) |
| AD-2 exact `correlation.py` edit | §8.1 | T6 |
| AD-3 cycle-unique branch names | §5.2 | T11 |
| AD-4 explicit update mode, server-verified | §7 | T9 |
| AD-5 launcher-minted identity, absent ⇒ refuse | §3, §4.3 condition 2 | T10, T3 |
| AD-6 no opt-out, self-provisioning, diagnosable | §4.1, §6.3, §10 | T3, T5 |
| AD-7 (clone, branch) key, cycle id as value | §4.1, §4.2 | T8 |

---

## 15. Notes routed (none blocking implementation)

**TD-N1 — the chokepoint is not shipped to consumers (to `architect`).** EF-2. §10 adds
`submit_pr.sh` and the two new files to the consumer ship-set so the shipped `worker.md`
prose is true where it lands. This widens what an install contains and therefore belongs on
the architect's record, not mine alone. It does **not** change consumer behaviour by itself:
nothing in a consumer repo calls `submit_pr.sh` until a consumer worker is told to, which is
the next note.

**TD-N2 — `--from` recovery for timed-out cycles (to `architect`).** §5.3 adds a path the
ADR does not discuss: a cycle killed by `HOS_CRON_MAX_SECONDS` leaves commits on a branch the
next cycle may not push. `--from` lets the next cycle create *its own* branch at that tip.
This is content adoption, not authority transfer, and is bound by an explicit prose rule that
the adopting cycle re-runs the full review chain. Flagged because it is adjacent to ADR §1's
principle and I would rather have it examined than discovered.

**TD-N3 — consumer worker PR routing (file a separate issue).** Consumer worker prose does not
route PR creation through `submit_pr.sh` today (there is no committed path at all — EF-1/EF-2).
Mandating it is the ADR §3 N2 class of pre-existing gap and is out of scope for #967.

**TD-N4 — orphan sweep and the missing push wrapper** remain ADR §3 N1/N2: separate
low-priority issues, explicitly not absorbed here.

**Startup-gap analysis (CORE).** This is the initial technical design for #967, not a
reactive revision. No prior technical design covers this surface and no code sign-off exists
against a superseded contract, so **no sign-off is orphaned and none requires re-review**.
The one adjacent contract is `correlation.py`'s `BRANCH_EXISTS`/cold-start lineage
(`UNATTENDED-WORKER-TECH-DESIGN.md:371-383`), which AD-2 narrows; ADR VF-1/VF-2 establish that
path was never executed, so nothing was built or approved against the behaviour being removed.
EF-3 confirms REQ-034's `ResumeState` reliance survives intact.

---

## HOS Self-Flag (design authoring)

```
RISK: HIGH
```

**Change classification: STRUCTURAL** — this document specifies new required behaviour (a
per-cycle ownership record, launcher-minted cycle identity, a new refusal path at the PR
chokepoint, a new branch-creation seam, and removal of an existing completion inference). It
is written against an explicit human decision already given on #967 (2026-08-02) and an
ACCEPTED architect ADR (ADR-037) that resolves every open question. Every structural element
traces to SPEC R1–R11 or ADR AD-1–AD-8 (§14); the material not covered by either is confined
to §15 and routed, not written into the contract silently.

```
BLAST RADIUS: The autonomous worker's ability to open PRs at all, on every deployment that
receives the change. Fail-open restores #967 while appearing fixed; fail-closed-too-far halts
autonomous delivery invisibly. Rollback: revert the §6 block in submit_pr.sh (one hunk, one
chokepoint); the store, the launcher exports, and create_branch.sh are inert if unread.
```

## Human Review Required

**§4.1 store location — review for correctness.** The record lives in
`<git-common-dir>/hos/branch-ownership/`, not under `~/.hos`. This discharges R8/T7 and
AD-7's clone-scoping by construction and diverges from the launcher's `${HOS_STATE_DIR}`
idiom. Confirm you accept the divergence.

**§5.3 / TD-N2 `--from` — review for correctness.** A prior cycle's unsubmitted branch is
foreign under AD-1; `--from` lets the next cycle adopt its *commits* under a new,
cycle-owned branch, bound by a prose rule requiring the full review chain to re-run. This is
the closest thing in this design to the boundary ADR §1 draws.

**§10 / TD-N1 consumer ship-set — review for process.** `bootstrap/submit_pr.sh` becomes a
shipped consumer file. Necessary for the shipped worker prose to be true, but it widens what
an install contains.

**§12 phasing — review for process.** P1 MUST land before P2. Merging P2 first halts
autonomous delivery in a way that presents as an idle worker.

```
CONFIDENCE: 87%
Basis: HIGH on everything verified against the working tree in this session — submit_pr.sh in
full, correlation.py in full, its test file's mock structure, the test_submit_pr.py stub
harness, test_hos_cron.py's claude-stub env capture, bin/hos-cron's state-dir/lock/export/
launch sequence, hos_install.sh's bootstrap copy list and framework_consumer_files.txt,
audit_log.sh's interface, and the repo-wide `git push` grep that settles EF-1. LOWER on two
points: (a) the exact consumer-side consequences of shipping submit_pr.sh, which I can reason
about but cannot test against a real consumer install from here (TD-N1); and (b) whether the
`--from` recovery path (TD-N2) should exist at all in this issue versus being deferred — I
judged the timed-out-cycle case common enough at a 1800s cap that omitting it would produce a
real delivery stall, but that is a judgement the architect may reverse without affecting any
other part of this design.
```
