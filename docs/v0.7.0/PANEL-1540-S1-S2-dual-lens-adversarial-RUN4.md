# PANEL-1540 (S1 + S2) — dual-lens adversarial panel, **FOURTH RUN**, against technical-design revision 6

```yaml
verdict:                              DO-NOT-BUILD
non_convergence:                      NOT DECLARED — every blocking finding is class "mechanical correction"
                                      (the human's own test, TD §9 rev-6 block); none reopens an architect ruling
escalates_to:                         technical-design (revision 7, within round 5) — plus TWO
                                      input-to-human items (§5): R-8's cost, and #1539's closure
gate:                                 TD-1540 §9 (run-4 scope) under ADR-1540-AMENDMENT-4 §3(c)
supersedes:                           none (runs 1–3 stand as written)
bundle_under_review:                  TECHNICAL-DESIGN-1540 rev 6 (ba4c1d7ea; file sha256_16 9a00649031808027)
                                      + the rev-5 → rev-6 diff (cf37b8bbe..ba4c1d7ea)
repo_head:                            99c9e3e3b
adversarial_cli:                      agy 1.2.3 (google — cross-vendor)
adversarial_invocation:               scripts/oversight/lib/vendor_invoke.sh, stdin, --sandbox --output-format json
adversarial_mode:                     7 chunks, each MEASURED consumed whole (3 sentinels echoed + input_tokens) — §0.2
completeness_cli:                     claude (Agent tool)
completeness_model_resolved:          claude-fable-5-1 (rank 4; bundle authors rank 3)
orchestrator:                         claude-opus-5-5 (rank 3 — SAME rank as the bundle's authors; §0.3)
timestamp:                            2026-09-25
```

**Status: DO-NOT-BUILD. `coder` is NOT cleared to build S1 or S2.**

**The one-paragraph version.** Revision 6's TP-1 change (walk key `(rank, number DESC)`) reached
every site the lenses checked, and TP-5/Q11/Q12/H6 are recorded correctly. **The TP-4 repair did not
hold.** The rescoped ADMISSION property — and the "unconditional" rank-dominance claim revision 6
leans on to say nothing was weakened — are **both false under D5.3's quarantine-and-continue and
D5.2's budget clamp**, which revision 5 introduced and no run has attacked against the new wording.
Five of seven independent agy chunks found it. Separately, **run 3's confirmed TP-2 and TP-3 were
dropped without a disposition** (zero occurrences of either ID in revision 6), and **F30 contradicts
the exit-3 contract** on the path the cutover will take most often. **Every blocking item is a
specification correction, not an architecture disagreement** — which is the class the human ruled
is fixed within round 5 (§5).

**And one live-state finding outside the design: #1539 — the design's S2 work item, an open
`priority:critical` security issue — was closed on merge of revision 6's own PR** by a closing
keyword inside a quoted ruling (RP4-7). The fix was never built. The worker has reopened it and filed
the tooling gap as #1856.

---

## 0. How this panel ran

### 0.1 The instrument defect is controlled this time — measured, not asserted

Run 3 proved the cross-vendor lens silently truncates oversized input and reports SUCCESS (#1718,
still open). Run 4 therefore never sent agy more than ~184 KB, and **proved consumption per call**:
each chunk carried three sentinels (start, exact middle, end) derived from a hash of the chunk tag,
and each response had to echo them. All 21 sentinels came back.

### 0.2 What each lens actually read

| Lens / chunk | Material | Bytes | `input_tokens` | Sentinels echoed | Verdict |
|---|---|---|---|---|---|
| agy D1 | rev5→rev6 diff, part 1 of 2 | 182,297 | 67,465 | 3/3 | DO-NOT-BUILD |
| agy D2 | rev5→rev6 diff, part 2 of 2 | 74,369 | 37,849 | 3/3 | DO-NOT-BUILD |
| agy T1 | TD rev 6 L1–724 | 183,298 | 73,514 | 3/3 | DO-NOT-BUILD |
| agy T2 | TD rev 6 L695–1463 | 183,793 | 69,433 | 3/3 | DO-NOT-BUILD |
| agy T3 | TD rev 6 L1434–2216 | 183,965 | 71,745 | 3/3 | DO-NOT-BUILD |
| agy T4 | TD rev 6 L2187–2734 | 183,855 | 68,061 | 3/3 | DO-NOT-BUILD |
| agy T5 | TD rev 6 L2705–2909 | 82,369 | 40,824 | 3/3 | DO-NOT-BUILD |
| completeness (fable) | full repo, from disk; live GitHub reads | — | n/a (no CLI path) | n/a | see §4 |

