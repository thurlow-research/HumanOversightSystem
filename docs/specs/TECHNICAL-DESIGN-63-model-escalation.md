# Technical Design — #63: Risk-tier model escalation (Sonnet → Opus) for the review path

**Document type:** Technical design
**Status:** Proposed — awaiting architect + human approval (no code lands with this PR)
**Issue:** [#63](https://github.com/thurlow-research/HumanOversightSystem/issues/63) (human-approved direction, 2026-06-26)
**Related:** [#895](https://github.com/thurlow-research/HumanOversightSystem/issues/895) (static model split), `docs/COST-MANAGEMENT.md` §4 (model tiering), SPEC-332 (`compute_triage_floor`), DECISIONS.md D4 (cross-vendor independence)
**Author:** worker (autonomous)
**Date:** 2026-06-28

---

## 1. Scope and intent

Issue #63 asks whether reviewer agents should **escalate from Sonnet 4.6 to Opus
4.8 for a second opinion**. The human owner settled the direction in the
2026-06-26 comment: escalation is **risk-tier-triggered**, not "escalate when the
agent feels stuck."

This document specifies that mechanism. It is the *dynamic* complement to the
*static* per-agent model split decided in #895 and documented in
`docs/COST-MANAGEMENT.md` §4 (Opus 4.8 only for `architect` + `technical-design`;
every reviewer and the oversight layer on Sonnet 4.6).

**In scope:** a deterministic rule that selects Opus 4.8 for a fixed set of
review-path agents when the change is HIGH or CRITICAL tier, and a single
invocation-time mechanism to apply it without mutating agent definitions.

**Out of scope (explicitly):**
- Changing the static #895 split for the LOW/MEDIUM path — it stands unchanged.
- The cross-vendor panel (`scripts/run_panel.sh`) — that is a *separate*
  independence mechanism (D4/D5) using vendor CLIs (`agy`, `codex`), not the
  Claude `--agent` reviewers, and is not retiered here.
- "Second opinion when uncertain" heuristics — deliberately rejected by the owner
  in favor of a deterministic tier trigger.
- Any change to reviewer independence or the cross-vendor requirement at high risk
  (DECISIONS.md D4) — escalation only changes the *Claude tier*, never which
  vendors vote.

## 2. The escalation contract

### 2.1 Trigger

A review-path agent runs on **Opus 4.8** when the governing risk tier for the
change is **HIGH or CRITICAL**; otherwise it runs on its static default (Sonnet
4.6, per #895). Escalation is **monotonic**: it can only *upgrade* capability
(Sonnet → Opus). It never downgrades any agent below its #895 static floor.

### 2.2 Escalated agent set

Exactly these four agents escalate (the owner's list, all on the highest
cost-of-escaped-defect path):

| Agent | Why it escalates on HIGH/CRITICAL |
|---|---|
| `risk-assessor` | The independent tier re-derivation should get Opus scrutiny when the change is already high-risk. |
| `security-reviewer` | Highest cost-of-error; Opus on high-risk diffs. |
| `code-reviewer` | Gates the parallel reviewers; Opus's stronger bug-finding on high-risk diffs. |
| `oversight-evaluator` | The compliance/quality + anti-gaming gate, on Opus for high-risk steps. |

No other agent escalates. `architect` and `technical-design` are already Opus
(#895) and are unaffected. Authoring agents (`coder`, `worker`, `pm-agent`) and
the `overseer`/`oversight-orchestrator` are **not** in the escalation set under
this design; the overseer already provides an Opus-grade merge gate per the #895
direction, so a HIGH/CRITICAL change receives Opus twice — inner-loop reviewer
escalation here plus the outer-loop merge gate.

### 2.3 Which tier governs which agent (the chicken-and-egg resolution)

`risk-assessor` is the agent that *produces* the validated tier, so it cannot key
its own model off its own output. The two tier signals already in the system
resolve this cleanly:

- **`risk-assessor` keys off the deterministic triage floor** —
  `compute_triage_floor(changed_files, added_lines)` in
  `scripts/oversight/panel_logic.py` (SPEC-332). This floor is computed *before*
  any model review from changed-file paths + diff size, ratchets LOW→…→CRITICAL,
  and is available without a model call. Using it to escalate `risk-assessor`
  means the high-risk *re-derivation* runs on Opus.
- **`security-reviewer`, `code-reviewer`, `oversight-evaluator` key off the
  validated tier** — the tier `risk-assessor` emits after its (possibly
  Opus-grade) re-derivation, per the owner's note: "the risk tier is already
  computed by `risk-assessor` … that signal can drive the model selection for the
  downstream reviewers."

Effective governing tier per agent = `max(triage_floor, validated_tier)` where the
validated tier is available, and `triage_floor` alone for `risk-assessor`. Using
the max keeps escalation monotonic: a downstream reviewer never runs *below* the
capability the deterministic floor already justified, even if a model re-derivation
proposed a lower tier.

## 3. Mechanism

### 3.1 Constraint: agent definitions are not the lever

Agent `model:` frontmatter (`.claude/agents/*.md`) is **static** and HOS-managed —
the technical-design contract forbids editing other agents' definition files, and
frontmatter cannot express a conditional. The static frontmatter therefore stays
exactly as #895 set it (the Sonnet 4.6 **floor**); escalation is applied at
*invocation* by overriding the model.

The Claude CLI invocation that runs these agents (`claude --agent <name> …`) takes
a `--model` flag that overrides frontmatter for that run. Escalation is: when the
governing tier is HIGH/CRITICAL, invoke the agent with
`--model claude-opus-4-8`; otherwise invoke it with no override (frontmatter
Sonnet applies).

### 3.2 The resolver (the one new, testable unit)

A single pure function concentrates the policy so every invocation site asks one
authority instead of re-implementing the rule:

```
select_review_model(agent_name: str, governing_tier: str) -> str | None
    returns "claude-opus-4-8"  when agent_name ∈ ESCALATION_SET and
                                governing_tier ∈ {"HIGH", "CRITICAL"}
    returns None               otherwise   (caller omits --model → frontmatter default)
```

- **Home:** `scripts/oversight/model_escalation.py` (new), a sibling of
  `panel_logic.py`. Pure, no I/O, no model call — fully unit-testable, mirroring
  how SPEC-332 isolates `compute_triage_floor`.
- **`ESCALATION_SET`** = the four agents in §2.2, defined once as the single
  source of truth.
- **Unknown / malformed tier** → returns `None` (fail toward the Sonnet floor; the
  static #895 split is never breached, and the deterministic floor independently
  guarantees at least Sonnet-grade review). Cost, not safety, is what an absent
  signal risks — and the floor caps that.
- A tiny CLI shim (`python3 -m scripts.oversight.model_escalation <agent> <tier>`
  printing the model id or empty string) lets shell invokers and the
  human/cron-driven `claude --agent` callsites consume it without duplicating the
  table.

### 3.3 Integration points (where the resolver is consulted)

The reviewer agents are invoked from the human/overseer-driven oversight loop and
its cron orchestration (`claude --agent <name>`), not from a single shell
dispatcher today. Wiring is therefore a **follow-up implementation slice** (see
§6) that, at each callsite, computes the governing tier (§2.3) and passes
`--model "$(python3 -m scripts.oversight.model_escalation <agent> <tier>)"` when
non-empty. This document fixes the *contract*; the callsite edits are deferred so
the policy can be reviewed and tested in isolation first.

## 4. Properties this must preserve

1. **Monotonic capability (load-bearing).** Escalation only ever moves an agent
   Sonnet → Opus. No path produces a model weaker than the #895 static floor. A
   missing/garbled tier degrades to *cost-default* (Sonnet), never to *less than
   Sonnet*.
2. **Independence unchanged (D4).** The escalated agents are all Claude-tier
   reviewers. The cross-vendor requirement at high risk — independent
   `codex`/`agy` votes that Claude cannot substitute for — is untouched. Opus
   still never reviews its own authored output: these reviewers review the
   *coder's* output, and the author-Opus/reviewer rule (D4) is unaffected.
3. **Determinism.** Given `(agent_name, governing_tier)` the model is a pure
   function — reproducible, no time/RNG, no model call to decide a model.
4. **No new gate.** Escalation changes *which model* runs an existing reviewer;
   it adds no step, changes no exit code, and cannot convert a FAIL to a PASS.

## 5. Cost impact

Bounded by construction and consistent with `docs/COST-MANAGEMENT.md` §4–§5
(allocate review effort by risk tier):

- Only HIGH/CRITICAL changes escalate — the common LOW/MEDIUM path stays entirely
  on Sonnet.
- Only four agents escalate, not the whole panel.
- The trade is the explicit one in COST-MANAGEMENT.md §4: pay Opus precisely where
  an escaped defect is most expensive, rather than uniformly upgrading every agent.

## 6. Build order (follow-up implementation, separate PR)

1. `scripts/oversight/model_escalation.py` — the resolver + `ESCALATION_SET` + CLI
   shim. **Pure; ships with unit tests** (`tests/oversight/test_model_escalation.py`):
   each escalated agent × {HIGH, CRITICAL} → Opus; × {LOW, MEDIUM} → default;
   non-escalated agent at every tier → default; unknown agent/tier → default.
2. Governing-tier plumbing: expose `compute_triage_floor` and the validated tier to
   the invocation sites and compute `max(...)` per §2.3.
3. Callsite wiring: pass `--model` from the resolver at each `claude --agent`
   reviewer invocation in the oversight loop / cron orchestration.
4. Docs: flip `docs/COST-MANAGEMENT.md` §4 from "proposed" to "implemented" for the
   dynamic escalation row, and add the DECISIONS.md status update.

Steps 2–3 touch the oversight gate path and are **MEDIUM+ risk**, requiring the
full reviewer panel + human authorization. Step 1 is LOW (pure helper + tests).

## 7. Open questions for architect / human

1. **Governing-tier composition** — confirm `max(triage_floor, validated_tier)` is
   the desired rule (vs. validated tier alone) for the three downstream reviewers.
2. **Overseer in or out** — the #895 *direction* puts `overseer` on Opus at the
   merge gate already; this design leaves `overseer`/`oversight-orchestrator` out
   of the dynamic set to avoid double-specifying that. Confirm.
3. **Re-review on tier change** — if `risk-assessor` (now on Opus for high-risk)
   *raises* the tier mid-step, should already-completed Sonnet reviews for that
   step be re-run on Opus? Proposed default: yes for the step's blocking reviewers,
   consistent with the affected-sign-offs analysis in the technical-design contract.
