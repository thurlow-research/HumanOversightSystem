# PANEL-1540 (S1 + S2) — dual-lens adversarial panel on the intake-trust-gate bundle

```yaml
verdict:                              findings
gate:                                 ADR-1540 §3(c) — the dual-lens adversarial panel #1540 mandates
bundle_sha256_16:                     438940549d2204cd
repo_head:                            da79b765
adversarial_cli:                      agy 1.2.3
adversarial_model_resolved:           gemini (agy 1.2.3 default; the CLI does not report a resolved ID)
adversarial_vendor:                   google — cross-vendor, independent of the bundle's authors
completeness_cli:                     claude (Agent tool, class alias `fable`)
completeness_model_resolved:          claude-fable-5-1
completeness_lens_rank:               4
bundle_author_rank:                   3 (opus — pm-agent, architect, technical-design)
completeness_lens_class_differential: true
per_bundle_consumption:               1 adversarial invocation (+1 void), 1 completeness invocation
findings_count:                       7 upheld (1 critical, 1 high, 2 medium, 3 low-cluster), 2 rejected
issues_created:                       none by this panel (see §5)
timestamp:                            2026-09-15T18:33:32Z
```

**Status: FINDINGS — `coder` is NOT cleared to build S1 or S2.**

This artifact is the §3(c) gate's output. It does not clear the gate; it reports what the gate
found. Two findings are blocking. One of them — reached **independently by both lenses** and then
confirmed by direct measurement against the live repository — means S2 as specified would make
**#1539 itself permanently unbuildable**, which is the issue this entire design exists to close.

---

## 0. How this panel ran, and what to distrust about it

**The panel's own invocation site does not exist.** ADR-033 AD-2 binds the dual-lens panel to
`scripts/run_spec_panel.sh`, which "runs both lenses, enforces fail-closed, and writes one
machine-readable artifact." TECHNICAL-DESIGN-033 §4.2 fully specifies it (Component C). **It was
never built**, no open issue tracks it, and so this panel — like ADR-035's before it — ran ad hoc,
by hand. That is precisely the condition D41 and ADR-033's own VF-1/VF-2/VF-3 were written about:
*a gate that exists only as agent prose is a gate that does not run.* This artifact is
hand-assembled evidence, not a gate's output. §5 records it as a follow-up.

**Lens coverage was asymmetric, and it matters when reading §1.**

- The **completeness lens** (`fable`, rank 4) read all five documents including all 1,363 lines of
  the technical design, and verified ~40 load-bearing claims against the repo's actual files. Its
  findings are well-grounded and its "verified sound" list is reproduced in §3.
- The **adversarial lens** (agy, cross-vendor) covered the ADR and both amendments well, but its
  reading of the technical design was demonstrably incomplete: two of its six findings assert
  absences that are contradicted by text present in that document (§2), and its own report header
  names only four of the five bundle documents. Measured rather than inferred: the prompt was
  496,689 bytes (~101k tokens by word count) and agy reported `input_tokens: 64377`. **Every agy
  finding below was therefore checked against the document before being credited**, and two were
  rejected outright.

**A first adversarial invocation returned `status: SUCCESS` with an empty response body** and a
denied `RunCommand` action — a non-review that a careless reader would record as "no findings". It
was re-run with tool use explicitly forbidden. Worth recording because it is the D41 failure mode
appearing inside the panel built to catch it. The shipped `run_second_review.sh` path is *not*
vulnerable to this specific shape: `salvage_review_json` rejects the envelope (it carries no
`verdict`/`findings`/`attacks` key), so the run degrades to `unparseable` → CONDITIONAL_PROCEED
rather than to a false clean review. Checked, not assumed.

**On the two lenses' verdicts.** Adversarial returned `DO-NOT-BUILD`; completeness returned
`CLEAR-WITH-CONDITIONS` while stating that its own C-1 "must be resolved in the TD … before `coder`
is cleared". Those are the same operational answer. §4 records the synthesis and why it lands where
it does.

---

## 1. Findings

Severity is the panel's, not either lens's. "New" means not on TECHNICAL-DESIGN-1540 §9's list
(A1–A7, T1–T3, R1–R10) — the bar §9 itself sets for a useful return.

