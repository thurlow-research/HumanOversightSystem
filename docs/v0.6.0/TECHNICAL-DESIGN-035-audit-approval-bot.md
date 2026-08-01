# TECHNICAL DESIGN — ADR-035 deterministic audit-approval bot

**Status:** **REVISION 2, 2026-08-01** — awaiting `architect` re-review. ADR-035 (ACCEPTED FOR DESIGN,
**Revision 3**, 2026-08-01) is the binding input. Revision 2 of this design incorporates the ADR's
Revision-3 dual-lens-panel rulings (AD-15…AD-19) and pm-agent's FR2 correction: it **adds the missing
producer half** the panel found absent (Component N, worker-identity audit-PR producer — AD-15),
formally declares the auditsync approver a **fourth identity class** (Component M, `AGENT-IDENTITY.md`
amendment — AD-16), hardens the predicate with six new rules (AD-17), makes the periodic sweep
**mandatory** (AD-18), and closes the doc-reconciliation and operability gaps (AD-19). All Revision-2
additions are consolidated in **§16**, which supersedes the affected rows of §2 (component map), §12
(build order / PR split), and §14 (coder clearance). DRAFT-1 sections §0–§15 are **left intact** per
the bundle's append/revise convention; where a section is materially changed, an inline **Revision 2**
blockquote points to §16. This document still does **not** clear `coder` to build — the structural
sign-off is now **larger** (§16.9).
**Date:** 2026-08-01 (Revision 2)
**Author:** technical-design
**Consumes:** `docs/v0.6.0/ADR-035-audit-approval-bot.md`, `docs/v0.6.0/REQUIREMENTS-035-audit-approval-bot.md`
**Consumer:** the autonomous `worker`, via a `needs-ai` issue in the v0.7.0 milestone — **only after** the human clears the holds.
**Scope note:** this document is the implementation contract. It describes *what the code must do*.
It contains no application code.

