# REQUIREMENTS-038 — Out-of-band clone sync: the execution-copy boundary, currency, and atomic repair

**Status:** DRAFT for architect. Four decisions are already **settled by the human** and are
carried here as bound premises, not re-opened (§1). Six points remain genuinely open and are
escalated (§4); architect may proceed on the settled requirements but MUST NOT bind the
escalated points until the human rules them.
**Date:** 2026-08-05
**Author:** pm-agent
**Source issue:** #1202 — "design: Human clone sync via cron — cadence, repair pass, and
drift-safety markers." Thread comprises the desktop design handoff (2026-08-02), a
re-measurement review, the *"Design decisions — resolved by @ScottThurlow"* comment (Decisions
1–4), the amendment scoping Decision 1 to all of `bin/`, and the `bin/`-stays-tracked comment
that exposed the consumer scope gap.
**Related:** #1200 (shipped — verified, VF-038-3), #1201 (open, v0.7.2 — to be re-scoped as the
implementation of this design or closed as superseded), #1185 (closed), #1183 (open),
#1146 (open, v0.7.2 — owns the sandboxing of the worker/overseer roles that VF-038-6 touches).
**Consumers:** `architect` (next), then `technical-design`.
**Scope note:** This document says WHAT and WHY only. No file layouts, no script names, no
function signatures, no crontab syntax, no schema-as-code. The marker is specified as *which
fields must exist and what they mean*, never as a serialization. Every interval and threshold
below is a **recommended default with a stated floor**; the binding values are the human's (§4).

---

## 0. Verification findings — where this design meets the repo

Per the thread's own method note (*"a design document that asserts current configuration state
should carry the command that produced the assertion"*), every finding below carries the command
that produced it, re-run in this session (2026-08-05) rather than inherited from the thread.
Six of the nine change the requirements rather than merely confirm them.

**VF-038-1 — CONFIRMED-WITH-CORRECTION: the installer does *not* copy "all of `bin/`" today, and
three launchers reach consumers by no path at all.** The amendment's premise (*"`bootstrap/hos_install.sh`
already copies all of `bin/` into consumer projects"*) is stale. `framework_consumer_files.txt`
lists exactly three `bin/` entries — `bin/hos-cron`, `bin/hos-trim-logs`, `bin/lib/git-credentials.sh`.
`bin/hos-human` is copied by a *separate* block (`hos_install.sh:2019–2025`). `bin/hos-worker`,
`bin/hos-overseer`, and `bin/hos-suspend` are shipped to consumers by **neither** path. The
installer's own comment at `hos_install.sh:1822` claims *"Covers: all of bin/ (incl. bin/lib/)"* —
the comment is wrong. **Consequence:** "copy all of `bin/`" is not a redirection of an existing
copy; it is partly a *new* ship-set decision, and the ship-set list is where it must be expressed
(FR4). Any design that assumes the copy already happens wholesale will silently omit three files.
*Command:* `cat scripts/framework/framework_consumer_files.txt`; `grep -n "bin/hos-human" bootstrap/hos_install.sh`

**VF-038-2 — CORRECTION: no programmatic crontab writer exists. Both installers only *print*
crontab lines for a human to paste.** `hos_install.sh:2452/2456/2459` are `echo` statements inside
a "Next steps" block; `hos_setup_partner.sh:212–221` is a `printf` block headed *"Suggested crontab
entries (run: crontab -e)"*. **Consequence:** "crontab generation points at `<project>/bin/`" is a
change to *emitted instructions*, and the migration of already-installed crontabs (amendment item
3) cannot be automated by editing a generator — there is nothing that writes a crontab. Migration
must be **detect-and-report plus documented human action**, not a silent rewrite (FR12, FR13).
*Command:* `sed -n '2440,2462p' bootstrap/hos_install.sh`; `sed -n '205,225p' bootstrap/hos_setup_partner.sh`

**VF-038-3 — CONFIRMED: #1200 has shipped.** `bootstrap/hos_repo_sync.sh` now emits an unmissable
`STALE — HEAD is N commit(s) behind origin/<branch>` report on stderr whenever the sync did not
succeed, and classifies the cause **structural** (a filesystem/permission restriction that will not
resolve by retrying) vs **transient** (network/auth/dirty tree/divergence). Issue #1200 is closed.
**Consequence:** Decision 2's stated precondition (*"defer cadence until #1200 ships"*) is now
**met**, but the second half (*"observe real staleness for a few days, then decide from data"*) has
not been performed. This document therefore does not pick a cadence; it requires the mechanism be
cadence-parameterised so the value can be set later without redesign (FR15, §3, §4-Q2).
*Command:* `bash bootstrap/query_issues.sh --app worker --issue 1200`; `cat bootstrap/hos_repo_sync.sh`