| ID | Sev | Finding | Source | §9? | Status |
|---|---|---|---|---|---|
| **P-1** | **CRITICAL** | The 25-check authorization cap starves the tail of the queue in API order: ~⅓ of candidates are permanently unselectable whatever the human does — **including #1539 itself** | **Both lenses, independently** (A-3 + C-1) | **T1's exception — found** | **UPHELD, measured live** |
| **P-2** | **HIGH** | FR4 and AD-4/D5 specify opposite gates; REQUIREMENTS-1540 contradicts its own title; the design never cites FR4 at all | Panel synthesis | **NEW** | **UPHELD** |
| **P-3** | **MEDIUM** | `docs/OVERSIGHT-RUNBOOK.md` tells the human to authorize by adding `needs-ai` and is not in S2's change set — AM-15 binds it | Completeness (C-2) | **NEW** | **UPHELD** |
| **P-4** | **MEDIUM** | Consumer half-mechanism: `bin/hos-cron` ships to consumers; the modules it will now import do not | Completeness (C-4) | **NEW** | **UPHELD** |
| **P-5** | **MEDIUM** | Post-S2 `/approve` strips `needs-human` too — the issue becomes invisible to *both* queues | Adversarial (A-1) | Sharpens R5 | **UPHELD (increment)** |
| **P-6** | **LOW** | "The cutover material" and "the S2 work item" are undefined artefacts; AM-15's milestone-route prohibition has no documentation home and no pinning test | Completeness (C-3) | **NEW** | **UPHELD** |
| **P-7** | **LOW** | Correctness cluster: test homes, incomplete AM-17 application, a vacated test, unstated fail-closed contracts | Completeness (C-5…C-9) | NEW | **UPHELD** |
| — | — | S2 ignores reversal events (revocation resurrectable by re-label) | Adversarial (A-6) | R-3/AM-8 | **Narrowed to accepted residual** — see P-7(f) |
| A-2 | — | "`CLAUDE.md` dropped from the human's surface list; `.claude/agents/**` belongs to S5" | Adversarial | — | **REJECTED** (§2) |
| A-5 | — | "`ALL-CANDIDATES-GATED` never reaches the cycle log" | Adversarial | — | **REJECTED** (§2) |

---

### P-1 — CRITICAL. The authorization-check cap starves the queue's tail. #1539 becomes unbuildable.

**This is the exception §9/T1 asked the panel to find.** It is not an argument: both lenses reached
it independently from the documents, and the panel then confirmed it by measuring the live queue.

**WHERE:** TECHNICAL-DESIGN-1540 §2.2 (`--max-authorization-checks`, "default and ceiling: 25"),
§2.3 Step D ("per record, **in API order**"), D5.1, D6; §3 row F15; against Amendment 2 AF-6 /
AM-14 and §3(b) H1 item 2.

**THE DEFECT.** Step D walks candidates *in API order*. An author-trusted record takes D4 at **zero**
API cost; an untrusted-authored record takes D5 and spends **one** authorization check. The cap is
25 — both default and ceiling. D5.1 on exhaustion: *"skip this and every remaining untrusted record,
emit one stderr `WARN authorization-check-cap-reached`, and continue to Step E with what is already
eligible."* F15 accepts this as safe because a partial answer is a subset of the eligible set.

It is a subset of the **evaluated** set, which is not the same thing. Four properties compound:

1. **Priority ranking (D6) runs *after* D5**, so the cap is spent before priority is consulted.
2. **Step C's query has no `sort` parameter**, so API order is GitHub's default `created desc` —
   newest first. Oldest issues sit at the end.
3. **FR7 forbids caching**, so every cycle re-walks the identical list from position 0 and spends
   the cap on the identical records. The starvation is deterministic, not probabilistic.
4. **A round-robin cursor is foreclosed** by §5's "no state file, no memo".

**THE FAILURE — measured against `thurlow-research/HumanOversightSystem`, 2026-09-15:**

```
open, milestone=v0.7.0, labels=needs-ai, non-PR records:   96
  scottthurlow-claude[bot]   46   untrusted by authorship (AM-1 option C) -> D5, costs 1 check
  hos-worker-hos[bot]        30   D4 only if the title carries a machine-filing marker (AD-2)
  hos-overseer-hos[bot]      16   same condition
  ScottThurlow                4   author-trusted -> D4, free
```

Counting only the 46 human-proxy-authored records — the ones certain to take D5 — **the 25th falls
at list position 63.** The cap is exhausted there at the latest; unmarked worker- and
overseer-authored records spend it earlier still.

**`#1539` sits at list position 86, authored by `scottthurlow-claude[bot]`.**

So, following AM-14's lazy drain exactly as specified — the human primes the head by authorizing
#1539 via §2.7.4's remove-then-re-add act:

1. The gate queries; 96 records return, newest first.
2. It walks from position 0, spending one check per untrusted-authored record.
3. The cap is exhausted no later than position 63.
4. Positions 64–95 are skipped **without ever being evaluated**. #1539 is at 86.
5. `eligible = 0`; the gate exits 0 and emits `ALL-CANDIDATES-GATED`.
6. Next cycle: identical list, identical order, identical outcome. Indefinitely.

