# PANEL-1540 (S1 + S2) — dual-lens adversarial panel, **SIXTH RUN**, against technical-design revision 8

```yaml
verdict:                              BUILD-WITH-CONDITIONS
non_convergence:                      NOT DECLARED — no finding reopens an architect or human ruling
escalates_to:                         coder (S1, then S2), carrying conditions C1–C4 (§5) as binding
                                      acceptance items; no technical-design revision required
gate:                                 TD-1540 §9 (revision-8 block: run 6's scope) under ADR-1540-AMENDMENT-4 §3(c)
run_6_scope:                          (a) FULL — no human ruling on RUN5 §5's question as of 2026-09-26T00:25Z,
                                      so the TD's stated default applied
supersedes:                           none (runs 1–5 stand as written)
bundle_under_review:                  TECHNICAL-DESIGN-1540 rev 8 (59ff4027d; file sha256_16 c94b94fca8e521e7)
                                      + the rev-7 → rev-8 diff (703098349..59ff4027d)
repo_head:                            59ff4027d
adversarial_cli:                      agy 1.2.11 (google — cross-vendor)
adversarial_invocation:               scripts/oversight/lib/vendor_invoke.sh, stdin, --sandbox --output-format json
adversarial_mode:                     8 chunks, each MEASURED consumed whole (3 sentinels echoed + input_tokens) — §0.2
completeness_cli:                     claude (Agent tool)
completeness_model_resolved:          claude-fable-5-1 (rank 4; bundle authors rank 3)
orchestrator:                         claude-opus-5-5 (rank 3 — SAME rank as the bundle's authors; §0.3)
live_checks:                          two GitHub REST page seams + the per_page clamp, read-only (§0.4)
timestamp:                            2026-09-26
```

**Status: BUILD-WITH-CONDITIONS. `coder` may build S1, then S2, carrying conditions C1–C4 (§5).**

**The one-paragraph version.** **The revision-8 repair held.** Each bounded fetch now issues one
request per page, and the stop test runs before every page, so `api_requests <= effective_ceiling`
holds by construction. The end-of-history discriminant is explicit for single-page and
exact-multiple histories, **and this run checked it against the live API** (§0.4). No site
prescribes `--paginate`, and nothing reads `Link`. "Bites" is decidable from page lengths and the
counter. Every class and test in `test_next_candidates.py` has a §4.2 row, and the RP5 register is
complete. **Seven of eight agy chunks and the completeness lens returned BUILD-WITH-CONDITIONS.** The
one DO-NOT-BUILD chunk (D1) rested on a HIGH finding refuted at the line (§3, rejection 1). What
remains are three MEDIUM gaps, each fixable inside the S1/S2 PRs, plus LOW and documentary items:
- **RP6-1:** revision 8's new Step C REFUSED state has no §3 row and no test.
- **RP6-2:** §5's `fetch_collaborators` signature can't run the stop test it is bound by.
- **RP6-3:** on the default consumer path, the F4a token is unreachable behind B1.

---

## 0. How this panel ran

### 0.1 The instrument defect is controlled again — measured, not asserted

#1718 (agy silently truncates oversized input and reports SUCCESS) is still open. Run 6 repeated
the control that runs 4 and 5 used, as TD §9's revision-8 block binds it to. No chunk exceeded
~186 KB. Each chunk carried three sentinels (start, exact middle, end), derived from a hash of the
chunk tag, and each response had to echo them. **All 24 sentinels came back.** No response was an
empty `denied_actions` envelope.

### 0.2 What each lens actually read

