# Session: v0.4.0 Implementation — Unattended Worker (#254) + Machine Accounts Phase 0 (#152)

**Date:** 2026-06-16
**Branch:** `feat/254-unattended-worker-impl`

---

## What was built

Full implementation of the HOS unattended worker subsystem (all 15 build steps, Phases A/B/C) and the machine accounts Phase 0 deliverables. 641 tests passing.

### #152 Phase 0 (machine accounts)
- `provision_agent_account.sh` — configure git/gh as worker or overseer bot
- `setup_branch_protection.sh` — apply §9 tiered-approval rules via gh api
- `Supervised-by:` trailer wired into AGENTS.md and PR template
- Branch protection live on `main` (enforced)

### #254 Phase A (safety foundation)
- `github.py` — REST-by-id wrapper, never exposes Search API
- `correlation.py` — cid derivation (sha256[:12]), artifact naming, idempotency precheck, cold-start state machine
- `config_resolver.py` — 4-layer config with narrow-only governance enforcement
- `activation.py` — two-key enable: AND-gate of repo authorization + operator activation
- `machine_lock.sh` — mkdir-atomic machine-global lock (bash 3.2, ADR-3 spawn-scope)
- `merge_authority.py` (detection half) — O3 gate detection, DEP[#152-followup] stub → PROPOSE_ONLY

### #254 Phase B (loop body)
- `ledger.py` — append-only per-run JSONL, summation-at-read (read-your-writes)
- `budget.py` — O5 token estimation (heuristic, no model), per-task/window gates
- `envelope.py` — machine-readable hos-envelope protocol, idempotency, version negotiation
- `probe.py` — token-free REST probe (never Search), adaptive cadence, per-customer quota
- `claim.py` — claim-then-verify (UUIDv4, lowest-id wins), heartbeat, terminal release
- `triage.py` — bug|feature|communication|security-report|spec-gap; security asymmetric
- `codeowners.py` — CODEOWNERS parse, last-match-wins, actor authorization (O19)
- `merge_authority.py` (full matrix) — tier × security × protected-surface × verdict gate; --class worker|overseer

### #254 Phase C (orchestration)
- `hos_orchestrator.sh` — 7-gate order: git pull → activation → halt → lock → config → probe → spawn
- `hos_worker.sh` — full triage→build→merge chain; heartbeat rechecks activation+halt
- `breakers.py` — failure cap, blast-radius, rate-limit, max-runtime, dead-man switch
- `observability.py` — JSONL-first + derived Markdown log, activity_report
- `self_review_source.py` — auto-file findings, fingerprint dedup (O6), suppression ledger (O9)
- `multi_customer.py` — round-robin + stagger, isolation, kill switches
- Operator guide doc

---

## Research findings filed

- `correctness-via-artifact-naming-not-coordination.md` — content-addressable cid naming eliminates duplicate-work structurally; the lock is a contention reducer, not a correctness mechanism
- `governance-config-currency-gap.md` — an autonomous loop reading governance config from a local checkout has a propagation latency; pre-run `git pull` bounds but does not eliminate it
- `two-key-enable-for-autonomous-systems.md` — separating repo authorization (committed, CODEOWNERS-gated) from operator activation (machine-local, non-synced) prevents self-enablement and provides three orthogonal shutdown controls

---

## Notable design decisions

- **Two-cronjob model** (spec §11a): worker at 0,30 / overseer at 15,45; 15-minute stagger; machine lock remains machine-global.
- **ADR-2 correctness**: cid is the only M1 guarantee; lock, claim, and activation are all contention reducers on top.
- **DEP[#152-followup]**: merge_authority.py detect_server_side_gate returns PROPOSE_ONLY until the risk-tier-vs-ceiling CI check ships — intentional fail-safe, not a bug.
- **Issue #300**: pre-run `git pull` added as step 0; the governance config currency gap is documented as a research finding and a known limitation.