**Stated precisely, because the precise version is bad enough.** The repository is not *entirely*
stopped: an issue inside the cap's reach can still be authorized and selected normally. The defect
is that **every issue beyond the cap's reach is permanently unselectable no matter what any human
does** — today about a third of the queue — and that **#1539, the `priority:critical` issue this
design exists to close and the obvious first entry in AM-14's primed head, is inside that region.**
(#1540 is unaffected for a different reason: it carries `needs-human`, so it is outside the
candidate query entirely and D2 would exclude it regardless.)

**Three aggravating details the completeness lens supplied:**

- **The loud line misstates the cause.** §1.2's reason-token set is closed and Step F's
  `ALL-CANDIDATES-GATED reasons:` line has **no token for cap-skipped records**, and the text does
  not say whether they count toward `gated=<G>`. So the one signal AM-13 makes load-bearing either
  undercounts or reports starved issues as "held for human authorization" — the wrong reason.
- **The document argues both sides.** D5.3 justifies exiting 2 on a failed events query because
  *"a partial candidate list is a correctness hazard — it can silently demote a `priority:critical`
  item"* (F13 repeats it). D5.1 then presents a partial determination as complete with exit 0, and
  silently demotes a `priority:critical` item. The contradiction is internal to §2.3.
- **The cap has no FR and no AD.** AD-10's per-cycle cap is the *assessor's* (ESC-5). This one was
  introduced by the technical design, self-rated MEDIUM confidence and "not derived from
  measurement", and was never put to the human — while Amendment 2 §3(b) H1 item 2 tells the human
  the queue's true size "is knowable only by running the gate, which is what S2 ships". Under a cap
  of 25 the gate never evaluates the full set, so that assurance is not true as designed.

**WHY IT SURVIVED.** §9/T1 named the branch and asked for the exception; the reasoning under review
was that a subset is always safe. The premise that falsifies it — untrusted-authored records
outnumber the cap ~2:1 *and* sit ahead of the authorized ones — is a property of the live queue that
no document measured. AF-6 measured the queue's **size** (≥93) to price the human's effort; the same
measurement, turned ninety degrees, breaks the cap. §9/R8 asked whether the lazy drain is a sound
availability default; the answer is that it cannot function at all at cap 25 against a queue of 96.

**Not fixable by raising the cap.** 96 > 25 today and the queue grows; any fixed cap reintroduces
this the moment the queue passes it. The cap interacts with *order*, so a fix must change what the
cap skips — rank before checking, cap in priority order, a cap ≥ the 100-record page ceiling, or
something else. **The panel does not choose the fix**; it is an architecture decision, and because it
changes AD-3's error-exit refinement and AM-14's stated basis, it needs an architect ruling.

---

### P-2 — HIGH. FR4 and AD-4/D5 specify opposite gates, and the design never cites FR4.

**NEW — not on §9's list, and found by neither lens.** This is the class §9/R3 pointed at — *a claim
correct in the place nobody reads and wrong in the place the decision-maker reads* — surfaced by
reading the documents against each other, which is what the architect asked for.

**WHERE:** REQUIREMENTS-1540 title and FR4 (`:273-280`); ADR-1540 `:128` and AD-4 (`:164-186`);
TECHNICAL-DESIGN-1540 §2.3 Step D4/D5.

**THE DEFECT.** The conflict begins *inside the requirements document*, between its title and its
own FR4. The title:

> REQUIREMENTS-1540 — Request-intake risk assessment: **no untrusted-authored request becomes
> autonomous work without a documented assessment and an explicit CODEOWNER approval**

That is an **authorization** model: an untrusted-authored request *does* become autonomous work,
given a CODEOWNER's approval. FR4, 273 lines later, states an **origin-trust** model, with no
qualification or carve-out:

> **FR4 — Trust attaches to the request's origin, not to the last actor who touched a label.** The
> trust determination MUST be a function of the **issue author** as reported by the GitHub API.
> **A subsequent label, milestone, or metadata change by a trusted actor (human *or* bot) MUST NOT
> convert an untrusted-authored request into a trusted one.**

ADR-1540 `:128` restates FR4 as binding, in the architect's own voice — *"A trusted actor — human
**or** bot — relabelling an untrusted-authored issue does not convert it."* AD-4 is then headed
**"(BINDING — FR4, FR5, FR7.)"** and specifies the opposite:

> **For an untrusted-authored candidate** the gate MUST NOT accept "carries `needs-ai`" as
> authorization. … Instead the gate re-derives, live at selection time, that a **verified human
> CODEOWNER** authorized this specific issue.

The design implements AD-4: D4 makes author-trusted records eligible; **D5 makes untrusted-authored
records eligible on a CODEOWNER's `labeled`/`milestoned` event** — exactly the conversion FR4
forbids. **TECHNICAL-DESIGN-1540 never mentions FR4 anywhere** (zero occurrences in 1,363 lines), so
the conflict is unreconciled in the document the coder builds from. Neither amendment mentions FR4.