**VF-038-4 — NEW, load-bearing for Decision 3: no interactive session registers a lock, so a
lock-based skip cannot see the sessions it exists to protect.** `$_HOS_DIR/locks/` is created and
written *only* by `bin/hos-cron` (`_LOCK_DIR="$_HOS_DIR/locks/hos-cron-${ROLE}-${PROJECT}.lock"`,
line 180). `bin/hos-human`, `bin/hos-worker`, and `bin/hos-overseer` contain no reference to
`_HOS_DIR` at all. **Consequence:** Decision 3 makes the lock the *primary* control, and the
primary control does not currently exist for the exact case it was chosen for — an interactive
Human session. Making interactive sessions lock-registering is a prerequisite of Decision 3, not
an optional extra (FR16, FR17).
*Command:* `grep -rn "_HOS_DIR\|locks/" bin/hos-cron bin/hos-human bin/hos-worker bin/hos-overseer bin/hos-suspend`

**VF-038-5 — NEW: today's sync records no pre-state, performs no repair, and suppresses its own
retry after a partial failure.** `hos_repo_sync.sh` never records HEAD before operating; has no
notion of restoring a tree; and writes `last_sync_epoch` at the end of the **pull/fast-forward
failure** path as well as the success path, so a failed sync silences the next attempt for the
whole interval (default 900s). It *does* already write its state file atomically (`mktemp` + `mv`),
guard state-directory ownership, and refuse to touch a dirty tree — those are sound precedents to
reuse. **Consequence:** the atomicity/repair requirements (FR19–FR22) are genuinely new behaviour,
and one of them is a bug fix to existing code: state must record the *outcome*, and a failed
attempt must not suppress the next one (FR22).
*Command:* `cat bootstrap/hos_repo_sync.sh`

**VF-038-6 — CORRECTION, material: the fork is at A for the Human clone only. For Worker and
Overseer the execution path is measurably open, and it is open in production right now.** The
thread's review concluded *"the current state is A … the escalation path has not opened."* That is
true of the Human clone and only the Human clone. Measured this session:
- `Human/.claude/settings.local.json` exists, 45 deny rules, still carrying `Edit(./bin/**)` and
  the absolute-path variant (mtime 2026-08-04 23:04 UTC — the file has changed since the thread's
  measurement; the `bin/` rules survived).
- `Worker/.claude/settings.local.json` and `Overseer/.claude/settings.local.json` **do not exist.**
  A write probe into `Worker/bin/` from inside this sandboxed autonomous session succeeded.
- The live crontab executes `…/HumanOversightSystem/Worker/bin/hos-cron --role worker`,
  `…/Overseer/bin/hos-cron --role overseer`, and `…/Worker/bin/hos-trim-logs` — i.e. the very files
  that probe showed writable — as the user, outside any sandbox.
- `bin/**` *is* in `scripts/framework/protected_surfaces.txt`, so a **merged** change to `bin/`
  requires human approval. The direct working-tree write bypasses that gate entirely: nothing
  merges, and cron executes the file on its next tick.
- The same crontab shows `…/CondoParkShare/Worker/bin/hos-cron` — a **consumer project**, same
  shape, confirming the final comment's "this is a framework property, not a three-clone problem."

**Consequence:** Decision 1 is not merely a tidy-up of a closed hazard; for two of three HOS roles
and for at least one consumer it closes a live one. This does not re-open Decision 1 — it raises
its urgency and it changes the *sequencing* framing (FR13): for the Human clone the sequencing item
is *removal* of a protection that exists; for Worker/Overseer there is nothing to remove and the
protection has to be *created*. This overlaps the open scope of **#1146** (sandbox worker +
overseer) and **#1183**; it is surfaced here, not re-filed, and §4-Q1 escalates whether an interim
mitigation is wanted before copy-on-install lands.
*Commands:* `python3 -c "…json.load(open('<clone>/.claude/settings.local.json'))…"` for each clone;
`touch Worker/bin/.sync-probe`; `crontab -l | grep hos`; `grep -n "bin/" scripts/framework/protected_surfaces.txt`

**VF-038-7 — NEW, decisive for the currency check: the existing generated-file guard pattern cannot
be reused, because CI cannot see the artifact.** `tests/framework/test_scripts_index.py` (and the
CODEOWNERS guard it mirrors) work by regenerating into a temp path and diffing byte-for-byte
against the **committed** artifact — both sides are in-repo, so a CI test can compare them. Under
Decision 1 the executed copy lives *outside every clone*, is not committed, and is invisible to CI
by construction. **Consequence:** the currency check cannot be a repository test of the
`gen_codeowners.sh` → `CODEOWNERS` shape, however much the shape is the right *intent*. It must run
**at the execution site, at execution time** (FR7–FR9). Architect should expect to spend design
effort here; this is the one requirement the thread's stated analogy does not transfer to.
*Command:* `sed -n '1,55p' tests/framework/test_scripts_index.py`

