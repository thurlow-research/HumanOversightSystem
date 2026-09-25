# PANEL-1540 (S1 + S2) — dual-lens adversarial panel, **FIFTH RUN**, against technical-design revision 7

```yaml
verdict:                              DO-NOT-BUILD
non_convergence:                      NOT DECLARED — every blocking finding is class "mechanical correction"
                                      (the human's 2026-09-16 rule); none reopens an architect or human ruling
escalates_to:                         technical-design (revision 8, within round 5) + ONE architect
                                      notification (RP5-1: AM-22's literal `--paginate`) + ONE question
                                      for the human (§5: whether round 5 continues)
gate:                                 TD-1540 §9 (revision-7 block: run 5's scope) under ADR-1540-AMENDMENT-4 §3(c)
supersedes:                           none (runs 1–4 stand as written)
bundle_under_review:                  TECHNICAL-DESIGN-1540 rev 7 (703098349; file sha256_16 3b7fac96b0008ff5)
                                      + the rev-6 → rev-7 diff (ba4c1d7ea..703098349)
repo_head:                            c79b79a18
adversarial_cli:                      agy 1.2.11 (google — cross-vendor; run 4 used 1.2.3)
adversarial_invocation:               scripts/oversight/lib/vendor_invoke.sh, stdin, --sandbox --output-format json
adversarial_mode:                     7 chunks, each MEASURED consumed whole (3 sentinels echoed + input_tokens) — §0.2
completeness_cli:                     claude (Agent tool)
completeness_model_resolved:          claude-fable-5-1 (rank 4; bundle authors rank 3)
orchestrator:                         claude-opus-5-5 (rank 3 — SAME rank as the bundle's authors; §0.3)
timestamp:                            2026-09-25
```

**Status: DO-NOT-BUILD. `coder` is NOT cleared to build S1 or S2.**

**The one-paragraph version.** **The revision-7 repair held.** The completeness lens worked the
restated ADMISSION and rank-dominance properties against every stop, and could not break either.
It found no path that counts a clamped record `gated`, and found that `N = E + U` holds by
construction. F30 now follows §2.2's single exit rule at every site. The differential test is
satisfiable on all four fixtures, and the finding-disposition register is complete. The agy chunks'
attacks on the properties themselves (six of seven attacked them) all reduced, on checking, to one
**test-coverage** gap (RP5-3), not a false property. **What stops `coder` is outside the repair's
logic:** **(RP5-1)** the fetch mechanism the design prescribes, `gh api --paginate`, **cannot** do
the job the design gives it. It can't bound pages, clamp a fetch, run the pre-issue stop test
between pages, or see the `Link` header "bites" depends on. It also leaves "end of history"
undefined for a short page. **(RP5-2)** §4.2 deletes a test file that #1805 gave two classes §4.2
never dispositions. Both are corrections, and neither reopens a ruling.

---

## 0. How this panel ran

### 0.1 The instrument defect is controlled again — measured, not asserted

#1718 (agy silently truncates oversized input and reports SUCCESS) is still open. Run 5 repeated
run 4's control exactly, as TD §9's revision-7 block binds it to. No chunk exceeded ~185 KB. Each
chunk carried three sentinels (start, exact middle, end) derived from a hash of the chunk tag, and
each response had to echo them. **All 21 sentinels came back.** No response was an empty
`denied_actions` envelope.

### 0.2 What each lens actually read

