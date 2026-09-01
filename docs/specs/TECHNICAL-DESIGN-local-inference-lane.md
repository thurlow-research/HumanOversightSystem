# Technical Design — Local Inference Lane (LIL)

**Status:** DRAFT — for design panel + cross-vendor critique
**Target milestone:** v0.6.1 — Stabilization
**Related:** `docs/COST-MANAGEMENT.md`, DECISIONS D4/D5/D6/D7/D33/D52,
`research/findings/agent-availability-is-a-setup-property-not-a-runtime-property.md`,
`research/findings/corroboration-ranked-review-reduces-noise-without-losing-coverage.md`,
SPEC-379 (diff-centric context), SPEC-376 (corroboration ranking), HOS#113 (silent zero-findings pass)

---

## 1. Problem

HOS burns scarce metered-equivalent quota (`agy`/Gemini, `codex`/OpenAI — `codex-20` is
~500k tokens/month ≈ 25 large calls per `token_tracker.py:44-48`) on work that does not
require frontier-model judgment: session summarization, JSON reformatting, risk triage
confirmation, and semantic dedup. Separately, `prompt-fidelity` is a declared NYI stub
(`.claude/agents/prompt-fidelity.md`), i.e. a permanent coverage gap, because implementing
it would add cost to every MEDIUM+ step.

An operator-owned GPU host (RTX 3090, 24 GB) can absorb these tasks at zero marginal token
cost. This design defines how to route work to it **without weakening any oversight
invariant**, and — critically — how the pipeline behaves when that host is unavailable.

## 2. Non-goals

- Replacing any cross-vendor reviewer (`agy` correctness, `codex` security/adversary).
- Participating in merge decisions, tier lowering, or finding suppression.
- Replacing deterministic validators or gates.
- Running `architect` / `technical-design` (the two Opus judgment roles).

---

## 3. Governing invariants

**I1 — Monotonic safety (D6/D33).** The local lane may only act in the safe direction: it
may RAISE a risk tier, ADD a finding, ADD a lens, or ADD an artifact. It may never lower a
tier, remove a reviewer, shorten a roster, or suppress a finding.

**I2 — No decorrelation credit (D4, COST-MANAGEMENT §10).** A local model is a different
training distribution but a materially weaker reviewer. Local output MUST NOT satisfy the
"≥1 cross-vendor reviewer at MEDIUM+" requirement in `run_second_review.sh:249-268`, and
MUST NOT be counted toward the corroboration tiers of SPEC-376. Local findings enter as
Tier-3 single-source, labeled `reviewer: local`.

**I3 — Never fall back "upward".** When the local lane is unavailable, work MUST NOT be
rerouted to `agy` or `codex`. Doing so would spend the scarcest quota precisely when the
free lane fails — the inverse of the design intent. Fallback is to Haiku, to a
deterministic path, or to an explicit NYI. (See §6.)

**I4 — Availability is a setup property, not a runtime property.** Per the existing
finding of that name: if `config.sh` declares the lane enabled and the host is unreachable,
that is a **configuration violation**, surfaced loudly — not a silent degradation to
"passed".

**I5 — Context truncation is a correctness fault.** Ollama defaults `num_ctx` to 4096 and
silently truncates. A truncated diff yields a confident clean review of code never seen —
the exact HOS#113 silent-zero-findings class. Every local call MUST pre-flight
`estimated_prompt_tokens <= num_ctx` and hard-fail if not.

**I6 — Reproducibility.** Local output feeds research artifacts (escaped-defect rate).
Every local call records `model:tag`, quantization, `num_ctx`, `temperature`, and `seed`
into the audit log. Model identity is pinned in `.hos-local-models.lock`.

---

## 4. Scope — what moves to the local lane

Ordered by (value / risk).

| # | Task | Current | Invariant class | Saves |
|---|---|---|---|---|
| T1 | `capture_session.sh --summarize` | requires `agy` or `codex` | pure artifact generation, no gate | agy/codex |
| T2 | `prompt-fidelity` semantic comparison | NYI stub | additive coverage (I1) | nothing — closes a gap |
| T3 | Prose→JSON repair in `run_second_review.sh:588-603` | re-runs the FULL agy review | transcription, not judgment | 1 duplicate agy call per prose response |
| T4 | Panel TRIAGE (`run_panel.sh:283-324`) | `claude -p --model haiku` | floor-bounded, can only confirm/raise | haiku quota |
| T5 | Semantic dedup / corroboration clustering | Sonnet arbiter `merged_from` + `reconcile_membership()` fallback | deterministic embeddings, fixed threshold | sonnet |
| T6 | Supplementary SQC review pass on LOW tier | not run (cost-bounded at 5%) | additive, non-blocking, Tier-3 | nothing — adds research signal |

