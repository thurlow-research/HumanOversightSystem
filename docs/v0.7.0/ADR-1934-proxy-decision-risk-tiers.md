# ADR-1934: Risk-tiered escalations. A per-item tier recorded by the filing script, fail-closed and monotone, a script-authored recommendation the human stamps from their own account, a strict parity test for the human-proxy block, and Part B held behind ESC-0/ESC-1

**Status:** ACCEPTED FOR DESIGN (Part A). AD-1 to AD-9 bind `technical-design`. Items marked **PROVISIONAL (ESC-n)** are drafted on the pm-agent default and name what changes under the alternative. **Part B (REQ-13 to REQ-18) is HELD**: §4 records only its decision structure and the room Part A leaves for it. Nothing in this ADR designs a proxy decision.
**Date:** 2026-10-08
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #1934 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every slice except S5 lands on protected surface (`CLAUDE.md`, `templates/CLAUDE.human.md`, `.claude/agents/**`, `bootstrap/**`, `scripts/framework/**`, `docs/AGENT-IDENTITY.md`), so the human gate applies whatever the computed tier.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1934-proxy-decision-risk-tiers.md` (REQ-1 to REQ-18, ESC-0 to ESC-9, VF-1 to VF-8). Also `ADR-1644-stage-per-cycle.md` (provenance paragraph `:24-29`, AD-C10, ARCH-ESC-6 `:969`), `ADR-1958-manual-worker-mode.md` (AD-1 resolver, S6), `bootstrap/escalate_to_human.sh`, `bootstrap/lib/comment_format_check.sh`, `bootstrap/worker-cron-prompt.md:104`, `.claude/agents/worker.md:171-177` and `:499`, `scripts/framework/select_work_candidates.py`, `scripts/framework/require_human_approval.py`, `scripts/framework/protected_surfaces.txt`, `scripts/framework/framework_consumer_files.txt`, `bootstrap/hos_install.sh:2048-2080`, `docs/AGENT-IDENTITY.md` §7/§9.1, and live reads of #1906 and #1928.
**Consumers:** `technical-design` → `coder` → review chain. `security-reviewer` is mandatory on S2 and S3 (new marker grammars that downstream trust decisions will read).
**Explicitly does NOT re-litigate:** ADR-1644's rulings, AD-C10, or ARCH-ESC-6 (acts count only from the human's own account), `BOT_ACCOUNTS`, the #757 human-approval assertion, ADR-1958's R-1/R-2 and its resolver, #1906's exception-clause wording, or #1928's assignment mechanics. Where §5 asks whether to amend ADR-1644, it asks; it does not decide.

---

