# REQUIREMENTS-1803 — The audit trail must be durable, discoverable and lag-detectable: reconcile #1803 ("`audit/log/**` stopped being committed") with the #1538 R4 ruling ("`audit-log` is never merged into `main`")

Issue: #1803 (`bug`, `process-gap`, `priority:high`, milestone v0.7.0). Related: #1538 (v0.7.10),
#1749, #1517, #1095, #1157.
Author: pm-agent. Date: 2026-10-11.

**Status:** DRAFT. **Blocked on ESC-1 before any design work starts.** The issue frames the defect
as "nothing commits `audit/log/**` to `main` any more" and asks who should own that commit. A
binding human ruling of 2026-09-10 (#1538 R4) says the trail must **never** reach `main`, and
"there is no audit PR, ever". Both of the issue's candidate mechanisms put records on `main`, so
both contradict that ruling. The pm-agent may not resolve a conflict between an issue body and a
human ruling by picking one. This document therefore:

1. records what the repository actually shows (§0), which corrects several of the issue's factual
   premises;
2. identifies the root cause as far as the evidence allows (§1);
3. states the requirements that hold **whichever way ESC-1 is answered** (§3–§5), written against
   a neutral term, the **trail of record**;
4. lists the extra constraints that apply only if a human reverses R4 (§6);
5. lists the human decisions (§8).

The issue body is treated as a description of desired work, not as ground truth. Every factual
claim in it was re-measured; corrections are marked **[CORRECTS ISSUE]**.

**Definition: trail of record.** The single git location that is the authoritative, durable,
shared copy of every audit record. Under #1538 R4, as ruled, this is the remote ref
`origin/audit-log`. If ESC-1 reverses R4, it is the default branch. No requirement below presumes
which.

---

## 0. Verification findings (measured 2026-10-11, Worker clone, branch based on `5cb3fdcbc`)

- **VF-1 — The clone is shallow, and that invalidates the issue's "last commit to add a record"
  evidence.** [CORRECTS ISSUE]
  - `git rev-parse --is-shallow-repository` → `true`.
  - `.git/shallow` lists three boundary commits: `823cea532` (the PR #1582 merge), `952e960ca` and
    `56aafb02c`.
  - In a shallow clone, `git log --diff-filter=A` attributes every file in a boundary commit's
    tree to that commit. `git log --full-history -- audit/` returns **only** `823cea532`, because
    nothing earlier is present locally.
  - So the issue's `823cea53 … last commit to ADD any audit record` is a property of the shallow
    boundary. It does not show that #1582 introduced the records, or that any regular commit path
    existed before it. Pre-boundary history cannot be inspected from this clone.
- **VF-2 — Two earlier boundary commits show the same gap was hit, and bulk-patched, on
  2026-09-01.**
  - `952e960ca` (2026-09-01T06:00:48Z, `hos-worker-hos[bot]`): *"audit: commit per-entry
    audit-log records for 2026-06-28 through 2026-08-17. Closes a gap where cron cycles wrote
    audit/log entries locally but they were never committed, leaving ~7,700 records outside the
    append-only audit trail."*
  - `56aafb02c` (2026-09-01T06:02:44Z, same bot), two minutes later: *"Revert … This reverts commit
    ad16c85b1…"*. That is a different SHA with the same message.
  - The failure "records are written but never committed to `main`" therefore **predates
    2026-09-11**. Records reached `main` through one-off bulk commits, not through a standing
    per-cycle path.
- **VF-3 — `main` tracks 7,927 records; the newest is 2026-09-03, not 2026-09-02.**
  [CORRECTS ISSUE]
  - By month: 2026/06 378, 2026/07 3,447, 2026/08 4,091, 2026/09 11.
  - The newest tracked record is `audit/log/2026/09/20260903T115616Z-pr-review-skipped-idempotent-1505.json`.
    It has a non-canonical, hand-written name, so the issue's `grep -E '^2026-'` skipped it.
- **VF-4 — The records are not lost. They are on `origin/audit-log`, which both cron roles push to
  every cycle.** [CORRECTS ISSUE]
  - `origin/audit-log` holds **46,485** records. By month: 06 711, 07 7,451, 08 7,591,
    09 21,994, 10 8,738.
  - Its newest commits are `9e3d53fc5` (2026-10-11T22:57:17Z, `hos-worker-hos[bot]`) and
    `26da3bc16` (22:55:57Z, `hos-overseer-hos[bot]`), both `chore(audit): sync logs …`.
  - **Worker clone:** 17,627 untracked records (`--untracked-files=all`). **17,622** are present on
    `origin/audit-log` by path. The other **5** were written during the current cycle
    (2026-10-11T23:05Z onward), after the last sync.
  - **Overseer clone:** 6,502 untracked; **6,500** on the branch; the 2 missing are from the
    current cycle.
  - **Human clone:** 0 untracked. It tracks the same 7,927 as `main`.
  - **Every `main`-tracked record is also on `origin/audit-log`** (0 missing by path).
  - The window the issue calls "already absent", 2026-09-04 → 2026-09-13, has **5,290** records on
    the branch.
  - The issue's "evidence loss … one `git clean` away" is therefore **false as of today**. A
    clone's untracked records are working copies of data already pushed off-machine. The real
    exposure is the unsynced tail: at most one cycle's records per clone, plus any clone that has
    no sync step (VF-7).
- **VF-5 — The writer and the sync path.**
  - **Writer:** every record goes through `scripts/oversight/lib/audit_log.py` `write_event`. It
    is write-once and content-addressed, `audit/log/<YYYY>/<MM>/<ts>-<event>-<sha12>.json`. The
    full writer inventory is TD-1538 TD-VF-2.
  - **Sync:** `bin/hos-cron` `_sync_audit_logs` (`:497-551`), called once per cycle at `:2357`.
    - It bases on `origin/audit-log`, falling back to `origin/main` if the ref is absent (`:511-512`).
    - It copies records not already on the base into a detached scratch worktree, commits, and
      pushes `HEAD:refs/heads/audit-log` without `--force` (`:543-546`).
  - **Failure handling:**
    - A fetch failure returns 0 silently (`:509`).
    - Push stderr is discarded (`:544`).
    - A push failure prints only a log-line `WARN` (`:546`). There is no audit event and no
      retry within the cycle.
- **VF-6 — The documented path to `main` does not exist, and the documents disagree with each
  other.**
  - **(a)** `bin/hos-cron:494-496` claims *"A GitHub Actions workflow reads from that branch and
    commits only those files to main."* `.github/workflows/` holds 10 workflows and none
    references `audit-log` or `audit/log`. The comment is false (also TD-1538 TD-VF-4).
  - **(b)** `DECISIONS.md` 2026-06-23 designed that workflow, with a dedicated `hos-auditsync-hos`
    App holding a Ruleset bypass for direct pushes to `main`. `docs/MACHINE-ACCOUNTS-SETUP.md`
    Step 5 still instructs creating it.
  - **(c)** #1538 (human ruling, 2026-09-10) supersedes that design. It allows no new App
    identity and no gate exception, and the `audit-log` ref is never merged into `main`.
  - **(d)** `contract/OVERSIGHT-CONTRACT.md:35` still says `audit/ ← COMMITTED to project repo
    (not gitignored)` and names the retired `oversight-log.jsonl`.
  - **(e)** `DECISIONS.md` D23 says the trail lives on the **current branch**.
  - **(f)** `CLAUDE.md`'s layout block says `audit/  Committed audit trail`.
  - So the spec set says three different things about where the trail lives. That is the
    underlying reason #1803 could be filed in good faith against a ruling that contradicts it.
- **VF-7 — The Human clone has no sync step** (TD-1538 TD-VF-9). `bin/hos-human` does not call
  `_sync_audit_logs`. Any record a Human-clone session writes reaches the trail only by accident.
- **VF-8 — Untracked records have a cost beyond noise.** `bootstrap/hos_repo_sync.sh:137` treats any
  `git status --porcelain` output as a dirty tree and falls back to fetch-only. `.gitignore` has
  no `audit` entry. So any clone that has written one record can never be fast-forwarded by
  `hos_repo_sync.sh` (TD-1538 TD-VF-8).
- **VF-9 — Branch protection on `main` has no bot bypass.** `scripts/framework/setup_branch_protection.sh:25,
  :128` sets `bypass_pull_request_allowances: []` ("bots are NOT bypass actors"), requires one
  approving code-owner review, and leaves `enforce_admins: false` (the human admin keeps the
  bypass). No bot can push directly to `main` today.
  - `scripts/dev/commit_onto_base.sh` builds a commit with plumbing. By its own header it
    **deliberately does not push** (`:43-44`), so it is not a path to `main`.
- **VF-10 — `audit/log/**` is not a protected surface.** It is absent from
  `scripts/framework/protected_surfaces.txt` and from `.github/CODEOWNERS` (#1749 fact 1).
  `origin/audit-log` is unprotected, so any token with push access can force-push or delete it
  (TD-1538 ESC-2).
- **VF-11 — Record content (privacy and size input).**
  - A sampled `agent-invocation` record (`2026-10-09T030620Z-agent-invocation-8219a85fd0f0.json`)
    carries `agent`, `dimension`, `verdict`, finding counts, `input_digest` (sha256),
    `session_id`, `model`, `cli_version`, `duration_ms`, `total_cost_usd`, `role` and `posture`.
    It carries no prompt or diff text.
  - `agent-invocation` is the largest kind: 8,400 of the Worker clone's 17,627 untracked records.
  - Growth on the trail is about 8,700 records in the first 11 days of October, roughly 800 a day.
  - TD-1538 TD-VF-14 measured blobs at a mean of 174 B.
- **VF-12 — Overlap with #1538 is near-total.** TD-1538 (merged in PR #1855) already designs:
  - the standalone sync (S2);
  - `.gitignore` plus an `audit_segregation` CI gate (S3);
  - the Human-clone sync (S8, behind ESC-4);
  - per-clone `audit_sync.sh --status` sweep evidence.

  TD-1538 §11 step 5 states: *"#1803 can close (its records are preserved, not committed to
  `main`)."* None of those slices is built: `bootstrap/audit_sync.sh` and
  `scripts/oversight/lib/audit_sync.py` do not exist. #1538's coding is blocked on its own
  ESC-1..6.

## 1. Root cause

**Finding: there was no regression in a commit-to-`main` path, because no standing path that commits
records to `main` exists in the evidence.**

1. The designed path (DECISIONS 2026-06-23: cron → `audit-log` branch → Actions workflow →
   `main`) is missing its second half. No workflow exists (VF-6a). The only live mechanism pushes
   to `audit-log` (VF-5), and it has kept working through the whole window the issue calls a
   stall (VF-4).
2. Records reached `main` through bulk, one-off commits:
   - the 2026-09-01 backfill attempt `952e960ca` / revert `56aafb02c` (VF-2);
   - whatever brought the tracked set into the tree at or before the PR #1582 merge `823cea532`
     (2026-09-11).

   TD-1538 TD-VF-7 calls the #1582 inclusion "almost certainly through `git add -A`". **This
   cannot be confirmed from this clone**, because `823cea532` is a shallow boundary (VF-1).
   Confirming it needs either an unshallowed clone or the GitHub API's file list for PR #1582.
3. The perceived regression has three contributing defects, each with evidence:
   - **Records are not ignored.** `.gitignore` has no `audit` entry, so every synced record still
     shows as untracked. That makes a healthy, synced trail look orphaned (VF-4, VF-8).
   - **Documentation asserts a `main`-resident trail that no mechanism maintains** (VF-6a, d, e,
     f). A reader of `main` sees a trail that ends on 2026-09-03 with no pointer to where it
     continues.
   - **Nothing detects or surfaces sync lag or sync failure** (VF-5 failure handling). A real
     stall would be as silent as the perceived one.

What the pm-agent **cannot** determine: whether any automated commit-to-`main` path existed before
the shallow boundary (2026-09-01). If it matters to the human, it needs a full-history check.

## 2. Controlling conflict (why this is ESC-1 before anything else)

| Source | Says |
|---|---|
| #1803 issue body (2026-09-22) | `audit/log/**` is a committed trail on `main`; restore committing (option a: work branch, or option b: a dedicated trail commit onto the base) |
| #1538 R4 + "there is no audit PR, ever" (human ruling, human-proxy session, 2026-09-10) | `audit-log` is never merged into `main`, permanently; no new App identity; no gate exception |
| `contract/OVERSIGHT-CONTRACT.md:35`, DECISIONS D23, `CLAUDE.md` layout | `audit/` is committed to the project repo / current branch |
| TD-1538 §8, §11 step 5 (merged design) | `.gitignore audit/log/`; CI gate fails any PR that adds `audit/log/` paths; #1803 closes on sweep evidence |

- **Option (a)**, committing on each cycle's work branch:
  - it is an audit PR in substance, which contradicts the #1538 ruling;
  - TD-1538 §8.2's planned gate would fail it;
  - it is exactly the forgery channel #1749 describes: records riding inside ordinary PR diffs and
    suppressing `pr-merged-without-review`.
- **Option (b)**, a dedicated commit onto the base:
  - it would need a push to `main` without PR review;
  - branch protection gives no bot that ability (VF-9);
  - #1538 rules out the App/bypass that would grant it (VF-6c).

The newest ruling is the human ruling, and it is the more specific one. The pm-agent's reading is
that #1803's real needs survive R4 unchanged: durability, detectability, discoverability from
`main`, and no false "orphaned" signal. Its proposed **mechanism** (commit to `main`) does not
survive. Re-scoping #1803 that way changes the issue's stated scope, so it is presented as ESC-1
and not applied.

## 3. Functional requirements (hold under either ESC-1 answer)

**FR-1 — Every record reaches the trail of record within a bounded lag.** A record written in any
role clone must be present, byte-identical, in the trail of record within the bound set under
ESC-8. The bound defaults to "by the end of the next cycle of the role that wrote it". Byte
identity holds by construction for content-addressed names; for legacy hand-written names it must
be checked by blob id.
- *AC-1.1:* For each of the Worker and Overseer clones, a single static command reports
  `missing_on_trail` = the count of local records absent from the trail. After one complete cycle
  with no new writes, it reports 0.
- *AC-1.2:* A record whose path exists on the trail with different bytes is reported as a
  conflict. It is never silently treated as synced.

**FR-2 — Every role clone that writes records has a sync path.** This covers the Human clone
(VF-7), or else a documented, human-ruled statement that Human-clone records are out of scope
(TD-1538 ESC-4).
- *AC-2.1:* A record written by a Human-clone session satisfies FR-1, or the human ruling
  excluding it is cited in the contract.

**FR-3 — Lag and stall detection.** A check must fail visibly in any of these cases:
- **(a)** a local record older than the FR-1 bound is absent from the trail ("clone lag", the
  issue's proposed check, re-based on the trail of record);
- **(b)** the newest record on the trail is older than a staleness threshold while records are
  still being written ("trail stall");
- **(c)** the most recent sync attempt failed.

The issue's literal formulation, "newest tracked record lags newest on-disk record", must **not**
be implemented against `main` if R4 stands. Under R4 it would fail permanently by design.
- *AC-3.1:* With the sync step disabled for one cycle beyond the bound, (a) fails and names the
  oldest missing record and the clone.
- *AC-3.2:* With the trail ref frozen while records accumulate, (b) fails.
- *AC-3.3:* A simulated push rejection makes (c) fail on the next run.
- *AC-3.4:* A regression test reproduces the 2026-09 situation (records synced but untracked;
  nothing new reaches `main`) and asserts the check **passes** under R4. A healthy trail must not
  alarm.
- *AC-3.5:* The check runs as one static, allowlistable command (CLAUDE.md "Shell usage under the
  sandbox"). Its output is machine-readable (exit code plus a structured summary).

**FR-4 — Sync failures are recorded, not just logged.** Each failed fetch or push must leave a
durable, queryable signal: an audit event and the run's exit status, not only a log line (VF-5).
Silent `return 0` on a fetch failure is not acceptable.
- *AC-4.1:* Fetch failure, push rejection and push error each produce a distinct, queryable record
  that FR-3(c) can read.

**FR-5 — A synced record must not appear as orphaned working-tree output.** After this issue,
`git status` in a role clone must not list records already present on the trail, and
`hos_repo_sync.sh` must not treat their presence as a dirty tree (VF-8).
- *AC-5.1:* In a clone whose only local difference is synced records, `hos_repo_sync.sh`
  fast-forwards the default branch.

**FR-6 — `main` must not present a trail that silently ends.** A reader of the default branch must
be able to discover, from the default branch alone, where the trail of record lives and how to
read it.
- *AC-6.1:* `contract/OVERSIGHT-CONTRACT.md` §1, `CLAUDE.md`'s layout block, DECISIONS (a new
  dated entry; D23 and the 2026-06-23 entry stay unedited, since the file is append-only) and the
  `bin/hos-cron:494-496` comment all name the same trail of record. None of them claims a
  mechanism that does not exist (VF-6).
- *AC-6.2:* If any `audit/log/**` records remain tracked on `main` (TD-1538 ESC-1 "leave
  frozen"), a reader can see from `main` that they are a frozen partial snapshot, not the live
  trail.
- *AC-6.3:* `docs/MACHINE-ACCOUNTS-SETUP.md` Step 5 (`hos-auditsync-hos`) is either marked
  superseded or retained by explicit human ruling (ESC-2).

**FR-7 — Backlog disposition is verified, not assumed.** Before #1803 closes, per-clone evidence
(Worker, Overseer, Human) is recorded on the issue showing every local record is on the trail of
record, or listing those that are not, with the human's disposition (ESC-4). The 2026-10-11
measurement (VF-4) is the baseline; it must be re-run at close.
- *AC-7.1:* The issue carries three per-clone outputs of the FR-1 status command, each with
  `missing_on_trail: 0` or an itemised remainder.

**FR-8 — A record that suppressed an escalation is reproducible by someone not on that machine.**
For #1749's suppression readers (`overseer-cron-prompt.md:38` `pr-merged-without-review` and the
release-gate idempotency check), the record that caused a skip must be retrievable from the trail
of record within the FR-1 bound.

FR-8 concerns **audit reproducibility only**. It must not be read as permitting decision-bearing
readers to treat shared-trail records as authoritative. TD-1538 F1 deliberately keeps decision
reads local-only and provenance-filtered, and #1749 owns read-side authority.
- *AC-8.1:* Given a logged skip for PR *n*, the matching record is found on the trail of record by
  a fresh clone after the writer's next sync.

**FR-9 — The 441+ legacy non-canonical record names are preserved as-is.** The sync and detection
must handle records whose names do not match the canonical grammar (VF-3; TD-1538 TD-VF-5). They
must not skip, rename or re-hash them.
- *AC-9.1:* The detection check counts `20260903T115616Z-pr-review-skipped-idempotent-1505.json`
  correctly in both directions.

## 4. Non-functional requirements

**NFR-1 — No races between concurrent writers.**
- The Worker and Overseer clones (and the Human clone, if FR-2 adds it) sync on independent cron
  schedules, often within minutes of each other (VF-4: 22:55:57Z and 22:57:17Z).
- Concurrent syncs must never lose a record, never rewrite trail history (no force-push, ever), and
  never leave the trail in a state where a later sync cannot succeed.
- A rejected non-fast-forward push must converge on a later attempt, with no human action.
- *AC:* a test runs two syncs against the same trail with interleaved new records. The union of
  both clones' records is on the trail afterwards, and its history is append-only.

**NFR-2 — Fail-safe, not fail-silent.**
- A sync or detection failure must never block, wedge or abort a cycle's real work. It must also
  never be invisible (FR-4).
- A cycle whose sync failed still completes. The failure is visible on the next detection run
  (FR-3c).
- This is the same "signal exists, nothing acts on it" class DECISIONS 2026-09-05 records for the
  42-hour overseer stall. Whether a persistent failure escalates to a human is ESC-8.

**NFR-3 — The live checkout is never touched.**
- Sync and detection must not change the live clone's HEAD, branch, index or tracked working tree.
  This is the #988 constraint preserved in `bin/hos-cron:514-521`.
- They must not use `git stash`, `reset` or `clean` on the live tree.

**NFR-4 — No review bypass is introduced without a human ruling.** No path may write to the
default branch without PR review unless ESC-2 explicitly allows it. No new GitHub App identity or
gate exception may be introduced (#1538 scope). Branch protection (VF-9) must not be loosened by
this issue.

**NFR-5 — Shallow-clone compatible.** Every git operation must work in a shallow repository (VF-1;
TD-1538 TD-VF-13).

**NFR-6 — Sandbox-allowlistable.**
- Every entry point an agent or launcher calls is a committed script, invoked with a literal,
  static command line (CLAUDE.md "Shell usage under the sandbox").
- On Worker and Overseer an unmatched command is silently denied. A detection check that is
  silently skipped is the failure mode NFR-2 forbids.

**NFR-7 — Cost.** Detection must stay cheap enough to run every cycle at the current trail size
(about 46.5k records, growing about 800 a day). TD-1538 TD-VF-14 measured a full blob scan at 0.19
s for 31.5k records.

**NFR-8 — Consumer portability.**
- `bin/hos-cron` ships to consumers, so whatever is built must work in a consumer repo that has
  no `audit-log` ref yet.
- It must not assume this repo's App names.
- Consumer rollout of any `.gitignore` or contract change is TD-1538 ESC-3.

## 5. Constraints handed to the architect (mechanism is the architect's call)

1. **Do not design a mechanism before ESC-1 is answered.** If R4 stands (the pm-agent's reading),
   the architect's first question is whether #1803 needs **any** code beyond what TD-1538
   S2/S3/S8 deliver. If not, #1803 reduces to:
   - FR-3 (detection), which is not in TD-1538;
   - FR-4 (failure recording), which TD-1538 S2 may cover; the architect confirms;
   - FR-6 (documentation reconciliation);
   - FR-7 (close-out evidence).

   Prefer extending TD-1538's `audit_sync.sh --status` over a second status reader. One reader,
   one sync (TD-1538's title, and the D41 one-invocation-site principle).
2. **Search before building.** `bin/hos-cron` `_sync_audit_logs`, `scripts/oversight/lib/audit_log.py`,
   TD-1538 §2's layer map and #1517 (external liveness monitor, already retargeted at the
   `audit-log` push) all overlap FR-3(b). Name what is reused.
3. FR-3 has a clone-local half and a remote half. **(a)** needs the clone's disk; CI cannot see it.
   **(b)** can run anywhere. Where each half runs is the architect's call, subject to NFR-6.
4. The detection threshold values (the FR-1 bound and the FR-3(b) staleness threshold) are tunable
   settings, not constants. The human sets the **response** to a breach (ESC-8). The architect
   proposes default **values**.
5. Do not edit DECISIONS D23 or the 2026-06-23 entry. Supersede them with a new dated entry.

## 6. Additional constraints if a human reverses R4 (ESC-1 option b only)

If the human rules that the trail of record is the default branch, these apply on top of §3–§4:

- **C-1:** #1538 must be re-opened for R4. TD-1538 §8 (the `.gitignore` and the `audit_segregation`
  gate) must not land, because it would make FR-1 unsatisfiable.
- **C-2:** Every path to `main` needs ESC-2 answered. Branch protection has no bot bypass (VF-9),
  and `commit_onto_base.sh` does not push.
- **C-3:** If records reach `main` through PRs, #1749's forgery exposure applies to every such PR.
  ESC-3 (protected surface) must be answered first, and #1749's AC-3 (no sync deadlock on the gate)
  becomes a requirement here.
- **C-4:** Record survival must not depend on an unrelated PR merging. That rules out option (a)'s
  property, which the issue itself flags.
- **C-5:** About 38,500 records exist on `audit-log` and not on `main` (VF-4). ESC-4 decides
  whether they are back-committed.

## 7. Non-goals

- Record **content** defects: #1774, #1726, #1655, #1748, and the `worker.md:894-905` retired-path
  write (TD-1538 TD-VF-2).
- Read-side authority and forgery resistance: #1749 and TD-1538 F1/ESC-6.
- Malformed-record halts: #1751.
- Untracked prompt artifacts: #1762 / #1769 / #1782.
- Rewriting `audit-log` history or removing its 666 framework-source files: TD-1538 ESC-5.
- Local pruning of synced records: TD-1538 TD-D6.
- The 581 `cycle-branch-reap-failed` records in the Worker backlog. They suggest a separate
  recurring failure, but are out of scope here; a follow-up only if the human wants one.

## 8. Escalations for the human (ESC) — not guessed

- **ESC-1 — Is #1803's "commit to `main`" mechanism superseded by #1538 R4 (2026-09-10)?**
  - **(a)** Yes. #1803 is re-scoped to §3's requirements against `origin/audit-log` as the trail of
    record. It closes on FR-3, FR-4, FR-6 and FR-7 plus TD-1538's S2/S3 and its sweep evidence.
    This matches TD-1538 §11 step 5.
  - **(b)** No, reverse R4: the default branch is the trail of record. This is a **structural**
    change to a ruled requirement. It re-opens #1538, and §6 applies.
  - *pm-agent reading of the spec:* (a). The measured facts (VF-4) remove the evidence-loss urgency
    that motivated committing to `main`. The contract §1 / D23 / `CLAUDE.md` wording that supports
    (b) predates the ruling. Either answer requires a new DECISIONS entry that resolves the
    three-way documentation conflict (VF-6).
- **ESC-2 — Is any path that writes to `main` without PR review acceptable?** This includes a bot
  Ruleset bypass (the 2026-06-23 `hos-auditsync-hos` design), the admin bypass, or anything else.
  - Today no bot has one (VF-9), and #1538 excludes new identities and gate exceptions.
  - Under ESC-1(a), the only consequence is whether `MACHINE-ACCOUNTS-SETUP.md` Step 5 is retired
    (AC-6.3).
- **ESC-3 (only under ESC-1 b, PR path) — Must `audit/log/**` become a protected surface?** If so,
  every PR that carries records is human-gated (#1749 option 1). Records riding in ordinary PRs are
  #1749's suppression-forgery channel. Protection closes it, but it makes record delivery
  human-paced.
- **ESC-4 — Backlog: back-commit, leave on `audit-log`, or write off?**
  - Measured: Worker 17,622 / 17,627 and Overseer 6,500 / 6,502 untracked records are already on
    `origin/audit-log`. The rest are current-cycle records the next sync pushes. The Human clone
    has none untracked.
  - Under ESC-1(a), the only open sub-question is the 7,927 records frozen on `main`. That is the
    same decision as **TD-1538 ESC-1** and should be answered once, there.
  - Under ESC-1(b), the question is whether about 38,500 branch-only records are back-committed to
    `main`.
  - Nothing currently needs writing off.
- **ESC-5 — Durability of the trail of record depends on protecting it.** `origin/audit-log` is
  unprotected (VF-10). Any token with push access can force-push or delete the whole trail. FR-1's
  "durable" is only as strong as that ref's protection. This is the same decision as
  **TD-1538 ESC-2** (a ruleset blocking force-push and deletion, with no review requirement).
  #1803 cannot be called resolved under ESC-1(a) without an answer to it.
- **ESC-6 — Privacy and size of a long-lived trail.**
  - `agent-invocation` records carry `session_id`, `model`, `cli_version`, `total_cost_usd` and an
    input digest. They carry no prompt text in the sample (VF-11).
  - The trail lives on the same remote as `main` under either ESC-1 answer, so visibility is the
    same either way.
  - The questions are: is per-invocation cost and session metadata acceptable in a permanent,
    unprunable trail? Does that answer change for **consumer** repos, where `hos-cron` writes the
    same records into the consumer's remote?
  - Growth is about 800 records a day, about 46.5k total. Is there a retention ceiling, or is the
    trail unbounded by design (it is the dissertation's empirical substrate, D23)?
- **ESC-7 — Milestone and sequencing.**
  - #1803 is v0.7.0 / `priority:high`.
  - Its natural close depends on TD-1538 slices in #1538's milestone, v0.7.10. Those slices are
    blocked on #1538 ESC-1..6, unanswered since 2026-09-25.
  - The options:
    - **(a)** keep #1803 in v0.7.0, blocked on #1538;
    - **(b)** carve a v0.7.0 slice that needs no #1538 ruling (FR-3 detection, FR-4 failure
      recording against the existing `_sync_audit_logs`, FR-6 documentation) and leave
      FR-5/FR-7 to #1538;
    - **(c)** move #1803 to v0.7.10.
- **ESC-8 — Response to a detection failure.** When FR-3 fails, what happens?
  - The options: log-only; an audit event; a needs-human escalation; or a dashboard/alert
    (precedent: #1944 D7 "no GitHub issue filing", alerting via Grafana).
  - Should a persistent sync failure ever block anything? NFR-2 says it must not wedge a cycle.
    Escalating to a human is a governance call.
  - The human also sets the acceptable lag (the FR-1 bound) if the default of one cycle is not
    acceptable.

## 9. Traceability

| Requirement | Source |
|---|---|
| FR-1, FR-7 | #1803 "Evidence loss", "back-committed or written off"; #1538 Scope "sweep the existing backlog" |
| FR-2 | TD-1538 TD-VF-9 / ESC-4 |
| FR-3 | #1803 "the gap should be detectable"; #1517 (liveness monitor) |
| FR-4, NFR-2 | #1803 (silent stall); DECISIONS 2026-09-05 (42 h silent overseer stall); `bin/hos-cron:509,544,546` |
| FR-5 | TD-1538 TD-VF-8; `bootstrap/hos_repo_sync.sh:137` |
| FR-6 | #1803 "consumers read a trail that silently ends"; VF-6 |
| FR-8 | #1803 consequence 3; #1749 |
| FR-9 | TD-1538 TD-VF-5 (441 hand-written names) |
| NFR-1 | #1803 "must not race concurrent cycles"; VF-4 sync timestamps |
| NFR-3 | #988; `bin/hos-cron:514-521` |
| NFR-4 | #1538 scope; `setup_branch_protection.sh:128` |
| NFR-5 | VF-1; TD-1538 TD-VF-13 |
| NFR-6 | CLAUDE.md "Shell usage under the sandbox" |
| NFR-8 | `hos-cron` ships to consumers; TD-1538 ESC-3 |

---

## Escalation flag (CORE self-flag)

RISK: MEDIUM. This is a requirements document for an audit-trail durability control. If it were
wrong in the direction of committing to `main`, it would contradict a human ruling and open the
#1749 forgery channel.
CONFIDENCE: HIGH on the measurements in VF-2..VF-12; they were re-run in this session.
LOW-to-MEDIUM on the pre-2026-09-01 history (VF-1: shallow clone, not inspectable).
Change classification: **structural**, if #1803 is re-scoped from "commit to `main`" to the
trail-of-record framing. That is why it is ESC-1 and not applied. No spec file was edited.

## Human Review Required

- ESC-1 must be answered before an architect or technical-design pass starts.
- ESC-4 and ESC-5 should be answered together with TD-1538 ESC-1 and ESC-2. They are the same
  decisions, so answer each once.
- The VF-4 measurement is a point-in-time snapshot (2026-10-11T23:1xZ). Re-run it at close-out
  (FR-7).
