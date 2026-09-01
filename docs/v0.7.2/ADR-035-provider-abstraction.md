# ADR-035 — Model-provider abstraction: slot-is-code / occupant-is-config, code-enforced cross-vendor credit

**Status:** Accepted — ratified by ScottThurlow 2026-08-31
**Epic:** #1476 · **ADR issue:** #1477 · **Milestone:** v0.7.2 — Model Provider Abstraction & Local Inference
**Supersedes:** ADR-034 **D-E** only. ADR-034's D-A, D-B, D-C, D-D, D-F (→V4) and D-G are inherited unchanged.
**Subsumes:** #63 escalation mechanism (becomes a binding field), `docs/COST-MANAGEMENT.md` §4 tiering table (becomes data), the #1455 fallback ladder (becomes the ordered candidate list).
**Design:** [`docs/specs/TECHNICAL-DESIGN-1476-provider-abstraction.md`](../specs/TECHNICAL-DESIGN-1476-provider-abstraction.md) (schema FROZEN)
**Author:** Architect · **Authored:** 2026-08-31 · **Ratified:** 2026-08-31

---

## 1. Context

Twelve files invoke a model CLI directly (`claude -p --model`, `agy -p`, `codex exec`); four more carry vendor/model knowledge without invoking. That is the **D41** failure class — the `codex --quiet` invalid invocation replicated across eight sites, each silently reporting "reviewed, no findings" when codex never ran.

Three facts shape every decision here:

1. **Cross-vendor identity is currently enforced by construction, not configuration.** `run_second_review.sh` calls `agy`/`codex` at hardcoded sites; `panel_logic.count_corroboration` counts distinct `reviewer` values stamped at those sites. No config attribute anywhere *grants* cross-vendor credit.
2. **`.claude/agents/*.md` `model:` frontmatter is read by the Claude Code harness**, which HOS does not control — `agent`-class model identity cannot be virtualised at runtime.
3. **HOS#985 precedent:** `.env` cross-vendor thresholds are read without executing the file and may only be **clamped downward** — config may make review more likely, never less.

## 2. Organizing principle (owner ruling, 2026-08-31)

> **"The slot is code; the occupant is config."** — with the goal that *"the orchestration of the SDLC be totally in code so that models can't take shortcuts,"* and the constraint that *"if invoked deterministically today, it needs to remain deterministic."*

| Owned by **code** | Owned by **config** (`config/models.yaml`) |
|---|---|
| Which slots exist; their fire-tiers | Which vendor/model occupies each seat (ordered candidate list) |
| The cross-vendor constraint | Which machine the inference host is |
| Fail-closed behavior; corroboration counting | — |
| Pipeline sequencing; capability class per slot | — |

This is the logical endpoint of a recorded direction — `COST-MANAGEMENT.md` §2 (orchestration out of agents, into cron/shell), D7 (cheap and deterministic first), D33 (deterministic re-derivation) — not a new departure. Model *selection* was the last place policy and identity were still tangled.

## 3. Decisions

### D-E′ — the seam (supersedes ADR-034 D-E)
`config/models.yaml` plus a single resolver and one runtime invocation helper per capability class is the **sole model-invocation authority** for all `completion`- and `embedding`-class calls. `agent`-class model identity is compiled from the same YAML at install (build-time) behind a fail-closed drift gate; runtime escalation overrides resolve through the same YAML. Deterministic built-ins (`ipcheck`) are not providers. The local lane's `local_model.py` is **one provider behind this interface**, not a second seam.

### D-H — cross-vendor credit is code-enforced, structurally
Cross-vendor-ness is a property of the **code-owned slot definition**, never a config field. Both config mechanisms considered — `counts_for_cross_vendor` (provider attribute) and `requires_cross_vendor` (per-binding boolean) — are **deleted**. A code-pinned `CROSS_VENDOR_ALLOWLIST = {google, openai}` (anthropic excluded: Opus authors, so no Claude model is an independent check — **D4**) has no config path to widen it. Validation **rejects at install and in CI** a roster seating a non-allowlisted vendor in *any* candidate position of a cross-vendor slot: config can only *fail to satisfy* the code constraint, never grant it. Runtime credit is computed from the **served** V4 provenance, never the declared primary — if a backup served a non-counting occupant, credit evaporates and the slot fails closed on the existing non-zero-exit path. This applies the HOS#985 one-directional clamp to occupancy and closes the **D49** hazard (config may never weaken the cross-vendor requirement).