| Lens / chunk | Material | Bytes | `input_tokens` | Sentinels echoed | Verdict |
|---|---|---|---|---|---|
| agy D1 | rev7→rev8 diff, part 1 of 2 | 183,162 | 71,765 | 3/3 | DO-NOT-BUILD (rests on refuted ADV-603) |
| agy D2 | rev7→rev8 diff, part 2 of 2 | 48,410 | 31,958 | 3/3 | BUILD-WITH-CONDITIONS |
| agy T1 | TD rev 8 L1–666 | 185,517 | 76,005 | 3/3 | BUILD-WITH-CONDITIONS |
| agy T2 | TD rev 8 L637–1294 | 185,243 | 70,046 | 3/3 | BUILD-WITH-CONDITIONS |
| agy T3 | TD rev 8 L1265–2014 | 185,498 | 71,692 | 3/3 | BUILD-WITH-CONDITIONS |
| agy T4 | TD rev 8 L1985–2634 | 183,649 | 71,074 | 3/3 | BUILD-WITH-CONDITIONS |
| agy T5 | TD rev 8 L2605–3170 | 185,456 | 69,948 | 3/3 | BUILD-WITH-CONDITIONS |
| agy T6 | TD rev 8 L3141–3377 | 88,362 | 42,930 | 3/3 | BUILD-WITH-CONDITIONS |
| completeness (fable) | full TD from disk (13 slices), the diff, RUN5 in full, live `bin/hos-cron`, `worker-cron-prompt.md`, `probe.py`, `github.py::_run_gh`, `test_next_candidates.py`, `docs/LABELS.md`; `gh --version`, `gh api --help` | — | ~365k reported (tool output included) | n/a | BUILD-WITH-CONDITIONS |

Chunks overlap by 30 lines. Every line was prefixed `L<n>:` so citations are checkable. All eight
agy calls ran in parallel, and each prompt carried the binding rulings plus §9's revision-8 attack
list. Prompt sha256_16: D1 `4e69d3ddb8ee3cd9`, D2 `ebb3f669cb2983a4`, T1 `4bea7f1e644c3899`,
T2 `7726a4c4a57eca6c`, T3 `b90d257748bad89d`, T4 `1f8d85eea4e33402`, T5 `934755edde1d60ce`,
T6 `9318313696aff291`.

**#1718 data point:** T1 consumed **76,005** tokens whole, the highest of any run so far (run 5's
T1 was 74,807). Bytes per token were 2.44–2.65 on full-size chunks. The sentinel echo remains the
check to trust.

### 0.3 What to distrust in this artifact

1. **The orchestrator is rank-equivalent to the bundle's authors** (opus), as in runs 1–5.
2. **Chunked reads can't see sections against each other.** Two agy findings were refuted by text
   in another chunk (§3). The completeness lens is the cross-section reader.
3. **I verified every credited finding at the line**, per §9.4 instruction 3, and I checked D1's
   blocking finding against the walk order before discounting its verdict. **The panel's verdict is
   still the conjunction of the lenses. A chunk's DO-NOT-BUILD counts only while the finding it
   rests on survives verification**, the same standard runs 2–5 applied to crediting findings.
4. **The lenses disagree on the exact-multiple stall, and I side with fable and T3 (RP6-5).** Three
   agy chunks call it a permanent stall. It is real in a frozen queue. But it is the same recurrence
   rule 4(b) already accepts for every genuine bite at a fixed walk position. What is wrong is only
   rule 4(a)'s sentence that implies a later cycle rescues it.
5. **The harness is ad hoc for the fourth time.** It lives in `/tmp/claude/panel6/`: a chunker, a
   per-chunk `vendor_invoke` runner and a sentinel checker. **#1136 owns `scripts/run_spec_panel.sh`**,
   the real home. This run again didn't widen its scope to build it, and CLAUDE.md's "second time,
   commit it" rule is now overdue against #1136.

### 0.4 Live checks — the claim §9.5 said only a panel with a read path could settle

TD §9.5 (revision 8) nominated its own weakest premise: *"is 'a page shorter than `per_page` ends
the history' true of every endpoint it is applied to? … A panel with a sanctioned read path should
check one events endpoint and one list endpoint at a page seam."* Checked 2026-09-26 with the
worker's installation token, read-only:

| Endpoint | Request | Raw length | Reading |
|---|---|---|---|
| `issues/1540/events` (30 events) | `per_page=100&page=1` | 30 | single short page — COMPLETE in 1 request; **no `Link` header** in the response (`gh api -i`) |
| same | `per_page=10&page=3` / `&page=4` | 10 / **0** | exact multiple — full page, then an **empty** page ends it (rule 4's exact-multiple case) |
| same | `per_page=7&page=5` | 2 | remainder — a short page ends it |
| `issues?state=open&milestone=2` (Step C's shape) | `per_page=100&page=1` / `2` / `3` | 100 / 99 / 0 | full, then short — COMPLETE after 2; page 3 confirms nothing lies beyond |
| same | `per_page=199&page=1` | **100** | **GitHub silently clamps `per_page` to 100** |

**The discriminant holds on both endpoints.** One hazard surfaced. It **does not** reach revision 8
as written, because every prescription pins the literal `per_page=100`, and the TD names that value
as the discriminant ("fewer than `per_page` (100)"). But a coder who parametrises `per_page` above
100 would read every full page as short and end every history at page 1, **silently**. That is
carried as condition C4's second sentence.

The same response carried `X-RateLimit-Limit: 5000` on the `core` resource for the worker App's
installation token. That is the first **observed** (not cited) value for the 5,000/hour figure
§0.6 gap 9 and AM-30 rest on. It doesn't change the ≈24% share, which remains a choice.

---

## 1. Findings

### RP6-1 — MEDIUM — revision 8's new Step C REFUSED state has no §3 row and no §6 test, so its "do not walk a partial list" rule is unpinned. **Non-blocking; condition C1. Class: mechanical correction (test coverage).**

**Raised by:** completeness CL6-1 (and CL6-6), agy T3 ADV-6-3, agy D1 ADV-605. Three independent readers.

**Verified at:** L1195 states the new behaviour and a must-not: *"the gate does not walk a partial
list. Nothing is admitted … Why not walk what was fetched: that is … AF-8's unordered truncation
reached through a flag"*. §3 (L1735–1787) has no row for it: F12 is transport failure, F32 is
Step D5.1, and F33 is the 5-page bound. A grep for `REFUSED` in §6.2 returns only events cases
(L2303, L2334). `test_max_api_requests_can_only_lower` (L2388) pins legality, not outcome.
`test_complete_is_yes_only_when_nothing_was_skipped` sweeps walk stops only (L2337). **A coder who
walks the partial list passes every mandated test.** Same class as RP5-3.

**Related (CL6-6):** at `N = 0` the `UNEVALUATED` line fires only *"when `U > 0` or the list was
truncated"* (L1367), and L1195 says no `WARN`. So only the summary's `complete=no` and exit 3 show
why. That is operator-only (`--max-api-requests 0`).

**Remedy (C1):** Add one §3 row, e.g. **F38**: Step C page refused by the ceiling → no walk,
`N = U = x`, `E = 0`, `complete=no`, `list-truncated=no`, exit 3, no WARN. Add one test that
serves 3 full pages at `--max-api-requests 2` and asserts:
- exactly 2 list requests, and no events request;
- empty stdout, exit 3;
- `evaluated=0`, `unevaluated:cost-ceiling=200`, and no `AUTHORIZED` line.

Add a second case at `--max-api-requests 0`: 0 requests, `complete=no`, exit 3. Then add "a refused
Step C page" to L2337's sweep. Decide CL6-6 in the same test: either the `UNEVALUATED` line fires
whenever `complete=no`, or the test pins its absence and the reason.

### RP6-2 — MEDIUM — §5's `fetch_collaborators(repo) -> Any` can't run the stop test §1.4 and §1.3.2 bind it to, and a ceiling refusal there is routed to F35's `WARN`. **Non-blocking; condition C2. Class: mechanical correction (interface).**

**Raised by:** agy T3 ADV-6-1 (HIGH as raised) and ADV-6-4, agy D1 ADV-602. The completeness lens
held item 1 on the rule text and didn't examine the §5 signature.

**Verified at:** L1882–1889: `fetch_collaborators(repo: str) -> Any`, *"Any failure -> the caller
passes None"*. It takes no counter or ceiling, and it returns nothing that reports requests spent.
Yet §2.2.1's counter table (L1104) counts *"each collaborator page"*, §5's mechanism block (L1985)
says *"Before each page: the page bound, then the request ceiling's stop test"*, and L686 routes a
refused collaborator page to F35. **§5 is "the contract a coder implements against", and as signed
it can't satisfy either rule.** A refusal there also emits `WARN tier-resolution-failed` (F35,
L1782), which contradicts AM-30 point 3's quiet ceiling. That only happens when a tier is listed and
the ceiling is ≤ 3, because Step C's page 1 is then refused anyway (L686's "moot in practice" is
right about the **outcome**, not about the line).