**THE FAILURE.** Two defensible readings of what S2 is, with no ruling between them:

- Under **FR4**, an issue authored by an anonymous member of the public can *never* become eligible,
  whatever a CODEOWNER does. Human approval is necessary but not sufficient.
- Under **AD-4/D5**, a CODEOWNER's label act makes it eligible, and the issue body then flows to
  pm-agent → architect → coder as the task specification.

The consequence is the one #1539 item 3 was written about: under D5, the only barrier between a
stranger's issue body and the build chain is one human's judgement at label-click time. FR4 was the
*structural* barrier; the design removes it while the ADR still asserts it. A reviewer checking the
built system against the requirements would find it non-compliant with FR4; against AD-4, correct.

It propagates operationally too: §2.7.4 instructs the human to perform, on 96 issues (92 of them not
author-trusted), precisely the act FR4 says must not confer trust.

**WHY IT SURVIVED.** AD-4's header *asserts* compliance with FR4 rather than reconciling with it,
and an assertion of that shape is not re-checked. The design inherited AD-4 without naming FR4, so no
pass ever had both sentences in view. Amendments 1 and 2 ruled E-1…E-7; none touched this.

**What the panel is NOT saying.** Not that FR4 is right and AD-4 wrong. FR4 as literally written may
be unimplementable alongside the human's #1539 ruling ("no work happens without approval from the
designated human"), which is an authorization model. **The defect is that both are on the books as
binding and the build document cites neither.** It needs a pm-agent/architect ruling — amend FR4, or
narrow D5 to require author-trust **and** CODEOWNER action — before a coder builds either.

---

### P-3 — MEDIUM. The operator runbook teaches the authorization act S2 invalidates, and is not in the change set.

**NEW.** AM-15 binds: *"The cutover material (**and anything else that tells the human how to
authorize an issue**) MUST state the act in a form that is correct under both resolutions of §0.6
gap 6."* AM-1 consequence 1: *"Any tooling or documentation that offers `edit_issue.sh --app human`
as the approval path is wrong and must not be written."*

**WHERE:** `docs/OVERSIGHT-RUNBOOK.md:70-75` (verified directly); TECHNICAL-DESIGN-1540 §2.1, §4.3
(the complete edited-file lists), §6.3.

**THE DEFECT.** The runbook's "Intervening" section reads:

> **`needs-human` ⇄ `needs-ai` handoff** — the normal channel. The overseer escalates a PR by
> labeling its issue `needs-human`; you respond by **removing `needs-human`, adding `needs-ai`**, and
> commenting your decision. Agents treat the `needs-ai` label (not a bare comment) as the resume
> signal.

Post-S2 that is wrong in the specific way AM-1 forbids. On an issue that **already carries**
`needs-ai` — which is every issue in the cutover set — "adding `needs-ai`" is a no-op that emits no
`labeled` event and authorizes nothing. The file appears in **no** list in §2.1, §4.3 or §6.3; the
three `test_labels_doc_*` conformance tests pin `docs/LABELS.md` only.

**THE FAILURE.** A human follows the runbook, believes they released the issue to the worker, and
the issue stays gated with no signal — "a gate whose documented approval path silently does nothing",
which AM-1 names as worse than no gate. The wording is *right* in TECHNICAL-DESIGN-1540 §2.7.4 and
*wrong* in the document an operator actually opens.

**A factual correction that travels with it.** §9/R5's third stated reason for leaving `/approve`
live is that it "is referenced by the runbook's intervention procedure". The completeness lens
checked: **the runbook contains no `/approve` literal at all** — it describes the manual label swap,
not the slash command. One of R5's three load-bearing reasons is not true, which matters because R5
is a judgement call the architect declined to overrule on the strength of those reasons.

---

### P-4 — MEDIUM. Consumer half-mechanism: `bin/hos-cron` ships; the modules it will import do not.

