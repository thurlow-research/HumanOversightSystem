# REQUIREMENTS-1605 — Split `security_scan.sh`: wire bandit-HIGH into CI as its own gate, move pip-audit to a schedule

**Status:** RULED by `pm-agent` — binding on `architect`, `technical-design`, `coder`, `unit-test`, `system-test` for issue #1605.
**Date:** 2026-09-22
**Author:** pm-agent
**Issue:** #1605 (v0.7.0, priority:high). Parent #1567; pattern #1571; vulnerabilities #1504.
**Inputs:** issue #1605 body; the worker's investigation brief; and eight facts I re-measured myself this session against this branch (§0).
**Consumers:** `architect` → `technical-design` → `coder`.
**Scope note:** This document says WHAT and WHY. It names no file layout, no flag spelling, no algorithm. Where it appears to, the text is marked NON-BINDING.
**Amendment 2026-10-14 (pm-agent) — PENDING HUMAN CLEARANCE:** AC-20, AC-20a (new), AC-26 and I-4 carry proposed amendments that align them with ADR-1605 AD-12a/AD-12b (label-authenticated tracking issue; CWE-345/CWE-863). This is a **STRUCTURAL** change: a new repo label and a new operator obligation. It takes effect only on explicit human clearance in the PR thread (ADR §6 item 3; §5 below). Until then, the original text of AC-20/AC-26 remains the approved requirement, and the implementation's use of the label is an open, disclosed discrepancy against it. **Merge gate (clarified 2026-10-14):** human clearance of AD-12a/AD-12b gates the merge of the **Part 2 implementation PR**, not this design PR. Until a human records that clearance in the implementation PR's thread, the implementation PR MUST NOT merge; disclosing the discrepancy in its body is required but is not sufficient to merge (ADR §6 item 3; TD merge-gate banner).

---

## 0. What I verified myself (only re-measured facts; the brief's others are taken as given)

| # | Claim | Verdict |
|---|---|---|
| V-1 | bandit 1.9.4 contaminates **stdout** with a rich progress bar before the JSON | **Confirmed.** `Working... ━━━ 100% 0:00:02\n{` at 219 files. |
| V-2 | The contamination threshold is a **file count** | **FALSE — it is duration.** No bar at 50 files (0.70s); bar at 100 files (1.22s) and 150 (2.09s). The trigger is elapsed scan time, so it varies with machine speed, CPU load and file size. |
| V-3 | The gate therefore fails open | **Confirmed by construction.** Parse fails → `2>/dev/null \|\| echo "0"` → `HIGH_COUNT=0` → prints `OK: no HIGH severity findings`. |
| V-4 | Existing tests cover this | **FALSE.** `test_security_scan_no_args_detects_high_finding` plants **one** file; sub-second scan, no bar, passes today with the defect live. The defect is wholly uncovered. |
| V-5 | `bandit -o <file>` emits uncontaminated JSON | **Confirmed**, rc=0, file begins `{ "errors": [],`. |
| V-6 | Bandit-HIGH debt baseline is 0 | **Confirmed, and confirmed *through the clean channel*** — 219 tracked `.py` files, `-lll -o`, **0 HIGH, 0 results total**. The baseline is genuine, not an artifact of V-3. |
| V-7 | `security` is excluded from `AUTO_CHECKABLE_GATES` | Confirmed (six keys, `security` absent). |
| V-8 | Zero `on: schedule` workflows exist in the repo | Confirmed. This is the first. |

**V-2 and V-6 are the two findings that move decisions.** V-2 dictates how AC-5/AC-6 must be tested (a duration-dependent bug cannot be pinned by a natural-reproduction test). V-6 removes the only reason to hesitate over the CI wiring: the gate lands green on day one.

---

## 1. Scope ruling

### S-1 — The bandit stdout fail-open fix is **IN SCOPE** for this PR. (The brief's question, answered.)

Four reasons, in ascending weight:

1. **The code is being moved anyway.** The bandit lane is the exact code this PR extracts into a standalone gate. Extracting a known-broken lane and fixing it in a follow-up means shipping a new file that is defective at the moment it is created.
2. **It defeats the issue's own stated purpose.** #1605 exists because "the HIGH-severity block is not executed anywhere in CI." A gate that cannot report a finding is not executed in any sense that matters; it would close the issue's letter and leave its purpose open.
3. **V-2 makes the residual risk worse than the brief assumed.** A count threshold would at least be predictable ("small PRs are safe"). A *duration* threshold means the same PR passes on a fast runner and fails open on a slow or loaded one — and CI runners are exactly the slow, loaded, shared environment where the bar is most likely to render. Wiring the gate into CI **increases** exposure to the defect rather than leaving it flat.
4. **Dispositive: it is a silent-negative security control.** A gate that prints `OK: no HIGH severity findings` when it in fact parsed nothing is worse than no gate at all — it manufactures affirmative evidence of safety. Every downstream consumer (the overseer's check reading, the #1571 debt baseline, a future promotion to required) treats that line as a measurement. Shipping a CI job whose green is not evidence is a governance defect, not a code defect, and this pipeline exists to prevent exactly that.

**Bounded, so it cannot absorb the PR.** In scope is only: (a) the bandit lane's JSON acquisition channel, and (b) fail-closed handling when that JSON is unparseable. Out of scope: any broader audit of the gate's other lanes, retry semantics, or timeout behaviour.

### S-2 — The **same fail-open class** in the pip-audit half is in scope only as a *construction requirement on the new code*, not as a fix to the old.

The pip-audit lane carries an identical `|| echo "0"` shape on `VULN_COUNT`. Since that lane's *reporting* behaviour is being rewritten as a scheduled workflow, the requirement attaches to the new artefact (AC-23) rather than generating a second fix to code that is about to change. The locally-retained pip-audit gate keeps its current behaviour otherwise.

### S-3 — Promotion of the new bandit job to a **required** status check is **DEFERRED** to a follow-up. Not in this PR.

V-6 says it is promotable, and the #1571 ratchet argument applies cleanly. I still defer, because: (i) #1605 asks to *wire*, not to *promote* — #1571 deliberately separates those two acts; (ii) promotion changes what blocks a merge for every future PR, which is a control change deserving its own visible decision rather than a line inside a refactor PR; (iii) the precedent promotions (type-check, lint) are recorded as **human overrides**, so the pattern is that a human decides promotion. Wiring alone is useful without it: the job runs, is visible on the PR, and the overseer reads check status.

**What would change my mind:** an explicit human instruction in this PR's thread. Nothing else — not the zero baseline, which I have already weighed.

### S-4 — Both halves keep running locally through `run_gates.sh` auto-discovery, with **no edit to `run_gates.sh`**.

Auto-discovery is `find gates/ -maxdepth 1 -name '*.sh'`. If an implementation needs to modify `run_gates.sh`, that is a signal the split is wrong; treat it as a design escalation, not a licence to edit.

### S-5 — Deferred to follow-up issues (to be filed by the worker when this PR opens, not by me)

| F | Deferred item | Why not now |
|---|---|---|
| F-1 | Promote `oversight-gate-security-scan` to required (add to `setup_branch_protection.sh`; human runs it) | S-3. Cite V-6's measured 0/219 baseline as the evidence, so the follow-up is a one-line decision. |
| F-2 | Audit every gate for the same "unparseable tool output → `\|\| echo 0`" fail-open shape | The pattern almost certainly recurs (pip-audit's lane already does). A repo-wide sweep is its own change with its own blast radius. **File this one regardless of PR budget** — it is the generalisation of a confirmed security defect. |
| F-3 | An issue create/update/list helper in `scripts/automation/lib/github.py` | Only if the technical design concludes the scheduled workflow needs one. Not presumed. |
| F-4 | Retiring the tracking issue in favour of #1504, or vice versa, once #1504 closes | See I-4. |

### S-6 — PR budget (≤15 files, ≤10 commits) and drop order

My estimate is 13–14 files, which is tight. If the implementation runs over, shed in **this order** — and stop, do not improvise past it. *(Aligned 2026-10-14 to ADR-1605 AD-14's shed order, which is binding; the 2026-09-22 step 2 — "`docs/OVERSIGHT-RUNBOOK.md` prose beyond the gate→key table row" — is withdrawn.)* (1) `SCRIPTS-INDEX.md` regeneration → follow-up; (2) fold the GitHub-helper tests into the scheduled workflow's own test file; (3) the scheduled pip-audit workflow, **split whole into its own PR** with #1605 kept open. **Never shed:** the fail-open fix and its test (S-1), the gate→key table updates (AC-29), the DECISIONS.md entry, or the runbook's "do not hand-remove the `dependency-audit` label" operator obligation (AC-26 amendment) — that line is a product obligation, not sheddable prose. If the scheduled workflow is split out, say so explicitly in the PR body — a silently half-delivered issue is a worse outcome than two PRs.

> **Commit-budget waiver request, 2026-10-14 (pm-agent): NOT GRANTED by pm-agent. ESCALATED to a human.** The request came from the architect (step1605-design register, 2026-10-14T08:35:54Z, C1). The Part 2 implementation branch already has 10 reviewed commits, ending at `b9c342559`. The security-review amendments would land as exactly one more commit, which makes 11 and exceeds the ≤10-commit limit above. The architect ruled correctly that the reviewed commits must not be squashed, because their SHAs anchor re-confirmations that are still pending.
>
> **Why pm-agent does not grant this itself.** The ≤10 limit in this section is not mine alone. It restates `docs/PR-SIZE-POLICY.md`. That policy calls ≤10 commits "recommended" with no hard ceiling, but it also does three things. It forbids the worker from opening a PR over 10 commits without splitting. It has the overseer request changes on one. And it says that when a split is genuinely impossible, the worker must "file a `needs-human` issue … and await explicit human authorization before exceeding the limit". It also says only human authorization overrides the agent-level enforcement. If pm-agent waived it, an agent would be approving its way past a human-gated step, so I may not.
>
> **PM recommendation to the human: authorize it.** The product reading supports the waiver. The limit exists to keep review fast and history readable. One extra commit containing only design-review-mandated security amendments does not weaken either, and the file budget is unchanged at 14 of 15. Splitting the amendments into their own PR is not an option, because the architect's conditions require them to land before Part 2 merges. Squashing would invalidate review anchors. Suggested terms for the human's authorization:
> - exactly **one** additional commit (11 total), containing only the security design amendments (SEC-M1/M2/S1/S4/S5 and their tests);
> - the file count stays ≤15;
> - the implementation PR body discloses the 11-commit count and links the human's authorization.
>
> If this is not authorized, the amendment commit MUST NOT be made, and the worker escalates instead of improvising (for example by squashing, or by splitting the amendments out against the architect's ordering).
>
> **Sequencing (corrected 2026-10-14, architect C6(b)):** the authorization MUST be obtained **before** the 11th commit is made. It MUST NOT wait for the AD-12a/AD-12b clearance. That clearance is recorded in the Part 2 implementation PR's thread, and that PR cannot be complete until the 11th commit already exists, so pairing the two would require making the commit first. The authorization is obtained in one of two places: a `needs-human` issue, as `docs/PR-SIZE-POLICY.md` prescribes for exceeding the limit ("file a `needs-human` issue … and await explicit human authorization before exceeding the limit"), or this design PR's thread. **This design PR's body MUST list the S-6 commit-budget waiver as an explicit human decision item**, separate from the AD-12a/AD-12b clearance. The waiver is not implied by that clearance, and that clearance is not implied by the waiver.

---

## 2. Acceptance criteria

Each is independently testable. "MUST" is binding; "SHOULD" is rebuttable by the architect with a stated reason.

### A. The standalone bandit-HIGH gate

**AC-1 — Runs standalone, with no network and no pip-audit.** Invoking the bandit-HIGH gate alone MUST complete a scan and report a verdict with pip-audit never invoked and no network access attempted. Testable: its output contains no pip-audit section, and the run succeeds with network unavailable.

**AC-2 — The file-list argv grammar is preserved exactly.** The bandit-HIGH gate MUST remain a `FILE_LIST_GATES` member under `tests/oversight/test_gate_arg_grammar.py`: positional files, `--diff <ref>`, `--step <n>`, `--staged`, `--all`, `--empty-changeset`, `--help`; exit 2 on unknown option with `unknown option` on stderr; exit 3 with empty stdout on a bad ref. Testable: that parametrised suite passes with the gate in the list, unmodified except for any rename.

**AC-3 — The #976 no-fail-open-on-empty-args contract survives.** A no-selector invocation MUST still default to a full project scan, print the `no files specified — defaulting` line, and detect a planted HIGH finding. Testable: `tests/oversight/test_scan_gates_empty_args.py`'s two security cases pass unchanged (modulo rename).

**AC-4 — Unparseable bandit output MUST fail the gate closed.** When the JSON the gate consumes cannot be parsed, the gate MUST exit non-zero and MUST NOT print any line asserting absence of findings (`OK: no HIGH severity findings` or equivalent). Zero findings MUST never be inferred from a parse failure. Testable deterministically: stub bandit on `PATH`/in the venv emitting garbage, assert non-zero exit and absence of the OK string.

**AC-5 — Progress-bar-contaminated output MUST be parsed correctly, not merely survived.** Given bandit output carrying a rendered progress bar *and* a genuine HIGH finding, the gate MUST report `GATE FAIL` naming that finding. Testable deterministically via a stub emitting `Working... ━━━ 100% 0:00:02\n` followed by fixture JSON containing one HIGH result.
> **Why a stub is mandatory here, not a convenience:** per V-2 the real bar is triggered by elapsed scan time (~1s on this machine), not file count. A natural-reproduction test would pass or fail with runner speed. A stub-based test is the only deterministic pin. NON-BINDING: `bandit -o <file>` is the known-good acquisition channel (V-5).

**AC-6 — End-to-end positive control.** A real bandit run over a file set large enough to trigger the bar on the executing machine, containing one genuine HIGH finding (e.g. `subprocess.Popen(cmd, shell=True)`), MUST report `GATE FAIL`. This test MAY be marked slow/opt-in and MUST NOT be allowed to gate CI on timing; AC-5 is the enforcing test, AC-6 is corroboration.

**AC-7 — Suspension still works and is scoped.** The bandit-HIGH gate MUST honour a suspension key via `is_suspended`, printing the suspended notice and exiting 0. It MUST NOT be added to `AUTO_CHECKABLE_GATES` (V-7: `security` is deliberately excluded; preserve that).

### B. Local behaviour — both halves

**AC-8 — `run_gates.sh` runs both halves locally with `run_gates.sh` itself unmodified.** Testable: a local full run's output contains both a bandit section and a pip-audit section, and `git diff` touches no line of `scripts/oversight/run_gates.sh` (S-4).

**AC-9 — The two halves have distinct suspension keys, independently effective.** Suspending the dependency half MUST NOT suspend bandit, and vice versa. Testable: two runs, one key suspended each time, asserting exactly one section is skipped.

**AC-10 — The dependency half is repo-scoped.** It MUST ignore file arguments and resolve its own applicability, following the `django_check.sh` / `astro_check.sh` precedent. Dependency posture is not derived from a diff — that premise is the whole issue. ~~Consequence, accepted explicitly: a local `run_gates.sh` run on an empty changeset now makes a network call where it previously short-circuited. This is a deliberate trade, and it MUST be noted in the runbook.~~ **Struck 2026-10-14 (pm-agent, clarifying): superseded by ADR AD-2a (§2a, 2026-09-22).** The dependency half honours the runner's explicit `--empty-changeset` signal and reports not-checked, so an empty-changeset run makes no network call and behaves as it does today. The runbook MUST NOT claim otherwise. AC-10's binding MUST (ignore file arguments, resolve its own applicability) is unchanged.

**AC-11 — The dependency half MUST NOT appear in `oversight-gates.yml`.** That workflow is deterministic-only, no network (brief constraint). Testable by grep, and by the CI-execution inventory row.

### C. The CI job

**AC-12 — Its own job, following the #1571 per-check pattern.** A new job in `.github/workflows/oversight-gates.yml`, named per the existing `oversight-gate-*` convention, not folded into any existing job. Its step shape MUST match the other file-scoped jobs: checkout PR head, Python 3.12, `ensure_venv.sh` with `HOS_SKIP_PROJECT_REQUIREMENTS=1`, fetch base, `git diff --name-only origin/$BASE...HEAD`, skip cleanly on empty diff, invoke the gate with the changed files.
> **Note 2026-10-14 (pm-agent, CLARIFYING): two sanctioned divergences from the literal step list.** The security design review (step1605-design-security, round 2: M-2 and S-1) changed two steps of the new job on purpose. Both are accepted by the architect (step1605-design register, 2026-10-14T08:35:54Z, C4). A job that makes these two changes and otherwise matches the sibling file-scoped jobs **satisfies AC-12**:
> 1. **Changed-file listing (SEC-M2).** The job lists files with `git diff -z` and reads them with `mapfile -d ''`, which is NUL-delimited. The siblings use newline-delimited `--name-only`. The listing is the same: the same three-dot range against the fetched base, the same set of changed files, passed to the gate as explicit argv. The change only stops a filename from being quoted, split or mangled: a non-ASCII name (git's `core.quotepath` quoting) or one containing whitespace or a newline. That keeps AC-13's "MUST pass the PR's changed files" exact.
> 2. **Scanner-presence assertion (SEC-S1).** The job has one extra step, after the venv build and before the scan, that fails the job if bandit is not present. This applies AC-4's rule that "zero findings MUST never be inferred" to a missing scanner. It does not change the skip-on-empty-diff step or the gate invocation.
>
> Why this is clarifying and not structural: AC-12's intent is a separate, file-scoped `oversight-gate-*` job that follows the #1571 pattern. Neither divergence changes the job's identity, its trigger, its scope (AC-13) or its required/advisory status (AC-15). Each one only makes it harder for the job to pass while having scanned the wrong files or none. Naming the literal `--name-only` flag was over-specification against this document's own scope note ("names no … flag spelling"). Other divergences from the sibling step shape are still bound by AC-12 as written. The matching annotation to the ADR's "step-for-step identical" text is at ADR-1605 AD-9 (the 2026-10-14 note), which records the same two divergences and no others. *(Updated 2026-10-14.)* Per that note, the primary reason for `-z` is git's default path quoting (`core.quotepath`): without it, a non-ASCII `.py` filename is emitted C-quoted and skipped as non-Python. Passing filenames that contain whitespace or newlines intact is the secondary benefit.

**AC-13 — File-scoped, not `--all`.** The job MUST pass the PR's changed files. A whole-repo run would surface pre-existing findings never enforced at that granularity — the explicit rationale in the workflow's own header.

**AC-14 — The per-gate debt baseline comment block gains an entry.** It MUST record the measured baseline **and how it was measured**: 0 HIGH over 219 tracked `.py` files, measured 2026-09-22 through bandit's uncontaminated output channel. The measurement method is load-bearing given V-3 — a bare "zero debt" note would be indistinguishable from a fail-open reading.

**AC-15 — Not promoted to required (S-3).** `scripts/framework/setup_branch_protection.sh` MUST NOT gain this check in this PR. Testable by diff.

**AC-16 — A HIGH finding in changed files fails the check.** Positive control at the job's own command shape: running the job's exact invocation against a file set containing a HIGH finding exits non-zero.

### D. The scheduled pip-audit workflow

**AC-17 — Its own workflow file, scheduled and manually dispatchable.** `on: schedule` (weekly SHOULD be the default cadence; nightly is acceptable) **plus** `on: workflow_dispatch`. Dispatch is mandatory, not optional: without it the only way to exercise the workflow is to wait for cron, which makes AC-19..AC-24 unverifiable at review time.

**AC-18 — CI-native auth, no App token minting.** `permissions: contents: read, issues: write` with the workflow-provided `GITHUB_TOKEN`, per the `label-swap.yml` precedent. The workflow MUST NOT mint a GitHub App token. It MUST NOT be triggered by `pull_request` and MUST NOT be capable of failing a PR check.

**AC-19 — A concurrency group MUST prevent overlapping runs.** A scheduled run racing a manual dispatch is the realistic path to two tracking issues, which would break AC-20 permanently. Testable by inspection of the workflow.

**AC-20 — Exactly one tracking issue, ever, identified by a hidden marker.** The workflow MUST locate its issue by a hidden HTML marker comment in the issue **body**, searched across `state=all` (open *and* closed). It MUST NOT match on title — titles are edited by humans, and a title miss silently creates a duplicate. Precedent: the worker cron prompt's `<!-- hos-worker-merge-block -->`.

> **Proposed amendment (2026-10-14, pending human clearance — ADR AD-12a):** ~~identified by a hidden marker~~ → **identified by the `dependency-audit` label AND the hidden marker as the body's first line, both required.** The marker is a public constant, so marker-only identification can be forged by anyone who can open an issue. That lets them hijack the bot-maintained issue, or cause a repeatable weekly DoS through a planted duplicate (CWE-345/CWE-863). Under the amendment:
> - An issue is adopted only if it carries the label (exact name) **and** has the marker on its first line. Neither condition alone matches.
> - Ambiguity (more than one match ⇒ fail closed, zero writes) counts **only issues carrying both**.
> - An issue that carries the marker but not the label is **ignored**. It is not adopted, and it does not count toward ambiguity, so it cannot block the first-run create or the weekly report.
> - The `state=all` search scope and the never-match-on-title rule are unchanged.
>
> Accepted residual (ADR AD-12a): an actor who already has triage rights can still plant a doubly-qualified issue. Author pinning is deferred to #1812 item 5.

**AC-20a — (Proposed, 2026-10-14, pending human clearance — ADR AD-12b) Creation applies the label and fails closed if it did not stick.** When the workflow creates the tracking issue, it MUST request the `dependency-audit` label on create. It MUST check the issue object returned by GitHub's create response, and if the label is absent the run MUST fail visibly (non-zero exit, message naming the missing label). Without this check, a create that silently loses the label leaves an issue that can never be adopted, and the next run creates another one every week, which is AC-20's duplicate as a slow leak. The check fires on create only; a reopen (AC-24) re-adopts the existing labelled issue. Testable without network via a recorded/stubbed writer whose create response omits the label (AC-28).

**"Idempotent" means exactly the following four cases (AC-21..AC-24).** The comparison unit is the **normalized finding set**: the set of tuples `(package name, installed version, vulnerability ID, sorted fix versions)`, compared order-insensitively. Fix versions are part of the key deliberately — `fix: none` becoming `fix: 1.2.3` is actionable news and MUST count as a change.

**AC-21 — Repeat run, identical finding set → ZERO writes.** No new issue, no comment, no body edit, no label change, no reopen/close. Not "a harmless no-op update" — zero write calls. Testable with fixture JSON and a mocked/recorded write layer.

**AC-22 — Changed finding set → one body update and exactly one comment.** The issue body is replaced with the current full set; exactly one comment is posted describing the delta (what was added, what was removed). One comment per change event — never one per finding.

**AC-23 — Zero findings → close, and only if an issue is open.** With an open tracking issue: post one closing comment and close it. With no issue, or an already-closed one: zero writes. The workflow MUST NEVER create an issue asserting zero findings.

**AC-24 — Findings return after closure → reopen the same issue.** The workflow MUST reopen and update the existing marked issue, never create a second one. This is what makes AC-20's "exactly one, ever" hold across the full lifecycle.

**AC-25 — Execution failure MUST NOT be read as zero findings.** If pip-audit times out, hits a network error, or emits unparseable output, the workflow run MUST fail visibly, and MUST NOT close the issue, edit its body, or post a comment. This is AC-4's rule applied to the second artefact (S-2) — and it is the single most likely way this workflow silently rots, since a permanent network failure would otherwise read as "all vulnerabilities fixed" and auto-close the issue. *(Clarified 2026-10-14, security review S-4:)* pip-audit output whose fields do not match the technical design's strict allowlist patterns counts as unparseable here — it MUST be rejected as malformed with the same fail-visible, zero-writes outcome (patterns and exit code are the TD's).

**AC-26 — No new label.** The tracking issue MUST NOT require a label absent from `docs/LABELS.md` / `KNOWN_LABELS`. It SHOULD carry no pending-actor label at all: it is a reporting artefact, not queued work, and `needs-ai` would route the worker into #1504's territory autonomously. Its body MUST cross-reference #1504.

> **Proposed amendment (2026-10-14, pending human clearance — ADR AD-12a/AD-12b):** ~~No new label. The tracking issue MUST NOT require a label absent from `docs/LABELS.md` / `KNOWN_LABELS`.~~ This clause is **superseded by AD-12a**. The tracking issue carries exactly one label, `dependency-audit`, which is its authenticator (AC-20, AC-20a). This is a **new repo label** and needs explicit human clearance (ADR §6 item 3). The rest of AC-26 still holds unchanged: the issue carries **no pending-actor label** (no `needs-ai`, because it is a reporting artefact and not queued work), and its body MUST cross-reference #1504. Two consequences follow:
> - **Registry deferral:** the `docs/LABELS.md` / `KNOWN_LABELS` row for `dependency-audit` is deferred to **#1812 item 12** (the implementation PR is at 14 of 15 files and the registry row touches two files — `docs/LABELS.md` and `KNOWN_LABELS` in `scripts/framework/check_agents_static.sh` — which would make 16). Until it lands, the label exists in the repo but not in the registry.
> - **New operator obligation:** do not hand-remove the label from the tracking issue. Removing it makes the next run treat the issue as absent and create a duplicate.

**AC-27 — Issue bodies MUST NOT be passed via `@path` expansion.** No `-f body=@file` / `--field body=@path` (#752, #1155) — that posts the literal string. Body content goes via a mechanism verified to transmit file contents.

**AC-28 — The idempotency logic MUST be unit-testable without network or live GitHub.** The finding-set normalization and diff MUST be callable directly against fixture JSON. Without this, AC-21..AC-25 are only assertable by inspection, and a workflow whose correctness rests on inspection is exactly the class of artefact this PR exists to eliminate. This is a binding *testability* requirement; where the logic lives is the technical design's call.

### E. Registry and docs

**AC-29 — Every gate→key table updated in the same PR.** `docs/specs/SPEC-375-deterministic-gate-invariant.md`, `docs/OVERSIGHT-RUNBOOK.md` (both the table and the invocation example at ~:301), `docs/CI-EXECUTION-INVENTORY.md`, and `SCRIPTS-INDEX.md` (regenerated via `scripts/framework/gen_scripts_index.sh`, never hand-edited).

**AC-30 — The retired rationale is explicitly retired.** `docs/CI-EXECUTION-INVENTORY.md`'s `security_scan.sh` row currently reads "CI-portable, deferred" *because of pip-audit*. It MUST be replaced by rows reflecting the split, not left alongside them.

**AC-31 — A DECISIONS.md entry, appended at the bottom under a dated header**, recording: the split, the fail-open defect and V-2's duration trigger, the V-6 baseline with its measurement method, and the S-3 deferral of promotion.

---

## 3. Non-goals — explicitly NOT this PR

1. **Fixing the 17 dependency vulnerabilities.** That is #1504. This PR changes only *where and how* they are reported.
2. **Promoting the bandit job to a required status check** (S-3, F-1).
3. **Any change to bandit's severity threshold.** HIGH blocks; MEDIUM continues to flow to `static_analysis.py` as a scored signal only. Not revisited.
4. **Any change to `static_analysis.py` or `oversight-validators.yml`.** The MEDIUM-severity scored lane is untouched; the duplication between it and the new job is intentional (different severities, different purposes).
5. **A repo-wide audit of other gates for the same fail-open shape** (F-2) — filed, not done here.
6. **Any change to `run_gates.sh`** (S-4).
7. **A general-purpose GitHub issue CRUD library** (F-3). Build only what the workflow needs.
8. **Changing suspension infrastructure** — no `AUTO_CHECKABLE_GATES` entry, no new suspension machinery.
9. **Auto-remediation of dependencies** — no Dependabot-style PR opening. Report only.
10. **Consumer-side artefacts.** `contract/gate-suspension.md` does not exist in this repo; do not create it here.

---

## 4. Spec interpretation calls, with reasons

**I-1 — "Implementer's call: flag or split" → I read the issue's own later clause as deciding it.** The issue offers `--skip-pip-audit` or two scripts, but then requires `run_gates.sh`'s auto-discovery to keep running both locally. Auto-discovery is file-based: a flag-only approach gives CI one script that must be invoked with a flag, while the local discovery path still runs the bundled script — leaving one code path where the two halves remain fused, and therefore one path where pip-audit's network dependency can still reach a context that forbids it. **Two scripts is the only shape that satisfies both clauses cleanly.** This is a ruling on observable behaviour (AC-8, AC-9, AC-11), not on file names.

**I-2 — NON-BINDING naming recommendation.** Keeping `security_scan.sh` as the bandit-only gate and adding a new repo-scoped dependency gate minimises churn: `security_scan` stays in `FILE_LIST_GATES`, keeps the `security` suspension key, and the #976 tests keep applying to the half that needs them. The alternative (new `bandit_*` script, `security_scan.sh` retains pip-audit) forces edits to two pinned test lists and four doc tables, and leaves the `security` key attached to the network-dependent half. The architect may overrule with a stated reason; if the key changes, AC-29 applies in full.

**I-3 — "Open or update a single tracking issue (idempotent)" is underspecified in the issue; AC-21..AC-25 are my construction of it.** The issue gives one word. I have read it as *zero writes on an unchanged set* rather than the weaker *no duplicate issue*, because the failure this protects against is notification fatigue: a weekly run that edits or comments every time trains the reader to ignore it, at which point the workflow reports to no one. I have also added AC-25 (failure ≠ zero findings), which the issue does not mention at all, because it is the same defect class as the one that motivated S-1 — reading an execution failure as a clean result.

**I-4 — The tracking issue overlaps #1504, and I accept the duplication.** #1504 already tracks these vulnerabilities, so the obvious alternative is to have the workflow comment on #1504. I rejected it: hardcoding an issue number into a workflow breaks the moment #1504 closes, and a closed #1504 with a workflow still commenting on it is worse than a duplicate. A ~~marker-identified~~ label-authenticated, marker-identified issue *(amended 2026-10-14 per AD-12a, pending human clearance)* is self-healing across the whole lifecycle (AC-24). The cost is two issues describing one problem, mitigated by AC-26's cross-reference, and resolved later by F-4.

**I-5 — Weekly over nightly (SHOULD, AC-17).** Dependency advisories do not arrive at a cadence that rewards daily polling, and AC-21's zero-write property means a nightly cadence costs nothing in noise — but it does cost seven times the Actions minutes and seven times the exposure to the AC-25 failure path. Weekly unless the architect has a reason.

**I-6 — I am not ruling on whether the workflow uses `gh` directly or `scripts/automation/lib/github.py`.** That is a technical-design question. The binding constraints are AC-18 (no App token minting), AC-27 (no `@path`), and AC-28 (unit-testable logic). CLAUDE.md's "use the code, don't roll it yourself" rule and the `label-swap.yml` plain-`gh` precedent point in different directions here; the tie-breaker is which one satisfies AC-28, and that is the designer's to assess.

---

## 5. Human Review Required

**RISK: MEDIUM — CONFIDENCE: HIGH**
**Change classification: ADDITIVE, with one item flagged STRUCTURAL-adjacent (S-1).**

Additive: this is a new requirements document for an issue already approved into v0.7.0; it fills a gap rather than changing approved behaviour.

**The one item a human should confirm — S-1.** Including the fail-open fix expands this PR beyond #1605's literal ask. The brief invited it, but a brief from the invoking worker is not human consent, and by my own rule a scope expansion that did not previously exist is structural regardless of size. I have ruled it **in scope** on the reasoning in S-1 (principally: a security gate that manufactures false green is a governance defect, and V-2 shows wiring it into CI *increases* exposure to it). **A human may reverse this**, in which case: the fix splits to a follow-up, the new CI job MUST be documented as non-load-bearing until that follows, and AC-14's debt-baseline entry MUST say so — do not let a known-toothless gate be recorded as zero-debt.

Two subsidiary calls a human may also want to see: **S-3** (deferring promotion to required despite a verified-clean baseline — conservative, reversible by instruction) and **I-4** (accepting a tracking issue that overlaps #1504).

Nothing here requires a human before `architect` proceeds; S-1's reversal would narrow scope, not invalidate the rest.

### Amendment 2026-10-14 — AD-12a/AD-12b alignment (AC-20, AC-20a, AC-26, I-4)

**RISK: MEDIUM — CONFIDENCE: HIGH**
**Change classification: STRUCTURAL.** The amendment adds a new repo label, a new operator obligation (do not remove the label), and a new fail-closed path (AC-20a), and it reverses AC-26's explicit "no new label". None of these was implied by the approved text. **Human clearance is required before the amendments become binding.** The original 2026-09-22 ruling is left visible above, and the amendments are marked pending.

**Process note, disclosed:** the implementation adopted the label on 2026-09-22 to close a HIGH security finding, before any spec document was amended. pm-agent is not ratifying that after the fact. On the requirements merits I support the change: AC-20's own purpose ("exactly one tracking issue, ever") cannot hold against a deliberate decoy under marker-only identity. As ADR §6 item 3 notes, the alternative to the label is author pinning (#1812 item 5), not "no label", because "no label" reopens the HIGH. But the decision is the human's.

**Effect on the 2026-09-22 process sign-off:** AC-20 and AC-26 stay orphaned (ADR §5) until a human clears this amendment. Until then, the implementation PR MUST NOT claim AC-26 conformance and MUST list this as an open discrepancy in its body. **Disclosure alone does not permit merge (clarified 2026-10-14):** human clearance of AD-12a/AD-12b gates the merge of the Part 2 implementation PR — it MUST NOT merge until that clearance is recorded in its PR thread. This design PR is not gated by that clearance (ADR §6 item 3; TD merge-gate banner). All other ACs are unaffected.