**Why MEDIUM, not HIGH:**
- It costs zero requests with an empty-tier roster, which is every deployment today (L687).
- It fails toward under-trust.
- A coder can't implement §2.2.1 without threading the counter anyway, so the gap surfaces at the
  first review.

**Remedy (C2):** `fetch_collaborators` takes the gate's request budget (the counter and the
effective ceiling, or a callable stop test) and returns the requests it spent, including on
failure. A ceiling refusal there resolves to `tier_members = frozenset()` with `complete=no` and
**no** `WARN`. Pin it with one test at `--max-api-requests 1` with one tier listed.

### RP6-3 — MEDIUM — on the default consumer path, B1 exits `bot-accounts-empty` for an **absent** `machine-accounts.env`, so AM-34's F4a token and remediation line are unreachable. **Non-blocking (fails closed); condition C3. Class: mechanical correction.**

**Raised by:** agy T2 TD1540-R8-03 (HIGH as raised) and R8-04.

**Verified at:**
- L710: `load_bot_accounts` returns an empty set on absence, and the gate *"rejects an empty result
  at Step B1 … after the env union"*.
- L1160: B1 is `empty → exit 2 bot-accounts-empty`.
- L1176: that token's condition is *"**present** but yielding no bot accounts"*.
- L1175: F4a (`machine-accounts-file-absent`) is the row AM-34 wrote for this consumer.
- Revision 8's own note at L1162 says *"file absence has one token whichever step first observes
  it"*, but B1 observes it first and emits the other token.