## 0. Verification findings (working tree at `909ae52bc`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED in substance, OVERSTATED in scope.** The exact CORE text, inside `HOS:CORE` (before `HOS:CORE:END`) in each file that has it, is:
  > `5. Escalation terminal points — PROJECT may not redirect a human escalation`
  > `     to an agent.`

  It appears in **19 of the 27 shipped agents** (`consumer_agents.txt`): a11y-reviewer:159, architect:86, code-reviewer:169, coder:96, infra-reviewer:145, ops-designer:88, ops-reviewer:169, overseer:855, pm-agent:99, privacy-reviewer:175, reliability-reviewer:140, security-reviewer:176, self-reviewer:129, system-test:98, technical-design:83, ui-reviewer:155, unit-test:107, ux-designer:106, worker:973. It is **absent** from eight shipped oversight-layer agents: `risk-assessor`, `dep-mapper`, `risk-historian`, `oversight-evaluator`, `oversight-orchestrator`, `spec-red-team`, `prompt-fidelity`, `post-change-sweep`. The requirements' "every shipped agent" is therefore wrong. The conclusion still holds, because the worker, overseer and every agent that files or arbitrates escalations carries it, and VF-1's own caveat is correct: the clause constrains **PROJECT**, so a HOS CORE change is not forbidden by its letter. It is the loosening the clause exists to keep under human control. (Routed as N-1; not a #1934 fix.)
- **VF-3 CONFIRMED.** `escalate_to_human.sh` is the only `needs-human` writer with a reason field. Its marker is `<!-- hos-escalation v=1 reason=<r> key=<k> -->`; its only machine reader outside the script is its own test. It never removes `needs-ai` (header, "Targets").
- **VF-4 CONFIRMED, three hunks.** After substituting `__CLONE_ROOT__`: (1) a line reflow on the identity sentence; (2) the template's auth step carries the `$TMPDIR`/`mktemp` warning and code block that `CLAUDE.md` lacks; (3) `CLAUDE.md` carries the "Never invoke `bin/hos-cron` yourself" paragraph that the template lacks. Only `tests/framework/test_require_human_approval.py` mentions the template, and it does not compare blocks. The installer *refreshes the block in place from the template* (`hos_install.sh:2076`), so hunk (3) is one HOS self-install away from silent deletion.
- **VF-5 CONFIRMED.** `select_work_candidates.py:111` excludes only on the presence of `needs-human`; a trusted author (every HOS App) is eligible with no check on who removed it. `escalate_to_human.sh` leaves `needs-ai` in place, so a proxy's removal of `needs-human` alone resumes a worker escalation today.
- **VF-6 CONFIRMED.** `worker.md:499` ("a qualifying human comment that post-dates your request") is prose with no stated author rule.

### 0.2 Architect findings

**AF-1: escalation tooling is HOS-only today.** Neither `framework_consumer_files.txt` nor `hos_install.sh` ships `escalate_to_human.sh`, `post_comment.sh`, `create_issue.sh` or `comment_format_check.sh`, yet shipped `worker.md` tells consumers to use them. Part A's new tooling follows the existing status (HOS-only) rather than widening the consumer surface inside this issue. ESC-9's "Part A ships to consumers" therefore ships **prose and the template**, not scripts (routed as N-2).

**AF-2: a tier error is asymmetric, so over-matching is the safe direction.** Raising a `clarifying` item to `hard-tradeoff` costs one stamp. Lowering a `hard-tradeoff` item is the failure #1934 exists to prevent. Every mechanical rule in AD-3 may therefore over-match freely; none may ever lower.

**AF-3: monotonicity can be computed without trusting authors.** Because the effective tier is the *maximum* over records, a marker forged or pasted by anyone can only raise a tier. The reader needs no author check to stay fail-closed. An author check is needed only for anything that *lowers* or *decides* (stamps, and Part B).

**AF-4: the stamp is only cheap if it binds to something machine-readable.** REQ-8's "binds to the most recent recommendation on that item" and "edited after the stamp is void" require the recommendation to carry an item id, its option letters and a content hash, and the reader to compare `updated_at` against the stamp's `created_at`. A model-composed markdown heading cannot carry that reliably; a script-appended marker can.

**AF-5: the human's PR approval is already an own-account act.** Every Part A slice is protected surface, so none can merge without the human's own-account approval. For Part A that approval is a stronger ESC-0 confirmation than an issue comment.

---

## 1. Organizing principle

**A tier is a recorded fact about an item, written by a script, readable without prose, and only ever raised by an agent. A decision is a human act from the human's own account. A recommendation is neither.** Part A builds the first and third and makes the second cheap. It moves no authority: under Part A the tier changes what the human *sees* (the friction they pay), never *who* may decide.

---

## 2. Decisions (Part A)

### AD-1: Tier vocabulary and fail-closed default. (BINDING; REQ-1, REQ-2.)

Two tokens: `clarifying`, `hard-tradeoff` (marker abbreviations `c`, `h`). REQ-1's two definitions are copied **verbatim** into the human-proxy block, `worker.md` and `architect.md` (S4), and a doc test anchors on them. The effective tier of an item is `hard-tradeoff` whenever: no valid record names it; the issue carries `needs-human` with no `hos-escalation` marker at all (every non-filing writer in VF-3, and every `create_issue.sh`/`edit_issue.sh` `needs-human` path); the marker is `v=1`; the marker is edited (`updated_at != created_at`), unparseable or names an unknown token; or any AD-3 rule fires. There is no third value and no "unknown".

### AD-2: The tier is recorded by `escalate_to_human.sh`, per item, in a v2 marker plus a script-authored visible table. Other writers are unchanged and mean `hard-tradeoff`. (BINDING on placement and fields; exact grammar is `technical-design`'s. REQ-4, REQ-5.)

- **Flags.** `--item <ID>=<clarifying|hard-tradeoff>`, repeatable; `<ID>` matches `^[A-Z][A-Z0-9-]{0,23}$` (e.g. `ESC-3`, `ARCH-ESC-1`). With no `--item`, the escalation is one implicit item `Q` at `hard-tradeoff`. A `--item` whose ID does not appear in the body is refused (exit 2). Omitting a tier value is refused, not defaulted, so a typo cannot be read as intent.
- **Marker v2.** `<!-- hos-escalation v=2 reason=<r> key=<k> tier=<c|h> items=<ID>:<c|h>[,<ID>:<c|h>…] -->`. `tier` is the maximum over items (REQ-4: the issue carries the highest). `key` additionally hashes the canonical items list, so a different tiering is a different escalation. Override reasons are **not** in the marker (length); they are in the audit event and the visible table.
- **Visible table.** The script appends, above the marker, a short script-authored table: item, recorded tier, and the override reason when the filer's tier was raised (REQ-3 AC). The body itself may not contain `hos-escalation`, `hos-recommendation` or `hos-proxy-decision` (extends the existing `body-carries-marker` refusal; the last two names are reserved now for S3 and Part B).
- **Audit.** `escalated-to-human` gains `tier`, `items[]` (`id`, `filed`, `recorded`, `reasons[]`) and `filer_app`.
- **Idempotency.** The existing exact-line own-marker match is kept. A retry of an in-flight v1 escalation after upgrade may post one v2 duplicate; that is accepted (`technical-design` may additionally match a v1 record for an identical body and reason when no `--item` is given, but must not weaken the match otherwise).
- **Other writers (REQ-5).** `create_issue.sh` and `edit_issue.sh` are **not** changed and are **not** routed through this script. Their `needs-human` means `hard-tradeoff` by AD-1. Any filer that wants an item read as `clarifying` must use `escalate_to_human.sh`. This keeps the merge-block, NG3b and overseer label paths untouched (VF-3), at the price that a `create_issue.sh --label needs-human` question can never be cheap. That price is intended.
- **Architect ESC items (REQ-4).** The architect does not file; it tiers. Every ADR's machine-readable escalation block carries `tier:` per item (this ADR's §7 is the first instance). The filing worker passes those tiers through as `--item` flags and may only raise them.