**VF-038-8 — CONFIRMED: `.claude/settings.json` is tracked, is merged-never-overwritten by the
installer, carries an executing `hooks` block, and is *not* a protected surface.** It is in
`git ls-files`; `.claude/settings.local.json` is gitignored. `hos_install.sh:1719–1757` merges three
`permissions.allow` entries into an existing file and only copies wholesale when none exists — that
is not template generation, and no template exists. The tracked file contains a `hooks.SubagentStop`
entry that executes a script. **Consequence:** Decision 4 is a three-part change (untrack, add a
template, generate per role), and because the file it replaces *executes code outside the sandbox*,
the template inherits that property: the template must be a **protected surface**, or Decision 4
converts a reviewed artifact into an unreviewed one — the exact inversion the decision's own caveat
warns against (FR24–FR26).
*Command:* `git ls-files .claude/`; `sed -n '1719,1757p' bootstrap/hos_install.sh`;
`python3 -c "import json;print(list(json.load(open('.claude/settings.json')).keys()))"`

**VF-038-9 — CONFIRMED: `<project>/` exists as a real directory with real HOS content, and an
out-of-clone execution precedent already runs in cron.** `/home/scott/Code/HumanOversightSystem/`
contains `bin/claude-role`, `.config/hos/`, and the three clones. The live crontab additionally runs
`/home/scott/.config/hos/worker-unstick.sh` — a script outside every clone, already executing on a
timer. Separately, `bin/hos-cron` already resolves a machine-local state root
`_HOS_DIR="${HOS_STATE_DIR:-${HOME}/.hos}"` and creates `locks/`, `wakeup/`, `last-run/`, `suspend/`,
`validation-cache/`, `test-clean/` under it. **Consequence:** HOS already owns a per-machine,
out-of-every-clone, env-overridable state root. It is the obvious home for the marker (FR22) and the
obvious candidate answer to the consumer scope gap (FR27, §4-Q4) — a consumer needs no `<project>/`
parent if the execution copy is keyed by project under that root.
*Commands:* `ls -la /home/scott/Code/HumanOversightSystem/ /home/scott/Code/HumanOversightSystem/bin/`;
`grep -n "_HOS_DIR" bin/hos-cron`; `crontab -l | grep hos`

---

## 1. Bound premises — settled by the human, not re-opened here

These are inputs. Requirements in §2 are *derived from* them. Architect must not re-litigate them;
if any is found to be unimplementable, that is an escalation to the human, not a redesign.

**P1 (Decision 1, as amended) — the repo is the source of truth; an out-of-clone copy is what
executes.** All of `bin/` — `hos-cron`, `hos-trim-logs`, `hos-human`, `hos-worker`, `hos-overseer`,
`hos-suspend`, and `bin/lib/` — stays version-controlled and PR-reviewed in the repo, and is
**copied at install time** to a location outside every clone. Cron and interactive launchers execute
the copy. The security property this buys: the agent may edit the source (gated by PR review, and
`bin/**` is a protected surface requiring human approval), but **changing what cron executes
requires a human-run install**, not a merge. `bin/lib/` must be copied with the launchers or the
copies break on first `source`.

**P2 (Decision 2) — cadence is deferred.** The hourly-vs-daily choice is not made in this document.
See §3 and §4-Q2.

**P3 (Decision 3) — lock-based skip is the default control; the marker is a backstop.** Sync is
skipped entirely while a session is active. Mid-session mutation must be made *impossible*, not
merely survivable. A session that consequently never syncs is handled by #1200 telling it that it
is stale.

**P4 (Decision 4) — `.claude/settings.json` becomes generated per role from a template at install
time, and is no longer tracked.** The **template** becomes the reviewed artifact, and the decision's
own caveat is binding: the generated-template model *must preserve* the version control and PR
review that tracking the file provided.

**P5 (final comment) — `bin/` stays tracked in the HOS repo.** It is simultaneously the source of
truth and the release payload shipped to consumers. Gitignoring it here would empty the release
bundle. The gitignore question is live only for a *consumer's installed copy*, and only if that copy
lands inside the consumer's repo (§4-Q4/Q5).

---

## 2. Functional requirements

Each FR is testable; the *Verify* line states the acceptance check.

### A. The execution-copy boundary (derives from P1)

**FR1 — The executed copy of every `bin/` launcher MUST live outside every clone the agent can
write.** No path that cron or an interactive launcher executes may be inside a repository working
tree that an agent session can modify. The location MUST be one an agent session cannot write and
that only a human-run install writes.
*Verify:* for each crontab entry and each documented launcher invocation, the executed path resolves
outside every clone; a write probe to that path from inside an agent session fails; no HOS-authored
instruction or script directs a session to write it.

