# ADR-1540 — AMENDMENT 1: rulings on `technical-design`'s escalations E-1 … E-4 and findings FIND-1 / FIND-2

**Status:** ACCEPTED — binding on `technical-design` and `coder`, subject to the checklist in §3. This document **amends** `docs/v0.7.0/ADR-1540-request-intake-risk-agent.md`; it does not replace it. Every decision in the original ADR (AD-1 … AD-15, ESC-1 … ESC-6) stands **except** where a ruling below names it.

> **AMENDED 2026-09-15 — read `docs/v0.7.0/ADR-1540-AMENDMENT-2-escalation-rulings.md` before quoting anything in §3 to the human.** `technical-design` revision 2 returned three further escalations (E-5, E-6, E-7) against the rulings below; all three are ruled in **Amendment 2** (AM-14 … AM-18, AF-6, AF-7). **Where Amendment 2 and this document differ, Amendment 2 governs.** Two corrections in it are to *this* document and both are load-bearing: **AM-14/AF-6** withdraw **AM-3**'s cutover recommendation and correct its volume claim (the cutover set is **≥93**, not "far smaller than 46"), and **AM-17** corrects **§3(b) H1 item 4** — the protected-surface count for S1/S2 is **five**, not four, because `.github/workflows/**` is in scope. Every superseded passage below carries an inline marker. **§3(b) H1 is superseded in full: Amendment 2 §3(b) carries its replacement text, and that is what must reach the human.** A reader who clears H1 from the text below clears a four-surface change set for a change that ships five.

**Date:** 2026-09-15 (original), amended 2026-09-15 (Amendment 2)
**Author:** architect
**Amends:** AD-2 (clarified, not widened), AD-3, AD-4, AD-6, AD-11, AD-13, AD-14, §3 build order. Also amends, cross-ADR: `ADR-1604` AD-5 and AD-9, and `ADR-1542` §4.9 (G11).
**Inputs:** `docs/v0.7.0/ADR-1540-request-intake-risk-agent.md`; `docs/v0.7.0/TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md` (§0.2 FIND-1, §0.3 FIND-2, §0.4 FIND-3, §0.5 FIND-4, §7 residuals/deviations, §8 E-1 … E-4); `docs/v0.7.0/REQUIREMENTS-1540-request-intake-risk-agent.md`; #1539 and #1540 read live this session via `bootstrap/query_issues.sh --app worker`; the working tree at `7e5c2a82`.
**Consumers:** `technical-design` (revision of the S1/S2 document), then the dual-lens adversarial panel #1540 mandates, then `coder`.

---

## 0. Verification — what I re-derived before ruling

I ruled on nothing I did not check. Every row below was read from this clone's working tree at `7e5c2a82` (branch `worker-1539-e1-architect-ruling-260915083001-268743`, cut from `main`; neither file listed has local modifications) or from live GitHub through `bootstrap/query_issues.sh`.

| Claim I relied on | Verified | Evidence |
|---|---|---|
| FIND-1 is real | **yes** | `scripts/automation/lib/probe.py` `_verify_codeowner_actor`: `elif ev == "milestoned": relevant_actors.append(event.get("actor") or {})` — the `milestone.title` field on the event payload is never read |
| FIND-2 is real | **yes** | same function: `_run_gh(["/repos/.../issues/<n>/events?per_page=100"])` — no `--paginate`, no page loop |
| `next_candidates.jq`'s only eligibility filter is the `needs-human` exclusion, and nothing reads `.user` | **yes** | `scripts/automation/lib/next_candidates.jq`, read in full |
| `bin/hos-cron:1137` still inlines `--jq "$(cat …next_candidates.jq)"` | **yes** | `bin/hos-cron:1137-1138` |
| `ADR-1604` AD-5 binds the stuck-marker exclusion to `next_candidates.jq` **and** its inlined twin, covered by `tests/automation/test_next_candidates.py` | **yes** | `docs/v0.7.0/ADR-1604-worker-self-split-isolation.md:121-128`; `TECHNICAL-DESIGN-1604-…:192-202, :274-276, :381 (Component H), :609, :975` |
| `ADR-1542` §4.9 (G11) plans "one call wrapping the canonical `next_candidates.jq`" and its slice 3 requires `worker-cron-prompt.md:101`'s `$(cat …jq)` to be deleted | **yes** | `docs/v0.7.0/ADR-1542-sandbox-script-coverage.md:120, :230` |
| #1539 is **open**, `priority:critical`, `needs-ai`, milestone v0.7.0 | **yes** | live query this session |
| #1540's 2026-09-15T06:47Z human ruling says the chain "just needs … kicked off" and does not mention ESC-2 or ESC-6 | **yes** | live `--comments 1540`, read in full |
| The human-proxy App's filings are LLM-composed (the premise of E-1) | **yes** | `CLAUDE.md` §"HOS: Human-proxy session identity": *"file an issue for the autonomous worker to pick up"*; `bootstrap/create_issue.sh` accepts `--app human` and has **no** per-instance confirmation flag (unlike `submit_pr.sh --confirmed`) |

### AF-5 (NEW — severity **HIGH** for the design's usability, and it invalidates one sentence of E-1's own recommendation): `/approve` can never satisfy AD-4 as the gate is designed, because the workflow's label write is performed by `github-actions[bot]`, not by the CODEOWNER who typed the command.

`.github/workflows/label-swap.yml` runs the `/approve` label edit with `GH_TOKEN: ${{ github.token }}`. The resulting `labeled` event's actor is therefore the GitHub Actions bot — `type == "Bot"`, login ending `[bot]` — which `is_bot_reviewer` (`scripts/framework/require_human_approval.py:140-158`, layer 1 and layer 2) excludes unconditionally, whether or not it appears in `BOT_ACCOUNTS`. The only human-identified artefact of an `/approve` is **the comment**, whose author is GitHub-reported and unforgeable.

`technical-design`'s `verify_codeowner_actor` (§1.4) walks **events only**. Consequence, as designed:

- In the S2 era, a CODEOWNER commenting `/approve` produces **no authorization**. The issue flips labels, the workflow posts "✅ … authorized by @ScottThurlow", and the gate still refuses it. That is fail-closed and therefore safe — and it is a silent no-op that *looks* like success, which is the exact failure mode AD-6 already condemns in the same workflow's `2>/dev/null || true`.
- E-1's option C in the technical design says an issue "becomes selectable when `ScottThurlow` personally applies `needs-ai` or the milestone from their own account — **or comments `/approve`**." The last clause is false. The first two are correct, and are the mechanism #1643 passes on.

AD-4's own text says *"walk the issue's events **and comments**"*; the design implemented half of it. I rule on this in **AM-6**. The original ADR under-specified it, so the affected-sign-off analysis in §2 covers it.

