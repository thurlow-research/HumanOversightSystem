# PANEL-1540 (S1 + S2) — dual-lens adversarial panel, **THIRD RUN**, against technical-design revision 5

```yaml
verdict:                              DO-NOT-BUILD
non_convergence:                      YES — this IS the 5-of-5 under the CORE cap (AMENDMENT-4 §0.0.1)
escalates_to:                         human, with the count and the sticking point. THERE IS NO ROUND 6.
secondary_verdict:                    the gate's adversarial half was ALSO instrument-compromised (TP-0)
gate:                                 ADR-1540-AMENDMENT-4 §3(c) — the bound third run
supersedes:                           none (run 1 and run 2 stand as written)
bundle_sha256_16:                     2b9e63ad2264d808
bundle_contents:                      ADR-1540-AMENDMENT-4 + REQUIREMENTS-1540-AMENDMENT-2 + TECHNICAL-DESIGN-1540 rev 5
bundle_bytes:                         792961
bundle_lines:                         3383
repo_head:                            cf37b8bb
adversarial_cli:                      agy 1.2.3
adversarial_vendor:                   google — cross-vendor, independent of the bundle's authors
adversarial_invocation:               scripts/oversight/lib/vendor_invoke.sh (ADR-1683 D-1/D-2), stdin
adversarial_pass_A:                   FULL BUNDLE, SINGLE SHOT — **INVALID, SILENTLY TRUNCATED AT ~34%**
adversarial_pass_B:                   CHUNKED re-read of the material pass A never received
completeness_cli:                     claude (Agent tool)
completeness_model_resolved:          claude-fable-5-1
completeness_lens_rank:               4
bundle_author_rank:                   3 (opus — pm-agent, architect, technical-design)
completeness_lens_class_differential: true
orchestrator_rank:                    3 — SAME RANK AS THE BUNDLE'S AUTHORS (independence limitation)
timestamp:                            2026-09-16T18:20Z
```

**Status: DO-NOT-BUILD. `coder` is NOT cleared to build S1 or S2.**

**Two things are true at once and the artifact would be dishonest if it reported only one.**

1. **A blocking design defect was found and confirmed at the line — TP-4.** Two §6.2 tests that
   revision 5 makes *binding* are **mutually unsatisfiable on the exact fixture one of them
   mandates.** A coder cannot implement Step E and pass the suite as written. Three further
   findings (TP-1, TP-2, TP-3) are confirmed defects, one of them a zero-privilege denial of
   service on all autonomous work.
2. **The gate's adversarial half did not run as specified — TP-0.** The cross-vendor lens
   silently received ~34% of the bundle and reported success. So **this finding set is a floor,
   not a ceiling**, and the coverage it represents is materially less than three runs of this
   gate should have produced.

**Per `ADR-1540-AMENDMENT-4` §0.0.1 this DO-NOT-BUILD IS the 5-of-5 non-convergence.** §5
carries the escalation with the count and the sticking point. **It does not become round 6.**

**The one thing a reader should not take from this.** The sticking point is **not**
architectural disagreement. AM-29's separation of the two orders is sound and survived attack;
what failed is the *expression* of it in two test descriptions that contradict each other, and
a sort key nobody noticed the public can write. **Both have remedies already present in this
chain.** §5.2 says so plainly, because a non-convergence escalation that does not distinguish
"the architecture is wrong" from "two paragraphs disagree" wastes the human's decision.

---

## 0. How this panel ran, and the thing it found out about itself

### 0.0 The primary result of run 3 is about the gate, not the design

**The cross-vendor adversarial lens silently reviewed about a third of what it was given and
reported success.**

Pass A was the run as specified: the whole revision-5 bundle (792,961 bytes, 3,383 lines) to
`agy` on stdin through `scripts/oversight/lib/vendor_invoke.sh`, the sanctioned primitive. It
returned `status: SUCCESS`, `num_turns: 1`, 11,810 response characters, exit 0, in 192s. By
every check the tooling performs, it worked.

**It did not work.** `usage.input_tokens` came back as **67,117** for an 806KB prompt — about
12 bytes per token, where English prose is ~4. That is a three-fold discrepancy, so I tested it
rather than reasoning about it.

**The test.** I rebuilt the identical bundle with three sentinel tokens planted in it — one at
the start, one at the exact midpoint (after line 1,691 of 3,383), one at the very end — and
asked agy only to echo back the ones it could find:

```
SENTINEL-ALPHA-7Q2M      <- start       FOUND
MISSING                  <- midpoint    NOT RECEIVED
MISSING                  <- end         NOT RECEIVED
```

`status: SUCCESS`, `input_tokens: 68,359`. **The lens never reached the midpoint of the
bundle.** At ~4 bytes/token the consumed prefix is ≈273KB of 793KB — **about 34%**.

**What that means for pass A, concretely.** The bundle is ordered `ADR-1540-AMENDMENT-4`
(100,938 B) + `REQUIREMENTS-1540-AMENDMENT-2` (49,250 B) + `TECHNICAL-DESIGN-1540` rev 5
(642,773 B). A 273KB prefix covers **both amendments in full** and then roughly **the first
19% of the technical design** — its header, §0.0 revision history, and part of §0.6/§1.

**The adversarial lens never saw §2 (the algorithm), §3 (the fail-closed matrix), §6 (the
tests), §7 (the residuals), §8 (the escalations) or §9 (the attack surfaces it was being asked
to attack).** Five of the six binding coverage items live entirely in text it never received.

**And it produced confident, well-formed findings citing those exact sections anyway** — "TD
§2.3 Step D5.3", "§3 rows F34–F37", "§8/E-9", "§6.2". Those citations came from **the prompt
preamble I wrote**, which summarised each attack item. The lens reconstructed plausible design
text from a description of it. **This is the failure mode the run-3 instructions were written
against — *"a gate output that cannot say what it read is not evidence"* — arriving from a
direction nobody in this chain anticipated: not a lens that declined to say, but a lens that
could not have known.**