### D-I — capability classes
Exactly `{agent, completion, embedding}`, each a **code** property of the slot. Cross-vendor is an **orthogonal independence constraint**, not a capability class — modelling it as a class was the enabling error behind the original defect, since an implementer would validate a shape field and believe the requirement met. Deterministic built-ins are not occupants and stay outside the registry (**D52**). Two slots **may** share a vendor under different lenses (the live HIGH roster is `agy:correctness, codex:security, codex:adversary`); independence is enforced at the corroboration layer against served provenance, where `count_corroboration` already collapses same-vendor-multi-lens to one. A cross-slot distinctness rule was proposed and **rejected** — no decorrelation value, and it would invalidate a working configuration.

### D-J — behavior-preserving refactor first
Landing #1 ships the registry with a default `config/models.yaml` reproducing **today's exact invocations** at all **12 direct sites** (byte-identical characterization bar) plus **4 knowledge-only sites** (resolved-knowledge-equals-today bar), plus build-time `agent` frontmatter generation. Of the 12, **7 are consumer-shipped and 5 (`framework/validate_*.sh`) are dev-pack-scoped** — and their *slot definitions* travel with the pack, with the orphan check scoped to the active configuration, so a consumer tree never orphans on tools it does not run. New capability lands separately. pm-agent and the architect reached this independently: unlike the local lane, the abstraction is **not** default-off, so a refactor of the invocation surface is itself a prime place to silently introduce an invalid invocation.

### D-K — subsumption
#63's escalation becomes an `escalation:` field reading the same roster (monotonic, never below the #895 floor); `COST-MANAGEMENT.md` §4 becomes data; the #1455 fallback ladder becomes the **ordered candidate list** (primary/backup is the two-element case).

### D-DET — determinism is preserved
The registry resolves **identity only**; it has no "should this fire?" entry point. Selection floors stay in code with a single source of truth (no second copy in a logic module). Discovery-driven winner variance — arriving with #1455 — is confined to **identity, never dispatch**, and is fully recorded in the provenance `selection` block: replayable, not opaque.

## 4. Scope boundary for landing #1

**Lands now:** the ordered-candidate schema, `select_candidate` as a pure function with a stable `discovered_facts`-accepting signature, and the provenance shape (`served_index` + `selection`).
**Deferred to #1455:** the live `GET /models` discovery client and the discovered-capacity constraint (dead code in this landing; its only live consumer is the gateway transport #1455 introduces).

Rationale: freezing the *shape* now avoids a second breaking refactor; shipping the unexercised discovery *engine* inside the consumer-critical refactor would contradict D-J's minimise-the-refactor basis.

## 5. Migration order

Per design §12: **characterization + D-DET tests before any reroute; the cross-vendor credit path before any occupant swap.** The dev-pack slot-scoping and the discovery deferral land in steps 1–2.

## 6. Consequences

- One implementation per backend; the D41 class becomes structurally impossible.
- Model selection becomes reviewable, validated data rather than prose spread across 16 files.
- A privacy consequence not originally articulated: code-enforced credit structurally prevents routing code to an uncredited local model while claiming external review.
- Cost: a config-validation gate must run at install and in CI, and two resolution paths (build-time for `agent`, runtime otherwise) must be maintained.

## 7. Gates cleared

| Gate | Verdict |
|---|---|
| pm-agent (product boundary) | PROCEED-WITH-CONDITIONS — economic condition closed (owner ruled power cost N/A) |
| Architect | APPROVE-WITH-CHANGES — bounded changes absorbed; A1 CRITICAL closed structurally |
| technical-design | Delivered; schema FROZEN; may proceed to a coder |
| privacy-reviewer | APPROVED — three implementation recommendations for #1455, none blocking |

**`startup-artifact-gap` annotated:** the abstraction arguably belonged in ADR-034, but **no code was built against D-E** — a decision for a path never built, so all prior sign-offs stand and nothing is orphaned.

## 8. Grounding paths

- `scripts/run_second_review.sh` — HOS#985 one-directional clamp (~67–97); cross-vendor fail-closed bands (~245–268); the duplicate-agy-call prose retry (~588–603)
- `scripts/oversight/panel_logic.py` — `count_corroboration`, the SPEC-376 seam
- `scripts/run_panel.sh` — roster construction (~369–385); `call_model` local `ipcheck` dispatch
- `docs/specs/TECHNICAL-DESIGN-63-model-escalation.md` — escalation must read the same roster
- `docs/COST-MANAGEMENT.md` §2, §4 — orchestration-in-shell; the tiering table that becomes data
- `DECISIONS.md` — D4, D7, D33, D41, D49, D52