**FR2 — Changing what cron executes MUST require a human-run install, and MUST NOT be achievable by
a merge alone.** Merging a change to `bin/` in the repo MUST have no effect on the executing copy
until an install is run by a human.
*Verify:* a merged change to a `bin/` source file leaves the executed copy byte-identical until an
install runs; the install is not invoked by any automated/agent path.

**FR3 — The copy MUST be whole: all launchers plus `bin/lib/`, with the executable bit preserved.**
Splitting the directory — some files copied out, some executed in place — is prohibited, because it
reintroduces the ambiguity of a directory that is both a source and an execution path.
*Verify:* every file the launchers `source` or exec is present at the execution location; each
launcher runs from a clean environment with no reference back into a clone for its own dependencies;
permissions are preserved.

**FR4 — The set of files that ship and are copied MUST be declared in one list, and the list MUST be
guarded against silent omission.** Per VF-038-1 the current ship-set omits three launchers and
`hos-human` is copied by a second, separate code path. There MUST be exactly one declaration that
both the copy step and the install manifest read, and a test MUST fail if a file present in `bin/`
is absent from that declaration.
*Verify:* adding a new file to `bin/` without adding it to the declaration fails a test; no launcher
is copied by a code path other than the one the declaration drives; the manifest cannot declare a
file the copy did not ship.

**FR5 — `bin/` MUST remain tracked in the HOS repo (P5), and MUST remain a protected surface.** The
review property Decision 1 depends on is `bin/**` requiring human approval to merge; that must not
be weakened as a side effect of the source/copy split.
*Verify:* `bin/**` is present in the canonical protected-surface list and the generated CODEOWNERS
after the change; a PR touching `bin/` still requires human approval.

**FR6 — In-clone `bin/` MUST NOT be an execution path once migration completes, and the design MUST
state which clones' `bin/` is agent-writable and why that is acceptable.** After migration the
clone's `bin/` is source only. The design MUST record the residual: a clone's `bin/` remains
agent-writable in the Worker and Overseer clones today (VF-038-6), and that is acceptable *only*
because nothing executes it. If anything still executes it, the residual is a live escalation path,
not a residual.
*Verify:* no crontab entry, systemd unit, `.envrc`, documentation step, or script invokes a launcher
from inside a clone after migration; a written statement of the residual exists and matches
measurement.

### B. Currency and drift of the copy (P1's stated cost)

**FR7 — The executed copy MUST detect at run time that it is not current with its repo source, and
MUST report it loudly.** Because CI cannot see the copy (VF-038-7), the check runs at the execution
site each time a launcher starts. "Loudly" means the same standard #1200 established: an unmissable
report on stderr that survives stdout filtering, naming the drift and what to do about it.
*Verify:* with the repo source changed and no install re-run, the next launcher invocation emits a
drift report identifying the affected file(s); with source and copy in agreement the report is
absent.

**FR8 — The currency check MUST NEVER self-heal.** It MUST NOT copy, update, patch, or otherwise
reconcile the executed copy from the repo source. A check that repairs itself from a
source an agent can write is an automated path from an agent edit to unsandboxed execution — it
would destroy the exact property P1 exists to create.
*Verify:* the drift path contains no write to the execution location; after a detected drift the
executed copy is byte-identical to what it was before the check ran; only a human-run install
changes it.

**FR9 — The check MUST distinguish *stale* from *unrecognised*, and MUST treat them differently.**
A copy that matches some earlier committed state of its source is **stale** — old but reviewed. A
copy that matches *no* committed state of its source has been modified outside the install path and
is **unrecognised** — a tamper signal. Stale MUST warn and escalate on persistence; unrecognised
MUST fail closed (refuse to run) and escalate immediately.
*Verify:* a copy set to a prior committed revision of its source is classified stale and the
launcher still runs; a copy with a hand-edited byte is classified unrecognised, the launcher
refuses to run, and an escalation is produced. *(The stale-path response — warn-and-escalate vs
halt — is §4-Q3.)*

### C. Migration and sequencing (derives from P1 + VF-038-2 + VF-038-6)

**FR10 — Already-installed crontabs that name an in-clone launcher MUST keep working throughout
migration.** No step may break a running installation. Because the clone's `bin/` remains tracked
and present (P5), the old path continues to resolve; the design MUST NOT rely on removing it to
force migration.
*Verify:* with a pre-migration crontab unchanged, worker/overseer/trim cycles continue to run
successfully after the new mechanism is installed.

**FR11 — Emitted crontab instructions MUST name the execution location, in every place they are
emitted.** Both installers currently print instructions (VF-038-2); both must be updated, and any
setup documentation that reproduces a crontab line must be updated with them.
*Verify:* no emitted or documented crontab line names an in-clone path after the change; a grep of
installers and docs for an in-clone launcher path returns only historical/migration context.