**Worked example, because the abstract version understates it.** Pass A's F1 (HIGH) argued that
`probe.py`'s `try/except GitHubError: return None` collapses "query failed" into "no CODEOWNER
found", making D5.3's `unevaluated:query-failed` quarantine unreachable. The citation is
genuine — `probe.py:298-303` appears five times in Amendment 4, which the lens *did* read in
full, and I confirmed the code at the line. **But the finding is wrong, and the text that
refutes it is at TD §2.3 D5.2–D5.3, which the lens never received:** the gate does not call
`probe.py`'s wrapper. D5.2 performs the fetch (where a transport failure is caught and routed
to D5.3.1's quarantine) and D5.3.2 then calls `verify_codeowner_actor(events, …)` — a **pure
function over already-fetched events**, whose `None` means only "no qualifying actor". The two
states are separated by construction. **A finding that looks like a HIGH against the design is
actually a HIGH against the instrument.**

### 0.1 How the verdict was reached, including the draft I discarded

Amendment 4 §0.0.1 binds the exit condition verbatim: *"if this third run returns
DO-NOT-BUILD, that IS the 5-of-5 non-convergence and it escalates to the human with the count
and the sticking point. There is no round 6."*

**I drafted a different verdict first and discarded it, and the record is worth more than the
tidier version.** After pass A failed and its findings were refuted, I drafted
`GATE-NOT-DISCHARGED` — a third category meaning *the instrument broke, so the gate did not
validly run; re-run it, and do not count this as the 5-of-5.* The reasoning was that a DO-NOT-
BUILD would assert a design defect I had not established, and would spend the chain's last
round on a tooling fault.

**Then pass B found one.** TP-4 is a confirmed, blocking, document-internal defect, verified by
me at `TD:1934` and `TD:1936`, and TP-1 is a confirmed zero-privilege DoS whose premise I
verified against live GitHub. **The premise of my draft verdict — "no design defect
established" — became false, so the verdict built on it had to go.**

I am recording this because the discarded draft is exactly the move this chain has twice
criticised: **a self-assessed exemption that happens to relieve the assessor of the costly
outcome.** I had an interest in `GATE-NOT-DISCHARGED` — it avoids ending the chain on my watch
— and I reached for it before the evidence was in. It was the right call on the evidence I had
and the wrong call twenty minutes later. **The lesson is the one standing instruction 3 already
states: check before crediting, including when the thing you are crediting is your own
verdict.**

**What survives from that draft, because it is still true:** the instrument failure is real,
independently critical, and means this run **under-reviewed** the design. That is reported as
TP-0 and filed as **#1718** — but it is now a qualifier on a DO-NOT-BUILD, not a substitute for
one.

### 0.2 What each lens actually read — the requirement, answered precisely

| Lens | Received | Verified how |
|---|---|---|
| **Adversarial, pass A** (agy 1.2.3, google) | **≈34% of the bundle**: both amendments in full, TD rev 5 to ≈line 510 of 2,684. **No repo access, no tool calls.** | Three-sentinel probe, §0.0 |
| **Adversarial, pass B** (agy 1.2.3, chunked) | TD rev 5 lines **450–2,684** in four overlapping contiguous slices, each sized well under the observed limit, each with a standing context header. **No repo access.** | Per-chunk `input_tokens` recorded in §3 |
| **Completeness** (claude-fable-5-1, rank 4) | **Full repo access.** Read all three bundle documents from disk — no CLI, therefore no truncation path — plus repo files at line level, plus live GitHub reads via `bootstrap/query_issues.sh` | Its own verification table, §4 |
| **Orchestrator** (this session, rank 3) | Everything, plus five independent live measurements neither lens could make | §2 |

**Pass B is a degraded mode and I am not going to pretend otherwise.** Chunking destroys the
single most productive technique both prior runs relied on — *reading the documents against
each other* — because no chunk sees the whole. It is strictly better than 34% and strictly
worse than the gate as designed.

### 0.3 What to distrust in this artifact

1. **The orchestrator is rank-equivalent to the bundle's authors** (both opus) and wrote this
   synthesis. The class differential that makes the completeness lens independent does not
   apply to me. Unchanged from run 2 and still true.
2. **Pass A's seven findings are not evidence about the design** and are not carried as
   findings. They are carried in §3 only as *exhibits of the instrument defect*.
3. **Pass B's chunks cannot catch cross-document contradictions**, which is where four of the
   prior runs' best findings came from.
4. **I chose the chunk boundaries**, and a defect straddling one could be missed by both
   adjacent chunks. The 60-line overlap at the first boundary is a partial mitigation, not a
   guarantee.
5. **Run 1's and run 2's verified-sound claims were not re-derived**, per Amendment 3 §3(c) and
   Amendment 4 §3(c). If one was wrong, this run did not catch it and was instructed not to try.

---

## 2. The orchestrator's measurements — five things neither lens could check

Amendment 4 §0.1 item 1 declares outright: ***"No live GitHub read was performed this
session… I did not re-measure, and a reader should know the numbers in this document are
inherited."*** The design's own §0.0.4 figures carry the provenance *"worker, measured
2026-09-16T~15:55Z. Not re-derived by me."* **So every load-bearing number in this bundle was
inherited by at least one author who says so.** Re-deriving them independently is the one
contribution available to me that neither lens can make, and standing instruction 3 — *check
every finding against the line before crediting it* — applies to a design's own measurements
as much as to a panel's findings.

### M-1 — the population figures: **CONFIRMED, with drift**

I re-ran Step C's own query (`state=open&milestone=2&labels=needs-ai`, paginated, PR records
excluded per #1236) at 2026-09-16T~18:10Z:

| Claim (TD §0.0.4) | Design's figure | **Measured independently** | Verdict |
|---|---|---|---|
| Candidate population | 101 | **102** | **Confirmed, +1 drift in ~2h** |
| `updated_at` present and non-null | 101/101 | **102/102** | **CONFIRMED** |
| `updated_at` values all distinct | all 101 | **102 of 102 distinct** | **CONFIRMED** |
| `user.login` present | 101/101 | **102/102** | **CONFIRMED** |
| Also carrying `needs-human` | 0 | **0** | **CONFIRMED** |
| Milestone 2 resolves to | `v0.7.0 — Quality` | **`v0.7.0 — Quality`, 102/102** | **CONFIRMED** |

**AM-29's primary binding `(rank, updated_at DESC, number ASC)` therefore applies and the
`(rank, number DESC)` fallback is not triggered** — now on an observation rather than on an
inherited one. Amendment 4's own §0.1 item 2 flagged this as asserted-not-observed and bound
the designer to verify; the designer did, and **I have now re-derived it from a third
independent read.**

**The drift is worth one line, because it is the direction that matters.** Amendment 4 reasoned
from 97/98; the designer measured 101; I measure 102. The population is **growing**, and it is
already above the ≈100-request cycle ceiling. AM-30's arithmetic is insensitive to a few
records, as it says — but the gap between population and ceiling is the thing R-8's
reachability trade rests on, and it is widening, not closing.

### M-2 — the author composition: **the design's E-10 reading is confirmed, and understated**

§8/E-10 records the designer proceeding on an unanswered question: read the human's
*"any candidate authored by an already-trusted identity needs zero further verification"*
directive as *"author is one of the HOS App identities"* and the gate skips verification on
*"97 of 101"* live records. Measured:

```
authored by an App/bot identity:  98/102
authored by a non-bot account:     4/102
   49  scottthurlow-claude[bot]
   32  hos-worker-hos[bot]
   17  hos-overseer-hos[bot]
    4  ScottThurlow
```

**The four non-bot records are authored by `ScottThurlow` — the CODEOWNER himself.** So under
the wide reading the gate would skip verification on 98 records as App-authored and clear the
remaining 4 as CODEOWNER-authored: **inert on 102 of 102 of the present queue**, not 97 of 101.
**The designer's narrow reading is correct and the margin is larger than they claimed.** E-10
should be closed in the designer's favour rather than left open.

### M-3 — the rate limit: **the citation is bad, the number is right**

Both the architect (AM-30, `CONFIDENCE: MEDIUM-HIGH`) and the designer (§0.6 gap 9) flagged
that the 5,000/hour figure is cited to `docs/OVERSIGHT-RUNBOOK.md:56`, **which is a crontab
example line.** I confirm the citation defect — `:56` is inside a fenced ```cron``` block
illustrating a staggered schedule. **And I measured the actual limit live for the worker App's
installation token:**

```
core_limit: 5000   core_remaining: 5000   graphql_limit: 5000   search_limit: 30
```

**5,000/hour is correct.** The derivation rests on a bad citation and a right number. Fix the
citation; do not re-open the arithmetic.

### M-4 — the cadence: **the assumed 12 cycles/hour is 2× the measured rate, in the safe direction**

AM-30 derives the ceiling from *"a 12-cycle/hour cadence"*, taken from the same illustrative
crontab block (`1,6,11,...` — every 5 minutes; note the literal ellipsis, which is not a valid
crontab expression). **Measured from this clone's own audit log**, worker `cycle-start` events
on 2026-09-16 fire at minutes `:03/:04, :13/:14, :23/:24, :33/:34, :43/:44, :53/:54` —
**every 10 minutes, 6 cycles/hour, 91 cycles over the day.**

**The real cadence is half the assumed one, so the ≈100-request ceiling is about twice as
conservative as its derivation intends.** That is the safe direction and nothing needs to
change — **but a ceiling justified by a number taken from an ellipsis-bearing illustration
should say so**, and the illustration should not be cited as though it were a measurement.

### M-5 — the overseer's consumption: **the architect's own nominated defect DISSOLVES**

Amendment 4 §3(c) item 4 is the architect's nomination of their own unmeasured claim:
*"Check the derivation, and check whether the overseer's own cron consumption was accounted
for. It was not measured, only reasoned about."* Their confidence note repeats it: *"the
overseer's cron is unaccounted for, and that is the same derived-not-observed shape that
produced E-8."* Pass A's F6 raised it independently.

**It does not need to be accounted for, because the overseer does not draw on the worker's
bucket.** The three roles authenticate as **three separate GitHub Apps**:

- `bootstrap/get_app_token.sh:78-92` resolves a distinct `APP_ID` / `PEM` / `DECLARED_BOT_LOGIN`
  triple per role (`HOS_WORKER_*`, `HOS_OVERSEER_*`, `HOS_HUMAN_*`).
- `get_app_token.sh:164` is an identity guard that **errors** if the authenticated login does
  not match the role's declared login — the mechanism that would fail loudly if two roles ever
  shared an App.
- The identities are live and distinct: `hos-worker-hos[bot]` and `hos-overseer-hos[bot]` both
  appear as issue authors in M-2's breakdown.

GitHub meters the primary rate limit **per installation**, so each App has its own 5,000/hour
bucket. **The overseer's cron consumes the overseer's budget, not the worker's.**

**Disposition: item 4's overseer half is answered and should be closed. Its budget-share half
survives** — the ≈24% share is still a choice rather than a measurement, but it is now a choice
about a bucket with a single consumer, at half the assumed cadence, verified at 5,000/hour.
**I would not hold a CRITICAL security fix for it.**

---

## 1. Findings

**Numbering.** Run 1 used `P-n`, run 2 used `RP-n`. This run uses **`TP-n`** (third panel), for the
reason run 2 gave: the lenses return their own `F1…Fn`, which collides with the technical
design's §3 fail-closed rows `F1…F37`. Every finding names the lens and label it came from.

