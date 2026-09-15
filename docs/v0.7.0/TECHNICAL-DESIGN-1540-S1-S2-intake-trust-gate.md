# TECHNICAL-DESIGN-1540 (S1 + S2) — Requester-trust primitive and the deterministic work-selection gate

**Status:** **REVISION 2 — architect-ruled contract, going to the dual-lens adversarial panel #1540 mandates.** No longer a draft for architect review: the architect has ruled on every escalation this document raised, in `ADR-1540-AMENDMENT-1-escalation-rulings.md` (ACCEPTED), and this revision applies those rulings. The panel is the next consumer.
**Scope:** ADR-1540 §3 slices **S1** (trust primitive) and **S2** (the gate) **only**. S3–S6 are out of scope and are not designed here.
**Date:** 2026-09-15 (revision 2; revision 1 same date)
**Author:** technical-design
**Binding inputs:** `docs/v0.7.0/ADR-1540-request-intake-risk-agent.md` (AD-1 … AD-15, §0, §3, ESC-1 … ESC-6); **`docs/v0.7.0/ADR-1540-AMENDMENT-1-escalation-rulings.md` (AM-1 … AM-13, AF-5, §2 affected-sign-offs, §3(a) A12, §3(c) panel surfaces) — binding, and it governs over the base ADR wherever it names a decision**; and `docs/v0.7.0/REQUIREMENTS-1540-request-intake-risk-agent.md` (FR1–FR27). Where this document is silent, the ADR-as-amended governs; where this document appears to contradict the ADR-as-amended, that is a defect in this document unless it is named in §8 Escalations.
**Consumers:** the dual-lens panel, then `coder`.

**S2 is the live-path fix for #1539**, an open `priority:critical` security issue. ADR §0/AF-1 established that #1539 was once closed by `abef062e`, which touched only `scripts/automation/lib/probe.py` — a module whose sole production caller is `multi_customer.py`, i.e. **not on this repo's live intake path**. This document does not repeat that. Every component below is specified against a call site that executes on every worker cron cycle.

**`coder` is NOT cleared to build S1 or S2.** This has not changed, and revision 2 does not soften it. What changed is *which* gates remain. E-1 — the blocking escalation revision 1 raised — is **ruled and closed** (AM-1/AM-2). Still outstanding, all three of them blocking:

1. **§3(b) H1 — ESC-6, the human's product-boundary clearance** (four items, each needing an explicit yes: the new user-visible hold, the standing operational obligation on the one CODEOWNER, the cost model, and the protected surfaces edited). **Two of those four items are no longer accurate as the amendment states them, and both corrections must reach the human before H1 is answered:** item 2's per-issue cost is **two acts, not one**, for every issue in the cutover set (§2.7.4, carried as **§8/E-5**), and item 4's protected-surface count rises from **four to five** because AM-6 point 3 cannot be honoured without editing `.github/workflows/label-swap.yml` (§2.1, §2.7.2, §4.3, carried as **§8/E-6**).
2. **§3(b) H3 — ESC-2**, whether GitHub repo collaborator permission counts as requester trust. This one **blocks S1 specifically**, because it decides whether AD-1 gains a fourth membership category. If the answer is the architect's recommended "no", S1 is unchanged and unblocked.
3. **§3(c) — the dual-lens adversarial panel** #1540 mandates, which runs after this revision and before `coder`. It is not satisfied by the amendment, by this document, or by ordinary review. Its starting points are reproduced in §9.

A12 (this revision) was the fourth gate; completing it clears that one and no other. Nothing in this document authorizes a merge, a protected-surface edit, or a line of code.

---

## 0.0 Revision history

**Revision 2 — 2026-09-15 — applies `ADR-1540-AMENDMENT-1-escalation-rulings.md` §3(a) item A12.** Revision 1 was the draft the architect ruled on; this revision applies the rulings rather than re-litigating them. One-line-per-ruling coverage map, so a reviewer can check completeness without diffing:

| Ruling | What it required of this document | Sections changed |
|---|---|---|
| **AM-1** (E-1 → option C + D) | Record verbatim that the authorizing act must be the human's own GitHub account; `edit_issue.sh --app human` is not an approval path. | §2.6, **§2.7.1 (verbatim sentence)**, §4.3, §8/E-1 |
| **AM-2** (AD-13 clarified) | Option B permanently foreclosed — no creation-time flag/token/marker may confer trust. Option A rejected as vacuous by the subset argument. | §1.5.2 (new **D-5**), §8/E-1 |
| **AM-3** (backfill) | Grandfathering list forbidden; bounded cutover set with the query that produces it. | **§2.7.3**, §8/E-1 |
| **AM-4** (FIND-1 confirmed, stricter) | Exact byte-for-byte milestone-title equality; **inverted default** (`None` = ignore `milestoned` events); "fifteen tests unmodified" criterion withdrawn for the milestone subset; new residual **R-7**. | §0.2, **§1.4**, **§1.6**, §2.3 D5, §3 (F21, F27–F29), §6.1, **§6.4**, §7.2 (R-7), §7.3 |
| **AM-5** (FIND-2 confirmed) | Bounded pagination in the fetch wrappers only, 10 pages / 1000 events, `re.sub` normalisation, bound-hit stderr diagnostic naming the issue. | §0.3, §1.4 ("Bounded pagination"), §1.6, §2.3 D5.3, §3 (F14), §7.2 (R-5) |
| **AM-6 / AF-5** (`/approve`) | Correct the false option-C clause; `/approve` authorizes nothing in S2; required doc changes in `docs/LABELS.md` **and** here; S3 closes it by reading the comment's GitHub-reported author. | §2.6, **§2.7.2**, §2.7.4, §4.3, §6.3, §8/E-1 |
| **AM-7** (E-2 declined) | R-4 accepted with three named revisit triggers; §6.1's two marker conformance tests are **binding**. | §1.5.2 (**D-6**), §6.1, §7.2 (R-4), §8/E-2 |
| **AM-8** (R-3) | Accepted for S2, closed in S3; record R-3 in the S2 work item alongside R-1; state the S3 clearing rule now. | §1.4, §7.2 (**R-3**), §8/E-2 |
| **AM-9** (`EXCLUDED_LABELS`) | Single landing site, no twin, no lock-step test; S2 first; ADR-1604 Component H orphaned; state the other admissible ordering. | §2.2, §2.3 D2, **§4.5 (new)**, §5, §7.3, §8/E-3 |
| **AM-10** (ADR-1604 AD-9) | Sub-issue filing MUST NOT enter `MACHINE_FILING_MARKERS`; authorization is live derivation from the parent, never cached. | §1.5.2 (**D-7**), §7.3 |
| **AM-11** (ADR-1542 G11) | G11 superseded, not overlapped; §6.3's conformance test is **required**; the fallback must contain no substitution, expansion, inline `jq`, or continuation. | §2.5, **§6.3**, §7.3, §8/E-4 |
| **AM-12 / DEV-1** (PR records) | Approved, with a binding added test that a bounced draft PR still reaches the worker and still blocks the #1395 skip. | §2.3 D1, **§6.2**, §7.1 (DEV-1), §8/E-4 |
| **AM-13** (cutover visibility) | DEV-2 required not optional; a distinct unmissable held-everything line; `bin/hos-cron` surfaces it into the cycle log; no issue filing. | §2.3 Step F, **§2.4**, §3 (F30), §6.2, §7.1 (DEV-2) |
| **§2 affected sign-offs** | `_verify_codeowner_actor` approvals **orphaned**, not "stand"; `_codeowners_humans` stand; `DECISIONS.md` correction note; add `ADR-1604` AD-9. | **§7.3** |
| **§3(c) panel surfaces** | Reachable from this document. | **§9 (new)** |

**New in revision 2, not in the amendment:** three escalations back to the architect — **§8/E-5** (the already-applied-signal deadlock: for every issue in the cutover set, no *additive* human act is available, because both qualifying signals are already present), **§8/E-6** (S2's protected-surface count rises from four to five, which changes what H1 item 4 asks the human to clear), and **§8/E-7** (an objection on record to the retained "skip a milestone-less record" rule, now that AM-4's inversion makes passing `None` the safe option). All three are recorded, not acted around.

**Numbering:** no existing section was renumbered. The amendment's cross-references to §1.4, §1.5, §1.6, §2.3, §2.5, §2.6, §6.1, §6.3, §7.3 and §8 all still resolve. Added: §0.0 (this section), §2.7, §4.5, §9.

---

## 0. Verification — what I re-derived, and the four findings that change the design

Every claim below was read from the Worker clone's working tree (revision 1: HEAD `80de8532`). I re-derived only what S1/S2 depend on; I did **not** re-derive the ADR's §0, which is authoritative.

### 0.0.1 What revision 2 re-read (branch `worker-1539-a12-td-revision2-260915124001-1317611`, base `6619e3e2`)

Applying a ruling is not a licence to restate the architect's verified facts as my own. The amendment's §0 verification table is **cited, not re-derived** — FIND-1's and FIND-2's presence in `probe.py`, `ADR-1604` AD-5's and AD-9's text, `ADR-1542` G11's text, and `bin/hos-cron:1137-1138`'s inlined `$(cat …jq)` are all the architect's, verified at `7e5c2a82`. What I read myself this revision, because I am writing new contract text that depends on it:

| Read this revision | What it establishes |
|---|---|
| `scripts/framework/require_human_approval.py:126-138` | The `re.sub(r"\]\s*\[", ",", out)` page-concatenation normaliser AM-5 binds is present, in exactly that form, with its own explanatory comment. `:140-158` `is_bot_reviewer`'s three denylist layers read as the amendment describes (type `Bot`; `[bot]` suffix; `BOT_ACCOUNTS` membership). |
| `.github/workflows/label-swap.yml:19, :36, :73-79, :96` | `GH_TOKEN: ${{ github.token }}` at `:36`; the `/approve` edit at `:74` is `gh issue edit --remove-label needs-human --add-label needs-ai 2>/dev/null \|\| true`; the confirmation body at `:75` is `"✅ /approve — needs-human → needs-ai (authorized by @${COMMENTER})."`. AF-5 is confirmed, and the confirmation *message* is the live artefact that tells the human they authorized something. |
| `bootstrap/edit_issue.sh:149-169` (`resolve_milestone_id`) | Milestones are resolved by `startswith($prefix)`, ambiguity fails closed. This is the prefix-matching AM-4 says the gate MUST NOT copy. |
| `bin/hos-cron:1046-1110` (PR fetch + routing), `:1134-1145` (candidates block), `:1152-1163` (skip condition) | `_OPEN_PR_NUMS` comes from a **separate endpoint** (`/pulls?state=open`), not from the issues query; the draft-PR bounce at `:1085` reads that PR's own labels; the skip at `:1158` requires `-z "$_OPEN_PR_NUMS"` independently of `-z "$_GATE_CANDIDATES"`. **This is why AM-12's binding test is satisfiable** (§6.2). The candidates `gh api` with `--jq "$(cat …)"` and `2>/dev/null` is at `:1137-1139`. |
| `bin/hos-cron:113-114` (crontab example) | The documented invocation is `>> /tmp/hos-worker-hos.log 2>&1` — stderr *is* merged into the cycle log there. Necessary but **not sufficient** for AM-13 point 3; see §2.4. |
| `tests/automation/test_probe.py:41-46, :295-437, :439-537` | `_make_issue()` emits only `number` and `labels` — **no `milestone` object**. `_milestoned_event()` (`:466`) emits no `milestone` object either. `test_verified_when_milestone_applied_by_codeowner_human` (`:476`) is the one test asserting a `milestoned` event authorizes. Four `TestProbeRepoMilestone` cases patch `_verify_codeowner_actor` and expect a candidate from a milestone-less fixture. **This widens AM-4's withdrawn acceptance criterion beyond the subset the architect named** — see §1.6, §6.4 and §8/E-7. |
| `docs/LABELS.md:1-45` (the `needs-ai` and `needs-human` rows) | `label-swap.yml` (`/approve`, `/handoff`) is listed as a writer of `needs-ai`; the control-flow column names `next_candidates.jq`'s `needs-human` exclusion. Both rows need AM-6's statement and §4.3's rename. |
| `bootstrap/query_issues.sh:13, :52, :55-57, :160-169, :192-197` | `--list --milestone <prefix> --label <l>` exists, filters `.pull_request == null`, and prefix-matches the milestone. This is the human-runnable form of AM-3's cutover query (§2.7.3) — no new tooling needed. |


### 0.1 Confirmed, unchanged from the ADR

| Claim | Evidence |
|---|---|
| Two copies of the eligibility filter exist | `bin/hos-cron:1138` (`--jq "$(cat "$REPO_ROOT/scripts/automation/lib/next_candidates.jq")"`) and `bootstrap/worker-cron-prompt.md:99-101` (the same query, same `--jq "$(cat …)"`) |
| The only eligibility filter is the `needs-human` exclusion | `scripts/automation/lib/next_candidates.jq` — `select((.labels // []) \| map(.name) \| index("needs-human") \| not)`. Nothing reads `.user`. |
| The shipped trust shapes are the right ones to promote | `probe.py:254-345` — `_codeowners_humans()` and `_verify_codeowner_actor()`, the latter composing `is_bot_reviewer` as *exclusion* then CODEOWNERS membership as the *positive* test, in that order |
| `is_bot_reviewer` is a layered denylist, pure, reusable | `scripts/framework/require_human_approval.py:140-158` |
| `BOT_ACCOUNTS` = worker + overseer + human-proxy + copilot | `scripts/framework/machine-accounts.env` |
| `.github/CODEOWNERS` yields exactly one individual human | `@ScottThurlow`; every other token is a path |
| `scripts/framework/**` is a protected surface; `scripts/automation/**` is not | `.github/CODEOWNERS` lists `/scripts/framework/`, `/bin/`, `/bootstrap/`, `/.github/workflows/`; no `/scripts/automation/` entry |
| `scripts/framework/trusted-requesters.txt` does not exist yet | `ls` — absent. S1 creates it. |

### 0.2 FIND-1 (severity **HIGH**) — `_verify_codeowner_actor` accepts a `milestoned` event for **any** milestone, including one the CODEOWNER never intended for this work

> **Disposition: CONFIRMED by AM-4, and amended *stricter* than I proposed.** The architect re-derived the defect independently and then rejected the back-compatible shape I built around it: a defaulted-to-vulnerable parameter guarded by a grep is the same class as the `--repo-root` and `--exclude-label` affordances this document itself rejects. The default is **inverted** (§1.4), the "fifteen tests unmodified" criterion is **withdrawn** for the milestone subset (§1.6, §6.4), and residual **R-7** is added (§7.2).


`probe.py:283-345` collects *every* `milestoned` event on the issue, with no check of which milestone was applied:

```
elif ev == "milestoned":
    relevant_actors.append(event.get("actor") or {})
```

The events payload carries `event.milestone.title`. The check does not read it. Consequence, on the live path S2 is about to build:

1. A stranger files an issue.
2. The human triages it from their own account to `Backlog` — an entirely benign act, and the *opposite* of authorizing autonomous work on it.
3. A later worker Step 0 cycle re-milestones it to `v0.7.0` and applies `needs-ai` (both bot actions, both correctly non-authorizing on their own).
4. The gate queries `milestone=<v0.7.0>&labels=needs-ai`, finds the issue, walks its events, finds a `milestoned` event by a verified human CODEOWNER, and declares it authorized.

The human's act of *deferring* the request becomes the authorization to build it. This is the same self-authorization shape #1539 exists to close, laundered through one benign human action. **S2 must not adopt the shipped shape unamended**, so this design binds the milestone-title match (§1.4) and carries the amended affected-sign-offs analysis in §7.3.

### 0.2.1 New in revision 2 — AF-5, the architect's finding, which invalidated one sentence of my own recommendation

The architect found what I missed: `.github/workflows/label-swap.yml` performs the `/approve` label edit under `GH_TOKEN: ${{ github.token }}` (`:36`, `:74` — I re-read both this revision), so the resulting `labeled` event's actor is `github-actions[bot]`, which `is_bot_reviewer` excludes unconditionally at layers 1 and 2. **A CODEOWNER commenting `/approve` therefore produces no authorization in S2.** My §8/E-1 option C claimed the opposite; that clause is corrected in §2.6 and §8/E-1, and the consequences are specified in §2.7.2. AD-4's own text says "walk the issue's events **and comments**"; revision 1 implemented half of it and did not notice. This is the sharpest single correction in this revision, and I record it as the architect's finding, not mine.

### 0.3 FIND-2 (severity LOW, availability only) — the events fetch is unpaginated

> **Disposition: CONFIRMED by AM-5**, with one addition I did not specify: hitting the page bound MUST emit a stderr diagnostic naming the issue number, because otherwise R-5 is an invisible permanent stall on exactly this repo's most-worked issues. Bound is 10 pages / 1000 events, in the **fetch wrappers only** — AD-1's no-network-in-the-predicate rule holds. Newest-end walking via `Link: rel="last"` is permitted, not required.


Both `_verify_label_actor` and `_verify_codeowner_actor` request `…/events?per_page=100` with no `--paginate`. GitHub returns issue events oldest-first, so on an issue with more than 100 events only the *oldest* 100 are visible and a recent CODEOWNER labelling is invisible. The failure direction is safe (no authorization found → gated) but it is an availability bug on exactly this repo's long-lived, heavily-relabelled issues. §1.4 binds bounded pagination.

### 0.4 FIND-3 (severity **HIGH** for the design, not for security) — AD-2's marker narrowing, read strictly, gates 93% of this repo's open issues

> **Disposition: RULED by AM-1/AM-2/AM-3.** AD-2 stands verbatim; nothing is widened. The subset argument below was adopted as binding reasoning. Option A is rejected as vacuous, option B is **permanently forbidden** by AD-13 as clarified in AM-2, option C is adopted with D as the ergonomic wrapper, and the backfill is bounded by the gate's own query rather than by the open backlog — **not 46 issues**. See §2.7. The architect explicitly did **not** route "are human-proxy filings trustworthy?" to the human, because even a maximally favourable answer has no admissible mechanism to express it; what remains the human's is the *consequence*, already on record as ESC-6 item 2. **The 46/100 and four-of-five counts below remain mine and were not re-derived by the architect** — the amendment's §3 flags them as such, and they should be re-derived before the human clears H1, since they size that burden.


