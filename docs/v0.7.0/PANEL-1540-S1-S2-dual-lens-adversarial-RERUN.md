# PANEL-1540 (S1 + S2) — dual-lens adversarial panel, **RE-RUN** against technical-design revision 4

```yaml
verdict:                              DO-NOT-BUILD
gate:                                 ADR-1540-AMENDMENT-3 §3(c) — the bound re-run
supersedes:                           PANEL-1540-S1-S2-dual-lens-adversarial.md (run 1, DO-NOT-BUILD)
bundle_sha256_16:                     1b1a50823ea04d55
bundle_contents:                      ADR-1540-AMENDMENT-3 + REQUIREMENTS-1540-AMENDMENT-1 + TECHNICAL-DESIGN-1540 rev 4
repo_head:                            12e2c7ed
adversarial_cli:                      agy 1.2.3
adversarial_model_resolved:           gemini (agy 1.2.3 default; the CLI does not report a resolved ID)
adversarial_vendor:                   google — cross-vendor, independent of the bundle's authors
adversarial_invocation:               scripts/oversight/lib/vendor_invoke.sh (ADR-1683 D-1/D-2), stdin, 1 turn, 121s
completeness_cli:                     claude (Agent tool, class alias `fable`)
completeness_model_resolved:          claude-fable-5-1
completeness_lens_rank:               4
bundle_author_rank:                   3 (opus — pm-agent, architect, technical-design)
completeness_lens_class_differential: true
per_bundle_consumption:               1 adversarial invocation, 1 completeness invocation, 1 orchestrator measurement
findings_count:                       23 upheld (3 critical, 5 high, 6 medium, 9 low), 3 rejected, 1 downgraded
issues_created:                       none by this panel (see §5)
timestamp:                            2026-09-16T03:03:18Z
```

**Status: DO-NOT-BUILD — `coder` is NOT cleared to build S1 or S2.**

This is the §3(c) gate's second output. It does not clear the gate; it reports what the gate
found. **Three findings are blocking and all three are CRITICAL.** One of them — **RP-1** — is
not a constructed scenario but an **existing state of this repository, measured today**: the
authorization path #1539 exists to close is open right now, through a channel the design
retains deliberately.

**The two lenses returned different verdicts, and the disagreement is not a defect.** The
adversarial lens returned DO-NOT-BUILD on three criticals. The completeness lens returned
BUILD-WITH-CONDITIONS and says in terms: *"Nothing I found touches the design's central
claims."* **It was not looking for that** — its brief was to verify claims against the repo,
and on that brief revision 4 performs extremely well (§3). The verdicts are answers to
different questions and the panel's verdict is the conjunction: **DO-NOT-BUILD.**

---

## 0. How this panel ran, and what to distrust about it

**The panel's own invocation site still does not exist.** ADR-033 AD-2 binds the dual-lens
panel to `scripts/run_spec_panel.sh`; TECHNICAL-DESIGN-033 §4.2 fully specifies it (Component
C). It was never built. Run 1 recorded this and **nothing changed**: I searched `scripts/`
(recursively), `bootstrap/`, `bin/` and `scripts/automation/lib/*.py` and found
`run_panel.sh` (post-PR, reads `panel-context.md`), `run_second_review.sh`, `run_red_team.sh`
and `run_release_panel.sh` — **none of which is the design-phase dual-lens panel.** I also
confirmed **no open issue tracks it** (`query_issues.sh --list --state open`, no match on
`spec.panel|run_spec_panel|dual-lens`). So this gate has now run **twice, by hand, for a
CRITICAL security fix.** That is precisely the condition D41 and ADR-033's VF-1/VF-2/VF-3 were
written about: *a gate that exists only as agent prose is a gate that does not run.* **This
artifact is hand-assembled evidence, not a gate's output.** §5 records it, as run 1 did, and
this time with the observation that recording it once did not cause it to be built.

**One thing did improve over run 1.** The adversarial invocation went through
`scripts/oversight/lib/vendor_invoke.sh`, the sanctioned agy/codex launch primitive (ADR-1683
D-1/D-2), rather than a hand-rolled CLI call — so the prompt reached agy on **stdin** and the
known `MAX_ARG_STRLEN` E2BIG failure mode was structurally excluded. The invocation returned
`status: SUCCESS`, 1 turn, 25,992 response bytes. **This matters because the known failure
mode of this lens is a silent empty SUCCESS** when the model attempts a tool call; a non-empty
response is the evidence that did not happen. It is recorded here so a future reader does not
have to take "the panel ran" on trust.

**Lens coverage was asymmetric, again, and in the same direction.**

- The **adversarial lens** (`agy`/gemini, rank unknown, cross-vendor) received the bundle as
  text with **no repository access** and was explicitly instructed not to attempt tool calls.
  Everything it claims about the repo is therefore **inference from the documents**, and is
  marked as such below. Its strength is construction; its weakness is that it cannot check
  itself. **One of its findings (RP-8) is downgraded on exactly that ground.**
- The **completeness lens** (`fable`, rank 4) had full repository access, read all 2,562 bundle
  lines plus ~25 repo files with line numbers, and performed one live GitHub read. Its
  verification results are reproduced in full in §3 because they are the most reusable part of
  this artifact.
- The **orchestrator** (this session, rank 3 — *same rank as the bundle's authors, which is a
  real independence limitation*) contributed one thing neither lens could: **a live measurement
  across all 97 candidate issues** (§2). It is what converted RP-1 from a construction into an
  observation and what downgraded RP-8.

**What to distrust in this artifact, stated rather than buried:**