**Calibration, stated once.** Amendment 4 §3(c) required each finding to say whether it is a
`blocking-defect`, an `input-to-human`, or `worth-mentioning`, because on this run the two
classes have different consequences. **Three findings are blocking: TP-0 against the instrument,
and TP-4 and TP-1 against the design.** Everything else is an input to the human's decision or
worth recording. **TP-4 and TP-1 are the sticking point of the §5 escalation; the rest is
context for it.**

---

### TP-0 — CRITICAL — the adversarial lens silently read ~34% of the bundle. **BLOCKING, and it is the gate, not the design.**

*Orchestrator, measured. Full account at §0.0. Filed as **#1718** (`priority:critical`,
`v0.6.1`).*

`vendor_invoke.sh` reports success on exit 0 with non-empty stdout and never checks how much of
the prompt was consumed. `VENDOR_INVOKE_BYTES` is bytes *written*. Measured ceiling on
`agy 1.2.3`: **≈68k input tokens / ≈270KB**; chunked calls at 48–50k tokens were consumed
whole. The production caller is `scripts/run_second_review.sh` — the **pre-PR cross-vendor
second review at MEDIUM+/HIGH+** — which sends `git diff` with no size guard, so this is not
confined to design panels. **#1136** will build `run_spec_panel.sh` on the same path and inherit
the defect.

**Why it is blocking here:** it is what prevents this run from discharging the gate, and the
worked example in §0.0 — a HIGH finding (pass-A F1) that is wrong because the refuting text was
in the unread 66% — shows the failure produces confident wrong findings, not obvious silence.

---

### TP-1 — HIGH — an untrusted author can reorder the gate's walk with one comment, defeating R-8's load-bearing mitigation. **input-to-human. NOT on the designer's §9.5 list.**

*Adversarial chunk 1 F1(2) and chunk 2 F6, independently. Premise verified live by the
orchestrator.*

**The claim attacked.** §2.2.1's R-8 mitigation (iii): *"The human's authorizing act is itself
an update, so it lands at the head of its band — and with an early exit that head position is
now worth more, not less."*

**The construction.** The walk order is `(rank, updated_at DESC, number ASC)` (AM-29).
**`issue.updated_at` advances when anyone comments** — and on a public repository that is any
GitHub account, with no permission beyond commenting. So:

1. The human applies the dispatch label to issue X. X goes to the head of its band. Mitigation
   (iii) working as designed.
2. **Anyone posts one comment on gated issues Y₁…Yₙ in the same band.** Each jumps ahead of X.
3. The walk now spends its request budget on Y₁…Yₙ — each costing 1–10 requests at D5.2 — and
   with the population (102) already above the ≈100-request ceiling, **it need not reach X at
   all.** Early exit does not save it: the stop is on *eligible* candidates, and the Yᵢ are all
   gated, so they consume budget without advancing the stop.

**Verified live, not constructed.** I compared each candidate's `updated_at` against its newest
comment's timestamp:

```
  #1709  updated_at 2026-09-16T07:30:43Z   newest comment 2026-09-16T07:30:43Z   -> the comment set it
```

**A comment advances the gate's within-band walk key.** The premise holds.

