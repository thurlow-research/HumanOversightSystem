# Technical Design — #1476: Model-provider abstraction (behavior-preserving identity refactor)

**Milestone:** v0.7.2 — Model Provider Abstraction & Local Inference
**Epic:** [#1476](https://github.com/thurlow-research/HumanOversightSystem/issues/1476)
**ADR:** [#1477 — ADR-1477](https://github.com/thurlow-research/HumanOversightSystem/issues/1477) (supersedes ADR-034 D-E; defines D-E′, D-H, D-I, D-J, D-K)
**Inherits:** [#1456 — ADR-034](https://github.com/thurlow-research/HumanOversightSystem/issues/1456) D-A, D-B, D-C, D-D, D-F(→V4), D-G
**Binding rulings:** #1476 comment "Authoring-chain rulings — pm-agent + architect" (A1–A6, R-P*); **operator reframing 2026-08-31** (slot-is-code / occupant-is-config — §0; host fully config-described — §0.4; ordered candidate lists + code-owned deterministic selection — §3.5; gateway discovery-only boundary — §3.6)
**Related decisions:** `DECISIONS.md` D4, D7, D33, D41, D49, D52; `docs/COST-MANAGEMENT.md` §2; HOS#985 (`.env` one-directional clamp)
**Author:** technical-design · **Status:** **APPROVED-WITH-CHANGES (architect, 2026-08-31)** — bounded changes absorbed; schema FROZEN; may proceed to a coder. A1/A2 re-ratified under §0 (OQ-0 accepted).

---

## HOS self-flag (design authoring)

```
RISK: MEDIUM
CONFIDENCE: HIGH
BLAST RADIUS: The model-invocation surface of the entire repo (every reviewer, red-team,
  validator, and session-summary path). Correct default config = zero behavior change;
  a resolver bug breaks every model call at once (pm R-P5.2 — this is the consumer risk).
```

**Change class: `additive`.** This document translates the ratified structural rulings of
ADR-1477 (A1–A6) and pm's PROCEED-WITH-CONDITIONS into an implementable contract, re-expressed
under the operator's slot-is-code/occupant-is-config framing (§0). It originates no architecture
decision. The framing **narrows** the config's authority (config can express *less* than the
epic draft allowed), which is strictly safer. **The architect re-ratified A1/A2 under this
framing (OQ-0 accepted, §15) and approved the design with two bounded changes, now absorbed;
the schema is frozen and the design may proceed to a coder.**

### Human Review Required
- The A6 upward-fallback annotation escape is human-gated by design (§11). A human owns each use.
- The economic decision (power, shared-host maintenance, unattended-cron dependency) is out
  of scope and remains a human gate per ADR-1477 gate 2 / pm.
- The 8 open questions are **all resolved** by the architect (§15); no design-gate item remains
  open. Remaining human gates are the two above (operational), not design gates.

---

## 0. The central distinction — the slot is code, the occupant is config

This is the organizing principle of the whole design, per the operator's 2026-08-31
reframing:

> "We are moving toward the orchestration of the SDLC being **totally in code** so that
> models can't take shortcuts. The slot is code; the occupant is config."

**This is not a new departure — it is the logical endpoint of an already-recorded
direction:**

- `docs/COST-MANAGEMENT.md` §2 ("Move orchestration out of agents and into cron/shell":
  discovery, sync, filtering, and dispatch are done deterministically in the shell layer so
  "model attention goes to routing and judgment, not infrastructure").
- **D7** ("Pipeline ordering — cheap and deterministic first").
- **D33** (independent *deterministic re-derivation* of any determination that would loosen
  oversight — "the actor being governed cannot be the judge"). Letting config decide *when*
  a cross-vendor slot fires would be exactly the self-governing loosening D33 forbids.

The abstraction extends that ratchet to model identity: it moves *which model* out of
scattered shell literals into one config file, **without** moving any *decision* out of
code.

### 0.1 What stays in CODE (the policy / orchestration surface — config can never change it)

Code — the shell scripts, the pure logic modules, and the new registry loader — owns the
entire decision surface:

- **Which slots exist** — the panel has a correctness slot, an adversary slot, an
  arbiter/triage slot; the second review has a correctness slot and a security slot; etc.
- **How many fire at which risk tier** — correctness at MEDIUM+, security/adversary at
  HIGH+ (the `_AGY_TIERS`/`_CODEX_TIERS` floors, `compute_triage_floor`, the score
  thresholds and the HOS#985 `.env` clamp).
- **That cross-vendor slots must be filled by distinct, code-allowlisted, non-author
  external vendors** — the A1 constraint, now a property of the *slot*, not of any config
  entry (§5).
- **The fail-closed behavior when a slot cannot be filled** (the existing `exit 1` bands in
  `run_second_review.sh`).
- **The corroboration counting rule** (`count_corroboration` — distinct served vendors).
- **Sign-off requirements, gate semantics, pipeline sequencing, escalation monotonicity.**
- **Whether a call site invokes deterministically at all** (§6).

### 0.2 What is CONFIG (the occupancy surface — `config/models.yaml`)

`config/models.yaml` owns **only which vendor/model candidates may occupy each seat, in
preference order, and the identity/address of the host each candidate runs on.** Nothing
else. Swapping `gemini → codex` in a slot, reordering candidates, or pointing the inference
host at a different machine is a config edit; changing *when* that slot fires, whether it is
required at MEDIUM+, or *which candidate wins* (the selection rule) is a **code change**
(§3.5).

Config supplies an **ordered candidate list** per slot, not a single occupant; **code**
applies a deterministic rule to pick the winner from discovered facts (§3.5). Primary/backup
is just the two-element case.

### 0.3 Consequence for A1/A2 — the constraint becomes structural again

The epic draft's `counts_for_cross_vendor` (provider attribute) and the ruling comment's
`requires_cross_vendor` (per-binding boolean) are **both dropped.** Under §0 there is no
config field that grants or describes cross-vendor credit at all. Code knows a slot is
cross-vendor; config only names its occupant; a roster edit that seats a non-counting or
disallowed occupant is **rejected at validation** because code owns the constraint. This is
a *stronger* satisfaction of architect A1 than the ruling-comment mechanism: there is no
field to get wrong. The architect's A1(3) served-provenance requirement still holds
verbatim — credit is computed from the served provenance (§5.3), so a slot whose backup
served a non-counting vendor yields zero credit at runtime and fails closed.

### 0.4 The inference host is an occupant too — fully config-described, zero code literals

Per the operator: "all the details about the host should be in config so that it could
logically point to any machine." The machine is an occupant, not a fixed part of the
mechanism:

- **Zero host literals in code.** No hostname, IP, port, or scheme for the inference host may
  appear in `local_model.py`, any script, any agent definition, or any resolver default. They
  live **only** in config (env-referenced, §3.4). Concrete names (`ollama.kumajyo.com`,
  `clarafuff`, `192.168.x.x`) appear **in docs as examples only, never as fallback defaults.**
- **Capabilities are discovered, not declared** (§2.1a). The model catalog, VRAM footprints,
  `max_context_tokens`, speed, and residency come from the gateway's `GET /models` at
  **runtime** — properties of whichever machine is configured, not code constants. Config
  names *which slot uses which model id*; the gateway supplies *what that model can do*.
- **A portability guard makes this enforceable** (§11.4): `portability_check.py` fails if a
  host literal appears outside config and docs. Requirement, not aspiration.
- A different GPU box, a colleague's box, or a cloud endpoint is reachable by editing config
  alone.

---

## 1. Scope

Per **architect A5 / pm R-P4.1**, this design covers **only** the behavior-preserving
identity refactor (ADR-1477 D-J, landing #1): the registry, `config/models.yaml`, the
resolver (build-time + runtime), the runtime seam + V4 provenance, the code-owned
cross-vendor constraint, the validation gate, and a default config reproducing **today's
exact invocations** at every site, proven by **characterization tests** written before any
behavior change.

**Out of scope (separate later landing, #1455):** local-inference occupants, the GPU/CPU
gateway transport, new routing, the fallback ladder as live behavior, #1469. This design
shows only that the schema **accommodates** them (§2.4, §3.4). Per pm P4/R-P4.1 the
abstraction closes **without** the lane and no #1455 issue may block it.

### 1.1 Scope boundary for discovery / selection (architect OQ-7 ruling — reading split)

The architect rejected building live discovery inside this consumer-critical refactor
(A5 / pm grounds). The boundary is precise:

**Land now** — behavior-preserving, all exercised by the default config, and would otherwise
force a second same-surface refactor:
- the ordered-candidate-list **schema** in its final shape (§3) — #1455 adds occupants, not a
  new shape;
- `select_candidate` (§3.5) as a **pure function with a stable signature that accepts
  `discovered_facts`**, applying only the constraints the default config exercises
  (capability-class match, cross-vendor allowlist, cost-gradient, CLI reachability). With
  single/two-element CLI lists it deterministically returns index 0;
- the **provenance shape** including `served_index` + the `selection` block (§10.2) — this
  freezes #1469's dataset shape now.

**Defer to #1455** — dead code in this landing whose only live consumer is the gateway
transport #1455 introduces:
- the live `GET /models` discovery **client** (§2.1a);
- the discovered-`max_context_tokens` **constraint** inside `select_candidate`.

In this landing `discovered_facts` is empty / CLI-static and the capacity constraint is a
**no-op**. The characterization suite (§8) need not cover live discovery.

---

## 2. Transport interface (formerly "provider interface")

Because a slot's occupant is named by `vendor` + `model`, and (today) each vendor has
exactly one CLI transport, the interface is now about **how to reach a vendor's backend**,
not about carrying policy. A transport is a Python object (home:
`scripts/oversight/transports/`) implementing three methods. Transports are the **only**
code that knows how to talk to a backend CLI or gateway; every invocation site calls the
resolver/seam, never a transport directly.

### 2.1 Signatures

```
probe()          -> ProbeResult
invoke(request)  -> InvokeResult                # (response payload + Provenance, §10)
capabilities()   -> Capabilities
```

```
Capabilities = {
    transport_id: str,             # "agy" | "codex" | "claude-cli" | "ollama-gateway"
    vendor:       str,             # REAL vendor: "anthropic"|"google"|"openai"|"local"
    models:       list[ModelFact], # DISCOVERED at runtime (§2.1a), not declared
    # NO counts_for_cross_vendor, NO cost_class here — both are code-owned (§0, §5, §11).
}
```

The mapping **vendor → transport** is a **code-pinned** table (`google → agy`,
`openai → codex`, `anthropic → claude-cli`), not config, because it is orchestration, not
occupancy. `local` maps to `ollama-gateway` and is introduced by #1455 (§2.4).

#### 2.1a Capabilities are discovered, not declared (operator requirement / #1475 "discover, do not hardcode")

> **Scope (OQ-7):** the *interface* for discovery is fixed now; the **live `GET /models`
> client is deferred to #1455** (§1.1). No default slot uses the gateway transport, so in this
> landing `capabilities()` for the gateway returns an empty/CLI-static fact set and the client
> is dead code. The shape below is frozen so #1455 adds a client, not a new interface.

`capabilities()` for the gateway transport returns facts obtained from **`GET /models` at
runtime**, never constants baked into the config or the code:

```
ModelFact = {
    model:              str,          # model id (e.g. "qwen2.5-coder:32b")
    max_context_tokens: int,          # discovered — the real max-safe context for THIS host
    vram_footprint:     int | None,   # discovered
    resident:           bool,         # discovered — currently loaded / warm
    # ...whatever GET /models reports; treated as authoritative for capacity...
}
```

The roster names *which model id* a slot may use; the gateway supplies *what that model can
do on the configured machine*. `max_context` is therefore **not** a config or code constant —
it is a property of the box the operator pointed at. For the CLI transports (agy/codex/claude)
`capabilities()` returns the static known model list (no discovery endpoint), which is fine —
their capacity does not vary by host.

### 2.2 Fault taxonomy and caller-visible outcomes

Every failure is classified into one honest fault, preserving **D41** (a non-review is loud
and distinct from a clean review) and **D52** (never silently suppress):

| Fault | Meaning | Caller-visible outcome |
|---|---|---|
| `UNAVAILABLE` | CLI absent / not authed / gateway unreachable | Same path as "reviewer unavailable" today — fallback (§11) or the existing fail-closed exit at MEDIUM+/HIGH+ |
| `INVOCATION_FAILED` | launched but exited non-zero / no parseable output | Distinct loud error (`review NOT performed`); **never** an empty clean pass (D41) |
| `DEGRADED` | responded, salvage/retry recovered output (agy prose-wrap, HOS#113) | Result surfaced with a degradation note; verdict stands |
| `SCHEMA_INVALID` | responded, salvage failed → prose only | Raw prose surfaced verbatim, verdict `parse-failed`, not `error`/`clean` |

Transports **return** these; they never map a fault to `findings:[]`. The
`|| echo '{"error":…,"findings":[]}'` idiom banned by D41 is banned inside transports too.

### 2.3 Why an interface and not just a helper

One transport per backend is the structural fix for the D41 class — the `codex --quiet` bug
replicated across sites becomes a one-line fix in one place.

### 2.4 Accommodation of #1455 (out of scope, shown only for adequacy)

`ollama-gateway` (GPU/CPU, `vendor: local`) is a fourth transport behind this same
interface (ADR-034 D-A). It needs **no** interface change: `local` is never on the
cross-vendor allowlist (§5) and sits at the bottom of the cost ladder (§11). The gateway's
address is a *deployment* fact carried **only** in config as env references
(`url_env`/`token_env`/`device`, §3.4) — never a literal in code, per §0.4. This is the one
place config carries more than pure occupancy, because it describes *where the operator's box
lives*, and that box is itself a swappable occupant. The default config in this landing
references **no** local occupant.

---

## 3. `config/models.yaml` schema — a slot roster

The file is a **roster**: per code-defined slot it names an **ordered candidate list**. It
carries **no policy** — no tier, no fire-condition, no cross-vendor flag, no count, no
selection rule. Code picks the winner from the list (§3.5).

```yaml
version: 1

# ── occupancy only, ordered candidates ──────────────────────────────────────
# Code owns the slots, the counts, the tiers, the constraints, and the SELECTION
# RULE. This file lists candidate occupants in PREFERENCE ORDER per slot. Editing
# or reordering candidates NEVER changes WHEN a slot fires, HOW MANY fire, WHETHER
# a slot is required, or WHICH candidate wins the deterministic pick (§3.5).

# Post-PR cross-vendor panel (run_panel.sh). Slots + fire-tiers are in CODE.
panels:
  correctness: [ { vendor: google, model: gemini }, { vendor: openai, model: codex } ]
  adversary:   [ { vendor: openai, model: codex } ]
  triage:      [ { vendor: anthropic, model: haiku } ]    # same-vendor helper, never a cross-vendor vote
  arbiter:     [ { vendor: anthropic, model: sonnet } ]   # synthesizer only (D4/D16)

# Pre-PR cross-vendor second review (run_second_review.sh). Bands are in CODE.
second_review:
  correctness: [ { vendor: google, model: gemini }, { vendor: openai, model: codex } ]
  security:    [ { vendor: openai, model: codex } ]

# System-level adversarial red-team (run_red_team.sh / run_redteam_sample.sh)
redteam:
  adversary:   [ { vendor: openai, model: codex } ]
  breadth:     [ { vendor: google, model: gemini } ]

# Non-oversight helper tasks (completion/embedding class). Illustrative local
# candidates (#1455, not in this landing) show the ordered-list purpose:
tasks:
  session_summary:      [ { vendor: google, model: gemini }, { vendor: openai, model: codex } ]
  self_review.correctness: [ { vendor: google, model: gemini } ]
  self_review.adversary:   [ { vendor: openai, model: codex } ]
  # fidelity:    [ { vendor: local, model: "qwen2.5-coder:32b" }, { vendor: local, model: "qwen2.5-coder:14b" } ]
  # json_repair: [ { vendor: local, model: "qwen2.5-coder:7b" },  { vendor: local, model: "qwen2.5-coder:14b" } ]

# agent-class roles — model identity compiled into frontmatter at BUILD time (§9).
# Single-candidate lists are the norm here (harness reads static frontmatter).
# escalation.model is the runtime --model override for #63; the WHEN (HIGH/CRITICAL)
# is code, only the target model is config.
agents:
  code_reviewer:       { candidates: [ { vendor: anthropic, model: claude-sonnet-4-6 } ], escalation: { model: claude-opus-4-8 } }
  security_reviewer:   { candidates: [ { vendor: anthropic, model: claude-sonnet-4-6 } ], escalation: { model: claude-opus-4-8 } }
  risk_assessor:       { candidates: [ { vendor: anthropic, model: claude-sonnet-4-6 } ], escalation: { model: claude-opus-4-8 } }
  oversight_evaluator: { candidates: [ { vendor: anthropic, model: claude-sonnet-4-6 } ], escalation: { model: claude-opus-4-8 } }
  architect:           { candidates: [ { vendor: anthropic, model: claude-opus-4-8 } ] }
  technical_design:    { candidates: [ { vendor: anthropic, model: claude-opus-4-8 } ] }
  # ...every other agent-class role, candidates only...

# Inference-host deployment facts — env references ONLY, never literals (§0.4).
# Introduced by #1455, absent in this landing:
# transports:
#   ollama-gpu: { kind: ollama-gateway, device: gpu, url_env: OVERSIGHT_LOCAL_HOST, token_env: OVERSIGHT_LOCAL_TOKEN }
```

### 3.1 Candidate entry shape

```
Candidate = { vendor: <anthropic|google|openai|local>, model: <str>, <arg>: <val> ... }
Slot roster = [ Candidate, Candidate, ... ]   # ORDERED preference; ≥1 element
```

Optional per-candidate args carry only invocation *identity* the current site already uses
(e.g. `num_ctx`, or a captured `--sandbox`/stdin-delivery flag). They do **not** carry policy.
A single-element list is the "no fallback" case (I3 net-new checks); a slot may also declare
`{ none: <reason> }` as a terminal candidate for "deterministic takeover" (embedding →
`reconcile_membership()`). **Primary/backup is the two-element case of the ordered list.**

### 3.2 The three corrections from the epic body (still binding, now automatic)

1. **No `class: cross_vendor`.** Cross-vendor-ness is a property of the code-defined *slot*
   (panels.correctness, second_review.correctness), never a config value (A2a / D-I / §0).
   The three capability classes `{agent, completion, embedding}` are a **code** property of
   each slot, not a roster field (§3.3).
2. **No `requires_cross_vendor` / `counts_for_cross_vendor`** anywhere in config (§0.3).
3. **`ipcheck` and deterministic built-ins are NOT occupants** (A2b / D-A / D52). They are
   not in the roster; they stay CORE panel members dispatched by code (§6). Routing a
   deterministic scanner through the roster would recreate the D52 suppression surface.

### 3.3 Capability class is a code property of the slot (V3)

Each slot has a fixed class in code — `panels.*`/`second_review.*`/`redteam.*`/tasks are
`completion` (or `agent` for harness-driven roles); embeddings are `embedding`. **Every**
candidate must be reachable by a transport of the slot's class; validation rejects a
raw-completion candidate in an `agent` slot (§11, V3). A terminal `{ none: <reason> }`
candidate means "deterministic takeover" (embedding → `reconcile_membership()`).

### 3.4 Deployment facts vs occupancy — host address is env-referenced only

The only non-occupancy data the file may hold is the gateway transport's deployment facts,
and they are **env references, never literals** (`url_env`/`token_env`/`device`, #1455) — per
§0.4, no hostname/IP/port/scheme appears in the file or in code; the config names the env var,
the operator's environment supplies the value. Introduced later, absent now. Everything else
is strictly candidate identity.

### 3.5 The selection rule (code-owned): first candidate satisfying the deterministic constraint

Config supplies the ordered candidate list; **discovery** (§2.1a, live client deferred to
#1455) supplies each candidate's real capacity; **code** applies a deterministic rule to pick.
Home: a **pure function with a stable, frozen signature** in `scripts/oversight/slots.py`:

```
select_candidate(slot_key, candidates, discovered_facts, governing_tier) -> (winner, rationale)
```

The `discovered_facts` parameter is part of the frozen signature **now** even though it is
empty/CLI-static in this landing (§1.1) — #1455 fills it from the discovery client without
changing the signature. The rule is **"first candidate (in config order) that satisfies every
constraint"**, where constraints are:

- **Code-owned policy (live in this landing)** — the slot's capability class matches (§3.3);
  for a `cross_vendor=True` slot the candidate vendor is allowlisted non-author external (§5);
  the cost gradient does not invert versus earlier candidates (§11); CLI reachability. A
  candidate failing any constraint is skipped, in order, with the eliminating constraint
  recorded (§10.2).
- **Discovered-capacity constraint (deferred to #1455, a NO-OP here)** — the candidate's model
  exists on the configured host, is available (`resident`/reachable), and the request fits its
  **discovered** `max_context_tokens` (never a config/code constant, §2.1a). Inert in this
  landing because `discovered_facts` is empty and no default slot uses the gateway.

If **no** candidate satisfies the constraints, the slot is **unfilled** → the slot's coded
fail-closed behavior applies (for a `required` cross-vendor slot, the existing
`run_second_review.sh` `exit 1`; §5.4). The rule is **deterministic**: identical
`(list, discovered_facts, tier)` always yields the identical winner — this is what preserves
D-DET (§6) and keeps #1469's provenance interpretable. **With the default config
`select_candidate` returns index 0** (single/two-element CLI lists, empty `discovered_facts`)
— a D-DET property, not merely a characterization property (§6.3). **Selection is never
delegated to the gateway** (§3.6).

### 3.6 Hard boundary — the gateway discovers, it does NOT select

| Gateway capability | Status | Why |
|---|---|---|
| `GET /models` (discovery) | **Required, trustworthy** (live client deferred to #1455, §1.1) | Supplies the real per-host capacity facts (§2.1a). |
| `POST /models/select` (delegated selection) | **Prohibited** | Moves the selection decision out of HOS code — the exact shortcut §0 forbids. Also unreliable on fact: `nvidia-smi` is absent from the gateway container, so its VRAM-protection logic reports 24 GB free unconditionally (verified against the live service; `aqua-wrapper/claude-feedback.md` runtime addendum). |
| `auto:*` model aliases | **Prohibited** | Substitution-by-design → non-deterministic provenance, contaminates #1469's dataset (#1475 R1). The roster must name concrete model ids; validation (§11) rejects an `auto:*` candidate. |

The selection decision lives only in `select_candidate` (§3.5). The gateway answers "what can
this host do?" — never "which model should you use?"

---

## 4. The code-owned slot registry (the policy surface)

A code module — proposed `scripts/oversight/slots.py` (pure, stdlib-only, sibling of
`panel_logic.py`) — is the single source of truth for the slot *definitions* that config may
never touch:

```
SLOTS = {
  "panels.correctness":     Slot(class_="completion", fires_at="MEDIUM", cross_vendor=True,  required=True),
  "panels.adversary":       Slot(class_="completion", fires_at="HIGH",   cross_vendor=True,  required=True),
  "panels.triage":          Slot(class_="completion", fires_at="ALWAYS", cross_vendor=False, required=False),
  "panels.arbiter":         Slot(class_="completion", fires_at="MEDIUM", cross_vendor=False, required=False),
  "second_review.correctness": Slot(class_="completion", fires_at="MEDIUM", cross_vendor=True, required=True),
  "second_review.security":    Slot(class_="completion", fires_at="HIGH",   cross_vendor=True, required=True),
  ... redteam.*, tasks.*, agents.* ...
}
```

The `fires_at` / `cross_vendor` / `required` / `class_` fields are **code constants**; the
roster (§3) supplies only the occupant for each key. `slots.py` also exports the
cross-vendor allowlist and cost pins (§5, §11). Loading the roster = "for each slot defined in
the **active** configuration, look up its occupant in the YAML and validate the occupant
satisfies the slot's coded constraints."

### 4.1 Slot definitions are scoped to the active configuration (architect OQ-1 ruling)

The architect ruled option (b) — a **dev-scoped roster** for the 5 framework validators — and
caught a consequence: **it is not only the roster *entries* that are dev-scoped; the slot
*definitions* are too.** The `framework.validate_*` slots must **not** be baked into the
shipped CORE `SLOTS` table. If they were, the bidirectional orphan check (§11 — "every code
slot has an occupant") would **fail on every consumer tree**, because a consumer's roster has
no occupant for tools it does not run.

Design:
- CORE `slots.py` ships **only** the consumer slots (`panels.*`, `second_review.*`,
  `redteam.*`, `tasks.*`, `agents.*`).
- The `framework.validate_*` slot **definitions and their roster** travel **together** in the
  **hos-dev-pack** — either a dev-only slots module or a merged/overlay `SLOTS` applied only
  when the dev pack is active.
- **The orphan check (§11) is scoped to the slots defined in the *active* configuration**:
  CORE-only on a consumer tree; CORE + dev overlay on a framework-dev tree. Neither tree ever
  has an orphaned slot.

This splits the §7 site inventory into **7 consumer-shipped direct sites + 5 dev-only direct
sites** (§7.1).

---

## 5. A1 (CRITICAL / blocking) — code-owned cross-vendor constraint (D-H), restated under §0

Under §0 the guarantee is structural: **code knows which slots are cross-vendor; config only
names occupants; a disallowed occupant is rejected at validation.** Four parts, mirroring
the HOS#985 one-directional clamp (config may strengthen, never weaken) and satisfying
D4/D33/D49/D52.

### 5.1 Code-pinned vendor allowlist — where it lives

**`scripts/oversight/slots.py`** (or a focused `cross_vendor.py` sibling):

```
CROSS_VENDOR_ALLOWLIST = frozenset({"google", "openai"})
```

- `anthropic` is **deliberately excluded**: Opus authors, so no Claude model is an
  independent cross-vendor check (D4). Stronger than the epic draft — anthropic can never
  corroborate itself, not merely "a flag is false."
- `local` and any unrecognized vendor **can never** count.
- The set lives **in code**; there is no config path that widens it.

### 5.2 The constraint is on the SLOT, checked against the occupant

For any slot with `cross_vendor=True`, validation (§11) requires **every candidate** in the
ordered list to be in `CROSS_VENDOR_ALLOWLIST`. A roster placing `vendor: local`,
`vendor: anthropic`, or an unrecognized vendor **anywhere** in a cross-vendor slot's list is
**rejected at install/CI**, not honored. There is no config `true`/`false` to subtract from;
the slot's cross-vendor-ness is code, so config can only *fail to satisfy* it, never *grant*
it. (This also means the deterministic selection rule, §3.5, can never pick a non-counting
winner for a cross-vendor slot — the list contains no such candidate.)

### 5.3 Credit is computed from the SERVED provenance, never the declared occupant (A1.3)

Runtime credit reads the **V4 provenance of the invocation that actually served the call**
(§10), specifically `provenance.served_vendor`, never the roster's declared occupant.
Consequence: if a cross-vendor slot's **backup** served and that backup is non-allowlisted
(local, or a same-vendor Claude fallback), **credit evaporates at runtime** even though the
roster named an allowlisted primary. *V1 and V4 are one guarantee from two ends, designed
together.*

### 5.4 Functions and files that change

- **`scripts/oversight/slots.py`** (new) — `SLOTS`, `CROSS_VENDOR_ALLOWLIST`,
  `counts_as_cross_vendor(served_vendor) -> bool` (`served_vendor in ALLOWLIST`), and
  `cross_vendor_credit(provenance_records) -> set[str]` (distinct allowlisted served vendors).
- **`scripts/oversight/panel_logic.py` — `count_corroboration()`** (§194). Today it counts
  distinct `merged_from[].reviewer` name strings. It changes to count distinct **allowlisted
  served vendors**: each membership entry is mapped to its served vendor via provenance, then
  filtered through `counts_as_cross_vendor` before the distinct-count. Same-vendor two-lens
  still collapses to one (binding 3 preserved); a local-served corroboration contributes
  **zero** cross-vendor tier credit; the fail-open ranking floor (binding 7) stays for
  ordering only.
- **`scripts/run_second_review.sh` — the fail-closed band checks (~§248–276) + a new
  post-invocation credit check.** After `run_agy_review`/`run_codex_review`, verify the
  served provenance vendor for each `required` cross-vendor slot is allowlisted. If not
  (backup served a non-counting occupant), treat the slot as **unfilled** and take the
  **existing** `exit 1` fail-closed path — the same one used for "both vendors unavailable."
  No new exit path is invented.
- **`scripts/oversight/second_review_logic.py`** — reviewer *selection* (the deterministic
  `_AGY_TIERS`/`_CODEX_TIERS`/threshold logic) is unchanged and stays in code. What changes
  is that "did we obtain cross-vendor credit" is no longer implied by "we selected the slot";
  it is a post-invocation assertion on provenance.

### 5.5 Required tests (A1.4 — acceptance criteria; now test the SLOT constraint)

- (a) A roster listing a **non-allowlisted vendor** (local/anthropic/unknown) **anywhere** in
  a `cross_vendor=True` slot's candidate list is **rejected at validation**.
- (b) A cross-vendor slot whose **fallback candidate served** a non-counting occupant records **zero**
  cross-vendor credit and, at MEDIUM+, fails closed on the **same path** as "both vendors
  unavailable" (`run_second_review.sh` non-zero exit).
- (c) `count_corroboration` counts a local/anthropic-served corroboration as **zero**
  distinct cross-vendor vendors.
- (d) Two lenses from the same allowlisted vendor collapse to one (binding 3 preserved).
- (e) The arbiter's synthesized product (§5.6) is **never** itself a corroborating vote —
  corroboration counts only the independent reviewers' served provenance, not the synthesis.

### 5.6 The double lock on same-vendor helpers (architect OQ-5 — REQUIRED, not optional)

`panels.arbiter` (sonnet) and `panels.triage` (haiku) are same-vendor Claude helpers that must
**never** count as a cross-vendor vote. Two independent guards are **both required** (the
architect ruled the belt-and-suspenders mandatory, not defence-in-depth nicety):

1. **Slot-level:** these slots are declared `cross_vendor=False` in `slots.py` (§4).
2. **Allowlist-level:** `anthropic ∉ CROSS_VENDOR_ALLOWLIST` (§5.1) — so even a
   mislabelled slot could not admit a Claude vote.

Either guard alone suffices; both are present so a single edit can never open the substitution
A1 guards against. Additionally, the **arbiter is a synthesizer only (D4/D16)**: its merged
product deduplicates the independent reviewers' findings and is **never** counted as a
corroborating reviewer — corroboration (§5.4, `count_corroboration`) reads only the independent
reviewers' served provenance via `merged_from`, never the arbiter's own output.

---

## 6. Determinism-preservation invariant (operator constraint)

> "If invoked deterministically today, it needs to remain deterministic."

**Invariant D-DET:** the abstraction MUST NOT convert any deterministic dispatch into a
model-mediated one. The registry resolves **identity** (who occupies a slot); it never
decides **whether** or **when** to invoke. Every fire/skip/threshold/count decision stays in
deterministic code.

### 6.1 The deterministic dispatch surface (must remain deterministic)

| Site | Deterministic decision that must stay in code |
|---|---|
| `run_panel.sh` | roster construction + which slots fire at which tier (the `run_reviewer` case is dispatch, the model literal is occupancy) |
| `run_second_review.sh` | score-vs-threshold logic, the HOS#985 `.env` one-directional clamp, the fail-closed band checks |
| `run_review_chain.sh` | `RUN_AGY`/`RUN_CODEX` tier gate (L238–241) |
| `second_review_logic.py` | `compute_reviewers` (`_AGY_TIERS`=MEDIUM+, `_CODEX_TIERS`=HIGH+) — pure |
| `panel_logic.py` | `compute_triage_floor`, `count_corroboration`, `compute_sqc_sample` — pure |
| `model_escalation.py` | `select_review_model(agent, tier)` — the WHEN of #63 escalation |
| `slots.py` `select_candidate` | the winner-pick (§3.5) — deterministic given (list, discovered facts, tier); identity selection only, never a fire/skip decision, never delegated to the gateway (§3.6) |
| config validation gate | all §11 checks |
| deterministic built-ins (`ipcheck`, scanners) | dispatched by code, **never** roster occupants (reinforces A2b) |

### 6.2 The invariant's test

For each deterministic-dispatch site, a test asserts the **dispatch decision is independent
of registry contents**: with the roster stubbed to arbitrary occupants (or absent), the
computed set of slots-that-fire, the threshold comparisons, `compute_reviewers`,
`compute_triage_floor`, and `select_review_model`'s WHEN all produce **identical** results.
Only the *resolved occupant string* may change with the roster. Equivalently: the registry
API exposes `resolve(slot) -> Occupant` and has **no** method that answers "should this
fire?" — that question has no registry entry point.

### 6.3 The residual: discovery-driven winner variance is identity, not dispatch (the #1455 boundary)

`select_candidate` (§3.5) is deterministic **given** `(list, discovered_facts, tier)`, and
`discovered_facts` **will vary at runtime once #1455's discovery client lands** (a model may
be resident on one cycle and evicted the next). Naming this residual precisely so the #1455
boundary is unambiguous:

- **(a) The variance is confined to *identity*, never *dispatch*.** Which candidate *wins* a
  slot may change with discovered facts; **whether/when the slot fires, how many fire, and
  whether cross-vendor is required do not** — those are code (§6.1) and take no input from
  discovery. A model becoming unavailable can only move the winner down the ordered list or
  leave the slot unfilled (→ the coded fail-closed path); it can never cause a slot to fire
  that code said should not, or vice versa.
- **(b) The variance is fully recorded.** The `selection` provenance block (§10.2) captures
  the consulted list, each eliminated candidate with its reason, and the discovered facts the
  rule keyed on — so a discovery-driven winner change is **replayable non-determinism**, not a
  D-DET violation. Given the recorded `discovered_facts`, the winner is reproducible.
- **In this landing** `discovered_facts` is empty, so there is no residual at all:
  `select_candidate` returning **index 0 for the default config is a D-DET property** (asserted
  as such, §3.5), independent of and stronger than the §8 characterization fixtures.

---

## 7. The invocation/knowledge sites

The epic asserts **17 files** incl. "the six `scripts/framework/validate_*.sh`". **Verified:
there are FIVE `validate_*.sh`, not six** (`validate_agents`, `validate_docs`,
`validate_scripts`, `validate_self`, `validate_spec_compliance`; `bootstrap/validate_setup.sh`
invokes no model). True count is **16**: **12 direct invocation sites** + **4
model-knowledge sites**. Per the architect OQ-1 ruling (§4.1), the 12 direct sites split into
**7 consumer-shipped** and **5 dev-only** (hos-dev-pack). OQ-2 (the epic's "17 / six
`validate_*.sh`" figure) is **confirmed wrong** by the architect; corrected inventory below.

### 7.1a Consumer-shipped direct invocation sites (7) — CORE slots, characterization-tested (§8)

| # | File | Backend(s) today (exact) | Slot(s) |
|---|---|---|---|
| 1 | `run_panel.sh` | `run_reviewer()` case (L131–134): `claude -p --model haiku`; `claude -p --model sonnet`; `agy -p`; `codex exec` | `panels.triage`, `panels.arbiter`, `panels.correctness`, `panels.adversary` |
| 2 | `run_second_review.sh` | `run_agy_review()` `agy --sandbox -p` (L595, retry L601); `run_codex_review()` `codex exec <` (L678) | `second_review.correctness`, `second_review.security` |
| 3 | `run_red_team.sh` | `codex exec` (L288); `agy -p` (L358) | `redteam.adversary`, `redteam.breadth` |
| 4 | `run_redteam_sample.sh` | `codex exec` (L167); `agy -p` (L169) | `redteam.adversary`, `redteam.breadth` (sampling mode) |
| 5 | `capture_session.sh` | `agy -p` (L168) else `codex exec` (L170) | `tasks.session_summary` (primary/backup) |
| 6 | `review_self.sh` | `agy -p` (L248); `codex exec` (L249) | `tasks.self_review.correctness/adversary` |
| 7 | `reverify_self.sh` | `agy -p` (L263); `codex exec` (L264) | `tasks.self_review.*` (reverify) |

### 7.1b Dev-only direct invocation sites (5) — hos-dev-pack slots, NOT shipped to consumers (§4.1)

Their slot definitions **and** roster travel in the dev pack; the orphan check is scoped to
the active configuration so a consumer tree never sees these as orphans.

| # | File | Backend(s) today (exact) | Slot(s) (dev-pack `SLOTS` overlay) |
|---|---|---|---|
| 8 | `framework/validate_agents.sh` | `agy -p` (L282); `codex exec <` (L339) | `framework.validate_agents.*` |
| 9 | `framework/validate_docs.sh` | `agy -p` (L191); `codex exec <` (L245) | `framework.validate_docs.*` |
| 10 | `framework/validate_scripts.sh` | `claude -p --model claude-opus-4-8` (L180); `agy --sandbox -p` (L181); `codex exec` (L182) | `framework.validate_scripts.*` |
| 11 | `framework/validate_self.sh` | `claude -p --model claude-opus-4-8` (L220) | `framework.validate_self.opus` |
| 12 | `framework/validate_spec_compliance.sh` | `agy -p` (L211); `codex exec <` (L284) | `framework.validate_spec.*` |

The default roster (consumer + the dev overlay on a dev tree) MUST reproduce each site
byte-for-byte (§8): same CLI, subcommand, flags (`--sandbox`, `--model claude-opus-4-8`), and
prompt-delivery channel (`codex exec <file` vs `agy -p "$prompt"`). The `MODEL=claude-opus-4-8`
literal becomes a resolved occupant.

### 7.2 Model-knowledge sites (4) — carry vendor/model knowledge, no model call

Not invocation sites; the byte-identical bar (§8) does not apply. They must resolve their
embedded knowledge from the same authority so no second list drifts:

| # | File | Embedded knowledge | Resolution under §0 |
|---|---|---|---|
| 13 | `run_review_chain.sh` | tier→{agy,codex} selection gate (L238–241); delegates invocation to `run_second_review.sh` | Selection stays **code** (a floor, D-DET §6); reads slot `fires_at`/`cross_vendor` from `slots.py`, not a private literal |
| 14 | `second_review_logic.py` | `_AGY_TIERS`/`_CODEX_TIERS` | Stays **code** (safety floor); **derived from `slots.py`, not a second copy** (§7.2.1); provenance-based credit (§5) replaces "selected ⇒ counted" |
| 15 | `validation_logic.py` | vendor finding-shape: agy=`category`, codex=`type` (L165–172) | Vendor identity of a finding resolves from provenance/registry, not name-string sniffing |
| 16 | `token_tracker.py` | cost/quota table `agy-20`/`agy-100`/`codex-20` (L46–48) | Cost **class** is code-pinned (§11); quota **numbers** stay in `token_tracker.py` for this landing and **never** enter the occupancy roster (OQ-3, ruled) |

`bin/hos-cron`, `bin/hos-worker*`, `bin/hos-overseer*` invoke `claude --agent` (the harness
`agent`-class path), resolved **build-time** (§9), not through the runtime seam; not in the 16.

#### 7.2.1 One source of truth for a shared tier floor (architect OQ-2 requirement)

Where a tier floor exists in **both** `slots.py` (a slot's `fires_at`) **and** a logic module
(`second_review_logic.py`'s `_AGY_TIERS`/`_CODEX_TIERS`, `run_review_chain.sh`'s
`RUN_AGY`/`RUN_CODEX` gate), there must be **exactly one source of truth**. Two acceptable
implementations:

- **(a) Derivation** — the logic module computes its floor sets from `slots.py`
  (`_AGY_TIERS = {t for slot in SLOTS if slot fires the correctness reviewer at tier ≥ t}`),
  holding no independent literal; or
- **(b) Asserted equality** — the literal remains but a **D-DET test** (§6.2) asserts it equals
  the `slots.py`-derived value, failing CI on any divergence.

No independent second copy may exist unguarded — that is precisely the D41 drift class
(one upstream change, N silently-stale copies) this epic exists to kill.

---

## 8. Characterization tests (pm R-P5.2 / architect A5) — the consumer-safety bar

Acceptance criterion for the refactor: **byte-identical invocation at all 12 direct sites
(§7.1a consumer + §7.1b dev-only), asserted before any behavior change.**

- **Capture argv, not network.** A record-mode shim on `PATH` (fake `agy`/`codex`/`claude`
  stubs) records the exact `(argv, stdin, env-subset, cwd, redirects)` each site would run.
- **Golden fixtures from the CURRENT tree** for each of the 12 sites: e.g. site 2 correctness
  ⇒ `argv=["agy","--sandbox","-p",<prompt>]`; site 2 security ⇒ `codex exec` with prompt on
  **stdin from a tempfile**; site 11 ⇒ `["claude","-p",<prompt>,"--model","claude-opus-4-8"]`.
- **Assert equality after the refactor:** the same sites, routed through the resolver with
  the default roster, produce byte-identical tuples. Any diff fails.
- **Coverage:** flags, subcommand, **prompt-delivery channel** (arg vs stdin vs
  stdin-from-tempfile, load-bearing and per-site), stderr redirect, and the surrounding
  `|| rc=$?` / salvage-retry behavior.
- **Selection reproduces today's invocation.** The default rosters are one/two-element CLI
  lists; with all CLI transports available (the current world, no local host), `select_candidate`
  (§3.5) deterministically picks index 0 — reproducing today's exact call. The characterization
  fixtures assert this: the ordered-list machinery is behavior-preserving in the default config.
- **ADR-034 relationship:** the `OVERSIGHT_LOCAL_HOST=""` off-path test becomes the **special
  case** "with no local occupant configured, resolution reproduces the exact current
  invocation" — one fixture in the suite (A5).
- **Knowledge sites (§7.2)** are not in this suite (no command issued); their bar is unit
  tests that YAML-resolved knowledge equals today's hardcoded values, plus the D-DET tests
  (§6.2).

---

## 9. A3 — the two resolution paths (D-E′)

Configuration is uniform (one roster); *implementation* has two resolution paths, stated
plainly per the epic's L1 honesty requirement.

### 9.1 Build-time — `agent`-class occupant identity

`.claude/agents/*.md` `model:` frontmatter is read by the Claude Code **harness**, which HOS
cannot intercept at runtime. Resolution:

- The roster's `agents:` block is authoritative; `scripts/framework/install.sh` **generates**
  each agent file's `model:` frontmatter from it.
- A **frontmatter drift validator** is **fail-closed at install and in CI** (A3.1, D47/D48):
  stale or hand-edited frontmatter **halts**, never warns. Joins the existing CORE-region
  drift model in `check_agents_static.sh`.
- This is **config compilation, not invocation** (architect A3): no model call is emitted, so
  it does not reopen the D-E "N drifting runtime sites" problem.

### 9.2 Runtime — `completion` / `embedding`

Resolved at call time through the seam (§10): load slot → resolve occupant → probe primary →
fallback per §11 → invoke → record provenance.

### 9.3 #63 escalation reads the SAME roster (A3.2, D-K)

`agent` identity has two levers, both resolving through the one authority:

- **base model** — build-time generated (§9.1).
- **runtime `--model` override** — #63 escalation
  (`scripts/oversight/model_escalation.py`, `select_review_model(agent, tier)`).

Under D-K, `select_review_model` reads the `escalation.model` of the agent's roster entry
instead of the hardcoded `"claude-opus-4-8"` and private `ESCALATION_SET`. The escalating set
becomes "agent roles carrying an `escalation:` entry"; the escalation model is
`escalation.model`. **The WHEN stays in code** (governing tier HIGH/CRITICAL, per §0/§6) —
only the target model is config.

**Monotonic invariant (A3.2):** escalation may only upgrade (never below the #895/#63 floor).
Validation (§11) rejects an `escalation.model` whose capability is below the base
`primary.model`. Unknown/garbled tier → `select_review_model` returns `None` (caller omits
`--model` → build-time base). Reviewer independence and which vendors vote are untouched.
`TECHNICAL-DESIGN-63-model-escalation.md` must be updated to say escalation reads the roster
(ADR-1477 doc-currency edit).

---

## 10. V4 — provenance recorded at the single seam

### 10.1 At the seam, never per-caller

Provenance is written by the runtime seam (one helper per class) on **every** `invoke()`,
never stamped by individual sites (a per-site stamp is the D41 forget-one-site failure, and
seam-recording is what makes A1.3 enforceable). Build-time `agent` bindings record resolved
identity at generation time into the same stream.

### 10.2 Fields

```
Provenance = {
    slot:            str,        # code slot key resolved (e.g. "second_review.correctness")
    transport:       str,        # transport that served the call
    served_vendor:   str,        # REAL vendor of the server — drives A1 (§5.3)
    resolved_model:  str,        # model id actually used
    served_index:    int,        # index in the ordered candidate list that won (0 = primary)
    device:          str | None, # X-Execution-Device when the gateway sends it
    digest:          str | None, # X-Model-Digest — INTERIM: may be absent (§10.3)
    cost_class:      str,        # code-pinned class of the served vendor (§11)
    fault:           str | None, # fault taxonomy value if degraded/failed (§2.2)
    # Selection rationale (WHY, not just WHAT) — cheap because the rule is deterministic:
    selection: {
        candidates:  list[str],  # the ordered candidate list consulted (model ids)
        rejected:    list[{ index: int, reason: str }],  # each skipped candidate + eliminating constraint
        chosen_index: int,       # == served_index; the winner
        rule:        str,        # rule id, e.g. "first-satisfying"
        discovered:  dict,       # the discovered facts the rule keyed on (max_context, resident, ...)
    },
}
```

`served_index` + `selection` are required so #1469's future dataset never silently mixes a
32B GPU run with a Haiku fallback run **and** can control for model variation across PRs (V4).
Because selection is deterministic (§3.5), recording the consulted list, the eliminated
candidates with reasons, and the chosen index is sufficient to replay the decision — no
decision tree need be serialized. A selection bug is debuggable after the fact from this
record alone. Recorded now because the seam is built now, even though #1469 is out of scope.

### 10.3 Digest interim (do NOT fail-closed on an absent field)

The gateway does **not yet reliably expose a model digest** (#1462). Therefore `digest` is
recorded **when present**, left `null` when absent; **provenance-by-name**
(`served_vendor` + `resolved_model`) is the **documented interim** and is what A1 credit (§5)
keys on. The **digest-equality hard-fail lands later**, only when #1462 ships. **This design
adds no check that fail-closes on `digest`** — an explicit non-requirement.

---

## 11. Config validation gate (A6 cost guard + V1/V3 + orphan + determinism)

Runs **at install** and **in CI**. Fail-closed: a typo halts at install, never at 3am in a
cron cycle. Distinct, actionable message per failure.

| Check | Failure report |
|---|---|
| Candidate transport exists | each candidate `vendor` maps to a known transport — else `no transport for vendor '<v>'` |
| Model catalog (discovery) | each candidate `model` is in that transport's catalog — gateway via `GET /models` at runtime, static list for CLIs — else `model '<m>' not served by vendor '<v>'`. **If the host is unreachable, this check cannot run → reports `unverified`, distinctly from `verified valid`, and does not silently pass (§11.5).** |
| No delegated selection | no candidate `model` is an `auto:*` alias (§3.6) — else `auto:* aliases are prohibited (selection is code-owned)` |
| **V3** class integrity | every candidate reachable by a transport of the slot's coded class — else `class mismatch: slot '<s>' is <c1>, candidate needs <c2>` |
| **V1 / A1** cross-vendor | **every candidate** of a `cross_vendor=True` slot is on `CROSS_VENDOR_ALLOWLIST` — else `slot '<s>' is cross-vendor but candidate vendor '<v>' is not allowlisted` (rejects) |
| **§0.4** no host literals | no hostname/IP/port/scheme literal in the roster (host is env-referenced) — else `inline host literal '<x>' — use an env reference` (mirrors the §11.4 code-side portability guard) |
| **V2 / A6** cost gradient (static) | `cost_class(backup) <= cost_class(primary)` on `free-local < subscription-claude < metered-scarce` — else `cost inversion in '<s>'` unless the human-gated annotation is present (§11.3) |
| **A6** cost-class pin | a vendor's effective cost class is the code pin; config may not downgrade it — else `cost class for vendor '<v>' may not be lowered below code pin '<x>'` |
| **#63** escalation monotonic | `escalation.model` capability ≥ base `primary.model` — else `escalation for '<r>' is below the static floor` |
| **D-DET** occupancy-only | the roster contains no policy keys (`fires_at`, `cross_vendor`, `required`, `tier`, `when`) — else `roster may not carry policy key '<k>' (code owns it)` |
| Orphan (both directions, **scoped to the active config**, §4.1) | every slot defined in the active configuration (CORE on a consumer tree; CORE + dev overlay on a framework-dev tree) has an occupant, and every roster entry names a real active slot — else `slot '<s>' has no occupant` / `roster names unknown slot '<s>'`. Dev-only `framework.validate_*` slots are absent from a consumer's active config, so they never orphan a consumer tree. |

### 11.1 Code-pinned cost classes (A6 hole 2)

In `slots.py`:

```
CODE_COST_CLASS = { "openai":"metered-scarce", "google":"metered-scarce",
                    "anthropic":"subscription-claude", "local":"free-local" }
```

Config may make a vendor **more** restrictive, never less — closing A6 hole 2 (relabeling
`codex` as `free-local` is rejected). Note the D-DET check above additionally forbids a
per-slot cost key in the roster.

### 11.2 The "explicitly annotated" upward-fallback escape is human-gated (A6 hole 1)

An upward-climbing fallback is permitted **only** via a **human-gated** annotation — a
human-created artifact (same class as the existing
`.claudetmp/oversight/human-tier-override.md` gate), not a YAML boolean the config author can
set alone. Any authorized inversion is surfaced **loudly** in provenance
(`cost_class` + `cost_inversion: true`) and telemetry (the concrete form of #1474 C4's
contention-vs-outage separation). Without the marker, the static V2 check rejects the
inversion.

### 11.3 Runtime cost-gradient enforcement (V2 is also runtime — A6)

The seam **refuses to climb past the last declared candidate.** The fallback chain is exactly
the ordered candidate list, then **stop** (#1474 C4 `CPU → Haiku, never straight to paid`). A
fault after the final candidate returns the fault outcome (§2.2); it never escalates to an
occupant absent from the list. The static cost-gradient check (above) guarantees the list
itself is non-inverting, so walking it in order can never climb.

### 11.4 Portability guard — host literals fail the build (operator requirement §0.4)

`scripts/oversight/validators/portability_check.py` (already flags hardcoded paths and
environment assumptions) gains a check that **fails** if an inference-host literal
(hostname/IP/port/scheme matching the gateway shape) appears **outside config and docs** — in
`local_model.py`, any script, any agent definition, or a resolver default. This is what makes
§0.4 requirement 1 enforceable rather than aspirational. Example names
(`ollama.kumajyo.com`, `clarafuff`, `192.168.x.x`) are permitted **only** in `docs/` and this
spec; anywhere else is a build failure.

### 11.5 Honest validation degradation when the host is unreachable

If the configured gateway host is unreachable at validation time, the gate **cannot verify**
that a candidate's model exists on it. It must **not** silently pass and must **not**
fail-closed the whole install for a merely-offline research box (the lane is operator-only,
optional — RK-4). It reports the model-catalog check as **`unverified`**, a state distinct
from both `verified valid` and `invalid`, connected to the fault taxonomy (§2.2
`UNAVAILABLE`). The distinction is surfaced to the human: "N candidates unverified — host
`$OVERSIGHT_LOCAL_HOST` unreachable" is not the same signal as "all candidates verified." CLI
candidates (agy/codex/claude) are always verifiable and are unaffected.

**A cross-vendor slot is structurally incapable of being `unverified` (architect OQ-8
sharpening).** A `cross_vendor=True` slot may list only allowlisted CLI vendors (§5.2) — a
`local`/unverifiable candidate in such a slot is **rejected at validation**, never merely
unverified. So a cross-vendor slot resolves to exactly one of two states: **verified-valid** or
**rejected**. The `unverified` state can therefore arise **only** on non-cross-vendor `tasks.*`
slots (the only slots that may list a `local` candidate). **Consequence:** the honest-
degradation state can never silently downgrade a safety gate — an offline research box can
leave a helper task `unverified`, but can never turn a cross-vendor requirement into a soft
pass. A `tasks.*` slot whose sole candidate is an unverified local model is reported
`unverified`, not `clean` (pm R-P2.1 — absence renders as `not performed`, never `clean`).

---

## 12. Migration plan (D-J landing #1) — keep the tree green throughout

1. **Registry + transports + resolver + `slots.py`, no sites wired.** Land the CLI transports,
   the resolver/seam, and `slots.py` (consumer `SLOTS` + allowlist + cost pins + credit + the
   deterministic `select_candidate` with its **frozen `discovered_facts`-accepting signature**,
   §3.5) with unit tests. **Per OQ-7 (§1.1): the live `GET /models` discovery client and the
   discovered-capacity constraint are NOT built here — deferred to #1455.** `discovered_facts`
   is empty/CLI-static; the capacity constraint is a no-op. Tree unchanged.
2. **`config/models.yaml` roster + validation gate + portability guard.** Author the default
   ordered-candidate roster reproducing today's occupants for the **7 consumer sites** (§7.1a);
   land the **dev-pack slot overlay + roster** for the **5 dev-only sites** (§4.1, §7.1b) in the
   hos-dev-pack, not CORE. Wire validation into install + CI including the `auto:*` prohibition
   (§3.6), the honest-degradation `unverified` state (§11.5), the no-host-literal check, and the
   **active-config-scoped orphan check** (§11); extend `portability_check.py` (§11.4) so a host
   literal outside config/docs fails the build. Freeze the **provenance shape**
   (`served_index` + `selection` block, §10.2) now — this fixes #1469's dataset shape. No runtime
   change.
3. **Characterization harness + golden fixtures (§8)** captured from the **current** tree,
   before any reroute. Freezes the byte-identical baseline. **Also land the D-DET tests
   (§6.2/§6.3)** here — including the `select_candidate`-returns-index-0 property and the shared
   tier-floor single-source-of-truth assertion (§7.2.1) — to prove dispatch is
   registry-independent before any reroute.
4. **A1 credit path first** (blocking gate): wire `count_corroboration` + the
   `run_second_review.sh` post-invocation credit check to provenance, with §5.5 tests green.
   Cross-vendor is code-enforced before any occupant can be swapped.
5. **Reroute the direct sites one at a time**, each gated by its characterization fixture.
   Order: lowest blast radius first — `capture_session.sh`, then `review_self`/`reverify_self`
   (the 7 consumer sites first), then the 5 dev-only `validate_*.sh`, then
   `run_redteam_sample`/`run_red_team`, then `run_panel.sh`, and **last** `run_second_review.sh`
   (cross-vendor-critical, already A1-guarded by step 4). Full suite stays green after each.
6. **Resolve the 4 knowledge sites (§7.2)** to read from `slots.py`/provenance, deriving any
   shared tier floor from `slots.py` (§7.2.1), never a second copy.
7. **Build-time `agent` generation + drift gate (§9)**; point `model_escalation.py` at
   `agents.*.escalation.model`. `bin/*` callsites unaffected.
8. **Doc-currency edits (ADR-1477):** `COST-MANAGEMENT.md` §4→data + §9/§10 cost axis;
   `OVERSIGHT-CONTRACT.md` advisory/local reviewer class; `TECHNICAL-DESIGN-63` reads roster.

At every step the tree builds, the characterization suite passes, and the D-DET tests hold; a
resolver bug is caught at the first rerouted site, not across all sites at once (pm R-P5.2).

---

## 13. Startup-artifact-gap analysis (ADR-1477)

Annotated `startup-artifact-gap`. **Dispositive:** the LIL design is DRAFT and **no code was
built against D-E**. This corrects a decision for a path never built — **all prior sign-offs
stand; nothing is orphaned.** No affected-sign-off re-review is triggered. (Another reason to
land this before #1455.)

---

## 14. Inherited invariants confirmed satisfied

- **D4 / D33 / D49 / D52** — cross-vendor and fire-timing are code-owned (§0, §5, §6); config
  can only fail to satisfy, never weaken; deterministic built-ins stay outside the roster and
  un-suppressible.
- **D7 / COST §2** — the abstraction extends "deterministic orchestration in the shell layer";
  §0 is its logical endpoint, not a new departure.
- **D41** — one transport per backend (§2.3); faults loud and distinct, never `findings:[]`.
- **HOS#985** — the constraint is one-directional (config strengthens, never weakens).
- **ADR-034 D-A/D-B/D-C/D-D/D-F/D-G** inherited; `local_model.py` is one transport (§2.4).

---

## 15. Open questions — ALL RESOLVED by the architect (2026-08-31)

All eight open questions were resolved in the APPROVE-WITH-CHANGES review; the design body
above already reflects the rulings. Recorded here for provenance.

- **OQ-0 — ACCEPTED.** A1/A2 re-ratified under the slot framing. Deleting the config term yields
  `effective = code_allowlist(served_vendor)`, so the only weakening lever A1 existed to close
  is **unrepresentable** — there is no field to set. A2's `requires_cross_vendor` field is
  explicitly superseded; A2's intent is fully carried. (§0.3, §5.)
- **OQ-1 — option (b), and slot DEFINITIONS are dev-scoped too.** The `framework.validate_*`
  slot definitions **and** roster travel together in the hos-dev-pack; the orphan check is
  scoped to the active configuration. Splits the inventory into 7 consumer + 5 dev-only.
  (§4.1, §7.1a/b, §11 orphan row.)
- **OQ-2 — §7.2 treatment ratified; site figure confirmed wrong.** Added requirement: a tier
  floor present in both `slots.py` and a logic module has **one source of truth** (derivation
  or an asserted-equality D-DET test); no independent second copy. (§7.2.1.)
- **OQ-3 — confirmed.** Cost *class* code-pinned (§11.1); quota *numbers* stay in
  `token_tracker.py` for this landing and **never** enter the occupancy roster. (§7.2 row 16.)
- **OQ-4 — confirmed.** Selection floors stay in code (D49 hazard if moved to roster). (§4, §6.1.)
- **OQ-5 — confirmed; belt-and-suspenders REQUIRED, not optional.** Slot `cross_vendor=False`
  **and** `anthropic ∉ CROSS_VENDOR_ALLOWLIST`, both mandatory; the arbiter is a synthesizer
  (D4/D16) whose merged product is never a corroborating vote. (§5.6.)
- **OQ-6 — reading (a) is binding.** Two slots MAY share a vendor under different lenses;
  cross-vendor is enforced at the corroboration/sign-off layer against served provenance, **not**
  by a distinct-vendor constraint at slot assignment. **No cross-slot distinctness check.** The
  per-slot §5.2 constraint stands. (§5.2, §5.4.)
- **OQ-7 — scope split; live discovery deferred to #1455.** Land now: the ordered-candidate
  schema, `select_candidate` as a pure function with the frozen `discovered_facts`-accepting
  signature, and the provenance shape (`served_index` + `selection`). Defer to #1455: the live
  `GET /models` client and the discovered-capacity constraint. (§1.1, §2.1a, §3.5, §12 step 1.)
- **OQ-8 — confirmed, with sharpening.** A cross-vendor slot is **structurally incapable** of
  being `unverified` (it is verified-valid or rejected at validation), so honest degradation can
  never silently downgrade a safety gate. (§11.5.)

---

## 16. Nothing in the rulings appears unimplementable

No ruling was wrong or unimplementable. The defects were in the **epic body**: the ruling
comment already flagged two (the `cross_vendor` class, `ipcheck`-as-provider); this design added
two more, both confirmed by the architect — the **site count** ("17 / six validate_*.sh" →
actually 16 / five, 12 invoking, now split 7 consumer + 5 dev-only) and the reframing's
**duplicate-vendor contradiction** (resolved as reading (a), no distinctness check). With the
two refinements absorbed (dev-scoped slot definitions, discovery deferred to #1455) and the two
tightenings applied (§6.3 discovery residual, §7.2.1 single-source tier floor), the **schema is
frozen** and the design may proceed to a coder.