**FR12 — The system MUST detect and report a crontab still pointing at an in-clone launcher.**
Because no component writes crontabs, migration cannot be automatic; detection is what prevents the
silent half-migrated state in which the old escalation path stays open indefinitely. The detection
MUST run somewhere a human or an automated cycle will see it, and MUST name the exact line to
change.
*Verify:* with a crontab entry naming an in-clone launcher, the detection fires and prints the
offending line and its replacement; with all entries migrated it is silent.

**FR13 — Protection changes MUST be sequenced strictly after copy-on-install and crontab migration
are verified, and the sequencing MUST be stated per clone.** The amendment states this for the Human
clone's `Edit(./bin/**)` **removal**. VF-038-6 shows the Worker and Overseer clones have no such rule
at all, so for them the sequencing item is the **addition** of protection, not its removal, and it
belongs to the open sandboxing work (#1146/#1183) rather than to this change. The design MUST state,
per clone: what protection exists today (measured), what changes, and after which verified step.
*Verify:* a written per-clone sequencing table exists whose "today" column matches a re-measurement
at implementation time; no protection change is scheduled before its stated predecessor step;
removal of the Human clone's `bin/` deny rules is not bundled into the same change as the
copy-on-install mechanism.

**FR14 — `.envrc`'s `PATH_add bin` MUST be resolved explicitly, not left ambiguous.** Once the
clone's `bin/` is source-only, putting it on `PATH` makes the *unexecuted* copy the one a human's
shell finds first — the worst of both worlds. The design MUST either repoint it at the execution
location or drop it, and MUST state which and why.
*Verify:* after the change, typing a launcher name in a clone shell either resolves to the execution
location or is not found; it never resolves to the in-clone source copy.

### D. The sync operation itself (derives from P2, P3)

**FR15 — Cadence MUST be a configured parameter with a stated default and floor, not a value
compiled into the mechanism.** Per P2 the value is not chosen here. Changing it later MUST require a
configuration change only.
*Verify:* the cadence can be changed without editing mechanism logic; the shipped default and its
floor are documented at the point a deployer configures it.

**FR16 — Sync MUST be skipped whenever a session is active, and this is the primary control, not a
fallback.** Mid-session mutation of a clone MUST be impossible by construction rather than made
survivable after the fact.
*Verify:* with a session lock held, a sync attempt performs no git operation that changes the
working tree and records a skip with its reason; with no lock held, sync proceeds.

**FR17 — Every session that could be affected MUST register a lock the sync can observe, including
interactive sessions.** Per VF-038-4 interactive launchers register nothing today, so FR16 is
currently unenforceable for the Human clone — the exact case Decision 3 was chosen for. The lock
MUST be released on every exit path (including abnormal termination) and MUST be reclaimable when
stale, so a crashed session cannot block sync forever.
*Verify:* starting an interactive session creates an observable lock; ending it (normally or by
kill) releases it; a lock left by a killed session becomes reclaimable after a bounded interval and
the reclamation is recorded.

**FR18 — Sync MUST be restricted to fast-forward from the tracked upstream default branch, and
nothing else.** No merge, no rebase, no reset, no force, no stash, no checkout of a different
branch. It MUST skip on a dirty tree and skip when the default branch is not the checked-out branch
(a fetch that updates the local ref without touching the working tree is permitted). Local
uncommitted edits MUST survive. This restriction is what makes an unreviewed automated change to a
clone acceptable: fast-forwarding from the upstream default branch introduces only commits that
already passed the PR gate. Any operation that could introduce un-gated content invalidates the
argument.
*Verify:* each prohibited operation is absent from the mechanism; a dirty tree produces a recorded
skip and no tree change; an uncommitted local edit is present and unchanged after a successful sync;
a divergent branch produces a recorded failure, never a merge or reset.

### E. Atomicity and repair (the thread's sharpest unaddressed item)

**FR19 — The pre-operation commit MUST be recorded before any operation that can modify the tree.**
*Verify:* the recorded pre-state is present and correct before the first tree-modifying command
runs, and is durable across a kill of the sync process at any point.

**FR20 — On any failure the tree MUST be restored to the recorded pre-state; a partially-applied
result MUST NOT be left behind.** A partially applied pull is strictly worse than a stale clone: the
tree matches neither the old commit nor the new one, `git status` looks plausible, and the agent's
file and line citations refer to content that corresponds to no reviewed commit.
*Verify:* an induced failure part-way through leaves the tree at the recorded pre-state; no file
differs from that commit except pre-existing tracked local edits; the failure is recorded, not
swallowed.

**FR21 — On success the tree MUST be verified clean at the new commit before the operation is
reported successful.** "Reported successful" and "actually at the new commit with a clean tree" MUST
be the same condition.
*Verify:* a success record is emitted only when the tree is verified clean at the new commit;
injecting a discrepancy causes the outcome to be recorded as failure.

**FR22 — A pre-existing partial state MUST be detected at start, and the mechanism MUST refuse to
proceed and escalate rather than compound it. A failed attempt MUST NOT suppress the next
attempt.** Both halves are corrections to existing behaviour: `hos_repo_sync.sh` today has no
pre-state notion at all, and it writes its last-sync timestamp on the pull-failure path, silencing
retries for the full interval (VF-038-5).
*Verify:* starting against a deliberately half-applied tree produces a refusal plus an escalation
and no further git operation; after a failed attempt the next scheduled attempt is not suppressed by
interval bookkeeping; the recorded state distinguishes success from failure.

**FR23 — Repair MUST be performed by code, not by a written runbook.** The thread's evidence:
the one manual repair performed needed a hand-written four-step procedure whose expected-commit
value went stale *during* the repair because the branch advanced. A procedure that decays between
authoring and execution is not a control.
*Verify:* recovery from a partial state requires no hand-authored, commit-specific instructions; the
mechanism derives the target state at run time.

### F. The marker (P3's backstop)

**FR24 — A marker MUST record the outcome of every sync attempt, with at minimum: state
(running / ok / skipped / failed), timestamp, the commit before, the commit after, and — when
skipped or failed — the reason.** These are the fields the design must carry; the serialization is
architect's.
*Verify:* each of the five outcome classes produces a marker containing every mandatory field; a
marker missing a mandatory field is detectable as malformed.

**FR25 — The marker MUST be written atomically, so no reader can observe a partial marker.**
*Verify:* a reader sampling continuously during many sync attempts never observes a partial or
malformed marker; the write is not an in-place truncate-and-rewrite.

**FR26 — The marker MUST live outside every clone, and MUST be readable from inside a sandboxed
session.** Inside the tree it could be rewritten by the very agent it exists to inform, and it would
itself be overwritten by the pull it describes. Readability is a requirement, not an assumption: the
per-role sandbox configuration must grant read access to its location, which ties this to P4's
template (FR27).
*Verify:* the marker path is outside all clones; a sandboxed session of each role can read it; a
sandboxed session cannot write it; a sync does not overwrite or delete it as a side effect of
updating the tree.

### G. Per-role settings generation (derives from P4)

**FR27 — `.claude/settings.json` MUST be generated per role at install time from a template, and
MUST no longer be tracked.** The generated result MUST carry the role's required read access —
including the marker location (FR26) — so a role cannot be configured into a state where its
backstop is unreadable.
*Verify:* a fresh install of each role produces a role-appropriate settings file that is not tracked
by git; the file grants read access to the marker location; a pull can no longer be blocked by an
incoming change to this path.

**FR28 — The template MUST be a protected surface, and MUST preserve the review property that
tracking the file provided.** Per VF-038-8 the file being replaced executes code outside the sandbox
(a `hooks` entry). Making it generated without protecting the template converts a reviewed artifact
into an unreviewed one — the inversion Decision 4's own caveat forbids.
*Verify:* the template path is present in the canonical protected-surface list and the generated
CODEOWNERS; a PR touching the template requires human approval; the generated file's provenance
(which template, which role, which release) is recorded.

**FR29 — Generation MUST be deterministic and reproducible, and drift of a generated settings file
from its template MUST be detectable.** Otherwise the same silent-degradation failure FR7 addresses
for `bin/` reappears here.
*Verify:* regenerating from the same template and role produces an identical file; a hand-edited
generated file is detectable as diverged from what the template and role would produce.

### H. The not-an-autonomous-role boundary

**FR30 — The sync mechanism MUST refuse to run in an agent-session environment, and the refusal MUST
be enforced rather than documented.** A sync job runs no agent, launches no model, and makes no
decisions — that is precisely why it is not a violation of the "there is no human cron role" rule.
The guard makes the distinction structural: the presence of agent-session environment variables in
the sync process's environment MUST cause it to refuse to run.
*Verify:* invoked with agent-session environment variables present, the mechanism exits without
performing any git operation and says why; invoked from a clean cron environment it proceeds.

**FR31 — The invariant MUST be stated at the cron entry itself, not only in a design document.** So
that nobody later removes the entry as a governance violation, and nobody later grows a decision
into it.
*Verify:* the emitted crontab instruction carries the invariant as a comment; the mechanism's own
header states it; a reviewer reading only the crontab can tell why this entry is not a human cron
role.

### I. Escalation

**FR32 — Consecutive skips and failures MUST escalate at defined thresholds, and failures MUST be
treated as qualitatively different from skips.** Silent accumulation of skips is exactly how the
originating incident happened. *Recommended defaults (binding values are §4-Q6):* **3** consecutive
skips, **1** failure.
*Verify:* the Nth consecutive skip produces an escalation; the first failure produces one; a
successful sync resets the skip count; the counters are durable across process restarts.

**FR33 — Escalation MUST NOT itself be best-effort.** An escalation that silently fails to be
delivered reproduces the defect. If escalation cannot be delivered, that fact MUST itself be
surfaced at the next session start.
*Verify:* with the escalation channel unavailable, the failure to escalate is recorded durably and
reported at the next session start; there is no code path in which an escalation is attempted, fails,
and is discarded.

### J. Consumer projects — the framework property

**FR34 — The execution-copy boundary MUST apply to consumer installs, not only to the three HOS
clones.** A consumer running the HOS pipeline inherits the identical shape today — measured: a
consumer project's own clone-internal launcher is executed by cron as the user (VF-038-6). The
requirement is a property of the framework; it MUST NOT be satisfied only for HOS's own layout.
*Verify:* a consumer install produces an execution location satisfying FR1–FR3; no consumer crontab
instruction names a path inside the consumer's repository.

**FR35 — The execution location MUST be derivable for a consumer that has a single repository and no
parent project directory, without requiring the consumer to create one.** *Recommended default:* key
the execution copy by project under the existing machine-local HOS state root — the same
env-overridable root that already holds `locks/`, `wakeup/`, `last-run/`, and `suspend/` outside
every clone (VF-038-9). This satisfies FR1 for HOS and consumers with **one** rule and no per-layout
exception, and as a side effect it dissolves the consumer-gitignore question entirely, because
nothing lands inside the consumer's repository. *The binding choice is §4-Q4; if the human instead
places the copy inside the consumer's repository, §4-Q5 must also be answered.*
*Verify:* a single-repo consumer install with no parent directory produces a valid execution
location; the same rule produces a valid location for the three-clone HOS layout; the location is
overridable by the existing state-root configuration.

### K. Relationship to shipped and adjacent work

**FR36 — This mechanism MUST compose with #1200's staleness reporting and MUST NOT duplicate or
weaken it.** #1200 has shipped (VF-038-3) and is load-bearing for P3: a session that never syncs
because it holds the lock is told it is stale rather than silently mutated. Detection (#1200) and
remediation (this document) stay separate concerns.
*Verify:* a session started while stale still receives the #1200 report unchanged; no requirement
here removes, softens, or re-implements that report; the marker (FR24) and the staleness report
agree about the clone's state when both are available.

---

## 3. What this document deliberately does not decide

**Cadence (P2).** Hourly-vs-daily is not chosen here, and architect MUST NOT choose it. The
originating "8 commits behind" measurement was taken while sync was *failing*, so it is evidence of a
broken mechanism rather than an insufficient interval and cannot support the choice. #1200 has now
shipped (VF-038-3), which satisfies Decision 2's stated precondition, but the observation period it
called for has not been run. FR15 exists so the value can be set from observed data later without
redesign. Calibration data recorded in the thread: the default branch advanced **15 commits in
roughly one day**.

---

## 4. Decisions escalated to the human

Genuine product/policy choices I cannot settle from the thread. Architect MUST NOT bind them until
ruled. A recommended default is given for each.

**Q1 — Interim mitigation for the measured Worker/Overseer exposure (VF-038-6).** The thread
concluded the fork sits at A with nothing exposed; that holds for the Human clone only. In the
Worker and Overseer clones `bin/` is agent-writable and cron executes those exact files unsandboxed,
today, and the same shape is live in at least one consumer project. *Recommendation:* treat it as
in-scope of the existing open sandboxing work (#1146/#1183) rather than re-filing, and decide
whether an interim protection is applied to the Worker and Overseer clones **now**, before
copy-on-install lands, or whether the exposure is accepted until then. *Human owns:* interim
mitigation yes/no, and whether this changes #1202's priority or milestone (it currently sits in
v0.6.0 while its sibling #1201 sits in v0.7.2).

**Q2 — Cadence and its floor (FR15, §3).** *Recommendation:* run the observation period #1200 now
makes possible, then set the value; ship a conservative default in the meantime. *Human owns:* the
interval, its floor, and whether the observation period is a prerequisite of implementation or can
run in parallel.

**Q3 — The response to a *stale* copy (FR9).** *Recommendation:* warn loudly and escalate on
persistence, but continue running — a stale copy is old *reviewed* code, not un-gated code, so
halting the autonomous loop on every merged `bin/` change is disproportionate. (Note the
*unrecognised* case is not escalated: FR9 already requires it to fail closed.) *Human owns:* whether
staleness beyond some age should instead halt.

**Q4 — Where the execution copy lives for a consumer project (FR35).** The thread explicitly leaves
this open and calls it a human decision. *Recommendation:* the machine-local HOS state root, keyed
by project — one rule for both layouts, no `<project>/` parent required, and the gitignore question
disappears. *Human owns:* that, versus a location inside the consumer's repository, versus requiring
consumers to adopt a parent-directory layout.

**Q5 — Whether a consumer's installed copy is gitignored — *only if Q4 places it inside the
consumer's repository*.** The trade-off is real in both directions: tracking invites drift and
hand-edits against a source the consumer does not own, while HOS's audit posture generally favours
committed artifacts and a consumer may want the installed pipeline visible in review. *Recommendation:*
moot under the Q4 recommendation; if Q4 goes the other way, gitignore it and rely on the existing
release/manifest provenance records. *Human owns:* the call, and the reasoning is to be recorded
either way.

**Q6 — Escalation thresholds (FR32).** *Recommendation:* 3 consecutive skips, 1 failure, with the
skip counter reset on success. *Human owns:* the numbers, and the escalation channel (a tracked
issue versus a loud session-start failure versus both).

---

## 5. Out of scope

- **Redesigning #1200.** It has shipped; this document treats it as a dependency (FR36).
- **Sandboxing the worker and overseer roles.** That is #1146/#1183. VF-038-6 is surfaced here
  because it corrects a premise this thread relies on, not to absorb that work.
- **The `bin/` source layout.** Moving the source elsewhere (e.g. `scripts/launchers/`) was
  considered in the thread and rejected: it breaks the established ship-set convention and buys
  nothing P1 does not already deliver.
- **Any implementation choice.** File layouts, script names, marker serialization, lock
  representation, and the currency-check algorithm are architect's and technical-design's.

---

## Human Review Required

This document authors new requirements that redefine a security-relevant execution boundary and
introduce new installer behaviour (a MEDIUM-or-above spec change), so per my role I self-flag.

**RISK: MEDIUM–HIGH.** The requirements *reduce* standing risk — they close a path from an agent
working-tree write to unsandboxed execution that VF-038-6 measured as open in two of three HOS roles
and in at least one consumer project right now. The residual risk is concentrated in three places.
First, **FR8**: a currency check that self-heals from repo source would rebuild the exact escalation
path the whole design removes, and it is the natural, convenient thing to implement — it is called
out as a prohibition for that reason. Second, **FR13 sequencing**: removing the Human clone's `bin/`
protection before copy-on-install and crontab migration are verified opens the path for real, which
is what the original handoff mistakenly believed had already happened. Third, **FR28**: Decision 4
un-tracks a file that executes code outside the sandbox, so if the template is not itself a protected
surface the change converts a reviewed artifact into an unreviewed one — a net loss of oversight
dressed as a fix. FR8, FR13, and FR28 are the three that must not be softened in design.

**CONFIDENCE: HIGH** on the requirement set and on the nine verification findings, all re-measured
this session with the commands recorded inline: I read `hos_repo_sync.sh`, `bin/hos-cron`'s lock and
state handling, the installer's ship-set loop and crontab-emission blocks, `framework_consumer_files.txt`,
`test_scripts_index.py`, `protected_surfaces.txt`, all three clones' local settings files, and the
live crontab, and I ran a write probe. **HIGH** specifically on the four findings that correct the
thread's premises (VF-038-1, -2, -6, -7), each of which came from running a command rather than
reading configuration. **LOWER** on: anything about consumer deployments other than the one
consumer project visible in this machine's crontab; the exact behaviour of Claude Code's own
settings/hooks bind-mount hardening, which I did not re-derive and took from the thread; and all six
escalated decisions in §4, which are correctly the human's.

**BLAST RADIUS:** what cron executes as the user, unsandboxed, on every HOS machine and every
consumer machine running the pipeline; the sandbox posture configuration of all three roles; the
installer's ship-set and its emitted setup instructions; and the crontabs of every existing
installation. The implementation touches `bin/**`, `bootstrap/**`, `scripts/framework/**`, and
`.claude/` — all protected surfaces — so the implementation PR requires human approval at merge
regardless of computed tier. A migration executed in the wrong order (FR13) affects running
production installations rather than only new ones.

**Change classification: STRUCTURAL.** It introduces new behaviour (an out-of-band sync operation, a
currency check, a marker, a lock contract for interactive sessions), a new installer obligation
(copy-on-install, per-role settings generation), a new user obligation (a crontab migration existing
operators must perform), and it changes the trust boundary around what cron executes. The four bound
premises in §1 already carry the human's explicit sign-off and are not re-opened; the six decisions
in §4 do not, and architect MUST NOT bind them until the human rules. Architect may begin design
against FR1–FR36 now.