> **Revision 2 changelog (2026-08-01).** Incorporates ADR-035 **Revision 3** (§5, AD-15…AD-19) and
> pm-agent's dated **FR2 correction** in REQUIREMENTS-035 (overseer-authored → **worker**-authored).
> The dual-lens panel (agy adversarial + fable-class completeness) found the DRAFT-1 design **materially
> incomplete**: it specified every *consumer* of the audit PR (approver E, gate exception C, #880 exemption
> H, trigger F) but **no producer** to create the branch, commit the records, and open the PR — the exact
> "consumer built, producer absent" half-mechanism class this repo keeps re-finding. Revision 2 closes it.
> **What changed:** (a) **NEW Component N** — a worker-identity audit-PR *producer* that **replaces**
> (not merely removes) `bin/hos-cron:_sync_audit_logs`; this **amends AD-13/Component I from *remove* to
> *replace*** (AD-15). (b) **NEW Component M** — `docs/AGENT-IDENTITY.md` amended to declare the auditsync
> approver a **fourth identity class** and to record the worker as the audit-PR author (AD-16); the FR2
> author identity is now **worker**, per pm-agent's correction. (c) **§3.5 (NEW)** — six predicate/gate
> hardening rules (AD-17): target-branch=`main`, drop `audit/automation/**`, extension-restrict
> `audit/log/**`, reject zero-content (mode/symlink) changes, fail-closed on patch truncation, and a
> proper unified-diff hunk parser (fixes the `+++`-prefix skip bug). (d) **AD-18** — the periodic sweep is
> now **mandatory** (event-only cannot satisfy FR16); it is co-located in Component N's cron slice. (e)
> **AD-19 doc/operability set** — `OVERSIGHT-RUNBOOK.md` Phase-11 reconciliation (NEW Component O),
> consumer bypass-remediation folded into Components K/L, the FR19 durable-record home resolved to the
> producer's PR path (no runner-local disk), an explicit **kill-switch**, and a chunking/size story. (f)
> **Filed-not-designed:** an independent external liveness monitor (deferred → #1151) and an App-key
> rotation policy (deferred → #152 lineage) are noted, not designed; `gh` is unauthenticated here so both
> deferral issues **still need real issues filed** — flagged, not silently skipped. (g) **Renumbering:**
> the DRAFT-1 tests row (old "Component M") is relettered **Component T** so "Component M" can carry the
> ADR's AGENT-IDENTITY assignment. (h) **Coder-clearance: still NOT cleared** — and the structural
> sign-off is now larger (adds the producer identity + the fourth-identity-class governance amendment).
> The authoritative post-Revision-2 component map, build order, PR split, and coder-clearance are in **§16**.

---

## 0. Verification findings — ADR premises re-checked against `origin/main`, plus new findings

The working tree is ~10 commits behind `origin/main`, so every citation is `git show origin/main:<path>`.
I re-read `require_overseer_approval.py`, `require_tier_ceiling.py`, `require_human_approval.py`,
`require-overseer-approval.yml`, `machine-accounts.env`, `protected_surfaces.txt`, `overseer.md`,
`DECISIONS.md`, `docs/MACHINE-ACCOUNTS-SETUP.md`, `bin/hos-cron`, `scripts/automation/pre_pr_stale_check.py`,
`bootstrap/get_app_token.sh`, and `scripts/framework/setup_branch_protection.sh`.

**The ADR's §0 findings VF-1…VF-5 and AF-1…AF-3 all re-verify as stated.** In particular AF-1 is
confirmed verbatim: `require-overseer-approval.yml` runs under `pull_request_target` **and**
`pull_request_review` with `actions/checkout@v4` pinned to `ref: ${{ github.event.pull_request.base.sha }}`,
with an in-file comment naming #972 and instructing that the PR's reviews are "read as DATA via gh
API calls, never checked out and executed." `require_tier_ceiling.py:_fetch_head_python` is the exact
data-as-fetch model AF-1 points at (fetches head content via `gh api ...contents/{rel}?ref={head_sha}`,
writes to a temp dir, parses, never executes).

The findings below are **new** and change the design. They are numbered TD-VF-n to avoid colliding
with the ADR's VF/AF numbering. **Two of them (TD-VF-1, TD-VF-2) are HIGH and one of them closes the
#1095 verification gap that pm-agent and architect could not close** (both flagged that `gh` was
unauthenticated and they could not read #1095; I read the code #1095 is about).

**Inherited verification gap (unclosed).** `gh` is unauthenticated in this sandbox
(`git ls-remote origin audit-log` returns nothing here; `gh auth status` fails), so I could **not**
confirm the live "zero bypass actors" ruleset state, nor whether the `audit-log` branch currently
exists on the remote, nor read the bodies of #1095/#873/#1151. Those are taken as given. Everything
below that I mark CONFIRMED was read from committed source on `origin/main`.

### TD-VF-1 (severity: HIGH) — the #1095 interim path is **half-built**: the producer-side push to an `audit-log` branch already exists in `bin/hos-cron`. This closes ESC-5's verification gap and changes what "option A vs B" means.

The ADR (VF-3) and pm-agent both state the 2026-06-23 sync was "specified but never built." That is
**only half true.** `bin/hos-cron:189-239` contains a **live, built** `_sync_audit_logs()` that, every
cron cycle, copies `audit/oversight-log.jsonl` and `audit/overnight-loop-log.md` into a detached
worktree and **`git push origin HEAD:refs/heads/audit-log`** (`bin/hos-cron:233`). What does **not**
exist is the *consumer* half — a GitHub Actions workflow that reads `audit-log` and commits those two
files to `main` (VF-3 CONFIRMED: `.github/workflows/` has no audit-sync workflow). So the true current
state is: **the cron machine already accumulates audit history on an `audit-log` branch that nothing
ever merges to `main`.** That is precisely the #1095 broken state, and it means the "interim
sync-branch migration" that ESC-5 option (B) would "ship first" is **partly already present** — the
branch-push producer exists; only the branch→main consumer is missing.

**Consequence for the design (two parts):**
1. This is the concrete answer to the ESC-5 verification gap. The human can now rule ESC-5 knowing
   that #1095's interim path is a *producer-only* half-mechanism (push to `audit-log`, no consumer),
   not a working stopgap. **My recommendation strengthens pm-agent's and architect's lean to option
   (A):** there is no functioning interim path to protect — option (B) would mean *finishing* the
   never-built consumer workflow only to retire it. I still do **not** bind ESC-5; it is the human's
   (§13).
2. `_sync_audit_logs()` and its `audit-log`-branch push are **in scope for disposition** by this
   design: under option (A) they are **removed** (the checked-PR path replaces them); under option (B)
   they stay and the consumer workflow is built first. `bin/**` is a protected surface
   (`protected_surfaces.txt`), so either disposition is human-gated. Component I owns this, **blocked
   on ESC-5.**

### TD-VF-2 (severity: HIGH) — a live, built gate (#880) **forbids the exact commit this design's overseer must make**. The audit PR is incompatible with `pre_pr_stale_check.py` as written, and `_AUDIT_ONLY_FILES` is a fourth duplicate of the audit-file set.

`scripts/automation/pre_pr_stale_check.py:check_audit_log_not_committed()` (#880) returns a violation
if **either** `audit/oversight-log.jsonl` **or** `audit/overnight-loop-log.md` appears in the diff of
any branch that is not `main`:

```
_AUDIT_ONLY_FILES: frozenset[str] = frozenset({
    "audit/oversight-log.jsonl",
    "audit/overnight-loop-log.md",
})
...
def check_audit_log_not_committed(branch, base="main"):
    if branch in (base, "main"):
        return []
    ...
    violations = sorted(_AUDIT_ONLY_FILES & changed_files)
```

This design's core mechanism (AD-3/FR2) is that **the overseer authors a PR — on a branch — whose diff
is exactly those audit files.** As written, `pre_pr_stale_check` would flag that PR as a violation and
the worker's pre-PR gate would refuse to open it. The two mechanisms are in **direct conflict.**

The #880 rationale is narrow: audit files in a *code/feature* branch shift PR HEAD past the validator
artifact commit and break the overseer's staleness check. **An audit-only PR has no code and no
validator artifact, so the rationale is void for it.** The reconciliation is therefore: the #880
prohibition must apply to *feature/fix* PRs only, and must **exempt a PR whose entire diff qualifies
as audit-only** — which is exactly what the shared predicate (AD-2) decides. Note also that
`_AUDIT_ONLY_FILES` is a **fourth hardcoded copy** of the audit-file set (alongside `overseer.md:208-209`,
the AD-5 allowlist, and — see TD-VF-3 — the stale gitignore comments). AD-2's "one shared source" and
AD-5's "single allowlist" must subsume `_AUDIT_ONLY_FILES` too, or the #1135 duplicate-gate class is
merely relocated, not eliminated.

**Consequence.** Component H reconciles `pre_pr_stale_check.py` to the shared allowlist and exempts a
fully-audit-only diff. **This is an architecture-topology question the ADR did not surface** (does the
audit PR coexist with #880 by exemption, or does the mechanism avoid a branch entirely?) → escalated to
`architect` (§13, ESC-A). `scripts/automation/**` is **not** a protected surface (verified: not in
`protected_surfaces.txt`), so H itself is not human-gated by path — but it is load-bearing for the
mechanism to work at all.

### TD-VF-3 (severity: MEDIUM) — the "gitignored" claim about the audit files is stale in **code**, not just docs. `.gitignore` has no `audit/` entry.

VF-4 verified `.gitignore` on `origin/main` has no `audit/` entry (I re-confirmed: `grep -i audit`
over `origin/main:.gitignore` returns nothing). Yet **code comments** assert the opposite:
`pre_pr_stale_check.py:41` — *"These are gitignored append-only operational files"*; `bin/hos-cron:192`
— *"keeping feature PRs free of append-only conflicts."* The files are **not** gitignored; they are
untracked-and-unignored, kept out of feature branches only by the #880 check (TD-VF-2). The design MUST
NOT assume any gitignore scaffolding exists (VF-4), and the stale "gitignored" comments in these two
files should be corrected in passing wherever this design edits them (H, and I if option A). This also
means the first qualifying audit PR genuinely *creates* the tracked files (AF-2) — there is no ignore
rule to fight, confirming AD-9.

### TD-VF-4 (severity: MEDIUM) — the auditsync identity has **no token-minting path**. `get_app_token.sh` recognises only `worker|overseer|human`.

`bootstrap/get_app_token.sh` accepts `--app [worker|overseer|human]` and maps each to
`HOS_{ROLE}_APP_ID` / `HOS_{ROLE}_PEM` / `HOS_{ROLE}_BOT_LOGIN`, with a #703 identity-mismatch guard
that fails if the authenticated login ≠ the declared `HOS_{ROLE}_BOT_LOGIN`. There is **no `auditsync`
case.** The old 2026-06-23 design stored `HOS_AUDIT_SYNC_APP_ID` / `HOS_AUDIT_SYNC_PRIVATE_KEY` as
**GitHub Actions secrets** (a workflow-token path), not as a `get_app_token` role. For the bot runtime
(Component E) to authenticate as the auditsync identity from a script, it needs either (a) a new
`auditsync` role in `get_app_token.sh` + `apps.env`, or (b) the Actions-secret path if the bot runs as
a workflow.

**Consequence.** Component G adds the `auditsync` role to `get_app_token.sh` and `apps.env.template`
(AD-1), with the #703 identity guard extended to `HOS_AUDITSYNC_BOT_LOGIN`. `bootstrap/**` is a
protected surface → human-gated. Which auth path is used depends on whether the bot runs as a workflow
or a cron script — that is **ESC-3-adjacent** (merge/actor topology). Design accommodates both (§9).

### TD-VF-5 (severity: MEDIUM) — the ADR's illustrative predicate signature under-specifies the inputs; the GitHub *files* API supplies exactly what AD-6 needs and nothing attacker-executable.

AD-2 sketches `classify_audit_diff(changed_paths, added_lines_by_path, existing_content_probe)`. Three
separate inputs (paths, added lines, "does it already exist") are all delivered by a **single** trusted
GitHub call, `gh api repos/{repo}/pulls/{pr}/files --paginate`, whose per-file records carry:
`filename`, `status` (`added`/`modified`/`removed`/`renamed`), `additions`, `deletions`, and `patch`
(the unified-diff hunk, or absent for binary/oversized). `status == "added"` **is** the
"existing_content_probe" AF-2 needs (first-creation); `deletions == 0` **is** additions-only (FR7);
`patch` supplies the added line text for well-formedness (FR8). GitHub computes `status` server-side
from `base...head`; it is not attacker-forgeable, and the `patch` text is inert data parsed as strings
(never executed), satisfying AF-1.

**Consequence.** §3 refines AD-2's signature to `classify_audit_diff(files, allowlist)` over a list of
**file records** (a documented subset of the files-API shape). This is a *clarifying* refinement of an
illustrative signature, not a departure from AD-2's contract; flagged to `architect` for confirmation
(§13, ESC-B) only because the ADR wrote a specific signature.

### TD-VF-6 (severity: MEDIUM) — the well-formedness contract for the markdown log is not derivable from `origin/main`; SPEC-888 already moved per-event logging off the JSONL file.

FR8/AD-6 requires added entries to be "structurally valid for their format (…markdown-log appends match
the expected record shape)." For `.jsonl` this is precise (each added line parses as one JSON object).
For `audit/overnight-loop-log.md` it is not: the **writer of that file is not locatable on `origin/main`**
— `bin/hos-cron` only *reads/copies* it in `_sync_audit_logs`; nothing in `scripts/**` writes it (the
per-event writer, `cycle_log.py`, writes **per-entry files under `audit/log/<YYYY>/<MM>/`** — SPEC-888,
#888 — and its header notes this "replaces the old append to the single audit/oversight-log.jsonl").
So `oversight-log.jsonl` is a **legacy append target**, `audit/log/**` is the **current** per-event
surface (write-once files, always `status == "added"`), and `overnight-loop-log.md`'s record shape is
producer-defined and unverifiable here.

**Consequence.** §3.3 specifies a **per-format validator registry** keyed by path/extension:
`.jsonl` → strict JSON-object-per-added-line; `audit/log/**` → JSON-object-per-file (write-once);
`overnight-loop-log.md` → a documented record-block shape that **must be reconciled with the producer
at build time**, and **fail-closed** (the file does not qualify) if the added content does not match the
reconciled shape or if the shape cannot be determined. This also couples to ESC-2: the human may choose
to drop `overnight-loop-log.md` from the allowlist, which removes the reconciliation need entirely.
Flagged as a build-time reconciliation item (§13, ESC-C).

### TD-VF-7 (severity: LOW) — the implementation touches **five** protected surfaces, so the whole build is human-gated and exceeds the 15-file soft split limit.

The full build edits `scripts/framework/**` (predicate, gate, allowlist, machine-accounts.env),
`bootstrap/**` (get_app_token, apps.env), `bin/**` (hos-cron, option A), `.claude/agents/**`
(overseer.md), and `.github/workflows/**` (the bot workflow) — **all** in `protected_surfaces.txt`.
Therefore the implementation PR trips `require_human_approval` and **cannot merge without a human
approver regardless of computed risk tier** (AD-11/FR11), and the audit-approval bot's own review can
never satisfy that gate (AD-4). The file count (~13 source + ~7 test ≈ 20) is over the 15-file soft
limit but under the 25-file hard ceiling → a split is required (§12).

---

## 1. Terminology and canonical rules (binding)

Every artifact this design touches uses these terms and no coined substitutes.

| Term | Precise meaning in this design |
|---|---|
| **Audit PR** | A pull request, authored by the overseer identity, whose diff `classify_audit_diff` (§3) returns `qualifies == True` for. |
| **Audit-only** | Every changed path matches the AD-5 allowlist (§4). One non-allowlisted path disqualifies the whole diff. |
| **Additions-only** | Every changed file has `deletions == 0` and `status ∈ {added, modified}`. `renamed`/`removed`/`copied` disqualify (FR7/AD-6). |
| **First-creation-aware** | `status == "added"` qualifies (the file does not yet exist on `main`) — the AF-2 case. It is NOT rejected for "not already existing." |
| **Well-formed** | Every added line is valid for its per-format validator (§3.3): JSONL → one JSON object per line; `audit/log/**` → one JSON object per write-once file; markdown log → the reconciled record shape (TD-VF-6). |
| **Identity-bound exception** | The `require_overseer_approval` exception fires only when the diff qualifies **AND** an `APPROVED` review exists from the specific `BOT_AUDITSYNC_USERNAME` login (AD-3). Never a diff-shape-only waiver. |
| **Fail-closed** | Any ambiguity, fetch failure, absent hunk, unknown format, or unclassifiable diff → `qualifies == False` → the normal overseer requirement applies → escalate. Never auto-qualify (FR18/AD-3/AD-6). |
| **Withhold-and-escalate** | The bot's disposition for a non-qualifying PR: no approval, no force/close/rewrite, leave open, route to the human channel (AD-7/FR13). |

**The load-bearing rule sentence (AD-3 — quote verbatim wherever the exception is documented):**

> The overseer requirement is treated as satisfied for a PR only when BOTH the diff qualifies under the
> shared predicate AND an APPROVED review exists from the named audit-approval identity. If either is
> absent, the gate falls through to requiring the overseer's own approval. An audit-only diff alone
> never discharges the gate.

**The scope-boundary sentence (state wherever the bot's authority is characterised):**

> This is not a general "deterministic bots may approve PRs" precedent. It is defensible only because
> audit-log entries are inert data — nothing imported, nothing that changes agent behavior. A malformed
> or malicious audit entry has categorically lower blast radius than any code change.

---

## 2. Component map

| # | Artifact | Kind | Binding | Protected surface? | Blocked on |
|---|---|---|---|---|---|
| A | `scripts/framework/audit_predicate.py` | NEW module + CLI | AD-2, AD-5, AD-6, AF-1, AF-2 | yes (`scripts/framework/**`) | structural sign-off (ADR §3); ESC-2 for membership only |
| B | `scripts/framework/audit_allowlist.txt` | NEW config | AD-5, AD-9, FR9 | yes | **ESC-2** (membership) |
| C | `scripts/framework/require_overseer_approval.py` | EDIT | AD-3, AD-4, AF-1, FR10, FR11 | yes | **structural sign-off** |
| D | `scripts/framework/machine-accounts.env` | EDIT config | AD-1, AD-4, AF-3 | yes | structural sign-off |
| E | `scripts/framework/audit_approval_bot.py` | NEW module + CLI | AD-2 (call site 1), AD-7, FR4, FR13, FR19 | yes | structural sign-off; ESC-4 (disposition detail) |
| F | `.github/workflows/audit-approval.yml` (or a cron launcher) | NEW | AD-1, AF-1, FR14 | yes (`.github/workflows/**`) | **ESC-1** (cadence), **ESC-3** (merge actor) |
| G | `bootstrap/get_app_token.sh` + `bootstrap/apps.env.template` | EDIT | AD-1 (TD-VF-4) | yes (`bootstrap/**`) | structural sign-off |
| H | `scripts/automation/pre_pr_stale_check.py` | EDIT | TD-VF-2, AD-2 (#880 reconcile) | no | ESC-A (architect) |
| I | `bin/hos-cron` `_sync_audit_logs` | EDIT / REMOVE | TD-VF-1, FR17, AD-8 | yes (`bin/**`) | **ESC-5** (#1095 ordering) |
| J | `.claude/agents/overseer.md` | EDIT | AD-5 (reconcile exempt list) | yes (`.claude/agents/**`) | **ESC-2** (membership) |
| K | `DECISIONS.md` | APPEND (new dated entry) | AD-8, FR17 | no | **structural sign-off** |
| L | `docs/MACHINE-ACCOUNTS-SETUP.md` | EDIT in place | AD-8, FR17 | no | **structural sign-off** |
| T | `tests/framework/**`, `tests/automation/**` (relettered from "M" in Revision 2 — see §16.7) | NEW / EDIT tests | §11 | no | follows its component |

**Explicitly NOT built** (ADR out-of-scope, AD-10 / §4 non-goals): any log rotation/compaction path
(forbidden by additions-only, by construction); any ruleset-bypass actor or direct-push path (AD-1,
FR1 — no code path may acquire content-write or bypass); any general deterministic-approver framework;
any reclassification of a code/config path as "audit"; any widening knob (AD-2 anti-tamper — knobs may
only narrow). The predicate does **not** import `gh`, network, or a model (FR4).

> **Revision 2 (2026-08-01) — this component map is superseded by §16.7.** Three components are **added**
> — **M** = `docs/AGENT-IDENTITY.md` fourth-identity-class amendment (AD-16), **N** = the worker-identity
> audit-PR *producer* (AD-15, the missing half), **O** = `docs/OVERSIGHT-RUNBOOK.md` Phase-11
> reconciliation (AD-19b). The DRAFT-1 **tests** row is relettered **T** (freeing "M" for the ADR's
> AGENT-IDENTITY assignment). Component **I**'s disposition changes **remove → replace** (AD-15; see the
> Revision 2 note at §10.2). See **§16.7** for the authoritative table.

---

## 3. Component A — `scripts/framework/audit_predicate.py` (the single shared authority)

**Purpose.** AD-2's "one function, two importers, zero copies." This module is the *sole* decision of
whether a diff is audit-only-and-well-formed. It is imported by Component E (the bot's approve/withhold
decision), Component C (the gate exception), and — per TD-VF-2 — consulted by Component H
(pre_pr_stale_check's #880 exemption). All three go through this one function; none re-implements it.

**Purity (matches `require_tier_ceiling.py`/`require_human_approval.py` discipline).** No subprocess,
no network, no `gh`, no model, no filesystem writes inside `classify_audit_diff`. Callers fetch the PR
file records (via `gh`, at the head SHA, as DATA — AF-1) and read the allowlist file, then pass both
in. Fully unit-testable with synthetic inputs — which is the only way the fail-closed branches get
exercised.

### 3.1 Types

- `FileRecord` — a `dict` (or `TypedDict`) with keys `filename: str`, `status: str`,
  `additions: int`, `deletions: int`, `patch: str | None`. This is a documented **subset** of the
  `gh api .../pulls/{pr}/files` element shape (TD-VF-5). Unknown extra keys are ignored.
- `AuditVerdict` — a frozen `NamedTuple(qualifies: bool, reason: str)`. `reason` is a short
  machine-stable string that names the *first* disqualifying condition (or the qualifying summary),
  written into the bot's decision record (FR19) and the gate log so the outcome is inspectable.

### 3.2 Core function (contract)

```
classify_audit_diff(files: list[FileRecord], allowlist: list[str]) -> AuditVerdict
```

Returns `qualifies == True` **only if every** rule below holds. On the first failing rule it returns
`qualifies == False` with a `reason` naming that rule and the offending path. Rule order is fixed so
`reason` is deterministic.

| # | Rule | Disqualifying `reason` (example) | FR/AD |
|---|---|---|---|
| 1 | `files` is non-empty | `empty-diff` (an empty diff is not an audit PR) | FR6 |
| 2 | Every `filename` matches ≥1 allowlist glob | `non-allowlisted-path:scripts/framework/require_overseer_approval.py` | FR6, FR9, AD-5, AD-4 barrier 1 |
| 3 | Every `status ∈ {"added","modified"}` | `disqualifying-status:removed:audit/oversight-log.jsonl` | FR7, AD-6 |
| 4 | Every `deletions == 0` | `deletion-present:audit/overnight-loop-log.md` | FR7, AD-6 |
| 5 | Every file with `additions > 0` has a non-`None` `patch` | `patch-unavailable:audit/log/2026/08/x.json` (binary/oversized/absent hunk) | FR8, FR18 |
| 6 | Every added line is well-formed per §3.3 | `malformed-jsonl:audit/oversight-log.jsonl:L3` | FR8, AD-6 |

Qualifying return: `AuditVerdict(True, "audit-only additions to {N} allowlisted file(s)")`.

> **Revision 2 (2026-08-01) — the rule set above is EXTENDED by §3.5 (AD-17).** Six hardening rules are
> added: a new **rule 0** (target branch must be `main`), two new tail rules (**rule 7** zero-content /
> mode / symlink rejection; **rule 8** patch-truncation fail-closed), a **signature refinement** (the pure
> function additionally takes the PR base ref as inert data), and a **corrected added-line parser** in §3.3
> (the naive `line.startswith('+++')` filter is a real skip bug). Read §3.5 as part of this contract; the
> equivalence test (§11.2) must cover a fixture for each new rule.

**Notes binding the coder:**
- Rule 2 is what makes AD-4 barrier 1 hold: *any* protected-surface or non-audit path (including any
  `scripts/framework/**` path) fails rule 2, so a diff that touches code can never qualify. There is no
  need — and no allowance — for a separate "is it a protected surface" check inside the predicate; the
  allowlist is a positive whitelist and everything off it fails.
- `status == "added"` (rule 3) is the **first-creation** case (AF-2/AD-9): the file does not yet exist
  on `main`. It must qualify, not be rejected. There is **no** "file must already exist" check anywhere.
- Rule 4 (`deletions == 0`) is the additions-only bound. A pure append shows `deletions == 0` in the
  unified diff (the last existing line is context, not a deletion). A rewrite of any existing line
  shows a `-` → `deletions > 0` → disqualified. This is the primary blast-radius bound (FR7).
- Rules 5–6 are **fail-closed** (FR18): an absent `patch`, an unknown format, or any parse failure →
  not qualifying. The predicate never guesses.
- Glob matching reuses the existing helper style in `require_human_approval.py`
  (`load_globs`/`glob_to_regex`, `dir/** = dir and everything under it`); do **not** coin a second glob
  dialect (AD-2 single-source discipline). §4 makes `audit_allowlist.txt` and that helper the one
  source both this predicate and the CODEOWNERS/human gate consult for the audit surface.

### 3.3 Per-format well-formedness validators (rule 6)

A registry maps a path/extension to a validator over the file's **added lines** (extracted from
`patch`: lines beginning `+` and not the `+++` header, with the leading `+` stripped). Added-line
extraction is pure string parsing over inert text (AF-1) — the parser never evaluates content.

| Format key | Validator | Source of the shape |
|---|---|---|
| `*.jsonl` (e.g. `audit/oversight-log.jsonl`) | each non-blank added line parses as exactly one JSON **object** (`json.loads` → `dict`); trailing blank lines allowed | append-log convention |
| `audit/log/**` (per-event write-once, SPEC-888) | the file's added content parses as one JSON object; these are always `status == "added"` (write-once) | `scripts/oversight/lib/audit_log.py` / `cycle_log.py` |
| `audit/overnight-loop-log.md` | added lines form complete record blocks matching the **reconciled** record header pattern (TD-VF-6) — **fail-closed if the shape cannot be reconciled with the producer at build time** | producer-defined; **reconciliation required (ESC-C)** |
| any allowlisted path with **no registered validator** | **fail-closed** — the file does not qualify (FR18) | AD-6 anti-tamper |

The registry is a plain in-module table; there is **no env var, label, branch, or PR-body input** that
adds a format, relaxes a validator, or bypasses rule 6 (AD-2 anti-tamper — mirror the
`min(trusted_baseline, clamp(env,0,1))` "narrow only" idiom from `run_second_review.sh`, but here there
is simply **no widening knob at all**).

### 3.4 CLI

`python3 scripts/framework/audit_predicate.py classify [--files <path|->] [--allowlist <path>]`
reads a JSON array of file records from a file or stdin, reads the allowlist (default:
`scripts/framework/audit_allowlist.txt`), prints `{"qualifies": bool, "reason": str}` to stdout, exits
`0` always for the reporter (the caller decides), exit `2` on usage/parse error. A `load_allowlist(path)`
helper (outside the pure function, mirroring `require_human_approval.load_globs`) reads and strips the
allowlist file.

**Header comment must state:** this module is the single authority for "audit-only-and-well-formed";
its three importers are Components C (gate), E (bot), and H (#880 exemption); adding a path happens only
in `audit_allowlist.txt` (a protected-surface, human-gated edit — AD-5); an unclassifiable diff is
fail-closed by design; no knob may widen qualification.

### 3.5 Revision 2 — AD-17 predicate/gate hardening (six binding rules)

**Added by Revision 2 (2026-08-01), binding per ADR AD-17.** The dual-lens adversarial pass found six
real fail-open / fail-closed defects in the DRAFT-1 predicate; architect confirmed all six and bound the
*requirement*, routing the exact code to this design. Each rule only **narrows** qualification (consistent
with AD-2 anti-tamper and AD-6 fail-closed). The §3.2 rule table is extended as follows; `reason` strings
stay machine-stable and rule order stays fixed so the *first* failing rule is deterministic.

**Signature refinement (AD-17a needs the PR base ref).** To keep both call sites equivalent (AD-2), the
target-branch check lives **inside** the shared predicate rather than in each caller (where they could
drift). The pure function is refined additively to:

```
classify_audit_diff(files: list[FileRecord], allowlist: list[str],
                    base_ref: str, protected_branch: str = "main") -> AuditVerdict
```

`base_ref` is the PR's `base.ref` — inert data the caller fetches from the same trusted `gh` PR record
(AF-1), passed in, never used to fetch or execute anything. This is **additive to** the AD-2-erratum
signature (`(files, allowlist)`); the function stays pure, network-agnostic, and unit-testable with
synthetic values. Both callers (Component C gate, Component E bot) pass the PR's real base ref; the
Component N producer sets `base = main` when it opens the PR, so a qualifying producer PR always satisfies
rule 0. `protected_branch` defaults to `main` and is not a widening knob — it can only make qualification
*stricter* if a consumer's protected branch differs; it can never point qualification at an unprotected
branch to auto-pass one.

| # | Rule (Revision 2) | Disqualifying `reason` (example) | AD-17 |
|---|---|---|---|
| **0** | `base_ref == protected_branch` (audit PRs target **`main`** only) | `wrong-target-branch:release/v0.7` | (a) |
| **7** | Every changed file has `additions > 0` (reject **zero-content** changes: file-mode-only, symlink creation, type change) | `no-content-addition:audit/log/2026/08/x.json` | (d) |
| **8** | For every file, the count of added lines parsed from `patch` **equals** the files-API `additions` field (detect **patch truncation**) | `patch-truncated:audit/oversight-log.jsonl` | (e) |

Binding notes for the coder:

- **Rule 0 (target branch).** An audit-shaped diff pushed against a feature/release branch **does not
  qualify** — without this, an audit-shaped PR could be auto-approved against a non-`main` target and then
  fast-forwarded, or used to launder a change. Fail-closed: an unreadable/empty base ref → not qualifying.
- **Rule 7 (zero-content).** DRAFT-1 rule 5 only checked "files with `additions > 0` have a `patch`,"
  so a file with `additions == 0` (a pure `chmod`/symlink/type change on an existing allowlisted file)
  slipped past the added-line validation entirely — nothing was actually checked, yet the file qualified.
  Rule 7 makes `additions == 0` on **any** changed file disqualifying. (A symlink whose target text does
  ride in `patch` is independently caught by the JSONL/JSON validators, which reject a path string; rule 7
  is the belt for the metadata-only case where no content appears at all.) The AF-2 first-creation case is
  unaffected — creating a real audit file has `additions > 0`.
- **Rule 8 (patch truncation).** The GitHub files API truncates `patch` for large files (~300 lines /
  ~300 KB per file). DRAFT-1 would then validate only the visible lines and pass — a fail-open, because the
  unseen tail could contain a rewrite or malformed content. Rule 8 reconciles the parsed added-line count
  against the authoritative `additions` integer; **any mismatch → fail-closed**. This is the predicate-side
  half of the truncation defense; Component N's producer-side chunking (§16.1) is the complementary half —
  the producer keeps each file's added diff under the threshold so a legitimate backlog never trips rule 8.
- **Rule 6 parser fix (AD-17f) — corrected in §3.3 below.** The DRAFT-1 §3.3 added-line extraction
  ("lines beginning `+` and not the `+++` header") is the **exact bug the adversarial pass named**: a
  *content* line whose text begins with `+++` (e.g. an audit record that embeds a diff snippet) is read as
  a file header by `startswith('+++')` and **silently skipped from validation**. §3.3 is corrected to parse
  unified-diff hunks properly (`@@ … @@` boundaries), not by string-prefix filtering.

**§3.3 correction (rule 6 parser).** Replace the naive "starts with `+` and not `+++`" extraction with a
**stateful unified-diff parse**: (1) consume the per-file header block (`diff --git`, `index`, `---`,
`+++`) which appears **before** the first `@@`; (2) enter hunk state only at an `@@ -a,b +c,d @@` marker;
(3) **inside a hunk**, classify each line by its single leading marker — `+` = added line (strip exactly
one leading `+`; a content line that then reads `++foo` or `+++bar` is a legitimate added line, not a
header), `-` = deletion, ` ` (space) = context; (4) a `+++`/`---` sequence is only a header when it is the
file-header block *outside* any hunk. Added-line text is still inert data parsed as strings, never
evaluated (AF-1). The per-format validators (§3.3 table) run over the correctly-extracted added lines. A
fixture in §11.1 embeds a `+++`-prefixed content line in a well-formed JSONL append and asserts it is
validated (not skipped) — the direct regression for AD-17f.

**Membership tightening (AD-17b, AD-17c) — see §4/Component B.** `audit/automation/**` is **dropped**
from this iteration's allowlist (allowlisted-but-no-registered-validator → fail-closed by AD-6/AD-14, same
basis as `overnight-loop-log.md`), and the `audit/log/**` glob is **extension-restricted** to
`audit/log/**/*.json` and `audit/log/**/*.jsonl` so a `.py`/`.sh`/dotfile under that tree cannot match
rule 2. Both are folded into Component B's recommended default in §4's Revision 2 note.

---

## 4. Component B — `scripts/framework/audit_allowlist.txt` (the single audit-surface source)

**Structure (bound by AD-5; membership is ESC-2, the human's).** A newline-delimited glob list in the
exact syntax `protected_surfaces.txt` and `require_human_approval.load_globs` already use (`dir/**`,
`*`, exact path; `#` comments and blank lines ignored). This is the **one** definition of the audit
surface. The following must all derive from or reference it rather than keep private copies (AD-5,
reinforced by TD-VF-2):

1. `audit_predicate.classify_audit_diff` (rule 2) — reads it as `allowlist`.
2. `overseer.md:208-209` exempt-files list (Component J) — reconciled to it.
3. `pre_pr_stale_check._AUDIT_ONLY_FILES` (Component H) — reconciled to it (TD-VF-2).

**Recommended default membership (architect's non-binding recommendation, carried forward — the human
owns this via ESC-2):**
```
audit/oversight-log.jsonl
audit/overnight-loop-log.md
audit/log/**
audit/automation/**      # ← ESC-2 open question: couples REQUIREMENTS-034's ledgers to this bot
```
The `audit/automation/**` membership is the one with real consequence (AD-5/ESC-2): it folds
REQUIREMENTS-034's ledgers into this bot's exception. **Blocked until the human rules ESC-2.** The file
lands with a header comment stating that every entry is an inert-record path, that adding a path is a
protected-surface (human-gated) change, and that `overseer.md`, `pre_pr_stale_check.py`, and the
predicate all read from this one file.

> **Revision 2 (2026-08-01) — the recommended default above is SUPERSEDED (AD-14 + AD-17b/c).** Two of the
> four DRAFT-1 entries are now removed for this iteration, both on the **AD-6 fail-closed basis** (a path
> with no registered, derivable validator can never qualify, so advertising it is misleading), not as an
> ESC-2 membership preference:
> - `audit/overnight-loop-log.md` — dropped by **AD-14** (Revision 2 of the ADR): its writer is not
>   locatable on `origin/main`, so its record shape is undeterminable → no validator → fail-closed forever.
> - `audit/automation/**` — dropped by **AD-17(b)**: allowlisted-but-no-registered-validator, the same
>   basis. Re-adding REQUIREMENTS-034's ledgers later requires a registered validator **and** a human ESC-2
>   membership sign-off, and is tracked coupled to REQUIREMENTS-034 (§16.6).
>
> Additionally, per **AD-17(c)** the `audit/log/**` glob is **extension-restricted** so a non-record file
> under that tree cannot match rule 2. The corrected recommended default for this iteration is:
>
> ```
> audit/oversight-log.jsonl
> audit/log/**/*.json
> audit/log/**/*.jsonl
> ```
>
> This collapses the functional allowlist to `oversight-log.jsonl` + the write-once per-event JSON files —
> both with derivable validators (§3.3). Because `overseer.md` (Component J) and
> `pre_pr_stale_check._AUDIT_ONLY_FILES` (Component H) both reconcile **to** this one file, dropping the two
> paths here removes them everywhere with no separate edits (the single-source payoff — AD-14). **ESC-2 is
> now nearly settled** — the only open membership question is whether 034's ledgers are re-added later.

**A test (§11) asserts the three consumers agree** — the direct antidote to `_AUDIT_ONLY_FILES` and the
`overseer.md` list drifting from the allowlist (the #1135 class).

---

## 5. Component C — `require_overseer_approval.py` (the AD-3 identity-bound exception)

**STRUCTURAL — held for human sign-off (AD-3/FR11). This is a protected-surface CI gate; the
implementation PR is human-gated regardless of tier (AD-11).**

The existing gate (verified structure): `main()` loads `machine-accounts.env`, reads
`BOT_OVERSEER_USERNAME`, fetches reviews via `get_reviews` (`gh api --paginate .../pulls/{pr}/reviews`),
and returns `0` iff `overseer_has_approved(reviews, overseer_login)`, else prints the FAIL message and
returns `1`. `_gh` exits `2` on any `gh` failure (fail-closed). The workflow runs `pull_request_target`
+ `pull_request_review` with checkout pinned to `base.sha` (AF-1), permissions
`contents: read, pull-requests: read`.

### 5.1 The additive branch (nothing existing is removed)

`overseer_has_approved(...)` and the whole existing pass/fail flow stay **exactly as-is**. A new,
purely additive branch runs **only when the overseer has NOT approved** (so the common path is
untouched and pays no cost):

New function:
```
audit_exception_satisfied(reviews, file_records, allowlist, auditsync_login) -> bool
```
returns `True` iff **both**:
- **(a)** `audit_predicate.classify_audit_diff(file_records, allowlist, base_ref).qualifies is True`, AND
- **(b)** some review in `reviews` has `state == "APPROVED"` and `login.lower() == auditsync_login.lower()`
  (reusing the exact case-insensitive login-compare already in `overseer_has_approved`).

> **Revision 2 (2026-08-01) — AD-17(a) base-ref plumbing + kill-switch.** Condition (a) now passes the PR's
> `base.ref` into the shared predicate (rule 0, §3.5), so an audit-shaped PR targeting anything other than
> `main` fails the exception. `main()` reads `base_ref` from the same trusted PR record it already fetches
> (the `get_changed_file_records` helper's PR call also carries `base.ref` — DATA only, AF-1); on an
> unreadable base ref, treat as not-evaluable → fall through to the existing FAIL (fail-closed). **Kill-switch
> (AD-19f):** §5.1 step 1 already falls through to FAIL when `BOT_AUDITSYNC_USERNAME` is empty — this is the
> named **emergency-disable procedure**: unsetting the audit-bot's recognized login makes condition (b)
> unsatisfiable, so every audit PR immediately escalates to a human and none can auto-approve. It is
> always-safe under AD-2 anti-tamper (it only removes approval capability). See §16.5 for the operator
> runbook wording.

`main()` change:
1. After `overseer_has_approved` returns `False`, read `auditsync_login = env.get("BOT_AUDITSYNC_USERNAME","").strip()`.
   If empty → **do not** raise; the exception simply cannot be satisfied (condition (b) can never
   match) → fall through to the existing FAIL. (Safe fail-closed direction: an unconfigured auditsync
   identity means audit PRs escalate, never auto-pass.)
2. Fetch the PR's file records as DATA at the head SHA via a **new non-exiting helper** (§5.2).
3. If `audit_exception_satisfied(reviews, file_records, allowlist, auditsync_login)` → print
   `✔ require-overseer-approval: audit-only PR approved by {auditsync_login} — exception satisfied
   (reason: {verdict.reason})` and return `0`.
4. Else → the existing FAIL path (return `1`), unchanged.

### 5.2 AF-1 data-only fetch (the #972 defense)

Add `get_changed_file_records(repo, pr) -> list[FileRecord] | None` modelled on
`require_tier_ceiling._fetch_head_python`'s "read PR files as DATA" model:
- Call `gh api --paginate repos/{repo}/pulls/{pr}/files` (via a **new** `_gh_data(*args) -> str | None`
  that returns `None` on failure instead of `sys.exit(2)`), parse the JSON array, project each element
  to a `FileRecord` (keep `filename`, `status`, `additions`, `deletions`, `patch`).
- On **any** failure (gh error, JSON parse error, `None`) → return `None`. The caller treats `None` as
  "exception not evaluable" → condition (a) is effectively false → fall through to the existing FAIL
  (return `1`). **Never** exit `2` on the files fetch (that would fail-closed the *whole* gate for a
  legitimately overseer-approved PR too, and add a DoS surface); the reviews fetch keeps its existing
  exit-`2` fail-closed behavior because a reviews-fetch failure genuinely means the gate cannot be
  evaluated at all.
- **The PR content is only ever fetched and parsed, never checked out or executed** — the module runs
  from the trusted base (AF-1), and the file records + patches are inert data. No `subprocess` in this
  path runs anything but `gh api`. This is the explicit #972-class boundary the ADR (AF-1) mandates.

### 5.3 Invariants the coder must preserve

- The exception **never** widens `require_human_approval` or `require_tier_ceiling` (AD-4 barrier 2):
  this edit is confined to `require_overseer_approval.py`; it reads `BOT_AUDITSYNC_USERNAME` but does
  not touch `protected_surfaces.txt`, the ceiling logic, or the human-gate. (Verified sibling ordering:
  for an overseer-authored audit PR, `require_tier_ceiling` passes trivially — VF-1: overseer never
  approved its own PR — and `require_human_approval` passes because `audit/**` is not a protected
  surface. So AD-3's branch is the *only* CI-gate change needed.)
- Stale-review interaction (AD-3 note): if `dismiss_stale_reviews` is on, a new commit dismisses the
  auditsync APPROVED review; condition (b) goes false and the PR correctly re-blocks. Do **not**
  engineer around this — it is the safe direction.
- Fail-closed everywhere (FR18): unreadable/ambiguous/unexpected content, absent patch, unknown format
  → `qualifies == False` → normal overseer requirement applies → escalate.

---

## 6. Component D — `machine-accounts.env` (config; AD-1, AD-4, AF-3)

Two additive changes (a **data/config** change, not code — AF-3):
1. Add a key alongside `BOT_OVERSEER_USERNAME`:
   ```
   BOT_AUDITSYNC_USERNAME="hos-auditsync-hos[bot]"   # audit-approval identity (ADR-035); review-submission scope only, NO push/bypass
   ```
   Read by Component C exactly as `BOT_OVERSEER_USERNAME` is read today.
2. Append the auditsync login to `BOT_ACCOUNTS` (AD-4/AF-3 defense-in-depth for `require_human_approval`):
   ```
   BOT_ACCOUNTS="${BOT_WORKER_USERNAME} ${BOT_OVERSEER_USERNAME} ${BOT_HUMAN_USERNAME} ${COPILOT_BOT_LOGIN} ${BOT_AUDITSYNC_USERNAME}"
   ```
   The existing `load_env` `${VAR}` expansion (verified in `require_overseer_approval.load_env`) resolves
   this. `is_bot_reviewer` already denies the auditsync review via `user.type=="Bot"` and the `[bot]`
   suffix (AF-3); this enumeration is the belt that also covers a future PAT-machine-user identity.

Both edits carry in the same human-gated PR (they are part of the structural change).

---

## 7. Component E — `scripts/framework/audit_approval_bot.py` (the deterministic approver runtime)

**AD-2 call site #1. FR4 (deterministic, no model), AD-7 (disposition), FR19 (self-auditable).**

Split logic (pure, testable) from I/O (subprocess, subprocess-tested with fixtures), matching the repo
convention and TD-033 §4.0:

**Pure decision (unit-testable):**
```
decide(files: list[FileRecord], allowlist: list[str]) -> BotDecision
```
where `BotDecision = NamedTuple(approve: bool, reason: str)` and `approve == classify_audit_diff(files, allowlist).qualifies`.
**This is the same predicate the gate calls — the equivalence guarantee of AD-2 is structural, and §11's
equivalence test proves both call sites route through it identically.**

**Runtime (`main()` / CLI `--pr <n> [--repo owner/repo]`):**
1. Authenticate as the auditsync identity (token already exported into `GH_TOKEN` by the launcher via
   Component G's `get_app_token.sh --app auditsync`, or by the workflow's app-token step). The runtime
   does **not** mint its own JWT (CLAUDE.md: token minting goes through `get_app_token.sh`, never a
   hand-built JWT).
2. Fetch file records as DATA: `gh api --paginate repos/{repo}/pulls/{pr}/files` (same projection as
   §5.2). **Never checks out or executes PR content** (AF-1). On fetch failure → treat as non-qualifying
   → withhold+escalate (fail-closed).
3. Read existing reviews; if the auditsync identity already has a current `APPROVED` review for this
   head, **no-op** (idempotent — avoids duplicate reviews on re-runs / re-triggers).
4. `d = decide(files, allowlist)`:
   - `d.approve` → `POST repos/{repo}/pulls/{pr}/reviews` with `event: "APPROVE"` and a body embedding
     the decision record (verdict reason, bundle of changed paths, head SHA). This is the **only** write
     the identity ever performs — the reviews API (AD-1: PR write is the sole write scope; NO
     content-write, NO bypass; there is no code path here that pushes, commits, or merges).
   - `not d.approve` → **withhold + escalate** (AD-7/FR13): do **not** approve, do **not** force/close/
     rewrite. Route to the repo's standard human-escalation channel (a `needs-human` issue / the same
     channel `oversight-orchestrator` uses), leaving the PR open. Whether it *additionally* submits a
     `REQUEST_CHANGES` review is **ESC-4** (default: silent withhold + escalation issue; the human may
     switch it to `REQUEST_CHANGES`). One flag, one branch — designed so ESC-4 is a one-line default.
5. **Record the decision durably (FR19):** append the decision record (qualify-and-approve OR
   withhold-and-escalate, with reason and head SHA) to the audit metadata that rides the **same** audit
   path (AD-7 — no separate mechanism, no unbounded regress). Concretely: emit it as a `cycle_log`-style
   audit event (per-entry file under `audit/log/**`, or an appended line on the allowlisted log),
   which the next audit PR carries to `main`.
6. Fail-closed on **every** error path (FR18): unresolved identity, fetch failure, classify error,
   reviews-submit error → withhold + escalate, never approve.

**Stuck-PR escalation (FR16):** the bot (or its launcher, per ESC-1's cadence) must detect an audit PR
that cannot merge — a required check erroring, checks staying non-green past a bound, or a merge
conflict — and escalate to a human after that bound, with the growing backlog observable, not silent.
The exact bound rides ESC-1 (cadence/lag); the mechanism (escalate, don't auto-anything) is bound here.

> **Revision 2 (2026-08-01) — AD-18 makes the FR16 sweep MANDATORY, and AD-19(d) fixes the FR19 home.**
> (1) A pure event-only trigger (webhook on `opened`/`synchronize`) can **never** satisfy FR16 — an audit
> PR that opens green and later goes stuck fires no event, so nothing re-evaluates it. AD-18 therefore
> makes a **periodic sweep of open audit PRs mandatory**. The natural home is **Component N's cron slice**
> (§16.1/§16.4): the producer already runs each cycle, so it both opens new audit PRs *and* sweeps existing
> open ones for stuck/non-green/conflicted state, escalating per FR16. Component E's per-PR `decide` stays
> a pure event-driven approver; the sweep is a Component N responsibility (co-located), not a second copy
> of the approval logic. (2) **FR19 durable record — no runner-local disk (AD-19d).** Under Shape 1 (an
> ephemeral GitHub-Actions runner) step 5's decision record MUST NOT be written to runner-local disk (it
> vanishes). It is written as an **audit-log append** (`audit/log/**` write-once JSON or an `oversight-log.jsonl`
> line) and carried to `main` by the **same Component N producer PR path** — inert data batched by the next
> producer cycle like any other record. This is consistent with AD-7's "rides along as metadata" and
> creates no unbounded regress. Component N also writes a **"last successful audit sync" heartbeat** marker
> the same way (AD-19c) — the future input to the deferred external liveness monitor (§16.6).

**Header comment must state:** the identity's only write is the reviews API; there is no push, commit,
or merge path; the decision is a deterministic function of the diff (no model); non-qualifying →
withhold-and-escalate, never approve/force/close/rewrite.

---

## 8. Component G — `get_app_token.sh` + `apps.env.template` (auditsync auth; TD-VF-4, AD-1)

**Protected surface (`bootstrap/**`) → human-gated.**

Add an `auditsync` role to `bootstrap/get_app_token.sh`: extend the usage string to
`--app [worker|overseer|human|auditsync]` and add a `case` arm mapping to `HOS_AUDITSYNC_APP_ID` /
`HOS_AUDITSYNC_PEM` / `HOS_AUDITSYNC_BOT_LOGIN`, with the existing #703 identity-mismatch guard extended
so the authenticated login must equal `HOS_AUDITSYNC_BOT_LOGIN` (`hos-auditsync-hos[bot]`). Add the three
`HOS_AUDITSYNC_*` variables to `bootstrap/apps.env.template` with comments stating the **narrowed
scope**: Pull requests **Read & write**, Contents **Read**, Metadata Read, everything else No access,
**NO ruleset bypass** (AD-1). If the bot instead runs purely as a GitHub Actions workflow (ESC-3), the
Actions-secret path (`HOS_AUDIT_SYNC_APP_ID`/`HOS_AUDIT_SYNC_PRIVATE_KEY` via
`actions/create-github-app-token`) is used instead and this `get_app_token` role is still added for
the cron/local path. Either way, **no path grants content-write or bypass** (AD-1 invariant).

---

## 9. Component F — the bot trigger surface (BLOCKED on ESC-1 + ESC-3)

**Two shapes are designed; the choice is the human's (ESC-1 cadence, ESC-3 merge actor).** The bot
*logic* (Component E) is identical under both; only the launcher differs.

- **Shape 1 — GitHub Actions workflow** `.github/workflows/audit-approval.yml` (recommended, matches
  "Copilot runs natively in CI"): triggers on `pull_request_target` (opened/synchronize/labeled)
  filtered to audit PRs; authenticates as auditsync via `actions/create-github-app-token` with the
  stored App ID/key; **checks out the trusted base** (`ref: base.sha`, AF-1 — the bot script must be the
  base version, not the PR's) and runs `audit_approval_bot.py`, which reads PR content as DATA. Native
  auto-merge (ESC-3) may be armed on the audit PR so it merges when the review lands and checks are
  green — with the auditsync identity holding **no** merge-bypass authority.
- **Shape 2 — cron launcher** on a separate schedule (e.g. a `bin/` entry or an existing cron cycle),
  minting the token via Component G and invoking the bot per cadence (ESC-1). Here the "merge actor"
  (ESC-3) is whoever/whatever performs the ordinary PR merge after approval — never a bypass.

`.github/workflows/**` and `bin/**` are protected surfaces → human-gated. **This component cannot be
finalized until ESC-1 and ESC-3 are ruled** — the trigger cadence and the merge actor determine the
shape.

---

## 10. Components H, I, J, K, L — reconciliations and the FR17 supersession

### 10.1 Component H — `pre_pr_stale_check.py` #880 reconciliation (TD-VF-2)

Reconcile `check_audit_log_not_committed` so a **fully audit-only** PR is exempt from the #880
prohibition: change `_AUDIT_ONLY_FILES` from a private hardcoded frozenset to a load from the shared
allowlist (Component B), and add the exemption — if **every** changed file on the branch is
allowlisted-audit (i.e. the whole diff would satisfy the predicate's rule 2), the check returns no
violation (this is the overseer's legitimate audit PR). A *mixed* PR (audit files **plus** any non-audit
file) still violates #880, preserving the original intent (audit files must not ride a feature branch).
Correct the stale "gitignored" comment (TD-VF-3). Route the topology confirmation to `architect`
(ESC-A). `scripts/automation/**` is not protected, but this is load-bearing: **without H the audit PR
cannot be opened at all.**

### 10.2 Component I — `bin/hos-cron` `_sync_audit_logs` disposition (BLOCKED on ESC-5; TD-VF-1)

- **Option A (recommended):** remove `_sync_audit_logs` and its `audit-log`-branch push; the checked-PR
  path (overseer authors an audit PR) replaces it. Correct the stale "gitignored" comment.
- **Option B:** keep `_sync_audit_logs`, build the missing `audit-log`→`main` consumer workflow **first**
  as the interim stopgap, then retire it when this mechanism lands.

`bin/**` is protected → human-gated. **Blocked on ESC-5.** Per TD-VF-1 the human now has the fact that
#1095's interim path is producer-only (no consumer), which is the missing input ESC-5 was waiting on.

> **Revision 2 (2026-08-01) — ESC-5 is BOUND (AD-13) and the disposition is now REPLACE, not remove
> (AD-15).** Two changes from the DRAFT-1 text above: (1) **ESC-5 is no longer the human's** — AD-13
> supersedes #1095's remaining scope (option A binds; no interim consumer is built), so Option B above is
> withdrawn. (2) **Component I's disposition changes remove → replace.** The panel found that DRAFT-1
> designed every *consumer* of the audit PR but AD-13 *removed the only producer* — leaving nothing to
> create the branch, commit the records, or open the PR. AD-15 corrects this: `_sync_audit_logs`'s
> bypass-push to the dead `audit-log` branch is still **deleted**, but its *role* (carry local audit records
> to `main`) is **re-homed** into the new worker-identity producer, **Component N** (§16.1), via a checked
> PR. The local record writers (`cycle_log.py` → `audit/log/**`, the `oversight-log.jsonl` appender) are
> **untouched** — they keep producing; Component N transports what they produce. The stale "gitignored"
> comment correction (TD-VF-3) still applies. The `audit-log`-branch accumulated history migrates to `main`
> via the first qualifying Component N PR (AD-9 first-creation), not discarded.

### 10.3 Component J — `overseer.md` exempt-list reconciliation (AD-5; BLOCKED on ESC-2 membership)

`overseer.md:200-215`'s exempt-files list (`audit/oversight-log.jsonl`, `audit/overnight-loop-log.md`,
`audit/automation/**`) is reconciled to reference the single allowlist (Component B) rather than restate
it. Protected surface (`.claude/agents/**`) → human-gated. Final wording depends on ESC-2 membership.

### 10.4 Component K — `DECISIONS.md` new dated entry (AD-8; STRUCTURAL, held)

**Append-only (CLAUDE.md) — do NOT edit the 2026-06-23 entry in place.** Append a new entry at the file
tail (currently `## 2026-07-30 — Advisory PACK-conflict detection…`):
```
## 2026-08-01 — Audit-approval bot supersedes the auditsync direct-push/bypass design (ADR-035)
```
It must (i) explicitly supersede the 2026-06-23 entry, naming it; (ii) record that the 2026-06-23 sync
was *producer-only* — the `audit-log`-branch push exists in `bin/hos-cron` but the branch→main consumer
was never built (TD-VF-1), so there is a documented path to delete but **no live ruleset bypass** to
remove; (iii) state the auditsync identity's authority is reconciled **downward** to review-submission
scope (AD-1); (iv) record that audit records now reach `main` through a checked PR with no bypass actor,
honoring #873. Not a protected surface, but part of the structural sign-off held for the human.

### 10.5 Component L — `docs/MACHINE-ACCOUNTS-SETUP.md` in-place rewrite (AD-8/FR17; STRUCTURAL, held)

**In-place correction** of Steps 5–6 (verified live content: Step 5a sets Contents `Read & write` and
says the workflow "pushes directly to main, bypassing the PR requirement"; Step 6 says "Bypass list →
Add bypass → search `hos-auditsync-hos` → set mode **Always**" and "`hos-auditsync-hos` can push audit
logs directly to main"). Rewrite so the identity is created with the **AD-1 review-submission scope**
(Pull requests Read & write, Contents Read, no bypass step, no direct-push language). **Acceptance
(FR17):** after the change, `git grep` across committed docs finds **no** instruction to add a ruleset
bypass actor or to push audit logs directly to `main` (a §11 test enforces this over both K and L).
Confirmed there is **no other** bypass-introduction path to fix: `setup_branch_protection.sh` already
sets `bypass_pull_request_allowances: []` ("bots are NOT bypass actors"), and no other committed file
references `auditsync`/`HOS_AUDIT_SYNC` (verified `git grep`).

> **Revision 2 (2026-08-01) — Components K and L must also carry a consumer bypass-REMEDIATION step
> (AD-19a).** A forward-only rewrite is insufficient: VF-2 confirmed the `hos-auditsync-hos` **Always**-bypass
> instructions were **live onboarding docs**, so already-deployed consumers may have configured the bypass
> actor. Both **Component K** (`DECISIONS.md` entry) and **Component L** (`MACHINE-ACCOUNTS-SETUP.md`
> rewrite) MUST include an explicit **upgrade/remediation step** for existing deployments: *"if you
> previously added `hos-auditsync-hos` to the `main` ruleset bypass list, remove it; and downgrade the
> `hos-auditsync-hos` App's live permissions from Contents: Read & write to Contents: Read (PR: Read &
> write, Metadata: Read only)."* Leaving deployed bypass actors in place does not honor #873 (AD-19a). The
> §11.8 FR17 grep acceptance test is unchanged (no committed doc instructs adding a bypass or direct push);
> a new assertion checks the remediation instruction is **present**. A third doc joins the reconciliation
> set — **Component O** (`docs/OVERSIGHT-RUNBOOK.md`, §16.5) — which still documents the superseded
> direct-audit-commit / `audit-log`-branch path.

---

## 11. Test plan

Conventions matched to the existing gate tests (`tests/framework/test_require_tier_ceiling.py`,
`test_require_human_approval.py`): pure logic → import the module by file path and call functions
directly; anything touching `gh`/subprocess → drive the real script/module with **monkeypatched fetch
helpers or fixtures**, exercising only paths that short-circuit before any live call. **Nothing may
require a live model, network, or authenticated `gh`.**

### 11.1 `tests/framework/test_audit_predicate.py` (Component A — pure)
1. Empty `files` → `qualifies False`, reason `empty-diff`.
2. A file off the allowlist (e.g. `scripts/framework/require_overseer_approval.py`) → `False`,
   `non-allowlisted-path:…` — **proves AD-4 barrier 1 (a protected-surface path never qualifies).**
3. `status == "added"` on an allowlisted file with well-formed additions → `qualifies True` —
   **the AF-2 first-creation case; asserts the predicate does NOT require a pre-existing file.**
4. `status == "modified"`, `deletions == 0`, well-formed appends → `True`.
5. `deletions > 0` on any file → `False`, `deletion-present:…` — **the additions-only / no-rewrite bound (FR7).**
6. `status ∈ {removed, renamed, copied}` → `False`, `disqualifying-status:…`.
7. `patch is None` with `additions > 0` → `False`, `patch-unavailable:…` (fail-closed on binary/oversized).
8. `.jsonl` added line that is not a JSON object (array, scalar, or garbage) → `False`, `malformed-jsonl:…`.
9. `audit/log/**` write-once file whose content is a valid JSON object → `True`; malformed → `False`.
10. An allowlisted path with **no registered validator** → `False` (fail-closed, AD-6 anti-tamper).
11. A malformed OR non-audit-only diff is **withheld (False), never approved** — the explicit
    negative the task requires; parameterised over cases 2/5/6/7/8/10.
12. CLI: `classify` emits valid JSON, exit 0; usage/parse error exit 2.

### 11.2 `tests/framework/test_audit_predicate_equivalence.py` (Component A — the AD-2 defense)
A shared fixture list of `(files, expected_qualifies)` covering qualify and every disqualify class.
For each fixture, assert **all three** agree:
- `audit_predicate.classify_audit_diff(files, allowlist).qualifies`
- `audit_approval_bot.decide(files, allowlist).approve`
- `require_overseer_approval.audit_exception_satisfied(reviews_with_auditsync_approval, files, allowlist, auditsync_login)`
  (with a fixed APPROVED-by-auditsync review, so condition (b) is held true and only (a) — the predicate
  — varies)

all equal `expected_qualifies`. **This is AD-2's binding deliverable: it proves the bot's decision and
the gate's exception can never drift, because both are the one predicate.** A grep-style assertion also
confirms neither Component E nor Component C contains an independent audit-only test (no second copy).

### 11.3 `tests/framework/test_require_overseer_approval_audit.py` (Component C — gate exception, hermetic)
Monkeypatch `get_reviews` and `get_changed_file_records` (no live `gh`):
1. Overseer approved → exit 0 (existing behavior, regression).
2. No overseer approval, qualifying diff, **auditsync APPROVED** → exit 0, message names the exception
   and the reason.
3. No overseer approval, qualifying diff, **no auditsync approval** → exit 1 (condition (b) fails —
   an audit-only diff alone never discharges the gate; FR10/VF-7).
4. No overseer approval, **non-audit diff**, auditsync APPROVED → exit 1 (condition (a) fails — the bot
   cannot waive a non-audit PR; FR10). **The malformed/non-audit-is-withheld defense at the gate.**
5. `BOT_AUDITSYNC_USERNAME` unset → exit 1 for an otherwise-qualifying audit PR (fail-closed: no
   configured identity → escalate, never auto-pass).
6. `get_changed_file_records` returns `None` (fetch failure) → exit 1, **not** exit 2 (no DoS on the
   files fetch; the reviews-fetch exit-2 behavior is unchanged — separate test).
7. Login compare is case-insensitive (`HOS-AUDITSYNC-HOS[bot]` matches).
8. **Barrier-independence assertion:** the edit does not reference `protected_surfaces.txt`, the ceiling,
   or the human-gate (grep guard — AD-4 barrier 2).

### 11.4 `tests/framework/test_audit_approval_bot.py` (Component E — hermetic, subprocess/monkeypatch)
1. Qualifying diff → the runtime issues exactly one `POST …/reviews` with `event: APPROVE` (assert on a
   captured/mocked `gh` call, never a live one).
2. Non-qualifying diff → **no approve call**, an escalation record is produced, the PR is left open
   (FR13). **Malformed/non-audit is withheld, not approved.**
3. Fetch failure → withhold + escalate (fail-closed, FR18); no approve.
4. Idempotency: an existing current auditsync APPROVED review → no second review submitted.
5. FR19: a durable decision record is written (approve and withhold cases both), carrying reason + head SHA.
6. The runtime contains **no** push/commit/merge call — a grep guard asserts the only write verb is the
   reviews API (AD-1 invariant).

### 11.5 `tests/framework/test_audit_allowlist_single_source.py` (Component B/H/J — the #1135 antidote)
1. `audit_allowlist.txt` parses under the shared glob helper.
2. `pre_pr_stale_check` loads its audit set from the allowlist (no private `_AUDIT_ONLY_FILES` literal
   remains — grep guard).
3. `overseer.md`'s exempt list references/derives from the allowlist and does not restate a divergent
   set (assert the enumerated audit paths in `overseer.md` are a subset of the allowlist).

### 11.6 `tests/automation/test_pre_pr_stale_check_audit_pr.py` (Component H — TD-VF-2)
1. A branch whose diff is **only** allowlisted audit files → **no** #880 violation (the audit PR is
   allowed). Regression-critical: without this the mechanism can't open a PR.
2. A branch mixing an audit file **and** a non-audit file → **still** a violation (original intent
   preserved).
3. On `main` → skipped (unchanged).

### 11.7 `tests/framework/test_machine_accounts_auditsync.py` (Component D)
1. `BOT_AUDITSYNC_USERNAME` present and equals `hos-auditsync-hos[bot]`.
2. `BOT_ACCOUNTS` expands (via `load_env`) to include the auditsync login (AF-3/AD-4).
3. `is_bot_reviewer("hos-auditsync-hos[bot]", "Bot", bot_accounts)` is True via **all three** layers
   (type, suffix, enumeration).

### 11.8 `tests/framework/test_decisions_and_setup_no_bypass.py` (Components K, L — FR17 acceptance)
1. `DECISIONS.md` contains a heading matching `^## 2026-08-01 — Audit-approval bot supersedes` at EOF,
   and the 2026-06-23 entry text is **unchanged** (append-only; compare against `git show`).
2. **FR17 grep acceptance:** across committed docs (`DECISIONS.md`, `docs/MACHINE-ACCOUNTS-SETUP.md`)
   there is no instruction to add a ruleset **bypass** actor and no "push … directly to main" language
   for the auditsync identity (regex sweep). This is the FR17 verify line, mechanised.
3. `docs/MACHINE-ACCOUNTS-SETUP.md` Step 5a no longer sets Contents `Read & write` for auditsync (asserts
   the review-submission scope).

### 11.9 Manual / operator verification (cannot be hermetic)
- One real audit-approval-bot run against a real qualifying audit PR (both CLIs authed): confirm exactly
  one APPROVED review from `hos-auditsync-hos[bot]`, the PR passes `require-overseer-approval` via the
  exception, and it merges via an ordinary PR merge with **zero** bypass actors configured (FR1/FR14).
- One run against a deliberately non-qualifying PR (a rewrite / a non-audit path): confirm **no**
  approval, an escalation surfaced, the PR left open (FR13).
- Confirm the `auditsync` App's live permissions are exactly PR Read&write + Contents Read + Metadata,
  **no** bypass (AD-1) — **unverified at design time** (`gh` unauthenticated); report, do not work
  around, any divergence.
- `./scripts/framework/run_tests.sh` passes including the coverage gate.

---

## 12. Build order and PR split

Dependencies are real; this order is not a preference. **Note the heavy ESC-gating: most slices cannot
start until the human clears the holds (§14).**

> **Revision 2 (2026-08-01) — this build order and PR split are SUPERSEDED by §16.8.** Three slices are
> added (S13 `AGENT-IDENTITY.md` fourth-class / Component M, **S14 the worker-identity producer / Component
> N**, S15 `OVERSIGHT-RUNBOOK.md` / Component O), S10's `hos-cron` slice changes remove→replace, and the
> file/commit count grows materially (now over the soft split limit toward the hard ceiling), so the PR
> split grows from four seams to **five**. Critically, **Component N (the producer) is a prerequisite of
> any end-to-end slice** — per AD-15 a slice that ships the approver without the producer is inert and must
> not be accepted. See **§16.8** for the authoritative re-sequenced order and split.

| # | Slice | Component(s) | Depends on | Blocked on |
|---|---|---|---|---|
| S1 | Shared predicate + unit tests (**not** the equivalence test) | A | — | structural sign-off (ADR §3) |
| S2 | Allowlist file | B | — | **ESC-2** (membership) |
| S3 | Bot runtime + tests | E | S1, S2 | structural sign-off; ESC-4 (disposition detail) |
| S4 | Gate exception + tests | C, D | S1, S2 | **structural sign-off** (protected-surface CI gate) |
| S5 | **Equivalence test** (AD-2 deliverable) | A/C/E | S3, S4 | same as S3+S4 |
| S6 | auditsync auth role | G | — | structural sign-off (`bootstrap/**`) |
| S7 | #880 reconciliation + tests | H | S2 | **ESC-A** (architect topology) |
| S8 | Bot trigger surface | F | S3, S6 | **ESC-1 + ESC-3** |
| S9 | overseer.md reconciliation | J | S2 | **ESC-2** (membership) |
| S10 | hos-cron disposition | I | — | **ESC-5** (#1095 ordering) |
| S11 | DECISIONS.md entry | K | S1–S10 (describe what shipped) | **structural sign-off** |
| S12 | MACHINE-ACCOUNTS-SETUP rewrite | L | — | **structural sign-off** |

**PR-size split (`docs/PR-SIZE-POLICY.md`; >15 files or >10 commits → split; 25 hard ceiling).** The full
build is ~20 files (over the soft limit, under the hard ceiling — TD-VF-7) and touches **five** protected
surfaces, so the whole thing is human-gated (AD-11) and must split. Recommended seams, each independently
green:
- **P1 — predicate + allowlist + equivalence** (S1, S2, S5 minus the call sites' own edits): the pure,
  ESC-2-membership-pending core. *Blocked on structural sign-off; membership placeholder pending ESC-2.*
- **P2 — the gate exception + config + bot** (S3, S4, S6): the load-bearing behavior. *Blocked on
  structural sign-off + ESC-2 + ESC-4.*
- **P3 — reconciliations** (S7, S9, S10): #880, overseer.md, hos-cron. *Blocked on ESC-A + ESC-2 + ESC-5.*
- **P4 — trigger + docs** (S8, S11, S12): workflow/cron, DECISIONS, setup doc. *Blocked on ESC-1 + ESC-3 +
  structural sign-off.*

---

## 13. Escalations (technical-design → other roles) and build-time reconciliations

| id | To | Question / item | Blocks |
|---|---|---|---|
| ESC-A | **architect** | TD-VF-2: the audit PR is incompatible with `pre_pr_stale_check.py` #880 as written. Confirm the reconciliation (exempt a fully-audit-only diff, reuse the shared allowlist) vs. a different topology (e.g. avoid a branch). This is an architecture-topology decision the ADR did not surface. | Component H (S7) |
| ESC-B | **architect** | TD-VF-5: I refined AD-2's illustrative `classify_audit_diff(changed_paths, added_lines_by_path, existing_content_probe)` to `classify_audit_diff(files, allowlist)` over files-API records. Confirm (a clarifying refinement, not a contract change). | Component A signature only |
| ESC-C | **architect / producer reconciliation** | TD-VF-6: `overnight-loop-log.md`'s record shape is not derivable from `origin/main`. The `.md` validator must be reconciled with the producer at build time, or the file dropped from the allowlist (couples to ESC-2). Until reconciled, the `.md` validator is fail-closed. | §3.3 markdown validator |
| ESC-D | **pm-agent** | Confirm whether the bot's stuck-PR/backlog escalation (FR16) and its self-audit record (FR19) reuse the existing `oversight-orchestrator`/`cycle_log` channels (my assumption) or need a new surface — a product/observability question. | Component E escalation wiring |

**These are separate from the ADR's ESC-1…ESC-7, which are the human's and are NOT mine to bind.** They
are restated in §14 as build blockers.

---

## 14. What is blocked, and whether `coder` can start today

> **Revision 2 (2026-08-01) — the coder-clearance position is unchanged in verdict but LARGER in scope;
> the authoritative restatement is §16.9.** Still: `coder` may build **nothing** today. Since DRAFT-1 the
> structural sign-off has **grown** — it now also covers the worker-identity producer (Component N / AD-15)
> and the fourth-identity-class governance amendment (`AGENT-IDENTITY.md` / Component M / AD-16), plus the
> Component K/L bypass-remediation and Component O runbook reconciliation. ESC-5 is now **bound** (AD-13);
> ESC-A/ESC-B/ESC-C are **resolved** by architect (AD-12 / AD-2 erratum / AD-14). The remaining human gates
> are exactly: **(1) structural sign-off** (now AD-3 + AD-8 + AD-15 + AD-16/Component M + remediation),
> **(2) ESC-2** (allowlist membership — now nearly settled, §4 Revision 2 note), **(3) ESC-3** (merge
> actor). See **§16.9**.

**Plainly: `coder` cannot start any slice today.** The ADR's cleared-to-build statement withholds
coder-clearance until (1) the human **signs off the structural change** (AD-3 gate exception + AD-8
`DECISIONS.md` supersession + `MACHINE-ACCOUNTS-SETUP.md` rewrite) and (2) the human **rules ESC-2
(allowlist membership), ESC-3 (merge actor), and ESC-5 (#1095 ordering)**. Every material slice sits
behind at least one of those holds:

| Human ruling needed | Unblocks |
|---|---|
| **Structural sign-off** (AD-3 + AD-8) | S1, S3, S4, S5, S6, S11, S12 — i.e. the predicate, gate, bot, auth, and both doc changes. This is the master gate; without it, nothing that ships behavior may be built. |
| **ESC-2** (allowlist membership, esp. `audit/automation/**`) | S2 (the allowlist file), S9 (overseer.md), and finalizes S1's fixtures and §3.3's `.md` decision |
| **ESC-3** (merge actor / auto-merge) | S8 (the trigger surface / Component F) |
| **ESC-5** (#1095 ordering — now informed by TD-VF-1) | S10 (`bin/hos-cron` disposition) |
| **ESC-1** (cadence/lag) | S8's cadence, S3's stuck-PR bound (FR16) |
| ESC-4 (predicate-fail disposition) | one default in S3 (does **not** block the build — bound default is silent withhold + escalate) |

**The single slice whose *contract* is fully settled independent of the ESCs is the pure predicate
(Component A / S1)** — its logic is bound by AD-2/AD-6/AF-1/AF-2 and it consumes the allowlist as *data*,
so ESC-2's membership does not change its code. But it still cannot be **built by coder** today, for two
reasons: (i) the ADR withholds coder-clearance for the mechanism as a whole pending structural sign-off;
and (ii) its binding deliverable — the AD-2 equivalence test (S5) — spans the gate (S4) and bot (S3) call
sites, which are themselves blocked. So even A delivers no verifiable value alone. **If the human wants
to unblock incrementally, the correct first grant is structural sign-off, after which S1 (predicate +
its non-equivalence unit tests) can proceed even before ESC-2 membership is final.**

Independently of all the above, the implementation PR is a five-protected-surface change that a **human
must approve at merge time regardless of computed risk tier** (AD-11/FR11/TD-VF-7); this technical
design is not that approval, and the audit-approval bot's own review can never provide it (AD-4).

---

## 15. Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design, before any code was written against it?*
This is a **new mechanism**, not a correction to already-built work, so — as the ADR's §3 notes — no
prior *design* or *code* sign-off is orphaned by these decisions. But two of my findings are
`startup-artifact-gap`-class defects in **existing** shipped code that this work exposes, and each gets
its own issue rather than being folded in:

- **ISSUE-1** — `[AI: technical-design] startup-artifact-gap: bin/hos-cron pushes audit logs to an
  \`audit-log\` branch that no workflow ever consumes (#1095 half-built; TD-VF-1)`. The producer exists,
  the consumer never shipped, so audit history has been accumulating on a dead branch. File regardless of
  which ESC-5 option the human picks.
- **ISSUE-2** — `[AI: technical-design] bug: pre_pr_stale_check.py and bin/hos-cron comment audit files
  as "gitignored" but .gitignore has no audit/ entry (TD-VF-3)`. Stale claims in live code.
- **ISSUE-3** — `[AI: technical-design] gap: the audit-file set is duplicated in four places
  (overseer.md, pre_pr_stale_check._AUDIT_ONLY_FILES, and — new — the allowlist and the predicate) —
  the #1135 class this ADR must not reproduce (TD-VF-2)`. Filed even though AD-5/Component B fixes it, so
  the pattern is on record.

**Affected sign-offs: none are invalidated.** Every prior approval was made against a pipeline in which
the aggregate audit logs did **not** reach `main` (they died on the `audit-log` branch). This work item
*adds* the path they were always meant to have. Two boundaries to watch, both bound here: (1) the #880
reconciliation (Component H) must not retroactively bounce any *existing* feature PR — it only *adds* an
exemption for audit-only diffs, never removes the feature-branch prohibition; (2) if the human picks
ESC-5 option A (remove `_sync_audit_logs`), the dead `audit-log` branch's accumulated history should be
migrated to `main` through the first qualifying audit PR (AD-9 first-creation), not discarded — a
migration note for the coder, not a new sign-off.

---

## 16. Revision 2 — dual-lens panel rulings incorporated (AD-15…AD-19 + FR2 correction)

**Added 2026-08-01. Binding input: ADR-035 Revision 3 (§5) and REQUIREMENTS-035's dated FR2 correction.**
This section is authoritative where it conflicts with DRAFT-1 §0–§15; the inline Revision 2 blockquotes
above point here. It closes the single core gap the panel found (no producer), declares the fourth identity
class, and folds in the AD-17/AD-18/AD-19 rulings.

### 16.1 Component N — worker-identity audit-PR **producer** (NEW; AD-15, AD-18) — the missing half

**Purpose.** Produce the audit PR that Components E/C/F/H consume. This is the component whose absence made
the DRAFT-1 design inert: nothing created the branch, committed the records, opened the PR, or handed off
to the merge path. Component N is the successor to `bin/hos-cron:_sync_audit_logs` — it **replaces** it
(AD-15 amends AD-13's "remove"), re-homing its *role* (carry local audit records to `main`) onto the
checked-PR path.

**Placement and identity.** A new deterministic helper — recommended `scripts/framework/audit_pr_producer.py`
(Python, so it is testable per the human's identity direction) — invoked from a **`bin/hos-cron` cron
slice**. Both surfaces are protected (`scripts/framework/**`, `bin/**`) → human-gated. The producer runs
under the **worker identity** (AD-16): it authenticates via the existing `get_app_token.sh --app worker`
(no new auth path needed — the worker role already exists), because `AGENT-IDENTITY.md §7` already grants
the worker class *"opens PRs, never approves."* It is **not** the overseer (whose charter, `overseer.md:7`,
forbids opening branches/PRs) and **not** auditsync (which only approves). The overseer is uninvolved in the
PR; each local audit record still names its deciding agent, so nothing is lost by the worker being the git
author/transport.

**Trigger — cron slice, and it carries the AD-18 mandatory sweep.** Each cron cycle the producer performs
**two** responsibilities, co-located because AD-18 rules an event-only trigger cannot satisfy FR16:
1. **Produce** — open a new audit PR from local audit records not yet on `main` (below).
2. **Sweep** (FR16, AD-18) — enumerate **open** audit PRs and escalate any that are stuck (a required
   check erroring, checks non-green past the ESC-1 bound, or a merge conflict) to the standard
   human-escalation channel, so the backlog is observable, not silent. The cadence *value* is ESC-1's
   (human's); the *existence* of a periodic sweep is bound here.

**Exact produce mechanics (contract — what the code must do):**
1. **Select records.** Determine the local audit records produced since the last successful sync — the
   write-once files under `audit/log/**/*.json[l]` and appends to `audit/oversight-log.jsonl` (the
   allowlisted set per §4 Revision 2) that are not yet on `main`. The "last successful sync" marker is read
   from the heartbeat record the previous cycle wrote (below); no runner-local state.
2. **Chunk to stay under the truncation threshold.** Split the selected records so **no single file's added
   diff exceeds the GitHub files-API patch-truncation threshold (~300 added lines / ~300 KB per file)**.
   A backlog larger than one chunk is split across **multiple sequential audit PRs**, each independently
   qualifying. This is the producer-side complement to §3.5 rule 8 (patch-truncation fail-closed): the
   producer never emits a diff the predicate would have to reject for truncation.
3. **Create the audit branch.** A deterministic, unique branch name (e.g. `audit-sync/{cycle-id}` or
   `audit-sync/{ISO-8601-UTC}`) — never `main`, never a push to `main`.
4. **Commit additions-only, allowlisted paths only.** Stage **only** paths on the §4 allowlist, and only as
   **additions** (append or first-creation), so the resulting diff is exactly what `classify_audit_diff`
   qualifies. **Producer-side self-check (fail-closed):** before opening the PR, the producer runs the same
   allowlist-membership + additions-only atom the predicate uses (§3.2 rules 2–4, shared source per AD-2/
   AD-12) against its own staged diff; if its own diff would **not** qualify, it MUST NOT open the PR — it
   escalates instead. The producer never forces a non-qualifying diff into the mechanism.
5. **Push under the worker identity** to the audit branch (ordinary push to a non-`main` branch, **no
   bypass**). Component H's #880 exemption lets an all-audit branch pass the pre-PR gate.
6. **Open the PR with `base = main`** (satisfying §3.5 rule 0's target-branch requirement by construction),
   authored by the worker bot, labeled/identifiable as an audit PR for the trigger surface (Component F).
7. **Hand off** to the trigger/merge path: Component F/E approves (auditsync), and the ESC-3 merge actor /
   armed auto-merge merges on green — with no identity holding bypass (AD-1).
8. **Write the durable records (FR19 + AD-19c/d).** Append, as ordinary allowlisted audit records that the
   **next** producer cycle carries to `main`: (i) the producer's own decision record (which records it
   selected/committed, with the head SHA and PR number), and (ii) a **"last successful audit sync"
   heartbeat** marker. Neither depends on runner-local disk (AD-19d) — both ride the same audit path, no
   unbounded regress (they are just more inert records batched next cycle).

**Boundaries Component N must honor.** It creates branches and opens PRs (worker role) but **never approves,
never merges via bypass, never pushes to `main`**. It commits **only** allowlisted, additions-only content.
It fail-closes on any anomaly (a local record that is a modification/deletion, a malformed record, an
unreadable allowlist) by **not** opening a PR and escalating. It honors the kill-switch (§16.5).

### 16.2 Component M — `docs/AGENT-IDENTITY.md` fourth-identity-class amendment (NEW; AD-16)

**STRUCTURAL — joins the human structural sign-off. Protected governance surface** (`docs/AGENT-IDENTITY.md`
self-lists as protected in its §9.0). The DRAFT-1 map used "M" for tests; that row is relettered **T**
(§16.7) so "M" carries the ADR's AGENT-IDENTITY assignment.

**What the amendment must do (contract, not prose):**
- **Amend §7 (Account structure — three classes) to declare a FOURTH class.** Add a table row for the
  **audit-approval bot** class: Account `hos-auditsync-hos[bot]`; Class = *single-purpose deterministic
  approver of inert-data audit PRs*; Members = the deterministic `audit_approval_bot` (Component E) only;
  "May approve PRs?" = **"Approves audit-only-and-well-formed PRs ONLY (never code, config, or any
  protected surface); never merges via bypass; holds no content-write."** Update the section heading count
  ("three classes" → "four classes") and add a **"why four now"** rationale paragraph: its trust basis is a
  small **reviewed deterministic Python function** (not an earned LLM approval ceiling like the overseer),
  its approval predicate is *audit-only-and-well-formed* (not risk-tiered), and it is structurally immune to
  the adversarial-framing attack class documented against LLM reviewers
  (`research/findings/adversarial-framing-attack-on-reviewer-agents.md`). State explicitly it is **not** a
  sub-role of the overseer (it performs no risk evaluation or oversight) and **not** the worker (which never
  approves).
- **Record the worker as the audit-PR author.** Note in §7 (worker-class row / members) that the autonomous
  **audit-PR producer (Component N) runs under the worker class** — consistent with the existing
  *"opens PRs, never approves."* **No change to the overseer charter is required** (`overseer.md:7` stands
  verbatim; Component J's exempt-*list* reconciliation is unaffected).
- **Amend §9.0 (protected surfaces) to reflect the fourth class**, with the **same "requires human approval
  regardless of computed risk tier"** framing already applied to the CI gate: any change that grants or
  widens the auditsync approver's authority — the `require_overseer_approval.py` exception (Component C), the
  allowlist (Component B), or this identity declaration — is a protected-surface change that **must** pass
  the human gate regardless of tier (mirrors AD-11/FR11). The identity declaration itself is human-gated
  because `AGENT-IDENTITY.md` is protected.

**A §11 test** (add to §11.8's doc suite) asserts `AGENT-IDENTITY.md` contains a fourth-class row naming
`hos-auditsync-hos[bot]` and the "opens PRs, never approves" worker attribution — so the governance doc and
the running identity model cannot drift.

### 16.3 Component O — `docs/OVERSIGHT-RUNBOOK.md` reconciliation (NEW; AD-19b)

**Part of the structural doc-reconciliation set (not itself a protected surface).** `OVERSIGHT-RUNBOOK.md`
still documents the **superseded direct-audit-commit path**: it states audit decisions "land in
`audit/oversight-log.jsonl` (synced to the `audit-log` branch each cycle)" and its post-merge steps do a
literal `git add audit/` + `git commit -m "…audit log entry…"` directly. That is the exact path FR17/AD-8
retire. **Contract:** reconcile these passages so they describe audit records reaching `main` via the
**checked audit PR** (Component N producer → auditsync approval → ordinary merge), and remove the
`audit-log`-branch "synced each cycle" language and the direct `git commit` of `audit/` to a working branch.
Add it to the Component K/L reconciliation set; the §11.8 FR17 grep acceptance extends to cover this file
(no committed doc instructs a direct audit commit or `audit-log`-branch sync as the path to `main`).

### 16.4 AD-18 — periodic sweep is mandatory (folded into Component N)

Bound in §16.1 responsibility 2 and the §7 Revision 2 note: FR16 is **unsatisfiable by an event-only
trigger**, so a periodic sweep of open audit PRs is **mandatory** and is co-located in Component N's cron
slice. Component F (the approver trigger) may still be Shape 1 (webhook) or Shape 2 (cron) per ESC-1/ESC-3,
but **whichever approver-trigger shape is chosen, the FR16 sweep must exist** — Shape 1 must be augmented
with the Component N cron sweep (it cannot stand alone). This narrows the DRAFT-1 §9 open question: the
event-only option is ruled out as a *sole* shape.

### 16.5 Kill-switch, FR19 home, and the unbounded-growth story (AD-19d/f)

- **Emergency-disable / kill-switch (AD-19f-i).** The named, always-safe operator kill-switch is
  **unsetting `BOT_AUDITSYNC_USERNAME`** in `machine-accounts.env` (Component D): with the audit-bot's
  recognized login unset, Component C's condition (b) can never match, so **every** audit PR falls through
  to the normal overseer requirement and escalates to a human — no audit PR can auto-approve. It is
  fail-closed by construction and safe under AD-2 anti-tamper (it only *removes* approval capability). A
  second, coarser switch is **emptying the allowlist** (Component B), which makes `classify_audit_diff`
  return `qualifies == False` for every diff. Document the first as the primary emergency-disable procedure
  in Component L (`MACHINE-ACCOUNTS-SETUP.md`) and §16.9. When disabled, audit PRs simply wait for a human;
  no records are lost.
- **FR19 durable-record home (AD-19d) — resolved.** As detailed in the §7 Revision 2 note and §16.1 step 8:
  the decision record lives as an allowlisted audit-log append carried by the Component N PR path, never on
  a runner-local disk. This removes the DRAFT-1 ambiguity about where the record persists under an ephemeral
  Actions runner.
- **Unbounded single-append growth (AD-19f-ii).** Bounded jointly by three already-required mechanisms:
  Component N's **chunking** (§16.1 step 2), §3.5 **rule 8** (patch-truncation fail-closed), and AD-18's
  **FR16 sweep** (a wedged oversized diff escalates rather than silently accumulating). Bind all three as
  jointly required; none alone is sufficient.

### 16.6 Filed, not designed — deferrals with named tracked issues (AD-19c/e)

Per architect's deferral, these are **not designed** here. This build does **not** block on either; each
has a named plug-in point for later:
- **Independent external liveness monitor** (a monitor that does not live inside the cron it watches) —
  **DEFERRED → issue "audit-sync + cron-loop independent liveness monitor", linked to #1151.** Plug-in
  point: it consumes the "last successful audit sync" heartbeat Component N already emits (§16.1 step 8) as
  its input. The heartbeat ships now; the external monitor is future work.
- **App-key rotation / expiry / revocation policy across all four identities**
  (worker/overseer/human-proxy/auditsync) — **DEFERRED → issue "GitHub App key rotation policy", linked to
  the #152 identity lineage.** The auditsync key inherits the existing worker/overseer PEM handling
  (Component G already adds the `auditsync` role and documents the `apps.env` PEM location); rotation policy
  is a pre-existing cross-identity gap, not unique to auditsync. Plug-in point: Component G's `apps.env`.

**`gh` is unauthenticated in this session** (`gh auth status` → not logged in), so I **cannot file** these
two deferral issues, nor the DRAFT-1 ISSUE-1/2/3 (§15) or the AF-4 (#880) / AF-5 (producer + charter)
annotations. Per the AF-4/AF-5 precedent these are recorded as a **build-blocking obligation**: **both named
deferral issues MUST be filed before their deferrals are honored**, and the ISSUE-1/2/3 + AF annotations
filed when the tracker is reachable. Flagged, not silently skipped.

### 16.7 Authoritative component map (supersedes §2)

| # | Artifact | Kind | Binding | Protected? | Blocked on |
|---|---|---|---|---|---|
| A | `scripts/framework/audit_predicate.py` (+§3.5 AD-17 rules 0/7/8, base-ref, parser fix) | NEW module + CLI | AD-2, AD-5, AD-6, AD-17 | yes | structural sign-off |
| B | `scripts/framework/audit_allowlist.txt` (narrowed: drop `automation/**`, ext-restrict `log/**`) | NEW config | AD-5, AD-14, AD-17b/c | yes | ESC-2 (now minimal) |
| C | `require_overseer_approval.py` (+ base-ref condition) | EDIT | AD-3, AD-4, AD-17a | yes | **structural sign-off** |
| D | `machine-accounts.env` (+ auditsync login; kill-switch anchor) | EDIT config | AD-1, AD-4, AD-19f | yes | structural sign-off |
| E | `scripts/framework/audit_approval_bot.py` (FR19 → producer PR path) | NEW module + CLI | AD-7, FR13, FR19, AD-19d | yes | structural sign-off; ESC-4 |
| F | approver trigger surface (webhook and/or cron) | NEW | AD-1, AF-1, AD-18 | yes | **ESC-1 + ESC-3** |
| G | `get_app_token.sh` + `apps.env.template` (auditsync role) | EDIT | AD-1 | yes | structural sign-off |
| H | `pre_pr_stale_check.py` (#880 exemption via shared allowlist) | EDIT | AD-12 | no | (ESC-A resolved by AD-12) |
| I | `bin/hos-cron` `_sync_audit_logs` — **REPLACE** (re-home into N) | EDIT | AD-13, **AD-15** | yes | structural (ESC-5 bound) |
| J | `.claude/agents/overseer.md` exempt-list reconciliation | EDIT | AD-5 | yes | ESC-2 |
| K | `DECISIONS.md` new dated entry (+ bypass-remediation) | APPEND | AD-8, AD-19a | no | **structural sign-off** |
| L | `docs/MACHINE-ACCOUNTS-SETUP.md` rewrite (+ bypass-remediation, kill-switch) | EDIT | AD-8, AD-19a/f | no | **structural sign-off** |
| **M** | **`docs/AGENT-IDENTITY.md` — fourth-identity-class amendment** | **NEW EDIT** | **AD-16** | **yes (governance)** | **structural sign-off** |
| **N** | **worker-identity audit-PR producer** (`audit_pr_producer.py` + `hos-cron` slice; incl. AD-18 sweep) | **NEW module + cron slice** | **AD-15, AD-18, AD-19c/d** | **yes (`scripts/framework/**`, `bin/**`)** | **structural sign-off; ESC-1 (cadence)** |
| **O** | **`docs/OVERSIGHT-RUNBOOK.md` reconciliation** | **NEW EDIT** | **AD-19b** | **no** | **structural sign-off (doc set)** |
| T | `tests/framework/**`, `tests/automation/**` (was "M") | NEW / EDIT tests | §11, +§16 fixtures | no | follows its component |

Protected-surface count is now **six** (adds `docs/AGENT-IDENTITY.md`), reinforcing AD-11/TD-VF-7: the
implementation is human-gated regardless of tier and exceeds the soft file-split limit.

### 16.8 Authoritative build order and PR split (supersedes §12)

| # | Slice | Component(s) | Depends on | Blocked on |
|---|---|---|---|---|
| S1 | Shared predicate + unit tests (incl. §3.5 AD-17 rules) | A | — | structural sign-off |
| S2 | Allowlist file (narrowed) | B | — | ESC-2 (minimal) |
| S3 | Bot runtime + tests | E | S1, S2 | structural; ESC-4 |
| S4 | Gate exception + config (+ base-ref) | C, D | S1, S2 | **structural sign-off** |
| S5 | Equivalence test (AD-2 deliverable, +AD-17 fixtures) | A/C/E | S3, S4 | as S3+S4 |
| S6 | auditsync auth role | G | — | structural sign-off |
| S7 | #880 reconciliation + tests | H | S2 | (ESC-A resolved) |
| S8 | Approver trigger surface | F | S3, S6, **S14** | ESC-1 + ESC-3 |
| S9 | overseer.md exempt-list reconciliation | J | S2 | ESC-2 |
| S10 | hos-cron **replace** (re-home push into N) | I | **S14** | structural (ESC-5 bound) |
| S11 | DECISIONS.md entry (+ remediation) | K | S1–S10, S13–S15 | **structural sign-off** |
| S12 | MACHINE-ACCOUNTS-SETUP rewrite (+ remediation, kill-switch) | L | — | **structural sign-off** |
| **S13** | **AGENT-IDENTITY.md fourth-class amendment** | **M** | — | **structural sign-off** |
| **S14** | **worker-identity producer + AD-18 sweep + tests** | **N** | **S1, S2, S6** | **structural sign-off; ESC-1** |
| **S15** | **OVERSIGHT-RUNBOOK.md reconciliation** | **O** | — | **structural sign-off** |

**Producer is the pivot.** The minimal **functional end-to-end** set is **S1 + S2 + S14 (producer) + S3
(bot) + S4 (gate) + S6 (auth) + S8 (trigger)** — no approver-only slice is functional without S14 (AD-15):
a build that ships E/C/F without N produces an approver with nothing to approve and must not be accepted.

**PR-size split (grows 4 → 5 seams; file/commit count materially up with N, M, O + producer tests, now near
the 25 hard ceiling — all human-gated per AD-11):**
- **P1 — predicate + allowlist + equivalence** (S1, S2, S5-core, incl. AD-17 rules/fixtures).
- **P2 — gate exception + config + bot** (S3, S4, S6).
- **P3 — producer + hos-cron re-home + approver trigger/sweep** (S14, S10, S8): the producer half — the
  slice DRAFT-1 lacked entirely.
- **P4 — reconciliations** (S7 #880, S9 overseer.md).
- **P5 — governance + docs** (S13 AGENT-IDENTITY fourth-class, S11 DECISIONS, S12 MACHINE-ACCOUNTS,
  S15 RUNBOOK): the enlarged doc/identity set, incl. bypass-remediation.

Each seam must be independently green; P3 cannot merge before P1+P2 (it depends on the predicate, gate, and
bot); P5's DECISIONS entry (S11) describes what P1–P4 shipped.

### 16.9 Coder-clearance — restated, one more time (supersedes §14's verdict scope)

**`coder` is cleared to build NOTHING today.** The human's **structural sign-off remains the blocking gate
for everything**, and it is now **larger** than at DRAFT-1: it covers AD-3 (the protected-surface CI-gate
exception) + AD-8 (the `DECISIONS.md` supersession + `MACHINE-ACCOUNTS-SETUP.md` rewrite) **and now also**
AD-15 (the worker-identity producer, Component N) + AD-16 (the fourth-identity-class governance amendment,
Component M) + the AD-19a consumer bypass-remediation + the Component O runbook reconciliation. What has
**cleared** since DRAFT-1: ESC-5 (bound by AD-13/AD-15 — no interim consumer), and the architect escalations
ESC-A/ESC-B/ESC-C (resolved by AD-12 / AD-2 erratum / AD-14). The **remaining human gates** are exactly:
1. **Structural sign-off** (the enlarged set above) — the master gate; without it, nothing that ships
   behavior *or* the identity/governance model may be built.
2. **ESC-2** (allowlist membership) — now **nearly settled** (§4 Revision 2 note narrows it to
   `oversight-log.jsonl` + `audit/log/**/*.json[l]`; the only open question is whether REQUIREMENTS-034's
   ledgers are re-added later, with a validator).
3. **ESC-3** (merge actor / auto-merge) — still the human's; no option may reintroduce a bypass (AD-1/FR1).

ESC-1/ESC-4/ESC-6/ESC-7 proceed on bound defaults and do not block. Independently, the implementation PR is
a **six-protected-surface** change a **human must approve at merge time regardless of computed risk tier**
(AD-11); this document is not that approval, and the audit-approval bot's own review can never provide it
(AD-4). Per my role I record this on the design as an escalation to the human: **the design is now
structurally complete (the producer gap is closed), but the build stays fully blocked pending the enlarged
structural sign-off.**

### 16.10 Startup-gap analysis for the Revision 2 changes

*Should the producer and the fourth-identity-class declaration have been in the initial technical design,
before any code was written against it?* **Yes** — and the ADR's AF-5 records the same for its own §0. But
**no design or code sign-off has been issued** against the DRAFT-1 shape (DRAFT-1 was never approved by
architect; nothing is built). **Affected-sign-offs analysis: none are orphaned** — this is the good case,
the gap caught by review before any build. The producer gap (AD-15) and charter/identity gap (AD-16) are
closed here in the design contract; the process obligation (annotate the panel finding onto the TD
duplication/gap issue, ISSUE-3) is recorded in §16.6 as blocked only on `gh` reachability. This Revision 2
edit therefore leaves **no already-approved code unaudited against a changed contract** — because there is
no already-approved code.

---

## Human Review Required

**RISK: MEDIUM.** This design implements a new autonomous approval identity and a narrow, identity-bound
exception to a protected-surface CI gate. Blast radius is bounded exactly as the ADR intends — inert
audit data only, additions-only, allowlist-derived, deterministic (no model), **one shared predicate
with a mandatory equivalence test** (no #1135 drift), identity-bound (no diff-shape fail-open),
fail-closed on every ambiguity, AF-1 data-only fetch (no #972 checkout-execute), and the gate change is
itself human-gated. The residual failure modes are the ones the human's held rulings close: a mis-scoped
allowlist (ESC-2) or an under-specified markdown validator (ESC-C) could let a non-inert or unvalidated
path ride the exception — which is why membership and the `.md` shape stay open, and why the predicate
is a single tested source. I surfaced **two HIGH findings the ADR did not** (the #880 conflict that
would have blocked the mechanism outright, and the half-built #1095 producer that answers ESC-5's
verification gap), both of which tighten rather than loosen the design.

**CONFIDENCE: HIGH** on the component contracts and on the §0 verification — I read every gate, the
workflow trusted-base model, the config files, `bin/hos-cron`, and `pre_pr_stale_check.py` in full on
`origin/main`. **LOWER** on: the live ruleset "zero bypass" state and the existence of the `audit-log`
branch (both unverifiable — `gh` unauthenticated); the exact `overnight-loop-log.md` record shape
(producer not locatable — TD-VF-6/ESC-C); and anything downstream of the unread #1095/#873/#1151 bodies.

**BLAST RADIUS:** the `main`-branch protection posture and the audit trail's integrity on every consumer
deployment; the implementation touches five protected surfaces (`scripts/framework/**`, `bootstrap/**`,
`bin/**`, `.claude/agents/**`, `.github/workflows/**`).

**Change classification: STRUCTURAL.** New machine identity with approval authority (scope-reduced,
AD-1); new exception to a protected-surface gate (AD-3); reconciliation of a live gate (#880) that would
otherwise block the mechanism (TD-VF-2); supersession of a standing `DECISIONS.md` entry and rewrite of
live setup documentation (AD-8). Per the CORE product-boundary checkpoint and the ADR's own holds, the
structural items and the security-consequential escalations (ESC-2/3/5) require explicit human sign-off
before they bind, and **I escalate to the human on record that `coder` is NOT cleared to build.**

**Cleared-to-build statement.** `coder` may build **nothing** today. The build unblocks only when the
human (1) signs off the structural change (AD-3 gate exception + AD-8 supersession/doc rewrite) and (2)
rules ESC-2 (allowlist membership), ESC-3 (merge actor), and ESC-5 (#1095 ordering) — with the new input
from TD-VF-1 that #1095's interim path is producer-only. ESC-1/ESC-4 may proceed on the bound defaults
and do not block. Additionally, `architect` must rule ESC-A (the #880 topology), and the `overnight-loop-log.md`
shape (ESC-C) must be reconciled at build time or the file dropped from the allowlist. The implementation
PR is itself a five-protected-surface change a human must approve at merge time regardless of tier
(AD-11) — this document is not that approval.

---

> ## Human Review Required — Revision 2 addendum (2026-08-01)
>
> This addendum self-flags the Revision-2 design change (§16). It **supersedes the DRAFT-1 self-flag above
> only where noted**; the DRAFT-1 block is left intact per the append/revise convention.
>
> **RISK: MEDIUM.** Revision 2 does not loosen anything — every change **tightens** the design: it adds the
> missing producer (Component N) so the mechanism is no longer inert, hardens the predicate with six
> narrow-only rules (AD-17: target-branch, zero-content, truncation, parser fix), makes the FR16 sweep
> mandatory (AD-18), declares the fourth identity class explicitly (AD-16), and adds consumer
> bypass-remediation (AD-19a). The residual failure modes remain the ADR's held ones (allowlist membership
> ESC-2 — now nearly settled; merge actor ESC-3). The producer is the one genuinely new blast-radius
> surface — a worker-identity component that opens PRs to `main` — but it holds **no** content-write or
> bypass, commits **only** allowlisted additions-only content, self-checks against the shared predicate
> before opening a PR, and targets `main` explicitly (rule 0); its authority is strictly the existing
> worker "opens PRs, never approves."
>
> **CONFIDENCE: HIGH** on the component contracts (they design directly against binding AD-15…AD-19 and
> pm-agent's FR2 correction), and on the two doc-reconciliation targets, which I re-verified on
> `origin/main` (`AGENT-IDENTITY.md §7` three-class table + §9.0 protected listing; `OVERSIGHT-RUNBOOK.md`
> lines 61–63 `audit-log`-branch sync + the direct `git commit` of `audit/`). **LOWER** on the live ruleset
> "zero bypass" state and the two deferral issues — **`gh` is unauthenticated here, so the #1151 liveness
> monitor and #152-lineage key-rotation issues, plus ISSUE-1/2/3 and the AF-4/AF-5 annotations, still need
> real issues filed** (§16.6): recorded as a build-blocking obligation, not silently skipped.
>
> **BLAST RADIUS (updated):** now **six** protected surfaces — the DRAFT-1 five (`scripts/framework/**`,
> `bootstrap/**`, `bin/**`, `.claude/agents/**`, `.github/workflows/**`) **plus `docs/AGENT-IDENTITY.md`**
> (the fourth-identity-class governance amendment, Component M).
>
> **Change classification: STRUCTURAL** — it adds a new autonomous producer identity role and amends the
> governance identity model (fourth class). Per AD-16's explicit routing, these **fold into the existing
> structural sign-off already routed to the human**; they create **no new, separate human gate**. This is
> `technical-design` designing against architect's *binding* AD-15/AD-16 rulings, not a new decision — so I
> do not re-escalate the decision, I record the enlarged contract and hand the design back to `architect`
> for re-review (§16.9).
>
> **Cleared-to-build (updated, supersedes the DRAFT-1 statement above):** `coder` may build **nothing**
> today. ESC-5 is now **bound** (AD-13/AD-15) and ESC-A/ESC-B/ESC-C **resolved** (AD-12 / AD-2 erratum /
> AD-14), so those drop off. The build unblocks only when the human (1) signs off the **enlarged structural
> change** (AD-3 gate exception + AD-8 supersession/doc rewrite + **AD-15 producer identity** + **AD-16
> fourth-identity-class amendment / Component M** + AD-19a bypass-remediation) and (2) rules **ESC-2**
> (allowlist membership, now nearly settled) and **ESC-3** (merge actor). The implementation PR is a
> six-protected-surface change a human must approve at merge regardless of tier (AD-11) — this document is
> not that approval.
>
> **Next step:** `architect` re-review of this Revision 2 (the producer + fourth-identity-class contract),
> then — only after the human's enlarged structural sign-off + ESC-2/ESC-3 — a `needs-ai` issue to the
> autonomous `worker` in the v0.7.0 milestone.