| Lens / chunk | Material | Bytes | `input_tokens` | Sentinels echoed | Verdict |
|---|---|---|---|---|---|
| agy D1 | rev6→rev7 diff, part 1 of 2 | 176,394 | 67,641 | 3/3 | DO-NOT-BUILD |
| agy D2 | rev6→rev7 diff, part 2 of 2 | 182,670 | 68,871 | 3/3 | DO-NOT-BUILD |
| agy T1 | TD rev 7 L1–672 | 184,362 | 74,807 | 3/3 | DO-NOT-BUILD |
| agy T2 | TD rev 7 L643–1320 | 184,731 | 69,568 | 3/3 | DO-NOT-BUILD |
| agy T3 | TD rev 7 L1291–2149 | 184,743 | 72,232 | 3/3 | DO-NOT-BUILD |
| agy T4 | TD rev 7 L2120–2674 | 184,705 | 70,299 | 3/3 | DO-NOT-BUILD |
| agy T5 | TD rev 7 L2645–3181 | 181,031 | 68,137 | 3/3 | DO-NOT-BUILD |
| completeness (fable) | full TD from disk (16 slices), the diff, RUN4, RUN3 excerpts, AM-20/21/22/30/31, live `bin/hos-cron`, `test_next_candidates.py`, `worker-cron-prompt.md`, `gh api --help`; #1540 read live | — | ~420k reported (tool output included) | n/a | BUILD-WITH-CONDITIONS |

Chunks overlap by 30 lines. Every line was prefixed `L<n>:` so citations are checkable. All seven
agy calls ran in parallel, and each prompt carried the run-3 and run-4 rulings plus §9's
revision-7 attack list. Prompt sha256_16: D1 `dd4b1d4a2c52e686`, D2 `dd585eb6a5f86193`,
T1 `6890d62528cc4f9f`, T2 `22a465f09775d69a`, T3 `7e9f38e13840e8d0`, T4 `e654b1531579c8ad`,
T5 `b25554a4a93253a0`.

**One more data point for #1718.** T1 consumed **74,807** tokens whole, the highest yet (run 4's
T1 was 73,514). Bytes per token were 2.46–2.66. That matches run 4's conclusion: the limit is not a
plain ~68k input-token ceiling, and the sentinel echo is the check to trust. The agy CLI moved from
1.2.3 to 1.2.11 between runs, so this is not a like-for-like measurement of the old defect.

### 0.3 What to distrust in this artifact

1. **The orchestrator is rank-equivalent to the bundle's authors** (opus). This is unchanged from
   runs 1–4.
2. **Chunked reads can't see sections against each other.** Several agy findings were refuted by
   text in another chunk (§3). The completeness lens is the cross-section reader.