**NEW.** This is the "consumer built, producer absent" class the repo has hit repeatedly (ADR-035
AD-15; #1128, #1131) — here inverted, and pointed at consumer deployments rather than this repo.

**WHERE:** `scripts/framework/framework_consumer_files.txt` (verified: `bin/hos-cron` at line 20;
`scripts/framework/require_human_approval.py` individually listed at line 67);
`bootstrap/hos_install.sh` `enumerate_framework_files`; TECHNICAL-DESIGN-1540 §2.1, §4.3.

**THE DEFECT.** The installer's ship-set is an **explicit list**, and `scripts/framework/` modules
are enumerated one by one — `require_human_approval.py`, the very module `requester_trust.py` will
import, is the standing precedent. S2 adds `scripts/framework/select_work_candidates.py`,
`scripts/framework/requester_trust.py` and `scripts/framework/trusted-requesters.txt`, and **adds
none of them to that list.** The existing guard test only checks that *listed* files exist — it
cannot detect a listed file whose dependency is unlisted.

**THE FAILURE.** A consumer upgrading to a release carrying S2 receives the new `bin/hos-cron`, whose
candidates block runs `python3 -m scripts.framework.select_work_candidates` against a tree that does
not contain it. `ModuleNotFoundError` → `_gate_candidates_ok=0` → no new work, every cycle. It fails
closed, and DEV-2 makes the traceback visible — but it is a bare Python traceback with **no
`$LOG_PREFIX` and no `ALL-CANDIDATES-GATED` token**, so the one operator-legible line §2.4 adds never
fires. Every consumer worker stops selecting work with only a raw stderr trace as the signal.

**A second, quieter half of it:** `trusted-requesters.txt` is a **consumer-maintained** file living in
an **HOS-owned** tree (`scripts/framework/**`). The design does not say whether an upgrade preserves
or overwrites it. Overwrite fails closed, but silently removes every trusted contributor the consumer
added.

---

### P-5 — MEDIUM. Post-S2, `/approve` removes `needs-human` too: the issue goes invisible to both queues.

**Sharpens §9/R5 rather than replacing it.** R5 records that `/approve` is left live and is *actively
harmful* — it consumes the human's additive act as `github-actions[bot]`. The increment is what
happens to the issue's **visibility**, which R5 does not cover.

**WHERE:** `.github/workflows/label-swap.yml:74` (read directly); TECHNICAL-DESIGN-1540 §2.7.2, §4.3,
§6.3; §2.3 Step D2.

**THE DEFECT.** The `/approve` branch is one edit doing both halves:

```bash
gh issue edit "$ISSUE_NUMBER" --remove-label "needs-human" --add-label "needs-ai" 2>/dev/null || true
```

Post-S2, a CODEOWNER typing `/approve` therefore produces an issue that **has** `needs-ai` (applied
by `github-actions[bot]`, so correctly gated) and **has lost** `needs-human` — so it no longer
appears in any `needs-human` listing a human uses to find work awaiting them. The issue is
simultaneously not-actionable by the worker and not-visible to the human. R5's stated failure is *"a
human believing they authorized work while having made authorizing it more expensive"*; the sharper
version is that the issue also **leaves the queue where the human would notice it needed anything**.
The shipped mitigation is wording (§2.7.2/§4.3, pinned by §6.3), which corrects the confirmation
comment's false "authorized by" claim but restores the issue to neither queue.

**WHY IT SURVIVED.** AF-5 and AM-6 examined the *actor* of the added label — the authorization
question. The removed label is on the same line and is a visibility question, so it fell between the
two lenses that looked at it.

---

### P-6 — LOW. Undefined artefacts: "the cutover material", "the S2 work item"; AM-15's prohibition has no home and no test.

**NEW.** From the completeness lens (C-3).

- **"Cutover material"** is used eleven times across the design and both amendments (TD `:695`,
  `:759`, `:1259`; AM-15 throughout) and is **never defined** — not a file in §2.1, not a PR body,
  not an issue comment. §2.7.4 specifies verbatim wording and then names no place to put it.
- **"The S2 work item"** must carry residuals R-1, R-3 and R-7 (§7.2) and is **never identified**.
  H6 asks the human to confirm "S2 is the fix that closes #1539", so the identity is pending — but
  the design does not say "when H6 is answered, the work item is that issue and the residuals are
  posted there". Residuals can be lost between "recorded here" and "recorded in the work item".
- **AM-15's milestone-route prohibition has no durable landing site.** AM-15 binds that the milestone
  route "MUST be documented as **not a cutover route**, with the Step 0 race as the stated reason".
  §4.3's `docs/LABELS.md` requirement enumerates four statements plus the churn sentence; **none is
  the prohibition**, and none of §6.3's `test_labels_doc_*` tests pins it. Amendment 2 §3(b) H1 item 2
  carries it, but H1 is one-shot clearance text, not persistent documentation.

**Why it matters more than "LOW" suggests:** the design's own failure-mode (ix) is "the milestone
route creeping back in as a suggestion". That is the prohibition with no test and no home.

---

### P-7 — LOW. Correctness cluster.

From the completeness lens (C-5…C-9), each verified against the repo. Absorbable by the coder with
design guidance; listed so none is silently dropped.

**(a) Test homes are missing for the `hos-cron`-side tests.** §6.2 says "one test per row F1–F30 …
each drives the CLI with a stubbed `gh`", but **F25** (`python3` missing), **F30** (the `$LOG_PREFIX`
cycle-log line) and **AM-12's binding
`test_bounced_draft_pr_still_reaches_the_worker_and_blocks_the_skip`** all exercise `bin/hos-cron`,
not the CLI, so they cannot live in `test_select_work_candidates.py`. A harness exists —
`tests/automation/test_hos_cron.py`, which runs the real script with `claude`/`gh` stubs — and the
design never names it as modified. A coder can satisfy "one test per row" for the CLI rows and
silently drop the three, **one of which is the condition DEV-1's approval hangs on**. Separately,
**F26** is an LLM behaviour; only the prompt string is pinnable, so "one test per row" over-claims
for it. And §6.3's sandbox-allowlistable test asserts on the line *after* `_build_prompt`'s
`@@MILESTONE_NUMBER@@` substitution — `_build_prompt` is a bash function inside `hos-cron`, and how
the test obtains the rendered prompt is unspecified.