Chunks overlap by 30 lines. Every line was prefixed `L<n>:` so citations are checkable. All seven
agy calls ran in parallel; each chunk's prompt carried the human's run-3 rulings and the §9 attack
list. Prompt sha256_16: D1 `4ae569f3394dc16e`, D2 `fdb1cf8c684f5f7b`, T1 `8f7fa272edd416f0`,
T2 `7759fa45e7378bb6`, T3 `bfc58e6bffd3b531`, T4 `13340abb45a7d07c`, T5 `7ba9db19b6626b63`.

**A data point for #1718, recorded because it narrows that issue's hypothesis.** T1 consumed
**73,514** tokens whole, above the ~68k at which run 3's 793 KB single shot was cut. The limit is
therefore not a plain input-token ceiling at ~68k; it's more likely a byte or request-size bound
on the prompt as submitted. Bytes per token here were 2.0–2.7 (line-number prefixes and dense
markdown), not the ~4 assumed in run 3's back-of-envelope check. **So a bytes/4 consumption
heuristic under-estimates tokens for this material; the sentinel echo is the check to trust.**

### 0.3 What to distrust in this artifact

1. **The orchestrator is rank-equivalent to the bundle's authors** (opus). Unchanged from runs 1–3.
2. **Chunked reads cannot see documents against each other.** The two diff chunks partly
   compensate, since each shows old and new text side by side. But nothing here re-read the ADR
   amendments against revision 6. The completeness lens (§4) is the cross-document reader.
3. **I verified every credited finding at the line** (§1 "Verified at"), per §9.4 instruction 3.
   Rejections are in §3.

---

## 1. Findings

### RP4-1 — CRITICAL — the ADMISSION property and "unconditional" rank dominance are both false under D5.3 quarantine and the D5.2 budget clamp. **BLOCKING. Class: mechanical correction.**

**Found independently by D1, D2, T1, T2, T3 and T4** — six of seven agy chunks, sharing no text
except the prompt header — **and by the completeness lens (F1)**, through a different route (the
clamp) and with a different verdict on the quarantine route. Both are recorded below.

- **The claim (L1114):** *"for any stop point `k`, the SET of candidates the walk ADMITTED equals
  the first `k` eligible elements of the ranked walk over the candidate set Step C returned."*
- **The claim (L1123):** rank dominance — *"nothing omitted by the walk outranks anything
  emitted … **This half is unconditional.**"* L1118 then rests revision 6's "nothing is weakened"
  argument on exactly this: *"Rank dominance is a property of the SET."*
- **The mechanism that falsifies both (L1136, rev 5, AM-31):** a transport error / non-zero exit /
  unparseable events response → *"QUARANTINE THE RECORD AND CONTINUE THE WALK."*
- **The second mechanism (L1130–1132):** the events fetch is clamped to
  `min(EVENTS_PAGE_BOUND, effective_ceiling − api_requests)` pages, and a clamped fetch with no
  match *"is identical"* to the page-bound case → **gated** (TP-2, RP4-3).

**Counterexample 1 — the budget clamp. Both lenses agree, and it breaks the binding test.** This one
is the completeness lens's (F1), and the orchestrator re-derived it by hand. Same rank: `#30`
untrusted, with its authorizing `labeled` event on events **page 2**; `#20` trusted-authored; `#10`
untrusted, authorized on page 1. `--max-api-requests 2` (legal; the ceiling may only be lowered).
**Bounded run:** list page → counter 1; `#30`'s fetch is clamped to 1 page, no match → **gated**
(L1132), counter 2; `#20` costs nothing (D4) → **admitted**; `#10` needs a request → ceiling stop.
Admitted `{#20}`. **Unbounded run:** `W = [#30, #20, #10]`.
`test_admitted_set_is_a_prefix_of_the_complete_walk` asserts `{#20} == set(W[:1]) = {#30}` —
**fails.** At default bounds the same shape needs a ~99-request fixture. That's still
constructible, and it describes live traffic (M-1). **Beyond the test: a `priority:critical` record a
complete walk would authorize is reported as held for human authorization**, which is the false
statement AM-20 exists to prevent. This is run 3's TP-2, now a counterexample to the repair itself
(RP4-3).