The dispatching worker verified live GitHub state this cycle: of 100 open non-PR issues, **46** are authored by `scottthurlow-claude[bot]` (the human-proxy App), **32** by `hos-worker-hos[bot]`, **15** by `hos-overseer-hos[bot]`, **7** by `ScottThurlow`. Of the five current candidate issues, four (#1539, #1340, #1356, #1540) have `scottthurlow-claude[bot]` as both the `needs-ai` and the milestone actor; #1643 has `ScottThurlow` for `needs-ai`; #1678 has `hos-worker-hos[bot]` for both.

AD-1 binds trust to `issue.user`. AD-2 narrows category (b) so a bot-authored issue is trusted only if it *also* matches an enumerated machine-filing marker. The human-proxy App's interactive filings carry no such marker and never will (§1.5 and §8/E-1 explain why no marker can be made to work there). Under a strict reading, four of five live candidates are gated and the fifth survives only on `ScottThurlow`'s own `needs-ai` click.

That is fail-closed and therefore safe, but it is a design outcome the architect must rule on, not one I may resolve by widening the exemption. AD-2 names this exact situation and routes it back to the architect. **§8/E-1 carries it, with my recommendation.** Nothing in §1–§6 widens category (b); this document is written so that E-1's resolution changes *configuration and one prompt/agent behaviour*, not the primitive's shape.

### 0.5 FIND-4 (coordination) — two other accepted designs own the artefact S2 deletes

> **Disposition: RULED by AM-9 (ADR-1604) and AM-11 (ADR-1542 G11).** S2 ships first. `ADR-1604` AD-5's *mechanism* bullet is amended to a single `EXCLUDED_LABELS` entry — no inlined twin, no lock-step divergence test, because there is no second implementation; AD-5's *semantics* are unchanged. G11 is **superseded**, not merely overlapped, and §6.3's conformance test is the required acceptance mechanism. The architect also found a third collision I did not have: `ADR-1604` **AD-9** (§7.3, and D-7 in §1.5.2).


- **`docs/v0.7.0/ADR-1604-worker-self-split-isolation.md` AD-5 and `TECHNICAL-DESIGN-1604-…` §4.6 (Component H)** bind *changes* to `scripts/automation/lib/next_candidates.jq` (new `timeout-stuck` / `blocked` exclusions), to its inlined twin in `worker-cron-prompt.md`, and to `tests/automation/test_next_candidates.py`. S2 deletes all three. Neither has shipped (`next_candidates.jq` still carries only the `needs-human` exclusion).
- **`docs/v0.7.0/ADR-1542-sandbox-script-coverage.md` §4.9 (G11)** plans "one call wrapping the canonical `next_candidates.jq`" as a sandbox-allowlistable wrapper. S2's entry point *is* that wrapper, built for a different reason; G11 is superseded, not merely overlapped.

Both are carried as notifications in §8 (E-3, E-4) with an affected-sign-offs analysis.

### 0.6 Verification gaps, stated up front

1. I did not re-derive the live GitHub authorship counts in §0.4; they are the dispatching worker's, taken as authoritative per my task brief.
2. I did not inspect live GitHub repository settings (branch protection, collaborator permissions). Same gap the ADR and the requirements doc both declared; ESC-2 turns on it.
3. No exploit of any kind was attempted. This is a public repository.
4. I read `bin/hos-cron` and `bootstrap/worker-cron-prompt.md` from the working tree, not from `origin/main`. The working tree is on `main` at `80de8532` with no modifications to either file.

**Added in revision 2:**

5. **The shape of GitHub's issue-event `milestone` payload is asserted, not verified.** AM-4 binds exact `milestone.title` equality. I have not observed a live `milestoned` event payload, and the repo's own fixtures do not contain one (`tests/automation/test_probe.py:466`'s `_milestoned_event()` emits no `milestone` object at all). My working assumption — which the coder MUST confirm against one live payload before relying on it — is that the issue-event `milestone` object carries **only** `title`, with no `number`. If that is right, title equality is not a choice but the only available discriminator, and residual R-7 (a milestone rename de-authorizes) is unavoidable rather than a trade. If it is wrong and `number` is present, the coder must **still** implement title equality as AM-4 binds it, and raise the discrepancy to me rather than substituting number equality on their own judgment. §6.1 carries this as a named acceptance check.
6. **GitHub's no-duplicate-`labeled`-event behaviour is asserted from the API's documented idempotency, not observed.** §8/E-5 turns on it: adding a label that is already present produces no new `labeled` event, so the human has no *additive* act available on an issue that already carries the dispatch label. A one-command live check settles it and is on §6.2's acceptance list. If the assertion is wrong, E-5 dissolves and the cutover is as cheap as AM-3 describes — which is why it is stated as an assumption rather than folded silently into the design.
7. I did not re-derive the amendment's own verification table (§0.0.1 says what I did read). The architect's §0 stands as their verification, cited.

---

## 1. S1 — the trust primitive

### 1.1 File layout (binding — AF-3; placement is load-bearing, do not relocate for import convenience)

| Path | Status | Purpose |
|---|---|---|
| `scripts/framework/requester_trust.py` | **new** | The single implementation of the requester-trust question: loaders, the pure predicate, the AD-2 marker table, and the pure CODEOWNER-actor verifier. |
| `scripts/framework/trusted-requesters.txt` | **new, empty of entries** | AD-1(c) roster. Header comment only; zero logins. |
| `scripts/automation/lib/probe.py` | **modified** | `_codeowners_humans` becomes a re-export of the shared function; `_verify_codeowner_actor` becomes a thin fetch-wrapper delegating its decision to the shared pure function. No decision logic remains in this file. |

**Import direction, binding.** `requester_trust.py` sits on a protected surface and therefore MUST NOT import from `scripts/automation/**` or `scripts/oversight/**` — neither is protected, so importing either would let a bot weaken the gate's dependencies without a human approval. Permitted imports: the standard library, and `scripts.framework.require_human_approval.is_bot_reviewer`. The dependency arrow is `probe.py → requester_trust.py`, never the reverse; `probe.py` already imports `require_human_approval`, so this is the established direction, not a new one.

There is no `scripts/framework/__init__.py`; `scripts/__init__.py` exists and `scripts.framework` resolves as a namespace package. `from scripts.framework.requester_trust import …` and `python3 -m scripts.framework.…` both work from the repo root today (verified this session against `scripts.framework.require_human_approval`).

### 1.2 Data types

```
@dataclass(frozen=True)
class TrustedSet:
    codeowners: frozenset[str]   # AD-1(a) — lowercased logins, '@' stripped
    roster:     frozenset[str]   # AD-1(c) — lowercased logins
    apps:       frozenset[str]   # AD-1(b) — lowercased logins, COPILOT excluded
    bots:       frozenset[str]   # BOT_ACCOUNTS, lowercased — EXCLUSION input only

@dataclass(frozen=True)
class MachineFilingMarker:
    marker_id:      str          # stable audit id, e.g. "hos-cron/baseline-red"
    title_prefix:   str          # anchored match against issue.title
    title_contains: str | None   # optional second required substring
    emitting_site:  str          # "path::symbol" — drives the conformance test
    status:         str          # "active" | "dormant"

@dataclass(frozen=True)
class RequesterVerdict:
    trusted:   bool
    reason:    str               # stable machine-readable token, never prose
    category:  str | None        # "codeowner" | "roster" | "trusted-app" | None
    marker_id: str | None
```

`TrustedSet.bots` lives inside `TrustedSet` for one reason only: so that a caller cannot construct a trusted set without also supplying the exclusion input. It is **never** consulted as a trust source. Any code path that reads `.bots` to decide eligibility is a defect.

**Reason tokens (closed set, binding).** `"codeowner"`, `"roster"`, `"trusted-app"`, `"trusted-app:<marker_id>"`, `"not-in-trusted-set"`, `"no-login"`, `"bot-in-human-category"`, `"trusted-app-no-machine-filing-marker"`. Downstream (S6 audit, S5 assessment header) parses these tokens; they are an interface, not a log message, and must not be reworded without updating consumers.

### 1.3 Loaders

All loaders take `repo_root: str = "."` and are pure with respect to the environment except where stated. All are fail-closed by construction: an absent source yields an **empty** category, and an empty category can only ever *reduce* who is trusted.

**`codeowners_humans(repo_root=".") -> set[str]`** — promoted verbatim from `probe.py:_codeowners_humans`. Read `<repo_root>/.github/CODEOWNERS`; skip blank lines and `#` comments; for each remaining line treat fields *after the first* (the path) as owners; strip a leading `@`; **skip any token containing `/`** (an `org/team` pattern is not an individual human — AF-2, and the reason no glob matcher is needed anywhere in this design); lowercase; return the set. `not path.is_file()` → empty set. Any other read error propagates to the caller. Behaviour is byte-identical to the shipped function so that `tests/automation/test_probe.py::TestCodeownersActorVerification`'s three existing cases pass unmodified against the new home.

**`load_trusted_apps(repo_root=".") -> set[str]`** — read `<repo_root>/scripts/framework/machine-accounts.env` and extract **exactly three** variables: `BOT_WORKER_USERNAME`, `BOT_OVERSEER_USERNAME`, `BOT_HUMAN_USERNAME`. Lowercase, strip surrounding quotes and trailing `#` comments. Binding constraints:

- `COPILOT_BOT_LOGIN` is **not** read (FR2(b): a third-party reviewer is not an HOS role). Neither is the composite `BOT_ACCOUNTS`.
- The file MUST be **parsed with a line regex, never `source`d.** Shell-executing a config file on an authorization path turns a config edit into code execution. `label-swap.yml` sources it today; that is a workflow running from the trusted default branch, a different threat model, and is S3's business (AD-6), not ours.
- Missing file → empty set.
- **No environment override.** AD-13 forbids any knob that widens the trusted set; an env var naming a fourth trusted app is exactly that.

**`load_bot_accounts(repo_root=".") -> set[str]`** — the exclusion input for `is_bot_reviewer`. Baseline = the four logins in `machine-accounts.env` (`BOT_WORKER_USERNAME`, `BOT_OVERSEER_USERNAME`, `BOT_HUMAN_USERNAME`, `COPILOT_BOT_LOGIN`). If the `BOT_ACCOUNTS` environment variable is non-empty, the result is the **union** of baseline and env — never the env alone.

Rationale, binding (AD-13): a *larger* denylist is strictly stricter, so the environment may add. Allowing the environment to *replace* would let an operator (or a compromised cron environment) shrink the denylist and thereby promote a bot to "human" — a widening knob wearing a narrowing costume. If the file baseline is empty, callers fail closed regardless of the environment (§2.3, step B).

**`load_trusted_requesters(repo_root=".") -> set[str]`** — read `<repo_root>/scripts/framework/trusted-requesters.txt`.

Format, binding (FR3 requires who/when/why *per entry*; enforcing it in the parser makes the requirement mechanical rather than a review convention):

```
<login>  # added-by: <login> added: <YYYY-MM-DD> why: <free text>
```

- Blank lines and whole-line `#` comments are ignored.
- A line that does not match the shape is **skipped, with a one-line diagnostic to stderr naming the line number**. It is never accepted on a best-effort read. A malformed roster grants nothing.
- An entry whose login ends in `[bot]`, or for which `is_bot_reviewer(login, "", bots)` is true, is **rejected with a diagnostic**. Without this, the roster is a trivial route around AD-2: add the worker bot to the roster and every worker-authored issue becomes trusted with no marker. The roster is for people.
- Missing file → empty set (FR3: the mechanism must still function with CODEOWNERS + apps as the trusted set).
- A read error that is not `FileNotFoundError` propagates.

The shipped file contains a header comment and **zero entries**. Its header states, in the file: that it is a protected surface; that entries require human approval; that bot logins are rejected by the parser; and that membership confers *requester* trust only, never approver authority.

**`load_trusted_set(repo_root=".") -> TrustedSet`** — composes the four loaders. This is the only constructor production code uses.

### 1.4 Predicates

**`is_trusted_requester(login, user_type, trusted_set) -> tuple[bool, str]`** — the ADR-bound signature (AD-1). **Pure: no network, no filesystem, no environment.** Evaluation order is fixed and total:

1. `login` empty/absent → `(False, "no-login")`.
2. `low = login.lower()`.
3. If `low in trusted_set.codeowners` **or** `low in trusted_set.roster`:
   - if `is_bot_reviewer(login, user_type, trusted_set.bots)` → `(False, "bot-in-human-category")`;
   - else → `(True, "codeowner")` or `(True, "roster")` respectively (codeowners checked first).
4. If `low in trusted_set.apps` → `(True, "trusted-app")`.
5. Otherwise → `(False, "not-in-trusted-set")`.

Step 3's bot guard is the requester-side twin of the shipped `test_bot_labeling_is_never_authorized_even_if_in_codeowners`: a bot login mislisted in CODEOWNERS (or slipped past the roster parser) must not confer requester trust either. Categories (a) and (c) are human categories by definition; the guard makes that structural rather than assumed.

**This function is not an eligibility test.** It answers set membership only. Step 4 returns `True` for *any* issue authored by a trusted app, including a laundered one — AD-2's narrowing is applied by `requester_verdict`, below. A conformance test (§6.1) asserts that `is_trusted_requester` has no production caller other than `requester_verdict`.

**`machine_filing_marker(title: str) -> MachineFilingMarker | None`** — pure. Returns the first table entry (§1.5) for which `title.startswith(entry.title_prefix)` and (`entry.title_contains is None or entry.title_contains in title`). Case-sensitive. Dormant entries match (a dormant emitting site that is re-enabled must not silently break).

**`requester_verdict(record: Mapping, trusted_set: TrustedSet) -> RequesterVerdict`** — the **only** composition any consumer may use to decide eligibility.

1. `user = record.get("user") or {}`; `login = user.get("login", "")`; `user_type = user.get("type", "")`.
2. `trusted, reason = is_trusted_requester(login, user_type, trusted_set)`.
3. If not `trusted` → `RequesterVerdict(False, reason, None, None)`.
4. If `reason == "trusted-app"` (AD-2 narrowing):
   - `m = machine_filing_marker(record.get("title") or "")`;
   - `m is None` → `RequesterVerdict(False, "trusted-app-no-machine-filing-marker", "trusted-app", None)`;
   - else → `RequesterVerdict(True, f"trusted-app:{m.marker_id}", "trusted-app", m.marker_id)`.
5. Else → `RequesterVerdict(True, reason, reason, None)`.

**Boundary the caller must honour:** `requester_verdict` reads only `record["user"]["login"]`, `record["user"]["type"]`, and `record["title"]`. It MUST NOT be passed a record whose fields were derived from anything but a GitHub API response (FR5). It never reads the body, and it never reads a label.

**`verify_codeowner_actor(events, codeowners_humans, bot_accounts, label_name, expected_milestone_title=None) -> str | None`** — AD-4's live authorization test, promoted out of `probe.py` as a **pure function over an already-fetched events list** (AD-1: no network inside the predicate; the caller fetches and passes data in — the ADR-035 AD-2 shape).

1. `events` not a list → `None`.
2. Build `relevant` in API order:
   - `event == "labeled"` and `event.label.name == label_name` → append `event.actor`;
   - `event == "milestoned"` **and `expected_milestone_title is not None`** and `event.milestone.title == expected_milestone_title` (byte-for-byte string equality) → append `event.actor`.
3. For `actor` in `reversed(relevant)`: skip if no login; **if `is_bot_reviewer(login, actor.type, bot_accounts)` → `continue`**; if `login.lower() in codeowners_humans` → return `login`.
4. Return `None`.

**AM-4 — the inverted default, and why the previous draft was wrong (binding).** Revision 1 made `expected_milestone_title=None` reproduce the shipped behaviour — "accept a `milestoned` event for any milestone" — so that the existing tests would pass untouched, and then defended it with a conformance test asserting both production callers pass a non-`None` value. The architect rejected that and is right: **it is a defaulted-to-vulnerable parameter guarded by a grep**, the same class as the `--repo-root` and `--exclude-label` affordances §2.2 rejects on exactly those grounds. A grep protects the callers that exist today; the default protects every caller that will ever exist, including the ones in consumer deployments nobody here reviews. The binding rule:

> **`expected_milestone_title=None` MUST mean "ignore `milestoned` events entirely" — never "accept any milestone."** With `None`, only `labeled` events can authorize. A caller who forgets the argument therefore gets a **stricter** result, not a vulnerable one.

Consequences, stated plainly rather than smoothed over:

- **Matching is byte-for-byte string equality.** Never a prefix match, never a case fold, never whitespace or Unicode normalisation, never a "starts with the version number" shortcut. `bootstrap/edit_issue.sh:149-169` prefix-matches milestone titles **by design** (`startswith($prefix)`, re-read this revision) because a human typing `--milestone v0.7.0` should not have to reproduce an em dash. **The gate must not copy that**: this repo's milestone titles contain em dashes and shared version prefixes, so a prefix match would let `v0.7.0` authorize work under `v0.7.0 — <anything>`, and a human's deferral to a differently-suffixed milestone of the same series would authorize the active one. The two tools are deliberately asymmetric and a reviewer who notices the inconsistency should read it as intentional.
- **Title, not number, is the discriminator** — because the issue-event `milestone` object is believed to carry only `title` (§0.6 gap 5: asserted, and a named coder acceptance check). The comparison the gate performs is `event.milestone.title == record["milestone"]["title"]`, i.e. against the title of the milestone the candidate is *currently* in, which is by construction the milestone `--milestone <n>` selected server-side. That is what "the milestone the candidate is being considered under" means operationally, and it is why the gate compares titles despite being given a number.
- **A test that must change is the honest signal that behaviour changed.** The revision-1 acceptance criterion "all fifteen existing `probe.py` tests pass unmodified" is **WITHDRAWN** for every test that asserts a `milestoned` event authorizes. Those tests must be updated to pass the expected title explicitly. §1.6 and §6.4 name them individually; preserving them unchanged was precisely the goal that produced the unsafe default.
- **New residual R-7 (§7.2), to be recorded in the S2 work item:** renaming a milestone de-authorizes every issue authorized under the old title until a human re-acts. Fail-closed; availability cost only. It is the correct trade against prefix-matching.

Three properties that are deliberate and must survive review:

- **Order is exclusion-then-positive-membership.** `is_bot_reviewer` decides only "is this a bot"; CODEOWNERS membership is what confers authorization. Inverting them, or reading `not is_bot_reviewer(...)` as authorization, admits every anonymous member of the public (VF-5). A repo-wide conformance test (§6.1) asserts the literal `not is_bot_reviewer` appears nowhere in production code.
- **A bot actor is `continue`, not `return None`** — the shipped semantics. A bot relabelling after a CODEOWNER does not erase the CODEOWNER's act. This deliberately differs from `_verify_label_actor`'s "found the event, actor not allowed → None"; the difference is intended and is now stated in the shared docstring, because a reviewer encountering both will otherwise read one as a bug.
- **`expected_milestone_title` closes FIND-1, and its default is the strict case, not the compatible one.** Both production callers still MUST pass a non-`None` value (`probe.py` from the issue record it already holds; the gate from the same), and the conformance test asserting that is retained — but it is now **defence in depth on top of a safe default**, not the only thing standing between a forgotten argument and a bypass. That is the whole substance of AM-4. Events for `unlabeled`/`demilestoned` are ignored in S2 — see residual **R-3** (§7.2), accepted for S2 and **closed in S3** by AM-8's rule, which is stated there in full so S3 does not redesign it from scratch.

**Bounded pagination (FIND-2 / AM-5, binding).** The *fetch wrappers* — never this pure function; AD-1's no-network rule holds and is what makes the predicate testable without a stub — request `--paginate` with `per_page=100`, bounded to **10 pages (1000 events)**, and normalise `gh --paginate`'s concatenated page arrays with the `re.sub(r"\]\s*\[", ",", out)` idiom already present at `scripts/framework/require_human_approval.py:130-138` (re-read this revision; its own comment records that the boundary is `"]\n["` or `"] ["`, not a literal `"]["`, which is why a naive `replace("][", ",")` is wrong). Three rules on the bound:

1. **Exhausting the bound without a match is "not authorized / skip that candidate", never an error.** It is fail-closed for exactly that issue and leaves every other candidate unaffected.
2. **A transport failure remains exit 2** at the gate (§2.3 D5.3) and `None` in `probe.py` (unchanged). "The query failed" and "the query succeeded and found nothing" are different facts and must not collapse.
3. **Hitting the bound MUST emit a stderr diagnostic naming the issue number** — e.g. `select_work_candidates: WARN events-page-bound-reached issue=#<n> pages=10`. Without it, R-5 is an invisible permanent stall on precisely this repo's most-relabelled issues, which are also its most important ones.

**Permitted, not required:** walking pages from the newest end via the `Link: rel="last"` cursor, which would make the bound effectively unreachable. If the coder does this, the pure function's contract is unchanged and the events list passed in must still be in API order (oldest-first), because step 3 walks it `reversed`.

### 1.5 AD-2 — the machine-filing marker: enumeration, mechanism, and its honest limits

#### 1.5.1 The real enumeration

The ADR named "at least three" sites. The exhaustive search this session covered: every caller of `bootstrap/create_issue.sh`; every `gh issue create` in `bin/`, `scripts/`, `bootstrap/`; every `--method POST` against `/issues` in `scripts/**/*.py`; and `.github/workflows/**`. The complete set is **seven emitting sites in three classes**, plus one dormant:

| # | Site | Title | Labels | Milestone | Reaches the candidate set? |
|---|---|---|---|---|---|
| 1 | `bin/hos-cron:959` | `[BLOCKED] agent unavailable — <role> halted (missing: …)` | `needs-human,needs-ai` | none | No — `needs-human` excluded, no milestone |
| 2 | `bin/hos-cron:1414` (`_dm_title_prefix`) | `[BLOCKED] local main diverged on <project> (<role>) — needs manual recovery` | `needs-human,priority:critical` | none | No |
| 3 | `bin/hos-cron:1617` (`_bs_title_prefix`, #1496 repair mode) | `[BLOCKED] inner-loop tests failing on <project> — diagnose and fix` | `needs-ai,priority:critical` | **PATCHed to the target milestone** | **YES — the only one** |
| 4 | `bin/hos-cron:1687` (`_bs_title_prefix`, legacy halt) | `[BLOCKED] inner-loop tests failing on <project> — worker halted` | `needs-human,needs-ai` | none | No |
| 5 | `bin/hos-cron:1982` (`_TIMEOUT_BREAKER_TITLE_PREFIX`) | `[SUSPENDED] <role> timeout breaker tripped on <project> — worker halted` | `needs-human,needs-ai` | none | No |
| 5d | `bin/hos-cron:2055` (`_USAGE_LIMIT_BREAKER_TITLE_PREFIX`) | `[SUSPENDED] <role> usage-limit breaker tripped on <project> …` | `needs-human,needs-ai` | none | **Commented out (dormant, #1446)** — the prefix variable is still live at `:225` |
| 6 | `scripts/automation/lib/self_review_source.py:192` `file_finding_as_issue()` | `[AI: self-review] <class>: <description>` | `hos-coordination,needs-ai` | none | No (not milestone-scoped) |
| 7 | `scripts/review_self.sh:294` | `[AI: <reviewer>] design-concern: <n> HIGH/CRITICAL self-review findings (<ts>)` | `design-concern` | none | No |

Three findings follow, and they matter more than the table:

**(i) All seven are deterministic-code sites.** Their titles and bodies are composed by program logic from *local machine state* — missing agent files, `git cherry` output, a pytest exit code, a wall-clock cap, validator output. None of them reads attacker-controlled GitHub content to build the issue it files. This is the property the marker is actually selecting for.

**(ii) There is a second, much larger class the ADR did not enumerate: LLM-prose filing sites.** `.claude/agents/worker.md:236, :458, :490, :901` and `.claude/agents/overseer.md:162` instruct an agent to file issues through `bootstrap/create_issue.sh --app worker|overseer`, choosing the title, body and labels itself. `worker-cron-prompt.md`'s injection-handling instruction ("if it is clearly malicious, stop and file a `needs-human` issue describing the injection attempt") is in this class, and `CLAUDE.md`'s human-proxy default path ("file an issue for the autonomous worker to pick up", `--app human`) is the highest-volume member of it. These sites share the bot identities with class (i) and are exactly the laundering surface AD-2 exists to remove. **The marker's real job is to separate class (i) from class (ii) inside one identity** — not to separate bots from humans, which AD-1 already does.

**(iii) On this repo's live path, exactly one machine-filing site can reach the candidate set: #3.** Every other site either carries `needs-human` (excluded by the ordering filter) or carries no milestone (invisible to the milestone-scoped query). This bounds the blast radius of a missed enumeration, which is the first attack the ADR's own closing section invites: *on the live gate*, missing a marker can only under-trust site #3, whose failure mode is "the baseline-repair issue is not auto-selected and the worker's red-baseline repair stalls visibly" — an availability regression with a loud standing issue, not a bypass. The other six entries exist because (a) `probe.py`'s milestone strategy applies **no** `needs-human` exclusion, so sites #1, #4 and #5 *are* reachable in a consumer deployment, and (b) a future change that adds a milestone to any of them must not silently gate it.

#### 1.5.2 The mechanism

The marker is a **title-shape match against a committed, tested table** in `requester_trust.py`:

```
MACHINE_FILING_MARKERS = (
  ("hos-cron/agent-unavailable",   "[BLOCKED] agent unavailable",            None,                                  "bin/hos-cron",                          "active"),
  ("hos-cron/main-diverged",       "[BLOCKED] local main diverged on ",      None,                                  "bin/hos-cron::_dm_title_prefix",        "active"),
  ("hos-cron/baseline-red",        "[BLOCKED] inner-loop tests failing on ", None,                                  "bin/hos-cron::_bs_title_prefix",        "active"),
  ("hos-cron/timeout-breaker",     "[SUSPENDED] ",                           " timeout breaker tripped on ",        "bin/hos-cron::_TIMEOUT_BREAKER_TITLE_PREFIX",     "active"),
  ("hos-cron/usage-limit-breaker", "[SUSPENDED] ",                           " usage-limit breaker tripped on ",    "bin/hos-cron::_USAGE_LIMIT_BREAKER_TITLE_PREFIX", "dormant"),
  ("self-review/finding",          "[AI: self-review] ",                     None,                                  "scripts/automation/lib/self_review_source.py::file_finding_as_issue", "active"),
  ("review-self/design-concern",   "[AI: ",                                  " design-concern: ",                   "scripts/review_self.sh",                "active"),
)
```

**Where the marker is written:** nowhere new. It is the title string the deterministic sites already emit. This is deliberate — see D-2 below.

**How the gate verifies it:** `requester_verdict` consults the table **only after** `is_trusted_requester` has already returned `"trusted-app"`, i.e. only after GitHub has reported the author as one of the three HOS App identities.

**Why a non-bot author cannot forge it:** because the marker is never a trust source. A stranger may title their issue `[BLOCKED] agent unavailable — please fix` and it changes nothing: their `issue.user.login` is not in `TrustedSet.apps`, so step 4 of `is_trusted_requester` is never reached and the marker is never consulted. The marker is a **one-way narrowing filter applied inside an already-identity-confirmed set** — exactly the direction AD-2 and FR24 permit. It can remove trust; it can never add it. §6.2 names this as its own test case.

**Design decisions, with reasons:**

- **D-1 — the marker is the title, not a body token or an HTML comment.** The title is already in the list response the gate fetches, so verification costs **zero additional API calls** (AD-3's cost note holds). A body marker would require either `per_page`-inflated payloads or a per-issue fetch, which would put an API call on the *trusted* path — the one path the ADR's cost argument depends on staying free.
- **D-2 — no new marker is stamped into the emitting sites.** Five of the seven are `gh issue create` calls in `bin/hos-cron`, a protected surface; adding a body token there would be five protected-surface edits buying nothing. More importantly, a marker that *every* invocation of a wrapper emits is **isomorphic to trusting the identity** — it carries zero information and would reinstate the laundering path under a new name. A marker is only meaningful when the set of call sites that can emit it is a strict subset of the set of call sites the identity can reach. That holds for the worker/overseer Apps (class (i) ⊂ class (i)+(ii)); it does **not** hold for the human-proxy App, every one of whose filings is class (ii) — which is precisely why §8/E-1 cannot be resolved with a marker.
- **D-3 — the table is enforced by a conformance test, not by review.** For each entry, a test asserts the literal `title_prefix` (and `title_contains`) appears in the named emitting file. A second test counts issue-creation call sites — `grep -c "gh issue create" bin/hos-cron == 6` (5 active + 1 commented), `scripts/review_self.sh == 1`, and exactly one `--method POST` to `/issues` in `scripts/automation/lib/` — so adding an eighth deterministic filing site fails the build until the enumeration is updated. This is the mechanical answer to "if a machine-filing site is missed, a live path breaks."
- **D-4 — the honest limit.** Within a single bot identity **no in-band marker can be unforgeable against induction**, because the inducing agent has the same write authority and can read the marker table out of the repo. The marker removes the large, easily-reached laundering surface (any LLM-composed bot filing) and leaves a small, specific one (an LLM induced into reproducing a deterministic template byte-for-byte, *and* into applying a milestone, *and* into applying `needs-ai`). The only known unforgeable construction is **a separate GitHub App identity used exclusively by deterministic filing code**, which is structural and out of S1/S2's scope. **Ruled by AM-7: declined for now**, with R-4 accepted as a recorded residual and three named revisit triggers — see D-6.

- **D-5 — no creation-time assertion may ever confer trust (AM-2, binding; this is AD-13 as clarified).** Nothing passed at *issue-creation* time — no flag, no argument, no body token, no HTML marker, no envelope, no "the human confirmed this" convention documented alongside a tool — may cause the resulting issue to be treated as trusted or approved, **under any identity, with any human-confirmation convention attached to it**. Authorization is only ever derived live, at selection time, from a GitHub-reported act by a verified human CODEOWNER (AD-4). The reason is not fastidiousness: *a creation-time assertion is a claim about a fact the reader cannot check.* At the moment the gate reads it there is no human present, no way to distinguish a flag an attentive human asked for from a flag an induced agent typed, and no record of which it was.

  This is what permanently forecloses §8/E-1's **option B** (a `--confirmed` flag on `create_issue.sh --app human`). The `submit_pr.sh --app human --confirmed` precedent **does not transfer**, and the distinction is worth stating because it will be proposed again: there, the flag gates *a mutation the human is watching happen*, and it confers no standing authority on any later autonomous decision. Here it would confer autonomous-build authorization on a future cycle, read by a machine, with no human present at read time. Option **A** (stamping a marker on `--app human` filings) is rejected as **vacuous by the subset argument** — the architect adopted that argument as binding reasoning and credited it to this document, so it is now a rule rather than my opinion: *a marker is meaningful only when the set of call sites that can emit it is a strict subset of the set of call sites the identity can reach.* For the human-proxy App every filing is LLM-composed, so the emitting set equals the reachable set and the predicate carries zero bits.

- **D-6 — R-4's three revisit triggers, and the tests that make them detectable (AM-7, binding).** Any one of these reopens the separate-App question (§8/E-2) as a **required decision, not an option**:

  1. the assessment layer (S5) ever gains authorization-relevant authority — AD-13 says it must not, so this trigger is a tripwire on AD-13 itself;
  2. **any entry in `MACHINE_FILING_MARKERS` acquires an LLM-composed emitting site** — in which case that entry MUST be removed from the table **in the same change**, because its subset property has gone;
  3. a second machine-filing site becomes reachable by the milestone-scoped candidate query (today exactly one is — §1.5.1(iii)).

  §6.1's `test_marker_table_literals_exist_in_emitting_files` and `test_issue_creation_site_count_is_pinned` are the mechanism that makes triggers 2 and 3 detectable rather than noticed-later, and they are **binding, not optional**. A reviewer tempted to relax either as "brittle string tests" should read them as the enforcement arm of a declined structural change.

- **D-7 — sub-issue filing (`ADR-1604` AD-9) MUST NOT be added to this table (AM-10, binding).** The architect found a contradiction inside `ADR-1604` AD-9 that revision 1 did not have: its point 1 says sub-issues "never acquire authorization by authorship" and are authorized because the parent was; its point 2 said sub-issue filing is an enumerated machine-filing path under AD-2. **Point 1 governs; point 2 is amended.** A sub-issue's title and body are composed by an LLM from the parent's content, so it is squarely class (ii) — a marker on it would be exactly as vacuous as one on the human-proxy App, and worse, its content derives from the very issue whose trust is in question. Its authorization is an **AD-4-class live derivation**: at selection time the gate resolves the parent from the machine-readable derivation link and requires the parent to be **authorized now**, by the same test — never cached (FR7), never inherited from a determination made when the sub-issue was filed. Designing that check belongs to #1604's chain and it is a **new consumer of AD-1/AD-4's primitive, not a second trust definition** (#1135). S1/S2's enumeration is complete as of today and does not anticipate it; the table must simply stay closed against it.

### 1.6 `probe.py` refactor (AD-1: refactored onto, never copied from — #1135)

| Before | After |
|---|---|
| `def _codeowners_humans(repo_root=".") -> set[str]:` (22 lines) | `from scripts.framework.requester_trust import codeowners_humans as _codeowners_humans` — a re-export alias, zero logic |
| `def _verify_codeowner_actor(owner, repo, issue_number, label_name, codeowners_humans, bot_accounts) -> Optional[str]:` (fetch + decide, 45 lines) | same signature plus `expected_milestone_title: str \| None = None`, **whose default now means "ignore `milestoned` events" (AM-4), not "accept any milestone"**; body reduced to: fetch events via `_run_gh` with bounded `--paginate`, then `return requester_trust.verify_codeowner_actor(events, …)`. On `GitHubError` → `None` (unchanged). |
| `bot_accounts` default `os.environ["BOT_ACCOUNTS"].split()` | `requester_trust.load_bot_accounts(repo_root)` — file baseline ∪ env. Strictly stricter; when the env is set as today, identical. |
| `probe_repo` milestone branch calls `_verify_codeowner_actor(owner, repo, n, "needs-ai", codeowners_humans, bots)` | additionally passes `expected_milestone_title=issue["milestone"]["title"]` (FIND-1). A record with no `milestone` object is **skipped**, not authorized. |

**Compatibility contract for the coder — the import surface holds; the "no test changes" claim does not (AM-4).** `tests/automation/test_probe.py` patches `scripts.automation.lib.probe._run_gh` and imports `_codeowners_humans` / `_verify_codeowner_actor` from `probe`. Both names MUST remain importable from `probe` and the fetch MUST continue to go through `probe._run_gh` — that part of the contract is unchanged and is what makes this a promotion rather than a rewrite.

**The revision-1 acceptance criterion "all fifteen existing tests pass unmodified" is WITHDRAWN.** It was the wrong criterion: it made behaviour-preservation the goal, and behaviour-preservation is exactly what produced the unsafe default AM-4 removed. **A test that must change is the honest signal that behaviour changed**, and suppressing that signal is worse than the edit it saves. The tests that must change, named individually so the PR cannot absorb them quietly (all line numbers re-read this revision):

| Test | Why it changes | Required edit |
|---|---|---|
| `TestCodeownersActorVerification::test_verified_when_milestone_applied_by_codeowner_human` (`:476-483`) | Asserts a `milestoned` event authorizes. Under AM-4's inverted default with no `expected_milestone_title`, it now returns `None`. **This is the one test in the file whose subject is the changed behaviour.** | Pass `expected_milestone_title` explicitly, and extend the `_milestoned_event()` helper (`:466`) to emit a `milestone` object — it currently emits none at all, so the assertion never exercised the field FIND-1 is about. |
| `TestProbeRepoMilestone::test_returns_candidate_with_verified_codeowner_actor` (`:337`), `::test_calls_verify_codeowner_actor_not_verify_label_actor` (`:357`), `::test_url_format_correct` (`:377`), `::test_multiple_issues_all_returned` (`:418`) | **Not named by AM-4, and found in this revision.** All four build fixtures with `_make_issue()` (`:41-46`), which emits only `number` and `labels` — **no `milestone` object**. The rule "a record with no `milestone` object is skipped, not authorized" (row 4 above, retained by AM-4) therefore drops those records *before* `_verify_codeowner_actor` is reached, so the patched return value is never consulted and `mock_verify_codeowner.assert_called_once()` fails. | `_make_issue()` gains a `milestone` object. Fixture-only; no assertion changes. |

Two things follow that a reviewer should hold me to. First, **revision 1's acceptance criterion was already false** for those four tests, independently of AM-4 — the skip rule was in revision 1's §1.6 and I did not check the fixtures against it. That is my defect, not a consequence of the ruling, and I record it as such rather than letting the amendment absorb the blame. Second, this widens the "tests must change" set beyond the subset the architect named; the objection I have to the rule that causes it is on record as **§8/E-7**, and I have applied the rule regardless.

The replacement acceptance criterion for "one implementation" is narrower and actually checkable: **every existing assertion either passes unmodified or is changed only in its fixture, and every changed test is listed in the PR body with the sentence "this test changed because the behaviour changed."** Any test whose *assertion* must weaken is a defect in the change, not in the test. The same applies to any test asserting the exact `_run_gh` argument list, which changes when `--paginate` is added.

**No other `probe.py` behaviour changes in S1.** In particular, the milestone strategy does **not** gain `requester_verdict`: it already requires a verified CODEOWNER actor for *every* issue, which is strictly stricter than the gate's trusted-author fast path. Adding requester-trust there would only *widen* it. Recorded as OBS-1, §7.1.

---

## 2. S2 — the deterministic selection gate

### 2.1 File layout

| Path | Status | Purpose |
|---|---|---|
| `scripts/framework/select_work_candidates.py` | **new** | AD-3's single entry point. Query + trust + authorization + ordering. The only way work candidates are produced. |
| `scripts/automation/lib/next_candidates.jq` | **deleted** | Absorbed. |
| `bin/hos-cron` | **modified** (`:1131-1146`, plus comments at `:1132`, `:1587`) | Calls the entry point. |
| `bootstrap/worker-cron-prompt.md` | **modified** (Step 2 fallback, `:97-101`) | Calls the same entry point. |
| `.claude/agents/worker.md` | **modified** (`:179`, `:271`) | Stops naming `next_candidates.jq` as the ordering implementation. |
| `docs/LABELS.md` | **modified** (`:11`, `:29`, `:30`, `:49`, plus the `needs-ai` row) | Hardcoded-literal inventory updated, **and AM-6's required statement added**: in the S2 era `/approve` performs a label swap and does **not** authorize autonomous selection. **No new label** (AD-11). |
| `.github/workflows/label-swap.yml` | **modified** (`:75`, and `:83`'s `/decline` sibling left alone) | **New in revision 2 — AM-6 point 3.** The `/approve` confirmation body currently reads `"✅ /approve — needs-human → needs-ai (authorized by @${COMMENTER})."` (re-read this revision at `:75`). In the S2 era that sentence is false, and it is the *live* artefact that tells a human they authorized work — `docs/LABELS.md` alone does not fix a lie told in the issue thread. See §2.7.2 for the required wording and for why the command is **not** made to refuse. |

`bin/hos-cron`, `bootstrap/**`, `scripts/framework/**`, `.claude/agents/**` **and `.github/workflows/**`** are all protected surfaces. **Five** human-gated merges — one more than revision 1 counted, because AM-6 point 3 cannot be honoured without touching `label-swap.yml`. None is pre-authorized by this document (AD-14). This changes what §3(b) H1 item 4 asks the human to clear, so it is carried to the architect as **§8/E-6** rather than being quietly absorbed into a count the human has already been shown.

### 2.2 CLI contract

```
python3 -m scripts.framework.select_work_candidates \
    --repo <owner/repo> \
    --milestone <positive integer> \
    [--label <name>]                        # default: needs-ai
    [--max-authorization-checks <n>]        # default and ceiling: 25
```

**stdout** — zero or more lines, byte-identical in format to the deleted jq filter:

```
#<number> [<critical|high|medium|low>] <title>
```

**stderr** — diagnostics and exactly one summary line. Never candidate data.

**Exit codes** — two, and only two:

| Code | Meaning |
|---|---|
| `0` | The determination completed. stdout is the complete, authoritative candidate list (possibly empty). |
| `2` | **Fail closed.** stdout is empty. stderr carries one `select_work_candidates: <reason-token>` line. The caller must treat this as "no candidates", never as "unknown, proceed anyway". |

`argparse`'s own usage-error exit is also `2`, which is consistent: a malformed invocation is a fail-closed condition.

**Flags that deliberately do not exist (AD-13 — no knob may widen the trusted set or disable the gate):**

- **No `--repo-root`.** The repo root is derived from `Path(__file__).resolve().parents[2]`. A `--repo-root` flag would let a caller point the gate at a directory containing a forged `.github/CODEOWNERS` or a populated `trusted-requesters.txt` — a complete bypass through an ergonomics flag. The *library* functions in `requester_trust.py` remain `repo_root`-parameterised (probe.py and the tests need that); the *entry point* is not.
- **No `--exclude-label`.** The exclusion set is the module constant `EXCLUDED_LABELS = ("needs-human",)`. A flag could remove the `needs-human` exclusion. **This constant is now the bound landing site for `ADR-1604` AD-5's queue exclusions (AM-9)** — the architect amended AD-5's *mechanism* bullet so the exclusion is expressed **once, here**, with no inlined twin in `worker-cron-prompt.md` and no lock-step divergence test, because after S2 there is no second implementation to diverge from. AD-5's *semantics* are unchanged and still binding. Note the scope precisely, so #1604's author is not misled: AD-5 makes one narrow marker authoritative for **both** the stuck-count and the queue exclusion; only the **exclusion** half lands here. The count half stays in #1604's stuck-set query. See §4.5.
- **No `--trusted`, `--allow`, `--skip-gate`, `--dry-run-trust` or any equivalent.** A test enumerates the parser's actions and asserts the flag set is exactly the four above.
- **`--label` is permitted** because it cannot widen trust: it changes only *which records are queried*, and every returned record still passes the identical trust and authorization tests. It exists so the `needs-ai` → `needs-worker` rename (#1349) is a one-line change rather than a sixth hardcoded literal (FR26). If the label is renamed and the default is not updated, the query returns nothing → zero candidates → fail-closed (AD-4's stated rename-survivability property).
- **`--max-authorization-checks` may only lower.** Effective value is `min(25, max(0, provided))`.

**Environment.** The gate requires `gh` to be authenticated already (`GH_TOKEN` exported by the cron launcher, or the worker's ambient session auth). It **MUST NOT mint or revoke tokens** — putting credential handling on the selection path adds a failure mode and a secret-handling surface to a gate whose whole value is being boring and deterministic.

**GitHub access.** The gate shells out to `gh api` directly, with `subprocess.run`, following the precedent already set in the same directory by `require_human_approval.py:_fetch_reviews`. It does **not** import `scripts.automation.lib.github._run_gh`, which is functionally the right helper but sits on an unprotected surface (§1.1). Search performed before writing this: `scripts/`, `bootstrap/`, `bin/`, and `scripts/automation/lib/*.py` — found `scripts/automation/lib/github.py::_run_gh` (right behaviour, wrong trust direction), `bootstrap/query_issues.sh` (mints its own token per call, emits a summary line with no `.user` fields, so unusable here), and `require_human_approval.py::_fetch_reviews` (right directory, right pattern, review-specific). If a third `scripts/framework/**` consumer ever needs `gh api`, the helper should be promoted **into** `scripts/framework/`, never imported out of `scripts/automation/`.

### 2.3 Algorithm (ordered; the order is part of the contract)

**Step A — arguments.** `--repo` must match `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. `--milestone` must parse as a positive integer. This second check is load-bearing: `bin/hos-cron` substitutes `@@MILESTONE_NUMBER@@` into the worker prompt **only when `HOS_TARGET_MILESTONE_NUMBER` is non-empty** (`bin/hos-cron:1808-1815`), so an unresolved milestone leaves the literal placeholder in the fallback command. `--milestone @@MILESTONE_NUMBER@@` must fail closed, not be coerced. Any violation → exit 2.

**Step B — configuration, all fail-closed.**

1. `bots = load_bot_accounts()` — empty → exit 2 `bot-accounts-empty`. (The house precedent: `require_human_approval.py` exits 2 on empty `BOT_ACCOUNTS`.)
2. `codeowners = codeowners_humans()` — empty → exit 2 `codeowners-empty`. An absent, unreadable, or team-patterns-only CODEOWNERS means **no actor can ever authorize anything**, so running is pointless and silence would be dangerous. Note this is stricter than the shared loader, which returns an empty set; the primitive stays permissive-of-absence for `probe.py` compatibility and the *gate* enforces.
3. `apps = load_trusted_apps()` — empty → exit 2 `trusted-apps-empty`.
4. `roster = load_trusted_requesters()` — absent → empty set, continue. A non-`FileNotFoundError` read error → exit 2 `roster-unreadable`.
5. Any other exception in Step B → exit 2 `config-error`.

**Step C — one list query.**

```
gh api "repos/<repo>/issues?state=open&milestone=<n>&labels=<label>&per_page=100"
```

Non-zero exit, non-JSON output, or a non-list result → exit 2 `list-query-failed`. No `--paginate`: this preserves today's documented 100-issue single-page ceiling exactly (`bin/hos-cron:1885-1890` states it as the known limit). Recorded unchanged as R-6, §7.2.

**Step D — per record, in API order.**

| Step | Rule | On failure |
|---|---|---|
| D1 | `record.get("pull_request")` present → **skip** | — (DEV-1, §7.1; **approved by AM-12 subject to §6.2's binding added test**) |
| D2 | any label name in `EXCLUDED_LABELS` → skip | — (the one landing site, AM-9 / §2.2) |
| D3 | `verdict = requester_verdict(record, trusted_set)` | — |
| D4 | `verdict.trusted` → **eligible**, `authorization = "requester-trusted:" + verdict.reason`, **zero extra API calls** | — |
| D5 | otherwise → AD-4 live authorization (below) | |
| D6 | rank: `priority:critical`→0, `priority:high`→1, `priority:medium`→2, else 3 | — |

**D5 — live actor-derived authorization.** For each untrusted-authored record:

1. `auth_checks += 1`. If `auth_checks > effective_cap`: **skip this and every remaining untrusted record**, emit one stderr `WARN authorization-check-cap-reached`, and continue to Step E with what is already eligible. This is a deliberate refinement of "any error → exit 2" and it needs its reason stated: a cap hit is **not an error**. Exiting 2 here would mean that anyone who can get N untrusted-authored issues into the milestone denies the worker *all* work, including trusted work — turning a cost control into a denial-of-service. Skipping is fail-closed for exactly the issues in question and preserves availability for everything else.
2. `record["milestone"]["title"]` absent → skip with a WARN (cannot bind FIND-1's check; never authorize blind).
3. Fetch `gh api --paginate "repos/<repo>/issues/<n>/events?per_page=100"`, bounded to 10 pages / 1000 events, normalising concatenated page arrays per §1.4. **Transport error, non-zero exit, or unparseable output → exit 2 `events-query-failed:<n>`.** A partial candidate list is a correctness hazard — it can silently demote a `priority:critical` item — so an incomplete determination must not be presented as a complete one. **Exhausting the page bound without a match is *not* an error**; it is "not authorized" → skip that candidate, **and it MUST emit `WARN events-page-bound-reached issue=#<n>` to stderr** (AM-5). A stall that nobody can see is R-5 becoming permanent.
4. `actor = verify_codeowner_actor(events, codeowners, bots, label, expected_milestone_title=record["milestone"]["title"])` — a non-`None` title always, per AM-4. Passing `None` here would silently disable the milestone channel, which is safe but wrong: the gate holds the title and has no excuse not to bind it.
5. `actor is None` → skip. Otherwise **eligible**, `authorization = "codeowner-actor:" + actor`.

**Step E — ordering (preserved exactly).** `sorted(eligible, key=lambda c: (c.rank, c.number))`. Emit `#{number} [{priority}] {title}` with `title` defaulting to `""` and **no truncation**. Python's `sorted` and jq's `sort_by` are both stable and the key is total, so the two are equivalent by construction, not by luck. Degenerate records (absent or `null` `labels`) must not raise — they rank `low` and stay eligible, matching the jq filter's `(.labels // [])` and its explicit test.

**Step F — the stderr summary, and AM-13's held-everything line (binding).**

Always exactly one summary line:

```
select_work_candidates: repo=<slug> milestone=<n> scanned=<N> eligible=<M> gated=<G> auth_checks=<A>
```

**And, when `eligible == 0 and gated > 0`, one additional, distinct, unmissable line** (AM-13 point 2). This is not the same fact as the summary and must not be left for an operator to infer by comparing two numbers at 3am:

```
select_work_candidates: ALL-CANDIDATES-GATED <G> of <N> in-milestone issues are held for human authorization
select_work_candidates: ALL-CANDIDATES-GATED reasons: trusted-app-no-machine-filing-marker=<a> not-in-trusted-set=<b> no-codeowner-actor=<c> …
select_work_candidates: ALL-CANDIDATES-GATED issues: #1539 #1340 #1356 #1540 (+<k> more)
```

Four binding properties:

1. **It must be distinguishable at a glance from "the milestone is empty."** `eligible=0 gated=0` and `eligible=0 gated=12` are opposite operational situations — nothing to do versus everything blocked on one person — and the summary line alone renders them as near-identical strings. The `ALL-CANDIDATES-GATED` token exists to be greppable and to be *visually* different, not to be parsed.
2. **It names the reason tokens and their counts** (AM-13's requirement), drawn from §1.2's closed reason-token set. `no-codeowner-actor` is the D5.5 outcome and is a gate-local token, not a `RequesterVerdict.reason`.
3. **It names the issue numbers**, bounded — first 20, then `(+k more)`. AM-13 requires only the count and the reasons; I am adding the numbers because §2.7.3's cutover is not performable without them, and because the gate has already scanned at most 100 records so the information is free. This is deliberately **not** AD-11's full held-request listing mode, which stays in S6: no bodies, no titles, no per-issue explanation, one bounded line.
4. **It is never routed into an issue** (AM-13 point 3). A per-cycle issue-filing loop on this condition would be its own denial-of-wallet, and bounded-retry/escalation is AD-10's design, which belongs with the assessor slice. stderr and the cycle log, nothing more.

Durable per-decision audit events are AD-12/S6 and are **not** built here. These lines are the whole of the S2-era operator signal, which is why §2.4's removal of `2>/dev/null` is **required, not optional** (AM-13 point 1).

### 2.4 Call site 1 — `bin/hos-cron` (the pre-computed candidates block)

**Today** (`:1131-1146`): the actionable-work gate runs `gh api …` piped through `--jq "$(cat "$REPO_ROOT/scripts/automation/lib/next_candidates.jq")"` with `2>/dev/null`, capturing into `_GATE_CANDIDATES` and setting `_gate_candidates_ok`. `_build_context` (`:1886-1897`) reuses `_GATE_CANDIDATES` and `head -5`s it into the `### Next work candidates` section.

**After:**

```
  _GATE_CANDIDATES=""
  _gate_candidates_ok=1
  _gate_err="$(mktemp)"
  if [[ -n "${HOS_TARGET_MILESTONE_NUMBER:-}" ]]; then
    if _GATE_CANDIDATES=$( (cd "$REPO_ROOT" && python3 -m scripts.framework.select_work_candidates \
        --repo "$_REPO_SLUG" --milestone "$HOS_TARGET_MILESTONE_NUMBER") 2>"$_gate_err" ); then
      _gate_candidates_ok=1
    else
      _gate_candidates_ok=0
      _GATE_CANDIDATES=""
    fi
    cat "$_gate_err" >&2                                    # DEV-2: nothing is swallowed
    if grep -q 'ALL-CANDIDATES-GATED' "$_gate_err"; then    # AM-13 point 3
      echo "$LOG_PREFIX ALL WORK CANDIDATES GATED — every in-milestone issue is held for human authorization; this is NOT an empty backlog (#1539/#1540, see the select_work_candidates lines above)"
    fi
  fi
  rm -f "$_gate_err"
```

Unchanged around it: `_gate_all_ok` composition (`:1152-1156`), the `no actionable work` skip (`:1158-1163`), `_build_context`'s consumption and `head -5` (`:1894-1895`). The `(cd "$REPO_ROOT" && …)` subshell mirrors the established `_audit` invocation at `:364`.

**Deliberate change, DEV-2 — required, not optional (AM-13 point 1):** the `2>/dev/null` at `:1139` is **removed**. Nothing about control flow changes; a silent skip is precisely the failure mode `CLAUDE.md` names as the one to guard against, and a fail-closed gate that says nothing is indistinguishable from an empty backlog.

**Why DEV-2 alone does not satisfy AM-13 point 3, and why the temp file is there.** I re-read `bin/hos-cron:113-114` this revision: the documented crontab is `>> /tmp/hos-worker-hos.log 2>&1`, so with `2>/dev/null` gone the gate's stderr does reach the cycle log in the shipped configuration. That is necessary and not sufficient, for two reasons the amendment's point 3 exists to cover. First, it is **configuration-dependent** — a consumer who redirects only stdout loses the entire signal, and AM-13's whole point is that this condition must not be losable. Second, raw subprocess stderr arrives **without `$LOG_PREFIX`**, so it is invisible to every existing habit and tool that greps the log by `[hos-worker-cron:<project>]`; the one line an operator most needs would be the one line that does not match their filter. Capturing stderr, re-emitting it verbatim, and then adding **one** prefixed line on the `ALL-CANDIDATES-GATED` token fixes both without parsing the gate's output for anything load-bearing — the token is a presence check, never a value the control flow depends on.

**What `bin/hos-cron` must NOT do with it:** not suppress the raw stderr in favour of the prefixed line (the reason tokens and issue numbers live in the raw lines); not branch on it (`_gate_candidates_ok` and `_GATE_CANDIDATES` remain the only control-flow inputs — a gated-everything cycle is *exit 0 with an empty list*, behaviourally identical to an empty milestone, and deliberately so); and **not file an issue about it** (AM-13 point 3).

**Semantics after the change — trace it through, because this is where AD-3's "the fallback is the same gated script" pays off:**

| Gate result | `_gate_candidates_ok` | Context section | Worker behaviour |
|---|---|---|---|
| exit 0, candidates | 1 | the list | picks the first non-blocked candidate |
| exit 0, empty | 1 | `(none available or fetch failed)` | Step 2 fallback → **same gated command** → same empty result → no work |
| exit 2 (any cause) | 0 | `(none available or fetch failed)` | Step 2 fallback → **same gated command** → exit 2 → no work |

In the third row `_gate_all_ok=0` means the cycle does **not** take the `#1395` early skip — Step 0 triage, Step 0.5 release gating and Step 1 PR handling all still run. Only *new work selection* is closed. That is the intended split: the gate closes work selection, not the cycle.

**One property worth stating because a reviewer will ask:** this block runs *before* the cycle's git sync (`bin/hos-cron:1004-1017` explains why), so the gate code executed is the local clone's, one sync behind `origin/main`. That is unchanged from today, where `cat next_candidates.jq` read the same local tree.

### 2.5 Call site 2 — `bootstrap/worker-cron-prompt.md` Step 2

**Today** (`:97-101`): a `gh api … --jq "$(cat scripts/automation/lib/next_candidates.jq)"` fallback. That command is unallowlistable under `CLAUDE.md` (command substitution), so on an unattended cycle it is **denied outright and silently skipped** — the exact class of failure `CLAUDE.md` documents.

**After** — the fallback becomes one static command with no substitution, no inline `jq`, and no variable expansion (`@@MILESTONE_NUMBER@@` is substituted by `_build_prompt` before the LLM ever sees it, so the rendered text is fully literal):

```
python3 -m scripts.framework.select_work_candidates --repo thurlow-research/HumanOversightSystem --milestone @@MILESTONE_NUMBER@@
```

**The prose that must accompany it is part of the contract, not decoration:**

> This command is the **only** sanctioned way to produce work candidates. If it exits non-zero it has **failed closed** — there are no candidates this cycle. Do NOT construct your own query, do NOT fall back to `gh api`, do NOT read the issue list by any other means, and do NOT pick an issue from the Step 0 triage list. STOP after Steps 0/0.5/1.

Without that paragraph a capable model will helpfully improvise a `gh api` query and reopen the bypass in the most sympathetic possible way. A conformance test (§6.3) asserts the prompt contains this instruction and contains **no** `gh api …labels=needs-ai…` query and **no** `--jq`.

**AM-11 — the binding acceptance condition, because G11 is superseded rather than merely overlapped.** `ADR-1542` §4.9 (G11) planned a sandbox-allowlistable wrapper around `next_candidates.jq` for exactly this call site. S2's entry point **is** that wrapper, built for a different reason, and building G11 separately would produce the duplicate-gate defect (#1135) in its purest form: two wrappers over the same selection decision, one of them trust-gated. The architect has therefore marked G11 superseded and orphaned its sign-offs **for that item only** — with a condition attached that this document must meet, not merely intend:

> The rendered fallback invocation MUST contain **no command substitution, no variable expansion, no inline `jq`, and no backslash continuation.**

That is G11's actual requirement, and it is the reason the current line is broken: per `CLAUDE.md`'s sandbox section, an unallowlistable command on an unattended cycle is not prompted for — it is **denied outright and silently skipped**, with the denial reported to the model and the cycle continuing as though the step had run. The command above satisfies all four conditions by construction, because `@@MILESTONE_NUMBER@@` is substituted by `_build_prompt` *before* the LLM ever sees the text, so the rendered string is wholly literal. **§6.3's conformance test is the mechanism that keeps it true, and AM-11 makes it required, not optional** — an intention about a prompt string, unpinned by a test, survives exactly until the next person needs a second milestone.

**Note on AD-7, binding:** this design assumes Step 0 does the wrong thing. Nothing above depends on Step 0's routing behaviour. S4 may improve Step 0; the gate's correctness does not move when it does.

### 2.6 Worked trace of the five live candidates

Applying §2.3 to the five candidates the dispatching worker verified (author, then `needs-ai`/milestone actors). Revision 1 labelled this "before §8/E-1 is ruled"; **E-1 is now ruled (AM-1) and the trace is unchanged** — option C keeps AD-2 exactly as written, so every verdict below stands. What changed is the *interpretation*: this is no longer a provisional picture pending a widening, it is the intended steady state.

| Issue | Author | `needs-ai` / milestone actor | D3 verdict | D5 result | Selectable? |
|---|---|---|---|---|---|
| #1539 | `scottthurlow-claude[bot]` | `scottthurlow-claude[bot]` | untrusted — `trusted-app-no-machine-filing-marker` | actor is a bot → `is_bot_reviewer` → `continue` → `None` | **No** |
| #1340 | `scottthurlow-claude[bot]` | `scottthurlow-claude[bot]` | same | same | **No** |
| #1356 | `scottthurlow-claude[bot]` | `scottthurlow-claude[bot]` | same | same | **No** |
| #1540 | `scottthurlow-claude[bot]` | `scottthurlow-claude[bot]` | same | same | **No** |
| #1643 | `scottthurlow-claude[bot]` | `ScottThurlow` (needs-ai), `scottthurlow-claude[bot]` (milestone) | untrusted | `labeled` event actor `ScottThurlow` — not a bot, in CODEOWNERS → **authorized** | **Yes** |
| #1678 | `hos-worker-hos[bot]` | `hos-worker-hos[bot]` (both) | untrusted — title has no marker | bot actor → `continue` → `None` | **No** — this is the self-authorization shape the gate exists to reject |

This is the correct, intended behaviour of every line of §1–§2 as written. It is also a near-dead work loop, which is why E-1 was an escalation and not a footnote. The mechanism has a *working* release valve — #1643 passes purely because a human clicked `needs-ai` from their own account, which is precisely AM-1's option C in action, observed rather than theorised.

**Correction, AM-6 / AF-5 — revision 1 got the valve's shape wrong in one clause.** Revision 1's §8/E-1 option C said an issue becomes selectable when `ScottThurlow` personally applies `needs-ai` or the milestone from their own account **"or comments `/approve`."** *That last clause is false.* `.github/workflows/label-swap.yml` performs the `/approve` label edit with `GH_TOKEN: ${{ github.token }}` (`:36`), so the resulting `labeled` event's actor is `github-actions[bot]` — `type == "Bot"`, login ending `[bot]` — which `is_bot_reviewer` excludes unconditionally at layers 1 and 2, whether or not it appears in `BOT_ACCOUNTS`. `verify_codeowner_actor` walks events only. **A CODEOWNER commenting `/approve` therefore produces no authorization at all in S2.** The issue flips labels, the workflow posts `"✅ /approve — needs-human → needs-ai (authorized by @ScottThurlow)."`, and the gate still refuses it: fail-closed and therefore safe, and **a silent no-op that looks exactly like success** — the same failure mode AD-6 already condemns in that workflow's own `2>/dev/null || true`.

The first two clauses of option C are correct, and #1643 is the live proof of the first. Everything that follows from the correction — what the human must actually do, what the repo must stop telling them, and the deadlock this creates for the cutover set — is §2.7.

**Reading the `needs-ai` column above with AF-5 in mind:** the trace's actors are the *recorded event actors*, so an issue whose `needs-ai` arrived via `/approve` would show `github-actions[bot]` there, not the commenter. None of the six does, so no row changes. A reviewer checking this against live GitHub should expect `github-actions[bot]` on any issue whose label came from a slash command, and must not read the workflow's confirmation comment as evidence of who applied the label.

---

## 2.7 The S2-era authorization act (AM-1, AM-3, AM-6) — what the human does, what the repo must stop saying, and the one thing that does not work

This section is new in revision 2. It exists because AM-1 makes one demand of this document above all others: *a gate whose documented approval path silently does nothing is worse than no gate.* Everything here is about making the documented path the one that actually works.

### 2.7.1 The authorizing act — stated verbatim, as the amendment requires

> **The authorizing act must be performed by the human's own GitHub account.** `bootstrap/edit_issue.sh --app human` writes as `scottthurlow-claude[bot]`, which `is_bot_reviewer` excludes, so any tooling or documentation offering `edit_issue.sh --app human` as the approval path is wrong and must not be written. The valid S2-era acts are: **the GitHub web UI, the GitHub mobile app, or a personal-access-token `gh` invocation under `ScottThurlow`.**

Three binding consequences for the S2 change set:

1. **No approval helper may be written.** Not a script, not a `Makefile` target, not a documented one-liner, not a convenience wrapper "that just calls `edit_issue.sh` for you." Any such tool would run under an App identity and would produce a `labeled` event the gate excludes — a tool that appears to authorize and does not is strictly worse than no tool, because it converts a visible gap into an invisible one. This is the same reasoning as D-5: the failure is silent and looks like success.
2. **The sentence above must appear in whatever the human is asked to do at cutover** (§2.7.3), not only here.
3. **Nothing in S1/S2 may special-case the human-proxy App**, in either direction. It is one of the three `machine-accounts.env` App identities in AD-1(b), narrowed by AD-2 exactly like the other two. A carve-out written to make the queue move would be option A wearing a configuration costume.

Option **D** — the human-proxy session stops self-applying the dispatch label to its own filings, and ends every filing by telling the human the exact act required — is adopted as the ergonomic wrapper and is *also* the correct hygiene fix independent of ergonomics: a human-proxy session applying `needs-ai` to its own filing is the same self-authorization shape as the worker's Step 0 (VF-3), one identity removed. It should stop regardless. The `CLAUDE.md` human-proxy-section edit that needs is a protected-surface change, human-gated at merge, and is **not pre-authorized here** (AD-14). It is also **not** in S2's file list (§2.1) — it is a behaviour change to an interactive session, separable from the gate, and folding it into the critical-path fix would add a sixth protected surface for an ergonomic gain.

### 2.7.2 `/approve` in the S2 era: what it does, what it must say, and why it is not made to refuse

**What it does:** the label swap, exactly as today. `needs-human` → `needs-ai`, performed by `github-actions[bot]`. **What it does not do:** authorize autonomous selection. AM-6 point 2 is explicit that **S2 is event-only and that is correct** — comment-reading must not be bolted onto the critical-path fix, and I am not proposing it.

**AM-6 point 3 is a shipping condition, not a documentation nicety:** *S2 MUST NOT ship while the repo tells a human that `/approve` authorizes work.* Two required elements of the S2 change set, both listed in §2.1:

| Where | Required change |
|---|---|
| `docs/LABELS.md` | The `needs-ai` row's writer column already names `label-swap.yml` (`/approve`, `/handoff`) — verified this revision. It gains an explicit statement: **in the S2 era `/approve` performs a label swap and does not authorize autonomous selection**; the label it applies is applied by `github-actions[bot]`, which the selection gate excludes; the acts that do authorize are §2.7.1's. |
| `.github/workflows/label-swap.yml:75` | The `/approve` confirmation body currently reads `"✅ /approve — needs-human → needs-ai (authorized by @${COMMENTER})."` It must stop claiming authorization and must name the act that does authorize — e.g. *"`needs-human` → `needs-ai`, requested by @${COMMENTER}. This label swap does **not** authorize autonomous work: the selection gate reads the account that applied the label, and this one was applied by `github-actions[bot]`. To authorize, apply the label or the target milestone from your own GitHub account (web/mobile/PAT). See docs/LABELS.md."* Exact wording is the coder's; the two facts it must carry are (a) this did not authorize anything and (b) here is what does. |

**Why `/approve` is NOT made to refuse outright until S3.** The architect explicitly left this to me within AM-6's constraint, so I rule it and give the reason. `/approve`'s label swap is load-bearing for things that have nothing to do with autonomous selection — it is the documented `needs-human` → `needs-ai` triage transition, it removes a **hard merge block** (`merge_authority.py`'s `_HUMAN_GATE_LABELS`), and it is referenced by the runbook's intervention procedure. Making it refuse would break three working mechanisms to fix a misleading sentence. **Fix the sentence.** The command keeps doing its real job and stops claiming one it never had.

**What S3 does about it (AM-6 point 4, stated now so it is not redesigned from scratch):** S3's gate accepts, in addition to the event sources, **a comment whose GitHub-reported author is a verified human CODEOWNER and whose first line begins with the approval command**, anchored the same way `label-swap.yml` already anchors it (first word of the first line). The comment *body* stays untrusted content — only the anchored command token and the API-reported author are read, and nothing in the body may influence the outcome. This costs one additional API call per untrusted candidate, on the path the ADR's cost note already accepts as non-free. The attack to watch, and the one the panel should press on: an implementation that reads "the gate reads comments" and forgets the anchoring on the *GitHub-reported author*, which would let an issue's own body claim its approval.

### 2.7.3 The cutover set: bounded by the gate's own query, no grandfathering (AM-3)

**A grandfathering list is forbidden.** It is two violations at once: a static list of pre-approved issues is a trusted-set widening (AD-13) *and* a cached eligibility determination (AD-4/FR7 — an authorization verified at time T is re-verified at T+n; an approval recorded earlier is evidence to re-check, not a stored grant). Revision 1 argued against it; AM-3 makes it a rule.

**The cutover set is not 46 issues.** It is bounded by the gate's own query, because an issue that is closed, milestone-less, in a non-target milestone, or without the dispatch label costs nothing at cutover — it costs one human act at the moment it would otherwise have been selected, which is the same act the human already performs implicitly when they decide it is next. The set is therefore **the open, dispatch-labelled, non-PR issues in the active milestone**, which is exactly `--milestone <n>&labels=needs-ai&state=open` minus `EXCLUDED_LABELS` minus PR records. Any framing of this as "46 issues on day one" overstates it, and revision 1's §8/E-1 did overstate it.

Two ways to produce the number, and they should agree:

| Purpose | Command | Notes |
|---|---|---|
| The human's own enumeration, before S2 merges | `bash bootstrap/query_issues.sh --app human --list --milestone "v0.7.0" --label needs-ai --state open` | Existing canonical entry point; filters `.pull_request == null` already; **prefix-matches the milestone title** (`:55-57`, `:160-169`). The prefix match is fine *here* — it is an enumeration tool for a human, resolving to one milestone and failing closed on ambiguity — and is exactly what the gate must not do (§1.4). |
| The authoritative answer, after S2 merges | The gate's own `ALL-CANDIDATES-GATED` lines (§2.3 Step F) | The only listing that cannot drift from the gate, because it *is* the gate. This is the minimal form of AD-11's held-request listing, pulled forward by AM-13 because the cutover is when it matters most. |

**The drain is per-issue and lazy by construction** — nothing needs doing ahead of time for an issue nobody is about to build. Whether to do a one-time pass over the active-milestone set immediately before S2 merges, or to let it drain lazily, is the human's and is folded into ESC-6 item 2 (§3(b) H1), not a new escalation. Both are safe; they differ only in whether the worker idles for a cycle or two. The architect's recommendation is the single pass, with AM-13's visibility as the backstop if it is not done.

**Before that choice can be made, §2.7.4 must be read** — because it changes what "one human act per issue" costs.

### 2.7.4 The already-applied-signal problem — new in revision 2, escalated as §8/E-5

AM-1's valve is that the human applies the dispatch label **or** the target milestone from their own account, producing a fresh `labeled` or `milestoned` event whose actor is a verified human CODEOWNER. On a *new* issue that works, and #1643 is the proof.

**On every issue in the cutover set it does not, and the reason is structural.** The cutover set is *by definition* the set of issues that **already carry the dispatch label and are already in the target milestone** — that is what the gate queries. GitHub's label and milestone writes are idempotent: applying a label an issue already carries produces no new `labeled` event, and re-setting the milestone it is already in produces no new `milestoned` event. So for every issue in the cutover set, **both qualifying signals are already present and neither can be freshly applied.** There is no additive act available. The web UI will not even offer the label as addable — it offers removal.

The human's actual options, none of which is the documented one:

| Route | Acts | Works in S2? | Notes |
|---|---|---|---|
| Remove `needs-ai`, then re-add it, from their own account | 2 | **Yes** | Produces `unlabeled` (human) then `labeled` (human). S2 ignores reversal events, so the fresh `labeled` authorizes. It also survives AM-8's S3 clearing rule, which re-establishes on "a fresh qualifying event by a verified human CODEOWNER" — which this is. |
| Remove the milestone, then re-apply it | 2 | **Yes**, same shape | Riskier: the issue leaves the milestone-scoped query between the two acts, and `bin/hos-cron`'s Step 0 triage sweeps milestone-less issues (`:1022`), so a bot may re-milestone it first — after which the human's act is again unavailable. Prefer the label route. |
| Comment `/approve` | 1 | **No** — §2.7.2 | And it makes things worse where it fires: it applies `needs-ai` as `github-actions[bot]`, consuming the additive act the human still had. |
| `edit_issue.sh --app human` | 1 | **No** — §2.7.1 | Writes as `scottthurlow-claude[bot]`. |

So AM-3's "one human act per issue" is, for the entire cutover set, **two acts per issue, in an order that must not be interrupted**, and the act is "remove and re-add a label" — which reads to any observer like undoing and redoing nothing. That is not a reason to change the design; fail-closed is still fail-closed and the security property is untouched. It *is* a material correction to what the human is being asked to clear in ESC-6 item 2, and to the cutover recommendation in AM-3, so it goes back to the architect as **§8/E-5** rather than being absorbed here as an implementation detail.

**Binding on S2 regardless of how E-5 is ruled:** whatever cutover instructions are written for the human MUST describe the act that actually produces an authorizing event, verified against §0.6 gap 6 first. Writing "apply the `needs-ai` label" for an issue that already has it is precisely the class of instruction AM-1 forbids.

**S3 closes this**, and it is the strongest argument for AM-6 point 4's comment-reading: a `/approve` comment is a single act that *is* available on an already-labelled issue, because a comment's existence does not depend on the issue's current label state.

---

## 3. Fail-closed matrix

Every row is a test case (§6). "Gated" = the request is not a candidate; "exit 2" = no candidates at all this cycle.

| # | Failure mode | Component | Outcome | Rationale |
|---|---|---|---|---|
| F1 | `.github/CODEOWNERS` absent | gate Step B2 | **exit 2** `codeowners-empty` | No actor can ever authorize; running is pointless and silence is dangerous |
| F2 | CODEOWNERS present, only `org/team` patterns | gate Step B2 | **exit 2** `codeowners-empty` | Teams are not individual humans (AF-2) |
| F3 | CODEOWNERS unreadable (permission) | `codeowners_humans` raises → gate | **exit 2** `config-error` | Not `FileNotFoundError`; never degrade to "empty and carry on" |
| F4 | `machine-accounts.env` absent/unreadable | gate Step B1/B3 | **exit 2** `bot-accounts-empty` / `trusted-apps-empty` | House precedent: `require_human_approval.py` exits 2 on empty `BOT_ACCOUNTS` |
| F5 | `BOT_ACCOUNTS` env set to `""` | `load_bot_accounts` | file baseline used; **not** empty | Env may only *add* to the denylist (AD-13) |
| F6 | `trusted-requesters.txt` absent | `load_trusted_requesters` | empty roster; **exit 0**, gate runs | FR3: mechanism functions with CODEOWNERS + apps |
| F7 | roster present but unreadable | `load_trusted_requesters` raises | **exit 2** `roster-unreadable` | Only `FileNotFoundError` is benign |
| F8 | roster line malformed (missing who/when/why) | parser | line **skipped** + stderr diagnostic | A malformed roster grants nothing |
| F9 | roster lists a `[bot]` login | parser | entry **rejected** + diagnostic | Otherwise the roster is a route around AD-2 |
| F10 | `--milestone` non-numeric (incl. an unsubstituted `@@MILESTONE_NUMBER@@`) | Step A | **exit 2** | Never coerce a placeholder |
| F11 | `--repo` malformed | Step A | **exit 2** | — |
| F12 | list query: `gh` non-zero / non-JSON / not a list | Step C | **exit 2** `list-query-failed` | A failed query is "unknown", and unknown must not read as "empty and go" at the *gate* (`hos-cron`'s own gate still treats it as unknown for the cycle-skip decision) |
| F13 | events query: `gh` non-zero / unparseable | Step D5.3 | **exit 2** `events-query-failed:<n>` | A partial list can silently demote a `priority:critical` item |
| F14 | events pagination bound (10 pages) exhausted, no match | Step D5.3 | candidate **gated**, exit 0 | Not an error; fail-closed for that issue only |
| F15 | authorization-check cap reached | Step D5.1 | remaining untrusted **gated**, exit 0, WARN | A cap hit is not an error; exiting 2 would convert a cost control into a DoS |
| F16 | `issue.user` absent or `login` empty | `requester_verdict` | **gated** (`no-login`) | Never authorize an unidentified author |
| F17 | issue record has no `milestone` object | Step D5.2 | **gated** + WARN | Cannot bind FIND-1's check; never authorize blind |
| F18 | Author is a trusted app, title has no marker | `requester_verdict` | **gated** (`trusted-app-no-machine-filing-marker`) | AD-2 |
| F19 | Author is untrusted; `needs-ai` applied by the worker bot | Step D5.4 | **gated** | VF-3 — the self-authorization the gate exists to close |
| F20 | Author is untrusted; `needs-ai` applied by `scottthurlow-claude[bot]` | Step D5.4 | **gated** | AD-6: a bot approval never satisfies the gate, **including the human-proxy App** |
| F21 | Author is untrusted; CODEOWNER milestoned it to a *different* milestone | `verify_codeowner_actor` | **gated** | FIND-1 / AM-4 — the benign `Backlog` deferral case |
| F22 | A bot login appears in CODEOWNERS or the roster | `is_trusted_requester` step 3 | **gated** (`bot-in-human-category`) | Human categories stay human |
| F23 | A stranger titles their issue with a machine-filing marker | `requester_verdict` step 2 | **gated** (`not-in-trusted-set`) | The marker is never a trust source |
| F24 | `copilot[bot]` authors an issue | `is_trusted_requester` | **gated** | FR2(b) — a third-party reviewer is not an HOS role |
| F25 | `python3` missing / module import error | `bin/hos-cron` | `_gate_candidates_ok=0`, `_GATE_CANDIDATES=""` | Same shape as today's query failure |
| F26 | Cycle-context section absent entirely | worker Step 2 | falls back to the **same gated command** | FR22 / AD-3 — the fail-open context builder is untouched and no longer matters |
| **F27** | `verify_codeowner_actor` called with `expected_milestone_title` omitted or `None` | `verify_codeowner_actor` step 2 | **`milestoned` events ignored entirely**; only a `labeled` event can authorize | **AM-4's inverted default.** A forgotten argument yields a *stricter* result, never a vulnerable one. This row is the whole of AM-4 and is the single most important test in §6.1. |
| **F28** | CODEOWNER milestoned it to a title differing only in case, whitespace, or an em dash vs. hyphen | `verify_codeowner_actor` step 2 | **gated** | Byte-for-byte equality. No normalisation, no prefix match — this repo's milestone titles make prefix matching dangerously loose (§1.4). |
| **F29** | The milestone is renamed after a CODEOWNER authorized under the old title | `verify_codeowner_actor` step 2 | **gated** until a human re-acts | **R-7.** Fail-closed, availability cost only, and the accepted price of F28. |
| **F30** | Every in-milestone candidate is gated (`eligible==0`, `gated>0`) | gate Step F → `bin/hos-cron` §2.4 | **exit 0, empty list, plus a distinct `ALL-CANDIDATES-GATED` stderr block and one `$LOG_PREFIX` cycle-log line** | **AM-13.** Behaviourally identical to an empty milestone — deliberately — so visibility is the *only* thing distinguishing the repo's most likely operational failure from a quiet week. Never an exit code, never an issue. |

---

## 4. Migration plan

### 4.1 `scripts/automation/lib/next_candidates.jq` — deleted, not wrapped

AD-3 permits "internal detail of the entry point **or** absorbed into it". **Absorb and delete.** Keeping it as a `jq -f` subprocess would put a `jq` runtime dependency on the live selection path; `tests/automation/test_next_candidates.py` already skips itself when `jq` is absent, so a `jq`-less machine would run the gate untested. Python is already a hard dependency of this path.

### 4.2 `tests/automation/test_next_candidates.py` — split, then deleted

AD-3 predicts the lock-step test "becomes vacuous". Half of it does; half of it becomes *more* load-bearing and must not be lost in the deletion.

| Existing test | Disposition |
|---|---|
| `TestPriorityOrdering::test_high_beats_low_across_number_inversion` | **Port 1:1** to `tests/framework/test_select_work_candidates.py`, same fixture, same assertion |
| `…::test_full_priority_ladder` | Port 1:1 |
| `…::test_tie_break_is_lowest_number_within_band` | Port 1:1 |
| `…::test_no_priority_label_defaults_to_low` | Port 1:1 |
| `…::test_default_low_label_rendered_as_low` | Port 1:1 — **including the exact expected line** `#894 [low] issue 894`, which is the output-format contract |
| `TestEligibilityFilter::test_needs_human_is_excluded` | Port 1:1 |
| `…::test_empty_input_yields_no_lines` | Port 1:1 |
| `…::test_all_blocked_yields_no_lines` | Port 1:1 |
| `…::test_missing_or_null_labels_does_not_crash` | Port 1:1 |
| `TestBothSelectionPathsAgree::test_filter_file_exists` | **Inverted** → `test_next_candidates_jq_is_gone` |
| `…::test_hos_cron_uses_canonical_filter` | **Replaced** → `test_hos_cron_invokes_the_entry_point` + `test_hos_cron_has_no_inline_jq_selection` |
| `…::test_cron_prompt_fallback_uses_canonical_filter` | **Replaced** → `test_cron_prompt_invokes_the_entry_point` + `test_cron_prompt_has_no_gh_api_candidate_query` |
| `…::test_both_paths_share_query_params` | **Retired as genuinely vacuous** — the query parameters now exist in exactly one place (the entry point). This is the one test AD-3's "becomes vacuous" actually describes. |

Every ported case gets a **trusted author** in its fixture, so ordering is tested in isolation from trust. The file `tests/automation/test_next_candidates.py` is then deleted. Porting is line-for-line: a reviewer must be able to diff the two files and see nine identical fixtures.

### 4.3 Documentation and agent-definition updates (all protected surfaces)

| File | Change |
|---|---|
| `.claude/agents/worker.md:179` | "The ordering is implemented once in `scripts/automation/lib/next_candidates.jq`…" → names `scripts/framework/select_work_candidates.py` as the single entry point, and adds that eligibility is now author-trust-gated, not merely label-filtered |
| `.claude/agents/worker.md:271` | `next_candidates.jq` ranks `priority:critical` at rank 0 → same rename |
| `bin/hos-cron:1132`, `:1587` | comments naming `next_candidates.jq` |
| `docs/LABELS.md:11, :29, :30, :49` | the "hardcoded literal sites" inventory loses `next_candidates.jq` and gains `select_work_candidates.py`; the `needs-ai` and `needs-human` rows' control-flow columns are updated to say the exclusion and the query now live in the gate. **No new label is registered — AD-11 holds; S2 adds none.** |
| `docs/LABELS.md`, the `needs-ai` row | **AM-6 point 3, a shipping condition (§2.7.2).** The row already lists `label-swap.yml` (`/approve`, `/handoff`) as a writer. It must state that **in the S2 era `/approve` performs a label swap and does not authorize autonomous selection**, that the label it applies is applied by `github-actions[bot]` (which the gate excludes), and what does authorize (§2.7.1). Also worth recording in the same edit, because it is the sharpest consequence: `/approve` **consumes** the human's additive act (§2.7.4). |
| `.github/workflows/label-swap.yml:75` | **AM-6 point 3 — the live artefact.** The `/approve` confirmation body must stop saying "authorized by @X" and must name the act that authorizes. Wording in §2.7.2. The command is **not** made to refuse; the reason is given there. **This is a fifth protected surface — see §2.1 and §8/E-6.** |
| `SCRIPTS-INDEX.md` | regenerate via `scripts/framework/regen_all.sh` |

### 4.4 Ordering and revertability

S1 and S2 are separate PRs in that order. **S1 is no longer describable as "behaviour-preserving for every existing caller"** — AM-4 changes `probe.py`'s milestone-strategy authorization semantics (a `milestoned` event now authorizes only on exact title equality, and a caller omitting the argument loses the milestone channel entirely), and consumer deployments inherit that. The honest statement: S1's live effects are `probe.py`'s stricter `bot_accounts` default (DEV-3, strictly stricter), AM-4's milestone binding, and AM-5's pagination — all on a path with no production caller *in this repo*, but with real behaviour change for consumers running the milestone strategy. §7.3 routes the affected sign-offs accordingly. S2 is the larger behaviour change.

If S2 must be reverted, reverting it restores `next_candidates.jq` and both call sites, and leaves S1 in place harmlessly — so the revert is a single-PR revert, not an unwind. **Reverting S2 does not restore `/approve`'s pre-S2 meaning**, and should not: the `label-swap.yml` and `docs/LABELS.md` corrections (§2.7.2) describe a fact about `github-actions[bot]` that was always true and that AF-5 merely discovered. They are correct with or without the gate, and must survive a revert.

### 4.5 Sequencing against `ADR-1604` (AM-9, binding)

**S2 ships first.** It is the live-path fix for an open `priority:critical` (#1539) and the original ADR §3 makes it the lead slice; #1604 is `priority:high` and nothing in it is blocked by waiting — its other components (branch ownership, breaker rungs, the stuck-set query) are untouched by S2.

1. **`ADR-1604` AD-5's mechanism bullet is amended** (by the architect, in AM-9 — not by this document, which had no standing to do it): the queue exclusion is expressed **once**, as an entry in `select_work_candidates.py`'s `EXCLUDED_LABELS` named module constant. **No inlined twin** in `worker-cron-prompt.md` and **no lock-step divergence test**, because after S2 there is no second implementation to diverge from — which is the whole point of AD-3. AD-5's **semantics are unchanged and still binding**: one narrow marker, authoritative for both the count and the exclusion; the generic human-attention label stays advisory and is never counted. Only the *exclusion* half lands in the gate (§2.2).
2. **Orphaned sign-offs, to be re-reviewed before #1604 is built:** `TECHNICAL-DESIGN-1604` §4.6 (Component H), its §4.7 component-table row for Component H, and its test row for `tests/automation/test_next_candidates.py`. All three were approved against a contract in which `next_candidates.jq` exists and is the single source of truth. The rest of `TECHNICAL-DESIGN-1604`'s sign-offs stand — the amendment touches the *location* of one exclusion, not the mechanism it implements.
3. **Whoever picks up #1604 next must carry the amendment into that document as the first step of the work**, not as a cleanup afterwards: re-point §4.6/§4.7/tests and note AD-5's amended bullet.
4. **The other admissible ordering, stated because it must not be improvised at the time.** If #1604 somehow reaches build before S2 merges, it ships against `next_candidates.jq` unchanged and **S2 absorbs the two exclusions during its deletion**. That ordering is permitted, is the only other admissible one, and **must be stated in whichever PR lands second** so a reviewer of the second PR is not left inferring which contract it was written against. What is *not* admissible under either ordering is both artefacts existing at once — that is the #1135 duplicate-implementation defect this design exists to remove.

---

## 5. Interface summary (the contract a coder implements against)

```
# scripts/framework/requester_trust.py  — protected surface; no imports from
# scripts/automation/** or scripts/oversight/**

codeowners_humans(repo_root: str = ".") -> set[str]
load_trusted_apps(repo_root: str = ".") -> set[str]
load_bot_accounts(repo_root: str = ".") -> set[str]
load_trusted_requesters(repo_root: str = ".") -> set[str]
load_trusted_set(repo_root: str = ".") -> TrustedSet

is_trusted_requester(login: str, user_type: str, trusted_set: TrustedSet) -> tuple[bool, str]
machine_filing_marker(title: str) -> MachineFilingMarker | None
requester_verdict(record: Mapping[str, Any], trusted_set: TrustedSet) -> RequesterVerdict

verify_codeowner_actor(
    events: Any,
    codeowners_humans: set[str],
    bot_accounts: set[str],
    label_name: str,
    expected_milestone_title: str | None = None,   # None == IGNORE milestoned events
) -> str | None                                     # (AM-4) — never "accept any milestone"

MACHINE_FILING_MARKERS: tuple[MachineFilingMarker, ...]
    # closed against sub-issue filing (AM-10 / D-7); entries are removed, never
    # relaxed, when an emitting site becomes LLM-composed (D-6 trigger 2)
EXCLUDED_LABELS is NOT here — it belongs to the gate (selection policy, not trust),
    and is the single bound landing site for ADR-1604 AD-5's exclusions (AM-9, §4.5)
```

```
# scripts/framework/select_work_candidates.py — protected surface; CLI entry point
# exit 0 = complete determination; exit 2 = fail closed, stdout empty
```

**Boundaries each component must honour:**

- `requester_trust.py` performs **no** network I/O and reads **no** environment variable except `BOT_ACCOUNTS` (union-only). It never reads an issue body. It never reads a label.
- `select_work_candidates.py` is the **only** module that may decide a work candidate is eligible. It never writes to GitHub — no labels, no comments, no state. It is a read-only decision.
- Neither may cache an eligibility determination (FR7/AD-4). There is no state file, no memo, no TTL. Every cycle re-derives from live state.
- Neither imports `scripts/automation/lib/codeowners.py` or `scripts/oversight/codeowners.py`. AD-6's ruling stands: requester trust is about **people**, not paths, so no glob matcher is needed and the dangerous over-matching module stays uncalled. **Parser count is unchanged by S1/S2** (the two documented divergent parsers plus `label-swap.yml`'s inline `awk`); S1 adds none, and removing the `awk` is S3's business.

---

## 6. Test plan

New: `tests/framework/test_requester_trust.py`, `tests/framework/test_select_work_candidates.py`, `tests/framework/test_selection_call_sites.py`. Modified: `tests/automation/test_probe.py` — **no longer additive only** (AM-4: five existing tests must change; §6.4 names each with its required edit). Deleted: `tests/automation/test_next_candidates.py` (after §4.2's port).

**Three tests in this plan are binding by ruling rather than by my judgment, and a reviewer should treat a proposal to relax any of them as a proposal to reverse a ruling:** §6.1's `test_marker_table_literals_exist_in_emitting_files` and `test_issue_creation_site_count_is_pinned` (AM-7 — the enforcement arm of the declined separate-App structural change, and the detector for D-6's revisit triggers), and §6.2's `test_bounced_draft_pr_still_reaches_the_worker_and_blocks_the_skip` (AM-12 — the condition DEV-1's approval hangs on; if it cannot pass, DEV-1 is withdrawn rather than the skip logic adjusted). §6.3's `test_cron_prompt_fallback_is_sandbox_allowlistable` is a fourth, required by AM-11 as G11's acceptance mechanism.

### 6.1 `test_requester_trust.py` — the primitive

**Loaders**
- `test_codeowners_humans_parses_individual_owners` / `_skips_team_patterns` / `_empty_when_file_missing` — the three shipped cases, re-pointed at the shared function
- `test_codeowners_humans_ignores_the_path_field` — `/scripts/framework/ @ScottThurlow` yields `{"scottthurlow"}`, never the path token
- `test_codeowners_humans_lowercases_and_dedupes`
- `test_load_trusted_apps_returns_exactly_the_three_hos_roles`
- `test_load_trusted_apps_excludes_copilot` — `copilot[bot]` is never in the result
- `test_load_trusted_apps_does_not_execute_the_file` — a fixture containing `EVIL=$(touch sentinel)` leaves no sentinel
- `test_load_trusted_apps_missing_file_is_empty`
- `test_load_bot_accounts_env_unions_with_file_baseline`
- `test_load_bot_accounts_env_cannot_shrink_the_baseline` — `BOT_ACCOUNTS=""` and `BOT_ACCOUNTS="only-one"` both still yield the four file entries
- `test_roster_is_empty_by_default` — the shipped `trusted-requesters.txt` parses to `set()`
- `test_roster_accepts_a_well_formed_entry`
- `test_roster_rejects_entry_missing_provenance` (each of who / when / why, three cases)
- `test_roster_rejects_bot_login` (`[bot]` suffix, and a `BOT_ACCOUNTS` member with no suffix)
- `test_roster_missing_file_is_empty` / `test_roster_unreadable_raises`

**`is_trusted_requester`**
- `test_codeowner_is_trusted` / `test_roster_member_is_trusted` / `test_trusted_app_returns_trusted_app_reason`
- `test_arbitrary_public_user_is_untrusted` — the FR1 acceptance check: `type == "User"`, no `[bot]` suffix, on no roster → `(False, "not-in-trusted-set")`
- `test_copilot_bot_is_untrusted`
- `test_empty_login_is_untrusted`
- `test_bot_listed_in_codeowners_is_untrusted` — `("hos-worker-hos[bot]", "Bot")` with the login in `codeowners` → `(False, "bot-in-human-category")`
- `test_bot_listed_in_roster_is_untrusted`
- `test_matching_is_case_insensitive`
- `test_is_pure` — no filesystem, no network, no env read (monkeypatch `open`/`subprocess` to raise)

**Conformance (these are the rules that keep the next consumer right)**
- `test_no_production_use_of_not_is_bot_reviewer` — the literal `not is_bot_reviewer` appears nowhere under `scripts/` or `bin/`
- `test_is_trusted_requester_has_one_production_caller` — `is_trusted_requester(` appears in `scripts/`/`bin/` only inside `requester_trust.py`
- `test_no_second_codeowners_parser_in_framework` — the `.github/CODEOWNERS` literal appears in exactly one module under `scripts/framework/`; `probe.py` contains no `CODEOWNERS` literal after the refactor
- `test_requester_trust_imports_nothing_from_automation_or_oversight`

**Marker**
- `test_each_marker_matches_a_real_title_from_its_site` — seven cases, using the title strings the emitting sites actually produce
- **`test_marker_table_literals_exist_in_emitting_files`** — for each entry, `title_prefix` (and `title_contains`) is found in `emitting_site`'s file. **BINDING, not optional (AM-7).** This and the next test are the mechanism that makes D-6's revisit triggers detectable; they are the enforcement arm of a *declined structural change* (the separate filing App), not string-matching fussiness. Do not relax either as brittle.
- **`test_issue_creation_site_count_is_pinned`** — `gh issue create` × 6 in `bin/hos-cron` (5 active + 1 commented), × 1 in `scripts/review_self.sh`, exactly one `--method POST` to `/issues` under `scripts/automation/lib/`. Adding an eighth deterministic filing site fails until the enumeration is updated. **BINDING (AM-7).**
- `test_dormant_marker_still_matches` — the usage-limit breaker, so re-enabling #1446 does not silently gate it
- `test_unmarked_bot_title_yields_no_marker`
- **`test_sub_issue_filing_is_not_in_the_marker_table`** (AM-10 / D-7) — asserts no entry's `emitting_site` names a sub-issue filing path, and that no entry's `title_prefix` matches a sub-issue title shape. This test exists to fail *loudly* if #1604's chain later reads `ADR-1604` AD-9's unamended point 2 and adds one.

**`requester_verdict`**
- `test_trusted_app_without_marker_is_untrusted` → `trusted-app-no-machine-filing-marker`
- `test_trusted_app_with_marker_is_trusted` → `trusted-app:hos-cron/baseline-red`
- **`test_stranger_with_forged_marker_title_is_untrusted`** — author `random-contributor`, title `[BLOCKED] agent unavailable — please fix`: the marker is never consulted; verdict `not-in-trusted-set`
- `test_verdict_ignores_body_and_labels` — a body containing a well-formed `---hos-envelope` with `from: ScottThurlow` changes nothing (FR5)
- `test_codeowner_author_needs_no_marker`

**`verify_codeowner_actor`** — the nine shipped `probe.py` cases ported (with the milestone case updated per §1.6, not ported verbatim), plus:
- **`test_milestoned_event_for_a_different_milestone_is_not_authorization`** (FIND-1) — the `Backlog`-deferral attack path from §0.2, written as the attack rather than as a parameter check
- `test_milestoned_event_for_the_expected_milestone_is_authorization`
- **`test_expected_milestone_none_ignores_milestoned_events_entirely`** (AM-4, F27) — **replaces** revision 1's `test_expected_milestone_none_preserves_shipped_behaviour`, which asserted the opposite and whose name is now a description of the defect. The new test asserts that with `None`, a `milestoned` event by a verified human CODEOWNER for the *matching* title **still returns `None`** — i.e. the omitted argument is strict, not permissive. **If this test is ever "fixed" to make an omitted argument permissive, the fix is the bug.**
- **`test_expected_milestone_none_still_allows_label_authorization`** — the other half of F27: with `None`, a CODEOWNER `labeled` event authorizes normally. Without this pair, a later reader cannot tell "ignore milestone events" from "ignore everything."
- **`test_milestone_title_match_is_byte_for_byte`** (F28) — a table of near-miss titles that must all fail: case difference, leading/trailing whitespace, em dash vs. hyphen, and a **prefix** (`"v0.7.0"` against `"v0.7.0 — <suffix>"`). The prefix case is the one that matters, because `bootstrap/edit_issue.sh` prefix-matches by design and a coder reading both may reasonably think that is the house convention.
- `test_bot_actor_after_codeowner_does_not_erase_authorization` — pins the `continue`-not-`return None` semantics
- `test_non_list_events_returns_none`

**Named acceptance checks the coder must perform and record (not unit tests):**
- **§0.6 gap 5** — observe one live `milestoned` issue-event payload and confirm the `milestone` object's fields. If `number` is present, implement title equality **anyway** as AM-4 binds it, and raise the discrepancy to `technical-design`; do not substitute number equality on your own judgment.
- **§0.6 gap 6** — confirm that adding an already-present label produces no new `labeled` event. §8/E-5 turns on it and it is a one-command check.
- **Amendment §0 gap 3** — confirm live that #1643's `needs-ai` label actor is `ScottThurlow`. The architect flagged this as the load-bearing ergonomic valve in AM-1 and asked that it be confirmed once before S2 merges rather than assumed from §2.6.

### 6.2 `test_select_work_candidates.py` — the gate

**Ordering parity** — the nine cases ported per §4.2, each with a trusted author.

**Trust and authorization** (each drives the CLI with a stubbed `gh`)
- **`test_untrusted_author_with_worker_applied_needs_ai_is_not_a_candidate`** — the core #1539 fix, VF-3's exact shape
- `test_untrusted_author_with_codeowner_applied_label_is_a_candidate`
- `test_untrusted_author_with_codeowner_applied_milestone_is_a_candidate`
- **`test_human_proxy_bot_authored_issue_is_gated_without_marker`** — author `scottthurlow-claude[bot]`, ordinary title: the #1539/#1340/#1356/#1540 shape from §2.6
- **`test_human_proxy_bot_labelling_does_not_authorize`** — AD-6's named asymmetry: `scottthurlow-claude[bot]` applied `needs-ai` **and** the milestone on an untrusted-authored issue → still gated. This is the case the ADR says "must be tested as its own case."
- **`test_worker_self_labelled_worker_authored_issue_is_rejected`** — #1678's shape: author and both label/milestone actors are `hos-worker-hos[bot]`, title carries no marker → gated
- `test_codeowner_applied_label_releases_an_issue_the_bot_later_relabelled` — #1643's shape
- `test_baseline_repair_blocked_issue_is_selectable_with_zero_events_calls` — the one live machine-filing site: author `hos-worker-hos[bot]`, title `[BLOCKED] inner-loop tests failing on HumanOversightSystem — diagnose and fix`, `needs-ai`+`priority:critical`, milestone set → selectable, and the `gh` stub records exactly one API call
- `test_codeowner_authored_issue_costs_zero_extra_api_calls` — AD-3's cost claim, asserted rather than assumed
- `test_roster_listed_author_is_selectable`
- `test_copilot_bot_authored_issue_is_gated`
- `test_issue_body_claiming_codeowner_identity_is_gated` (FR5)
- **`test_pull_request_records_are_excluded`** (DEV-1)

**AM-12's binding condition on DEV-1 — the bounce loop must be proved intact, not assumed.** DEV-1 is approved *conditional on this test*, and the condition has teeth:

- **`test_bounced_draft_pr_still_reaches_the_worker_and_blocks_the_skip`** — a bounced draft PR carrying the dispatch label, with the candidate list **empty**, must (a) still be surfaced to the worker through `bin/hos-cron`'s PR path and (b) still prevent the `#1395` no-actionable-work early skip.

  I read that path this revision and it is satisfiable by construction, which the coder should know before writing the test: `_OPEN_PR_NUMS` is populated from `gh api repos/<slug>/pulls?state=open` (`bin/hos-cron:1049-1050`) — **a different endpoint from the issues query the gate replaces** — and the bounce detection at `:1085` reads that PR's own `draft` flag and labels (`:1078-1086`). The skip condition at `:1158` requires `-z "$_OPEN_PR_NUMS"` **independently of** `-z "$_GATE_CANDIDATES"`. So excluding `pull_request` records from the *issues* list cannot affect PR surfacing at all. The test pins that independence rather than discovering it.

  **If the test cannot be made to pass, DEV-1 is withdrawn and PR records stay in** — escalate to the architect. Do **not** adjust the skip logic to make it pass; that would be repairing the gate's blast radius by widening it.

**AM-13 visibility (F30) — the gate must be loud when it holds everything:**
- **`test_all_gated_emits_the_distinct_held_line`** — `eligible=0, gated>0` produces the `ALL-CANDIDATES-GATED` block on stderr, with the count, the reason tokens, and the issue numbers
- **`test_empty_milestone_does_not_emit_the_held_line`** — `eligible=0, gated=0` produces the summary line and **nothing else**. This is the test that gives the previous one its meaning: a token emitted in both cases distinguishes nothing.
- `test_held_line_issue_list_is_bounded` — more than 20 gated issues renders `(+k more)` rather than an unbounded line
- `test_all_gated_still_exits_zero` — the held condition is never an exit code and never an error
- `test_gate_never_creates_an_issue` — the `gh` stub records no `POST` to `/issues` under any input (AM-13 point 3; also FR-scope: §5's "never writes to GitHub")

**Fail-closed** — one test per row **F1–F30** of §3, each asserting the exit code, empty stdout where applicable, and the stderr reason token.

**Anti-knob (AD-13)**
- `test_parser_exposes_exactly_four_flags`
- `test_no_repo_root_flag` / `test_no_exclude_label_flag`
- `test_no_environment_variable_grants_trust` — a sweep setting `TRUSTED_REQUESTERS`, `HOS_TRUSTED_APPS`, `HOS_SKIP_GATE`, `BOT_ACCOUNTS=""`, `CODEOWNERS=…` never makes an untrusted record selectable
- `test_label_flag_cannot_widen_trust` — `--label anything` still gates an untrusted-authored record
- `test_max_authorization_checks_can_only_lower` — `--max-authorization-checks 10000` clamps to 25

**No caching (FR7/AD-4)**
- `test_two_consecutive_runs_both_query_live` — no state file is written and the second run makes the same API calls
- `test_authorization_revoked_between_runs_is_not_carried_over`

### 6.3 `test_selection_call_sites.py` — the collapse, **and G11's acceptance mechanism (AM-11: required, not optional)**

This file carries two jobs that revision 1 ran together without saying so. The first is the collapse itself — proving the second implementation is gone. The second is new in revision 2: **it is the mechanism by which `ADR-1542` G11's requirement is satisfied**, and AM-11 makes that mechanism *required*. G11 is superseded rather than merely overlapped (§2.5), which means S2 has taken on G11's acceptance condition; an intention about a prompt string, unpinned by a test, survives exactly until the next person needs a second milestone.

**The collapse**

- `test_next_candidates_jq_is_gone`
- `test_hos_cron_invokes_the_entry_point` / `test_hos_cron_has_no_inline_jq_selection` (no `--jq` on the candidates query, no `$(cat`)
- `test_cron_prompt_invokes_the_entry_point` / `test_cron_prompt_has_no_gh_api_candidate_query` (no `labels=needs-ai` `gh api`, no `--jq`, no `$(`)
- `test_cron_prompt_forbids_improvised_fallback` — the §2.5 "do NOT construct your own query" instruction is present verbatim
- `test_worker_agent_doc_does_not_cite_next_candidates_jq`
- `test_only_one_selection_entry_point_exists` — `select_work_candidates` is referenced from exactly the two call sites plus tests and docs

**G11's four conditions, as one test (AM-11, binding)**

- **`test_cron_prompt_fallback_is_sandbox_allowlistable`** — asserts of the *rendered* Step 2 fallback line, after `_build_prompt`'s `@@MILESTONE_NUMBER@@` substitution, that it contains **no command substitution** (`$(`, backtick), **no variable expansion** (`$`), **no inline `jq`** (`--jq`, `jq -f`, `jq '`), and **no backslash continuation** (a trailing `\`). Those are G11's four conditions verbatim from AM-11, written as four assertions with four distinct failure messages so a regression names which one broke. A single combined regex would report "the fallback is wrong" and leave the next reader to find out how.

  This is the one test in the plan whose *absence* would leave an accepted ADR item (G11) marked superseded by a change that does not actually satisfy it. Per `CLAUDE.md`'s sandbox section, an unallowlistable command on an unattended cycle is not prompted for — it is denied outright and silently skipped — so the failure this test prevents is invisible at runtime by construction.

**AM-6 point 3's shipping condition, as tests (`/approve` must stop claiming authorization)**

AM-6 point 3 is *"S2 MUST NOT ship while the repo tells a human that `/approve` authorizes work."* A shipping condition that lives only in prose is a shipping condition nobody can fail. Both artefacts are repo literals, so both belong in this file rather than in §6.2:

- **`test_labels_doc_states_approve_does_not_authorize`** — `docs/LABELS.md`'s `needs-ai` row (or an adjacent note it links) contains the statement that in the S2 era `/approve` performs a label swap and does **not** authorize autonomous selection (§4.3, §2.7.2).
- **`test_label_swap_confirmation_does_not_claim_authorization`** — `.github/workflows/label-swap.yml`'s `/approve` confirmation body no longer contains the literal `authorized by` (`:75`, re-read this revision). This is an *absence* assertion deliberately: the replacement wording is the coder's (§2.7.2 fixes the two facts it must carry, not the phrasing), so pinning the new string would be pinning a choice this document did not make, while pinning the old string's absence pins exactly the lie AM-6 forbids.
- **`test_label_swap_decline_path_is_unchanged`** — `:83`'s `/decline` sibling is untouched. S2's edit is one confirmation message, not a workflow rewrite, and this test says so mechanically.

### 6.4 `test_probe.py` — **no longer "additive only"** (AM-4)

**Revision 1's acceptance criterion — "all fifteen existing tests pass unmodified" — is WITHDRAWN**, and this section is where that shows up as work. §1.6 explains why: behaviour-preservation was the wrong goal, and it is what produced the unsafe default AM-4 removed. **A test that must change is the honest signal that behaviour changed.**

**Five existing tests must change; each is named in §1.6's table with its required edit.** Restated here as the test-plan obligation, because a PR that quietly rewrites test fixtures is exactly what this document exists to prevent:

| Test | Kind of change | Assertion changes? |
|---|---|---|
| `TestCodeownersActorVerification::test_verified_when_milestone_applied_by_codeowner_human` (`:476-483`) | Pass `expected_milestone_title` explicitly; extend `_milestoned_event()` (`:466`) to emit a real `milestone` object | **Yes** — this is the one test whose subject is the changed behaviour |
| `TestProbeRepoMilestone::test_returns_candidate_with_verified_codeowner_actor` (`:337`) | `_make_issue()` (`:41-46`) gains a `milestone` object | No — fixture only |
| `TestProbeRepoMilestone::test_calls_verify_codeowner_actor_not_verify_label_actor` (`:357`) | same | No — fixture only |
| `TestProbeRepoMilestone::test_url_format_correct` (`:377`) | same | No — fixture only |
| `TestProbeRepoMilestone::test_multiple_issues_all_returned` (`:418`) | same | No — fixture only |

The four `TestProbeRepoMilestone` rows are **not** named by AM-4; I found them this revision. They change because of the *retained* "a record with no `milestone` object is skipped" rule, not because of the inversion — the fixtures never carried a `milestone` object, so those records are dropped before `_verify_codeowner_actor` is reached and `mock_verify_codeowner.assert_called_once()` fails. Two things follow. First, revision 1's acceptance criterion was **already false** for those four, independently of any ruling; that is my defect and §1.6 records it as mine. Second, this widens the "tests must change" set beyond the subset the architect named, which is the objection carried as **§8/E-7** — applied regardless, and on record rather than worked around.

**The replacement acceptance criterion** (from §1.6, restated as a check a reviewer can run): every existing assertion either passes unmodified or is changed only in its fixture; every changed test is listed in the PR body with the sentence *"this test changed because the behaviour changed"*; and **any test whose assertion must *weaken* is a defect in the change, not in the test.** The same applies to any test asserting the exact `_run_gh` argument list, which changes when `--paginate` is added.

**Added tests:**
- `test_codeowners_humans_is_the_shared_function` — `probe._codeowners_humans is requester_trust.codeowners_humans`
- `test_verify_codeowner_actor_delegates_to_shared_predicate`
- `test_probe_passes_expected_milestone_title` — the milestone branch passes `issue["milestone"]["title"]`, never `None`
- **`test_probe_milestoned_event_for_a_different_title_does_not_authorize`** — FIND-1/AM-4 at `probe.py`'s own call site, not only at the gate's. This is the test that proves the *shipped* defect is closed in the module consumer deployments inherit, and it is the reason §7.3 routes `_verify_codeowner_actor`'s approvals to re-review rather than letting them stand.
- `test_probe_skips_issue_with_no_milestone_object` — retained behaviour (§1.6 row 4), and the rule §8/E-7 objects to. It is tested because it is binding, not because I agree with it.
- `test_probe_events_fetch_is_bounded_paginated` — the `--paginate` argument list and the 10-page bound (AM-5), including that the bound-hit path returns `None` rather than raising.

---

## 7. Recorded deviations, residuals, and the startup-gap analysis

### 7.1 Named deviations from current behaviour

- **DEV-1 — pull-request records are excluded. APPROVED by AM-12, conditional on one test.** The `issues` REST endpoint returns PRs (they share the number sequence, #1236). `next_candidates.jq` has no `select(.pull_request == null)`; `bootstrap/query_issues.sh --list` and `bin/hos-cron`'s milestone-less gate both do. Without the filter, a bounced worker PR (`needs-ai`, in-milestone, draft) would be run through the *issue* gate, found untrusted, and dropped for want of a CODEOWNER actor — a silent behaviour change either way. The architect's reason for approving is sharper than mine and is worth carrying: leaving PR records in would mean the *issue* gate silently adjudicates PR eligibility, which contradicts AD-14's scope boundary far more than filtering them does. **The condition has teeth:** §6.2's `test_bounced_draft_pr_still_reaches_the_worker_and_blocks_the_skip` must demonstrate that a bounced draft PR carrying the dispatch label is still surfaced through `bin/hos-cron`'s PR path (`:1085-1099`) and still prevents the `#1395` no-actionable-work early skip, **with the candidate list empty**. If that test cannot be made to pass, **DEV-1 is withdrawn and PR records stay in** — escalate to the architect. Do **not** adjust the skip logic to make it pass; that repairs the gate's blast radius by widening it.
- **DEV-2 — `2>/dev/null` removed from the `bin/hos-cron` candidates call. REQUIRED, not optional (AM-13 point 1).** Revision 1 filed this as "logging only", which was true and beside the point. It is no control-flow change *in the gate*, and it is the **carrier** for AM-13's `ALL-CANDIDATES-GATED` block (§2.3 Step F, §2.4): with `2>/dev/null` in place, the one signal distinguishing "every candidate is held for a human" from "the milestone is empty" is written to a stream nobody reads, and the most likely operational failure of this whole mechanism becomes invisible for as long as nobody looks. A fail-closed gate that says nothing is indistinguishable from an empty backlog.
- **DEV-3 — `probe.py`'s `bot_accounts` default becomes file-baseline ∪ env** instead of env-only. Strictly stricter; identical when the env is set, as it is in every current invocation.
- **OBS-1 — `probe.py` does not gain `requester_verdict`.** Its milestone strategy already requires a verified CODEOWNER actor for *every* issue, which is stricter than the gate's trusted-author fast path. Adding requester-trust there could only widen it. Consequence worth recording: in a consumer deployment, a worker-filed `[BLOCKED]` issue is **not** auto-selectable through `probe.py` — existing behaviour, unchanged here.
- **OBS-2 — `probe.py`'s milestone strategy applies no `needs-human` exclusion.** Unchanged by S1/S2, and the reason the marker table's non-live entries are not dead weight (§1.5.1(iii)).

### 7.2 Residuals accepted for S2

- **R-1 (ADR-named, required to be recorded).** An untrusted author can edit the issue title or body **after** a CODEOWNER authorizes it. S2's authorization binds to the issue, not to its content. **Closed by S3** (AD-5's digest binding). Strictly smaller than today's "no check at all."
- **R-2.** AD-4 accepts a CODEOWNER `labeled`/`milestoned` event from any point in the issue's history, including one that predates the content's current form. Same class as R-1; closed by S3's invariant 4 (approval newer than the assessment).
- **R-3 — ACCEPTED for S2 by AM-8, CLOSED in S3, and the closing rule is stated now so S3 does not redesign it.** A CODEOWNER `milestoned` event that was later reversed (`demilestoned`) and re-applied by a bot to the same milestone still authorizes — `unlabeled`/`demilestoned` events are ignored in S2. FIND-1's title match closes the *different-milestone* case but not reverse-and-re-apply. The architect's reason for not folding it into S2 is the availability risk, not the security judgment: with AM-4's title binding in place the surviving case requires the human to have genuinely placed the issue in the **work** milestone at some point — materially weaker than FIND-1, where the human's act meant the opposite — while honouring reversal events changes *when* authorization evaporates, and nobody has measured how often bots toggle labels and milestones in normal operation. Getting that wrong stalls all autonomous work behind a human re-click. **Binding for S3, verbatim from AM-8:**

  > Authorization from an event source is evaluated against the issue's **current** state of that signal: a `demilestoned` (for the matching title) or `unlabeled` (for the matching label) event **clears** any authorization derived from a prior matching event, regardless of which actor performed the reversal. Re-establishment requires a fresh qualifying event by a verified human CODEOWNER. A bot re-applying a signal a human once applied does not restore the human's authorization.

  S3 must **measure the availability impact** (how many live issues the rule would de-authorize on the day it ships) before enabling it, and report it in the PR body. One interaction worth recording now, because it is easy to miss when S3 is written: §2.7.4's cutover route — the human removes and re-adds the dispatch label from their own account — **survives this rule**, because the re-add is itself "a fresh qualifying event by a verified human CODEOWNER". The cutover work is not invalidated by S3.
- **R-4 — ACCEPTED by AM-7 with three named revisit triggers.** Marker forgery by an induced bot session (§1.5.2 D-4). Requires an LLM under a trusted App identity to reproduce a deterministic template byte-for-byte *and* apply the target milestone *and* apply the dispatch label — and on this repo exactly one machine-filing site can reach the candidate set at all (§1.5.1(iii)). Bounded, and strictly smaller than today's no-check-at-all. **Any one of D-6's three triggers reopens the separate-App question (§8/E-2) as a required decision, not an option**, and §6.1's `test_marker_table_literals_exist_in_emitting_files` and `test_issue_creation_site_count_is_pinned` are what make triggers 2 and 3 detectable rather than noticed-later. Those two tests are **binding** (AM-7): they are the enforcement arm of a declined structural change, and relaxing either as "brittle string tests" silently converts an accepted residual into an unbounded one.
- **R-5.** The 10-page (1000-event) pagination bound means an extraordinarily churned issue can never be authorized. Availability only, fails closed. **AM-5 adds the part that keeps it a residual rather than a permanent invisible stall:** hitting the bound MUST emit `WARN events-page-bound-reached issue=#<n>` to stderr (§1.4, §2.3 D5.3, F14). Without that line, R-5 lands on precisely this repo's most-relabelled — and therefore most important — issues, with no signal anywhere that it has.
- **R-6.** The 100-issue single-page list ceiling is preserved from today (documented at `bin/hos-cron:1885-1890`). A milestone with more than 100 open dispatch-labelled issues truncates silently. Unchanged, recorded, not fixed here.
- **R-7 — NEW, added by AM-4.** Renaming a milestone **de-authorizes every issue authorized under the old title** until a human re-acts. Fail-closed, and an availability cost only. It is the accepted price of byte-for-byte title equality (F28/F29), and the correct trade against prefix-matching, which this repo's own em-dashed, version-prefixed milestone titles would make dangerously loose — `bootstrap/edit_issue.sh:149-169` prefix-matches milestones **by design**, and the gate must not copy it (§1.4). Two consequences worth stating rather than discovering: the de-authorization is silent from the issue's point of view (it simply stops being selected), so a milestone rename during an active build week looks exactly like the gate holding everything — which is what AM-13's `ALL-CANDIDATES-GATED` line (F30) exists to disambiguate; and the human's re-act is subject to §2.7.4's already-applied-signal problem, because a renamed milestone's issues still carry the dispatch label.

**Recorded in the S2 work item (not discovered later).** The original ADR §3 carries a standing requirement that named residuals be written into the work item. **R-1** (ADR-named), **R-3** (AM-8: "recorded in the S2 work item alongside R-1") and **R-7** (AM-4: "to be recorded in the S2 work item") are the three under that requirement. R-2, R-4, R-5 and R-6 are recorded here and carried by this document; they are not separately required in the work item, and I have not padded the list to look thorough.

### 7.3 Startup-gap recovery and affected-sign-offs analysis

FIND-1 and FIND-2 are defects in code that shipped for #1539 (`abef062e`) and that S2 now depends on. Asking the required question — *should this have been settled before code was written against it?* — the answer is **yes**: #1539 went from human ruling to merged code with **no requirements and no technical-design stage**, so the contract `_verify_codeowner_actor` had to meet was never written down anywhere, and two defects (FIND-1 HIGH, FIND-2 LOW) plus one unstated impossibility (AF-5) were found by the first design document to look at it, five days later.

The architect reached the same conclusion independently in the amendment's §2 and **widened it**: the gap covers **AM-4, AM-6 and AM-10** — three instances of one class, an ADR asserting a mechanism without checking it against the mechanism's own constraints. AM-6's instance is the sharpest: AD-4 said "events **and comments**" and AD-6 assumed `/approve` was reusable as an authorization channel, and a five-minute read of `label-swap.yml`'s `env:` block — which AD-6 already cites for three other properties — would have caught it. AM-10's is a contradiction *inside one decision* (`ADR-1604` AD-9 points 1 and 2).

**One `startup-artifact-gap` issue covering AM-4 / AM-6 / AM-10 is required**, and it is **amendment §3(a) item A11 — a worker action, explicitly not a gate on the build.** Neither the architect nor I have filed it: the architect does not open issues from an architecture ruling, and this task is design-document-only. It is recorded here so that the absence of the issue is a visible omission rather than a silent one.

### Affected sign-offs — which stand, which are orphaned

Revision 1 got the second row of this table wrong, and the amendment's §2 corrected it. The correction is recorded as a correction, not smoothed into a fresh table.

| Prior sign-off | Disposition | Changed from revision 1? |
|---|---|---|
| `abef062e`'s approvals for `probe.py::_codeowners_humans` | **STAND.** Promotion is behaviour-identical and the three shipped assertions re-run against the new home (§6.1). | No |
| `abef062e`'s approvals for `probe.py::_verify_codeowner_actor` | **ORPHANED — RE-REVIEW REQUIRED by `code-reviewer` and `security-reviewer` when S1 lands.** | **Yes — this is the correction.** |
| `abef062e`'s `DECISIONS.md` claim that the fix "closes the self-authorization loophole" | **RE-REVIEW REQUIRED, and the entry needs a correction note when S1 lands.** It is an orphaned *claim*, not orphaned code: FIND-1 shows the shipped shape admits a human's benign `Backlog` triage as authorization for a different milestone, so the loophole was narrowed, not closed. The correction note is a **required element of the S1 change set**, not a nicety — a decision log that overstates what a security fix achieved is the artefact a later reader trusts instead of re-reading the code. | No (confirmed by the amendment) |
| `TECHNICAL-DESIGN-1604` Component H — §4.6, its §4.7 component-table row, and its test row for `tests/automation/test_next_candidates.py` | **ORPHANED — re-review before #1604 is built.** All three were approved against a contract in which `next_candidates.jq` exists and is the single source of truth; S2 deletes it. The **rest** of `TECHNICAL-DESIGN-1604`'s sign-offs stand — the amendment touches the *location* of one exclusion, not the mechanism it implements. §4.5 and §8/E-3 carry the sequencing. | No (confirmed; AM-9 adds that `ADR-1604` **AD-5's mechanism bullet is amended too**, which I had no standing to do) |
| `ADR-1542` §4.9 (G11) | **SUPERSEDED — sign-offs orphaned for that item only.** `ADR-1542`'s other slice-3 items (G10 identity assertion, G7 merged sweep, G4 release tier, the `check_pr_reviewed.sh`/`pr_readiness.py` retrofits) are untouched. §6.3's conformance test is the acceptance mechanism AM-11 requires. | No (confirmed) |
| **`ADR-1604` AD-9** | **AMENDED (point 2), by AM-10.** Nothing was built against it, so **no sign-off is orphaned** — but #1604's chain must consume the amended text, and D-7 plus §6.1's `test_sub_issue_filing_is_not_in_the_marker_table` are what make a later reader of the *unamended* point 2 fail loudly instead of quietly adding a table entry. | **New — the architect found this; it was not in revision 1's list.** |

**Why `_verify_codeowner_actor`'s approvals are orphaned, stated plainly because revision 1 argued the opposite.** Revision 1 recorded them as *"stand for what they approved — with `expected_milestone_title=None` the shipped behaviour is bit-for-bit preserved and the nine existing tests pass unmodified; the contract is extended, not changed."* **Both halves of that justification are withdrawn.** AM-4 inverts the default, so `None` now means "ignore `milestoned` events entirely" and the milestone path's behaviour **genuinely changes**; and §1.6/§6.4 show five existing tests must change, so "pass unmodified" was false on its own terms — for four of them independently of the ruling. Behaviour-preservation was the thing that made the old approvals transferable, and behaviour-preservation is exactly what the ruling removed. The approvals are therefore orphaned **for the milestone-authorization path**, and re-review is routed to `code-reviewer` and `security-reviewer` at S1.

**Reviewer independence note:** these are re-reviews of *shipped* code against an amended contract, not re-approvals of the same diff. The reviewer must read `probe.py`'s milestone strategy as it will exist after S1 — with the inverted default, the title binding, and the bounded pagination — and must not treat the `abef062e` approval as a starting point to be confirmed.

**The honest closing statement, corrected.** Revision 1 wrote *"the only behavioural change on an approved path is DEV-3 (strictly stricter)."* **That is no longer true.** AM-4 changes `probe.py`'s milestone-strategy authorization semantics on a path that shipped, was approved, and that **every consumer deployment inherits** — the change is strictly stricter in the direction that matters (a forgotten argument now gates rather than authorizes), but "stricter" is not "unchanged", and a consumer running the milestone strategy will see issues stop being selected. What remains true is the property the CORE contract actually requires: **no code approved against the superseded contract is left unaudited against the fix.** The one shipped path this amendment changes is routed to named re-reviewers in the table above, and §6.4 names the tests that will demonstrate the change rather than hide it.

---

## 8. Escalations

**Status of this section in revision 2.** E-1 … E-4 are **ruled and closed** by the amendment; they are kept, not deleted, because the reasoning in them is what the rulings bind and because a reviewer arriving at §8 from the amendment's cross-references must land on the ruling, not on the open question it replaced. Each now opens with its disposition. **E-5, E-6 and E-7 are new, open, and addressed to the architect** — they arise from applying the rulings, which is the only place they could have arisen.

| # | Disposition | Ruled by |
|---|---|---|
| E-1 | **CLOSED** — option C adopted, D as the ergonomic wrapper; A vacuous, B permanently forbidden; backfill bounded, no grandfathering | AM-1, AM-2, AM-3 (+ AM-6's correction) |
| E-2 | **CLOSED** — separate filing App declined now, R-4 accepted with three revisit triggers; R-3 accepted for S2, closed in S3 | AM-7, AM-8 |
| E-3 | **CLOSED** — S2 ships first; `ADR-1604` AD-5's mechanism bullet amended; Component H orphaned | AM-9 |
| E-4 | **CLOSED** — G11 superseded (not overlapped); DEV-1 approved with a binding added test | AM-11, AM-12 |
| **E-5** | **OPEN — to `architect`.** The already-applied-signal deadlock: no additive human act exists for the cutover set | — |
| **E-6** | **OPEN — to `architect`.** Protected-surface count rises four → five, changing what ESC-6 item H1 item 4 asks the human to clear | — |
| **E-7** | **OPEN — to `architect`, objection on record.** The retained "skip a milestone-less record" rule, now that AM-4's inversion makes `None` the safe option | — |

E-5 and E-6 are **not** blocking in the sense E-1 was — neither changes the shape of §1–§6, and the coder is already not cleared for other reasons. They are material corrections to **what the human is being asked to clear in ESC-6**, and ESC-6 is a gate, so they must reach the architect and through them the human *before* H1 is answered, not after. E-7 is an objection I have already complied with.

### E-1 — **RULED AND CLOSED by AM-1 and AM-2 (backfill by AM-3, option C's text corrected by AM-6).** Recorded in full because the subset argument below was adopted as binding reasoning and now governs more than this question.

> **Disposition.** Option **C ADOPTED**, with **D ADOPTED as the ergonomic wrapper**. Option **A REJECTED** as vacuous by the subset argument. Option **B REJECTED and permanently forbidden** — AD-13, as clarified by AM-2, now forecloses any creation-time flag, argument, body token or HTML marker that confers trust, under any identity, with any documented human-confirmation convention attached (see §1.5.2 **D-5**). The **backfill** is ruled by AM-3: **a grandfathering list is forbidden**, and the cutover set is bounded by the gate's own query rather than by the open backlog — see §2.7.3, and then §8/E-5, which is what that cutover actually costs. **AD-2 stands verbatim; nothing is widened.** The routing question I raised was answered rather than forwarded: see "the routing ruling" at the end of this entry.

**The tension, stated precisely.** ADR line ~163 says `scottthurlow-claude[bot]` "is a trusted *requester* under AD-1(b) and is explicitly **not** a valid *approver*." AD-2 then narrows category (b) to bot-authored issues that also carry an enumerated machine-filing marker. The human-proxy App is not a machine-filing site: per `CLAUDE.md`, its default path is *"file an issue for the autonomous worker to pick up"*, composed interactively by an LLM. Both statements are correct and together they gate it. Live counts: 46 of 100 open issues are `scottthurlow-claude[bot]`-authored, and four of the five current candidates are gated by this alone (§2.6).

**Why I cannot resolve it with a marker.** A marker is only meaningful when the set of call sites that can emit it is a **strict subset** of the set of call sites the identity can reach. For the worker/overseer Apps that holds: deterministic filings (class (i)) are a strict subset of all their filings (class (i)+(ii)). For the human-proxy App **every** filing is class (ii), so any marker `create_issue.sh --app human` stamps would appear on all of them and be **isomorphic to trusting the identity outright** — the laundering path AD-2 closes, under a new name. That is the analysis, not a preference.

**The options, as proposed and as ruled:**

| Option | What it does | Cost | **Ruling** |
|---|---|---|---|
| **A** — stamp a marker on `--app human` filings | Trusts all human-proxy filings | Vacuous narrowing; reopens AD-2's laundering path | **REJECTED.** Vacuous by the subset argument — it reopens the laundering path AD-2 closes, under a new name, **while every test passes**. |
| **B** — add a `--confirmed` flag to `create_issue.sh --app human` (the `submit_pr.sh --app human --confirmed` precedent) and mark only those | Narrows *within* the identity to filings the human authorized per-instance | The LLM types the flag, so it is a prose guarantee with extra steps — D53's failure class | **REJECTED AND FORBIDDEN (AM-2).** It is a command-line flag whose presence marks a request approved, which AD-13 already prohibits; AM-2 makes that explicit so it is not re-proposed each time the queue feels slow. **The `submit_pr.sh --confirmed` precedent does not transfer:** there the flag gates *a mutation the human is watching*, conferring no standing authority on any later autonomous decision; here it would confer autonomous-build authorization on a future cycle, read by a machine, with no human present at read time. See §1.5.2 **D-5**. |
| **C** — keep AD-2 exactly as written; close the live-path gap through **AD-4, not AD-1** | A human-proxy-filed issue is untrusted-*authored* and becomes selectable when `ScottThurlow` personally applies the dispatch label or the target milestone **from their own GitHub account**. Uses only mechanism the ADR already binds. | One human act per issue — but see E-5: for the cutover set it is **two** | **ADOPTED.** Adds no trust concept and widens nothing. |
| **D** — gate human-proxy filings and let the human-proxy session stop applying `needs-ai` itself, always ending a filing by telling the human the exact act required | C, plus an ergonomic path | Needs a `CLAUDE.md` human-proxy-section edit, a protected surface and a separate human decision | **ADOPTED as the ergonomic wrapper**, and it is *also* the correct hygiene fix independent of ergonomics: a human-proxy session applying `needs-ai` to its own filing is the same self-authorization shape as the worker's Step 0 (VF-3), one identity removed. It should stop regardless. Not pre-authorized here (AD-14), and deliberately **not** in S2's file list — §2.7.1. |

**Revision 1's option C and option D each contained one false clause, and AM-6/AF-5 removed both.** C said an issue becomes selectable when the human applies the label or milestone *"or comments `/approve`"*; D reduced the act to *"one comment"*. **Both are wrong.** `label-swap.yml` performs the `/approve` label edit under `GH_TOKEN: ${{ github.token }}`, so the resulting `labeled` event's actor is `github-actions[bot]`, excluded unconditionally by `is_bot_reviewer` layers 1 and 2. A CODEOWNER commenting `/approve` produces **no authorization** in S2. The correction and everything that follows from it are §2.6 and §2.7.2; the acts that *do* authorize are stated verbatim in §2.7.1. The table above has been rewritten accordingly rather than annotated, because a false approval path left visible in a table is the exact artefact AM-1 says is worse than no gate.

**The subset argument, now binding rather than my opinion.** The architect adopted it as binding reasoning and credited it to this document: *a marker is meaningful only when the set of call sites that can emit it is a strict subset of the set of call sites the identity can reach.* For the worker/overseer Apps that holds — deterministic filings (class (i)) are a strict subset of all their filings — so the marker carries information. For the human-proxy App **every** filing is class (ii), so the emitting set equals the reachable set and the predicate carries zero bits. It is not a preference; it is the definition of a vacuous predicate. It now governs D-5, D-6 and D-7 as well as this question.

**The routing ruling — the architect answered the question I asked rather than forwarding it, and the reasoning matters more than the answer.** I asked whether *"are human-proxy filings trustworthy?"* is a product/operations question that belongs with the human. The ruling: **in its raw form it is, but it is not load-bearing, so it does not need the human's answer to unblock this work** — because even a maximally favourable answer ("the human reads every filing before it is made") **has no sound mechanism to express it**. Expressing it requires either A (vacuous) or B (forbidden by AD-13). There is no third construction. The architecture question therefore collapses to a single admissible answer and was ruled, not routed. What **is** the human's is the *consequence*, and it was already on record as **ESC-6 item 2** — so E-1 opened no new escalation; the architect amended ESC-6 item 2's text instead of creating ESC-7. **AM-1 binds as the technical call and takes effect only once ESC-6 clears**, which was already true of every decision in the original ADR.

**The honest cost, carried forward so nobody is surprised.** This converts a frictionless path into a per-issue-act path, and the mechanism's most likely real-world defeat — named in the original ADR's own closing section — is a single overloaded CODEOWNER clicking through without reading. Architecture cannot prevent that. AM-3 bounds the volume; it does not remove the obligation. **And the volume was overstated in revision 1:** "~46 issues at cutover" was wrong. The cutover set is bounded by the gate's own query — open, dispatch-labelled, non-PR, in the active milestone — because everything else costs one act at the moment it would otherwise have been selected, which is the act the human already performs implicitly when they decide it is next. §2.7.3 states the bounded figure with the query that produces it.

**The backfill — ruled, not open.** Revision 1 asked for a ruling between a bulk relabel, a lazy drain, and a grandfathering list. **AM-3 forbids the grandfathering list outright**: a static list of pre-approved issues is two violations at once — a trusted-set widening (AD-13) *and* a cached eligibility determination (AD-4/FR7, where an authorization verified at time T must be re-verified at T+n and an earlier approval is evidence to re-check, never a stored grant). §2.7.3 implements the ruling. The remaining choice — one pass over the active-milestone set immediately before S2 merges, or a lazy per-issue drain — is **the human's**, folded into ESC-6 item 2, with AM-13's visibility as the backstop if the pass is not done. The architect recommends the single pass so the first post-merge cycle is not a silent no-work cycle. **§8/E-5 is a material correction to what that pass costs, and it is why E-5 exists.**

### E-2 — **RULED AND CLOSED by AM-7 (the separate App) and AM-8 (R-3).** The marker's anti-forgery ceiling.

> **Disposition.** The separate deterministic-filing App is **declined for now, as recommended** — R-4 becomes an accepted, recorded residual with **three binding revisit triggers**, any one of which reopens this as a *required decision, not an option*. **R-3 is accepted for S2 and closed in S3**, with the clearing rule stated now so S3 does not redesign it, and it **must be recorded in the S2 work item alongside R-1**.

Within one bot identity, **no in-band marker can be unforgeable against induction**: the inducing agent has the same write authority and can read the marker table out of the repo (§1.5.2 D-4). The only construction that is genuinely unforgeable is a **separate GitHub App identity used exclusively by deterministic filing code** (`bin/hos-cron`'s five `gh issue create` sites plus `self_review_source.py`), so that class (ii) prose filings *cannot* author under it. The architect confirmed the analysis and declined the build: it is structural (an App to provision, rotate and document in `machine-accounts.env` and `AGENT-IDENTITY.md` §7) and S2 is the live-path fix for an open `priority:critical`.

**The three revisit triggers are binding and are written into the design at §1.5.2 D-6**, with §6.1's `test_marker_table_literals_exist_in_emitting_files` and `test_issue_creation_site_count_is_pinned` as the mechanism that makes triggers 2 and 3 detectable rather than noticed-later. Those two tests are therefore **binding, not optional** — they are the enforcement arm of a *declined structural change*, and a reviewer tempted to relax either as "brittle string tests" is proposing to convert a bounded residual into an unbounded one without saying so.

**R-3 — ruled, and not as I framed it.** Revision 1 offered R-3 as "your call whether it belongs in S2 or a follow-up". **AM-8 chose neither of those framings:** it is accepted for S2 and **closed in S3 by a rule stated now**, which is stronger than "a scoped follow-up" because it removes the redesign. The reason for not folding it into S2 is availability, not a weaker security judgment: with AM-4's title binding in place the surviving case requires the human to have genuinely placed the issue in the *work* milestone at some point — materially weaker than FIND-1, where the human's act meant the opposite — while honouring reversal events changes *when* authorization evaporates, and nobody has measured how often bots toggle labels and milestones in normal operation. Getting that wrong stalls all autonomous work behind a human re-click, the failure mode AD-15 warns about. The rule, the S3 measurement obligation, and the interaction with §2.7.4's cutover route are in **§7.2 (R-3)**. **§7.2 now also carries the ADR §3 requirement that R-1, R-3 and R-7 be written into the S2 work item.**

**One thing the panel should press on, which neither the amendment nor I resolved:** AM-8's own confidence on this deferral is recorded as **MEDIUM**, explicitly because the availability frequency that determines the trade was not measurable from the architect's position. If the panel can measure it, the amendment invites the deferral to be revisited on evidence rather than on judgment. I am not re-litigating it; I am recording that it is the one ruling in the amendment that asked to be re-examined.

### E-3 — **RULED AND CLOSED by AM-9.** `ADR-1604` / `TECHNICAL-DESIGN-1604` Component H owns the file S2 deletes.

> **Disposition.** **S2 ships first**, as recommended. But the ruling went further than my recommendation in a way I had no standing to propose: **`ADR-1604` AD-5's *mechanism* bullet is amended** — the queue exclusion is expressed **once**, as an entry in `select_work_candidates.py`'s `EXCLUDED_LABELS` named module constant, with **no inlined twin and no lock-step divergence test**, because after S2 there is no second implementation to diverge from. AD-5's *semantics* (one narrow marker, authoritative for both the count and the exclusion; the generic human-attention label stays advisory and is never counted) are **unchanged and still binding**. Component H's sign-offs are **orphaned**. The full sequencing contract is **§4.5**; the sign-off dispositions are **§7.3**.

`ADR-1604` AD-5 and `TECHNICAL-DESIGN-1604-worker-self-split-isolation.md` §4.6 bind changes to `scripts/automation/lib/next_candidates.jq` (new `timeout-stuck` / `blocked` exclusions), to its inlined twin in `worker-cron-prompt.md`, and to `tests/automation/test_next_candidates.py` — including a `test_jq_label_literals_match_hos_labels` conformance test. S2 deletes all three artefacts. Neither design has shipped.

Three consequences now binding, all restated in §4.5 so the coder does not have to read §8 to build:

1. **Whoever picks up #1604 next must carry this amendment into that document as the *first step of the work*,** not as a cleanup afterwards: re-point §4.6, §4.7's Component H row and the `test_next_candidates.py` test row, and note AD-5's amended bullet.
2. **The other admissible ordering is stated in advance** rather than improvised: if #1604 somehow reaches build before S2 merges, it ships against `next_candidates.jq` unchanged and S2 absorbs the two exclusions during its deletion. That ordering is permitted, is the **only** other admissible one, and **must be stated in whichever PR lands second**. What is not admissible under either ordering is both artefacts existing at once — the #1135 duplicate-implementation defect this design exists to remove.
3. **`EXCLUDED_LABELS` is bound as the landing site.** My instinct to make it a named module constant rather than an inline tuple was adopted as the seam, which means it is now a contract surface: it lives in `select_work_candidates.py` (selection policy), **not** in `requester_trust.py` (trust) — see §5's explicit note — and #1604's entries are added to it rather than to a second list.

### E-4 — **RULED AND CLOSED by AM-11 (G11) and AM-12 (DEV-1).** Two smaller collisions, and one of them was larger than I filed it as.

> **Disposition.** **G11 is SUPERSEDED, not merely overlapped** — a stronger word than "should be marked superseded rather than built twice", and it comes with an **acceptance condition binding on S2**. **DEV-1 is APPROVED**, with a binding added test.

1. **`ADR-1542` §4.9 (G11) — superseded, with a condition S2 must *meet*, not merely intend.** G11 planned a sandbox-allowlistable wrapper around `next_candidates.jq` for the worker's Step 2 fallback (`REQUIREMENTS-1542` VF-7's specific complaint about `--jq "$(cat …)"` at `worker-cron-prompt.md:101`). S2's entry point **is** that wrapper, built for a different reason, and building G11 separately would produce the duplicate-gate defect (#1135) in its purest form: two wrappers over the same selection decision, one of them trust-gated. G11's line item in `ADR-1542`'s slice 3 is satisfied by S2's merge; its sign-offs are orphaned **for that item only**, and `ADR-1542`'s other slice-3 items are untouched (§7.3). **The condition:** the rendered fallback invocation MUST contain **no command substitution, no variable expansion, no inline `jq`, and no backslash continuation** — and **§6.3's conformance test is the required mechanism**, not an optional nicety (§2.5, §6.3). By taking G11's supersession, S2 has taken G11's acceptance obligation with it; an intention about a prompt string, unpinned by a test, survives exactly until the next person needs a second milestone.
2. **DEV-1 — approved, and the architect's reason is better than mine.** I filed the PR-record exclusion as a deviation I was recording rather than absorbing, offering to revert it. The ruling approved it on a ground I had not stated: leaving PR records in would mean the **issue** gate silently adjudicates **PR** eligibility, which contradicts AD-14's scope boundary far more than filtering them does. Both behaviours are a change; the filtered one is intentional, testable, and cheaper. **The condition:** §6.2's `test_bounced_draft_pr_still_reaches_the_worker_and_blocks_the_skip` must prove the bounce loop intact (§7.1 DEV-1). If it cannot be made to pass, **DEV-1 is withdrawn and PR records stay in — escalate back to the architect rather than adjusting the skip logic.** I read that path this revision and it is satisfiable by construction (`_OPEN_PR_NUMS` comes from a different endpoint, and the skip at `:1158` requires `-z "$_OPEN_PR_NUMS"` independently); the test pins the independence rather than discovering it.

---

### E-5 — **OPEN. To `architect`.** The already-applied-signal deadlock: for every issue in the cutover set, **no additive human act exists**, so AM-3's "one human act per issue" is in fact two acts, and the documented act is not one of them.

**What this is not.** It is not a request to reopen AM-1, and it is not a security finding. Every verdict in §2.6 stands, fail-closed is still fail-closed, and nothing in §1–§6 changes whichever way this is ruled. It is a correction to **what the human is being asked to do**, on the one point AM-1 insisted must be exactly right: *a gate whose documented approval path silently does nothing is worse than no gate.*

**The deadlock, stated structurally rather than as an inconvenience.** AM-1's valve is that the human applies the dispatch label **or** the target milestone from their own account, producing a fresh `labeled` or `milestoned` event whose actor is a verified human CODEOWNER. On a **new** issue that works, and #1643 is live proof. But the cutover set is **by definition** the set of issues that *already carry the dispatch label and are already in the target milestone* — that is precisely what the gate queries (§2.3 Step C). GitHub's label and milestone writes are idempotent, so applying a label an issue already carries produces **no new `labeled` event**, and re-setting the milestone it is already in produces **no new `milestoned` event**. **For every issue in the cutover set, both qualifying signals are already present and neither can be freshly applied.** The web UI will not even offer the label as addable — it offers removal. §2.7.4 develops this with the full route table.

**The consequence for ESC-6 item 2, which is the part that must reach the human before H1 is answered.** AM-3's recommended single pass over the active-milestone set costs, per issue, **two acts in an order that must not be interrupted** — remove the dispatch label from the human's own account, then re-add it — and the act reads to any observer like undoing and redoing nothing. The milestone route is worse: the issue leaves the milestone-scoped query between the two acts, and `bin/hos-cron`'s Step 0 triage sweeps milestone-less issues (`:1022`), so a bot may re-milestone it first and consume the human's act. And `/approve` **actively makes it worse where it fires**: it applies `needs-ai` as `github-actions[bot]`, consuming the additive act the human still had on an issue that did not yet carry the label.

**The verification status, stated rather than asserted around.** §0.6 gap 6 records the underlying no-duplicate-`labeled`-event behaviour as **asserted from GitHub's documented idempotency, not observed**. It is a one-command live check and it is on §6.1's named-acceptance-check list for the coder. **If the assertion is wrong, E-5 dissolves entirely** and the cutover is as cheap as AM-3 describes. I have stated it as an assumption rather than folding it silently into the design precisely because the whole escalation turns on it — and because an escalation built on an unverified premise should say so in its first paragraph, not in a footnote.

**What I am asking for.** Not a redesign: a ruling on three things I do not have standing to decide.

1. **Does AM-3's cutover recommendation stand once the act is two-step?** A single pass over N issues at two acts each, with a "remove then re-add" shape, is a different proposition from N one-click acts — and it is the human's burden, so it is ESC-6 item 2's content, not mine to revise.
2. **Should the "remove and re-add the dispatch label" instruction be written into the cutover material at all**, given that it is indistinguishable at a glance from a no-op and will look, to anyone reviewing the issue's event log later, like churn? I can see an argument that the *milestone-less* route (remove the milestone, re-apply it) is more legible despite being riskier, and I do not think that is my call.
3. **Is this an argument for pulling AM-6 point 4's comment-reading forward from S3?** A `/approve` comment is a **single** act that *is* available on an already-labelled issue, because a comment's existence does not depend on the issue's current label state. I am **not** proposing it — AM-6 point 2 is explicit that S2 is event-only and that bolting comment-reading onto the critical-path fix is wrong, and I agree. I raise it because E-5 is the strongest argument for AM-6 point 4 that exists, and the architect should get to weigh it while ESC-6 is still open rather than after the cutover is done the hard way.

**Binding on S2 regardless of the ruling** (already recorded at §2.7.4): whatever cutover instructions are written for the human MUST describe the act that actually produces an authorizing event, verified against §0.6 gap 6 first. Writing *"apply the `needs-ai` label"* for an issue that already has it is exactly the class of instruction AM-1 forbids.

### E-6 — **OPEN. To `architect`.** S2's protected-surface count rises from **four to five**, which changes what §3(b) H1 item 4 asks the human to clear.

**The fifth surface is `.github/workflows/label-swap.yml` — i.e. `.github/workflows/**` — and it is not optional.** It is a direct consequence of **AM-6 point 3**, which is a *shipping condition*: **S2 MUST NOT ship while the repo tells a human that `/approve` authorizes work.** The live artefact that tells them so is the workflow's own confirmation body at `:75`, `"✅ /approve — needs-human → needs-ai (authorized by @${COMMENTER})."` — re-read this revision. `docs/LABELS.md` alone does not fix a lie told in the issue thread, so the condition cannot be honoured without editing the workflow. §2.1 lists it, §2.7.2 specifies what it must say and why the command is **not** made to refuse, §4.3 carries the edit, and §6.3 pins it with a test.

**Why this is an escalation and not a line item.** The amendment's §3(b) H1 item 4 asks the human to clear **"four protected surfaces ... (`scripts/framework/**`, `bin/`, `bootstrap/`, `.claude/agents/**`)"**, and the amendment's own BLAST RADIUS repeats "four protected surfaces, none pre-authorized here." That text is what the human will be shown. The count is now **five** — `.github/workflows/**` is a protected surface in `scripts/framework/protected_surfaces.txt` and generates a CODEOWNERS entry — so H1 item 4 as written understates what it is asking about, and it understates it in the direction of a *workflow file*, which is the surface class a reviewer is least likely to expect in a work-selection change. **A human-approval gate whose enumeration is quietly one short is a gate that was cleared for something other than what shipped.** I will not absorb it into a number the human has already been shown.

**What I am asking for.** An amended H1 item 4 naming five surfaces and the reason for the fifth, so the human clears the actual change set. No design change follows either way: if the architect would rather S2 not touch the workflow, then **AM-6 point 3 cannot be met by S2** and the honest consequence is that S2 does not ship until it can — which is itself a ruling I do not have standing to make.

**One related count, recorded so it is not later read as a sixth surprise.** Option D's `CLAUDE.md` human-proxy-section edit **would** be a sixth protected surface (`CLAUDE.md` is on the protected list). It is deliberately **not** in S2's file list (§2.7.1): it is a behaviour change to an interactive session, separable from the gate, and folding it into the critical-path fix would buy an ergonomic gain for a sixth human-gated merge. If the architect disagrees and wants D in S2, the count is six and H1 item 4 changes again.

### E-7 — **OPEN. To `architect`, as an objection on record.** The retained "skip a milestone-less record" rule, now that AM-4's inversion has made passing `None` the safe option.

**I have applied the rule. This is an objection, not a deviation.** §1.6 row 4, §2.3 D5.2 and F17 all implement "a record with no `milestone` object is skipped, never authorized", exactly as AM-4 retained it ("both correct, both retained").

**Why I think the retention deserves one more look.** The rule was *load-bearing* under revision 1's semantics: with `expected_milestone_title=None` meaning "accept any milestone", passing `None` for a milestone-less record would have been **vulnerable**, so skipping was the only safe option. **AM-4 inverted the default.** Under the inversion, `None` means "ignore `milestoned` events entirely", so passing `None` for a milestone-less record is now **the safe option by construction** — it evaluates the `labeled` channel only, which is precisely the channel a milestone-less record can legitimately be authorized through. The rule that was the safe choice is now the *strict* choice, and the justification that made it the safe choice no longer applies. I cannot tell from the amendment's text whether the retention is a deliberate defence-in-depth judgment made *after* the inversion, or a carry-forward of a bullet whose premise the inversion removed — and the difference matters, because one of those is a decision and the other is an artefact.

**The concrete cost, which is what moved me to record it.** §0.0.1 and §1.6 name it: `tests/automation/test_probe.py`'s `_make_issue()` (`:41-46`) emits only `number` and `labels` — **no `milestone` object** — so all four `TestProbeRepoMilestone` cases (`:337`, `:357`, `:377`, `:418`) have their records dropped by the skip rule before `_verify_codeowner_actor` is reached, and `mock_verify_codeowner.assert_called_once()` fails. **That widens AM-4's withdrawn acceptance criterion beyond the subset the architect named** — the amendment withdrew it for "any existing test that asserts a `milestoned` event authorizes", which is one test; the real figure is five. The four extra are fixture-only changes (§6.4), so the cost is small. I am recording it because the *reason* for it is a rule whose premise changed, and because a withdrawn acceptance criterion that keeps widening after the ruling is the kind of thing that should be visible at the time rather than reconstructed from a PR diff.

**The counter-argument, stated fairly because it may well be the right one.** A milestone-less record reaching the gate is an **invariant violation**, not a normal case: the gate queries `milestone=<n>` server-side, so every record it sees should carry a milestone object, and a record that does not means the response is not the shape the design assumes. Failing closed on an unexpected shape is the correct response to a violated invariant, independent of whether the alternative would also have been safe. If that is the reasoning, I withdraw the objection and would ask only that it be *stated*, so the next reader does not re-derive my version of it. (`probe.py`'s milestone strategy is in the same position for the same reason.)

**What I am asking for.** One sentence either way — "retained deliberately as fail-closed-on-invariant-violation" or "retained by carry-forward; `None` is now acceptable for milestone-less records". Nothing in §1–§6 moves on the first answer; on the second, §1.6 row 4, §2.3 D5.2, F17 and four test fixtures do, and I would rather change them on a ruling than leave the document carrying a rule I have argued against.

---

## 9. Attack surfaces for the dual-lens adversarial panel

**New in revision 2.** #1540 mandates the chain `pm-agent → architect → technical-design → dual-lens adversarial panel`, re-confirmed by the human on 2026-09-15. The panel runs **after** this revision and **before** `coder`. It is **not** satisfied by the amendment, by this document, or by ordinary review, and it is one of the three gates still outstanding (§0 preamble item 3).

This section exists so the panel does not start from scratch, and so those starting points are reachable as a numbered section rather than buried in a closing self-flag block. It is the **single** list: the "three places I would attack this document first" that revision 1 put at the end of the Human Review Required block are items **T1–T3** below, not a second set, and the closing block now points here rather than repeating them.

**Provenance is marked, because who found a surface is information about it.** `ADR` = the original ADR's own closing section; `TD` = this document; `AM` = the architect's amendment §3(c); `R2` = new in this revision.

| # | Surface | From |
|---|---|---|
| **A1** | **AD-2's marker enumeration.** Miss a site and a live path breaks; loosen it and the laundering path reopens. §1.5.1's search was exhaustive *as of today*; the panel should attack the search, not the table. | ADR |
| **A2** | **AD-8's unresolved assessor-dispatch seam.** S5, not S1/S2 — listed for completeness, and out of scope for a panel reviewing this document. | ADR |
| **A3** | **ESC-6 item 2 — one overloaded CODEOWNER approving without reading.** The mechanism's most likely real-world defeat, named by the ADR itself. Architecture cannot prevent it; AM-3 bounds the volume and E-5 corrects the per-issue cost. | ADR |
| **T1** | **The authorization-check cap's "carry on with a partial answer" branch** (§2.3 D5.1). The **only** place in the design where a limit does not produce exit 2. The partial answer is always a *subset* of the eligible set, and the reasoning that "a subset is always safe" is exactly the kind that turns out to have an exception. Look for the exception. | TD / AM |
| **T2** | **The marker table as a title-shape match against `printf` strings in a protected shell script** (§1.5.2). A single reworded `--title` in `bin/hos-cron` silently turns the baseline-repair loop off, with no failing test unless §6.1's literal-presence test is kept honest — and that test is now *binding* (AM-7), which raises the stakes on relaxing it rather than lowering them. | TD / AM |
| **T3** | **The assumption that `requester_verdict` is the only composition anyone will use** (§1.4). Enforced by a grep, and **a grep is weaker than a type.** §6.1's sole-caller conformance test is the whole control. | TD / AM |
| **A4** | **AM-4's inverted default.** Confirm `None` really does mean "ignore `milestoned` events" **everywhere**, including any consumer deployment's own callers of `probe.py` — not just the two production callers in this repo. F27 is the test; the attack is a caller F27 does not see. | AM |
| **A5** | **AM-6 generalised: look for any *other* place a workflow's or bot's write is read as a human's act.** `label-swap.yml` was not the only candidate — it was the first one checked. This is the highest-yield item in the list, because AF-5 was found by reading one `env:` block. | AM |
| **A6** | **AM-13's loud line.** A gate that holds everything and whispers is indistinguishable from an empty backlog. Attack the **visibility**, not just the logic: §2.4's `grep -q 'ALL-CANDIDATES-GATED'` on a temp file is a string match on a string this document chose. | AM |
| **A7** | **The cutover itself.** S2's merge is the moment this repo's autonomous work loop can stop dead. Ask what happens if the human is unavailable the week it merges — and read **§8/E-5** before answering, because the per-issue cost is two acts, not one. | AM |
| **R1** | **§0.6 gap 6 — the premise under E-5 is asserted, not observed.** GitHub's no-duplicate-`labeled`-event idempotency is taken from documentation. E-5 dissolves if it is wrong, and the cutover instructions written for the human are wrong if it is right and they say "apply the label". It is a one-command check and the panel is better placed to run it than I was. | R2 |
| **R2** | **§0.6 gap 5 — the `milestoned` event payload's shape is asserted, not observed.** AM-4 binds byte-for-byte `milestone.title` equality; the repo's own fixtures contain no `milestone` object at all (`test_probe.py:466`), so **nothing in this repo has ever exercised the field FIND-1 is about.** If the payload carries `number`, the design still binds title equality — attack whether that is right, not whether the coder will comply. | R2 |
| **R3** | **The five-protected-surface count (§8/E-6), and H1 item 4's stale "four".** A human-approval gate whose enumeration is one short was cleared for something other than what shipped. Check the count against `scripts/framework/protected_surfaces.txt` yourself rather than against any document. | R2 |
| **R4** | **`label-swap.yml`'s replacement confirmation wording (§2.7.2).** §6.3 pins the *absence* of `authorized by` and deliberately does not pin the new string. That is a hole by design — attack whether a replacement can be written that stops claiming authorization while still misleading, e.g. by implying the swap did something to the queue. | R2 |
| **R5** | **`/approve` is left working, not made to refuse (§2.7.2), and that was my call within AM-6's constraint, not the architect's.** My reason: refusing would break three working mechanisms (the documented triage transition, the `merge_authority.py` `_HUMAN_GATE_LABELS` merge-block removal, the runbook's intervention procedure) to fix a misleading sentence. If that trade is wrong, it is wrong in a place where the failure is a human believing they authorized work. | R2 |
| **R6** | **`EXCLUDED_LABELS` as a bound cross-ADR landing site (§4.5, AM-9).** Two designs now write to one constant in a protected file, with the divergence test that used to guard the seam **deleted** as part of the same change. Attack the window: what reviews the second design's entries, now that nothing mechanical compares two implementations? | R2 |
| **R7** | **The gate is a single point of failure for all autonomous work.** Every fail-closed row in §3 is a row in which the worker does nothing. Attack §3 as an availability surface rather than a security one — F1–F7 in particular, where a configuration file's absence stops the repo. | R2 |

**If the panel finds an item that is not on this list, that is the most useful thing it can return** — more useful than a deeper reading of any item here, because everything here has already been reasoned about by at least one of the three authors upstream of it.

---

## Human Review Required

**RISK: HIGH.** This document is the implementation contract for a control that decides whether autonomous work begins at all, on a public repository where §0 of the ADR confirms the current answer is *no check at all* on the live path. The specific ways it can fail while looking correct: (i) a consumer reading `is_trusted_requester` as an eligibility test and skipping `requester_verdict`, which would restore the full AD-2 laundering path while every test still passes — §6.1's sole-caller conformance test exists only because of this; (ii) `not is_bot_reviewer(...)` reappearing anywhere, which admits every anonymous member of the public; (iii) a `--repo-root` or `--exclude-label` flag being added later for testing convenience, either of which is a complete bypass through an ergonomics affordance; (iv) **AM-4's inverted default being read as a back-compat inconvenience and restored to "an omitted argument accepts any milestone" by a coder chasing green tests** — this is a *sharper* risk in revision 2 than the revision-1 version of it, because five existing `probe.py` tests must now change (§1.6, §6.4) and a coder who "fixes" §6.1's `test_expected_milestone_none_ignores_milestoned_events_entirely` instead of the fixtures re-admits a human's benign `Backlog` triage as authorization to build, with the test suite green; (v) the worker improvising a `gh api` fallback when the gate exits 2, which is why §2.5's prohibition is a tested prompt string and not advice; (vi) **AM-13's `ALL-CANDIDATES-GATED` block being dropped as logging polish**, after which a fully-gated queue is indistinguishable from an empty backlog for as long as nobody looks — which is why DEV-2 is recorded as required, not optional (§7.1). The gate is also, by construction, a **single point of failure for all autonomous work**: every fail-closed row in §3 is a row in which the worker does nothing.

**CONFIDENCE: HIGH** on §0.1, §1.5.1's enumeration, and §2 — each re-derived from the working tree, and the enumeration produced by an exhaustive search of every issue-creation mechanism (`create_issue.sh` callers, `gh issue create`, `--method POST` to `/issues`, workflows), not by extending the ADR's partial list. **HIGH** on FIND-1, traced end-to-end through the live selection path. **HIGH** on AF-5's consequences (§2.6, §2.7.2) — the architect's finding, re-read at `label-swap.yml:36, :75` this revision rather than taken on trust. **HIGH** on §8/E-6's surface count, checked against `protected_surfaces.txt` and the generated CODEOWNERS. **MEDIUM** on the authorization-check cap's value (25) and the pagination bound (10 pages) — defensible defaults, neither derived from measurement. **MEDIUM on §8/E-5**, and the reason is specific rather than general: the deadlock follows structurally from the cutover set's definition, but its load-bearing premise — GitHub emits no duplicate `labeled` event — is **asserted from documented idempotency, not observed** (§0.6 gap 6). If that is wrong, E-5 dissolves. **LOWER** on anything downstream of §0.6's declared gaps: I did not re-derive the live authorship counts (the amendment's §3 flags them as mine, unverified, and they size the human's H1 burden), and live GitHub repository settings remain uninspected (ESC-2 turns on them).

**BLAST RADIUS:** `bin/hos-cron`'s work-selection path and its actionable-work skip gate; `bootstrap/worker-cron-prompt.md` Step 2; `.claude/agents/worker.md`; `scripts/automation/lib/probe.py`'s **authorization semantics** and therefore every consumer deployment that inherits them (AM-4 — this is a behaviour change, not only a promotion; §4.4 and §7.3 state it); `docs/LABELS.md`; `.github/workflows/label-swap.yml`'s `/approve` confirmation; the deletion of `scripts/automation/lib/next_candidates.jq`, which two other accepted designs depend on; and two accepted designs amended by the ruling this revision applies — `ADR-1604` (AD-5, AD-9, Component H) and `ADR-1542` (G11). **Five protected surfaces: `scripts/framework/**`, `bin/`, `bootstrap/`, `.claude/agents/**`, and `.github/workflows/**`** — one more than revision 1 and one more than the amendment's §3(b) H1 item 4 states, which is **§8/E-6**. None is pre-authorized by this document. A sixth (`CLAUDE.md`, for option D) is deliberately excluded from S2 (§2.7.1).

**Change classification: STRUCTURAL.** This is the contract for a new decision point gating whether autonomous work begins, plus a new trust roster file, and it now also carries amended authorization semantics for shipped code. **Revision 2 changed no structural decision** — it applies rulings and records three new escalations — but the document it produces remains structural and is held accordingly.

**`coder` is NOT cleared to build S1 or S2.** Revision 2 does not soften this and completing A12 clears exactly one gate — its own. The current gate set, stated so nobody has to reconstruct it from §0:

| Gate | Status |
|---|---|
| §3(a) **A12** — this revision | **CLEARED by this document**, and by nothing else in it |
| **§8/E-1** — the blocking escalation revision 1 raised | **RULED AND CLOSED** (AM-1, AM-2, AM-3, with AM-6's correction). It is no longer a gate. |
| §3(b) **H1 — ESC-6**, the human's product-boundary clearance (4 items, each needing an explicit yes) | **OUTSTANDING — BLOCKING S1 and S2.** Item 4's protected-surface enumeration is now wrong by one (§8/E-6), and item 2's per-issue cost is now two acts, not one (§8/E-5). Both must reach the human *before* H1 is answered. |
| §3(b) **H3 — ESC-2**, whether GitHub collaborator permission counts as requester trust | **OUTSTANDING — BLOCKS S1 specifically**, because it decides whether AD-1 gains a fourth membership category. If the answer is the architect's recommended "no", S1 is unchanged and unblocked. |
| §3(c) — the **dual-lens adversarial panel** #1540 mandates | **OUTSTANDING — BLOCKING.** Runs after this revision and before `coder`. Not satisfied by the amendment, by this document, or by ordinary review. Its starting points are **§9**. |
| **§8/E-5, §8/E-6, §8/E-7** — new escalations to the architect | **OPEN.** E-5 and E-6 do not block the *build* independently — they are corrections to what ESC-6 asks the human to clear, and ESC-6 already blocks. E-7 is an objection I have complied with. |

**Nothing in this document authorizes a merge, a protected-surface edit, or a line of code.**

**Status: ESCALATED** — on **E-5**, **E-6** and **E-7**, to the architect. I did not resolve any of them and I did not route around any of them: E-5's deadlock is recorded with the act the human would actually have to perform rather than the act the ruling names; E-6's fifth protected surface is raised rather than absorbed into a count the human has already been shown; E-7's rule is **applied as ruled** with my objection on record beside it. Revision 1's `Status: ESCALATED` on E-1 is discharged — E-1 was ruled, and I applied the ruling rather than re-litigating it.

**Where to attack this document first: §9.** Revision 1 ended with three places; §9 now carries those three (T1–T3) together with the ADR's, the amendment's, and seven more found in this revision, as a numbered section the panel can be pointed at. They are not repeated here. **If the panel finds one that is not on that list, I would rather hear it there than after S2 merges.**