**(b) AM-17 was applied incompletely to the base ADR.** ADR-1540's own "Human Review Required"
BLAST RADIUS (`:394`) still reads **"Four protected surfaces."** AM-17 corrected AD-14 inline and
Amendment 1's BLAST RADIUS, but not the ADR's closing block — **the block a human reads.** This is
the *same class* as the E-6 error it was issued to fix, one document further up, and it is live
against the design's own failure-mode (x).

**(c) Dangling citations.** Amendment 2 §0 cites `GH_TOKEN` at `label-swap.yml:66` (actual `:36`;
`:66` is the CODEOWNERS membership test). TD §2.1 cites "`:83`'s `/decline` sibling" (the write is
`:79`). TD §6.1 says "the nine shipped `probe.py` cases" for `verify_codeowner_actor` (there are
eight, `:468-529`). `_milestoned_event` is `:465`, not `:466`.

**(d) A test goes vacuous.** `test_skips_issue_with_no_verified_codeowner_actor`
(`test_probe.py:318`) builds `_make_issue(100, …)` with no `milestone` object, so under AM-18's
retained skip rule the record is dropped **before** `_verify_codeowner_actor` and `results == []`
passes for the wrong reason. The test stops exercising its stated subject while satisfying the
design's replacement criterion. The shared `_make_issue()` fix covers it — but a coder who inlines
fixtures only for the four *failing* tests leaves this one vacuous. It is not among the five named.

**(e) Unstated fail-closed contracts.** F4 implies an unreadable `machine-accounts.env` collapses to
"empty"; F3/F7 make an unreadable CODEOWNERS/roster *propagate* (`config-error` / `roster-unreadable`).
§1.3 specifies only "missing file → empty set" for `load_trusted_apps` and nothing for
`load_bot_accounts`. Both directions fail closed; the contract is simply not written down.
Separately, **FR8's verify clause** ("a test enumerates the selection paths and asserts agreement")
has no corresponding test — §6.3 asserts reference counts, and nothing asserts that `probe.py`'s
milestone strategy and the gate reach the same negative verdict on the same fixture.

**(f) The reversal-event residual (adversarial A-6), narrowed.** S2 ignores `unlabeled`/`demilestoned`
events, so a stale human `labeled` event still authorizes if the dispatch label is later re-added.
The lens asserted this is reachable today via `merge_authority.py:1068`; **that is false** —
`merge_authority.py` contains no occurrence of `needs-ai` at all (verified). Both the panel's and the
completeness lens's independent enumerations found the only site adding the dispatch label to an
*existing* issue is `label-swap.yml:74` (`/approve`, human-triggered, non-authorizing post-S2); every
other writer is creation-time or PR-side. A human revoking also normally applies `needs-human`, which
D2 excludes outright. So the residual is real but **currently unreachable**, consistent with AM-8's
decision to accept it for S2 and close it in S3. Recorded so the acceptance carries its reachability
argument — which is exactly the "in this repo, today" qualifier §9/R9 warns decays.

**(g) A premise the design adopts without noting the contradiction.** §2.5 asserts the current Step 2
fallback "on an unattended cycle … is **denied outright and silently skipped**", citing `CLAUDE.md`.
But `bin/hos-cron:1764` launches `claude --print --permission-mode bypassPermissions`, commented
"bypassPermissions clears the approval gate so the agent can run gh/git/bash unattended." The two
repo sources disagree and the design adopts one silently. No design consequence either way — but
AM-11's acceptance justification ("the failure this test prevents is invisible at runtime by
construction") rests on the unreconciled premise.

---

## 2. Rejected findings

Recorded because a rejected finding is information about coverage, and because both were presented
at HIGH/MEDIUM by the adversarial lens.