**Counterexample 2 — quarantine. THE LENSES DISAGREE, and the disagreement is the defect.**
Same-rank `#30, #20, #10`, all authorized; `--max-candidates 1`. `#30`'s events query 502s →
quarantined, walk continues; `#20` → admitted; stop. Admitted `{#20}`, first-1 of the walk `{#30}`.
**Five agy chunks call this false. The completeness lens calls the property TRUE here**, reading
"eligible" as *determined eligible in the same run*: against a deterministic stub the unbounded run
quarantines `#30` too, so `W` excludes it. **Both readings are available from L1114's text, and
under the ground-truth reading it is false.** The property has to say which reading it means. A
safety sentence that is true or false depending on the reader is the RP-16 shape (*"the surviving
statement MUST be the true one"*).

**Counterexample 3 (rank dominance, T2).** `#1678` (critical, authorized) and `#1600` (medium,
authorized). The walk visits `#1678` first; its query fails → quarantined, continue; `#1600`
admitted and emitted. **An omitted record outranks an emitted one.** L1123's "unconditional" is
false, and so is L915's *"Nothing omitted can outrank anything emitted survives a stop at any
position."* The stop didn't do this. The *hole* did. (The completeness lens accepted "rank dominance
is a property of the SET" *as worded*, and noted that under the clamp it survives **only by
vocabulary**: the mis-determined record is "gated", not "omitted". A quarantined record *is* omitted
— it is `unevaluated` — so no vocabulary rescues the quarantine case.)

**Why it is not an architecture finding.** AM-31 ruled the *behaviour*: quarantine-and-continue,
because halting "buys zero security and costs all new issue work". The behaviour is safe: no
input to this path produces an authorization (L1142), and I agree. **What is wrong is the
property sentence, which never admitted that the walk can have holes.** AM-31 even named the
consequence (*"a partial list can silently demote a `priority:critical` item"*, L1140) and met it
by reporting. So the sentence contradicts a ruling already in the chain. Revision 6's §9.5 named
this exact sentence as its own top candidate; the candidate was right.