**Direction of harm, stated precisely because it bounds the severity.** This **cannot authorize
anything** — every Yᵢ still gates, and the fail-closed direction is untouched. What it buys an
attacker is **control over which records the gate reaches**, and therefore the ability to starve
authorized work for as long as they keep commenting. Against R7 (*"the gate is a single point of
failure for all autonomous work"*) that is a denial of service on the whole autonomous pipeline,
mounted for one comment per issue, by anyone.

**Why it is not classified blocking, and the remedy is already in the chain.** It is an
availability defect, it is loud (`ALL-CANDIDATES-GATED`, `unevaluated:cost-ceiling` and
`complete=no` all fire), and **AM-29 itself already specifies an order that is immune to it**:
the stated fallback **`(rank, number DESC)`** uses no attacker-controllable key. AM-29 reached
for `updated_at` to get the promotion-on-authorization property, and that property is real — but
it was chosen without anyone noting that the same key is writable by the public. **This needs
one ruling on which key to use, not a design round.**

---

### TP-2 — MEDIUM — a budget-clamped events fetch is recorded as a determination it did not make. **input-to-human. On binding item 2.**

*Adversarial chunk 1 F2 and chunk 2 F2, independently. Confirmed against the text by the
orchestrator.*

§1.4 rule 4 (TD `:612`): a record's events fetch is clamped to
`min(EVENTS_PAGE_BOUND, effective_ceiling - api_requests)` pages, and *"if the clamp bites
before a match is found, the outcome is identical to rule 1 — **gated**"*.

§0's binding (TD `:454`): ***"`gated=<G>` counts determinations only."***

**These cannot both hold.** The clamp can reduce the fetch to **one page, or none**, purely
because of how much budget remained when the walk arrived. A record whose authorizing `labeled`
event sits on page 2 is then recorded as `gated` / `no-codeowner-actor` — *the gate looked and
found no qualifying actor* — when the gate did not look. The consequences are the ones AM-20
exists to prevent: `gated=<G>` is inflated, `unevaluated=<U>` is undercounted, and the record
enters the `ALL-CANDIDATES-GATED reasons:` breakdown that TD `:453` reserves for determinations.

**The sharpest form, which neither lens stated.** The determination becomes **a function of walk
position rather than of repository state** — the same record, same labels, same actors, is
`gated` or `eligible` depending on how much budget remained when it was reached. That is
non-determinism in the output of a component whose name is *the deterministic work-selection
gate*.

**Distinguish from the page-bound case, which is correctly ruled.** Rule 1 (all 10 pages
fetched, no match) genuinely *is* a determination, and AM-5 ruled it so deliberately. The defect
is specific to the budget clamp, which is new in revision 5 and inherited rule 1's disposition
without inheriting its justification. The fix is one token: `unevaluated:cost-ceiling` with the
issue number.

---

### TP-3 — MEDIUM — `unevaluated:list-truncated=<y>` is both underivable and outside the partition it is summed into. **input-to-human. Found by reading the document against itself.**

*Adversarial chunk 2 F3. Confirmed against the text by the orchestrator.*

Three statements in one document:

1. **TD `:443`** — `unevaluated:list-truncated` means *"the record was never on the candidate
   page set at all"*. Such records are **not in `N`**, the scanned set.
2. **TD `:1106`** — `unevaluated=<U>` carries the identity **`N = E + U`**.
3. **TD `:1116`** — the summary line must print `unevaluated:list-truncated=<y>`, a **count**.

(1) and (2) are inconsistent whenever `y > 0`: summing records outside `N` into `U` breaks
`N = E + U`. And (3) is **unsatisfiable on its own terms**, because TD `:976`/`:979` bind the
gate to say *"at least 500 records matched; the total is UNKNOWN"* and **never a count it cannot
derive** — GitHub's `/issues` returns no total. AM-31 says this in terms: Step C *"may not
report a truncation count it cannot derive."*

**So the design forbids the count in one section and mandates it in another, 670 lines apart.**
This is exactly the class standing instruction 1 was written for, and it is the third such
instance the designer predicted (§9.4) without finding.

---

### TP-4 — CRITICAL — two §6.2 tests that revision 5 makes BINDING are mutually unsatisfiable on the fixture one of them mandates. **BLOCKING. On the architect's own top item.**

*Adversarial chunk 3 F1. **Confirmed at the line by the orchestrator.** This is the finding
Amendment 4 §3(c) item 1 asked for in terms: "attack the seam between them."*

AM-29 deliberately separated two orders — the gate **walks** in
`(rank, updated_at DESC, number ASC)` and **emits** in `(rank, number ASC)`. Revision 5 makes
two §6.2 tests binding:

- **`TD:1936` — `test_emission_order_is_rank_number_even_when_the_walk_order_differs`** *(NEW in
  revision 5, BINDING, AM-29 point 2)*: *"A fixture in which the two orders **disagree**: three
  same-rank records whose `updated_at` order is the reverse of their number order. Assert the
  walk visited them newest-first … and that stdout emits them in ascending issue number."*
- **`TD:1934` — `test_emitted_list_is_a_prefix_of_the_complete_walk`**: *"run the same fixture
  twice, once with the default bounds and once with bounds high enough that `complete=yes`, and
  assert `bounded_output == unbounded_output[:len(bounded_output)]` **byte for byte**."*

**Run the second test on the first test's mandated fixture.** Three same-rank records whose
`updated_at` order reverses their number order — so `#30` newest, `#10` oldest:

| | |
|---|---|
| Walk order `(rank, updated_at DESC, number ASC)` | `[#30, #20, #10]` |
| Unbounded run — all admitted, Step E emits `(rank, number ASC)` | `[#10, #20, #30]` |
| Bounded run, early exit at 1 — admits `{#30}`, Step E emits | `[#30]` |
| `test_emitted_list_is_a_prefix_of_the_complete_walk` asserts | `[#30] == [#10]` → **FAILS** |

At `--max-candidates 2` it fails the same way: `[#20, #30]` versus `[#10, #20]`.

**This is not an edge case, it is the normal path.** The test only passes when the early exit
does not bite — i.e. when the candidate set is smaller than the stop. **The measured population
is 102 against a default stop of 5** (M-1), so the early exit bites on every cycle.

**The underlying property is broken, not just its test.** `TD:810` defines exit 0 as *"stdout is
an exact prefix of the ranked walk over the fetched set"*. With the two orders separated, the
unbounded emission `[#10, #20, #30]` is **the reverse** of the ranked walk `[#30, #20, #10]` —
not a prefix of it. **Taking the top-k under order A and re-sorting that subset by order B does
not, in general, yield a prefix of the full set under either order.** That is arithmetic, not
judgement.

**What this is and is not.** It is **not** a refutation of AM-29 — separating the two orders is
right, and rank dominance survived attack (§3, rejection list). It is that **prefix-correctness
and its differential test were written when the two orders were the same**, and revision 5
carried both forward unchanged after making them different. **The seam the architect told the
panel to attack is exactly where it broke.**

**Remedy, so the escalation is actionable.** Scope the prefix property to the **walk** order and
compare walk-order output in the differential test, or restrict that test to equal-bounds runs.
One of the two test descriptions has to give. **This is a specification reconciliation, not an
architectural question** — see §5.2.

---

### TP-5 — HIGH — exact tier matching excludes admins and maintainers from `tier:write`, and the repo already ships the same bug. **input-to-human: it is a product ruling, not a design flaw.**

*Adversarial pass A F3, chunk 1 F4 and chunk 4 F3 — three independent raises. Live corroboration
by the completeness lens.*

§1.3.2 binds **exact** matching: `role_name == token`. GitHub's tiers are **hierarchical**
(`admin` > `maintain` > `write` > `triage` > `read`). A project owner who writes `tier:write`
meaning *"anyone with push access"* gets a roster that **excludes their own admins and
maintainers**, silently and fail-closed.

**The design flags this itself** (§9.1 item 8(b)): *"Exact-not-hierarchical matching is MY
decision, not the human's — they ruled the tokens, not the ordering."* **The panel's answer is
that the surprise is real and lands in a direction that matters.**

**And the repository already demonstrates the bug.** The completeness lens found
`scripts/framework/provision_agent_account.sh:190` calling the per-user
`/collaborators/{user}/permission` endpoint and reading **`.permission`** — the *legacy*
vocabulary, which per GitHub's documentation returns only `admin`/`write`/`read`/`none`, mapping
`maintain`→`write` and `triage`→`read`. **Its `case` arms matching `worker-maintain` and
`overseer-maintain` can therefore never fire.** That is a live, shipped instance of precisely
the vocabulary trap §1.3.2 reasons about — pre-existing and out of S2's scope, but it is the
strongest available evidence that the concern is not theoretical.

**Two corrections to the raises, because crediting them unchecked would propagate errors.**
Pass A's claim that the collaborators endpoint *"requires admin rights"* is **not credited** —
it is asserted from model training, and `provision_agent_account.sh:190` calls the sibling
endpoint successfully today. And the design's *"nothing in the tree calls the endpoint"*
(§0.6 gap 8) is **wrong as written**: nothing calls the *list* endpoint; the *per-user* one is
called. The `role_name` field itself **is** on GitHub's documented list-collaborators schema, so
§1.3.2's choice is consistent with the documentation — it remains unobserved on a live payload,
exactly as the design declares.

**Why input-to-human rather than blocking.** The human ruled the tokens; whether matching is
hierarchical is a **product decision they have not been asked**. It fails closed, so nothing
unsafe ships. **One sentence from the human settles it.**

---

### TP-6 … TP-11 — the completeness lens's documentary findings. **All input-to-human or worth-mentioning.**

*Completeness lens, verified at the line with full repo access. Reproduced in condensed form;
§4 carries its full verification table.*

| # | Finding | Class |
|---|---|---|
| **TP-6** | **Q11 and Q12 were never posted to #1540.** The chain treats them as "outstanding, riding with H1", but a grep of all 11 comments finds **zero** matches. The human answered at 07:14:38Z against Amendment 3's text, in which they do not exist. AR-7 fails closed so the build is safe — but **the human cannot ratify a narrowing of their own #1539 ruling that nobody has put in front of them.** | input-to-human |
| **TP-7** | **Amendment 4's escalation was false when authored.** Committed `63da291a` at 15:32:09Z — **8h17m after** the human's 07:14:38Z ruling. Its *"H1 has never been answered… the critical path"* and its fourth-consecutive *"nothing is orphaned because H1 is unanswered"* were both already untrue. TD §0.0.5 records this correctly. **The human should also be told that the "~105-request worst case" they accepted on Amendment 3's text was a floor**; AM-30 re-denominated it and holds it at ≈100 *requests*. | input-to-human |
| **TP-8** | **One coverage-map row is false — the RP-22 class the author says was eliminated.** H1 item 3's row names **§2.7.2**, which is **byte-identical** between revisions 4 and 5. `:1342` also still says S3 introduces the digest binding the human cancelled. 13 of 14 other checked rows hold. | worth-mentioning |
| **TP-9** | **The divergence test named in §6.3 does not exist.** `test_jq_label_literals_match_hos_labels` is a *planned* TD-1604 test. The real one is `tests/automation/test_next_candidates.py:127 TestBothSelectionPathsAgree`. RP-11/AM-37's premise is about a phantom test; the replacement assertion is sound on its own terms. | worth-mentioning |
| **TP-10** | **Three bundle claims are factually wrong.** (i) *"nothing in the tree calls the [collaborators] endpoint"* — **`scripts/framework/provision_agent_account.sh:190`** calls the per-user `/permission` sibling and reads **`.permission`**, the legacy vocabulary (`admin/write/read`, with `maintain`→`write`, `triage`→`read`), so **its own `maintain` arms can never match** — a live demonstration of the trap §1.3.2 warns about. (ii) *"UWP:448 is the only in-repo 5,000/hr statement"* — `UNATTENDED-WORKER-TECH-DESIGN.md:256-257` also states it **and already defines a per-customer request budget**, unrecognised prior art for AM-30. (iii) see TP-9. | input-to-human |
| **TP-11** | **`run_spec_panel.sh` IS tracked — by #1136, and three documents say it is not.** Run 1, run 2, `pm-agent` §5 and Amendment 4 §4 item 2 all assert no open issue tracks the panel's invocation site. **#1136** (open, `needs-ai`, `priority:high`, milestone **v0.7.8 — Design-Chain Panel (ADR-033)**) names it explicitly: *"S4 — C — `scripts/run_spec_panel.sh` — The single deterministic gate invocation site (AD-2)."* **Verified directly by the orchestrator.** Prior searches missed it because the script name is in the issue's body table, not its title, and `query_issues.sh --list` is page-capped at 100 with no pagination. **Amendment 4's recommendation to fold the work into #1696 is misrouted.** | input-to-human |

**TP-9 changes the shape of a complaint this chain has made three times.** The panel's missing
invocation site is not an untracked gap — it is **scheduled two milestones away (v0.7.8) while
the gate it automates is being hand-run for a `priority:critical` security fix in v0.7.0.**
That is a sequencing decision someone should make deliberately, and #1718 makes it sharper: when
#1136 is built, it will inherit TP-0 unless TP-0 lands first.

---

## 3. The adversarial lens — what it read, what it returned, and what was rejected

**Pass A (full bundle, single shot) is VOID.** Its seven findings are not carried. They are
retained at `/tmp` only as exhibits for #1718. The worked rejection is in §0.0: pass-A F1 (HIGH,
"D5.3's quarantine is unreachable") is **wrong**, and the text refuting it — §2.3 D5.2/D5.3,
where the fetch and the verdict are separate steps and `verify_codeowner_actor(events, …)` is a
pure function over already-fetched events — sits in the 66% the lens never received.