**A-2 — "`CLAUDE.md` was dropped from the human's five-surface list; `.claude/agents/**` belongs to
S5, not S1/S2." REJECTED on both halves.** `.claude/agents/worker.md` **is** modified by S2 —
§2.1 lists it as `modified (:179, :271)`, removing its references to the deleted `next_candidates.jq`.
And `CLAUDE.md`'s exclusion is not an omission: AM-17 ruled the count is five, not six, and
*explicitly requires the human be told the sixth surface exists as a deliberately-excluded planned
follow-up* (Amendment 2 §3(b) item 4's closing paragraph). Both the panel and the completeness lens
independently verified all five surfaces against `scripts/framework/protected_surfaces.txt`; all five
are present, and the new roster file is covered by `scripts/framework/**` — which is what makes the
count five rather than four.

**A-5 — "`select_work_candidates.py`'s stderr is lost because command substitution captures only
stdout, so `ALL-CANDIDATES-GATED` never reaches the cycle log." REJECTED — the design already does
exactly what the finding demands.** §2.4 specifies:

```bash
if _GATE_CANDIDATES=$( (cd "$REPO_ROOT" && python3 -m scripts.framework.select_work_candidates ...) 2>"$_gate_err" ); then
...
cat "$_gate_err" >&2                                    # DEV-2: nothing is swallowed
if grep -q 'ALL-CANDIDATES-GATED' "$_gate_err"; then    # AM-13 point 3
  echo "$LOG_PREFIX ALL WORK CANDIDATES GATED — ..."
```

stderr is redirected to a file, echoed, and grepped into the cycle log. The finding describes an
implementation the design does not propose. With A-2, this is the concrete evidence in §0 that the
adversarial lens's reading of the technical design was incomplete.

---

## 3. Verified sound

Load-bearing claims checked independently against the repository and found correct. This matters as
much as the findings: it records what was actually covered. Items marked **‡** were verified twice,
by the completeness lens and by the panel separately.

| Claim | Verdict |
|---|---|
| The five protected surfaces are real and complete for S2's file list **‡** | **Sound** — each checked against `protected_surfaces.txt`; the roster lands under `scripts/framework/**`, which is the fifth |
| `bin/hos-cron`'s live selection path has no actor check (#1539's premise) | **Sound** — `:1136-1137`, `state+milestone+labels` only; nothing reads `.user` |
| AF-5 — `/approve` writes as `github-actions[bot]` **‡** | **Sound** — `label-swap.yml:36` `GH_TOKEN: ${{ github.token }}`; `:74` the write; `:29` no label-state precondition |
| AM-15's window claim — `/approve` is the only site adding the dispatch label to an *existing* issue **‡** | **Sound as of today** — every scripted writer enumerated; `merge_authority.py:633`/`:1223` are PR-side, `self_review_source.py:229` and the agent prompts are creation-time, Step 0 is milestone-less-scoped |
| S2 subsumes the Step 0 self-triage half of #1539 (the H6 question) | **Sound** — F19 gates a worker-bot-applied label regardless of Step 0's routing; §2.5's AD-7 note records that the gate's correctness does not move when Step 0 changes |
| AD-2's machine-filing marker enumeration | **Sound** — six `gh issue create` sites in `bin/hos-cron`; title prefixes match the marker table byte-for-byte; `review_self.sh:294` and `self_review_source.py:192` match |
| Team entries in CODEOWNERS cannot silently widen trust | **Sound** — tokens containing `/` are skipped and an all-team CODEOWNERS exits 2 `codeowners-empty` (F2) |
| A bot in CODEOWNERS or the roster cannot confer requester trust | **Sound** — F22, plus the roster parser's `[bot]`/`BOT_ACCOUNTS` rejection |
| The cutover set is ≥93 (AF-6) | **Sound** — measured 96 by the panel; AF-6's floor holds |
| `tests/automation/test_next_candidates.py` is handled on deletion of the `.jq` | **Sound** — §4.2 ports nine cases and inverts `test_filter_file_exists` to `test_next_candidates_jq_is_gone` |
| §4.3's `next_candidates` reference inventory is complete | **Sound** — matches a repo-wide grep; remaining hits are historical docs, the deleted test file, and TD-1604 (orphaned by AM-9) |
| Revision 3's coverage map (AM-14…AM-18) is honest | **Sound** — every ruling traced to the sections named; AM-15's instruction appears verbatim in §2.7.4; AM-18's diagnostic in §1.6/D5.2/F17; revision 2's AM-1…AM-13 map likewise resolves |
| `hos-cron` integration assumptions (`_REPO_SLUG`, `LOG_PREFIX`, `@@MILESTONE_NUMBER@@` substitution, the `:1158` skip condition) | **Sound** — each located; AM-12's test is satisfiable as §6.2 argues, since `_OPEN_PR_NUMS` comes from `/pulls` independently |
| Cross-ADR amendments were actually applied | **Sound** — ADR-1604 AD-5/AD-9 and ADR-1542 G11 are struck with AM-9/AM-10/AM-11 markers in place |
| AM-18's new `probe.py` stderr surface is safe | **Sound** — `multi_customer.py` invokes `probe_repo` in-process without capturing stderr |