3. **I verified every credited finding at the line** (see each finding's "Verified at"), per §9.4
   instruction 3. Rejections, with reasons, are in §3.
4. **The lenses disagree on one point, and I sided with agy (RP5-3).** Fable reports the
   differential test *"catches every defective walk I could construct"*. Six agy chunks built one it
   doesn't catch, and I worked it by hand. Fable is right that the **property** holds. Agy is right
   that the **test** can't see over-admission.
5. **The harness is ad hoc, for the third time.** It is `/tmp/claude/panel5/`: chunker, per-chunk
   `vendor_invoke` runner, sentinel checker. CLAUDE.md's "second time you need it, commit it" rule
   applies. **#1136 owns `scripts/run_spec_panel.sh`**, which is the real home. This run didn't
   widen its scope to build it.

---

## 1. Findings

### RP5-1 — HIGH — the prescribed `gh api --paginate` cannot bound, clamp or count the fetches the design gives it, and "bites" is undecidable under it. **BLOCKING. Class: mechanical correction (plus an architect notification).**

**The claim.** §1.4 (L744) and D5.2 (L1236) prescribe `gh api --paginate "…/events?per_page=100"`,
*"bounded to 10 pages"* and *"additionally clamped to `min(EVENTS_PAGE_BOUND, effective_ceiling −
api_requests)` pages"*. The counter table (L1047–1050) requires the stop test to run **before each
request is issued**. Rule 4(a) (L752) says a clamp bites only if *"unfetched pages remained, as
GitHub's `Link` header indicates"*. Step C (L1127) and the collaborator fetch (L648) use the same
form with their own page bounds (5 and 3).

**Why it's false.** Live `gh api --help` on the installed gh 2.45.0 (the baseline #1805's comment
names) says: *"In `--paginate` mode, all pages of results will sequentially be requested until
there are no more pages of results."* It has no page cap, and it returns only after every page is
fetched. So under the literal invocation:

- (i) none of the three page bounds limits **requests**, only what is kept afterwards;
- (ii) the clamp can't stop a fetch at `L` pages, because they are already spent;
- (iii) the pre-issue stop test has no point between pages at which to run;
- (iv) `Link` is not visible on `--paginate` stdout.

§9.5 (L3032) already admits (iv) and leaves it *"to the coder"*. The invariant
`api_requests <= effective_ceiling`, which §6.2 asserts as a property over **every** fixture
(L2224), **can't be satisfied under the prescribed form**. Revision 7 made this load-bearing: the
clamp now decides `unevaluated` versus `gated` (TP-2 / RP4-1(i)).

**The same root, found independently by four agy chunks.** Rule 4(a) says *"if the gate cannot
tell whether a further page exists, it MUST treat the clamp as having bitten"*, and §6.2 companion
case 3 (L2233) binds *"a stub whose last page gives no `Link` information … must be treated as a
bite"*. **GitHub omits `Link` entirely on a single-page result.** So companion case 1 (*"history
ends on page 1 with no match … a determination: gated"*) and companion case 3 describe
**indistinguishable** stubs unless page length is the discriminant, and the text never says it is.
Read literally, every short-history untrusted record reached at `L < 10` becomes a spurious bite
that ends the walk. That fails safe (unevaluated, never a false `gated`), but it's wrong. Found by
D2 F4, T2 F-R7-4, T4 ADV5-3 and T1 ADV-502; T3 F-06 found the collaborator-fetch instance.

**Two §6 tests pin the wrong form.** L2219 (`test_step_c_paginates`: *"asserts `--paginate` is
present on the list call"*) and L2399 (`test_probe_events_fetch_is_bounded_paginated`: *"the
`--paginate` argument list and the 10-page bound"*).

**Verified at:** L744, L1236, L1047–1050, L752, L2233, L2219, L2399, L648, and `gh api --help`
(gh 2.45.0, read this session).

**Remedy (one paragraph plus echoes).** Bounded or clamped fetches are issued **one page per
request** (`?page=N`, or `-i` to read `Link`), never with `--paginate`. **A page shorter than
`per_page` terminates the history**, which is a determination. "Cannot tell" applies **only** to a
full page with no readable continuation signal. Re-scope companion case 3 to a full page, and
re-aim L2219 and L2399 to assert per-page issuance, the request count and the termination rule. The
`re.sub` normaliser becomes unnecessary on these paths (harmless if kept). **Why this isn't a
round:** AM-5 and AM-22 rule the bound **values** (10 / 1000, 5 / 500) and their purposes, and the
flag is mechanism. **But AM-22's table says `--paginate` literally**, so the architect should get an
E-12-style notification that the ruled bound is implemented by manual paging.

### RP5-2 — MEDIUM — #1805 drift: §4.2 deletes `test_next_candidates.py`, and two of its five classes have no disposition. **BLOCKING for the S2 PR's deletion step, not for the design's correctness. Class: mechanical correction.**

**Every agy chunk that could see it, and the completeness lens, raised it.** Verified live:
`TestPaginationGlobalSort` is at `tests/automation/test_next_candidates.py:192` and
`TestBothPathsPaginate` at `:242`. The TD mentions them only at L1362 and L2641, both as "not
dispositioned". §4.2's own rule (L1728, L1746) is that nothing load-bearing is lost in the
deletion.

**The panel's answer to §9's question, "does it block `coder`?":**

- **The stale `bin/hos-cron` line citations do not block.** S2 replaces the whole block, so the
  coder locates it by content. The completeness lens confirmed revision 7's own corrected pointer
  (`head -5` at `:1912–1915`) is right.
- **The missing §4.2 rows do block.** A coder can't delete the file without either silently dropping
  a regression test for a real defect (#1805: 36 issues unselectable) or inventing a disposition.

**Verified at:** L1362, L2641, L1728, L1746, `test_next_candidates.py:192` and `:242`.

**Suggested rows (the completeness lens's, checked against the file):**

- `TestPaginationGlobalSort::test_combined_set_is_globally_sorted` and
  `::test_page_two_issues_are_reachable_at_all` → **Port** as a two-page Step C fixture in
  `test_select_work_candidates.py`. Both walk and emission orders must interleave across the page
  seam.
- `::test_per_page_filtering_is_not_globally_sorted` and
  `::test_trap_is_invisible_in_the_first_five_lines` → **Retire**. They characterise the jq trap,
  which has no successor.
- `TestBothPathsPaginate` (all of it) → **Retire as vacuous after S2**. It asserts
  `"--paginate" in HOS_CRON` and `"add | $(cat"`, both false by design after S2 (§6.3
  `test_hos_cron_has_no_inline_jq_selection`). Pagination then lives in Step C alone. **Note the
  interaction with RP5-1:** Step C's pagination becomes manual, so the port must not re-pin
  `--paginate`.

**Also refresh by content:** §2.1 L890, §2.4 L1364 and §2.5 L1428. The "Today" form at L1428 cites a
`--jq` fallback that #1805 replaced; `worker-cron-prompt.md:100–101` now uses the paginated
`jq -sr` form.

### RP5-3 — MEDIUM — the rewritten differential test can't detect over-admission past `--max-candidates`, and the TD claims it catches "a limb nobody thought to enumerate". **Non-blocking. Class: mechanical correction.**

**Found by six of seven agy chunks** (D1 RP5-1, D2 F3, T2 F-R7-1, T3 F-02, T4 ADV5-1, T5 ADV-1),
most framing it as the property being vacuous. **The property is not vacuous.** The completeness
lens verified ADMISSION over determinations and restated rank dominance as true under every stop,
and I agree. **The test is.**

**Worked, fixture (i) at `--max-candidates 1`:** `W = [#30, #20, #10]`. A defective gate that
ignores the bound and admits `{#30, #20}` has `len(bounded_stdout) = 2`, so the assertion
`set(bounded_stdout) == set(W[:2])` **passes**. The "actually stopped" guard is `complete=no`
with `sufficient` non-zero, and it also passes because `#10` is unreached. The only thing that
catches this defect is `test_early_exit_stops_at_max_candidates_and_admits_nothing_after` (exactly
5 of 20), a separate limb.

That contradicts the TD's claim at L2213 (*"strictly stronger … A limb nobody thought to enumerate
still fails it"*). It also doesn't meet §9.5's own falsifiability standard (L3031), which names the
**differential** test as what a skipping walk fails. For **skipping**, it does fail: the lens
worked (i) at bound 2. For **over-running**, it doesn't.

**Verified at:** L2205–2206, L2213, L3031, plus the early-exit test in §6.2.

**Remedy:** add `assert len(bounded_stdout) == min(bound, len(W))` for candidate-bounded runs.
Fixture (iv) at `--max-api-requests 2` asserts an admitted count of `0`, which the text already
implies. Then either strike the overclaim or let it stand once the anchor is in.

### RP5-4 — LOW — F14b routes end-of-history to "F14's determination", which carries a WARN that rule 4(a) says doesn't fire. **Non-blocking. Class: mechanical correction.**

L1693 (F14b): *"one that reaches the end of the history is F14's determination"*. F14 (L1692) is
**10-page exhaustion**, and it emits `WARN events-page-bound-reached`. Rule 4(a) (L752) says a fetch
that ends at the end of history is a plain determination: `no-codeowner-actor`, gated. A short
history that is also clamped would therefore fire a page-bound WARN it never reached. Found by D1
RP5-2 and T3 F-05. **Verified at:** L1692, L1693, L752. **Remedy:** replace the words with *"is a
rule-1 determination (`no-codeowner-actor`, gated, no page-bound WARN)"*.

### RP5-5 — LOW — `WARN budget-clamped-events-fetch` fires on the event revision 7 defines as the ceiling stop, which AM-30 point 3 removed from the WARN class. **Non-blocking. Class: mechanical correction.**

Rule 4(c) (L754): *"A bite IS the ceiling stop."* Rule 4(b) (L753):
`WARN budget-clamped-events-fetch` *"still fires"*. F32 (L1711) and §1.2 consequence 5 (L587) say
the ceiling stop emits no WARN, because a warning that fires every cycle of correct operation is a
banner. The walk order is deterministic, so a mid-fetch bite on a multi-page record recurs every
cycle until the population moves. It's rare today (AF-7: at most 17 events per issue, one page).
This is the completeness lens's F2.

D2 F2 raised the same sites as a **contradiction** that a coder can't satisfy. **That framing is not
credited:** rule 4(b) states both lines explicitly, and F32's absence test is a plain ceiling
fixture. **Remedy:** drop the prefix (routine class, like its `unevaluated:cost-ceiling issue=#<n>`
sibling) at L753, L1030, L1238, L1693, L2005 and L2231, or state at rule 4(b) why this one is an
anomaly.

### RP5-6 — LOW — documentary: sweep gaps and stale sites, each verified at the line. **Non-blocking. Class: mechanical correction.**

- **(a) RP4-6(h)'s sweep missed two live sites.** Both still say the overseer's consumption is
  *"unaccounted for"*: L351, and L3109 in the HRR CONFIDENCE block. The register marks (h) FIXED.
  (T5 ADV-2; completeness F4.)
- **(b) RP4-6(c)'s reason correction missed two sites.** L894 and L1549 still give the Step 0 race
  as the **live** reason for the milestone-route prohibition. That contradicts §4.3(5) (L1756) and
  the revision-7 test at L2338. (Completeness F5.)
- **(c) L579 has stale counts:** it says *"the eight tokens above … the three above"*, but L557 lists
  **nine** and L559 says **four**. (T1 ADV-506; completeness F6.)
- **(d) §8/E-9 (L2849) still justifies the exit-3 emptiness condition by
  `if _GATE_CANDIDATES=$( … )`**, the caller description RP4-6(g) corrected elsewhere to §2.4's
  `case`. (T5 ADV-5.)
- **(e) L3153 and L3165 instruct the worker to post "R-8 in its revision-6 form" to #1539.**
  Revision 7 (RP4-5) found that form overclaims the recovery act. **This is a worker instruction to
  post a known-false statement,** so it should say "revision-7 form". (T5 ADV-4.)
- **(f) L3171 still calls the blocking gate "the panel's FOURTH run".** (T5 ADV-3.)
- **(g) L1028 and L1134 state list-bound truncation as an unconditional "exit 0".** §2.2's rule
  (and F33, correctly) says exit 3 when nothing is emitted. These are RP4-2-class sites outside
  RP4-2's list. (T2 F-R7-5.)
- **(h) L1105 names exit token `trusted-apps-missing`,** which isn't in the binding token register
  (L1116–1120: `machine-accounts-file-absent` / `trusted-apps-empty`). (T2 F-R7-8.)
- **(i) L1229 folds the clamp-bitten record into "left UNREACHED",** but rule 4 has it reached and
  partly fetched. The property still holds; the wording is imprecise. (D1 RP5-4, T2 F-R7-6.)

---

## 2. What held — verified by the completeness lens, spot-checked at the line

| Claim | Result |
|---|---|
| ADMISSION over determinations: admitted set = `W[:j]` under early exit, ceiling stop, clamp bite, quarantine and list bound (L1212–1216, L1234) | **TRUE.** No counterexample constructible |
| Restated rank dominance: no unreached record outranks an admitted one; quarantine is carved out and named (L1229) | **TRUE** |
| "Determined" does real work | **TRUE**, via D5.3 item 1 (only a transport failure quarantines) and the fixture-declared `D` checked against the unbounded run. A walk that admits after a stop fails limb (d) and fixture (iv); a walk that skips fails (i) at bound 2. *Over-running is RP5-3* |
| Differential test satisfiable on all four fixtures at every mandated bound | **TRUE**, worked by hand |
| No path counts a clamped record `gated`; at most one bite per run | **TRUE** |
| `N = E + U`, `U = w + x + z`, `list-truncated` outside `U`; the boolean is consistent with AM-20 point 3 | **TRUE** |
| No site states an all-gated exit other than §2.2's rule | **TRUE** (13 sites checked). *L1028/L1134's list-bound "exit 0" is RP5-6(g), a different case* |
| Finding-disposition register: every TP-0…TP-11 and RP4-1…RP4-8 present, dispositions matching | **TRUE**, except the (h) and (c) sweep gaps (RP5-6 (a), (b)). **Nothing vanished this time** |
| RP4-8 re-attribution at every site | **TRUE** |
| #1540: no human reply after 2026-09-25T07:16:34Z | **TRUE** (read live by both the lens and the orchestrator) |

---

## 3. Rejected or not credited

1. **D2 RP5-1 (CRITICAL as filed): "the ceiling stop fires only on an attempted request, so free
   records after an exhausted budget are admitted — limb (d)'s fixture is 'doctored'." NOT
   CREDITED.** The ceiling bounds **requests**. A free record reached before any request is refused
   is reached in walk order, sits in `W`, and is admitted consistently with the property. Limb (d)'s
   fixture states that precondition openly (RP4-6(m)). A clamp bite stops at the record for the
   same reason: a request was needed and refused. *If the human wants budget exhaustion itself to
   be a stop, that is a behaviour change, not a correction.*
2. **T1 ADV-501 (CRITICAL as filed): "'before a match' lets a later `unlabeled` on an unfetched page
   revoke an authorization the gate admits." NOT CREDITED.** Unlabeled events are ignored by
   design. That is residual **R-3**, accepted by AM-8 and restated by AM-36, and rule 4(d)'s
   monotonicity argument depends on it. Attacking it reopens a ruling.
3. **T3 F-03: "`W` is derived from stdout in emission order, so the test fails on every band."
   REFUTED.** §6.2 computes `W = sorted(D, key=walk_key)` with `walk_key = (rank, -number)` from the
   fixture (L2204). The L2060 summary's wording is loose, but the binding text is correct.
4. **T3 F-01: "`cost-ceiling=<x>` is 'at most one', so the unreached tail falls out of `U`." NOT
   CREDITED.** "At most one" qualifies the **named** `issue=#<n>` line. `x` counts the tail, per
   L1295 and L1312.
5. **T1 ADV-504: "L655 says tier-resolution failure is exit 3 unconditionally." NOT CREDITED.**
   L969 reconciles §1.3's wording explicitly, and `test_tier_resolution_failure_alone_does_not_discard_candidates`
   (L2246) pins exit 0 with a candidate.
6. **T1 ADV-503, T4 ADV5-4, T2 F-R7-1 (second half): "'under the same per-record query outcomes'
   is circular for transient live failures." NOT CREDITED.** The property is stated per-run, over
   one outcome vector, and quarantine holes are named per record. That is the restatement's
   deliberate scope, and the completeness lens found it has teeth. Its cardinality gap is RP5-3.
7. **T2 F-R7-2: "`--max-api-requests 0` violates the invariant." NOT CREDITED**, on RUN4 §3 item
   3's ground: the stop test refuses Step C's first request, so `api_requests = 0`. The phrase
   *"Step C still runs"* at L1052 is imprecise.
8. **T2 F-R7-3: "D5.3 needs an explicit clamp pre-check."** Rule 4(b)/(c) and F14b already route
   a bite before D5.3's actor step. It's an ordering detail for the coder, not a defect.
9. **T2 F-R7-7: "`UNEVALUATED 0 of N … list-truncated=yes` reads oddly."** It's cosmetic, and the
   revision-7 "or" deliberately forces the line. Not carried.
10. **T1 ADV-505: "L350 'nothing in the tree reads the endpoint' survives."** Plausible, but that
    sentence is about the collaborator **list** endpoint, while `provision_agent_account.sh:190`
    reads a sibling. Not carried as a defect; revision 8 may qualify it.
11. **T1 ADV-508 (frozen dataclass with a mapping field is unhashable).** True of Python, and the TD
    already says "do not hash `TrustedSet`". `field(hash=False)` is a nicety. Not a design defect.
12. **D1 RP5-5 (§0 items cite 19:56:31Z for Q11).** The completeness lens found L2642 corrects the
    residual cites globally. Not credited as a live defect.

---

## 4. The completeness lens

The completeness lens (`claude-fable-5-1`, rank 4) read revision 7 **in full from disk**, plus the
diff, RUN4, RUN3's TP-2/TP-3/TP-6…11, AM-20/21/22/30/31, the live `bin/hos-cron`,
`tests/automation/test_next_candidates.py` and `bootstrap/worker-cron-prompt.md`, and `gh api --help`.
It read #1540 live through `bootstrap/query_issues.sh`. No CLI sat between it and the text, so
#1718 doesn't reach it. **It performed no writes.**

**Its verdict: BUILD-WITH-CONDITIONS.** In its words: *"What genuinely stops `coder` is one
sentence, not a ruling: the fetch wrappers must be told to issue pages one request at a time (F1)
… and §4.2 needs two disposition rows before `test_next_candidates.py` is deleted (F3)."* That is
DO-NOT-BUILD in all but name. **The panel's verdict is the conjunction of the lenses**, as runs 2–4
established, and seven DO-NOT-BUILD chunks with two coder-stopping conditions give DO-NOT-BUILD.

**Its findings map into §1 as:** F1 → RP5-1; F2 → RP5-5; F3 → RP5-2; F4 → RP5-6(a);
F5 → RP5-6(b); F6 → RP5-6(c).

**Considered and rejected by the completeness lens:**

- the literal "if and only if `complete=yes`" wording (already routed to §8/E-12);
- `--max-api-requests 0` with `N = 0` against the `complete` invariant (consistent if a refused
  Step C counts as a truncating bound);
- the "one request later" phrasing at L1206 (imprecise, not wrong);
- quarantine mid-clamp (AM-31's accepted, named hole);
- all-gated-incomplete never firing the #1395 skip (a disclosed cost of AM-32);
- §9.1 and §9.5 "one recovery act" (retained, record-marked revision-6 blocks).

---

## 5. Disposition — and the question for the human

**Class, in the human's terms:** *"a mechanical defect fixable without reopening an architect
ruling is a correction; an architecture disagreement is a round."* **RP5-1 and RP5-2 are
corrections.** RP5-1 changes a mechanism, not a ruled value, and carries one architect
notification (AM-22's literal flag). RP5-3 through RP5-6 are corrections, and none blocks on its
own. **Under the human's rule, the next step is technical-design revision 8 within round 5, then
run 6.**

**What changed this run, stated plainly because it's the trend to watch.** The panel has returned
DO-NOT-BUILD **five times**. But this is the first run where **the previous run's repair held
completely**. Every run-4 blocking finding is verified fixed, and the property-level attacks that
drove runs 3 and 4 found nothing. The blocking items have moved out of the algorithm into its
**plumbing** (a CLI flag's semantics) and its **migration** (a test file that changed under it).
Neither is visible to a design-only read without a live check of the tool or the tree.

**The question for the human — procedural, and yours alone.** The design has been in round 5 since
2026-09-16 on the class rule. The corrections are real, and each run now finds less. **But a
design-only panel will keep finding plumbing, because the plumbing only becomes concrete in code.**
Two options, and the panel recommends neither over the other:

- **(a) Revision 8, then run 6 as usual.**
- **(b) Revision 8, then a scoped run 6 that verifies only RP5-1 and RP5-2 and the register.**
  Anything else would go to the coder's inner loop, where code-reviewer, security-reviewer and the
  cross-vendor second review see the real fetch wrapper.

Option (b) changes what §3(c) requires, so it's your call, not the worker's. Without a ruling, the
worker proceeds with (a).

**Carried, unchanged, from run 4:** R-8's cost question (whether newest-first starvation within a
band was part of the TP-1 trade) is still pending with the human. #1539 is still open, which is
the state the worker restored.

**Nothing in this artifact authorizes a merge, a protected-surface edit, or a line of code.** No
design document was modified by this run, and no issue was filed, labelled or reopened.

---

*Panel run 5 conducted 2026-09-25 by the autonomous worker (`hos-worker-hos[bot]`) at repo head
`c79b79a18`. Adversarial lens: agy 1.2.11 (google), seven sentinel-verified chunks. Completeness
lens: claude-fable-5-1. Orchestrator: claude-opus-5-5 — rank-equivalent to the bundle's authors,
a standing independence limitation of all five runs.*