1. **The orchestrator is rank-equivalent to the bundle's authors** and wrote this synthesis.
   The class differential that makes the completeness lens independent does not apply to me.
2. **Run 1's ~40 verified-sound claims were deliberately NOT re-derived** (Amendment 3 §3(c)).
   If one of them was wrong, this re-run did not catch it and was instructed not to try.
3. **The adversarial lens saw three documents, not five.** The ADR and run 1's own artifact
   were excluded to keep the re-run scoped. A finding turning on base-ADR text it never read
   would have been missed.
4. **A harness notice fired on the completeness lens's output** for matching an
   instruction-shaped pattern (`bypass-permissions`). I inspected it: the match is on **quoted
   shell text from `test_hos_cron.py:102`** (`cat > /dev/null 2>&1 || true`) reproduced as
   evidence. It is benign quoted content, not an injection attempt, and nothing in that output
   was treated as an instruction.

---

## 1. Findings — upheld

**Numbering.** Run 1 used `P-1 … P-7`. This re-run uses **`RP-n`** deliberately: the
adversarial lens returned its own `F1 … F14`, which **collides with the technical design's
§3 fail-closed rows `F1 … F33`** — an `F5` in this artifact and an `F5` in TD §3 would be
different objects, which is precisely the hyphen-versus-no-hyphen ambiguity the design itself
flags at §9.2/R6. Every finding below carries the lens's original label so nothing is lost.

### RP-1 — CRITICAL — the `milestoned` channel launders a bot's label through a human's routine triage. **BLOCKING. AND IT IS LIVE TODAY.**

*Surface: A5 (the "highest-yield item"). Adversarial lens F7. **Confirmed against code AND against live repository state by the orchestrator.***

**The claim attacked.** Step D5 authorizes a record if the `needs-ai` label **or** the
milestone assignment was applied by a verified CODEOWNER human.

**The construction (adversarial lens).** A human bulk-assigns a milestone to backlog issues
during routine sprint planning. A bot later attaches `needs-ai`. The gate checks: `labeled`
actor is a bot → rejected; `milestoned` actor is the human → **accepted**. The bot's label is
laundered through the human's scheduling act. The human triaged a milestone; the gate read it
as clearance to execute untrusted content.

**Verified at code level.** `scripts/automation/lib/probe.py:292-294`, the docstring of
`_verify_codeowner_actor`, states it outright:

> *"**Either signal alone authorizes the issue** — checks the most recent 'labeled' event for
> `label_name` and the most recent 'milestoned' event, and returns the first verified-human
> actor found."*

The implementation matches: `probe.py:308-313` appends the actor of **every** `labeled`
(matching the label) **and every `milestoned`** event to one `relevant_actors` list, then
`:315-322` returns the first reversed entry that is a non-bot CODEOWNER. **There is no
requirement that the authorizing actor be the one who applied the dispatch label.**

**Verified against live repository state — this is the part that makes it blocking.** I swept
**all 97** open, `needs-ai`, non-PR issues in milestone `v0.7.0` and compared, per issue, the
actor of the most recent `labeled:needs-ai` event against the actor of the most recent
`milestoned` event:

```
F7-LIVE #1542  needs-ai by BOT(scottthurlow-claude[bot])  milestoned by HUMAN(ScottThurlow)
checked=97  f7_live_matches=1
```

**#1542 is in that state right now.** No human ever applied its dispatch label; a human applied
its milestone. Under Step D5 as specified, S2 would select it for autonomous execution and
report it as `codeowner-actor:ScottThurlow`. The issue itself is benign internal work — **the
mechanism is the finding, not the issue.**

**The variant neither lens stated, and which is worse.** The adversarial lens's scenario needs
a bot to label an *already-milestoned* issue, and §9.2/R9 argues that window is currently
uncontested. **The reverse order needs no such window and is routine.** Worker Step 0 triage
assigns milestone **and** `needs-ai` together, both as a bot — correctly unauthorized. Then the
human **re-routes the issue to a different milestone**, which this repo's own triage rules
actively instruct (`v0.5.1` drained, `v0.6.0` closed, priority overrides theme). That writes a
fresh `milestoned` event under the human's account, and AM-4's byte-for-byte check compares it
against `record["milestone"]["title"]` — **the new milestone, which matches.** The issue
becomes authorized. **The human's routine act of re-planning grants execution authority to
content they may never have read.** R9's window analysis does not reach this because nothing
about the dispatch label changes.

**Why it survives checking.** AM-4 hardened *which* milestone matches. AM-15 told the human not
to cycle milestones *as an authorization route*. **Neither removes `milestoned` from D5's
disjunction**, and H1 item 2's instruction — "do not use the milestone route" — is addressed to
the human's *deliberate* act, not to their routine one. The design's own §9.2/A5 asked the
panel to *"look for any other place a workflow's or bot's write is read as a human's act."*
**This is that place, and it is inside the gate itself.**

**What this does to the chain.** #1539's ruling item 1 says *"the `needs-ai` label and/or
milestone assignment was applied by the designated human CODEOWNER"* — so the disjunction is
**traceable to the human's own words** and is not an error the design introduced. That makes
this a **requirements** finding, not only a design one: `pm-agent` and the human must decide
whether the milestone channel survives at all. The architect cannot rule it away alone.

### RP-2 — CRITICAL — pagination + cost ceiling + `number`-ascending tie-break starves recently-authorized issues. **BLOCKING.**

*Surface: P1-b — the architect's own "does any pair interact badly?" question. Adversarial lens F1.*

**The claim attacked (AM-22, via TD §6.2):** *"ranking sits between the widening and the
truncation, so widening can only move a high-priority record INTO the evaluated region."*