**Pass B (chunked)** re-read the design in four contiguous slices, each verified consumed whole
by its own `input_tokens`:

| Chunk | TD lines | `input_tokens` | Consumed whole | Findings |
|---|---|---|---|---|
| 1 | 450–1009 | 48,249 | yes | 6 — incl. TP-1, TP-2 |
| 2 | 1010–1569 | 50,433 | yes | 6 — incl. TP-1 (independently), TP-2 (independently), TP-3 |
| 3 | 1570–2129 | 43,495 | yes | 6 — **TP-4 (CRITICAL)**, TP-1 (independently), TP-3 (independently) |
| 4 | 2130–2684 | 60,247 | yes | 6 — TP-1 (independently), TP-5, plus §9's own surfaces |

**The convergence is the most useful signal pass B produced.** The four chunks share no text and
were invoked independently. **TP-1 was found by chunks 1, 2, 3 and 4 — all four.** TP-2 was found
by chunks 1 and 2; TP-3 by chunks 2 and 3; TP-5 by chunks 1 and 4 and by pass A. Independent
reads of disjoint material converging on the same defects is stronger evidence than a single
read of the whole, and it is the one respect in which the degraded mode outperformed the mode it
replaced.

**Per-chunk verdicts, recorded rather than averaged:** chunk 3 returned **DO-NOT-BUILD**; chunks
1, 2 and 4 returned BUILD-WITH-CONDITIONS; the completeness lens returned BUILD-WITH-CONDITIONS
with *"what genuinely stops the build: nothing I found."* **The panel's verdict is the
conjunction, as run 2 established** — and chunk 4's own output is internally inconsistent, since
it returned BUILD-WITH-CONDITIONS while labelling two of its findings `blocking-defect`. **That
inconsistency is noted rather than silently resolved in either direction.**