---

## 4. Verdict

```
PANEL-VERDICT: DO-NOT-BUILD
```

`coder` is **not** cleared for S1 or S2.

**Synthesis of the two lenses.** Adversarial returned `DO-NOT-BUILD`; completeness returned
`CLEAR-WITH-CONDITIONS` while attaching the condition that *"C-1 must be resolved in the TD (and …
likely with an architect ruling) before `coder` is cleared."* Those are the same operational answer
stated at different strengths, and the panel takes the stronger one for a reason that is not a
tie-break: **P-1 is not a documentation defect that a revision can absorb.** It is a functional
defect that, on measured live data, makes the `priority:critical` issue this design exists to close
permanently unbuildable by the mechanism the design ships. A revision cannot state its way out of
that; the algorithm has to change.

- **P-1 — blocking.** Needs an architect ruling on evaluation order and/or cap semantics. It changes
  AD-3's error-exit refinement and AM-14's stated basis, so it is not the design's to settle alone.
- **P-2 — blocking.** The requirements document and the design specify different gates, and the
  design cites neither of the two conflicting statements. A coder building from it produces a system
  that fails its own FR4. Needs a pm-agent/architect ruling on which model governs.
- **P-3, P-4 — not blocking, but change-set additions that belong in the same revision** (§2.1, §4.3,
  §6.3). P-4 in particular is invisible from this repo: it only fails in consumer deployments.
- **P-5 — not blocking**; one line in a file S2 already edits.
- **P-6, P-7 — absorbable by the coder** with design guidance, except P-7(b), which is a one-line
  correction to the ADR block a human reads and should be made before H1 is put to them.

**The three gates outstanding before this panel remain outstanding**, and this panel clears none of
them: §3(b) **H1** (ESC-6, using Amendment 2 §3(b)'s replacement text), §3(b) **H3** (ESC-2), and
§3(c) — **this gate, now answered with findings rather than cleared.**

**One sequencing note for whoever resolves P-1 and P-2.** H1 asks the human to clear a change set
whose cost is stated as ≥93 issues × 2 acts. If P-1's resolution changes evaluation order or the cap,
and if P-2's resolution narrows D5, **both change what H1 is actually asking for** — and P-4 adds
files to the change set H1 enumerates. **H1 should not be put to the human until P-1, P-2 and P-4 are
ruled**, or the human will clear a design that no longer exists. That is the same failure AM-17
corrected when Amendment 1's four-surface text would have reached them.

---

## 5. Follow-ups this panel did not file

Recorded, not filed — filing is the intake path, and this artifact is the panel's output. A human or
a later cycle should decide each.

1. **`scripts/run_spec_panel.sh` does not exist**, though ADR-033 AD-2 binds it as the single
   deterministic invocation site for this gate and TECHNICAL-DESIGN-033 §4.2 fully specifies it
   (Component C). Every dual-lens panel run to date — ADR-035's and this one — has been ad hoc prose.
   No open issue tracks it. This is D41's own failure class sitting inside the mechanism built to
   catch it, and it is squarely within epic **#1643**'s scope ("every review dimension enforced in
   code … no step ever discretionarily skipped").
2. **An agy invocation can return `status: SUCCESS` with an empty response body** when it attempts a
   denied tool action (§0). `run_second_review.sh` degrades safely via `salvage_review_json`, but any
   *new* caller reading the envelope without that guard would record a non-review as a clean review.
   Worth a shared guard before a second caller lands.
3. **FIND-2 is only half-fixed (completeness C-6).** §0.3 identifies **both** `_verify_label_actor`
   and `_verify_codeowner_actor` as unpaginated; AM-5 and §1.6 paginate only the latter. The consumer
   coordination strategy keeps the availability defect the design itself diagnosed. Related: FR6's
   "a search finds no second implementation of the membership test" — `_verify_label_actor`'s
   `requester_allowlist` check remains a second, differently-shaped membership test; §1.4 notes the
   semantic difference but never records the scope boundary that keeps it outside FR6.
4. **#1696** already covers landing the duplicate-`labeled`-event scan in `scripts/` with a test;
   §9/R1 notes the panel could not re-run the evidence it was handed. No new issue needed.

---

**Provenance:** dual-lens adversarial panel, autonomous worker cycle, 2026-09-15.
Adversarial lens: agy 1.2.3 (google — cross-vendor, independent of the bundle's authors).
Completeness lens: `fable` class, rank 4, a strict differential over the bundle's rank-3 authors.
Panel synthesis, verification of every lens finding against the bundle and the repository, P-1's
live measurements, and P-2: this session (`claude-opus-5`).

**Nothing in this artifact authorizes a merge, a protected-surface edit, or a line of code.**