### AD-3: The REQ-3 never-clarifying list: four mechanical layers in the filing script, the rest stated in prose. (BINDING on layers and direction; term list content PROVISIONAL (ESC-4). REQ-3.)

Layers, evaluated per item; any hit records `hard-tradeoff` with the named reason:
1. **Reason allowlist (inverted).** `clarifying` is possible only when `--reason` is in a short committed allowlist (initially `awaiting-human-answer`, `confirm-reading`, `scoped-fix-authorization`). Any other reason forces every item hard (`forced:reason`). New trigger reasons (round cap, convergence failure, Condition-10, gate override, release, security, cross-role) are therefore hard without anyone enumerating them. Covers (b), (c), (d), (e), (f), (h) when the filer uses an honest reason.
2. **Target labels.** Any of a committed label list on the target issue (at minimum `hos-embargo` and every security-report label; `technical-design` derives the list from `docs/LABELS.md` and cites it) forces all items hard (`forced:label:<l>`). `release-request` is already refused outright. Covers (d) and part of (a).
3. **Protected-path tripwire.** An item block that mentions any path matching a `protected_surfaces.txt` entry forces it hard (`forced:path:<p>`). The script reads `protected_surfaces.txt` at runtime, so the list never forks. Covers (a).
4. **Term tripwire.** An item block containing any term from a committed data file (`bootstrap/lib/escalation_forced_hard.txt`, one case-insensitive term per line) forces it hard (`forced:term:<t>`). The list must cover every REQ-3 category (indicatively: resume, reset, round cap, budget, convergence, CODEOWNER, merge, approve, release, embargo, security, Condition-10, C14, false positive, override, cross-role, identity, `--app`, structural, product, policy, BOT_ACCOUNTS, tier, classify, who may, trusted, selectable, ARCH-ESC). Over-matching is accepted (AF-2).
5. **Monotonicity (REQ-6).** Before writing, the script reads every `hos-escalation` v2 marker already on the issue, **from any author** (AF-3), and records each item at `max(filed, prior)`. A lower filed tier is recorded hard with `raised:prior-record` and audited as `tier-downgrade-ignored`. Reusing an item ID for a new question therefore inherits its old tier; filers use a new ID (as ADR-1644 did with `ARCH-ESC-1R`).