**The construction.** Step E/D-rank sorts by `(rank, number)` **ascending** (TD `:716`,
`sorted(eligible, key=lambda c: (c.rank, c.number))`). Lower issue number = **older**. AM-22
widens Step C from 100 to **500** records. The 400 newly-admitted records are, by construction,
**older** than everything on page 1 — so within any given priority band they sort **ahead** of
the newer records. Under FR7 an untrusted record is **never cached** and costs one check every
cycle. If 100+ older unauthorized records occupy the critical/high bands, the walk spends its
entire 100-check ceiling on them and stops. A newer, genuinely authorized issue is **never
reached** — where before pagination it sat on page 1 and was evaluated.

**Why this is the pair interacting badly, and not either bound alone.** Without widening, page 1
holds the 100 newest records and the ceiling of 100 covers **all** of them. With widening, the
ceiling covers only the top 100 of 500 by `(rank, number)` — which within a band are the
**oldest**. **Widening strictly reduces the evaluated coverage of recent records.** The
architect's construction is correct that widening moves high-priority records *into* the pool;
it does not follow that this helps, because the pool is then truncated by a budget that the
newcomers consume first.

**Why it survives checking.** TD §6.2's
`test_pagination_and_ceiling_interaction_is_ordered_not_arbitrary` asserts the interaction is
*ordered* — and it is. **Ordered is not the same as harmless.** Prefix-correctness is preserved
and the outcome is still bad, which is the strongest possible demonstration that
prefix-correctness was never a sufficient safety property. **This is run 1's T1 lesson
recurring**: the reasoning you are least sure of is the one to write down.

**Interaction with RP-4.** This finding and E-8 are the same collision seen from two sides: a
ceiling derived from a one-page population, applied to a five-page population.

### RP-3 — CRITICAL — an absent roster is not benign for consumers, and the documentation shipping condition is breached. **BLOCKING.**

*Surface: P4-a and P4-b — the architect's own question and the designer's own escalation. Adversarial lens F5; corroborated in detail by the completeness lens.*