T5 note: SPEC-376 and the corroboration finding require ranking be computed from a
deterministic rule, not an LLM's plausibility judgment. A pinned embedding model at a fixed
threshold is *more* compliant than the current Sonnet-arbiter dedup, not less.

T6 note: LOW/MEDIUM SQC sample rates (5%/15%) are set partly by cost. An unmetered lane can
run a supplementary adversarial pass at up to 100% of LOW, producing a much denser
escaped-defect estimator. It is a second estimator, never a gate.

---

## 5. Architecture

### 5.1 Transport

The GPU host is a **separate machine**. `OVERSIGHT_LOCAL_URL` points at an Ollama-compatible
`/api/chat` endpoint over the LAN or a WireGuard/Tailscale address.

Security requirements (Ollama ships with no authentication):
- The host MUST NOT bind `0.0.0.0` on a publicly routable interface.
- Reachability MUST be over a private overlay (Tailscale/WireGuard) or an SSH tunnel; a
  bare LAN bind is acceptable only on a trusted network and MUST be recorded as such.
- Optional `OVERSIGHT_LOCAL_TOKEN` bearer credential, read from an uncommitted file.
- Prompt payloads contain source diffs and prompt artifacts. Egress to an operator-owned
  host is a *privacy improvement* over a vendor CLI, but only if the transport is private.

### 5.2 Dispatch

Add `local)` to `call_model()` (`run_panel.sh:129-137`), alongside the existing `ipcheck)`
case — which is already the precedent for a panel participant that is not a vendor CLI.
A new `scripts/oversight/local_model.py` provides:

```
local_model.py probe                       → exit 0 healthy | 1 unreachable | 2 misconfigured
local_model.py call --task <T> --in FILE   → stdout JSON, exit non-zero on any fault
local_model.py embed --in FILE             → stdout vectors
```

Task→model routing lives in `scripts/oversight/local-models.toml`, not in shell.

### 5.3 Configuration (`config.sh`)

The **host FQDN is the enable switch.** There is no separate on/off flag: if the operator
has not named a host, there is no lane.

```
OVERSIGHT_LOCAL_HOST=""            # FQDN of the Ollama host. Blank/unset = lane disabled.
OVERSIGHT_LOCAL_PORT=11434         # optional, default 11434
OVERSIGHT_LOCAL_SCHEME=http        # http | https
OVERSIGHT_LOCAL_REQUIRED=0         # 1 = probe failure is a hard error (research mode)
OVERSIGHT_LOCAL_TASKS=summarize,fidelity,json-repair,triage,embed,sqc-supplement
```

**Resolution semantics:**

| `OVERSIGHT_LOCAL_HOST` | Probe | Behavior | Issue filed? |
|---|---|---|---|
| unset or blank (default) | not attempted | fallback ladder (§6.2) — this is the normal, supported path | **No** |
| set, host healthy | pass | local lane active | No |
| set, host unreachable | fail | fallback ladder + degradation record | **Yes** (§6.4) |
| set, `REQUIRED=1`, unreachable | fail | hard error, pipeline stops | Yes |

**C1 — "Not configured" is not an outage.** A blank FQDN means the operator never opted in;
the fallback path is the *designed* behavior, not a degradation. It emits no audit
degradation event, no `needs-human` issue, and no warning beyond an informational line.
Conflating "no GPU box" with "GPU box down" would file a permanent open issue on every
consumer install that never had a GPU — the single most likely way this feature becomes
hated. This is the load-bearing distinction in the whole config surface.

**C2 — FQDN, not bare IP.** A name is required so the endpoint can move (DHCP, overlay
re-address) without a config edit, and so TLS/overlay identity is checkable. A bare IP is
accepted but MUST emit a warning: it cannot be identity-verified and will silently follow a
DHCP reassignment to a different machine. `localhost`/loopback is rejected — the lane is
by definition a separate host, and a loopback value is almost certainly a copy-paste error.

**C3 — Validate at config time, not first use.** `scripts/framework/install.sh` and a
`local_model.py probe` MUST verify at configuration time that the FQDN resolves, the port
answers, and the required model tags are present. Discovering a typo'd hostname during an
autonomous 3am cron run — where the only symptom is a fallback — is exactly the class of
failure invariant I4 exists to prevent.

**C4 — Default posture for consumers.** `OVERSIGHT_LOCAL_HOST` ships blank. A consumer who
installs HOS and never touches it gets today's behavior, byte for byte, with no new
dependency, no probe latency, and no issue noise.

## 6. Unavailability handling

### 6.1 Fault taxonomy

These are NOT the same fault and MUST NOT collapse into one branch:

| Fault | Detection | Disposition |
|---|---|---|
| F1 host unreachable | probe timeout (2s) | fallback ladder + issue |
| F2 model not pulled | `/api/tags` lacks tag | fallback + issue with `ollama pull <tag>` remediation |
| F3 context too small | `num_ctx` < estimated prompt tokens | hard fail this call (I5) — never truncate |
| F4 OOM / evicted mid-call | non-2xx or empty body | treat as F1 for this call |
| F5 malformed output | schema validation fails after 1 retry | discard local result, fall back |
| F6 model drift | running tag ≠ `.hos-local-models.lock` | hard fail when `REQUIRED=1`, warn + record otherwise |
| F7 FQDN does not resolve | DNS NXDOMAIN at probe | distinct from F1 — this is a *config* fault, remediation is "fix the hostname", not "start the host" |

### 6.2 Fallback ladder (per task, not global)

Each task declares its own fallback, because "next cheapest" differs by task. **No task
falls back to `agy` or `codex` (I3).**

| Task | Fallback 1 | Fallback 2 |
|---|---|---|
| T1 summarize | `claude -p --model haiku` | skip + record `summary: unavailable` |
| T2 fidelity | `claude -p --model haiku` | `Status: NYI` (today's behavior) |
| T3 json-repair | `claude -p --model haiku` | existing `parse_prose()` → `unparseable` → CONDITIONAL_PROCEED |
| T4 triage | `claude -p --model haiku` (current behavior) | deterministic floor alone (conservative) |
| T5 dedup | `reconcile_membership()` file+line ±5 (exists today) | — |
| T6 sqc-supplement | **skip** — supplementary only | — |

Haiku is the substitute of record because it is subscription-covered, i.e. it consumes the
budget HOS already treats as tracked-for-awareness rather than the constrained
`agy`/`codex` quota.

### 6.3 Degradation must be visible, never silent

1. **Audit event.** Append `local_lane_degraded` to `audit/oversight-log.jsonl` with fault
   code, task, and substitute used.
2. **Token accounting.** Record substitute usage under vendor `local-fallback:haiku` in
   `token_tracker.py` so an outage's cost appears in the report rather than hiding inside
   normal Claude usage.
3. **Artifact annotation.** Any artifact produced by a substitute carries
   `produced_by: fallback(haiku) — local lane unavailable (F1)`. An artifact must never
   claim provenance it does not have (I6).
4. **`required` mode fails closed** — consistent with `run_validators.sh` fail-closed
   behavior; it does not degrade.

### 6.4 GitHub issue on unavailability

On first transition healthy→unavailable:

- Create ONE issue, `--label needs-human,priority:medium`, `--assignee @me`, milestone
  unset, titled `local-inference: GPU host unavailable (<fault>)`, body carrying fault code,
  endpoint, last-success timestamp, affected tasks, active substitutes, and remediation.
- **Idempotency is mandatory.** `bin/hos-cron` fires on a schedule; a naive implementation
  files an issue every cycle. Dedup on a stable marker line
  `<!-- hos-local-lane-outage:<endpoint-hash> -->` searched via
  `gh issue list --state open --search`. If found: append a comment with an occurrence
  counter (rate-limited to ≤1 comment/hour), do not open a second issue.
- **Circuit breaker.** After 3 consecutive probe failures, write
  `.claudetmp/oversight/local-lane.state` = `degraded`, and back off probing to once per
  15 minutes so every pipeline stage does not pay a 2s timeout.
- **Recovery.** On the first successful probe after degradation, comment "recovered at
  <ts>, outage duration <d>" and close the issue. State returns to `healthy`.

---

## 7. Hardware utilization plan (RTX 3090 24 GB / Ryzen 7 5800X 8C-16T / 64 GB DDR4)

**Binding constraint: everything must fit in VRAM.** With 8 Zen 3 cores on dual-channel
DDR4 (~50 GB/s vs. the 3090's ~936 GB/s), partial CPU offload is roughly an order of
magnitude slower. Any configuration that spills layers to system RAM is a misconfiguration,
not a tradeoff. 64 GB of system RAM is useful for model staging and the embedding index —
not for inference.

Ampere has no FP8/FP4 path, so quantization is GGUF `Q4_K_M` / `Q5_K_M` (or AWQ INT4).

**Two-slot residency policy** (VRAM budget ≈ 22 GB usable):

- **Slot A — always resident (~10 GB).** A 14B-class instruct model (Qwen2.5-Coder-14B or
  Phi-4) at Q4_K_M (~9 GB) plus `bge-m3` embeddings (~1 GB). Serves T3 json-repair,
  T4 triage, T5 embed, and T1 summarize. Low TTFT, no model swap.
- **Slot B — on-demand (~14–18 GB).** Either Mistral-Small/Devstral-24B Q4_K_M (~14 GB,
  leaves ~8 GB for KV → comfortable 32–64k context) or Qwen3-Coder-30B-A3B Q4_K_M (~18 GB,
  3B active → very fast, but only ~4 GB KV). Serves T2 fidelity and T6 SQC pass.
- Loading Slot B evicts Slot A. **Therefore batch same-model work; never interleave.**
  A cold 18 GB load from NVMe costs ~10–20 s.

Recommended daemon settings:
`OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`
(≈halves KV footprint → materially more context), `OLLAMA_NUM_PARALLEL=1` (parallel slots
divide `num_ctx` — a silent truncation vector, see I5), `OLLAMA_MAX_LOADED_MODELS=2`.

**Highest-leverage uses of the box beyond the six tasks:**

1. **Repo-wide embedding index** (bge-m3 over source, specs, ADRs, `audit/oversight-log.jsonl`).
   Enables tight context packing for paid calls — input tokens dominate review spend, and
   SPEC-379 already argues *less* context detects better. Batch-encoding the corpus is a
   minutes-scale job on a 3090.
2. **Overnight backfill as a research instrument.** The box is idle at night and `hos-cron`
   already runs unattended. Re-review the merged history with the local model and compare
   its findings against what the paid panel actually reported. That yields an empirical
   local-vs-frontier agreement rate — the evidence needed before trusting the lane anywhere
   further. This is the single most valuable use of the hardware: it converts a cost lever
   into a measurement.
3. **Dense SQC sampling** (T6) for a better escaped-defect estimator.
4. **Offline curation of `hallucination_surface.py`'s hardcoded `_KNOWN_RISKY` list** —
   batch-propose candidate version-sensitive APIs for human review, outside the loop.

**Honest cost note:** a 3090 under sustained load draws ~350 W. A 24/7 cron lane is a real
electricity cost that partially offsets subscription savings, and should be measured rather
than assumed away.

---

## 8. Rejected alternatives

- **Local model as a cross-vendor vote.** Violates I2/D4.
- **Local model as a pre-filter that skips paid reviewers.** Violates I1 — it would be a
  loosening determination made by the weakest model in the system.
- **Single global fallback vendor.** Collapses the fault taxonomy and, if set to agy/codex,
  inverts the cost intent (I3).
- **Running the lane inside CI.** D5: the panel runs locally against subscription auth; the
  GPU host is likewise operator-owned and not CI-reachable.

## 9. Open questions for the panel

- OQ-1: Should `LOCAL_INFERENCE=preferred` be permitted for **research** runs at all, given
  that a mid-run substitution changes the data-generating process? Or is `required` the only
  legitimate research mode?
- OQ-2: Does T5 (embedding dedup) require a SPEC amendment to SPEC-376, or is a pinned
  deterministic embedder already within its "deterministic rule" language?
- OQ-3: Is Haiku-as-substitute acceptable for T2, given the check does not exist today —
  i.e. does a fallback that spends budget on a brand-new additive check need its own opt-in?

---

## 10. Design panel outcome (2026-08-31)

Six independent reviewers: `agy` + `codex` (cross-vendor) and `architect`, `security-reviewer`,
`reliability-reviewer`, `infra-reviewer`, `ops-reviewer` (HOS panel). **All six returned
request_changes / CONDITIONAL.** None rejected the concept; the consistent theme is that the
invariants are correctly reasoned but **under-enforced** — I1, I5, and I6 are stated as
properties without mechanisms that guarantee them.

This document is therefore **superseded in its details** by the issue set filed under epic
**#1455** (milestone v0.6.1). Do not implement from this draft — see #1455 for the ranked
findings, the architect's rulings on OQ-1/2/3, and the required ADR-034.

Top corroborated findings (independent-source count in brackets):

- **#1457 [4]** T3 JSON repair can mutate/fabricate vendor findings; fail-open to CONDITIONAL_PROCEED
- **#1459 [4]** I5 truncation guard has no teeth — an estimate cannot enforce it; use `prompt_eval_count`
- **#1460 [5]** transport security is unenforceable prose; plaintext + optional auth
- **#1458 [3]** T5 embedding dedup is a D52 suppression path — must be additive-only (new invariant I7)
- **#1462 [4]** an Ollama tag is not a model identity — pin by digest
- **#1461** no inference-call timeout is specified anywhere
- **#1465** telemetry schema gaps (verified against `token_tracker.py:249`)

Later operator constraints not reflected above: the GPU host is **shared** with other
workloads (#1470 — reject 32B, consolidate on a 14B + embeddings pair, add VRAM admission
control), and outage memory must be cleared by **recovery, not a timer** (#1463, #1464).

Adjacent architecture question raised during the panel: **#1471** — add an adversarial
verification phase (detector-then-validator) to the cross-vendor panel. The local lane is
what makes that phase affordable.