### Rejected — findings the lenses returned that do not survive checking

Run 1's and run 2's rejection sections were judged their most valuable output. Carrying that:

1. **Pass A F1 (HIGH) — REJECTED.** See above. Correct citation, real code, wrong conclusion:
   the gate does not call `probe.py`'s wrapper.
2. **Pass A F2's claim that the collaborators endpoint "requires admin rights" — NOT CREDITED.**
   It is asserted from the model's training, not from the bundle, and the completeness lens
   found the repo already calls the per-user `/permission` sibling successfully at
   `provision_agent_account.sh:190`. The *vocabulary* half of the concern is real and survives
   as TP-8(i); the *permissions* half is unsupported.
3. **Pass A F6 and chunk findings on the overseer's API consumption — REJECTED on measurement.**
   See M-5: the overseer is a separate GitHub App with its own 5,000/hour bucket and does not
   draw on the worker's. The architect's own nominated defect does not survive.
4. **"The 5,000/hour figure is wrong because it is cited to a crontab line" — HALF REJECTED.**
   The citation is bad (M-3 confirms it) and **the number is right**, measured live at 5,000.
5. **Chunk 2 F4 (stale milestone-as-authorization text in §2.7.3) — NOT CREDITED as a defect.**
   §2.7.3 is cutover *sizing*, and the sizing is unchanged by which channel authorizes.

---

## 4. The completeness lens — what it verified

The completeness lens (`claude-fable-5-1`, rank 4, class differential over the bundle's rank-3
authors) read all three bundle documents **from disk**, so no CLI sat between it and the text
and TP-0 does not touch it. It checked 22 claim groups at the line, performed live GitHub reads
through `bootstrap/query_issues.sh`, and read GitHub's published collaborators schema.

**Its verdict: BUILD-WITH-CONDITIONS — *"What genuinely stops the build: nothing I found."***
That is a real result and it is recorded as it stands. **It is not the panel's verdict**, for
the reason run 2 gave: the two lenses answer different questions, and the panel verdict is their
conjunction. The completeness lens was verifying claims against the repository — and on that
brief **revision 5 performs extremely well.**

**The headline verification results:**

| Claim | Result |
|---|---|
| `probe.py` ranges `:257-277`, `:280-324`, `:292-294`, `:298-303`, `:307-313`, `:315-322`, `:428-431` | **VERIFIED exact.** Revision 5's corrections are right and the `:254-345`/`:283-345` it carried since revision 1 were wrong |
| `bin/hos-cron:1147-1151` (TD) vs `:1146-1150` (Amendment 4) | **TD right, Amendment 4 off by one.** AM-32's premise holds exactly |
| `merge_authority.py:633` / `:1223`; `docs/LABELS.md:29` stale at `:599`/`:1068` | **VERIFIED both** — plus a **third** stale item the design does not list: `:29` names `/handoff` as a `needs-ai` writer, but `/handoff` **removes** it |
| `_verify_codeowner_actor` authorizes on either a `labeled` or a `milestoned` actor | **VERIFIED** — and the docstring's *"the most recent"* is **false**: the body collects **every** matching event of both kinds and walks the whole history past bots |
| Scope-vs-authorization separation (the trap AM-35 names) | **VERIFIED — separate code paths.** The list queries share no code with the `milestoned` arm; deleting the arm cannot break selection |
| `expected_milestone_title` readers | **VERIFIED zero** — it was a revision-4 proposal never built, so "deleting" it deletes a design line, not code |
| The three human comments at 07:14:38Z / 07:16:58Z / 15:46:50Z | **VERIFIED at the stated timestamps with the stated content.** Amendment 4 was committed at **15:32:09Z, 8h17m after** the H1 ruling it says was never given |
| Population = 101 | **≥102 now** — matches the orchestrator's independent 102 (M-1) |
| `machine-accounts.env` shipped or generated for consumers | **VERIFIED neither** — tracked here, absent from `framework_consumer_files.txt`, no writer anywhere. **#1640** already tracks the consumer gap |
| 13 of 14 coverage-map rows | **VERIFIED changed.** The fourteenth is TP-8 |