**(a) A consumer with team-based CODEOWNERS is permanently halted.** AM-26 rules
`trusted-requesters.txt` **not** shipped, on the sound ground that `cp_framework_file()` is an
unconditional `cp` (**verified**: `bootstrap/hos_install.sh:615-626`, guard is only
`[[ ! -f "$src" ]]`, header comment at `:610-614` says skipping "defeats the purpose of running
an upgrade"). AM-26 calls the absent roster benign *because CODEOWNERS and apps still confer
trust*. **The design's own §3 contradicts this**: row **F2** — *"CODEOWNERS present, only
`org/team` patterns → gate Step B2 → **exit 2** `codeowners-empty`"* (TD `:1055`), with F1 the
same for an absent file. Team-handle CODEOWNERS (`@org/core-devs`) is **the common enterprise
configuration.** For such a consumer, S2 makes every worker cycle exit 2 forever, and §2.1's
`machine-accounts.env` precondition compounds it — **verified** by the completeness lens:
**zero** producers in `hos_install.sh`/`install.sh`, and `provision_agent_account.sh:56` dies
if it is missing. The failure is **indistinguishable from a broken install**, which is the
second half of the architect's question and the answer is *no, it is not distinguishable*.

**(b) FR29 is a shipping condition and the shipped artefact cannot satisfy it.**
`REQUIREMENTS-1540-AMENDMENT-1` AR-6 marks FR29 binding — *"S2 MUST NOT merge without it."*
**Verified**: `scripts/framework/framework_consumer_files.txt` contains **no `docs/` path of
any kind**. A consumer receives the gate and **none** of its documentation — not `docs/LABELS.md`,
not `docs/OVERSIGHT-RUNBOOK.md`. They are handed a control that silently requires
`machine-accounts.env`, requires a two-act label remove/re-add **from a personal account**, and
has an inert `/approve`, with **no instructions for any of it**.

**On the designer's triage, which §9/P4-b explicitly asked the panel to rule on.** The designer
judged this a repo-wide documentation-shipping question rather than one S2 creates, and declined
to fold it into a `priority:critical` fix. **The panel finds that triage half right.** The
general defect (no `docs/` ships, ever) is indeed pre-existing and is not S2's to fix. **But
FR29 is a shipping condition on S2 specifically**, and a shipping condition that the shipping
mechanism cannot express is not satisfied by noting that the mechanism was already broken.
**Either FR29 is met for S2's documents, or AR-6 must be amended by `pm-agent` to say what it
actually requires.** It is not the designer's to absorb, and it is not dischargeable by triage.

### RP-4 — HIGH — E-8 is a real defect, is present in **three** places, and the ceiling binds in the state the design calls normal. **BLOCKING.**

*Surface: P1-c — the item both the architect and the designer nominated as "the claim H1 rests
on that nobody measured". Adversarial lens F2; independently verified and **strengthened** by
the completeness lens.*

**The designer could not resolve E-8 and handed it to the panel. The panel resolves it: E-8 is
real, and understated.**

AM-19 fixes the cost ceiling at **100** — *"one check per record on one list page, i.e. the
natural per-cycle maximum"* — and requires that *"the ceiling must not bind in normal
operation."* AM-22, 55 lines later, makes the list **five** pages / 500 records.

**The completeness lens found it in a third site the designer did not name:** Amendment 3's own
**CONFIDENCE block** (`:381`) repeats *"the ceiling's 100 is better grounded, being one check
per record on one page"* — so the broken derivation propagated into the architect's own
self-assessment. And **AM-19's own cost paragraph (`:81`) already prices "1–5 list requests"** —
**the architect knew of pagination inside the ruling that derived the ceiling from a single
page.**

**The consequence, which is what makes it blocking rather than editorial.** Under AM-14's lazy
drain — *the architect's own designated normal operating state for weeks* — most of the queue is
unauthorized, and FR7 forbids caching. The queue is **97 today and grows monotonically**. The
moment unauthorized records exceed 100, the gate pays 100 checks **every cycle**, hits the
ceiling **every cycle**, and emits `complete=no` **every cycle**. **A bound that binds on every
cycle in the normal state is not a cost ceiling; it is the algorithm.** AM-19's own stated
requirement is falsified by AM-22, and the ceiling **may only be lowered**, so the designer had
no instrument. This is the architect's to rule.

**Second defect attached (adversarial lens).** The ≈105-requests/cycle envelope assumes one
events page per issue, derived from a measured maximum of 17 events on a young repo. AM-5
bounds events pagination at **10 pages**. If older issues accumulate events past 100, 100 checks
issue 200–500+ requests/cycle — **2,400–6,000+/hour against a 5,000/hour limit.** H1 item 2
discloses ≈105 as the worst case. **It is not the worst case.** The human is being asked to
clear an operating envelope on a number that is a floor, presented as a ceiling.

### RP-5 — HIGH — Step C's exit 0 fails **both** limbs of AM-21's criterion, not one. **BLOCKING.**

*Surface: P1-d. Adversarial lens F3.*

AM-21 states the criterion: a bound may exit 0 **only** when the omission is **(i) enumerable**
and **(ii) ordered**; *"if either property is absent … the gate MUST exit 2."* TD `:628` concedes
Step C's list bound *"is enumerable but **unordered**, so strictly the criterion above pushes it
toward exit 2"*, and exits 0 anyway on a denial-of-service argument.

**The attack: it is not enumerable either.** GitHub's `/issues` endpoint returns **no total
count**. When Step C stops at page 5 with a `Link: rel="next"`, the gate cannot say whether it
omitted 1 record or 1,000. **So the concession is too weak** — the design believes it is failing
one limb and buying an exception; it is failing **both**, and the criterion has no exception
shaped to that.

**On the exception's stated ground.** The design says 500 makes reaching the bound *"an
operational emergency rather than a residual."* **An emergency is the canonical case for failing
closed**, not for proceeding with a warning that a cron loop discards. And the design's §9/P1-d
names this exact weakness itself: *"that is a claim about operational practice, not about code."*
**The panel agrees with the design's own doubt over the design's own ruling.**

### RP-6 — HIGH — prefix-correctness has an unstated **fifth limb**: input completeness. Not independently blocking.

*Surface: P1-a — the central claim. Adversarial lens F4.*

**The adversarial lens could not break prefix-correctness within the candidate set, and says so
plainly** (see §4, rejection 1 — it reconstructed the proof and found it sound over its input).
**That is a real result and the panel records it as such**: AM-19's four limbs — total ordering,
monotonic walk, non-interference, universal terminal stop — do prove the walk emits an exact
prefix **of the set fed into D-rank**.

**The fifth limb is that the set fed into D-rank is complete.** Step C truncates at 500 by
`created desc` **before** ranking. An omitted 501st record may be `priority:critical` while
emitted records are `high` or `medium` — so **an omitted candidate outranks an emitted one**, and
the emitted set is *not* a prefix of what a complete walk would produce. §9/P1-a asked: *"if there
is a fifth limb, the tests do not cover it and neither does the argument."* **There is, and they
do not.**

**Not independently blocking** because it is downstream of RP-5: making Step C's truncation
exit 2 restores the limb. Recorded separately because **the decomposition is what §6.2 tests
against**, and a four-limb test suite will stay green while the fifth is violated.

### RP-7 — HIGH — fail-closed exit 2 mid-walk is a remote denial-of-service on all autonomous work. **BLOCKING.**

*Surface: R7 — "attack §3 as an availability surface rather than a security one". Adversarial lens F9.*

D5.3 exits **2** if the events query fails for **any** candidate mid-walk (TD `:710`), and
`bin/hos-cron` aborts candidate selection for the cycle. **The events query is issued against
issues supplied by untrusted authors.** An issue with a pathological event history — thousands
of cross-references, bot comments, label churn — that reliably times out or errors on
`/events` **halts the worker on every 5-minute cycle**, including for `priority:critical` work
authored by the CODEOWNER. **No authorization is needed to file an issue**, so this is a
denial-of-service reachable by any member of the public against the entire autonomous pipeline.

AM-21 elevated D5.3's exit 2 to a general principle on correctness grounds — *a partial list can
silently demote a `priority:critical` item* — which is right. **What is missing is the third
option** between "proceed with a partial list" and "stop the repo": quarantine the unqueryable
record, count it under the existing `unevaluated` machinery AM-20 already built, and continue the
ranked walk. **AM-20 supplies the vocabulary for exactly this and AM-21 does not use it.**

**This finding and RP-5 pull in opposite directions and must be ruled together.** RP-5 says one
bound fails closed too little; RP-7 says another fails closed too much. **That is not a
contradiction — it is the observation that "fail closed" was applied as a slogan rather than
per-failure-mode**, which is what AM-21's criterion was introduced to fix and does not yet
finish.

### RP-8 — LOW (**DOWNGRADED from the adversarial lens's HIGH — see §2**) — `milestoned` payload shape.

*Surface: R2. Adversarial lens F8.*

The lens claimed the `milestone` field's shape *"can be a string, an integer ID, or an object
omitting the `title` property"* and that title-binding may be *"dead on arrival."* **The
orchestrator measured this across all 97 candidate issues and the claim is not supported** —
see §2. **Downgraded to LOW**, and retained only for its sound residue: the repo's fixtures
still exercise no `milestone` object (`test_probe.py:465`, **verified**), so the coverage hole
is real even though the speculation about shape is not. **This is the adversarial lens's one
finding that its own lack of repository access produced**, and it is recorded as such rather
than quietly dropped.

### RP-9 … RP-14 — the non-blocking adversarial findings

| # | Sev | Surface | Finding | Note |
|---|---|---|---|---|
| **RP-9** | MEDIUM | P3-a | **With `/approve` inert, there may be no automated dispatch path at all**, stranding CLI-only operators. | The **inverse** §9/P3-a asked for. The lens answers the design's question: after AM-25 the writers are Step 0 triage and a human, and nothing else. **The completeness lens verified the search** (§3) — `worker.md:331` and `worker-cron-prompt.md:75` cite `/approve` as a *pattern*, not a caller. So the enumeration holds **today**, which is the strongest form available. |
| **RP-10** | MEDIUM | R9 | **No conformance verification is possible for "no automation adds the dispatch label to a milestoned issue."** | The lens did **not** produce a mechanical detector, which is itself the answer to §9.2/R9's standing question. Next-best detector proposed: assert at gate runtime, not at test time — if a `labeled` event's actor is a bot **and** the record is authorized via the milestone channel, that is RP-1's signature and the gate can **report** it even if it cannot prevent it. |
| **RP-11** | MEDIUM | R6 | **`EXCLUDED_LABELS` seam is unguarded** — two designs write one constant in a protected file, and the divergence test that guarded it is deleted in the same change. | Unchanged from revision 3's statement of it; the lens adds no new construction. Carried. |
| **RP-12** | MEDIUM | R10 | **A sound comment-revocation anchor may exist**: GitHub's native comment **minimize/hide** is a server-side state transition on the comment, reported in metadata, not defeatable by the requester. | If correct, this weakens AM-16's third pillar (*"a comment has no inverse"*). **Unverified — the lens had no repo or API access** and the panel did not measure it. Recorded as a construction for the architect to check, **not** as an established defect. |
| **RP-13** | LOW | A4 | Inverted default may break **general** milestone-verification callers outside this repo's two. | The attack §9.2/A4 asked for (*"a caller F27 does not see"*), but the lens names no such caller. Weak. |
| **RP-14** | LOW | A1 | Title-marker enumeration may fail on dynamic or nested machine filings. | Speculative; the lens had no access to the marker table's call sites. |

### RP-15 … RP-23 — completeness-lens findings (documentary and test-specification defects)

**Two are blocking on `coder` specifically** — not on the design's soundness, but because a coder
**cannot satisfy the spec as written**:

| # | Sev | Type | Finding |
|---|---|---|---|
| **RP-15** | MEDIUM | under-applied ruling | **AM-27 under-applied.** TD `:1030` promises *"every occurrence in this document is replaced by the specific file it means"*, and specifies `test_no_document_uses_the_phrase_cutover_material` as *"a repo-wide absence assertion over `docs/v0.7.0/**`."* **The phrase survives 11 times across 6 files** — including the TD itself (`:1740`), **`REQUIREMENTS-1540-AMENDMENT-1`'s FR29 text**, and the **immutable run-1 panel artifact**. As specified the test **cannot pass** without editing other authors' rulings and a historical artifact. **Re-scope before `coder`.** |
| **RP-16** | MEDIUM | internal contradiction | **AM-25 under-applied in §6.3.** `:1503` still requires `docs/LABELS.md` to carry the *harmful* form of the `/approve` statement (a revision-3 test carried forward), while `:1126` statement 4 requires the **replaced** form — *`/approve` cannot consume the additive act, because it writes no label.* **A coder satisfying both writes a registry row asserting `/approve` both can and cannot consume the act.** One test to invert or delete. |
| **RP-17** | LOW | internal contradiction | **§2.3 D5 item 2 is duplicated verbatim** (`:708-709`), so the list reads 1, 2, 2, 3, 4, 5 — and **every `D5.n` citation after it is off by one** (F13→D5.3, F17→D5.2, F19/F20→D5.4, `no-codeowner-actor`→D5.5). Revision-4 editing artefact. |
| **RP-18** | LOW | under-applied ruling | **AM-22 under-applied in Step F** (`:782`): *"the gate has already scanned at most 100 records"* — a revision-3 remnant; Step C now scans 500. A wrong load-bearing number in a document whose §7.3 is about wrong load-bearing numbers. |
| **RP-19** | LOW | missing coverage | **`trusted-requesters.txt.example` is ruled into the ship list** (`:567`, `:1129`) but appears in **no** file-layout table and **no** slice, and `test_every_listed_file_exists_in_source` fails the moment the list names a non-existent file. Also: **H1 item 4 tells the human Amendment 3 adds *one* file to surface 1; the TD adds two.** |
| **RP-20** | LOW | internal contradiction | **G11's test home moved** to `test_hos_cron.py` (`:1461`) but it is still listed under `test_selection_call_sites.py` and **absent from §6's binding test-homes table** — the table AM-28(a) required precisely so no test row is homeless. |
| **RP-21** | LOW | internal contradiction | **`auth_checks` is off by one.** `:696` increments **before** the comparison and stops on `>` ceiling, so the counter reads **101** at the stop; `:741` defines it as *checks spent*; F32's test (`:1386`) asserts `== 100`. **This is the one field the ceiling's entire report is built on.** |
| **RP-22** | LOW | map checkability | **The coverage map claims four sections that carry no revision-4 change** (AM-19→§2.4, AM-20→§2.4, AM-23→§0.1, AM-24→§7.2). Harmless in effect — *claimed-changed-but-unchanged*, the inverse of the usual defect — but the map's whole value is that each row is checkable. |
| **RP-23** | LOW | wrong state claim | **"Currently vacuous" is imprecise** (`:1884`, Human Review item iv). `probe.py:421-435` has **no** skip today, so `:318`'s test **does** exercise its subject in the shipped tree; it *goes* vacuous once S1's skip lands. §6.4 and Amendment 3 §0 word it correctly. **In a chain that has logged four instances of a number being wrong in the one place a decision-maker reads it, the self-flag block should match §6.4.** |

---

## 2. The panel's own measurement — what neither lens could do

Both lenses reason about `milestoned` events; **neither could observe one.** The adversarial
lens had no repository access by construction, and the completeness lens's single live read was
the candidate list. §9.2/R2 states the gap precisely: *"the `milestoned` event payload's shape
is **asserted, not observed**… nothing in this repo has ever exercised the field FIND-1 is
about."* **That was still true at the start of this panel. It is no longer.**

I swept the `/events` endpoint for **all 97** open `needs-ai` non-PR issues in milestone
`v0.7.0` and recorded, per issue, the most recent `labeled:needs-ai` actor, the most recent
`milestoned` actor, and **the key set of the `milestone` object**.

**Result 1 — the payload shape, observed for the first time in this chain:**

```
distinct milestone key sets observed:
     97 title
```

**97 of 97 `milestoned` events carry a `milestone` object whose key set is exactly
`["title"]`.** Sample payload:

```json
{"event":"milestoned","actor":"scottthurlow-claude[bot]","actor_type":"Bot",
 "milestone":{"title":"v0.7.0 — Quality"}}
```

**Three consequences, all of which resolve open questions:**

1. **AM-4's byte-for-byte `title` binding is FORCED, not chosen.** §9.2/R2 asks: *"If the payload
   carries `number`, the design still binds title equality — attack whether that is right."*
   **The payload does not carry `number`.** There is no alternative field to bind. R2's question
   is **moot**, and AM-4 is **vindicated on a ground the architect did not have**: they chose
   title equality on strictness grounds, and it turns out to be the only option available.
   **R2 can be closed.**
2. **RP-8 (adversarial F8) is downgraded.** Its speculation that the shape varies — string,
   integer ID, `title` omitted — is **contradicted by 97 observations**. Crediting it would have
   sent the architect to re-derive a non-problem, which §9.4's second standing instruction
   exists to prevent.
3. **The fixture hole is real but now trivially closable.** `test_probe.py:465`'s
   `_milestoned_event()` emits no `milestone` object (**verified by the completeness lens**), so
   the coverage gap stands — but the correct fixture is now **known rather than guessed**:
   `{"milestone": {"title": "<exact title>"}}`.

**Result 2 — RP-1 is live**, `f7_live_matches=1` (#1542). See RP-1.

**Result 3 — the architect's 97 is independently re-derived, now three times.** The architect
measured it 2026-09-15; `technical-design` re-derived it 2026-09-16; this panel's sweep counted
**97** again through the same sanctioned path, and the completeness lens **separately**
reproduced it with the full priority split (3 critical / 58 high / 27 medium / 3 low / 6
unlabelled = 97, `#1539` at position 88). **The number in H1 item 2 is sound.** Recorded
explicitly because H1 is in front of the human now.

**The method is committed nowhere.** It ran from `/tmp/claude/probe_f7.sh` this cycle. Per
`CLAUDE.md`'s "the second time you need it, it belongs in `scripts/` with a test", **this is
exactly the material `scripts/run_spec_panel.sh` should own** — see §5.

---

## 3. Verified sound — do not re-derive these

**This section is the most reusable part of the artifact and it is reproduced in full
deliberately.** Run 1's §3 was judged *"a genuine asset"*; this is its successor. Everything
below was checked against the working tree at `12e2c7ed` by the completeness lens, with line
numbers it actually read.

**All four of revision 4's re-derived citation corrections are correct:**

| Claim | Verdict | Found |
|---|---|---|
| `/decline` write at `label-swap.yml:79` (not `:83`) | **VERIFIED** | `:74` `/approve` edit, `:75` body, `:78` `else`, `:79` `/decline` edit, `:80` close |
| `verify_codeowner_actor` has **eight** shipped cases (not nine) | **VERIFIED** | `:468, :476, :484, :495, :503, :511, :519, :529`; the three `codeowners_humans` cases correctly excluded |
| `_milestoned_event()` at `test_probe.py:465` (not `:466`) | **VERIFIED** | `:465` def, `:466` body |
| `_make_issue()` at `:42-46` (not `:41-46`) | **VERIFIED** | `:42` def, `:43-46` body |

**The designer beat the amendment on a fifth**: TD's correction of `docs/OVERSIGHT-RUNBOOK.md`'s
NG3b block to `:77` (against the amendment's `:76-85`) is right — `:76` is blank.

**Also verified sound:**

- **The 97 / position-88 / 3-58-27-3-6 measurement** — reproduced exactly through the sanctioned
  read path, and again by this panel (§2).
- **AM-26's ship-set argument, end to end** — unconditional `cp` (`hos_install.sh:615-626`), no
  `docs/` entry anywhere in `framework_consumer_files.txt`, `machine-accounts.env` absent from
  the list **and** from any installer producer, `provision_agent_account.sh:56` dies without it,
  and the existing guard test is **existence-only** (`test_consumer_framework_files.py:47`), so
  the new import-graph test §6.3 specifies is genuinely new coverage. *(The argument is sound;
  RP-3 is about its **conclusion** being wrong for consumers, not its reasoning.)*
- **AM-25's two falsified reasons and the "no caller" claim** — both greps reproduce.
  `grep '/approve' docs/OVERSIGHT-RUNBOOK.md` → **0 hits**. `_HUMAN_GATE_LABELS` reads **PR**
  labels (`merge_authority.py:494, :519-521, :557-566`) while `/approve` fires only on issues
  (`label-swap.yml:29`). Repo-wide, the only `/approve` hits are the workflow definition and two
  **pattern citations** (`worker.md:331`, `worker-cron-prompt.md:75`).
- **§2.5 states the `bypassPermissions` discrepancy as unresolved and adopts neither side**
  (AM-28(g) applied as ruled), with AM-11's justification restated on the `CLAUDE.md` ground.
- **AM-28(a)** — `test_hos_cron.py` named in §2.1/§4.3/§6; F26's over-claim corrected; the
  `_build_prompt` mechanism specified **and sound** (stub `:102`, env override
  `hos-cron:44, :981`, harness precedent `test_hos_cron.py:3114-3123`).
- **AM-28(d)** — the six `probe.py` tests requiring change are all at the cited lines.
- **AM-28(e)** — §1.3.1's per-loader fail-closed table present for all four loaders; FR8's
  agreement test present.
- **AM-28(f)** — R-3's reachability argument and re-check trigger attached.
- **AM-19/20/21/22 landed where the map says** for §1.2, §2.2, §2.2.1, §2.3, §3, §5, §6.2,
  §7.1, §7.2.
- **AM-23/AR-5** — per-step FR citations present; the bounds table cites ruling + safety
  property per row.
- **AM-27** — the three named landing sites, the milestone-route prohibition in `docs/LABELS.md`
  with a test, S2's work item recorded as #1539. *(Under-applied only as RP-15 describes.)*
- **The architect's own in-change-set corrections** (P-7(b), P-7(c), AF-9, AD-4 header) **all
  landed**.
- **Protected surfaces = five**, confirmed against `protected_surfaces.txt` — now a **fourth**
  independent derivation.
- **§9.3's eleven retirements each carry a reason**; T1, R5 and R3 spot-checked against their
  revision-3 substance — consistent. *(§9.5 invited exactly this check.)*

**On §9.5's instruction aimed at the designer.** Of the four self-named weak claims, the panel
finds: **E-8 is real and understated** (RP-4 — the designer was right to escalate rather than
absorb, and right not to hold revision 4 for it); **the ≈105 envelope is worse than disclosed**
(RP-4); **the "one line" stub claim is essentially correct** — one stub line plus one
`CronEnv.__init__` attribute, so "one line" is off by one attribute, not by three; and **the §9
rewrite's retirements survive spot-checking**. **Naming its own weak claims is what made three of
the four checkable in a single pass**, and the panel records that the practice worked.

---

## 4. Findings considered and REJECTED

**§9.4's second standing instruction makes this section a requirement, not a courtesy.** Run 1
threw out two findings here and that was judged the most valuable part of the artifact.

**Rejected by the adversarial lens itself (it checked its own work):**

1. **That AM-19's lazy walk violates prefix-correctness *within* the candidate set.**
   *Rejected because it is sound.* `(rank, number)` over unique issue numbers is a **strict total
   order with zero ties**; the walk is monotonic; both stops terminate it **completely** for
   trusted and untrusted alike. Any emitted `e` and any stop-omitted `o` satisfy
   `(rank_e, number_e) ≤ (rank_stop, number_stop) ≤ (rank_o, number_o)`. **AM-19's central claim
   survives a direct attack by a cross-vendor adversary that was explicitly instructed to break
   it.** That is a real result and the strongest single piece of evidence in this artifact **for**
   the design. The defect is upstream, in Step C (RP-6).
2. **That `edit_issue.sh --app human` is an operator approval path.** *Rejected — the bundle
   forecloses it explicitly* (AM-1, TD §2.7.1, H1 item 2): it writes as
   `scottthurlow-claude[bot]`, which `is_bot_reviewer` rejects.
3. **That `/approve` is an exploitable authorization bypass.** *Rejected* — AF-5 established
   `label-swap.yml` runs as `github-actions[bot]`, excluded at layer 2, and AM-25 removes the
   label write entirely.

**Rejected/downgraded by the panel:**

4. **RP-8's payload-shape speculation** — **refuted by measurement**, 97/97 (§2). Retained at LOW
   only for the fixture-coverage residue.
5. **RP-12's minimize-comment revocation** — **not rejected, but explicitly not credited as a
   defect.** The lens had no API access and the panel did not verify that comment minimization is
   reported in timeline metadata in a form the gate could read. It is handed to the architect as
   **a construction to check**, which is what §9.2/R10 asked for — *"if the panel can construct a
   sound revocation… AM-16's third pillar weakens"* — with the honest caveat that constructing is
   not verifying.

---

## 5. Follow-ups — recorded, not filed by this panel

1. **`scripts/run_spec_panel.sh` does not exist, and recording it once did not build it.** This
   gate has now run **twice by hand for a `priority:critical` security fix**, and **no open issue
   tracks the gap** (searched this cycle). Run 1 recorded it in its §5 and nothing followed. The
   panel's own measurement machinery (§2) is the second piece of throwaway tooling this gate has
   produced. **Recommend filing it as a real work item**, with §2's sweep as its first
   committed capability.
2. **#1542 should be re-checked after any RP-1 ruling.** It is the live instance and it is the
   natural regression fixture.
3. **`docs/` ships to no consumer, at all** (RP-3(b)). Larger than S2 and the designer is right
   that S2 did not create it; **but FR29 cannot be satisfied until it is addressed**, so the two
   cannot be fully decoupled.

---

## 6. Verdict

## VERDICT: DO-NOT-BUILD

**`coder` is NOT cleared to build S1 or S2.** Three CRITICAL findings block, and they are not of
one kind:

- **RP-1 is a requirements defect, not a design defect.** Step D5's `labeled OR milestoned`
  disjunction is traceable **to the human's own 2026-09-10 ruling**, so the architect cannot
  rule it away alone — `pm-agent` and the human must decide whether the milestone channel
  survives. **It is live in this repository today** (#1542), and the routine-re-milestoning
  variant makes it reachable without the automation window §9.2/R9 argues is currently closed.
  **This is the gap #1539 exists to close, still open, through the fix intended to close it.**
- **RP-2 and RP-4/RP-5/RP-6 are one defect seen from four sides**: a cost ceiling derived from a
  one-page population applied to a five-page one, with a truncation that fails both limbs of the
  design's own exit criterion and breaks a fifth, unstated limb of prefix-correctness. **The
  bounds must be ruled as a set, by the architect**, and the ceiling's may-only-lower constraint
  means the designer has no instrument to fix it.
- **RP-3 makes S2 a breaking change for an ordinary consumer configuration** and breaches a
  shipping condition `pm-agent` marked binding.
- **RP-7 is the availability mirror** of the security posture and must be ruled **together with**
  RP-5, since the two point in opposite directions.

**What this panel does NOT say.** It does **not** say revision 4 is poor work. On the
completeness lens's brief revision 4 is **excellent**: every re-derived citation correct, the
coverage map honoured on every traceable ruling, the live measurement reproducing exactly, and
E-8 escalated rather than absorbed — an escalation this panel **upholds and strengthens**. The
central algorithmic claim **survived a direct cross-vendor attack**. The blocking findings are
concentrated in **the seams between rulings** — between AM-19 and AM-22, between AM-21's two
directions, between AM-26's reasoning and its conclusion — which is exactly where §9.4's first
standing instruction said to look, and it is why that instruction has now produced the best
findings in **both** runs.

**Loop state.** Amendment 3 records revision 4 as **round 4** of the architect ↔
`technical-design` loop against a CORE cap of **5**. This artifact is the round-4 gate output.
**Round 5 is the last**; if it does not converge, the non-convergence escalates to the human with
the iteration count and the sticking point. **RP-1 may not be resolvable inside that loop at
all** — it is `pm-agent`'s and the human's — and the panel flags that as the likeliest reason
round 5 will not close the chain.

**Nothing in this document authorizes a merge, a protected-surface edit, or a line of code.**

---

## Human Review Required

**RISK: MEDIUM.** This artifact is evidence, not code: it changes no behaviour and adds one
document. The risk it carries is **being wrong in the direction of blocking** — three CRITICAL
findings that hold up an open `priority:critical` security fix. Each blocking finding is
therefore stated with its verification path so it can be overturned on evidence rather than
judgement: **RP-1** is verified against `probe.py:292-322` **and** against live repository state
(97-issue sweep, 1 match); **RP-2** is verified against the sort key at TD `:716` and AM-22's
own bounds table; **RP-3** is verified against TD §3 row F2, `framework_consumer_files.txt`, and
`hos_install.sh:615-626`; **RP-4** is verified against three separate sites in Amendment 3. **If
any of these is wrong, the fastest way to show it is to check those specific lines.**

**The specific ways this artifact could fail while looking correct:** (i) **the orchestrator is
rank-equivalent to the bundle's authors** and wrote this synthesis, so the class differential
that makes the completeness lens independent does **not** apply to the framing, the severities,
or the verdict; (ii) **run 1's ~40 verified-sound claims were deliberately not re-derived**, on
Amendment 3's instruction, so a defect among them is invisible to this run **by design**;
(iii) **the adversarial lens saw three of five documents** and a finding turning on base-ADR
text would have been missed; (iv) **RP-12 is an unverified construction** and is marked so —
crediting it as established would send the architect after a pillar that may not be weak;
(v) **the §2 measurement is a single sweep at one moment** — `f7_live_matches=1` is a floor that
rises with every routine re-milestoning, and a reader who quotes "1" as the scale of RP-1 has
misread it; (vi) **the two lenses' verdicts differ** and a reader who takes the completeness
lens's BUILD-WITH-CONDITIONS in isolation would clear a design with three live criticals — the
verdicts answer different questions and only the conjunction is the panel's.

**CONFIDENCE: HIGH** on **RP-1**, which is verified twice over — at code level in the docstring
and implementation, and empirically against all 97 candidates — and on **RP-3** and **RP-4**,
both verified line-by-line against the working tree by a rank-differentiated lens. **HIGH** on
§2's measurement, which I ran myself and which reproduces the architect's 97 independently.
**HIGH** on §3's verified-sound list and §4's rejections. **MEDIUM-HIGH** on **RP-2** and
**RP-5**: the constructions are sound as reasoning about the specification, but **no code exists
yet to execute them against**, so they are arguments about a design, not observations of a
system. **MEDIUM** on **RP-6** and **RP-7**, which are correct as stated but whose severity
depends on rulings that have not been made. **LOW-MEDIUM** on **RP-13** and **RP-14**, which the
adversarial lens raised without the repository access needed to ground them, and which are
recorded at LOW for that reason rather than dismissed.

**BLAST RADIUS:** one new document under `docs/v0.7.0/`. No code, no configuration, no protected
surface, no test. The blast radius of the *findings* is the S1/S2 change set, which remains
unbuilt.