**Minimal remedy, in two parts.** **(i) The clamp — run 3's own TP-2 remedy, which both lenses
endorse:** a clamp that bites before a match is `unevaluated:cost-ceiling issue=#<n>`, never
`gated`, and it **is** the ceiling stop: the walk ends, and nothing is admitted after it, trusted or
otherwise. Then the admitted set is `W[:j]` under every stop. Sites: L667, L936, L1130–1132, L1579,
L1854, L2040–2046. This reopens nothing. AM-5 (page bound → gated) is untouched, and AM-20 (*"a
record the walk never reached is unevaluated"*) is being applied. **(ii) Quarantine:** restate both halves over
**determinations**: *the admitted set is the first `k` records the walk DETERMINED eligible, in
walk order; every record it stepped over without a determination is named on its own
`unevaluated:query-failed issue=#<n>` line and forces `complete=no`.* Then restate rank dominance as
*"nothing the walk DETERMINED and did not admit outranks anything admitted; a quarantined record
may, and is named."* The alternative is to halt the walk on quarantine. That reopens AM-31, which
is an architecture question, so **the panel recommends the restatement.** Also, §6.2 needs a test
that quarantines a higher-ranked record and asserts the lower one is emitted **and** that the
`WARN … issue=#<n>` line names the higher one. Nothing in §6.2 currently exercises a hole.

*Verified at:* L915, L1063, L1114, L1118, L1123, L1130–1132, L1136, L1140–1142, L2043–2046.

### RP4-2 — HIGH — F30 contradicts the exit-3 contract on the cutover's most common path. **BLOCKING. Class: mechanical correction.**

*Found by T3; verified at the line by the orchestrator.*

- **F30 (L1595):** every candidate gated (`eligible==0`, `gated>0`) → **exit 0**, *"Never an exit
  code"*, and *"when `complete=no`, the block MUST carry the fourth `INCOMPLETE` line."* So F30
  explicitly covers `complete=no` and still says exit 0. `test_all_gated_still_exits_zero` (L2092)
  pins it.
- **§5 interface (L1839):** *"exit 3 IFF complete=no AND stdout empty (AM-32)."*

An all-gated walk that stops on the request ceiling has `complete=no` and an empty stdout, so it
satisfies both rows, and the two rows demand different exit codes. **That's the ordinary cutover
state:** measured today (§2), 149 candidates, of which 145 need one or more paid events requests,
against a ~100-request ceiling. So an all-gated cycle **cannot** be `complete=yes` at this
population. If F30 wins, `bin/hos-cron` sees exit 0 with empty stdout and takes the "no actionable
work" path — the exact outcome AM-32 exists to prevent.

**Remedy:** amend F30 and its test so exit 0 is conditioned on `complete=yes`, and the
`complete=no` all-gated case exits 3. The block and the `INCOMPLETE` line are unchanged.

### RP4-3 — HIGH — run 3's confirmed TP-2 and TP-3 were dropped without a disposition. **BLOCKING (process). Class: mechanical correction.**

Found by D1, D2, T1, T2, T3 and T4. **Verified: "TP-2" and "TP-3" each occur zero times in
revision 6.** Neither is in the §0.0 revision-6 coverage map, §7.2, §8 or §9.

- **TP-2 still stands at L1132:** a budget-clamped fetch *"is identical"* to the page-bound case →
  `gated`, counted as a determination. That contradicts AM-20 point 3 (L1242: an unevaluated record
  counted as "held for human authorization" *"is a false claim about a person's queue"*), and it
  also drives RP4-1.
- **TP-3 still stands at L1199:** `unevaluated:list-truncated=<y>` sits inside `UNEVALUATED <U> of
  <N>`, but `N` is *"records returned by Step C"* (L1184). A record Step C never returned can't be
  in `N`, so `N = E + U` (L1189) breaks, and `<y>` is a count AM-31 forbids deriving (L885, L1040).

Run 3 gave both remedies (§5.2 of RUN3): the `unevaluated:cost-ceiling issue=#<n>` token for TP-2,
and a boolean or removal from the `U` sum for TP-3. **The human ruled only on TP-1/4/5 because only
those were put to them. Silence on TP-2/3 was not a ruling to drop them.** This is the "silent
removal" failure §9.3 was written to prevent, and it happened between runs rather than inside a
register.

### RP4-4 — MEDIUM — the rewritten differential test is vacuous on its fixture and derives `W` from a log that omits trusted records. **Class: mechanical correction.**

Found by D1, D2, T1, T3, T4 and T5. The orchestrator verified two of the lenses' three claims:

1. **Vacuous as specified (verified, L2042).** It runs *"once with the default bounds"*. The default
   `--max-candidates` is 5. The emission-order fixture has **three** records, so the bound never
   bites and the test compares a set with itself. The TP-4 check §9.1 item 9(c) asked for passes,
   but only trivially. **Remedy:** mandate `--max-candidates` below the eligible count (e.g. 1 and
   2 over a ≥3-record fixture).
2. **`W` is under-derived (verified, L2043 vs L1063).** `W` is recovered *"from the `gh` stub's call
   log"*. D4 makes a trusted-authored record eligible with **zero** API calls, so it never appears
   in that log. On any fixture with a trusted record (e.g. limb (d)'s), `W` is wrong. **Remedy:**
   take walk positions from the fixture itself, sorted by the binding key, or from a test-only walk
   trace. Don't use the request log.
3. **Not credited:** D2's and T2's claim that the test is **unsatisfiable**. Those lenses compared
   bounded stdout with a slice of *unbounded stdout*, which is the retired revision-5 form. The
   revision-6 assertion compares against `W`. **The completeness lens confirmed it satisfiable on the
   emission-order fixture** (k=1: `{#30} = W[:1]`; k=2: `{#30,#20}`, stdout `[#20,#30]`). It stays
   satisfiable in general only once RP4-1(i) is applied. Until then, the clamp fixture in RP4-1
   fails it.

### RP4-5 — MEDIUM — R-8's "surviving recovery act" doesn't exist for `priority:critical`, and doesn't reliably work anywhere. **Non-blocking. Class: documentary — plus one input-to-human question (§5).**

Found by D1, D2, T1, T2, T4 and T5. Verified at L924 and L1171.

- The recovery act is *"changing a record's rank"*. **For rank 0 (`priority:critical`) there is no
  higher rank.** Old criticals behind ≥5 newer eligible criticals have no recovery act at all.
- For lower ranks, a promoted record enters the new band **at its own (low) number**, so under
  `number DESC` it lands at that band's tail. **It is reached only if fewer than 5 newer records in
  that band are eligible.** The act works only when the band is nearly empty.
- **The FIFO overclaim (T5, L1161).** *"Step E is the single line that converts the walk order into
  that contract"* (#901's FIFO-within-band). Under the early exit, Step E sorts **the newest ≤5
  eligible records** of a band. Across cycles, selection is **LIFO-within-band**, and FIFO holds
  only inside the admitted slice. L1159 and R-8 do name the oldest-tail starvation, so this is an
  overclaim at one site, not a hidden defect.

- **The tail is large and the gate cannot name it (completeness lens F4).** Counted per band
  (server-side, each band under the 100 cap): a fully-gated walk under `(rank, number DESC)` covers
  band 0, all ~80 high and roughly the 16 highest-numbered medium records before the ~100-request
  ceiling. **About 40 medium, 7 low, and every unlabelled record are never evaluated, on any
  cycle.** The only per-record `unevaluated` line is `query-failed` (L1200–1201).
  `cost-ceiling=<x>` is a bare count, and `ALL-CANDIDATES-GATED issues:` names gated records only
  (L1211). **So an operator who wanted to apply even the partial recovery act can't find out which
  record to re-rank.** The act's efficacy also depends on the population: promoting to `high` puts
  an old record at about position 83 today, which is reached, but not once band 1 exceeds ~96.

**Remedy:** strike "recovery act" in favour of "none within a band; for rank 0, none at all";
correct L1161 to "FIFO within the admitted slice"; emit a bounded `UNEVALUATED issues:` line (first
N plus "k more") or at least the boundary record; and state the tail formula instead of "coarser"
(L2312). Beyond that, this is the human's question (§5).

### RP4-7 — HIGH — the design's S2 work item, #1539, was CLOSED by accident; the worker has reopened it. **Input to human. Class: neither — a live-state defect, not a design defect.**

*Found by the completeness lens (F5); root cause established and remedied by the orchestrator.*

The TD's premise (L22: *"an open `priority:critical` security issue"*), H6, and §7.2's obligation to
post R-1/R-3/R-8 **on #1539** (L1647, L2331) all assume #1539 is open. **It was closed on
2026-09-17 at 02:57:53Z, one second after PR #1725 (this TD's revision 6) merged at 02:57:52Z,**
`state_reason: completed`, attributed to the merging account. **Line 60 of #1725's PR body quotes the
human's H6 ruling verbatim, "S2 is the fix that c‌loses #1539", and GitHub parsed the quotation as a
closing keyword.** The S2 code does not exist on `main`, so the security gap #1539 describes stayed
live for 8 days while its issue read `completed`.

**Remedy applied this run (state only, reversible):** the worker reopened #1539 with the evidence in a
comment, and filed the tooling gap as **#1856** (`submit_pr.sh` does not detect unintended closing
keywords — a recurring hazard in a repo whose practice is to quote rulings verbatim). **This
artifact's own PR body avoids the phrase.** If the human intended the closure, they should re-close
it and re-home the S2 work item.

### RP4-8 — MEDIUM — the TP-4 remedy is attributed to the human; it was the panel's. **Non-blocking. Class: mechanical correction (provenance).**

*Found by the completeness lens (F3); verified by the orchestrator against the live #1540 thread.*

L10 (precedence **level 0**: *"the TP-4 remedy (specification reconciliation, designer's choice of
limb)"*), L59 (*"HUMAN — TP-4: fix by specification reconciliation, 'one of two paragraphs
gives'"*) and L2721 (*"The human ruled the remedy … and left the choice to me"*). **Those words are
RUN3:652, the panel's.** The human's 19:55:45Z comment says, on TP-4, only that the round
classification *"still need[s] your call"*. The 19:56:31Z comment rules that *"TP-4 and TP-1 get
fixed within the existing round 5 scope."* **No remedy was ruled.** That matters because level 0
outranks the architect. A panel recommendation has been promoted above AM-29 by attribution. It's the
mirror image of the TP-5 provenance error revision 6 correctly fixed. **Remedy:** re-attribute at all
three sites. The limb choice is the designer's, on the panel's recommendation, and ranks where
designer choices rank.

### RP4-6 — LOW/MEDIUM — documentary defects, each verified at the line. **Non-blocking. Class: mechanical correction.**

| # | Site | Defect | Found by |
|---|---|---|---|
| a | L445–460 vs L614 | `TrustedSet.tier_members` is a bare `frozenset[str]`, but step 3(iii) says the login→tier **mapping** *"is passed in with the TrustedSet"*. No field carries it, so `roster-tier:<tier>` can't be computed as typed | T1 |
| b | L547 | `tier:Write` is listed as a malformed line to be skipped, then the parenthetical says it is **accepted**, and adds *"the example above is for a token that is not one of the five"* — false for `tier:Write` | T1 |
| c | L2170 vs L1642 (5) | `test_labels_doc_states_milestone_route_is_forbidden` still asserts the **Step 0 race as the stated reason**; §4.3 statement (5) demotes the race to *"the historical reason… not as the reason it is refused"* (AR-7) | T3 |
| d | L2493 (§8/E-2) | still says R-1, R-3 **and R-7** go into the S2 work item; §4.3 (L1647) and §7.2 say R-7 is retired and R-8 replaces it | T4 |
| e | L2448 | §8's E-7 row still describes AM-18's skip and diagnostic as live; the rule was retired by AM-35 (L2556) | T4 |
| f | L2607 (§8/E-8) | *"Prefix-correctness holds at any ceiling"* — an unqualified rev-4 sentence §0.0's rev-6 sweep says must not survive unqualified | T4 |
| g | L875 | still describes the caller as `if _GATE_CANDIDATES=$( … )`; §2.4 (L1259–1265) replaced it with an explicit `case "$_gate_rc"` | T2 |
| h | L2252, L2716 | still say the overseer's consumption is *"unaccounted"*; run 3's M-5 measured it as a separate App with its own bucket. The TD never absorbed M-5 | T4 (see §3) |
| i | L1938 (§6.1) | `test_tier_matching_is_exact_not_hierarchical`: a rev-5 fragment (*"rather than the human's (they ruled the tokens, not the ordering) …"*) was left outside the strike-through, so the TP-5 note reads backwards | D1 |
| j | L2316, L940, L961 | *"The population (101) is already past the ceiling (100)"* confuses **records** with **requests**. At 101 records, 4 free and 2 list pages, a full walk costs 99 ≤ 100, so the ceiling did **not** bind at 101 or 102. It does bind now (M-1). Right conclusion today, invalid derivation — the class §2.2.1 (L978) itself warns against | fable F6 |
| k | L2172, L2501; L978 | Run 3's **TP-9** and **TP-10(ii)** were also dropped without a disposition: the phantom `test_jq_label_literals_match_hos_labels` is still cited (absent from `tests/`), and L978 still calls UWP:448 *"the only in-repo statement"* of 5,000/hr (`docs/specs/UNATTENDED-WORKER-TECH-DESIGN.md:256` also states it). **TP-8**'s rev-5 map row → §2.7.2 has no RP-22-style correction paragraph | fable F7 |
| l | L31, L57, L61–63, L326 | five coverage-map rows cite a *"§9 gate table"*; §9 has none. The table changed is under "Human Review Required" (L2878–2897). Changed-but-misnamed, not claimed-but-unchanged; **every other rev-6 row was verified changed in the diff** | fable F9 |
| m | L2039 | limb (d)'s fixture (*"exhausted at position 12; trusted at 30 MUST NOT be emitted"*) holds only if an untrusted record lies between 12 and 30, because the ceiling stop fires at the next *attempted* request (L955). Say so in the fixture | fable F10(a) |

---

## 2. Orchestrator measurements

**M-1 — population (paginated `issues?milestone=2&labels=needs-ai`, 2026-09-25 ~07:00Z).**
**151** open issues, **2** also `needs-human` → **149** candidates. Rank bands: critical **1**,
high **79**, medium **56**, low **13**. Oldest `#1335`, newest `#1853`. Up from 102 at run 3 (9
days, +49). The 500-record list bound doesn't bind. **The ~100-request ceiling does bind on any
walk that must pay for more than ~99 records**, and that's the fact RP4-2 turns on.

**M-2 — trusted-author fast path.** Unchanged: 4 of the candidate population are `ScottThurlow`'s
own filings (E-10's narrow reading, confirmed by run 3's M-2). So ~145 records each need ≥1 paid
events request.

---

## 3. Rejected or not credited

1. **T4 F7 — "overseer API consumption is unaccounted, could exhaust the installation limit."
   REJECTED on measurement** (run 3 M-5): the overseer is a separate GitHub App with its own
   5,000/hour bucket. The *text* claiming it's unaccounted is stale, and survives as RP4-6(h).
2. **T1 F7 — "dormant machine-filing markers match at runtime (fail-open)." NOT CREDITED.** L622
   states it as a deliberate choice with its reason (*"a dormant emitting site that is re-enabled
   must not silently break"*). A marker only matters for an App-authored record (AD-2), so this is
   A1's surface, already carried in §9.2, not a new defect.
3. **T2 ADV-7 — "`--max-api-requests 0` contradicts L1036's exit 2." NOT CREDITED.** A ceiling of 0
   means Step C's request is *never issued*. That's a D5.1-class budget stop, not a list-query
   *failure*, so `complete=no` → exit 3 is consistent.
4. **T5 ADV-6 / D2 ADV-407 — "exit 0 with `complete=no` and non-empty stdout masks incompleteness."
   NOT CREDITED.** It's the designer's recorded §8/E-9 choice. The caller has real work, and the
   stderr summary still carries `complete=no`. The harmful variant — **empty** stdout — is RP4-2.
5. **D2 ADV-405 / T5 — "walk in `(rank, number ASC)` instead."** **Not a defect finding.** It asks
   to revisit the human's TP-1 ruling. It is carried as input to the human in §5, with AM-29's own
   objection to ASC attached (it starves the *newest* tail permanently instead).
6. **T3 F8 — "D4 is an eager pre-pass, contradicting limb (d)."** **Not credited as a defect.** The
   D-step table lists D4 before D-rank, but D5.1 (L1109) and limb (d)'s test (L2039) are explicit
   that nothing is admitted after a stop. At most it's an ordering ambiguity in the §5 comment
   block. Noted for revision 7, not carried.
7. **RP4-4 point 3** (the test "unsatisfiable") — see RP4-4.

---

## 4. The completeness lens

The completeness lens (`claude-fable-5-1`, rank 4) read revision 6 **from disk** — §0 header, §0.0,
§0.0.6, §2.2–§2.3, §2.6, §6.2, §7.2, the §7.3 rev-6 block, §8/E-11 and all of §9 — plus the full
rev5→rev6 diff, RUN3's TP-2/TP-3/TP-6…11 and §5, and AM-29 in Amendment 4. It did live reads through
`bootstrap/query_issues.sh` (#1540's rulings, #1539, #1678, the six §2.6 issues, per-band counts).
No CLI sat between it and the text, so #1718 doesn't reach it. It reported ~250k tokens consumed,
tool output included. **It performed no writes.**

**Its verdict: BUILD-WITH-CONDITIONS** — *"What genuinely stops `coder` today: F1 … and F5."* That
is the panel verdict in all but name. **The panel's verdict is the conjunction of the lenses, as
runs 2 and 3 established**, and the conjunction with seven DO-NOT-BUILD chunks is DO-NOT-BUILD.

**Its findings map into §1 as:** F1 → RP4-1 (clamp counterexample) and RP4-3; F2 → RP4-3 (TP-3);
F3 → RP4-8; F4 → RP4-5; F5 → RP4-7; F6, F7, F9, F10(a) → RP4-6 (j), (k), (l), (m); F8 → RP4-6(f);
F10(b) → RP4-4(1).

**Verified TRUE by the completeness lens — the part of revision 6 that holds:**

| Claim | Result |
|---|---|
| AM-29 states `(rank, number DESC)` as its own fallback (Amendment 4:106) | TRUE |
| The human's run-3 rulings as quoted (TP-1, TP-5, "Correction, not round 6", Q11/Q12/H6) | TRUE verbatim — **but they contain no TP-4 remedy** (RP4-8) |
| `(rank, number DESC)` is total by construction; limb (b) needs no tie-break (L1128) | TRUE — the one unambiguous gain from TP-1 |
| Admission property under early exit, ceiling stop without clamp, and list bound | TRUE each |
| `test_admitted_set…` satisfiable on the emission-order fixture | TRUE (but vacuous at default bounds — RP4-4) |
| The three quoted `updated_at` carve-outs carry superseded markers (L91, L897, L1153) | TRUE — **the TP-1 sweep reached every load-bearing site** |
| Step E's "both bounds compound on the oldest records" (L1159, L2314) | TRUE |
| TP-11 corrected at every site; TP-5 provenance corrected | TRUE |
| Re-fusion hazard is one token and one test (L2823) | TRUE |

**Could not verify:** the count of records with no `priority:*` label (no label-free query path under
the 100 cap; the orchestrator's paginated M-1 supplies it — 13 `low` including unlabelled); why #1539
closed (the orchestrator established it — RP4-7); `provision_agent_account.sh:190` (verified by run 3,
not re-derived).

**Considered and rejected by the completeness lens:** E-11's "nothing else moves" vs the 10-section
coverage row (E-11 is conditional on an architect disagreement); "exactly three carve-outs" (the
other old-key occurrences at L321, L1165, L2301, L2659 are all marked or struck); 101 vs 102 as a
contradiction (both are dated measurements); the early-exit non-conflict argument at L917–918 (it
holds).

---

## 5. Disposition — and the one question for the human

**Class, in the human's terms (TD §9 rev-6 block):** *"a mechanical defect fixable without
reopening an architect ruling is a correction; an architecture disagreement is a round."* **RP4-1,
RP4-2, RP4-3 and RP4-4 are all corrections.** RP4-1's recommended remedy deliberately restates the
property rather than changing AM-31's behaviour. Nothing here asks the architect anything. **Under
the human's own rule, the next step is technical-design revision 7 within round 5, then run 5.**

**The count, stated plainly because it's the thing to watch:** the panel has now returned
DO-NOT-BUILD **four times**. Run 4's blocking finding sits **in the repair of run 3's blocking
finding**, in a sentence revision 6 itself nominated as its weakest. The findings are shrinking in
kind: run 3 had a walk key the public could write, run 4 has sentences that don't match rulings
already made. But they're not shrinking in count. **Whether that continues under round 5 is the
human's call, not the panel's.**

**One non-blocking question for the human (RP4-5).** The TP-1 ruling traded away
promotion-on-authorization. The trade put to the human in run 3 §5.3 didn't state the other cost of
`(rank, number DESC)` combined with the early exit at 5: **selection becomes newest-first within a
band, and the oldest authorized records in a busy band — including old `priority:critical` ones —
have no act that reaches them.** At today's population the high band holds 79 records. **The
panel isn't asking to reverse the ruling.** It's asking whether that cost was part of what was
accepted. If not, the options already in the chain are: (a) keep `DESC` and accept it; (b) walk
`ASC` (AM-29's objection: starves the newest instead, and Step E becomes a no-op); or (c) raise the
early-exit stop. Each is the human's call.

**Second input-to-human item (RP4-7): confirm #1539 should be open.** The worker reopened it on the
evidence: closed one second after #1725 merged, by a quoted closing keyword, with the fix unbuilt. If
the closure was intended, re-close it and name the S2 work item's new home on #1540.

**Nothing in this artifact authorizes a merge, a protected-surface edit, or a line of code.** No
design document was modified by this run. **Writes made outside this artifact:** #1539 reopened
(state only) with an evidence comment, and **#1856** filed for the closing-keyword tooling gap.

---

*Panel run 4 conducted 2026-09-25 by the autonomous worker (`hos-worker-hos[bot]`) at repo head
`99c9e3e3b`. Adversarial lens: agy 1.2.3 (google), seven sentinel-verified chunks. Completeness
lens: claude-fable-5-1. Orchestrator: claude-opus-5-5 — rank-equivalent to the bundle's authors,
a standing independence limitation of all four runs.*