### Verification gaps, stated rather than asserted around

1. **I did not re-derive FIND-3's authorship counts** (46/100 human-proxy-authored; four of five candidates gated). `bootstrap/query_issues.sh` exposes no author field and I did not hand-roll a `gh api` read. I corroborated only that `scottthurlow-claude[bot]` is the author of every comment on #1540. **My E-1 ruling does not turn on the number** — it turns on the structural fact that every human-proxy filing is LLM-composed, which I did verify. The count sizes the human's burden, and is the part of this that is the human's to weigh; the checklist in §3 flags it as "asserted by `technical-design`, not re-derived by me."
2. **Live GitHub repository settings remain uninspected** (branch protection, "Require review from Code Owners", collaborator permission levels). Same gap the requirements doc and the original ADR both declared. ESC-2 turns on the third and stays the human's.
3. **I did not verify #1643's `needs-ai` label actor live.** The claim that a human's own label click produces a passing `labeled` event is taken from `technical-design` §2.6. It is mechanically obvious from the code path, but it is the load-bearing ergonomic valve in AM-1 and it deserves one live confirmation before S2 merges — I put that on the checklist as a coder-verifiable acceptance test rather than an assumption.
4. **No exploit of any kind was attempted.** This is a public repository.

---

## 1. Rulings

### AM-1 — E-1 (BLOCKING). **Option C, with D as the ergonomic wrapper.** AD-2 is not widened, not softened and not reinterpreted. The routing question is answered: the *architecture* is mine and is ruled here; only the *operational consequence* is the human's, and it is already ESC-6 item 2 — not a new escalation. (Amends: nothing. Confirms AD-2 as written; resolves the escape hatch AD-2 opened.)

**AD-2 stands verbatim.** A bot-authored issue is trusted only if it also matches an enumerated machine-filing marker. The human-proxy App matches none, and none can be made for it.

`technical-design`'s subset argument is correct and I adopt it as binding reasoning: *a marker is meaningful only when the set of call sites that can emit it is a strict subset of the set of call sites the identity can reach.* For the worker and overseer Apps, deterministic filings are a strict subset of all their filings, so the marker carries information. For the human-proxy App, **every** filing is LLM-composed, so any marker it stamps is present on all of them and is isomorphic to trusting the identity outright. That is not a preference; it is the definition of a vacuous predicate.

Ruling on each option:

| Option | Ruling | Reason |
|---|---|---|
| **A** — stamp a marker on `--app human` filings | **REJECTED** | Vacuous by the subset argument. Reopens the laundering path AD-2 closes, under a new name, while every test passes. |
| **B** — a `--confirmed` flag on `create_issue.sh --app human` | **REJECTED, and forbidden** — see AM-2 | It is a command-line flag whose presence marks a request approved. AD-13 forbids exactly that. The `submit_pr.sh --confirmed` precedent does not transfer: there the flag gates a *mutation the human is watching*, and it confers no standing authority on any later autonomous decision; here it would confer autonomous-build authorization on a future cycle, read by a machine, with no human present at read time. |
| **C** — close the live-path gap through **AD-4, not AD-1** | **ADOPTED** | Adds no trust concept, widens nothing, and uses only mechanism the ADR already binds. An issue filed by the human-proxy App is untrusted-*authored* and becomes selectable when the human, **from their own GitHub account**, applies the dispatch label or the target milestone to it. |
| **D** — the human-proxy session stops self-applying the dispatch label and ends every filing by telling the human the exact act needed | **ADOPTED as the ergonomic wrapper**, and it is *also* the correct hygiene fix independent of ergonomics | A human-proxy session applying `needs-ai` to its own filing is the same self-authorization shape as the worker's Step 0 (VF-3), one identity removed. It should stop regardless of E-1. The `CLAUDE.md` human-proxy-section edit this needs is a protected-surface change, human-gated at merge, and is **not** pre-authorized here (AD-14). |

**Binding consequences of C+D:**

1. **The authorizing act must be performed by the human's own account.** `bootstrap/edit_issue.sh --app human` writes as `scottthurlow-claude[bot]`, which `is_bot_reviewer` excludes (layers 1 and 2). Any tooling or documentation that offers `edit_issue.sh --app human` as the approval path is wrong and must not be written. The valid S2-era acts are: the GitHub web UI, the GitHub mobile app, or a personal-access-token `gh` invocation under `ScottThurlow`. **This sentence must appear verbatim in the revised design and in whatever the human is asked to do at cutover** — a gate whose documented approval path silently does nothing is worse than no gate.
2. **`/approve` is NOT an authorization path in S2.** See AM-6.
3. **Nothing in S1/S2 may special-case the human-proxy App**, in either direction. It is one of the three `machine-accounts.env` App identities in AD-1(b), narrowed by AD-2 like the other two.

**Routing ruling, explicitly, because `technical-design` asked and because it determines whether this unblocks now.**

The question *"are human-proxy filings trustworthy?"* looks like a product/operations question, and in its raw form it is. **But it is not load-bearing here, and therefore does not need the human's answer to unblock this work** — because even a maximally favourable answer ("yes, the human reads every filing before it is made") has **no sound mechanism to express it**. Expressing it requires either A (vacuous) or B (forbidden by AD-13). There is no third construction that survives; the only expressible forms of "this specific request is authorized" are AD-4's live, GitHub-reported human act — which is option C. So the architecture question collapses to a single admissible answer and **I rule it now**; I do not route it.

What *is* the human's is the **consequence**, and it is already on the record as **ESC-6 item 2** (the standing operational obligation on a single CODEOWNER). E-1 does not create a new escalation; it makes ESC-6 item 2 concrete and numerically specific, which is what the human needs in order to clear it. I have therefore amended ESC-6 item 2's text in §3(b) rather than opening ESC-7. Per the CORE product-boundary checkpoint, AM-1 binds as the technical call **and takes effect only once ESC-6 clears** — which was already true of every decision in the original ADR.

**The honest cost, stated so the human is not surprised:** this converts a frictionless path into a one-act-per-issue path, and the mechanism's most likely real-world defeat — named in the original ADR's own closing section — is a single overloaded CODEOWNER clicking through without reading. Architecture cannot prevent that. AM-3 bounds the volume; it does not remove the obligation.

### AM-2 — AD-13 is clarified: a per-filing confirmation flag is a widening knob. (Amends AD-13 — additive, strictly stricter.)

AD-13 reads *"No environment variable, label, issue content, config file, or command-line flag may add a trusted actor, mark a request approved, or disable the gate."* Add, binding:

> This includes a flag, argument, body token, or HTML marker passed at **issue-creation** time that causes the resulting issue to be treated as trusted or approved — by any tool, under any identity, with any documented human-confirmation convention attached to it. Authorization is only ever derived live, at selection time, from a GitHub-reported act by a verified human CODEOWNER (AD-4). A creation-time assertion is a claim about a fact the reader cannot check.

This is what forecloses E-1's option B permanently, rather than leaving it to be re-proposed each time the queue feels slow. It is a narrowing of the configuration surface, which AD-13 permits and the CORE contract requires to be one-way.

### AM-3 — The backfill: **no grandfathering list** (binding, architecture). ~~The volume is far smaller than 46~~, and the choice of how to drain it is the human's. (Amends AD-14 by adding a cutover clause.)

> **[PARTLY SUPERSEDED BY `ADR-1540-AMENDMENT-2` AM-14 / AF-6 — 2026-09-15.** The binding rules below — no grandfathering list, the set bounded by the gate's own query, the lazy per-issue drain — are **unchanged and still binding**. The struck volume claim is **wrong**: measured live, the cutover set is **≥93**. The recommendation at the end of this ruling is **withdrawn**. Amendment 2 AM-14 governs both.**]**

**Binding, mine:**

- **A grandfathering list is forbidden.** It is two violations at once: a static list of pre-approved issues is a trusted-set widening (AD-13) *and* a cached eligibility determination (AD-4/FR7 — "an authorization verified at time T is re-verified at T+n; an assessment or approval recorded earlier is evidence to re-check, not a stored grant"). `technical-design`'s instinct against it is right and I make it a rule.
- **The backfill is bounded by the gate's own query, not by the open backlog.** The gate fetches `state=open&milestone=<target>&labels=<dispatch>` (design §2.3 Step C). An issue that is closed, milestone-less, in a non-target milestone, or without the dispatch label **costs nothing at cutover** — it costs one human act at the moment it would otherwise have been selected, which is the same act the human already performs implicitly when they decide it is next. So the cutover set is *the open, dispatch-labelled issues in the active milestone*, not the ~46 open human-proxy-authored issues. ~~Any framing of this as "46 issues on day one" overstates it~~, and the revised design must state the bounded figure with the query that produces it. **[CORRECTED BY `ADR-1540-AMENDMENT-2` AF-6 — 2026-09-15: the boundary rule in this bullet is right; the inference that the bounded set is therefore *small* is wrong. The bounded figure, run this session, is **≥93**. See Amendment 2 AF-6.]**
- **The drain is per-issue and lazy by construction.** Nothing needs to be done ahead of time for an issue nobody is about to build.

**The human's, folded into ESC-6 item 2 (not a new escalation):** whether to do a one-time pass over the active-milestone set at cutover, or to let it drain as each issue comes up. Both are safe; they differ only in whether the worker idles for a cycle or two. ~~*My recommendation:* a single pass over the active-milestone dispatch-labelled set immediately before S2 merges, so the first post-merge cycle is not a silent no-work cycle — with AM-13's visibility requirement as the backstop if it is not done.~~

> **[WITHDRAWN AND REPLACED BY `ADR-1540-AMENDMENT-2` AM-14 — 2026-09-15.** The struck recommendation was made on this ruling's wrong volume claim (AF-6) and before the per-issue act was known to be two acts rather than one (`technical-design` §8/E-5). Amendment 2 AM-14 is the current recommendation and is the only one that should be put to the human. AM-13's visibility requirement is unchanged and is now load-bearing rather than a backstop.**]**

### AM-4 — FIND-1 (HIGH): **CONFIRMED, with an amendment stricter than the one proposed.** Authorization derived from a `milestoned` event must bind to the milestone the work would be selected under; and the "ignore" case must be the safe default, not the vulnerable one. (**Amends AD-4.** Changes behaviour in `scripts/automation/lib/probe.py`, which consumer deployments inherit.)

FIND-1 is verified in the working tree and the attack path is correct as written: a CODEOWNER deferring a stranger's issue to `Backlog` is, today, indistinguishable at the gate from a CODEOWNER authorizing it for the active milestone. A human's act of *declining for now* becomes the authorization to build. That is the #1539 self-authorization shape laundered through one benign human action, and it is the single most serious thing in `technical-design`'s document.

**AD-4 gains, binding:**

> An authorization derived from a `milestoned` event is valid **only** when the event's `milestone.title` is **exactly equal** (byte-for-byte string equality — never a prefix match, never a normalisation) to the title of the milestone under which the candidate is being considered. A `labeled` event's authorization is likewise valid only for the exact dispatch label being queried (already the shipped behaviour).

**One amendment to `technical-design` §1.4 / §1.6, and it is not optional.** The design makes `expected_milestone_title: str | None = None` reproduce the shipped (vulnerable) behaviour so that nine existing tests pass unmodified, and then defends that with a conformance test asserting both production callers pass a non-`None` value. **That is a defaulted-to-vulnerable parameter guarded by a grep** — the same class as the `--repo-root` and `--exclude-label` affordances the design itself rejects, and it fails open for the next caller who omits it. Invert it:

> **`expected_milestone_title=None` MUST mean "ignore `milestoned` events entirely" — never "accept any milestone."** With `None`, only `labeled` events can authorize. A caller who forgets the argument therefore gets a *stricter* result, not a vulnerable one.

Consequences the coder must accept rather than work around:
- Any existing `probe.py` test that asserts a `milestoned` event authorizes must be **updated to pass the expected title explicitly**. The design's "all fifteen tests pass unmodified" acceptance criterion is **withdrawn for that subset**. A test that must change is the honest signal that behaviour changed; preserving it unchanged was the goal that produced the unsafe default.
- `probe.py`'s milestone strategy passes `issue["milestone"]["title"]`; a record with no milestone object is skipped, never authorized (design §1.6 and §2.3 D5.2 — both correct, both retained).
- **New residual R-7, to be recorded in the S2 work item:** renaming a milestone de-authorizes every issue authorized under the old title until a human re-acts. This is fail-closed and an availability cost only. It is the correct trade against prefix-matching, which this repo's own em-dashed milestone titles would make dangerously loose (`bootstrap/edit_issue.sh` prefix-matches milestones by design; **the gate must not**).

**Does this amend the shipped ADR?** Yes. AD-4 previously blessed *"`_verify_codeowner_actor`'s existing, shipped, tested shape"* by reference. That shape is under-specified in exactly this way. AD-4 is amended as above; §2 carries the startup-gap and affected-sign-offs analysis, since `probe.py` is shipped code that consumer deployments inherit.

### AM-5 — FIND-2 (LOW): **CONFIRMED.** Bounded pagination as specified. (Amends AD-4 — mechanical.)

The unpaginated fetch is verified. The failure direction is safe (a recent CODEOWNER act beyond the first page is invisible → not authorized → gated), so this is an availability defect, not a security one — and on a repo whose issues are relabelled many times, it is a live one.

**Binding:** the fetch wrappers (never the pure predicate — AD-1's no-network rule holds) paginate with `per_page=100`, bounded to **10 pages / 1000 events**, normalising `gh --paginate`'s concatenated page arrays with the existing `re.sub(r"\]\s*\[", ",", out)` idiom already used in `require_human_approval.py` (verified present at `:130-138`). Exhausting the bound without a match is **"not authorized" (skip that candidate), never an error**; a transport failure remains exit 2. The bound being hit MUST emit a stderr diagnostic naming the issue number — otherwise R-5 is an invisible permanent stall on exactly the repo's most-worked issues.

**Permitted but not required:** walking pages from the newest end (via the `Link: rel="last"` cursor) instead of the oldest, which would make the bound effectively unreachable. If the coder does this, the pure function's contract is unchanged and the events list passed in must still be in API order. I do not mandate it; the 10-page bound plus a diagnostic is sufficient for S2.

### AM-6 — AF-5: `/approve`'s label write is not an authorization signal, and never can be. S2 ships without it; **S3 MUST close it by reading the approval comment's GitHub-reported author.** (Amends AD-6 and AD-4.)

**Binding:**

1. **A label or milestone write performed by a workflow, a bot, or any App identity is never an authorization signal**, regardless of who triggered it. Authorization attaches to the GitHub-reported author of the human act itself. `label-swap.yml` writes labels under `${{ github.token }}` (verified), so the CODEOWNER's `/approve` leaves its human fingerprint **only on the comment**.
2. **S2 is event-only and that is correct** — do not bolt comment-reading onto the critical-path fix. The S2-era human act is the CODEOWNER's own label or milestone application (AM-1).
3. **S2 MUST NOT ship while the repo tells a human that `/approve` authorizes work.** Concretely, the S2 change set must state, in `docs/LABELS.md` and in the revised design, that in the S2 era `/approve` performs a label swap and **does not** authorize autonomous selection. A human who types `/approve` and sees "✅ authorized by @…" while the gate silently refuses is being lied to by their own tooling.
4. **S3's AD-6 work gains a required element:** the gate's authorization test accepts, in addition to the event sources, **a comment whose GitHub-reported author is a verified human CODEOWNER and whose first line begins with the approval command** — parsed with the same anchoring `label-swap.yml` already uses (first word of the first line). The comment *body* remains untrusted content; only the command token and the API-reported author are read. This costs one additional API call per untrusted candidate, on the path the ADR's cost note already accepts as non-free.
5. AD-6's other three rules (a bot approval never satisfies the gate **including the human-proxy App**; the `2>/dev/null || true` goes; parser count three → two) are unchanged.

### AM-7 — E-2: **declined, as recommended.** Do not build the separate deterministic-filing App now. R-4 is an accepted, recorded residual with named revisit triggers. (Amends AD-14's scope list.)

The analysis is right: within one bot identity no in-band marker is unforgeable against induction, because the inducing agent has the same write authority and can read the marker table out of the repo. The only sound construction is a separate App identity used exclusively by deterministic filing code.

**Ruling: not now.** It is structural (a new App to provision, rotate and document in `machine-accounts.env` and `AGENT-IDENTITY.md` §7), and S2 is the live-path fix for an open `priority:critical`. The residual it would close (**R-4**) requires an induced LLM under a trusted App identity to reproduce a deterministic template byte-for-byte *and* apply the target milestone *and* apply the dispatch label — and on this repo exactly one machine-filing site can reach the candidate set at all (design §1.5.1(iii)). That is bounded and strictly smaller than today's no-check-at-all.

**Binding revisit triggers — any one of these reopens E-2 as a required decision, not an option:**
- the assessment layer (S5) ever gains authorization-relevant authority (AD-13 says it must not, so this trigger is a tripwire on AD-13 itself);
- any entry in `MACHINE_FILING_MARKERS` acquires an LLM-composed emitting site — in which case that entry must be **removed from the table in the same change**, because its subset property has gone;
- a second machine-filing site becomes reachable by the milestone-scoped candidate query.

The marker table's conformance tests (design §6.1 `test_marker_table_literals_exist_in_emitting_files`, `test_issue_creation_site_count_is_pinned`) are the mechanism that makes these triggers detectable. They are binding, not optional.

### AM-8 — R-3 (reverse-and-re-apply): accepted for S2, **closed in S3**, with the rule named now so it is not redesigned from scratch. (Amends AD-5 by adding a clearing-event invariant.)

R-3: a CODEOWNER `milestoned` event that was later `demilestoned` and re-applied by a bot to the same milestone still authorizes, because reversal events are ignored.

I am not folding this into S2. With AM-4's title binding in place, the surviving case requires the human to have genuinely placed the issue in the *work* milestone at some point — materially weaker than FIND-1, where the human's act meant the opposite. Against that, honouring reversal events changes when authorization evaporates, and I cannot verify from here how often bots toggle labels and milestones on issues in normal operation; getting that wrong stalls all autonomous work behind a human re-click, which is the failure mode AD-15 warns about. Adding it to the `priority:critical` slice is the wrong risk.

**Binding for S3, stated now:**

> Authorization from an event source is evaluated against the issue's **current** state of that signal: a `demilestoned` (for the matching title) or `unlabeled` (for the matching label) event **clears** any authorization derived from a prior matching event, regardless of which actor performed the reversal. Re-establishment requires a fresh qualifying event by a verified human CODEOWNER. A bot re-applying a signal a human once applied does not restore the human's authorization.

S3 must measure the availability impact (how many live issues would be de-authorized by the rule on the day it ships) before enabling it, and report it in the PR body. **R-3 must be recorded in the S2 work item alongside R-1**, per the original ADR §3's standing requirement that named residuals be written into the work item rather than discovered later.

### AM-9 — E-3: **S2 ships first.** `ADR-1604` AD-5's mechanism clause is amended; its semantics clause stands. Component H's sign-offs are orphaned. (Amends `ADR-1604` AD-5.)

Verified: `ADR-1604` AD-5 binds the stuck-marker exclusion to `next_candidates.jq` *and* its inlined twin, "in lock-step, covered by the existing `tests/automation/test_next_candidates.py` divergence test"; `TECHNICAL-DESIGN-1604` §4.6/§4.7 (Component H) and its test row implement exactly that. S2 deletes all three artefacts. Neither has shipped.

**Binding:**
1. **Sequencing: S2 first.** It is the live-path fix for an open `priority:critical` (#1539) and the original ADR §3 makes it the lead slice. #1604 is `priority:high`. Nothing in #1604 is blocked by waiting — its other components (branch ownership, breaker rungs, the stuck-set query) are untouched.
2. **`ADR-1604` AD-5 second bullet is amended**, effective from this document: the queue exclusion is expressed **once**, as an entry in `select_work_candidates.py`'s `EXCLUDED_LABELS` constant. There is no inlined twin and no lock-step divergence test, because there is no second implementation — which is the whole point of AD-3. AD-5's *semantics* (one narrow marker, authoritative for both the count and the exclusion; the generic human-attention label stays advisory and is never counted) are **unchanged and still binding**. `technical-design`'s instinct to make `EXCLUDED_LABELS` a named module constant rather than an inline tuple is the right seam and I bind it as the landing site.
3. **Affected sign-offs.** `TECHNICAL-DESIGN-1604` §4.6 (Component H), its §4.7 component-table row for Component H, and its test row for `tests/automation/test_next_candidates.py` were approved against a contract in which `next_candidates.jq` exists and is the single source of truth. **Those sign-offs are orphaned and must be re-reviewed against the amended contract before #1604 is built.** The rest of `TECHNICAL-DESIGN-1604`'s sign-offs stand — the amendment touches the *location* of one exclusion, not the mechanism it implements.
4. **Whoever picks up #1604 next must carry this amendment into that document** (re-point §4.6/§4.7/tests, note AD-5's amended bullet) as the first step of the work, not as a cleanup afterwards. If #1604 somehow reaches build before S2 merges, it ships against `next_candidates.jq` unchanged and S2 absorbs the two exclusions during its deletion — that ordering is permitted, is the only other admissible one, and must be stated in whichever PR lands second.

### AM-10 — Cross-ADR: `ADR-1604` AD-9's sub-issue filing is authorized by **derivation from its parent**, and is NOT added to the machine-filing marker table. (Amends `ADR-1604` AD-9 point 2.)

`ADR-1604` AD-9 (verified at `:164-171`) says sub-issues *"never acquire [authorization] by authorship"*, that each carries a machine-readable derivation link and is authorized because the parent was — and then, in point 2, that *"sub-issue filing is an enumerated machine-filing path under ADR-1540's AD-2"*. Points 1 and 2 pull in opposite directions and the technical design for #1540 did not catch it, because sub-issue filing does not exist yet.

**Ruling: point 1 governs; point 2 is amended.** A sub-issue's title and body are composed by an LLM from the parent's content, so it is squarely class (ii) under AM-1's subset argument — a marker on it would be exactly as vacuous as a marker on the human-proxy App, and worse, its content derives from the very issue whose trust is in question. **Sub-issue filing MUST NOT appear in `MACHINE_FILING_MARKERS`.** Its authorization is an AD-4-class live derivation: at selection time the gate resolves the parent from the machine-readable link and requires the parent to be authorized *now*, by the same test; a sub-issue whose parent cannot be resolved, or whose parent is not currently authorized, is not selectable. Never cached (FR7).

Designing that derivation check belongs to #1604's chain, and it is a **new consumer of AD-1/AD-4's primitive**, not a second trust definition (#1135). S1/S2's enumeration is complete as of today and does not need to anticipate it.

### AM-11 — E-4.1: `ADR-1542` §4.9 (G11) is **superseded** by S2's entry point, not merely overlapped. (Amends `ADR-1542` §4.9.)

Verified: G11 plans "one call wrapping the canonical `next_candidates.jq`" and `ADR-1542`'s slice 3 requires `worker-cron-prompt.md:101`'s `$(cat …jq)` to be deleted. `select_work_candidates.py` is invocable with wholly literal arguments from the cron prompt (design §2.5, with `@@MILESTONE_NUMBER@@` substituted before the LLM sees the text) and deletes that exact call site. Building G11 separately would produce the duplicate-gate defect (#1135) in its purest form: two wrappers over the same selection decision, one of them trust-gated.

**Binding:** G11 is marked superseded by S2 in `ADR-1542`'s next revision; its slice-3 line item is satisfied by S2's merge; its sign-offs **for that item only** are orphaned. `ADR-1542`'s other slice-3 items (G10 identity assertion, G7 merged sweep, G4 release tier, the `check_pr_reviewed.sh`/`pr_readiness.py` retrofits) are untouched. **Acceptance condition, binding on S2:** the S2 entry point must actually satisfy G11's requirement — the cron-prompt fallback must contain no command substitution, no variable expansion, no inline `jq`, and no backslash continuation. The design's §6.3 conformance test is the mechanism; it is required, not optional.

### AM-12 — E-4.2 / DEV-1: **approved.** S2 filters `pull_request` records, with one added acceptance test. (Amends AD-14's "PR intake stays out of scope" by making the exclusion explicit.)

The `issues` REST endpoint returns PRs; `next_candidates.jq` never filtered them and `bootstrap/query_issues.sh --list` and `bin/hos-cron`'s milestone-less gate both do. Leaving them in would mean the *issue* gate silently adjudicates PR eligibility, which contradicts AD-14's scope boundary far more than filtering them does. Both behaviours are a change; the filtered one is intentional, testable, and cheaper (it saves an events call per bounced PR).

**Binding condition** — because this is the one place where a "no behaviour change" claim could be wrong in a way that costs the worker its bounce loop: the S2 change set MUST include a test demonstrating that **a bounced draft PR carrying the dispatch label is still surfaced to the worker through `bin/hos-cron`'s PR path (`:1085-1099`) and still prevents the `#1395` no-actionable-work early skip**, with the candidate list empty. If that test cannot be made to pass, DEV-1 is withdrawn and the PR records stay in — escalate back to me rather than adjusting the skip logic.

### AM-13 — Cutover visibility: a gate that holds everything must say so loudly, in S2. (Amends AD-11 by pulling a minimal held-count forward from S6; amends AD-3's logging.)

The single most likely operational failure of this mechanism is not a bypass. It is that S2 merges, every candidate is gated, and the repo looks like an empty backlog for days — which is precisely the silent-skip class `CLAUDE.md` names as the failure mode to guard against.

**Binding for S2:**
1. DEV-2 (removing `2>/dev/null` from the `bin/hos-cron` candidates call) is **approved and required**, not optional.
2. The gate's stderr summary already carries `eligible=<M> gated=<G>` (design §2.3 Step F). When `M == 0 and G > 0` it MUST emit an additional, distinct, unmissable line naming the count and the reason tokens involved, distinguishable at a glance from "the milestone is empty."
3. `bin/hos-cron` MUST surface that condition into the cycle log. It MUST NOT be routed into a new escalation issue in S2 — that is AD-10's bounded-retry/escalation design and it belongs with the assessor slice; a per-cycle issue-filing loop here would be its own denial-of-wallet.

This is the minimal form of AD-11's held-request listing ("it cannot drift from the gate, because it *is* the gate"), pulled forward because the cutover is when it matters most. The full listing mode stays in S6.

---

## 2. Startup-gap recovery and affected-sign-offs analysis

**The required question, asked of every item in §1:** *should this have been settled in the initial architecture review, before design and code were built against it?*

| Ruling | Should it have been settled earlier? | Consequence |
|---|---|---|
| AM-4 (FIND-1) | **Yes.** AD-4 blessed `_verify_codeowner_actor`'s shipped shape by reference without stating the contract it had to meet. The shape shipped for #1539 (`abef062e`) with no `technical-design` stage at all, so no document ever stated it. | **`startup-artifact-gap` issue required** (see below). ADR amended. Affected sign-offs below. |
| AM-6 (AF-5) | **Yes.** AD-4 said "events **and comments**" and AD-6 assumed `/approve` was reusable as an authorization channel; neither checked which identity performs the workflow's label write. A five-minute read of `label-swap.yml`'s `env:` block — which AD-6 cites for three other properties — would have caught it. | Fold into the same `startup-artifact-gap` issue. AD-6 amended. No code exists against it yet, so no sign-off is orphaned. |
| AM-10 (`ADR-1604` AD-9) | **Yes**, at ADR-1604 time. Two clauses of one decision contradict. | Fold into the same issue as a second instance of the same class (an ADR asserting a mechanism without checking it against the mechanism's own constraints). `ADR-1604` AD-9 amended; nothing built against it. |
| AM-1, AM-2, AM-3, AM-7, AM-8, AM-9, AM-11, AM-12, AM-13 | **No.** These are decisions a technical design is supposed to surface — escape hatches the original ADR deliberately opened (AD-2's), coordination between designs written in parallel, and refinements of a build order. This is the escalation path working. | No gap issue. |

**The `startup-artifact-gap` issue** — one issue covering AM-4, AM-6 and AM-10 — has **not** been filed by me (this task is documentation-only and I do not open issues from an architecture ruling). Filing it is on the checklist in §3(a) as a worker action, and its framing is: *a `priority:critical` security fix (#1539, `abef062e`) went from human ruling to merged code with no requirements or technical-design stage, so the contract its central predicate had to meet was never written down; two defects (FIND-1 HIGH, FIND-2 LOW) and one unstated impossibility (AF-5) were found by the first design document to look at it, five days later.* `technical-design` §7.3 reaches the same conclusion independently; this is confirmation, not a second finding.

**Affected sign-offs — which stand, which must re-review:**

| Prior sign-off | Disposition | Changed from `technical-design` §7.3? |
|---|---|---|
| `abef062e`'s approvals for `probe.py::_codeowners_humans` | **Stand.** Promotion is behaviour-identical and the three shipped assertions re-run against the new home. | No |
| `abef062e`'s approvals for `probe.py::_verify_codeowner_actor` | **RE-REVIEW REQUIRED — `code-reviewer` and `security-reviewer`, when S1 lands.** `technical-design` recorded these as "stand, because `expected_milestone_title=None` preserves shipped behaviour bit-for-bit." **AM-4 withdraws that preservation**: `None` now means "ignore `milestoned` events," so the milestone path's behaviour genuinely changes and the approvals are orphaned for that path. | **Yes — this is a direct consequence of my ruling and `technical-design` must update §7.3 accordingly.** |
| `abef062e`'s `DECISIONS.md` claim that the fix "closes the self-authorization loophole" | **RE-REVIEW REQUIRED**, and the entry needs a correction note when S1 lands. It is an orphaned *claim*, not orphaned code. | No (confirmed) |
| `TECHNICAL-DESIGN-1604` Component H (§4.6, §4.7 row, test row) | **ORPHANED — re-review before #1604 is built.** | No (confirmed; AM-9 adds that `ADR-1604` AD-5's mechanism bullet is amended too, which `technical-design` did not have standing to do) |
| `ADR-1542` §4.9 (G11) | **SUPERSEDED — sign-offs orphaned for that item only.** | No (confirmed) |
| `ADR-1604` AD-9 | **AMENDED (point 2).** Nothing was built against it; no sign-off is orphaned, but #1604's chain must consume the amended text. | New — I found this; it is not in `technical-design`'s list |

**No code approved against a superseded contract is left unaudited.** The only shipped code this amendment changes is `probe.py`'s milestone-strategy authorization path, and it is explicitly routed to re-review above.

---

## 3. What remains blocking before `coder` may build S1/S2

This section is written to be quoted to the human with no other context. #1539 is an **open `priority:critical`** security issue: on this public repo, an issue filed by anyone can today be labelled by the worker's own triage step and then selected and built by the worker, with no code anywhere in that path checking who filed it. **S2 is the fix.** S1 is the shared trust module S2 needs. Nothing below is a request to re-decide the design; it is the list of gates that must clear before code is written.

### (a) CLEARED by the architect — no further ruling needed

| # | Item | Status |
|---|---|---|
| A1 | **E-1** (BLOCKING escalation): human-proxy-App-authored issues are gated. **Ruled: option C + D.** No widening of AD-2; the approval act is the human's own GitHub account applying the dispatch label or the target milestone. Option B (a `--confirmed` creation flag) is now explicitly forbidden by AD-13 (AM-2). | Cleared (AM-1, AM-2) |
| A2 | **Backfill**: **no grandfathering list** (it is both a trusted-set widening and a cached authorization). The cutover set is bounded by the gate's own query — open + dispatch-labelled + in the active milestone — **not** the ~46 open human-proxy-authored issues. **[VOLUME CORRECTED and RECOMMENDATION WITHDRAWN by `ADR-1540-AMENDMENT-2` AM-14 / AF-6 — the bounded set is **≥93**; see A13 there.]** | Cleared (AM-3) |
| A3 | **FIND-1 (HIGH)** — confirmed and amended **stricter** than proposed: exact milestone-title equality required, and an omitted argument must mean "ignore milestone events," not "accept any milestone." Amends AD-4; some `probe.py` tests must change. | Cleared (AM-4) |
| A4 | **FIND-2 (LOW)** — confirmed: bounded pagination, 10 pages / 1000 events, with a stderr diagnostic when the bound is hit. | Cleared (AM-5) |
| A5 | **New architect finding (AF-5)**: `/approve` **does not and cannot** authorize work in S2 — the workflow's label write is performed by `github-actions[bot]`, not by the human who typed it. S2 must document this; S3 must close it by reading the approval comment's author. | Cleared (AM-6) |
| A6 | **E-2** — separate deterministic-filing App: **declined for now**, with three named triggers that reopen it. **R-3** (reverse-and-re-apply): accepted for S2, closed in S3 by a stated rule; must be recorded in the S2 work item alongside R-1. | Cleared (AM-7, AM-8) |
| A7 | **E-3** — sequencing: **S2 first**; `ADR-1604` AD-5's mechanism bullet amended (one `EXCLUDED_LABELS` constant, no twin, no lock-step test); Component H sign-offs orphaned and must be re-reviewed before #1604 is built. | Cleared (AM-9) |
| A8 | **E-4** — `ADR-1542` G11 superseded by S2; **DEV-1** (excluding PR records) approved, conditional on a test proving a bounced draft PR is still surfaced through the PR path. | Cleared (AM-11, AM-12) |
| A9 | Cross-ADR: `ADR-1604` AD-9's sub-issue filing is authorized by derivation from its parent and **must not** be added to the machine-filing marker table. | Cleared (AM-10) |
| A10 | **Cutover visibility**: DEV-2 required; the gate must emit a loud, distinct line when it holds every candidate, so a fully-gated queue never looks like an empty backlog. | Cleared (AM-13) |
| A11 | **Worker action, not a gate:** file one `startup-artifact-gap` issue covering AM-4 / AM-6 / AM-10 (§2). Does not block the build. | Worker to file |
| A12 | **`technical-design` revision required before the panel** — the S1/S2 document must be updated for AM-4 (inverted default; withdrawn "tests unchanged" criterion), AM-6 (`/approve` correction in §8/E-1's option C and in §2.6), AM-9 (`EXCLUDED_LABELS` landing site), AM-12 (added test), AM-13 (held-count line), and §7.3's amended sign-off dispositions. | `technical-design` |

### (b) THE HUMAN'S ALONE — an architect must not answer these, and I do not

> **[H1 BELOW IS SUPERSEDED IN FULL BY `ADR-1540-AMENDMENT-2` §3(b) — 2026-09-15. DO NOT QUOTE THE ROW BELOW TO THE HUMAN.** Its item 2 states the per-issue cost as one act when it is **two**, and states a cutover recommendation that is **withdrawn**; its item 4 enumerates **four** protected surfaces when S1/S2 edits **five** — `.github/workflows/**` is missing, and is the surface a reviewer is least likely to supply for themselves (AM-17). Amendment 2 §3(b) carries the replacement text, written to be quoted verbatim. **A human who clears the row below clears a four-surface change set for a change that ships five.** H2 … H7 are unchanged except as noted in H7.**]**

| # | Question | What "done" looks like |
|---|---|---|
| **H1 — ESC-6 (the master gate, 4 parts)** — **SUPERSEDED; see Amendment 2 §3(b)** | Product-boundary clearance for the whole mechanism: (1) **user-visible behaviour** — every request from outside the trusted set now waits for a human decision before any work begins, a new visible hold with a new failure mode (nobody answers); (2) **operational obligation** — a standing duty on the one designated CODEOWNER (`@ScottThurlow`) to personally authorize each outside request. **E-1 makes this concrete and immediate:** with option C ruled, the human-proxy App's own filings are in that set, so the act is required for those too. The act must be performed **from the human's own GitHub account** (web UI, mobile, or a personal `gh`); `edit_issue.sh --app human` will NOT work, because it writes as `scottthurlow-claude[bot]`. ~~Plus the cutover choice: one pass over the active-milestone set before S2 merges, or let it drain lazily~~ **[superseded — AM-14]**; (3) **cost model** (see H2); (4) ~~**four protected surfaces** will be edited (`scripts/framework/**`, `bin/`, `bootstrap/`, `.claude/agents/**`)~~ **[SUPERSEDED — the count is FIVE: `.github/workflows/**` is also edited, because AM-6 point 3 cannot be honoured without changing `label-swap.yml`'s `/approve` confirmation. See Amendment 2 AM-17 and its §3(b) item 4.]** — each human-gated at merge, none pre-authorized. | An explicit yes/no per item on #1540 or #1539. **Blocks S1 and S2.** |
| **H2 — ESC-5** (cost-model value) | The per-cycle assessment cap value. | Blocks **S5 only** — not S1/S2. |
| **H3 — ESC-2** | Does GitHub repo **collaborator permission** count as requester trust? Architect's recommendation: **no** — keep the trust boundary in a committed, reviewable roster rather than in un-versioned GitHub settings. Nobody has inspected the live repo settings (declared gap in all three documents). | A ruling on #1540. **Blocks S1** (it decides whether AD-1 gains a fourth membership category). If the answer is the recommended "no", S1 is unchanged and unblocked. |
| **H4 — ESC-3** | May a CODEOWNER `/approve` a request that has not been assessed — refuse, or allow with a durable override record? (Bound either way: it must never be silent.) | Blocks **S3 only**. |
| **H5 — ESC-4** | Should an unanswered gated request eventually auto-**close** (never auto-approve), or wait indefinitely? | Blocks **S3/S5 only**. |
| **H6 — ESC-1** | Largely resolved: #1539 is **open** again, `priority:critical`, `needs-ai`, milestone v0.7.0. What remains is confirmation that **S2 is the fix that closes it**, so the live half is not split across two issues and missed a second time. | One comment on #1539. |
| **H7** | **Does the 2026-09-15T06:47Z ruling on #1540 clear ESC-6?** I read it as **no**: it says the 2026-09-10 requirements ruling is complete and the design chain should be kicked off. It predates none of ESC-2…ESC-6 and mentions neither. A product-boundary checkpoint asks for explicit clearance; silence is not clearance and I will not treat it as such. If the human intends it as blanket clearance, they need only say so — but H1's four items each need a yes. | An explicit statement either way. |

**One number the human should know is unverified:** `technical-design` reports 46 of 100 open issues authored by the human-proxy App, and four of five current candidates gated. I did **not** re-derive those counts (`query_issues.sh` exposes no author field and I did not hand-roll a `gh api` read). My ruling does not depend on them — it depends on the structural fact that every human-proxy filing is LLM-composed, which I did verify in `CLAUDE.md` and `create_issue.sh`. The counts size H1's burden, and H1 is the human's decision, so they should be re-derived before that decision rather than taken from a document.

### (c) THE DUAL-LENS ADVERSARIAL PANEL (#1540's own mandate)

#1540 requires the full chain `pm-agent → architect → technical-design → dual-lens adversarial panel`, re-confirmed by the human on 2026-09-15. The panel runs **after** `technical-design` revises for A12 and **before** `coder` builds. It is not satisfied by this amendment, by the ADR, or by ordinary review.

**Attack surfaces to hand the panel, so it does not start from scratch** (three from the original ADR, three from the technical design, four from me):
1. AD-2's marker enumeration — miss a site and a live path breaks; loosen it and the laundering path reopens.
2. AD-8's unresolved assessor-dispatch seam (S5, not S1/S2).
3. ESC-6 item 2 — the real-world failure is one overloaded CODEOWNER approving without reading.
4. The authorization-check cap's "carry on with a partial answer" branch (design §2.3 D5.1) — the only place a limit does not produce exit 2.
5. The marker table as a title-shape match against `printf` strings in a protected shell script.
6. The assumption that `requester_verdict` is the only composition anyone will use — enforced by a grep, and a grep is weaker than a type.
7. **AM-4's inverted default** — confirm that `None` really does mean "ignore milestone events" everywhere, including any consumer deployment's own callers of `probe.py`.
8. **AM-6** — look for any *other* place where a workflow's or bot's write is being read as a human's act. `label-swap.yml` was not the only candidate; it was the first one checked.
9. **AM-13's loud line** — a gate that holds everything and whispers is indistinguishable from an empty backlog. Attack the visibility, not just the logic.
10. **The cutover itself** — S2's merge is the moment the repo's autonomous work loop can stop dead. Ask what happens if the human is unavailable the week it merges.

---

## 4. What I decline to rule, and why

- **ESC-2, ESC-3, ESC-4, ESC-5, ESC-6** stay the human's exactly as the original ADR left them. Nothing in E-1 … E-4 gives me new grounds to absorb any of them, and three of them (ESC-2's auditability-versus-maintenance trade, ESC-4's contributor-relations call, ESC-5's spend ceiling) have no correct technical answer.
- **Whether the human-proxy session's filings are, as a matter of operational fact, personally reviewed by the human.** I did not rule this, and I did not need to: §AM-1 shows there is no admissible mechanism to express a favourable answer, so the answer changes nothing in the architecture. If the human wants that fact to matter, the change they are asking for is a change to AD-13, and it must be argued as such — on the record, with its laundering consequence stated — not smuggled in as an ergonomics flag.
- **The `/approve` workflow's own remediation beyond AM-6's four points** — whether `label-swap.yml` should post a different confirmation message in the S2 era, and whether `/approve` should refuse outright until S3 lands, is `technical-design`'s call within AM-6's constraint, and it is a protected-surface edit either way.

  > **[SELF-CONTRADICTION, FOUND BY `technical-design` §8/E-6 AND RULED IN `ADR-1540-AMENDMENT-2` AM-17 — 2026-09-15.** This bullet says the `label-swap.yml` edit "is a protected-surface edit either way"; §3(b) H1 item 4 above enumerates four protected surfaces and **omits `.github/workflows/**`**. Both sentences are in this document, and the one heading for the human was the wrong one. **This bullet is correct; item 4 was not.** The count for S1/S2 is **five**, and `technical-design` **ruled** the second question here (`/approve` is not made to refuse until S3) with reasons the architect has read and declined to overrule — see Amendment 2 AM-17 and §4.**]**
- **Whether #1539 or #1540 is the issue S2 closes** (H6) — issue hygiene and accountability for an open critical are the human's, as ESC-1 already said.

---

## Human Review Required

**RISK: HIGH.** This amendment changes the authorization semantics of shipped code (`probe.py`, inherited by every consumer deployment) and rules on the one escalation that decides whether this repo's autonomous work loop keeps running after S2 merges. The specific ways it can fail while looking correct: (i) AM-1 being quietly re-litigated later as "the queue is slow, let's just mark human-proxy filings trusted" — which is why AM-2 forecloses the flag form in the ADR text rather than in prose here; (ii) AM-4's inverted default being read as a back-compat nicety and restored to "accept any milestone" by a coder chasing green tests, which re-admits a human's benign `Backlog` triage as authorization to build; (iii) AM-6 being implemented as "the gate reads comments" without anchoring on the GitHub-reported comment author, which would make an issue's own body able to claim its approval; (iv) AM-13 being dropped as logging polish, after which a fully-gated queue is indistinguishable from an empty backlog for as long as nobody looks; (v) AM-9's sequencing being taken as permission for #1604 to proceed against the old contract without re-pointing Component H, producing two selection implementations — the exact defect (#1135) this whole design exists to avoid.

**CONFIDENCE: HIGH** on AF-5, FIND-1 and FIND-2, each re-derived from the working tree this session and each traceable to a specific line of shipped code. **HIGH** on AM-1's reasoning: the subset argument is a structural property, not a judgment call, and option B's disposal follows directly from AD-13's existing text. **HIGH** on AM-9/AM-10/AM-11, all three verified against the cited documents. **MEDIUM** on AM-8 (deferring R-3 to S3) — I deferred it partly because I could not verify from here how often bots toggle labels and milestones on issues in normal operation, and that unverified frequency is exactly what determines the availability cost; if the panel can measure it, the deferral should be revisited on evidence rather than on my judgment. **MEDIUM** on AM-3's bounded-backfill claim, which follows from the gate's query as designed but depends on FIND-3's authorship distribution, which I did not re-derive (§0 gap 1). **LOWER** on anything downstream of the uninspected live GitHub repository settings (ESC-2).

**BLAST RADIUS:** `scripts/automation/lib/probe.py`'s authorization path and therefore every consumer deployment that inherits it; the S1/S2 contract for `bin/hos-cron`'s work-selection path, `bootstrap/worker-cron-prompt.md` Step 2, and `.claude/agents/worker.md`; `.github/workflows/label-swap.yml`'s role in S3; and two other accepted designs — `ADR-1604` (AD-5, AD-9, Component H) and `ADR-1542` (G11). ~~Four protected surfaces, none pre-authorized here.~~ **[SUPERSEDED BY `ADR-1540-AMENDMENT-2` AM-17 — 2026-09-15: **five** protected surfaces — `scripts/framework/**`, `bin/**`, `bootstrap/**`, `.claude/agents/**`, `.github/workflows/**` — none pre-authorized here. `label-swap.yml` is edited in **S2**, not only "its role in S3": AM-6 point 3 is a shipping condition and the confirmation body at `:75` is the artefact that violates it.]**

**Change classification: STRUCTURAL.** It amends a shipped ADR's authorization semantics, amends two sibling ADRs, orphans named sign-offs, and rules on a blocking escalation whose consequence is a standing human obligation. It is held for the ESC-6 clearance (§3(b) H1) exactly as the original ADR was; **`coder` remains NOT cleared to build S1 or S2** until §3(a) A12, §3(b) H1 and H3, and §3(c) the dual-lens panel are all complete.

**This document expects to be attacked**, and §3(c) hands the panel ten specific places to start, four of which are attacks on this amendment rather than on the documents beneath it.