So with the file absent and `BOT_ACCOUNTS` unset, which is DEV-4's consumer who has neither, the
halt is correct but its token claims the file is present. That is the mute-halt defect AM-34
exists to remove. Separately, L646 (*"if the file baseline is empty, callers fail closed regardless
of the environment"*) contradicts L710 (the check is on the post-union set). The outcome is moot,
because B3 then halts on the same absent file, but the sentences disagree.

**Remedy (C3):** B1 distinguishes absence (→ `machine-accounts-file-absent`) from
present-but-empty-after-union (→ `bot-accounts-empty`). Pin it with the file absent and the env
unset. Reword L646 to "the post-union set" in the same PR, or record the reconciliation in the PR
body.

### RP6-4 — LOW — `probe.py` is bound by rule 3's "MUST emit a stderr diagnostic" and by §1.6's "writes nothing to stderr". **Non-blocking; condition C4. Class: mechanical correction.**

**Raised by:** completeness CL6-5. **Verified at:** L803 (rule 3, *"the fetch wrappers"*) vs
L896/L907 (§1.6: `probe.py` *"writes nothing to stderr and does not import `sys`"*, *"gains no
output surface"*). Revision 8 makes `probe.py` walk `k = 1 … 10` (L893), so the contradiction now
has a code path. R-5 (L2565) cites only gate sites, which suggests "gate only" was meant.

**Remedy (C4):** Rule 3's WARN binds the gate's wrapper only. `probe.py`'s bound-hit path returns
`None` silently, as today's single-page fetch does; say so in the S1 PR and pin it in §6.4's test.

### RP6-5 — LOW — rule 4(a) implies a later cycle rescues the exact-multiple spurious bite; in a frozen queue it recurs, like every bite. **Non-blocking. Class: documentary.**

**Raised by:** agy D1 ADV-604, D2 ADV-6-01 and T2 TD1540-R8-01 (HIGH as raised, "permanent
stall"). **Held** by agy T3 and by the completeness lens (its rejection 1).

**Verified at:** L807 ends *"… and a cycle with one more request of budget would fetch the empty
page and determine it."* That is true, but under a static ceiling and a static queue no such cycle
comes. L808 (rule 4(b)) already says the general case plainly: *"a mid-fetch bite on a multi-page
record recurs on every cycle until the population moves"*. **The spurious bite is that same
recurrence at the same walk position.** It is fail-safe, it is named every cycle on its own line,
and it adds no new stall class. A record with one more event on page `L+1` stalls identically as a
legitimate bite. The tail it holds back is R-8's territory, now #1867's.

**Remedy:** Replace the clause with "and it recurs each cycle until the population moves, like any
bite (rule 4(b))". That can ride with the S2 PR's TD annotation or any later revision.

### RP6-6 — LOW — Step F's stderr grammar omits the `budget-clamped-events-fetch` line that rule 4(b) keeps. **Non-blocking. Class: mechanical correction.**

**Raised by:** agy T3 ADV-6-2. **Verified at:** L808 (rule 4(b)) keeps
`select_work_candidates: budget-clamped-events-fetch issue=#<n>` in the routine class, and L1761
(F14b), L2084–2105 (§5) and L2334 (§6.2) carry it. But Step F's grammar block (L1370–1376), which
is the one place the stderr lines are enumerated, lists only
`unevaluated:cost-ceiling issue=#<n>`. **Remedy:** Add the line to Step F's block. The coder
follows §5 and §6.2, which already carry it.

### RP6-7 — LOW — documentary: stale or miscounted sites, each verified at the line. **Non-blocking. Class: mechanical correction.**

- **(a)** §1.4 rule 5 defines REFUSED as *"the last page fetched was full"* (L795), but Step C
  calls a refused **page 1** REFUSED (L1195), where nothing was fetched (CL6-2, D1 ADV-601). Add
  "or `k = 1`" to the definition.
- **(b)** *"reaches only operator-lowered ceilings below 5"* (L1195, L2745, L3055, L3203) ignores
  B5's 1–3 collaborator requests. REFUSED is reachable up to a ceiling of 7 when a tier is listed
  (CL6-3; D2 ADV-6-02 on this ground only, see §3).
- **(c)** L1109 still glosses `--max-api-requests 0` as *"evaluate only the free path"*. The
  revision-8 note in the same cell says nothing is evaluated (T2 R8-02).
- **(d)** §6.4 L2492: *"any test asserting the exact `_run_gh` argument list, which changes when
  `--paginate` is added"*. This is a revision-7 relic, and L2500 now asserts `--paginate`'s absence
  (T4 RP6-1).
- **(e)** L2158 says *"Six are RE-AIMED"*, but eight are: add `test_list_page_bound_truncates_loudly`
  (L2321) and the page-3-full collaborator case (L2193) (CL6-4).
- **(f)** L3174 says *"five more rows"*, while its table has seven and L3228 says seven (T6 R6-1).
- **(g)** Some `bin/hos-cron` citations lie outside the revision-8 note's "read by content" scope:
  L1156 (`:1808-1815`, live `:1828`) and L1498 (`:1764`, live `:1781`) (CL6-7). This is non-blocking
  per RUN5's ruling on citations.

Reported by agy and **not individually verified** (LOW, documentary, no coder consequence), for
whoever next edits the TD: T5 ADV-601 (A4 row absent from §9.3's tables), T5 ADV-602 (§7.3's
`_verify_codeowner_actor` sign-off row lacks revision 8's per-page re-review item), T5 ADV-603/605,
and T6 R6-2 … R6-6.

---

## 2. What held — verified by the completeness lens, spot-checked at the line

| §9 item | Result |
|---|---|
| 1. Per-page fetch rule | **Held.** Rule 3 (L791) checks the bound and then the stop test before each request, and the counter increments after return (L1106). Step C (L1185), D5.2 (L1302), collaborators (L685–686) and `probe.py` (L893) are all per-page. Every `--paginate` site is history, struck, #1805's pre-S2 caller, or an **absence** assertion. Every `Link` site is "not read", AM-5's record with the declination beneath (L816), or the non-binding `rel="last"` probe. **Live-checked (§0.4).** |
| 2. The clamp as REFUSED | **Held.** Every conjunct in rule 4(a) (L807) is a page length or the counter, with no "cannot tell" case. It fails safe (`unevaluated:cost-ceiling`, never `gated`). The liveness sentence is RP6-5. |
| 3. Step C REFUSED | **Held on the arithmetic.** `N = U = x`, `E = 0`, and `complete=no` via L1363's widened clause, so exit 3 per §2.2. It holds at `N = 0`. The coverage gap is RP6-1. |
| 4. Cardinality anchor | **Held.** Worked on all four fixtures at `b = 1, 2` and fixture (iv) at `--max-api-requests 2` (fable's table; T4 concurs). An over-admitting gate fails `len == b`. Fixture (iv)'s full page 1 is stated (L2301, L2334). |
| 5. RP5-4 / RP5-5 at every site | **Held.** F14b (L1761) is a plain determination. `budget-clamped-events-fetch` carries no `WARN` at L808, L1087, L1304, L1761, L2084–2105, L2324 and L2334. The Step F omission is RP6-6. |
| 6. §4.2 rows and the register | **Held.** 5 classes and 22 functions in the live file, each with a row and exact line citations. `TestBothPathsPaginate` is at L1817. RP5-1 … RP5-6(i) dispositions match the text, and nothing vanished. |
| 7. Fail-open / security routing | **Held.** No security-affecting failure is routed to exit 0 or 3. Step B stays exit 2, collaborator failure under-trusts, and events FAILED quarantines. |

---

## 3. Rejected or not credited

1. **D1 ADV-603 (HIGH, the basis of D1's DO-NOT-BUILD): "D3/D4 admit a trusted record after the
   budget is spent, so an unreached record can outrank an admitted one."** **Refuted.** The walk
   is `(rank, number DESC)`, rank-major, so any record visited after C2 ranks **at or below** C2.
   The construction's premise *"if Candidate 3 outranks Candidate 2"* is unsatisfiable. D5.1
   (L1272) defines the stop as the **refusal** of a request, so a free record reached before any
   refusal precedes the stop. That is exactly ADMISSION over determinations, and L1227 already
   states it (*"ADMITTED only when the walk reaches it in walk order, and never after a stop"*).
2. **T4 RP6-2: §5's `complete=yes` summary (L2073) lets a refused Step C exit 0 with empty stdout.**
   **Not credited.** L2073 is a summary of Step F's definition, and L1363 widens "a bound truncated
   the candidate set" to include a refused Step C page. RP6-1 is the real residue: the rule is
   untested, not fail-open.
3. **T4 RP6-3: `TestBothPathsPaginate` has no disposition.** **Refuted:** §4.2 L1817 retires both
   tests as vacuous after S2, with reasons.
4. **D2 ADV-6-02's rate-limit premise:** "the effective ceiling is clamped by
   `X-RateLimit-Remaining`". **Refuted:** `effective_ceiling = min(100, max(0, provided))` (L1968),
   with no rate-limit term. The finding's other ground (pre-Step C consumption) is credited as
   RP6-7(b).
5. **T1 ADV6-1: L472's "newest-end walking via `Link: rel="last"` is permitted" contradicts
   revision 8.** **Not credited:** L472 records AM-5's disposition, and L816 is the design's binding
   declination (*"the coder MUST NOT exercise it in S1 or S2"*). The completeness lens rejected the
   same shape at L814.
6. **T2 R8-01 / D1 ADV-604 / D2 ADV-6-01 as a HIGH "permanent stall".** **Downgraded** to RP6-5
   (documentary), for the reasons given there.
7. **T3 ADV-6-1 and T2 R8-03 at HIGH.** Credited at MEDIUM as RP6-2 and RP6-3: both fail closed or
   under-trust, and neither reaches today's configuration.
8. The completeness lens's own ten rejections (its §D) are adopted as written. They include
   BOUND-REACHED at a spent budget (consistent under rule 3's order), FAILED-with-a-match (D5.3's
   fail-closed quarantine), and `--max-api-requests 0` (RUN5's binding non-credit).

---

## 4. The completeness lens

The completeness lens (`claude-fable-5-1`, rank 4) read revision 8 **in full from disk**, plus the
rev7→rev8 diff (including every deleted line), RUN5 in full, and the live tree the design modifies.
It ran `gh --version` (2.45.0) and `gh api --help`. **It performed no writes.**

**Its verdict: BUILD-WITH-CONDITIONS.** In its words: *"The revision-8 repair holds on every item in
§9's revision-8 block … What remains is one coverage gap of RP5-3's class — Step C's REFUSED state
… has no §3 row and no §6.2 test … plus five LOW wording items, none of which a coder needs resolved
to implement the text as written."*

**Its findings map into §1 as:**
- CL6-1 → RP6-1
- CL6-2 → RP6-7(a)
- CL6-3 → RP6-7(b)
- CL6-4 → RP6-7(e)
- CL6-5 → RP6-4
- CL6-6 → RP6-1
- CL6-7 → RP6-7(g)

It didn't examine §5's `fetch_collaborators` signature (RP6-2) or Step B's token ordering (RP6-3).
Both came from agy chunks, and both are verified above.

---

## 5. Disposition

**Class, in the human's terms:** every finding is a mechanical correction, and none reopens a
ruling or touches a bound value. **For the first time in six runs, no finding stops `coder`.** The
trend runs 4 and 5 recorded carried through: the prior repair held, and what remains sits at the
edges of new text (one new state, one signature, one token order).

**Conditions — binding acceptance items for the S1 and S2 PRs, checked by `code-reviewer` in the
inner loop:**

- **C1 (S2)** — RP6-1: add the §3 F38 row and the Step C REFUSED tests at ceilings 2 and 0, and
  add the case to the `complete` sweep. Decide and pin CL6-6.
- **C2 (S1 + S2)** — RP6-2: `fetch_collaborators` takes the request budget and reports the requests
  it spent. A ceiling refusal there is quiet (no `WARN`) and still sets `complete=no`. Add one test.
- **C3 (S2)** — RP6-3: B1 distinguishes an absent `machine-accounts.env`
  (`machine-accounts-file-absent`) from an empty post-union set. Add one test with the file absent
  and the env unset.
- **C4 (S1)** — RP6-4: `probe.py`'s bound-hit path stays silent, and rule 3's WARN is the gate's
  alone. **Also:** every bounded fetch pins `per_page=100` literally and never parametrises it
  (§0.4: GitHub silently clamps larger values, which would end every history at page 1).

RP6-5, RP6-6 and RP6-7 are documentary. They can ride with the S2 PR's design annotation or with
any later revision, and none needs a technical-design round first.

**What this does not settle.** A panel verdict clears the §3(c) gate. It doesn't clear the
protected-surface human-approval gate on the S1/S2 PRs (five surfaces, AM-17). It doesn't answer
R-8, which is #1867's to design, or the scope question RUN5 §5 put to the human. That question is
now moot for run 6, and a human who wants the conditions applied as a revision 9 before `coder`
starts can say so on #1540.

**Nothing in this artifact authorizes a merge, a protected-surface edit, or a line of code outside
the S1/S2 build.** No design document was modified by this run, and no issue was filed, labelled or
reopened.

---

*Panel run 6 conducted 2026-09-26 by the autonomous worker (`hos-worker-hos[bot]`) at repo head
`59ff4027d`. Adversarial lens: agy 1.2.11 (google), eight sentinel-verified chunks. Completeness
lens: claude-fable-5-1. Orchestrator: claude-opus-5-5, rank-equivalent to the bundle's authors, a
standing independence limitation of all six runs.*