**What it could not verify, in its own words:** the exact 101 figure at 15:55Z (the sanctioned
reader is page-capped at 100 and unpaginated — which is also why prior runs missed **#1136**); a
live collaborators payload from *this* installation; #1542's event log; live repository settings.
**The orchestrator's M-1 supplies the first of those from a paginated read.**

---

## 5. The escalation — 5 of 5, with the count and the sticking point

**This section is the deliverable Amendment 4 §0.0.1 specifies.** *"If that run returns
DO-NOT-BUILD, that IS the non-convergence, and it escalates to the human under the CORE cap with
the count (5 of 5) and the sticking point. It does not become round 6."*

### 5.1 The count

**Round 5 of 5 under the CORE cap.** The architect ↔ `technical-design` loop ran five rounds;
`ADR-1540-AMENDMENT-4` recorded round 5 as the last and stated that round 5 *"CONVERGES on
architecture."* **That statement is not contradicted by this run** — see §5.2. The panel gate
ran three times: DO-NOT-BUILD, DO-NOT-BUILD, and now DO-NOT-BUILD.

### 5.2 The sticking point — and what it is NOT

**It is not architectural disagreement.** Nothing in this run refutes an architect ruling.
AM-29's separation of walk and emission orders survived direct attack; so did rank dominance,
the scope/authorization separation, the retirement set's completeness, and AM-31's per-record
licensing argument (§3, rejections). **The architecture converged. The paperwork did not.**

**Four confirmed defects, in the order a human should spend attention on them:**

| # | Defect | Class | Remedy, and where it already exists |
|---|---|---|---|
| **TP-4** | Two binding §6.2 tests are mutually unsatisfiable on the fixture one of them mandates; the prefix property at `TD:810` is broken by the very order-separation AM-29 introduced | **Blocking** | **Specification reconciliation.** Scope the prefix property and its differential test to the **walk** order, or restrict the differential test to equal-bounds runs. One of two paragraphs gives |
| **TP-1** | Any GitHub account can reorder the gate's walk with one comment, exhaust the request ceiling on gated records, and starve authorized work indefinitely — the walk *"ends COMPLETELY"* on the ceiling stop | **Blocking** | **Already in the chain: AM-29's own stated fallback `(rank, number DESC)`** uses no attacker-writable key. It costs the promotion-on-authorization property, which is the trade to put to the human |
| **TP-2** | A budget-clamped events fetch is recorded as `gated` — a determination the gate did not make — making the verdict a function of walk position rather than repository state | **Non-blocking, but it defeats AM-20's purpose** | One token: `unevaluated:cost-ceiling` with the issue number |
| **TP-3** | `unevaluated:list-truncated=<y>` is summed into a partition it sits outside, and is a count AM-31 forbids deriving | **Non-blocking** | Make it a boolean flag, or drop it from the `U` sum |

**And the qualifier that should shape how much weight the above carries: TP-0.** The adversarial
lens received ~34% of the bundle on the run as specified. Pass B recovered the remainder in a
**degraded chunked mode that cannot see the documents against each other** — the technique that
produced four of the prior runs' best findings. **So this finding set is a floor.** A correctly
instrumented run could find more, and the two runs before it were conducted on the same
unmeasured path.

### 5.3 The three questions for the human

1. **TP-4 and TP-1 are both mechanically fixable without reopening an architect ruling. Does
   fixing them constitute round 6, or a correction within round 5?** If a correction: the chain
   is not in non-convergence and this escalation closes with two edits and a re-run. If round 6:
   the cap binds and the human decides whether to lift it. **This panel cannot rule on its own
   exit condition and does not try to.**
2. **TP-1's remedy is a trade, not a fix.** `(rank, number DESC)` is immune to the attack but
   loses AM-29's promotion-on-authorization property — the property that closed RP-2. **Which
   does the human want: an order the public can influence, or one where a freshly authorized
   record does not jump the queue?**
3. **TP-5 is a one-sentence product ruling** the human has not been asked: should `tier:write`
   include admins and maintainers? The design chose exact matching and flagged the choice as its
   own. **Q11 and Q12 (TP-6) have also never been posted to #1540** — a grep of all 11 comments
   finds zero matches. They are outstanding because nobody asked them, not because nobody
   answered.

### 5.4 What this panel did NOT do

**Nothing in this artifact authorizes a merge, a protected-surface edit, or a line of code.**
`coder` is not cleared. No design document was modified by this run. No issue was closed. The
one write this run made outside its own artifact is **#1718**, the instrument defect, filed as
`priority:critical` / `v0.6.1` because it affects `run_second_review.sh` on the live PR path and
not only this gate.

---

## 6. Register — retirements and carries for a fourth run, if there is one

**Carried at full weight** (attacked this run, not closed): A1, A5, R2 (re-aimed to the
collaborators payload — still unobserved on a live response from *this* installation), R6, R7,
R9, R10. §9.2's entries stand as written.

**Closed by this run, with reasons:**

| Row | Disposition |
|---|---|
| **Item 4's overseer half** (the architect's own nomination) | **CLOSED on measurement — M-5.** The overseer is a separate GitHub App with its own 5,000/hour bucket. It was never drawing on the worker's budget |
| **§0.6 gap 9's rate-limit citation** | **HALF CLOSED — M-3.** The citation is bad and the number is right, measured live at 5,000 |
| **AM-29's `updated_at` presence premise** | **CLOSED — M-1.** Present, non-null and all-distinct on **102/102**, re-derived independently. The fallback is not triggered *on availability grounds* — **though TP-1 now argues for it on security grounds, which is a different reason** |
| **§8/E-10** (the trusted-author skip reading) | **CLOSED in the designer's favour — M-2, and by a wider margin than they claimed.** Under the wide reading the gate is inert on **102 of 102**, not 97 of 101 |
| **"No issue tracks `run_spec_panel.sh`"** | **RETIRED AS FALSE — TP-11.** #1136 tracks it, in `v0.7.8`. Carried wrongly by run 1, run 2, `pm-agent` §5 and Amendment 4 §4 item 2 |

**New residual for whoever comes next: the gate this chain depends on is hand-run.** Three runs,
three hand-assemblies, and TP-0 shows the hand-assembly was measuring nothing about what the
lens received. **#1136 builds the invocation site in v0.7.8; #1718 must land before it, or the
automated gate will inherit the defect that invalidated this one.**

---

*Panel run 3 conducted 2026-09-16 by the autonomous worker (`hos-worker-hos[bot]`) at repo head
`cf37b8bb`. Adversarial lens: agy 1.2.3 (google). Completeness lens: claude-fable-5-1.
Orchestrator: claude-opus-5 — rank-equivalent to the bundle's authors, which §0.3 records as a
standing independence limitation of all three runs.*