An **item block** is the body text from a line whose first token is the item ID to the next such line; text outside every block applies to every item. `technical-design` fixes the exact delimiter and must provide a fixture table proving each of REQ-3 (a)–(j) that is mechanically reachable trips at least one layer, and that the three REQ-1 `clarifying` examples, phrased plainly, do not.

**Prose-only (stated in S4, not mechanised):** (g) structural spec change and the product checkpoint, (i) meta-authority, and (j) untrusted-author selectability, beyond what the term list happens to catch. Their enforcement is the filer's CORE obligation plus the visible table the human sees. This residual is stated, not hidden.

### AD-4: Recommendations are posted by a dedicated script that never touches labels, with a script-authored heading and marker. (BINDING; exact body grammar is `technical-design`'s. REQ-7, REQ-11.)

New `bootstrap/post_recommendation.sh --number <N> --item <ID> --body-file <path> --app <human|worker>`:
- The heading is **script-authored** from `--app`: `RECOMMENDATION (human-proxy, not a ruling)` or `RECOMMENDATION (worker, not a ruling)`. A body that starts with a heading, contains `(human,` as a heading, or carries any reserved marker is refused.
- The body must contain ≥2 lettered options (`(A)`, `(B)`, …), one `Recommended: <letter>` line naming an existing option, and a consequence line per option. Refused otherwise.
- **URL rule, mechanised (REQ-11).** A bare `#<digits>` reference outside a URL is refused, as is a bare 7–40 hex commit SHA outside a URL. The check is a new function in `bootstrap/lib/comment_format_check.sh`, also applied by `escalate_to_human.sh` when `--app human` (REQ-11's "escalation bodies filed by the proxy").
- Marker: `<!-- hos-recommendation v=1 item=<ID> options=<letters> rec=<letter> hash=<sha256-16 of the body as posted> -->`.
- The script **has no label, close or state code path**. "A recommendation never removes `needs-human`, applies `needs-ai` or closes anything" therefore holds by construction for this script; it does not, by itself, stop the proxy calling `edit_issue.sh` (VF-5; ARCH-ESC-2).

The worker may post a recommendation for its own escalation items, so worker-filed escalations are stampable (REQ-9).

### AD-5: Stamps are resolved by one read-only resolver; agents never interpret stamps from prose. (BINDING on placement and binding rules; grammar PROVISIONAL (ESC-7). REQ-8.)

New `scripts/automation/lib/stamp.py` with a CLI `scripts/automation/resolve_stamps.py --issue <N>`, built on `scripts/automation/lib/github.py`. For each item it emits JSON: `decision` (an option letter) or `status` ∈ {`no-recommendation`, `no-stamp`, `ambiguous`, `void-edited`, `not-own-account`}, with the URLs of the recommendation and stamp.
- **Own account:** author not in `BOT_ACCOUNTS` (case-insensitive, via `merge_config.py`'s loader), `user.type == "User"`, and the same verified-CODEOWNER test ADR-1644 AD-C10 uses (`technical-design` locates and reuses it; it may not write a second one).
- **Binding:** a stamp binds to the most recent `hos-recommendation` marker for that item created before it. If that recommendation's `updated_at` is later than the stamp's `created_at`, or its body no longer hashes to `hash=`, the result is `void-edited`.
- **Grammar (ESC-7 default):** trimmed, case-insensitive; a lone letter that is in `options`, or `agreed`/`yes` (resolving to `rec`); `ESC-n: B` forms for multi-item issues. A lone letter or `agreed` when more than one item has an open recommendation is `ambiguous`. Anything else is not a stamp.
- Under ESC-6's default, relayed `(human, …)` comments are bot-authored and so resolve as `not-own-account` with no extra code.

The worker reads decisions through this CLI on resuming a `needs-human` item and cites the stamp URL. **The stamp records the decision; it is not a resume.** Resume stays the human's existing label act (ARCH-ESC-3 asks whether to change that).

### AD-6: Parity: the `HOS:HUMAN-PROXY` block is byte-identical modulo `__CLONE_ROOT__`, with an empty exemption list; HOS-only text lives outside the markers. (BINDING; REQ-12, VF-4.)

- The template is the source (the installer copies from it). Resolve VF-4 as: hunk (1) reflow to match; hunk (2) the template's auth-step text is copied into `CLAUDE.md`; hunk (3) the "Never invoke `bin/hos-cron`" paragraph moves **out of the block** in `CLAUDE.md`, to immediately after `<!-- HOS:HUMAN-PROXY end -->`. That removes the silent-deletion risk and keeps consumers unchanged, because the paragraph names `hos-suspend`, which is not shipped (`framework_consumer_files.txt`). Whether consumers should receive an equivalent warning is routed as N-3, not decided here.
- New `tests/framework/test_human_proxy_block_parity.py`: extract both blocks between the markers, substitute `__CLONE_ROOT__` with the value in `CLAUDE.md`, assert byte equality, and assert each marker occurs exactly once per file. **No exemption list** is introduced; a future HOS-only line must go outside the markers. This is stricter than REQ-12 permits and satisfies it.

### AD-7: The URL rule (REQ-10) is a standing prose rule in the block, mechanised only where text passes through a script. (BINDING.)

The block gains: refer to every GitHub object by full URL, never a bare number. Chat cannot be checked by a script; recommendations and proxy-filed escalations are (AD-4). No new check is added to `create_issue.sh` or `post_comment.sh` (REQ-11 does not ask for it, and on GitHub `#N` already renders as a link).

### AD-8: Human-act regression test (acceptance #3). (BINDING.)

New `tests/framework/test_proxy_never_human.py`, parameterised over every **code-level** human-act check: `require_human_approval.py`, `merge_authority.py`'s approval finder, `select_work_candidates.py`'s CODEOWNER label-applier trust, the AD-5 resolver, and, if present when the slice is built, ADR-1644 AD-C10's question-close check and the NG3b release-signal check. Each must reject the human-proxy login and every `BOT_ACCOUNTS` login. The VF-5 path (trusted-author resume on any `needs-human` removal) is asserted as **`xfail(strict=True)`** referencing ARCH-ESC-2, so it is recorded, visible, and flips red the day it is fixed or worsens. Prose consumers (`worker.md:499`) gain an author rule in S4: "a qualifying human comment is one from an account not in `BOT_ACCOUNTS`".

### AD-9: The "How to authorize" block (REQ-9). (BINDING on content; wording `technical-design`'s.)

`worker.md:171-177` becomes: the item list with each item's recorded tier; "reply from your own GitHub account with the option letter (e.g. `B`) or `agreed`; a reply by the human-proxy or any bot does not count"; then the existing label steps (unchanged under ARCH-ESC-3's default). `worker-cron-prompt.md:104` gains the `--item` flags and the instruction to post a recommendation per hard item.

---

## 3. Slices (each ≤15 files including tests; each independently mergeable)

| # | Slice | Files | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|
| **S1** | Parity test and VF-4 reconciliation (AD-6). | `CLAUDE.md`, `templates/CLAUDE.human.md`, `tests/framework/test_human_proxy_block_parity.py` (new): 3 | **Yes** (`CLAUDE.md`, template) | — | human protected-surface approval only |
| **S2** | Tier recording (AD-1, AD-2, AD-3), reserved markers, proxy URL check in escalations. | `bootstrap/escalate_to_human.sh`, `bootstrap/lib/escalation_tier.sh` (new; item parsing, layers, monotone max), `bootstrap/lib/escalation_forced_hard.txt` (new), `bootstrap/lib/comment_format_check.sh`, `prompts/bootstrap/escalate_to_human.md`, `tests/automation/test_escalate_to_human.py`, `tests/automation/test_escalation_tier.py` (new), `SCRIPTS-INDEX.md` (regen): 8 | **Yes** (`bootstrap/**`) | — | ESC-4 confirmation of the list (extension is append-only, so a later ruling only adds terms) |
| **S3** | Recommendation script and stamp resolver (AD-4, AD-5). | `bootstrap/post_recommendation.sh` (new), `bootstrap/lib/comment_format_check.sh` (if not already in S2), `scripts/automation/lib/stamp.py` (new), `scripts/automation/resolve_stamps.py` (new), `tests/automation/test_post_recommendation.py` (new), `tests/automation/test_stamp.py` (new), `SCRIPTS-INDEX.md`: 7 | **Yes** (`bootstrap/**`) | S2 (reserved marker names, item-ID grammar) | ESC-7 (grammar), ESC-6 (whether relays resolve) |
| **S4** | Prose (AD-1 definitions, AD-3 prose residual, AD-7, AD-8 author rule, AD-9). Agent-definition edits are authored by the top-level session, not `coder` (CLAUDE.md, #1347). | `CLAUDE.md`, `templates/CLAUDE.human.md`, `.claude/agents/worker.md`, `.claude/agents/architect.md` (CORE: definitions; ESC items carry `tier:`), `bootstrap/worker-cron-prompt.md`, `docs/LABELS.md`, `docs/AGENT-IDENTITY.md` (§9.1: recommendation vs ruling vs act; VF-2's four kinds), `tests/framework/test_tier_prose_anchors.py` (new): 8 | **Yes** (all but LABELS and the test) | S1, S2, S3 | ESC-0 (by the PR approval itself, AF-5), ESC-2, ESC-6 wording |
| **S5** | Human-act regression test (AD-8). | `tests/framework/test_proxy_never_human.py` (new), at most 1 fixture: 1–2 | No | — (S3 adds its resolver case when it lands, or S3 extends this test) | none |

**Order:** S1 and S5 first and in parallel; S2; S3; S4 last (it names the scripts and edits the block under S1's test). **Codable before any human answer:** S1, S2 and S5, with S2's term list and allowlist carried as PROVISIONAL (ESC-4). S3 may be designed and built on the ESC-7 default, but its stamp grammar is finalised only after ESC-7. S4 may be drafted but its relay wording waits on ESC-6/ARCH-ESC-1. **No Part B slice exists.**

### Test obligations

- **S1:** the three VF-4 hunks are gone; byte equality after substitution; marker counts; a negative fixture (one-character drift) fails.
- **S2:** REQ-2 (no `--item`, unknown token, v1 marker, edited marker → hard); every AD-3 layer, one fixture each; the REQ-3 (a)–(j) table; the REQ-1 `clarifying` negatives; REQ-6 (prior hard + new clarifying → hard, `tier-downgrade-ignored` audited; a pasted marker by a non-bot can only raise); `--item` ID absent from body → exit 2; reserved-marker bodies refused; `--app human` bare `#N` refused, `--app worker` allowed; existing T-ESC cases pass unchanged.
- **S3:** heading forgery refused; <2 options or `Recommended` naming a missing letter refused; no label/close call is made (the `gh` stub records calls); resolver table: own-account `B` → B; bot `B` → `not-own-account`; letter not in options → `no-stamp`; recommendation edited after stamp → `void-edited`; two open items + lone `agreed` → `ambiguous`; stamp before any recommendation → `no-recommendation`.
- **S4:** REQ-1 definitions verbatim in the three files; URL rule present in both block files; `worker.md` "How to authorize" shows tier and stamp form; anchors avoid first-occurrence traps.
- **S5:** as AD-8, with VF-5 `xfail(strict=True)`.

---

## 4. Part B: HELD. Decision structure and the room Part A leaves

**Decision tree (human, own account; every node is `hard-tradeoff` under REQ-3(i)):**
`ESC-0` (is #1934 yours?) → `ESC-1` ∈ {A none, B clarifying-only, C relay-only}. **A** or **C** ⇒ Part B is dropped; REQ-18 collapses to "the human for both tiers". **B** ⇒ then ESC-3 (self-dealing), ESC-5 (label), ESC-8 (reversal cadence), ESC-9 (consumers), and a new ADR revision designs REQ-13 to REQ-17.

**Architect's condition on any ESC-1 = B grant (stated now so it is not a surprise later):** a proxy may never answer an item that carries `needs-human`. A granted Part B must take ESC-5's route, so a `clarifying` item is filed under a distinct pending-actor label and is never a human escalation. That is the only design that leaves every CORE terminal-point clause (VF-1) literally true. Any design in which the proxy settles a `needs-human` item is rejected as architecture, as ADR-1958 rejected flag-based authorization. Part B would also depend on ADR-1958 AD-1's resolver (`hos_clone_role == human-proxy`) for REQ-13's "interactive Human clone only".

**What Part A already provides, so Part B lands without rework:**
1. Per-item, machine-readable, monotone tiers with filer identity and override reasons in the audit event. That is REQ-14's "filed or tiered by self" and "tier changed by an agent" inputs.
2. The `hos-proxy-decision` marker name, reserved and refused in bodies (AD-2), so no comment written before Part B can impersonate a decision.
3. A single resolver (AD-5) whose `not-own-account` path already excludes bots. REQ-16's "never a human act" becomes an extension of S5's test, not a new mechanism.
4. Tier is orthogonal to label. Nothing in Part A keys label behaviour on tier, so ESC-5's distinct label can be added without unpicking anything.

**#1928 interaction.** #1928's title asks for an expected-next-actor *role*; its body and acceptance criteria assign only `HUMAN_REVIEWER` on any `needs-human`. Under Part A both tiers route to the human, so #1928's body is consistent with Part A and needs nothing from it. Under Part B, REQ-18 would require #1928 to read the AD-2 marker's tier; whether an App identity can be an assignee is still unverified and stays #1928's to check. **Sequencing:** #1928 is milestone v0.7.10 and will most likely edit `escalate_to_human.sh`. S2 should land first. No `blocked_by` edge is needed in either direction for Part A.

**#1906 interaction.** #1906 (v0.7.0) rewrites the exception clause in the same block S1 and S4 touch, and ADR-1958 S6 also edits it. **Sequencing:** S1 merges first. #1906, ADR-1958 S6 and #1934 S4 then merge serially in any order, each editing both files under S1's parity test. The orchestrating session should add a `blocked_by` edge from #1906's code slice to this issue's S1 PR only if #1906 is about to be coded first; otherwise ordering by merge is enough.

---

## 5. Reconciliation with ADR-1644 (relays vs acts)

ADR-1644 makes two distinct rules, and they must not be conflated:
- **Provenance paragraph (`:24-29`):** relayed rulings headed "(human, date)" by the proxy are accepted **for rulings**.
- **ARCH-ESC-6 (`:969`):** acts (resume, reset, question-close, CODEOWNER re-route) count **only** from the human's own account.

Part A is consistent with both: a recommendation is neither a ruling nor an act, and AD-5 only adds an own-account path. **pm-agent's ESC-6 would amend the provenance paragraph, not ARCH-ESC-6:** for `hard-tradeoff` items, a relay would no longer count as a ruling. Because AD-3 makes nearly every item `hard-tradeoff`, ESC-6's default in practice **ends relayed rulings**. Every ruling would then be one own-account comment (cheapened by AD-5's stamp). That is an amendment to ADR-1644 with a real product cost, and it is put to the human as **ARCH-ESC-1**. It is not decided here. If it is accepted, S4 adds a dated amendment note to `ADR-1644-stage-per-cycle.md` (one more file, still within S4's cap). Rulings already relayed stand: requirements §5 excludes retroactive tiering.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible (requirements-sanctioned):** escalation comments gain a tier table; recommendations take a fixed format; the "How to authorize" block changes. **Not sanctioned, routed:** ending relays (ARCH-ESC-1), refusing proxy label removal (ARCH-ESC-2), stamp-as-resume (ARCH-ESC-3).
- **Startup gap: no.** Tiering is a new requirement (#1934). The VF-4 drift is a defect in a protected doc, not an architecture decision that should have been settled earlier.
- **Affected sign-offs:** the #1644 T3.0a sign-off on `escalate_to_human.sh` is **re-reviewed within S2** (marker grammar, key and refusal set change; exit-code contract unchanged). ADR-1644's design stands unless ARCH-ESC-1 = (b), in which case only its provenance paragraph is amended. ADR-1958 stands; its S6 is sequenced under S1. No approved design is orphaned.

---

## 7. Open human escalations

pm-agent's ESC-0 to ESC-9 stand as filed; this ADR adds no default to them except where AD-n says PROVISIONAL. Architect items, every one `hard-tradeoff` under REQ-3(i):

- **ARCH-ESC-1 (amends ADR-1644 provenance; = pm ESC-6).** For `hard-tradeoff` items: **(a)** keep accepting relayed "(human, date)" rulings; **(b)** accept only your own-account stamp, which in practice ends relays, since almost everything is hard; **(c)** accept a relay only if you later stamp it. Consequence of (b): one own-account comment per ruling, no more relays from the proxy session. *No architect recommendation; this is policy.* Gates S3's resolver scope and S4's wording.
- **ARCH-ESC-2 (VF-5 mechanical gap).** Today the proxy removing `needs-human` resumes a worker escalation. **(a)** leave it, recorded as an S5 `xfail`, as requirements §5 implies; **(b)** later refuse `edit_issue.sh --app human --remove-label needs-human`; **(c)** later make the selector require the removal actor to be your own account for worker-filed escalations. (b) and (c) end proxy-relayed resumes and touch ARCH-ESC-6 territory, which §5 marks out of scope. *Default (a) for #1934.* Either (b) or (c) would be a new issue.
- **ARCH-ESC-3 (stamp vs resume).** **(a)** the stamp records the decision and you still flip labels to resume (default, no selector change); **(b)** an own-account stamp on every open item itself resumes the issue (one selector change on protected surface, a new issue). Consequence of (a): three actions per decision instead of one.

```yaml
adr: ADR-1934
issue: 1934
part_a_codable_now: [S1, S2, S5]
part_a_design_now_finalize_later: {S3: [ESC-7, ARCH-ESC-1], S4: [ESC-2, ESC-6, ARCH-ESC-1]}
part_b: held
part_b_held_on: [ESC-0, ESC-1]
escalations:
  - id: ARCH-ESC-1
    tier: hard-tradeoff
    amends: docs/v0.7.0/ADR-1644-stage-per-cycle.md#provenance
    equals_pm: ESC-6
    options: {a: keep-relays, b: own-account-only-for-hard, c: relay-then-stamp}
    recommended: null
    gates: [S3, S4]
  - id: ARCH-ESC-2
    tier: hard-tradeoff
    options: {a: record-xfail, b: refuse-proxy-label-removal, c: selector-checks-removal-actor}
    recommended: a
    gates: [S5]
  - id: ARCH-ESC-3
    tier: hard-tradeoff
    options: {a: stamp-plus-label-flip, b: stamp-resumes}
    recommended: a
    gates: [S4]
```

---

## 8. Notes routed (non-blocking)

- **N-1 → pm-agent.** VF-1's "every shipped agent" is 19 of 27; eight oversight-layer agents carry no PROJECT-may-never list at all. Whether they should is a separate question.
- **N-2 → pm-agent.** AF-1: shipped `worker.md` instructs consumers to use bootstrap scripts that are not shipped. Pre-existing; not widened here.
- **N-3 → pm-agent.** Consumers never received the #1616 "never invoke `bin/hos-cron`" warning; AD-6 keeps it HOS-only because it names unshipped `hos-suspend`.

## Escalation flag (CORE self-flag)

RISK: HIGH. Every Part A slice except S5 is protected surface; S2 changes the marker grammar of the only record-first escalation writer, and S3 introduces the first parser of human stamps, which Part B would later build authority on.
CONFIDENCE: HIGH on §0 (every citation was read in this session). MEDIUM on AD-3 layer 4's term list: it will over-match, which is safe (AF-2) but may make `clarifying` rare enough to be cosmetic. That is acceptable under ESC-1 = A and becomes a calibration question only if Part B is granted.
BLAST RADIUS: every worker escalation (S2); the human-proxy block in HOS and in every consumer install (S1, S4); no merge, selection or approval code path changes in Part A.
Change classification: STRUCTURAL (adds a filing obligation and a recommendation protocol; moves no authority).

## Human Review Required

ARCH-ESC-1 to ARCH-ESC-3, and pm-agent's ESC-0 to ESC-9. **Part B may not be designed until ESC-0 and ESC-1 are answered from your own GitHub account.** For Part A, your own-account approval of each protected-surface PR is the confirmation (AF-5).
