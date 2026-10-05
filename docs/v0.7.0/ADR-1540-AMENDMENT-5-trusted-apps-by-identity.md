# ADR-1540 — AMENDMENT 5: the three HOS Apps are trusted requesters by identity; the machine-filing marker no longer decides eligibility (#1989)

**Status:** ACCEPTED — binding on `technical-design` and `coder` for #1989. This document **amends** `docs/v0.7.0/ADR-1540-request-intake-risk-agent.md` and `ADR-1540-AMENDMENT-1` … `ADR-1540-AMENDMENT-4`. It replaces none of them and **edits none of them** (AM-38, §4 below). Every decision in the base ADR (AD-1 … AD-15, ESC-1 … ESC-6) and every ruling in Amendments 1–4 (AM-1 … AM-38, AF-5 … AF-9) stands **except** where a ruling below names it. Where any earlier document in this chain differs from this one, **this document governs.**
**Date:** 2026-10-05
**Author:** architect
**Authorization (human, verified live):** ScottThurlow (the repository's individual human CODEOWNER), comment on #1989 at **2026-10-05T18:58:57Z**, verbatim:

> *"Human explicitly approves this. The fix to restrict work started has bugs and is too restrictive. All work got blocked. We will need to relax the restrictions now so work can resume. The "real" fix is planned for 0.7.2."*

I read this comment myself through `bootstrap/query_issues.sh --app worker --comments 1989`. Its GitHub-reported author is `ScottThurlow`, not a bot. It is the product/policy clearance this amendment needs under the CORE product-boundary checkpoint (§2), and it is the justification on record: **this is a deliberate relaxation, made now so work can resume. The stricter fix is planned for v0.7.2 and tracked under #1540.**
**Amends:** **AD-2** (its machine-filing-marker requirement, **superseded for the three HOS Apps**). **`ADR-1540-AMENDMENT-1` AM-1** (its first two sentences, *"AD-2 stands verbatim … The human-proxy App matches none, and none can be made for it"*, are **superseded**; its binding consequences are dispositioned in AM-42). **AM-7** (R-4 and its three revisit triggers become **moot**). **AM-10** (its *conclusion* still holds; its *security premise* is moot; see AM-42). Also, **cross-ADR, by disposition only and without editing them:** `ADR-1604` AD-9; `ADR-1644` VF-C5, AD-C16, ARCH-ESC-3 and its affected-sign-offs paragraph; `REQUIREMENTS-1644-AMENDMENT-1` VF-C5 and ESC-2; and the `TECHNICAL-DESIGN-1540` rows and tests that encode the marker requirement.
**Confirms without change:** AD-1 (its three categories and every binding rule), AD-1's *"no actor confers trust by a metadata act"*, AD-2's **corollary** (a trusted *request* is never a trusted *spec*), AD-4 / FR16 / FR28 (live CODEOWNER authorization of a gated issue, through `verify_codeowner_actor`), AD-6 (no bot approval satisfies the gate, **including the human-proxy App's**), AD-13 and AM-2 (no knob widens the trusted set), FR19 fail-closed behaviour, `bot-in-human-category`, and every Amendment 4 ruling.
**Inputs:** #1989 (body and the comment above, read live this session); `ADR-1540` and Amendments 1–4; `REQUIREMENTS-1540-request-intake-risk-agent.md` FR2/FR4; `REQUIREMENTS-1540-AMENDMENT-1-fr4-ruling.md`; `ADR-1604-worker-self-split-isolation.md` AD-9; `ADR-1644-stage-per-cycle.md`; `REQUIREMENTS-1644-AMENDMENT-1-stage-per-cycle.md`; `TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md`; `docs/LABELS.md`; and `scripts/framework/requester_trust.py`, `scripts/framework/select_work_candidates.py` and `tests/framework/test_requester_trust.py` in this worktree. See §0.
**Consumers:** `coder` (#1989), then `code-reviewer`, `security-reviewer` and the protected-surface CODEOWNERS gate. The change set touches `scripts/framework/**`.
**Scope note:** This document covers only what #1989 orders and what that change forces on other recorded decisions. It adds no mitigation that #1989 places out of scope. It edits one file, this one. **I have posted nothing to GitHub, filed no issue and changed no label.**

---

## 0. Verification: what I re-read before ruling

| Claim I relied on | Verified | Evidence |
|---|---|---|
| `requester_verdict` gates a trusted-App author with no title marker | **yes** | `scripts/framework/requester_trust.py:576-595`. When `reason == "trusted-app"` and `machine_filing_marker(title)` is `None`, it returns `RequesterVerdict(False, "trusted-app-no-machine-filing-marker", "trusted-app", None)` (`:586-591`) |
| `is_trusted_requester` already trusts the three Apps by login | **yes** | `:558-559`, `if low in trusted_set.apps: return True, "trusted-app"`. The marker test is applied only afterwards, in `requester_verdict` |
| The trusted-apps set is exactly worker, overseer and human-proxy, and never Copilot | **yes** | `load_trusted_apps` (`:284-297`) reads only `BOT_WORKER_USERNAME`, `BOT_OVERSEER_USERNAME` and `BOT_HUMAN_USERNAME`. Its docstring excludes `COPILOT_BOT_LOGIN` and the composite `BOT_ACCOUNTS` |
| `bot-in-human-category` is evaluated **before** the App test | **yes** | `:548-552`. A bot login in the CODEOWNER, roster or tier set is untrusted before the App branch is reached. This change does not touch it |
| `_REASON_TOKENS` is a closed set, and a test enforces **exact** equality with what the code produces | **yes** | `requester_trust.py:183-193`. `tests/framework/test_requester_trust.py:692-742`, `test_reason_tokens_conform_to_the_closed_vocabulary`, whose docstring says it *"also catches an entry in `_REASON_TOKENS` that no code path actually produces (exact-set equality, not mere subset containment)"* |
| Nothing outside the module and its test consumes `trusted-app-no-machine-filing-marker` | **yes** | a search of `scripts/`, `bin/`, `bootstrap/`, `tests/`, `.claude/` and `audit/` finds it only in `requester_trust.py` and `test_requester_trust.py`. The selector's gated-reason counter records `no-codeowner-actor` (`select_work_candidates.py:637`), not the requester reason. S6 (the audit consumer TD §1.2 names) is unbuilt |
| AD-2 is the source of the marker requirement | **yes** | `ADR-1540-request-intake-risk-agent.md:156`: *"**Binding:** category (b) trust applies only to bot-authored issues that **also** match an enumerated machine-filing marker … A bot-authored issue matching no marker is **gated like any other untrusted request**."* |
| The requirements never asked for the marker | **yes** | `REQUIREMENTS-1540-request-intake-risk-agent.md:271-275`, FR2(b): *"this deployment's own worker, overseer, and human-proxy App identities, and only those."* No marker. The marker narrowing is AD-2's, which is mine. **This amendment brings the implementation back to FR2(b) as written. No requirements change is needed.** |
| The two contradictory sentences exist where #1989 says | **yes** | see AM-40 |
| `needs-human` is excluded from selection | **yes** | `select_work_candidates.py:111`, `EXCLUDED_LABELS = ("needs-human",)`. This is relevant to the AD-2 injection-report path in §2 |
| `worker-app-derivation-required` (ADR-1644 AD-C16) is unbuilt | **yes** | the token is absent from all code. T3.8a has not been built |

**Verification gaps.** (1) I did not run the selector against live GitHub. #1989's acceptance criterion *"`eligible` greater than 0"* is the coder's to show. (2) I did not inspect live GitHub App settings. The claim that a `[bot]`-suffixed login can only belong to a GitHub App is GitHub's documented behaviour, not something I measured. Pinning numeric App ids, which would make that independent of login strings, is a #1540 follow-on (§2.3), not part of this change.

---

## 1. Rulings

### AM-39: An issue whose `user.login` is one of the three HOS App identities is a **trusted request**, category `trusted-app`. The machine-filing marker no longer decides eligibility. (**Supersedes AD-2's binding paragraph for the three Apps**, and AD-2's escape hatch with it.)

**The superseded text** is `ADR-1540-request-intake-risk-agent.md:156`, quoted in §0, together with the AD-2 title's *"narrowed to enumerated machine-filing paths"* and `:158`'s *"If `technical-design`'s enumeration shows the marker approach is fragile … it escalates back to me rather than widening the exemption."* **That paragraph's requirement is withdrawn for the worker, overseer and human-proxy Apps.** These are the only identities AD-1(b) ever admitted, so nothing of the requirement remains in force.

**Binding on `coder`:**

1. `requester_verdict`: when `is_trusted_requester` returns `"trusted-app"`, the verdict is **trusted**, with `category="trusted-app"`.
   - If `machine_filing_marker(title)` matches, the reason is `trusted-app:<marker_id>` and `marker_id` is set. This is unchanged.
   - If nothing matches, the reason is the plain token **`trusted-app`** and `marker_id` is `None`.
   - Only the audit reason depends on the title. Eligibility never does.
2. **Everything else is unchanged:**
   - the CODEOWNER, roster and roster-tier paths;
   - `bot-in-human-category` and its precedence;
   - `not-in-trusted-set` and `no-login`;
   - `verify_codeowner_actor` and the D5 authorization walk for every untrusted record;
   - every Step B fail-closed exit;
   - `load_trusted_apps`'s exact three keys.
3. **`copilot[bot]` and every other account outside the three Apps remain untrusted.** This includes any other `[bot]` login and any human who is not a CODEOWNER and not on the roster. Such an issue becomes selectable only through a verified individual human CODEOWNER's own `labeled` event for the dispatch label (AD-4, AR-7).
4. **No metadata act confers trust (AD-1, FR4 as amended).** This is unchanged and stays load-bearing. An App *applying* `needs-ai` to an issue it did not author does nothing for that issue's trust. Trust comes only from authorship of the issue (`issue.user`).
5. **Tests (#1989's acceptance list, made binding).** The coder must cover:
   - an App-authored issue with a marker: trusted, `trusted-app:<id>`;
   - an App-authored issue without a marker: trusted, `trusted-app`. Do this for **each** of the three Apps, because AM-1 point 3 forbids special-casing any of them;
   - an unknown bot, including a `copilot[bot]` author: gated;
   - a human who is not a CODEOWNER: gated;
   - a CODEOWNER: trusted;
   - a `labeled` event by a bot on an untrusted issue: still not authorizing.

   `test_trusted_app_without_marker_is_untrusted` encodes the superseded rule. **Invert it and rename it. Do not delete it.** Its absence would read as an omission.
6. **No time bound and no kill switch in code.** This follows #1989's body. The CODEOWNER's comment says this is a relaxation *now* and that the "real" fix is planned for v0.7.2. That is a plan for a **future decision under #1540**, which will supersede this amendment by a later amendment. It is not a timer, flag or environment variable here. Any of those would be a trust-widening knob, and AD-13 forbids that in either direction of toggling.

**Why this does not breach AD-13 or AM-2.** AD-13 forbids a *knob*, meaning an environment variable, label, issue content, config file or flag, from widening the trusted set. This change is a reviewed edit to the protected trust primitive. It is authorized by the human CODEOWNER on the record and goes through the protected-surface human gate. That is exactly the channel AD-13 leaves as the only way to change the set. AM-2's ban on creation-time assertions also holds: trust still attaches to the GitHub-reported `user.login`, which the author cannot set in content.

### AM-40: The contradiction between the base ADR's AD-6 and Amendment 1's AM-1 is resolved. **AD-6's wording governs.** The human-proxy App is a trusted *requester* and is not an *approver*.

The two sentences, verified:

- `ADR-1540-request-intake-risk-agent.md:268` (AD-6): *"**A bot approval never satisfies the gate — including the human-proxy App.** `scottthurlow-claude[bot]` is a trusted *requester* under AD-1(b) and is explicitly **not** a valid *approver*."*
- `ADR-1540-AMENDMENT-1-escalation-rulings.md:57` (AM-1): *"**AD-2 stands verbatim.** A bot-authored issue is trusted only if it also matches an enumerated machine-filing marker. The human-proxy App matches none, and none can be made for it."* (The same claim appears in the AD-2 banner at base ADR `:149-152`.)

**How they conflicted.** Read together under AD-2, `:268`'s "trusted requester" meant only *"a member of category (b), subject to AD-2"*. AM-1 (`:57`) then made that membership empty for the human-proxy App. So the human-proxy was nominally a trusted requester while in practice none of its requests could ever be trusted. The repository has been operating on the second reading, and #1989 measures the result: 87 of 87 candidates gated.

**Ruling.** `:268` governs **in its plain reading**. An issue authored by the human-proxy App is a trusted request, as for the worker and overseer Apps (AM-39). AM-1's sentence at `:57` and the AD-2 banner at `:149-152` are **superseded**. The second half of `:268` **stands unchanged and is now the more important half**: the human-proxy App is **never an approver**. A label it applies to someone else's issue authorizes nothing (AD-6, AM-1 binding consequence 1). Its approvals do not count toward the human-approval gate (`BOT_ACCOUNTS`). The requester/approver asymmetry `:268` describes is exactly the asymmetry that now holds.

### AM-41: Reason-token vocabulary. **`trusted-app-no-machine-filing-marker` is REMOVED from `_REASON_TOKENS` and RETIRED. `trusted-app` is now a token `requester_verdict` produces directly.**

**Decision:** remove it from the closed set in the same change that stops emitting it. Do not keep it for back-compatibility. The reasons:

1. **The set's definition is "tokens the code produces," and a test enforces that.** `test_reason_tokens_conform_to_the_closed_vocabulary` asserts **exact-set equality** precisely so that a token no code path produces gets caught. Keeping the dead token would mean either a red binding test or weakening it to a subset check. Weakening it would delete the guard against exactly this kind of drift. That is the wrong trade.
2. **There is no consumer to stay compatible with.** The token is referenced only in the module and its test (§0). The selector's gated-reason report uses `no-codeowner-actor`. No `audit/` record contains the token. S6, the named downstream parser, is unbuilt.
3. **History is protected in this document, not in a live constant.** Records written before this amendment, such as stderr logs and any audit an operator kept, may still carry the token. **Binding on whoever builds S6 or any other reader of historical gate output:** treat `trusted-app-no-machine-filing-marker` as a **retired** token meaning *"App-authored, no marker, gated under the pre-AMENDMENT-5 rule."* It is not an unknown token and not a parse error. I do **not** order a `_RETIRED_REASON_TOKENS` constant now. With no consumer it would be speculative structure. S6 adds one if it needs one, citing this paragraph.

**`trusted-app` is unchanged as a token.** It was already in `_REASON_TOKENS`, emitted by `is_trusted_requester`. It now also appears as a final `requester_verdict` reason. The test's case for `title: "hello"` under an App author must now yield `trusted-app`. The set equality then holds with one member fewer: `codeowner`, `roster`, `trusted-app`, `not-in-trusted-set`, `no-login`, `bot-in-human-category`, plus the parameterised prefixes `roster-tier:` and `trusted-app:`.

### AM-42: `MACHINE_FILING_MARKERS` is **retained, demoted to audit enrichment**. AM-7, R-4 and AM-1's binding consequences are dispositioned.

| Item | Disposition | Reason |
|---|---|---|
| `MACHINE_FILING_MARKERS` table and `machine_filing_marker()` | **KEPT, unchanged in content** | #1989 orders it kept. A matched marker tells an auditor *which deterministic site* filed an issue, and that remains useful |
| The table's code comment (`requester_trust.py:126-128`: *"Closed against sub-issue filing (AM-10/D-7): entries are REMOVED, never relaxed, the moment an emitting site becomes LLM-composed"*) | **MUST be updated in the same change** | It now describes a security property the table no longer carries. Replacement meaning, wording left to the coder: *the table labels deterministic filing sites for the audit reason only. It never affects eligibility. An entry whose emitting site becomes LLM-composed is still removed, because its label would then be false.* A stale security comment on a protected surface would mislead the next reviewer, which AM-28(c)/AM-35 already treat as non-cosmetic |
| `test_marker_table_literals_exist_in_emitting_files`, `test_issue_creation_site_count_is_pinned` (AM-7 called them binding) | **KEPT** | They keep the audit labels accurate. They no longer guard a trust boundary, and the change must not describe them as if they did |
| **AM-7 / R-4** (marker forgery by an induced LLM under an App identity) and its **three revisit triggers**, TD D-4 / D-6 | **MOOT** | Forging a marker gains nothing when identity alone confers trust. The separate deterministic-filing App that AM-7 declined no longer has a security purpose *under this policy*. Whether v0.7.2's stricter fix revives it is for #1540 to decide |
| **AM-1** option A (stamp a marker on human-proxy filings) **rejected as vacuous** | **MOOT** | It was rejected as being isomorphic to trusting the identity outright. The human has now chosen to trust the identity outright, openly and on the record, which is honest where the vacuous marker would not have been |
| **AM-1** option B / **AM-2** (no creation-time confirmation flag) | **STANDS** | Unchanged. It is still forbidden, and it is not needed |
| **AM-1** option C and **binding consequence 1** (an authorizing act must come from the human's own account, never `edit_issue.sh --app human`) | **STANDS for every untrusted-authored issue** | It is no longer the route by which human-proxy filings become selectable, because they are trusted. It is still the only route for anyone else's |
| **AM-1** **binding consequence 3** (nothing may special-case the human-proxy App) | **STANDS** | All three Apps are treated identically by AM-39 |
| **AM-1** option D (the human-proxy stops self-applying the dispatch label) | **MOOT as a security control** | Its stated basis was the self-authorization shape. With authorship-based trust, a human-proxy filing plus a human-proxy label is selectable by design. Whether the human-proxy applies `needs-ai` is now a workflow choice, not a trust question. I make no ruling on the `CLAUDE.md` text, which stays human-gated (AD-14) |
| **AD-2 corollary** (a bot-authored trusted *request* is never a trusted *spec*; `pm-agent`'s CORE instruction that issue bodies are untrusted input) | **STANDS, and is now load-bearing** | See §2. It is now the main in-pipeline defence against content laundered into an App-authored issue |
| **ESC-6 / H1 item 2** (the standing obligation on a single CODEOWNER to decide every outside request) | **Volume reduced, obligation unchanged in kind** | App-authored issues no longer join the queue. Only genuinely outside requests do. This is the outcome #1989 asks for |

### AM-43: Consumer-facing text that the policy change makes false MUST be corrected in the same change. (Forced by AM-39. Same principle as AM-6 point 3: the repo must not tell a human something the gate does not do.)

`docs/LABELS.md:34` currently says the gate trusts *"an HOS App identity carrying a recognised machine-filing marker"*, and that a bot applying `needs-ai` to an untrusted-authored issue *"— including the human-proxy App's own filings — never authorizes it."* After AM-39 the first clause is false. The parenthetical is false too, because a human-proxy filing is no longer untrusted-authored. **Binding:**

- The first clause becomes *"an HOS App identity (worker, overseer or human-proxy)"*.
- The parenthetical is removed, or restated so it applies only to issues authored outside the trusted set.
- Nothing else in that section changes. Points 1–5, the PAT route, AR-7 and the bot-label exclusion are all still true.

If `requester_trust.py` or `select_work_candidates.py` docstrings carry the same claim, they get the same correction. The coder must check for this, not assume it.

### AM-44: Knock-on dispositions for every recorded decision that reasoned from the marker requirement

I found these with `grep -rn "trusted-app-no-machine-filing-marker\|MACHINE_FILING_MARKERS" docs/`, plus the decisions those hits cite. **None of them is edited by this amendment** (§4). Each is dispositioned here, and whoever next amends that document must carry the disposition in, as AM-9 point 4 required for ADR-1604.

| Document / decision | Disposition | What changes, and the honest security consequence |
|---|---|---|
| **`ADR-1540-AMENDMENT-1` AM-10** (`:178-184`): sub-issue filing MUST NOT enter `MACHINE_FILING_MARKERS`; sub-issue authorization is live derivation from the parent | **Conclusion STILL HOLDS. Security premise MOOT. The derivation mechanism is MADE MOOT for App-authored sub-issues** | Sub-issue filing still must not get a marker, now only because the marker would mislabel an LLM-composed filing in the audit reason. **The derivation requirement no longer has work to do for a sub-issue filed by any of the three Apps, because authorship trusts it.** It still binds for a sub-issue authored by anyone else, which is never trusted by authorship. **Security consequence, stated plainly:** a worker-filed sub-issue whose title and body an LLM composed from a parent's content, where that content may originate from an untrusted outside issue, **is now trusted by authorship.** That is exactly the laundering shape AM-10 was written to close, and it is now open by decision |
| **`ADR-1604` AD-9** (`:174-184`), *"Sub-issues inherit authorization from the parent explicitly; they never acquire it by authorship"*, and point 2's in-place AM-10 supersession note at `:180` | **Point 1's "never acquire it by authorship" and point 3 are SUPERSEDED for sub-issues authored by the three Apps. They STILL HOLD for any other author.** Point 1's derivation link requirement (that the sub-issue *carries* a machine-readable parent link) **STILL HOLDS** as structure | The link is still how the splitter, the reconcile sweep (AD-10) and tracking-parent auto-close find children. It simply stops being the *authorization* basis. **Security consequence:** the "machine creating its own authorized work" shape AD-9 names is now permitted for the worker App, on the CODEOWNER's ruling |
| **`ADR-1644` VF-C5** (`:65-70`), a verification finding that `requester_verdict` returns `trusted-app-no-machine-filing-marker` for any App author without a marker | **SUPERSEDED as a description of the code** | It was true when written and is false after #1989 lands. It is historical. No action is needed beyond this record |
| **`ADR-1644` AD-C16** (`:711-776`), the one new S2 admission path for worker-authored children of a currently authorized parent: new token `worker-app-derivation-required`, the D5 derivation check, the parent-revocation property, the AD-C16.5 consumer sentence, and the T3.8a review requirement | **MADE MOOT in full. T3.8a has no trust-layer work left. The token `worker-app-derivation-required` MUST NOT be introduced** | Every worker-authored issue, child or not, is now trusted before D5 is reached, so the derivation path would never fire. **Three consequences must be recorded honestly:** (i) **the parent-revocation property of AD-C16.4 is lost.** A CODEOWNER can no longer revoke every worker-filed child by removing the parent's dispatch label. Each child must be stopped individually, by removing its `needs-ai` or adding `needs-human`; (ii) **AD-C16.5's sentence** (*"applying the label also starts autonomous work on any sub-issues the worker files under that issue, for as long as the issue stays authorized"*) **MUST NOT be written.** It would understate the policy, since children are selectable whether or not the parent stays authorized; (iii) AD-C16's **splitter bounds still hold**, because they constrain *creation*, not trust: `max_children`, depth one, priority ≤ parent, milestone inherited, and AD-C12's floor. They are now the main bounds on amplification. The **`stage:tracking`** emission exclusion of the parent (AD-C16.4, AD-C4) also still holds |
| **`ADR-1644` ARCH-ESC-3** (`:956-961`, `:1068-1070`): *"is ESC-2's worker trust limited to derivable children … or should worker authorship alone suffice?"*, with the stricter reading bound meanwhile | **ANSWERED by the human in #1989, in the permissive direction, and wider than the question asked.** Authorship alone suffices for the worker, overseer **and human-proxy** Apps. The stricter reading bound at `:754-757` (*"worker-filed issues that are not decomposition children … anything filed by the human-proxy App"* stay gated) is **SUPERSEDED**. Its third bullet (*a child authored by anyone else needs a CODEOWNER act every time*) **STILL HOLDS** for any author outside the three Apps | ARCH-ESC-3 should be marked answered by #1989 / AMENDMENT-5 in ADR-1644's next amendment. No separate human question remains open on it |
| **`ADR-1644` affected-sign-offs** (`:1027-1035`): *"These stand: … The overseer and human-proxy App paths, `MACHINE_FILING_MARKERS` … are all unchanged"*, and the flag on S2 tests encoding "every worker-App issue without a marker is gated" | **SUPERSEDED.** Those paths are changed by this amendment | The S2 tests that encode marker-required gating are flagged for re-review under §3 below, which replaces that paragraph's scope for this purpose |
| **`REQUIREMENTS-1644-AMENDMENT-1` VF-C5** (`:100-108`): *"child issues the worker's planner writes would NOT be trusted … Loosening the gate to let children through would re-open the laundering path #1539/#1540 closed"* | **SUPERSEDED as a description of the gate. Its laundering observation is ACCURATE and is accepted as a residual** (§2) | The finding was correct. The human has decided to accept the consequence it names |
| **`REQUIREMENTS-1644-AMENDMENT-1` ESC-2** (`:576-588`), options (a)/(b)/(c) for making planner children selectable | **MOOT for children authored by the three Apps.** No option is needed, because they are trusted by authorship. **PM's recommendation (c)** (stage-per-cycle on one issue by default, children only for genuine multi-deliverable splits) **is unaffected as a workflow design.** It no longer has a trust rationale | The human's 2026-09-30 ESC-2 ruling (*worker-created child trusted, unknown/external actor untrusted*) is consistent with, and contained in, #1989's policy |
| **`TECHNICAL-DESIGN-1540`**: §1.2 token list (`:594`), the D3/D4 verdict step (`:750`), the Step F sample line (`:1386`), the #1539 trace row (`:1536`), row **F18** (`:1765`), and the test `test_trusted_app_without_marker_is_untrusted` (`:2229`) | **SUPERSEDED for the trusted-App branch only.** Under AM-38 the document is not edited. `coder` implements AM-39 and AM-41, not these rows | F18 becomes *"Author is a trusted app, title has no marker → **trusted**, `trusted-app`."* The `:1536` row for #1539, authored by the human-proxy App, would now read *trusted*. The row's second limb (a bot actor never authorizes) is unchanged |
| **`TECHNICAL-DESIGN-1540` D-7** (`:884`) and the table row at `:270` | **Same as AM-10:** the conclusion holds and the premise is moot | — |
| **`REQUIREMENTS-1540` FR2(b)** (`:273-275`) | **UNCHANGED, and now implemented as written** (§0) | — |
| **`REQUIREMENTS-1540` FR4 *Verify*** (`:319`): a worker-authored `[BLOCKED]`/self-review issue *"under an enumerated machine-filing marker is trusted by authorship"* | **STILL HOLDS.** It remains true, and is now one case of a wider rule rather than the whole of it | — |
| **`REQUIREMENTS-1540-AMENDMENT-1`** `:133`: *"AD-2's marker narrowing is unaffected"* | **MOOT.** It is a historical statement about a narrowing this amendment removes | — |

---

## 2. Security consequences, accepted by the human on the record. No new mitigations are added here.

**CORE product-boundary checkpoint.** This decision changes user-visible behaviour (which issues the worker builds without a human act) and the system's trust boundary. Both are the human's to clear, and **both were cleared** by the CODEOWNER's 2026-10-05T18:58:57Z comment on #1989, quoted in the header. The technical call is mine and binds from that clearance. The protected-surface CODEOWNERS approval on the PR that carries the change remains a separate human gate, and this amendment does not lower it.

### 2.1 What is re-opened, by decision

AD-2 existed to close one laundering route: *content that induces an HOS App's LLM session to file an issue produces a trusted-authored request.* **That route is open again for all three Apps.** Concretely:

- Text in an outside issue, PR, comment or document that the worker, overseer or human-proxy session reads can induce that session to file a new issue.
- That issue is trusted by authorship.
- If it also carries the dispatch label and the target milestone, it is selectable with **no human act**. Any App can apply both.
- The same is true for a worker-filed sub-issue whose body an LLM composed from an untrusted parent (AM-44 rows 1–2).
- For worker-filed children, the AD-C16 parent-revocation lever is lost.

**The human CODEOWNER accepted this trade-off in #1989.** The stated reason is that the strict gate blocked all work: 87 of 87 candidates gated, worker idle since about 2026-10-03. This is a deliberate relaxation pending the stricter v0.7.2 fix.

### 2.2 What still stands between such an issue and a merge (existing controls only, listed so no one has to rediscover them)

- Every untrusted-authored issue is still gated.
- No bot label act authorizes anything (AD-1, AD-6, AR-7).
- An injection attempt the worker *recognises* is filed with `needs-human` and is excluded from selection (`EXCLUDED_LABELS`).
- The AD-2 corollary: issue bodies stay untrusted input to `pm-agent` and the design chain.
- Every resulting PR still passes risk scoring, the reviewer set, the overseer's verdict, cross-vendor second review at its tiers, and the protected-surface CODEOWNERS gate. None of these is changed here.

**These are not new mitigations, and none of them is claimed to close the route.** They are what was already in the tree.

### 2.3 Follow-ons. Out of scope for #1989 and tracked under #1540 (stricter fix planned for v0.7.2)

These are listed, not designed. #1989 places them out of scope, and I add none of them to this change.

- **Pinned numeric GitHub App ids** in place of login strings for the trusted-apps set.
- **An intake safety review** of App-authored filings: the shape and timing are #1540's to decide.
- **Revisiting the separate deterministic-filing App** that AM-7 declined, if v0.7.2 needs an unforgeable distinction between deterministic and LLM-composed filings.
- **Restoring a parent-revocation lever for decomposition children**, if v0.7.2 re-introduces derivation-based authorization.

---

## 3. Startup-gap recovery and affected sign-offs

**Should this have been settled in the initial architecture review? Yes, and the gap is mine.** FR2(b) asked for the three App identities, *"and only those"*. AD-2 narrowed that with a marker requirement, and Amendment 1 hardened it into "none can be made for the human-proxy App". **Nobody measured what share of the selectable backlog the narrowing would hold.** #1989 measured it in production: all of it. This is a startup-artifact gap: a binding narrowing of a requirement, made without measuring its availability cost. **Recommendation, not filed** (I am instructed not to file): annotate #1989, or open a `startup-artifact-gap` issue, citing this paragraph.

**Affected sign-offs:**

| Prior sign-off | Disposition |
|---|---|
| S1/S2 code approvals for `requester_verdict`'s trusted-App branch, and the tests that encode marker-required gating (`test_trusted_app_without_marker_is_untrusted`, the `_REASON_TOKENS` conformance test's App/"hello" case) | **ORPHANED for that branch. Re-review is required in #1989's PR.** The tests must be changed as AM-39 point 5 and AM-41 state, and reviewed as a trust-boundary change by `security-reviewer`, not as a test fix |
| S1/S2 approvals for every other path (CODEOWNER, roster, tier, `bot-in-human-category`, Step B exits, D5 walk, `verify_codeowner_actor`, cost ceiling, ordering) | **STAND.** Untouched |
| `ADR-1644` AD-C16 / T3.8a design sign-offs | **ORPHANED (moot). No code was built** (§0), so no shipped behaviour is left unaudited. Any T3.8a work in flight must stop at the trust layer and re-read AM-44 |
| `ADR-1604` AD-9 design sign-offs | **STAND for structure** (the derivation link, record-first filing, the reconcile). **Orphaned only for the authorization-basis claim**, per AM-44 row 2 |
| `TECHNICAL-DESIGN-1540` row F18 and the `:1536` trace | **Superseded for the trusted-App branch** (AM-44). No sign-off depends on them beyond the orphaned code above |

---

## 4. Supersession convention. Why no earlier document is edited

Amendments 1–3 placed in-place pointer banners in earlier documents. **Amendment 4 ended that practice:** AM-38 binds that *"no ACCEPTED document in this chain … may be edited after acceptance except to correct a factual error in it … Amendments supersede; they do not overwrite,"* and Amendment 4 itself edited no other file. I follow AM-38. **`ADR-1540`, Amendments 1–4, `ADR-1604`, `ADR-1644`, `REQUIREMENTS-1644-AMENDMENT-1` and `TECHNICAL-DESIGN-1540` are not touched.** The cost is that a reader of the base ADR does not see a pointer to this document. That cost is known and was accepted at AM-38. AM-44's table is the index a reader needs. For `ADR-1604` and `ADR-1644`, which are separate chains, the disposition must be carried into each one's next amendment.

---

## 5. What this amendment is NOT

- **NOT a widening beyond the three Apps.** `load_trusted_apps`'s three keys are unchanged. Copilot, other bots and non-roster humans are untrusted.
- **NOT a change to authorization.** An untrusted issue still needs a verified individual human CODEOWNER's own `labeled` event. No App, workflow or milestone act authorizes.
- **NOT a change to the approver set.** The human-proxy App is still never an approver (AD-6 `:268`, `BOT_ACCOUNTS`).
- **NOT a deletion of the marker table.** It stays, for the audit reason.
- **NOT a time-boxed or switchable change.** It holds until a later amendment under #1540 supersedes it.
- **NOT a design for v0.7.2's stricter fix.** §2.3 lists follow-ons only.

---

## Human Review Required

**RISK: HIGH.** This amendment deliberately removes the control that kept LLM-composed, App-authored issues from being self-selectable. It re-opens the AD-2 laundering route and the AM-10 sub-issue route for all three HOS Apps, and drops AD-C16's parent-revocation lever. The human CODEOWNER cleared that trade on the record (#1989, 2026-10-05T18:58:57Z) to restore a fully blocked pipeline. The ways this can go wrong while looking correct are:

- a coder widening AM-39 from "the three App logins" to "any `Bot`-type author", which would admit `copilot[bot]` and every third-party App;
- the stale `MACHINE_FILING_MARKERS` comment or `docs/LABELS.md:34` being left in place, so the repo describes a control that no longer exists;
- a test being deleted rather than inverted, so the trust-boundary change looks like a test fix in review.

**CONFIDENCE: HIGH.** Every code claim in §0 was read in this worktree. The human authorization was read live from GitHub. The two contradictory sentences are quoted from the documents. The knock-on set was found by grep, then I read each cited decision in its document. It is complete for `docs/`. Claims about other surfaces (agent definitions, prompts) are limited to the `docs/LABELS.md` and code-docstring checks that AM-43 orders.

**BLAST RADIUS:** `scripts/framework/requester_trust.py` (`requester_verdict`, `_REASON_TOKENS`, the marker table's comment), `tests/framework/test_requester_trust.py`, and `docs/LABELS.md:34`. In behaviour, it changes which issues every consumer deployment's worker selects without a human act. By disposition only, it also affects `ADR-1604` AD-9, `ADR-1644` AD-C16/ARCH-ESC-3/T3.8a, and `REQUIREMENTS-1644-AMENDMENT-1` VF-C5/ESC-2.

**Change classification: STRUCTURAL (trust boundary).** The PR needs `security-reviewer`, cross-vendor second review at its risk tier, and the CODEOWNERS human approval on `scripts/framework/**`.

**Provenance:** `architect`, interactive worker session in worktree `Worker-1989` (branch `interactive-1989-trust-apps-by-identity`), 2026-10-05, ruling #1989 under the CODEOWNER's on-record approval.
