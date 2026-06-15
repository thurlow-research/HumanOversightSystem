# Technical Design — Unattended Worker & Customer↔HOS Coordination Protocol (#254, v0.4.0)

**Status:** coder-ready technical design. Derived from `docs/specs/UNATTENDED-WORKER-PROTOCOL.md` (the normative PRD) and the architect's GO-approved ADR set (ADR-2/ADR-3 + the binding invariants below). This document specifies *contracts* — file formats, GitHub object shapes, exact algorithms, gate ordering, failure handling, and R-number coverage — not implementation code.

**Author:** technical-design agent. **Architect:** GO given; ADR-2/ADR-3 + read-your-writes + O3/O6/O9/O15/O17/O18 invariants are **binding inputs**, not relitigated here.

**Target stack:** bash (macOS bash 3.2 floor — **no `flock`**) + Python 3.10+ stdlib-first, matching `scripts/framework/` and `scripts/oversight/` conventions (colours, idempotency, `doctor`, stdlib-only where possible; `schema.py`-style result envelopes for scored signals).

**Scope note:** this is the #254 unattended-worker design. The #152 completion follow-ups (the risk-tier-vs-ceiling status check; `provision_agent_account.sh`; branch-protection-as-code) are a **separate small track** per `AGENT-IDENTITY.md §10b`. They are a hard **dependency** of T10/merge-authority detection (R9.1.1 re-checks the overseer's bypass standing, which that track configures), but they are **not designed here**. Where this design depends on them, it is called out as `DEP[#152-followup]`.

---

## 0. Binding ADR inputs (design to these; do not relitigate)

These are reproduced verbatim from the architect's ruling so every component below can cite them.

- **ADR-2 (keystone — M1 correctness).** M1 (zero duplicate work) derives **solely** from R6.1 deterministic correlation-id:
  `cid = sha256(issue_url + "#" + issue_number)[:12]` (hex) → branch `hos/auto/<cid>`. Every lock/claim/activation layer is a **contention reducer** on top. **Any design that makes correctness depend on a lock is a regression.**
- **ADR-3 (resolves RACE-1 — lock scope).** The §7.5 machine lock `/tmp/hos-worker.lock` guards the **probe → claim → dispatch(SPAWN)** critical section **only**. It is **released once per-task workers are spawned**, NOT held for the per-task worker's full runtime. Per-task worker exclusivity is owned by the §7 GitHub claim + heartbeat. A **separate short `orchestrator_lock_timeout` (~20m)** detects machine-lock hangs, distinct from per-task `max_task_runtime` (4h). **Dispatch = spawn, not run-to-completion.**
- **Read-your-writes invariant (binding).** Every correctness-sensitive read — claim re-verify (R7.1), cost-ledger summation (R8.2), blast-radius window (R11.2), the R6.1 "does a branch already exist?" idempotency check — **MUST read the authoritative REST object by id**. The Search API is for **cold reconciliation only** (R10.1b). No correctness path may call Search.
- **O3 →** server-side-gate detection = **protection-API read + overseer-bypass-standing verification** (NOT a live no-op canary) in v1.
- **O6 →** exact-key `(sorted files, finding-class)` fingerprint ledger in v1; fuzzy-match deferred to v2; **record the RAW finding text** for later reconcile.
- **O9 →** suppression ledger = **HOS-shipped baseline + per-repo overlay**.
- **O15 →** per-customer API-call budget exists; **quota-aware round-robin**; **staggered probe starts**.
- **O17/O18 invariants.** ONE machine-global lock path resolved **identically** by every per-repo cronjob (config constant, not per-repo). PID liveness check = **alive-AND-command-match** (`ps -p <pid> -o command=` vs the orchestrator script + the `hos-orchestrator` marker), **NEVER bare `kill -0`**.

**Self-flag (this document is authoring):**
`RISK: MEDIUM` · `CONFIDENCE: HIGH` · `BLAST RADIUS: new subsystem; adds `scripts/automation/` modules; consumes the existing #152 protected-surface gate and config conventions; no edit to shipped gate/validator behavior.`
Change class: **additive** (a new subsystem; no existing contract rewritten). The protected-surface set is *extended* by adding two paths (`hos-halt`, `PROJECT/hos-coordination.yaml`) — that edit to `protected_surfaces.txt` is itself a protected-surface change and routes to human at build time (noted in T10/T2). No `structural` change to an existing contract is introduced by this design, so no pre-write human escalation is required; the protected-surfaces edit is flagged for the coder.

---

## 1. Module layout & boundary map

All new code lives under `scripts/automation/` (new) for the loop, with shared scored-signal helpers reusing `scripts/oversight/validators/schema.py`. Python is stdlib-first (the loop must run on a cold box); `gh` + `git` are the only external binaries on the hot path.

```
scripts/automation/
  hos_orchestrator.sh        # entrypoint; the cron target. Holds the machine lock.
                             #   gate order: activation → hos-halt → machine-lock → probe → claim → dispatch(spawn)
  hos_worker.sh              # per-task worker entrypoint (spawned by orchestrator); triage→gates→merge for ONE cid
  lib/
    config_resolver.py       # T2  — 4-layer resolve + activation AND-gate (component: config-resolver)
    activation.py            # T2  — ~/.hos/<repo-id>/ACTIVE contract + repo-id slug + hos activate/deactivate
    machine_lock.sh          # T8  — mkdir-atomic lock, holder inspection, hang timeout, trap cleanup
    probe.py                 # T4  — REST/GraphQL token-free probe, cadence, round-robin, stagger
    envelope.py              # T5  — parse/emit hos-envelope, threading DAG, idempotency, version negotiation
    triage.py                # T6  — classes, confidence floor, asymmetric security, severity, benefit≫risk gate
    claim.py                 # T8  — claim-then-verify, instance-id, heartbeat, timeout, terminal release
    correlation.py           # T7  — cid derivation, artifact-name resolution, idempotency probe (REST-by-id)
    ledger.py                # T9/T14 — append-only per-run cost/action JSONL + manifest + summation reads
    budget.py                # T9  — per-task estimate, per-window budget, default-deny, mid-flight re-ask
    merge_authority.py       # T10 — gate detection (O3), matrix, PROPOSE_ONLY, no-release guard
    self_review_source.py    # T12 — validate_self auto-file, fingerprint dedup, suppression ledger, burndown
    breakers.py              # T13 — failure cap, blast-radius window, rate-limit, max-runtime, dead-man
    observability.py         # T14 — JSONL-first + derived Markdown activity log
    codeowners.py            # O19 — CODEOWNERS parse + label-actor verification
    github.py                # shared gh wrapper: REST-by-id reads, rate-limit honoring, retries
  fixtures/                  # test corpora: O14 ack-patterns, O19 CODEOWNERS edge cases, envelope samples
```

**Boundary contract — what each module must NOT assume:**
- `probe.py` must **never** invoke a model and **never** call the Search API on the hot path (R10.1b). Its only outputs are candidate work-item ids; it does no triage.
- `correlation.py` is the **single** owner of the cid algorithm and artifact-name strings. No other module re-derives a branch name.
- `claim.py` must **not** be relied on for correctness (ADR-2). It reduces contention; M1 lives in `correlation.py`.
- `merge_authority.py` must **re-check** gate detection immediately before each merge (R9.1.1) — it must not trust the cached config flag for the merge decision.
- `ledger.py` must **never** mutate an existing record — append-only, per-run files, summation at read.

---

## 2. config-resolver  (T2 · R13.1–R13.3 · O1)

### Responsibility
Resolve effective config from 4 layers (later overlays earlier, **narrow-only**), and expose the activation AND-gate as the **first** thing the orchestrator calls. Repo authorization (`enabled`) is layer 2a; operator activation is **not a config layer** (§3 of this doc).

### Data structures / file formats

**Layer 1 — shipped defaults** (`scripts/automation/hos-coordination.defaults.yaml`, inert, `enabled: false`). Schema is the §13 PRD YAML verbatim.

**Layer 2a — governance config** (consumer repo): canonical path **`PROJECT/hos-coordination.yaml`** (O13 resolved; on the protected surface, R9.1.3-gc). HOS's own dogfood copy lives at `PROJECT/hos-coordination.yaml` in the HOS repo, committed + CODEOWNERS-gated. Carries only: `enabled`, `thresholds.*`, `requester-allowlist`, `mode` floor, `security-sensitive-paths`, cadence/self-review **floors**.

**Layer 2b — operational soft state** (`.ai-local/hos-automation/`, gitignored): `cadence-state.json` (per-repo back-off level + last-poll ts), `instance-state.json`. MUST NEVER contain `enabled`/thresholds/allowlist/mode.

**Layer 3 — runtime env** (`HOS_AUTO_*` env vars): narrow-only.

**Effective config object** (in-memory dict, validated):
```
{ customer, enabled, protocol_version, mode, requester_allowlist[],
  security_sensitive_paths[], thresholds{...}, cadence{floor,ceiling},
  self_review{cadence,cross_vendor}, claim{timeout,heartbeat},
  breakers{...}, suppression{default_ttl,nag_lead_days} }
```

### Algorithm — `resolve(repo_root) -> EffectiveConfig`
1. Load layer 1 defaults.
2. Overlay layer 2a from `PROJECT/hos-coordination.yaml` if present.
3. Overlay layer 2b soft state (cadence/last-poll only).
4. Overlay layer 3 env (`HOS_AUTO_*`).
5. **Narrow-only enforcement (R13.1):** after each overlay, for `enabled`, `thresholds.*`, `requester-allowlist`, `mode`: a later layer may only *narrow*. Concretely:
   - `enabled`: `false` at any earlier layer is an **absolute veto** — no later layer may set `true`. (`effective.enabled = AND of all layers that specify it`.)
   - `thresholds`: `effective = min(layer values)` for each numeric threshold (tighter = smaller budget).
   - `requester-allowlist`: `effective = intersection` (a later layer may only remove members).
   - `mode`: `propose-only` floor wins; a later layer may force `propose-only` but never `autonomous` (also gated by detection, §10).
   Any attempted widen is **logged and dropped** (not fatal), with the narrowed value used.
6. **Fatal config errors (exit non-zero at load):** `self_review.cadence < 24h` (R3.2.2 hard floor); a layer-2b file containing any governance key (R13.3 violation); a malformed YAML.

### Failure handling
Missing layer-2a file → `enabled` stays `false` (inert), no error. Unreadable layer-2a → fatal (cannot safely assume authorization). Soft-state corruption → discard layer 2b, fall back to cadence floor (R10.5), warn.

### Requirements implemented
R13.1 (narrow-only incl. layer-3 veto), R13.2 (repo authorization half), R13.3 (source ships unconfigured; governance in PROJECT; soft state in `.ai-local/`), R3.2.2 (24h floor fatal), O1 (path + resolution order resolved below).

### O1 resolution (technical-design's call)
- Governance-config path: **`PROJECT/hos-coordination.yaml`** (already pinned by R9.1.3-gc).
- Resolution vs `config.sh`: `config.sh` (the existing framework config) is **orthogonal** — it configures the *validation suite*, not the loop. The loop's resolver reads `PROJECT/hos-coordination.yaml` directly and does **not** merge `config.sh`. The one tie-in: `config.sh`'s `PROJECT_NAME` seeds the default `customer` slug if layer-2a omits it. Resolution order is layers 1→2a→2b→3 as above; `config.sh` is consulted only for the `customer` default.

---

## 3. activation-gate  (T2 · R13.2 · R13.4 · O16 closed, MF-4)

### Responsibility
The **very first action on every cron wake**, before any probe, GitHub API call, or model invocation. Decides ACTIVE/OFF for *this machine, this repo*. Not part of the 4-layer chain — an independent AND condition. `hos activate`/`hos deactivate` helpers manage the file.

### Data structures / file formats

**Activation file:** `~/.hos/<repo-id>/ACTIVE` (external to repo; never committed/synced).

**`<repo-id>` slug (MF-4 — the canonical algorithm; single source of truth):**
1. Read `git remote get-url origin`.
2. Normalize to `<owner>/<repo>`: strip scheme/host from both `https://github.com/owner/repo.git` and `git@github.com:owner/repo.git`; strip trailing `.git`.
3. Lowercase; replace `/` with `-`. Result: `owner-repo`. Example: `https://github.com/ScottThurlow/HumanOversightSystem.git` → `scottthurlow-humanoversightsystem`.

**File content contract (G3):** a single line — the machine-binding token: either `hostname -f` output or a per-machine UUID written by `hos activate`. (`hos activate` writes `hostname -f` by default; `--uuid` writes a generated UUID and records it for future comparison in `~/.hos/<repo-id>/MACHINE-TOKEN`.)

### Algorithm — `check_activation(repo_root) -> ACTIVE | OFF`  (fail-closed)
1. Derive `<repo-id>`.
2. `path = ~/.hos/<repo-id>/ACTIVE`. If not a readable regular file → **OFF**.
3. Read, trim whitespace. If empty → **OFF**.
4. Compute this machine's canonical token (`hostname -f`; or the recorded UUID if `MACHINE-TOKEN` exists). If file token ≠ machine token → **OFF**.
5. Else → **ACTIVE**.

Any branch to OFF: the orchestrator emits **at most one** `"inactive — exiting"` log line and exits 0. **Zero** other activity (no probe, no API call, no model). "Off" = ZERO activity, not "no work performed."

**`hos activate [<repo-id>]`:** derive repo-id from cwd remote, `mkdir -p ~/.hos/<repo-id>`, write the machine token to `ACTIVE`, print confirmation. **`hos deactivate`:** `rm -f ~/.hos/<repo-id>/ACTIVE`.

### Failure handling
ABSENT / EMPTY / UNREADABLE / token-mismatch → OFF unconditionally (never overridable to on-by-assumption). A dotfile-synced file from another machine reads OFF because the token won't match. In-flight per-task workers recheck activation at **every heartbeat** (§7) and self-terminate on OFF.

### Requirements implemented
R13.2 (operator-activation half + two-condition AND), R13.4 (full activation contract, slug, content token, helpers, non-propagating, fail-closed), MF-4 (slug algorithm), O16 (path resolved).

---

## 4. machine-lock  (T8 · §7.5 · ADR-3 · O17 · O18)

### Responsibility
Enforce **at most one orchestrator process machine-wide** for the **probe → claim → dispatch(spawn) critical section only** (ADR-3). Released once per-task workers are spawned. The PRIMARY single-worker enforcer (R7.5.7); GitHub claim is the cross-machine backstop.

### Data structures / file formats
**Lock = a directory** (mkdir is the atomic mutex; `flock` forbidden on bash 3.2). 

**O17 resolution — exact path + fallback:**
- Canonical path constant (a **config constant resolved identically by every per-repo cronjob**, O17/O18 invariant): `HOS_LOCK_DIR="/tmp/hos-worker.lock"`.
- **Fallback:** if `/tmp` is not writable (probe `[ -w /tmp ]` at startup), fall back to `${HOME}/.hos/worker.lock` — still **machine-global** (one path per machine, shared across all repos), NOT per-repo. The chosen path is recorded in the metadata and logged so all cronjobs agree. The resolution function `resolve_lock_dir()` lives in `machine_lock.sh` and is the single source; it must return the same value for every repo's cron on a given machine (it depends only on `/tmp` writability, not on repo identity).

**Metadata file** `${HOS_LOCK_DIR}/meta` (written immediately after a successful mkdir), three lines:
```
pid=<orchestrator pid>
started=<ISO-8601 UTC>
marker=hos-orchestrator
```

### Algorithm — acquire (R7.5.3)
1. **Jitter:** `sleep $((RANDOM % 61))` (0–60s) — load-spread only, NOT mutual exclusion.
2. **Atomic acquire:** `mkdir "$HOS_LOCK_DIR"` (NO check-then-create — TOCTOU forbidden).
3. **On success (won):** write `meta`; install `trap` (step "cleanup"); proceed to probe/dispatch.
4. **On failure (contention):** go to holder inspection.

### Algorithm — holder inspection on contention (R7.5.4 · O18)
1. Read `pid` from `meta`. If `meta` unreadable/missing → treat as stale, reclaim (step 4 below).
2. **Liveness + identity (alive-AND-command-match — NEVER bare `kill -0`):**
   `ps -p <pid> -o command=` → `cmd`.
   **O18 resolution — exact match pattern:** the holder is a legitimate orchestrator iff `cmd` contains **both** the orchestrator script basename `hos_orchestrator.sh` **and** the marker token `hos-orchestrator`. Concretely:
   `printf '%s' "$cmd" | grep -q 'hos_orchestrator\.sh' && printf '%s' "$cmd" | grep -q 'hos-orchestrator'`.
   The orchestrator guarantees the marker is present in its own command line by `exec`-ing with an argv element `hos-orchestrator` (e.g. the cron line runs `hos_orchestrator.sh hos-orchestrator`), so `ps -o command=` shows both tokens. Rationale: basename-only is too broad (a developer running the script by hand, an editor, a grep of the path would false-match the bare path; requiring the explicit `hos-orchestrator` argv marker plus the script name makes a recycled-PID collision astronomically unlikely while surviving path variations across machines).
3. **HUNG check (R7.5.5 — takes precedence over alive):** read `started`; if `now - started > orchestrator_lock_timeout` → HUNG. (See note below: ADR-3 splits this from `max_task_runtime`.) HUNG ⇒ reclaim **AND fire the dead-man's-switch / page** (R11.5); never silently reclaim a HUNG lock.
4. **Stale (dead OR command-mismatch, and not within timeout):** `rm -rf "$HOS_LOCK_DIR"`; retry acquire **once** from the jitter step; log `stale-lock-reclaim`.
5. **Alive AND command-match AND not hung:** legitimate holder → **abort this run**, wait for next cron window; log `lock-contention`.

**ADR-3 `orchestrator_lock_timeout` note (binding):** the hang timeout for the *machine lock* is a **separate, short** `orchestrator_lock_timeout` (default **20m**) — NOT `max_task_runtime` (4h). The machine lock only covers probe→dispatch(spawn), which should complete in minutes; a 20m hold is already anomalous. (The PRD R7.5.5 text says `max_task_runtime`; ADR-3 supersedes it here because the lock is released at spawn, not held for the 4h task. This is the one place the design deviates from the PRD prose, on the architect's binding ruling — recorded as a `startup-artifact-gap` candidate in §16.)

### Algorithm — cleanup (R7.5.6)
`trap 'rm -rf "$HOS_LOCK_DIR"' EXIT TERM INT`. `/tmp` clearance on reboot is the backstop. The trap removes the lock at **spawn-completion exit** of the orchestrator (ADR-3: the orchestrator process exits after dispatch; per-task workers are separate processes spawned detached — they do NOT hold the lock).

### Dispatch = spawn (ADR-3, pinned)
After claiming + deciding to work an item, the orchestrator **spawns** `hos_worker.sh <cid>` as a **detached background process** (e.g. `nohup ... &` / `setsid`), records the spawn in the ledger, and continues. Once all found work is spawned, the orchestrator **releases the lock and exits**. Per-task worker lifetime (up to 4h) is governed by §7 claim+heartbeat + `max_task_runtime`, **not** the machine lock.

### Requirements implemented
R7.5.1–R7.5.7, ADR-3 (lock scope + orchestrator_lock_timeout split), O17 (path + fallback), O18 (ps match pattern).

---

## 5. probe  (T4 · §10 · §12 · R10.1b · O15)

### Responsibility
Token-free "is there work?" sweep across N customer repos, round-robin, quota-aware, staggered. Outputs candidate work-item ids only. **Runs only after activation + hos-halt pass** (gate order, §11 of this doc).

### Data structures / file formats
**Cadence state** (`.ai-local/hos-automation/cadence-state.json`, soft, floor-fallback):
```json
{ "<repo-id>": { "backoff_level": 0, "last_poll": "<ISO-8601>", "next_due": "<ISO-8601>",
                 "pinned": false, "pin_reason": null, "pin_since": null } }
```
**API-call budget state** (`.ai-local/hos-automation/api-budget.json`): `{ "<repo-id>": { "window_start": "<ISO>", "calls_used": <int> } }`.

### Algorithm — `probe_cycle(config, repos)`
1. **Window/blast-radius pre-check (R11.2):** read the rolling-24h ledger (REST-by-id-backed cost records; §8 of this doc) and the per-run blast-radius totals. If any window cap (5 PRs / 10 issues / 25 files) is already met → **do not claim new work this cycle**; page (R11.2) and continue only with already-claimed in-flight bookkeeping.
2. **Round-robin order (R12.2):** iterate customers in a rotating order; **stagger** start by `floor / N_repos` offsets (compute the per-repo offset; skip a repo whose `next_due` is in the future).
3. **Per-repo quota gate (R12.1, O15):** if `api-budget.calls_used >= per_customer_api_budget` for the window → **skip** this repo until window reset; log.
4. **Probe query (R10.1b — REST list or batched GraphQL, NEVER Search):**
   - REST: `GET /repos/{owner}/{repo}/issues?since=<last_poll>&state=open&labels=hos-coordination` plus a second `since` list for non-coordination new issues/PRs; **or** a single batched GraphQL query across repos (`search` node is forbidden — use `repository(...).issues(filterBy:{since})`). Increment `calls_used`.
   - **Cold reconciliation only** (R10.1b): the Search API may be used **once** on a cold start to find orphaned `hos-claimed`/`hos/auto/*` artifacts; never on the hot path.
5. **Coordination-label actor verification (R4.1.4):** for each item tagged `hos-coordination`, read the label event actor (`GET /repos/{o}/{r}/issues/{n}/events`, find the `labeled` event for `hos-coordination`); if actor ∉ allowlist → skip + log. (Adds API cost; counted against quota.)
6. **Cadence update (R10.2/R10.3/R10.4/R10.5):**
   - Inbound event found → reset this repo to floor (`backoff_level=0`).
   - No activity → `backoff_level += 1`, `next_due = now + min(floor * 2^level, ceiling)`.
   - **Priority pin (R10.4):** open `P0` / unanswered coordination / `hos-embargo` pins to floor. Unanswered-coordination pin has a max duration (`pin_max=72h`): on expiry → label `needs-human`, release pin.
   - On cold start with no cadence state → start at floor (R10.5, safe).
7. **Output:** a deduped list of `(repo, issue/PR number, url)` candidates for the claim/dispatch stage.

### Failure handling
Honor `X-RateLimit-*` (R11.3): on remaining-near-zero, exponential backoff, never hammer; record in ledger. A single repo's probe failure (rate-limit, network) is isolated (R12.3) — log, skip that repo, continue the round-robin.

### O15 resolution — per-customer API-call budget default
The REST core bucket is **5000 req/hr per machine-account**, shared across all customers on that account. Budget so the busiest plausible fleet stays under it with headroom:
- Per probe cycle, a repo costs ≈ 1 list call + (1 events call per coordination item). Default **`per_customer_api_budget = 300 calls / rolling 1h window`**. With a 15m floor that is ≤4 cycles/hr × ~75 calls headroom per cycle — comfortably under 5000/hr even at ~15 active customers. Calibration constant; tune per-customer. Quota-aware round-robin skips a customer that hits 300 until its window resets.

### Requirements implemented
R10.1–R10.5, R10.1b (REST/GraphQL not Search; cold-reconcile carve-out), R11.2 (window pre-check), R11.3, R12.1, R12.2, R12.3, R4.1.4 (label-actor verify on probe), O15 (budget default).

---

## 6. coordination envelope  (T5 · §4)

### Responsibility
Parse/emit the machine-readable `hos-envelope`; build the threading DAG; enforce at-least-once idempotency; protocol-version negotiation; requester-allowlist authn (against the **GitHub-API-verified author**, not the envelope `from:`).

### Data structures / GitHub object shapes
Envelope = a fenced ```` ```hos-envelope ```` YAML block in an issue/comment body + the marker line `<!-- 🤖 [AI: claude] hos-envelope v1.0 -->`. Fields per §4.1 (`protocol-version`, `type`, `from`, `to`, `correlation-id`, `in-reply-to?`, `priority`, `signature`). `type` vocabulary includes the added `nag` and `suppression-expired` (R3.2.6).

**Parsed envelope object:**
```
{ protocol_version, type, from, to, correlation_id, in_reply_to|None,
  priority, signature, github_author (from comment.user.login), raw_body }
```

### Algorithm
- **Emit:** every autonomous message carries an envelope + the marker. The `correlation-id` of an **originator** is the work-item `cid` (correlation.py); a reply sets `in-reply-to` to the message it answers.
- **Parse:** extract the fenced block; if absent and the comment is inbound → default `{from: human, type: question}` (R4.1.1) **after** the R4.1.1 guards (below).
- **Threading DAG (R4.1.2):** "already answered?" = does an `answer` envelope exist with `in-reply-to == this.correlation_id`? Deterministic lookup over the issue's comments (REST-by-id read of the issue + comments), never NL inference.
- **Idempotency (R4.1.3):** every consumer keys on `correlation-id`; reprocessing the same id is a no-op. GitHub is the dedup store.
- **Allowlist authn (R4.3.1/R4.3.2):** check `github_author` (`comment.user.login` / `issue.user.login`) against `requester-allowlist`. The envelope `from:` is **routing only**, used **after** the author check passes. Off-allowlist author → ack + route to human, never autonomously actioned, regardless of `from:`.
- **Version negotiation (R4.2):** `protocol-version` mandatory. Unsupported version → post `type: ack` + `unsupported-version` error, route to human. Floor-based: operate at `min(supported)`; major mismatch (`2.x`↔`1.x`) → human.

### R4.1.1 envelope-less / chatter guards (O14)
Before routing an envelope-less inbound comment to triage:
- **(a) Terminal-state skip:** if the issue carries `needs-human` / `hos-embargo` / `hos-halt` **or is closed** → ignore entirely.
- **(b) Acknowledgment-pattern skip (O14):** if the comment matches the configurable ack-pattern list → log + do not triage.
- **(c) One-clarification-per-thread:** if the loop has already posted one clarification with no structured response → escalate once and wait; never post a second clarification.

**O14 resolution — ack-pattern v1 default list + test corpus.** The list is **case-insensitive substring / regex** patterns, stored in config (`PROJECT/hos-coordination.yaml → ack_patterns`, layer 2a overridable; shipped default below):
```
thanks            thank you          thx
lgtm              looks good         looks good to me
sounds good       ok / okay (whole-word)   👍
closing           closing this       closing as resolved
never mind        nevermind          nm
no action         no action needed   wontfix-ack
will do           done               resolved (whole-word, no trailing ? )
```
Matching rule: a comment is an ack iff, after stripping the envelope/marker and trimming, its **entire** remaining text matches one pattern OR is ≤ 4 words and contains a pattern (prevents "thanks, but actually the bug still repros" — which has >4 words and a substantive clause — from being silently dropped). Whole-word patterns (`ok`, `okay`, `done`, `resolved`) must not match inside larger words.
**Test corpus** (`scripts/automation/fixtures/ack_patterns.jsonl`): ≥ 30 labeled cases — true-acks (`"thanks!"`, `"LGTM 👍"`, `"closing as resolved"`), true-non-acks that contain a pattern (`"thanks, but it still fails on macOS"`, `"this looks good except the null check"`, `"done? not yet — see line 12"`), and edge cases (emoji-only, mixed-language). Each case: `{text, expected: ack|triage}`. The classifier must pass 100% of the corpus; the corpus is the regression contract for O14.

### Failure handling
Malformed/spoofed envelope body → fails the allowlist check loudly (the `signature` marker is an integrity hint, not crypto, R4.3.2) → ack + human. Unparseable YAML → treat as envelope-less, apply guards (a).

### Requirements implemented
R4.1.1 (+ O14 guards), R4.1.2, R4.1.3, R4.1.4, R4.2.1, R4.2.2, R4.3.1, R4.3.2.

---

## 7. claim  (T8 · §7 · ADR-2 backstop)

### Responsibility
Claim-then-verify **contention reducer** (NOT mutual exclusion — ADR-2: correctness is correlation.py). Heartbeat as claim-envelope re-stamp. Timeout, crash-before-first-heartbeat auto-release, terminal release.

### Data structures / GitHub object shapes
**instance-id:** a UUIDv4 minted **at orchestrator startup** (NOT hostname+pid — collides at PID 1 in containers). Carried in the `type: claim` envelope. Distinct from `cid` (correlation.py): instance-id is the **claim tiebreak only**, never names an artifact.

**Claim envelope** (`type: claim`) posted as a comment on the work issue + label `hos-claimed` + self-assign (`hos-worker`):
```hos-envelope
type: claim
from: hos-worker
correlation-id: <cid of the work item>
signature: ...
```
plus the claim body carries `instance-id: <uuid>` and `claimed-at: <ISO>`.
**Heartbeat envelope** (`type: heartbeat`) re-stamps `updated-at` every ≤ `heartbeat_interval`.

### Algorithm — claim-then-verify (R7.1)
1. **Idempotency precheck first (R6.1 — correlation.py):** does `hos/auto/<cid>` branch / draft-PR / answer envelope already exist? (REST-by-id, never Search.) If yes → resume/skip, do not re-claim fresh.
2. Mint instance-id (once per orchestrator). Post `type: claim` envelope + `hos-claimed` + self-assign.
3. **Jittered delay** (default 30–90s).
4. **Re-read the issue by id (REST, NOT search)** — read-your-writes invariant. Collect all claim envelopes.
5. If multiple claims: **lowest instance-id wins.** Losers release immediately (remove `hos-claimed`, unassign) **and delete any artifact they created** (R6.1 loser-cleanup) BEFORE releasing.
6. **No artifact before verified win (R7.1):** an instance MUST NOT create a branch / PR / answer envelope until step 4–5 confirm it won. Pre-verification artifacts are a protocol violation.

### Algorithm — heartbeat & timeout (R7.2/R7.3/R7.4)
- Per-task worker posts **first heartbeat within one `heartbeat_interval`** (<15m) of claiming; a claim with no first heartbeat in that window = crash-before-first-heartbeat → auto-released.
- Re-stamp every ≤ `heartbeat_interval` (15m). At each heartbeat the worker also **rechecks activation file + `hos-halt`** (R8.4/R13.4) and self-terminates on OFF/halt (release claim, post final heartbeat noting the reason, exit).
- **Staleness is computed from the claim envelope `updated_at`** (GitHub-observable), NOT process liveness. `claim_timeout = 45m` = 3 missed beats. A stale claim may be re-picked by any instance (which first runs the R6.1 idempotency precheck).
- **Terminal release (R7.4):** merge, escalation, or per-issue failure-cap hit → remove `hos-claimed`, unassign, record outcome in ledger.

### Requirements implemented
R7.1 (UUIDv4 instance-id, claim-then-verify, lowest-wins, no-artifact-before-win, loser-cleanup), R7.2 (heartbeat re-stamp + first-beat window + activation/halt recheck), R7.3 (45m timeout from envelope `updated_at`), R7.4 (terminal release). Reads obey the read-your-writes invariant (REST-by-id).

---

## 8. correlation & idempotent recovery  (T7 · §6 · ADR-2 keystone)

### Responsibility
**The M1 correctness owner.** Deterministic cid; artifact naming; idempotency precheck; cold-start recovery state machine. This is the keystone module (ADR-2) — every other layer is contention reduction on top.

### Data structures
**cid (ADR-2, R6.1):** `cid = sha256(f"{issue_url}#{issue_number}".encode()).hexdigest()[:12]`.
- `issue_url` = the canonical `https://github.com/{owner}/{repo}/issues/{n}` form (normalize before hashing — strip trailing slash, lowercase host).
- Deterministic across instances → two racers produce the **same** cid → **same** branch → second push is a no-op/fast-forward (NOT a duplicate-work incident).

**Artifact names (all derived from cid, single owner of these strings):**
- branch: `hos/auto/<cid>`
- draft-PR title: carries `<cid>` (e.g. `[AI: hos-worker] <summary> (auto/<cid>)`)
- answer-envelope: `correlation-id: <cid>`

**M1 operational definition (R6.1):** a duplicate-work incident = **two distinct cids naming the same work item** (two `hos/auto/<id>` branches against the same source issue). A second push to the *same* `hos/auto/<cid>` branch is the idempotency mechanism working correctly, NOT an incident.

### Algorithm — idempotency precheck (`already_exists(cid) -> resume_state | None`)
**Read-your-writes invariant — REST-by-id, NEVER Search:**
1. `GET /repos/{o}/{r}/git/ref/heads/hos/auto/<cid>` → branch exists?
2. `GET /repos/{o}/{r}/pulls?head={o}:hos/auto/<cid>&state=all` → PR exists?
3. Scan the issue's comments (REST-by-id) for an answer envelope with `correlation-id: <cid>`.
Return the furthest-progressed state; the worker resumes from there (cold-start table below).

### Cold-start recovery state machine (R6.1 M4 table)
| Interrupted at | Recovery |
|---|---|
| After claim, before triage | re-triage (claim envelope present) |
| After triage, before branch | create branch (idempotent — same cid) |
| After branch, before PR | open PR (branch exists) |
| After PR, before gates | re-run gates (PR exists) |
| After gates, before merge decision | re-read gate results from PR; re-decide |
| After merge decision, before merge | re-attempt merge (idempotent if already merged) |

**Claim-race loser cleanup (R6.1):** a losing instance deletes any branch/PR/envelope it created under its losing attempt **before** releasing the claim.

### Failure handling
A reaped-mid-work claim is safe to re-pick because every artifact is cid-named and idempotent. Cold-start drill (R6.3, M4) is a **release gate**: destroy an instance mid-task at each table row; a fresh instance must reach a correct non-duplicating state from GitHub alone.

### Requirements implemented
R6.1 (deterministic cid — the M1 keystone; loser cleanup; no-artifact-before-win tie to claim.py), R6.2 (no external datastore; canonical hyphen-case label set), R6.3 (cold-start drill gate), ADR-2.

---

## 9. budget & ledger  (T9 · §8 · O4 · O5 · ADR read-your-writes)

### Responsibility
Estimate-then-gate per-task; per-window cumulative budget; default-deny on timeout; mid-flight overrun re-ask; GATED-vs-UNGATED classification; the append-only conflict-free cost/action ledger.

### O4 resolution — ledger directory layout (technical-design's call)
Per-run files (R11.6 mandates this), **per-customer subdirectories** under the committed `audit/` tree, with a manifest, referenced from the existing `audit/oversight-log.jsonl`:
```
audit/automation/
  <customer>/
    runs/
      <instance-id>-<ISO8601-compact>.jsonl     # one file per orchestrator run; append-only
    manifest.jsonl                               # one line per run file: {file, instance_id, started, ended, customer}
    automation-log.md                            # R11.8 derived human-readable log (per customer)
  watchdog/                                       # R11.5 probe-completion events index (optional mirror)
```
- **Reference from `audit/oversight-log.jsonl`:** on each merge/escalation the loop appends **one** existing-schema event to `audit/oversight-log.jsonl` with a pointer field `{"automation_run": "<customer>/runs/<file>", "cid": "<cid>"}`, so the canonical audit log links to the detailed per-run ledger without duplicating it. This keeps the existing committed audit trail authoritative and the detailed cost records conflict-free.
- **Why per-customer subdirs:** isolates one customer's churn from another's git history and lets blast-radius/budget summation scope a single customer cheaply (R12.1 per-customer budgets).

### Data structures — cost/action record (one JSONL line)
```json
{ "ts": "<ISO>", "instance_id": "<uuid>", "cid": "<cid>", "customer": "<slug>",
  "event": "spawn|triage|estimate|gate-start|gate-end|merge|escalate|propose|suppress|halt|stale-lock-reclaim|...",
  "who": "hos-worker|hos-overseer", "what": "<short>", "why": "<short>",
  "token_cost": <int|null>, "files_touched": <int>, "prs": <int>, "issues": <int> }
```
Append-only; each record keyed by `cid` (conflict-free — N instances append distinct files, never mutate a shared counter, R8.2).

### Algorithm — per-window summation (R8.2 · read-your-writes)
Window total for `(customer, window)` = **sum over all `token_cost` in all run files in the rolling window** (read at read time; no shared mutable counter). Blast-radius window total (R11.2) = sum of `prs`/`issues`/`files_touched` over the rolling 24h. **These sums are correctness-sensitive reads** → the underlying GitHub objects (e.g. "did this PR merge?") are confirmed REST-by-id, never via Search.

### O5 resolution — token-estimation signals + ~free computation (technical-design's call)
A **cheap heuristic, no model pre-pass** (R8.1 — estimation error acceptable, err high; R8.6 re-asks). Signals, all ~free from already-fetched GitHub objects / `git`:
1. `issue_body_chars` — length of the issue body (already fetched).
2. `changed_file_count` — from `git diff --name-only` on the working branch (or, pre-branch, an estimate from the issue's referenced paths; default to a class baseline if none).
3. `total_diff_lines` — `git diff --shortstat` (added+deleted) when a diff exists.
4. `blast_radius` — dep/file fan-out count if available (else 0).
5. `historical_cost` — median `token_cost` of the **last K (default 20)** completed tasks of the same triage class from the ledger (this is the calibrating signal; ~free, a ledger read).

**Estimate formula (calibration constants, tunable):**
```
estimate = BASE[class]
         + 6   * issue_body_chars/1000
         + 1500 * changed_file_count
         + 8   * total_diff_lines
         + 1000 * blast_radius
estimate = max(estimate, historical_cost_median * 1.25)   # err high; floor at 1.25× historical
```
`BASE[class]`: `bug=40_000`, `communication=8_000`, `spec-gap=15_000`, default `30_000`. Constants live in config (`thresholds.estimation`), are not load-bearing for correctness (the gate just needs to be roughly right and err high), and are calibrated against the ledger over time. **This is the authoritative estimation contract for test purposes** (a unit test feeds fixed signals → expects a deterministic estimate).

### Algorithm — gates
- **Per-task estimate gate (R8.1):** compute estimate **before** any GATED work. If `estimate > per_task_threshold` (150k) → create a `type: question` permission request (§8.2 contract) + label `hos-budget-gated`, **block that task** until approved.
- **Per-window budget gate (R8.2):** if cumulative window spend + estimate > `window_budget` (1.5M) → gate all further GATED work in the window. Soft ceiling with headroom (R8.6 re-asks for overrun).
- **Default-deny on timeout (R8.3):** unanswered permission request past `approval_timeout` (12h) → **denied**, leave `needs-human`. Silence ≠ yes; never defaults to auto-approve.
- **Mid-flight overrun re-ask (R8.6):** a task exceeding its estimate while running is **paused at the next gate boundary** and re-submitted with the revised number.
- **GATED vs UNGATED (R8.7):** GATED = full build-chain run, self-review run, cross-vendor validation. UNGATED (always allowed even when budget exhausted) = triage, envelope parse, token estimation, drafting escalations/`needs-human`, heartbeat, label ops. A budget-exhausted loop stays able to triage and communicate (R8.2a).
- **Wire to pager (R8.5):** cost-runaway / budget-exceeded / kill-switch fire the existing SMS/alert path, not just the ledger.

### §8.2 escalation contract (R8.2a/R8.2b)
Every escalation / permission request / `needs-human` handoff MUST carry, in order: (1) problem + risk + background (assume context-free human; includes the token estimate + blast-radius summary, R8.2b), (2) options with pros/cons, (3) recommendation + justification. A missing element = **malformed escalation** (self-reject, emit a complete one).

### Requirements implemented
R8.1, R8.2 (+ append-only per-run ledger, summation-at-read), R8.2a, R8.2b, R8.3, R8.5, R8.6, R8.7, O4 (layout), O5 (signals + formula), R11.6 (ledger structure), R11.2 (blast-radius summation).

---

## 10. merge-authority  (T10 · §9 · O3 · DEP[#152-followup])

### Responsibility
Detect server-side gate ("detected, not assumed"), apply the orthogonal tier × security × protected-surface matrix, default PROPOSE_ONLY, no-autonomous-release guard, and the draft-PR / `needs-human` / `needs-ai` review queue.

### O3 resolution — gate detection = protection-API read + overseer-bypass-standing verification (NOT a live canary), v1
`detect_server_side_gate(repo) -> AUTONOMOUS_CAPABLE | False`:
1. `GET /repos/{o}/{r}/branches/{default}/protection` → confirm: a required PR review (`required_pull_request_reviews`), required approving count ≥ 1, `require_code_owner_reviews` true on protected paths, `dismiss_stale_reviews` true. Missing → False.
2. **Overseer bypass-standing verification:** confirm the **overseer account cannot bypass** the rule — i.e. it is NOT in `enforce_admins`-exempt set / not an unrestricted admin able to merge without the gate. (`GET .../protection` + the bypass/allowances fields; and that `enforce_admins` applies.)
3. Confirm the overseer's approval is **accepted as a valid review** under the rules (required-approvals count, CODEOWNERS, dismiss-stale-on-push) **and** that the overseer can merge after self-approving a non-protected LOW PR.
   - **DEP[#152-followup]:** the precise "overseer may merge ≤ceiling but not above" enforcement is the risk-tier-vs-ceiling status check that the #152 follow-up track builds. This module **reads** that status check's presence as part of detection; if the check is absent → cannot confirm above-ceiling enforcement → **PROPOSE_ONLY**.
4. If any of 1–3 is unverifiable or false → **PROPOSE_ONLY** for this repo.

**R9.1.1 — cached detection enables config; never substitutes for a pre-merge re-check.** Branch-protection status AND overseer bypass-standing MUST be **re-queried immediately before each merge attempt**. A failed pre-merge re-check → immediate downgrade to PROPOSE_ONLY for that merge.

### Merge-authority matrix (R9.1 — authoritative for tests)
Auto-merge **iff** `(tier ≤ MEDIUM) AND (not security-relevant) AND (not protected-surface) AND (full PROCEED) AND (server-side gate detected active, re-checked)`.

| Risk tier | Security-relevant? | Protected surface? | Server-side gate? | Outcome |
|---|---|---|---|---|
| SAFE/LOW/MEDIUM | no | no | yes | **Auto-merge** (overseer approves+merges) |
| SAFE/LOW/MEDIUM | no | no | no | **PROPOSE_ONLY** |
| SAFE/LOW/MEDIUM | **yes** | any | any | **Human** |
| SAFE/LOW/MEDIUM | any | **yes** | any | **Human** |
| HIGH/CRITICAL | any | any | any | **Human** |
| any | any | any | not detected | **PROPOSE_ONLY** |

- **Security-relevant (R9.1.2):** the change touches `audit/`, auth, secrets, gate scripts, or any path on the **per-repo** `security-sensitive-paths` config list (NOT the framework-canonical set).
- **Protected-surface (R9.1.3):** matches a glob in the **framework-canonical** set — reuse `scripts/framework/protected_surfaces.txt` + the existing `require_human_approval.py` glob matcher (already implemented, line 52 `glob_to_regex`). This design **adds two paths** to that file: the `hos-halt` path and `PROJECT/hos-coordination.yaml` (R8.4, R9.1.3-gc). **This edit to `protected_surfaces.txt` is itself a protected-surface change → routes to human at build time** (flagged for the coder; see §16).
- **Authorship backstop (R9.1.4):** ANY PR authored by the worker/overseer machine account that touches `PROJECT/hos-coordination.yaml` or any protected-surface path → HUMAN, even if no glob matched (rename/path-edge). A machine-authored governance-config PR is a **P0 anomaly** → escalate immediately.

### Review-queue convention (R9.3)
- **R9.3.1:** open a **draft PR** (worker account, carrying an envelope, labeled `hos-coordination`) + a `needs-human` tracking issue with the §8.2 contract + a disposition menu (approve / request change X / reject). The set of open `needs-human` issues **is** the queue.
- **R9.3.2:** draft = "AI work done, awaiting human." The loop MUST distinguish its **own** drafts (worker-authored + envelope + `hos-coordination`) from **human** drafts and never touch a human's in-progress draft.
- **R9.3.3:** `needs-ai` = the human's "go" signal; `needs-human` = AI→human. Never mark ready / merge until `needs-ai` present.
- **R9.3.4:** on `needs-ai`, in AUTONOMOUS mode for a matrix-permitted change, the loop **verifies a GitHub PR Review in APPROVED state by an allowlisted human** exists before merging. `needs-ai` authorizes soliciting/proceeding, NOT a substitute for a formal approval. In PROPOSE_ONLY / above-ceiling / security / protected-surface → mark ready, leave merge to the human.
- **R9.3.5:** no "(DRAFT)" in titles (GitHub's draft badge is the signal).

### Embargo path (R9.2 — T11)
`security-report` triage → **acknowledge (envelope, NO detail)** → route to a human + **deployment-configured private channel** (governance config; e.g. private GHSA / private Slack / private repo — never hard-coded) → label `hos-embargo`. **No public branch / PR / test.** The loop's ONLY autonomous action is ack + route + label (R9.2.2). Everything else is human-driven in v1.

### No autonomous releases (R9.4.1)
The loop may **prepare** a release (draft notes, open a release PR) and **escalate** it (§8.2), but MUST NOT run the release-cut path, push a release tag, or publish notes without explicit human approval — independent of tier/mode/gate.

### Requirements implemented
R9.1.1 (detection + pre-merge re-check), R9.1.2, R9.1.3 (+ `protected_surfaces.txt` reuse + 2-path addition), R9.1.3-gc, R9.1.4, R9.2.1, R9.2.2, R9.3.1–R9.3.5, R9.4.1, O3 (detection method).

---

## 11. Gate ordering — the orchestrator main loop  (R13.4 · R8.4 · §3 · ADR-3)

**The binding gate order on every cron wake (SF-1 caption + ADR-3):**

```
hos_orchestrator.sh:
  1. ACTIVATION CHECK (activation.py)        # FIRST. OFF → "inactive — exiting", exit 0. Zero activity.
  2. HOS-HALT CHECK (read the hos-halt file) # present (non-empty, readable) → exit, no probe.
  3. MACHINE LOCK ACQUIRE (machine_lock.sh)  # jitter→mkdir; contention/hung handling (§4).
  4. CONFIG RESOLVE (config_resolver.py)     # incl. enabled:true (layer-2a authorization) check.
  5. PROBE (probe.py)                          # round-robin, quota-aware, staggered; REST/GraphQL.
  6. For each found+claimable work item:
       CLAIM (claim.py) → verify win → idempotency precheck (correlation.py)
       DISPATCH = SPAWN hos_worker.sh <cid>  (detached)   # ADR-3: spawn, not run-to-completion
  7. RELEASE MACHINE LOCK (trap on exit) + post probe-completion heartbeat (watchdog, R11.5) + exit.

hos_worker.sh <cid> (per-task, bounded long-lived, up to max_task_runtime=4h):
  triage → benefit≫risk gate → budget gate → (red/green or evidence artifact) →
  build chain (run_validators.sh / risk-assessor / run_second_review.sh / oversight-evaluator) →
  merge-authority decision → merge or PROPOSE_ONLY/escalate → terminal claim release.
  AT EVERY HEARTBEAT (≤15m): recheck activation + hos-halt; OFF/halt → self-terminate.
```

**hos-halt contract (R8.4):** a committed **file** (NOT a label) at the configured path. **Path resolution:** the file is `PROJECT/hos-halt` if a `PROJECT/` area exists, else `.hos-halt` at repo root — the resolved path is pinned per repo in config (R13.3) and **must match across all consumers**. This path is **added to `protected_surfaces.txt`** (server-side branch protection prevents the worker/overseer from merging changes to it). Present (non-empty, readable) → probe/dispatch exits with no action; per-task workers self-terminate within one heartbeat. `hos-halt` is also in the R4.1.1(a) terminal-state set.

### Requirements implemented
R13.4 (activation first gate), R8.4 (hos-halt file, path, protected surface, heartbeat self-terminate), ADR-3 (lock scope, dispatch=spawn), §3 execution model + gate order.

---

## 12. self-review-source  (T12 · §3.2 · O6 · O9 · O10-flagged)

### Responsibility
Run `validate_self` on a cadence (default weekly, hard 24h floor), file each NEW finding as a tracked issue (exact-key fingerprint dedup), three dispositions (fix / won't-fix+suppress / escalate), suppression ledger with time-bounded lifecycle, burndown metric (M6).

### Data structures / ledger formats

**O6 resolution — exact-key fingerprint (v1), record RAW text.** Fingerprint key = `(sorted(files), finding_class)`. Stored in the **disposition ledger** (committed):
```
audit/automation/self-review-ledger.jsonl
  { "fingerprint": "<sha256 of sorted-files + '|' + finding_class>",
    "files": [...sorted...], "finding_class": "...",
    "disposition": "filed:#N | fixed | noise",
    "raw_finding_text": "<verbatim — for v2 fuzzy reconcile>",
    "first_seen": "<ISO>", "last_seen": "<ISO>" }
```
A finding is filed **only if its fingerprint is absent** (R3.2.1). On file, record `filed:#N` immediately so it never re-surfaces. The **raw finding text is recorded** for the v2 fuzzy-match reconcile (O6 deferred; exact-key is the v1 floor).

**O9 resolution — suppression ledger = HOS-shipped baseline + per-repo overlay.**
```
scripts/automation/suppression-baseline.jsonl   # HOS-shipped (framework), known framework-level FPs
PROJECT/suppression-overlay.jsonl               # per-repo accepted-risk decisions (committed, CODEOWNERS-gated*)
```
Effective suppression set = baseline ∪ overlay. (*The overlay sits in PROJECT; a suppression that rules on governance config is itself a governance act — placement near `PROJECT/hos-coordination.yaml` keeps it auditable. Suppression entries are NOT on the auto-merge path; they require the §3.2.5 human ruling for restricted classes.) Suppression entry:
```
{ "fingerprint": "...", "files":[...], "finding_class":"...",
  "approver": "<login>", "rationale": "<text>", "approved_at": "<ISO>",
  "ttl_days": <int>, "review_by": "<ISO date>" }
```
Suppression is **distinct from `scanner-fp`** (which fixes the heuristic) and from `noise` — it is an accountable accepted-risk record (R3.2.5).

### Algorithm
- **Cadence (R3.2.2):** `self_review_cadence` default weekly, independent of probe cadence; **values < 24h are fatal at config-load**. Budget-gated like all GATED work (R8.7).
- **Run:** invoke the existing `scripts/framework/validate_self.sh` (optionally cross-vendor). For each finding: compute fingerprint; if in effective suppression set → skip; if fingerprint in dedup ledger → skip; else **file an issue** (envelope, severity P0–P3 per R5.3.1, `hos-coordination` label), record `filed:#N`. Filed findings re-enter normal triage (R3.2.3 — no privileged fast path; reproducing-test/evidence rule R3.1.1 still applies).
- **Dispositions (R3.2.5):** each finding → exactly one of fix / won't-fix+suppress / escalate. A won't-fix writes a scoped suppression entry (above) so the validator/self-review stops re-reporting. **Won't-fix on security / privacy / license is human-only** (O10 floor) — the loop suppresses only classes it is permitted to rule on, escalates the rest.
- **Governance findings are human-to-close (R3.2.4):** the loop files but never auto-closes a filed governance finding when it stops reproducing.
- **Burndown (M6):** track open model-produced finding count; a rising count is itself an alert.

### Suppression lifecycle (R3.2.6)
- Each entry carries approver + timestamp + `review_by` (default TTL **90d**, `suppression_default_ttl`).
- **Nag (`nag_lead_days`, default 14):** N days before `review_by`, post a `type: question` envelope on the suppression issue, labeled `needs-human`, carrying original rationale + approver + expiry + renew-or-expire request.
- **Expiry:** past `review_by` without renewal → file/update an issue labeled `suppression-expired` with a back-reference (original issue # + rationale + approver + expiry). The expired suppression is routed **directly to the human queue** (`needs-human`) — NOT autonomous triage, NOT auto-claimed/auto-fixed. The finding re-surfaces as human-assigned work.

### O10 — FLAGGED, NOT DECIDED (human governance call)
The exact **won't-fix human-only class list** is a **human governance decision** and is explicitly **out of technical-design's authority** (per the task). The PRD proposes the floor **security / privacy / license**. This design implements the *mechanism* (a configurable `human_only_suppression_classes` list, defaulting to `["security","privacy","license"]`), and **flags O10 for human ratification of the final list**. The loop must NEVER autonomously won't-fix a class on this list regardless of confidence. **`HUMAN-DECISION-REQUIRED: O10` — pm-agent/human to confirm the final class list before this module ships.**

### Requirements implemented
R3.2.1 (fingerprint dedup), R3.2.2 (cadence + 24h floor), R3.2.3 (normal triage), R3.2.4 (human-only close), R3.2.5 (three dispositions + suppression + human-only classes mechanism), R3.2.6 (lifecycle: nag + expiry), M6 (burndown), O6 (exact-key + raw text), O9 (baseline+overlay). O10 flagged for human.

---

## 13. triage  (T6 · §5)

### Responsibility
First action on any found work; fails toward the human. Classify (confidence floor + asymmetric security), assign severity, run the benefit≫risk gate, honor the optional codeowner authorization tag.

### Algorithm
- **Classes (R5.1):** `bug · feature · communication · security-report · spec-gap · governance · config · duplicate · invalid`. Each carries a **minimum verification artifact** (R3.1.1): `bug`→red/green test; `spec-gap`→before/after spec diff + human confirmation; `governance`/`config`→structured before/after assertion; others N/A. Absence of the class's artifact = hard reject.
- **Confidence floor (R5.2.1):** triage emits a confidence score; **< 0.75 → human**.
- **Asymmetric security (R5.2.2):** ANY signal of a vulnerability (even low-confidence) → embargo path. False-positive embargo is cheap; false-negative public auto-fix is catastrophic.
- **Severity on every actionable item (R5.3.1):** P0–P3 on every bug, feature, and self-review finding (label + envelope `priority`). Highest-first handling (R5.3.2); open P0 pins probe to floor (§10).
- **Benefit≫risk gate (R5.3.3 — authoritative matrix for tests):**

  | Severity | tier ≤ MEDIUM | tier HIGH+ |
  |---|---|---|
  | P0/P1 | **ACT** | **ESCALATE** |
  | P2/P3 | **ACT** if blast-radius within per-run caps (§11.2: 5 PRs/10 issues/25 files) | **ESCALATE** |

  **Hard overrides (always ESCALATE/HUMAN):** any security-relevance flag (R9.1.2); any protected-surface match (R9.1.3); any triage class other than `bug` or `communication`.
- **Rejection → human (R5.3.4):** a benefit≫risk rejection is NOT silently dropped — route to human (`needs-human`) with the full §8.2 contract incl. the benefit-vs-risk analysis + the loop's recommendation to NOT proceed.

### Codeowner authorization tag (R5.4 · A7 · O19)
`hos-autowork-authorized` (label) — an optional CODEOWNER pre-authorization that **expands the triage-class scope for that one item** (e.g. lets a queued feature proceed to claim+fix). It does **NOT** bypass any structural gate (R5.4.3: merge-authority matrix, protected-surface, embargo, benefit≫risk, budget all still apply).
- **Label-actor verification (R5.4.2 — reuse §4.1.4 pattern):** read the `labeled` event actor (`GET .../issues/{n}/events`) for `hos-autowork-authorized`; verify actor ∈ CODEOWNERS (O19 below). A non-codeowner application is **ignored and logged**. Re-verify each cycle (no caching of "label present").

### O19 resolution — CODEOWNERS lookup mechanism (technical-design's call)
`codeowners.py`: **parse the repo's `.github/CODEOWNERS` file** (do NOT rely on a GitHub CODEOWNERS API endpoint — none returns "is X a codeowner for these files" cheaply; parsing is deterministic and free).
- **Determine owners for the item's files-at-triage-time:** collect the files the item references / its PR diff touches; for each, find the **last matching** CODEOWNERS pattern (CODEOWNERS = last-match-wins), collect its owners.
- **Edge cases (must not false-positive a non-codeowner as a codeowner):**
  - **Team entries (`@org/team`):** resolve via `GET /orgs/{org}/teams/{team}/memberships/{user}` (cached per cycle); if the org/team is unresolvable (no org, API error) → treat as **NOT a codeowner** (fail-closed), log.
  - **Wildcard `*` root entry:** a `*` owner covers all files; an actor matching the `*` owner IS a codeowner. But a CODEOWNERS that does NOT cover the root and has no pattern matching the item's files → **no owner** → the label authorizes nothing (fail-closed).
  - **Files with no matching pattern:** that file has no owner; if ANY referenced file is unowned, do not treat the actor as authorized for the item unless the actor owns a pattern that matches **all** referenced files (conservative — prevents a partial-owner from pre-authorizing a cross-cutting change).
  - **Username vs team membership:** direct `@user` match is a codeowner iff `actor == user` (case-insensitive login compare).
- **Cost control:** parse CODEOWNERS once per cycle; cache team-membership lookups per cycle; this is the same CODEOWNERS used for branch-protection enforcement (consistency with #152).

### O20 resolution — label names + T2 provisioning (technical-design's call)
- **`hos-autowork-authorized`** confirmed as the v1 label name — fits the `hos-*` convention (R6.2), no conflict with the existing set. Added to the canonical label set.
- **Full canonical `hos-*` label set provisioned at T2 onboarding:** `hos-coordination`, `hos-claimed`, `hos-in-progress`, `hos-budget-gated`, `hos-embargo`, `hos-halt` (label form is **NOT** the kill switch — the kill switch is the *file*; this label, if used at all, is only a visual marker — prefer not creating it to avoid confusion; **decision: do NOT create an `hos-halt` label** since R8.4 mandates a file, to avoid the false impression that the label is the switch), `hos-autowork-authorized`, `suppression-expired`. **Reuse (do not recreate):** `needs-ai`, `needs-human` (existing hyphen-case repo labels). T2 creates the `hos-*` set per repo on opt-in via `gh label create`.

### Requirements implemented
R5.1, R5.2.1, R5.2.2, R5.3.1–R5.3.4, R5.4.1–R5.4.4, R3.1.1 (verification artifact by class), O19 (CODEOWNERS lookup + edge cases), O20 (label names + T2).

---

## 14. circuit-breakers + observability  (T13 · T14 · §11)

### Circuit breakers (R11.1–R11.5)
- **Per-issue failure cap (R11.1):** default **3**. A poison-pill issue that keeps failing → `needs-human`, stop burning tokens. Failure count tracked in the ledger keyed by `cid`.
- **Per-run blast-radius caps (R11.2):** rolling **24h** window from the ledger, read at the **start of every probe cycle, before claiming**: max 5 PRs / 10 issues / 25 files. A cycle that would exceed any cap halts new work for the window and pages. (Implemented in probe.py step 1; sums via ledger.py.)
- **Rate-limit backoff (R11.3):** honor `X-RateLimit-*`; exponential backoff; never hammer.
- **Max runtime per task (R11.4):** `max_task_runtime = 4h`; a task exceeding it is abandoned (claim released, `needs-human`). **Distinct from `orchestrator_lock_timeout` (20m, machine lock, §4) — ADR-3.**
- **Dead-man's-switch (R11.5 — externally checkable):** the dead-man condition = **"no probe-completion event in GitHub in the last 6h."** The loop posts a `type: heartbeat` envelope on a **designated watchdog issue** (created per repo at T2) at the end of every probe cycle. The checker is **NOT the loop** — an external cron / GitHub Action / human checks for the event; no event in 6h → page. (A dead loop can't report its own death.)

### Observability (R11.6–R11.8)
- **Run ledger (R11.6 — JSONL-first, authoritative):** per-run files + manifest (O4 layout, §9). Written **first**; the authoritative source for all aggregated metrics.
- **Shadow / dry-run mode (R11.7):** runs the full loop (triage, claim-eval, build-plan) and records what it **would** do without acting. **Mandatory default for a newly-onboarded customer** (T2 C-4: onboarding sets `mode: propose-only` / shadow until the operator graduates).
- **Markdown activity log (R11.8 — derived):** `audit/automation/<customer>/automation-log.md`, one dated plain-language entry per cycle/task (what picked up, decided + why, changed/merged/escalated, running token cost). **Derived from the JSONL** (regenerable); append-only; roll-up summaries are **separate regenerated artifacts**, never in-line rewrites of the append-only log.

### Multi-customer fairness (T15 · R12.1–R12.4)
- Per-customer token AND API-call budgets (R12.1); quota-aware round-robin + staggered starts (R12.2, §5 of this doc); isolation — one customer's failure never halts others (R12.3); per-customer capability (auto-merge/allowlist/thresholds/cadence/mode, R12.4). Kill switch is per-repo AND global (a global `hos-halt` stops everything, R12.3).

### Requirements implemented
R11.1–R11.8, R12.1–R12.4.

---

## 15. BUILD ORDER (dependency-ordered first coding tasks → §17 T-items)

Ordered so each task's dependencies are already built. Foundation first (correctness keystone + the gates that make the loop *safe to even start*), then the loop body, then work sources.

**Phase A — Safety & correctness foundation (must land before any GitHub-mutating code runs):**
1. **B1 → T7 (correlation.py).** The cid algorithm + artifact naming + idempotency precheck (REST-by-id) + cold-start state machine. **This is the M1 keystone (ADR-2) — build and unit-test it first; everything else is contention reduction on top.** Pure function + REST reads; no mutation. *Dep: github.py (gh REST-by-id wrapper).*
2. **B2 → T2 (config_resolver.py + activation.py).** The 4-layer resolver (narrow-only) + the activation AND-gate (first cron gate, fail-closed) + `<repo-id>` slug + `hos activate/deactivate`. Nothing in the loop may run before these gate it. *Dep: none (stdlib + git remote read).*
3. **B3 → T8 machine-lock (machine_lock.sh).** mkdir-atomic lock, holder inspection (O18 ps-match), hang timeout (`orchestrator_lock_timeout` 20m), trap cleanup, O17 path+fallback. **Spawn-scope only (ADR-3).** *Dep: none.*
4. **B4 → protected-surfaces edit + T10 detection (merge_authority.py detection half + the `protected_surfaces.txt` 2-path addition).** Add `hos-halt` path + `PROJECT/hos-coordination.yaml` to `protected_surfaces.txt`; build `detect_server_side_gate` (O3: protection-API read + overseer-bypass verification). **The `protected_surfaces.txt` edit is a protected-surface change → routes to human at build time.** *Dep: reuses existing `require_human_approval.py` glob matcher; DEP[#152-followup] for the above-ceiling status check (detection degrades to PROPOSE_ONLY without it — safe).*

**Phase B — Loop body:**
5. **B5 → T9 (ledger.py + budget.py).** Append-only per-run ledger (O4 layout), summation-at-read (read-your-writes), per-task estimate (O5 formula), per-window budget, default-deny, GATED/UNGATED, §8.2 escalation contract. *Dep: correlation.py (cid keys), github.py.*
6. **B6 → T5 (envelope.py).** Parse/emit, threading DAG, idempotency, version negotiation, allowlist authn (GitHub-author, not `from:`), R4.1.1 guards + O14 ack-pattern corpus. *Dep: github.py.*
7. **B7 → T4 (probe.py).** Token-free REST/GraphQL probe (NOT Search), cadence + back-off + priority-pin, round-robin + stagger, per-customer API-call quota (O15), blast-radius window pre-check, coordination-label actor verify. *Dep: config_resolver, ledger (window read), envelope (label verify), github.py.*
8. **B8 → T8 claim (claim.py).** Claim-then-verify (UUIDv4 instance-id), heartbeat re-stamp + first-beat window + activation/halt recheck, 45m timeout from envelope `updated_at`, terminal release. *Dep: correlation.py (idempotency precheck first), envelope.py.*
9. **B9 → T6 (triage.py) + codeowners.py.** Classes + confidence floor + asymmetric security + severity + benefit≫risk matrix + rejection→human + `hos-autowork-authorized` tag with O19 CODEOWNERS lookup. *Dep: envelope.py, github.py.*
10. **B10 → T10 (merge_authority.py matrix + queue) + T11 (embargo).** Matrix, PROPOSE_ONLY default, pre-merge re-check (R9.1.1), R9.1.4 authorship backstop, draft-PR/`needs-human`/`needs-ai` queue, no-release guard, embargo ack+route+label. *Dep: detection (B4), triage (B9), config_resolver.*

**Phase C — Orchestration, work sources, safety nets:**
11. **B11 → hos_orchestrator.sh + hos_worker.sh.** Wire the binding gate order (activation → hos-halt → machine-lock → config → probe → claim → dispatch=SPAWN → release), and the per-task worker chain (triage → gates → build chain → merge decision → terminal release; activation/halt recheck at each heartbeat). *Dep: all of Phase A+B.*
12. **B12 → T12 (self_review_source.py).** `validate_self` auto-file, exact-key fingerprint dedup (O6 + raw text), suppression ledger (O9 baseline+overlay), lifecycle (nag/expiry), burndown (M6), O10-flagged human-only classes mechanism. *Dep: triage (filed findings re-enter triage), ledger, envelope.*
13. **B13 → T13 (breakers.py) + T14 (observability.py).** Failure cap, blast-radius window, rate-limit, max-runtime, dead-man's-switch (+ watchdog issue at T2), JSONL-first ledger consumers, derived Markdown log, shadow mode (default for new customer). *Dep: ledger, orchestrator.*
14. **B14 → T15 (multi-customer fairness wiring).** Per-customer budgets/round-robin/isolation/global+per-repo kill — mostly integration across probe/budget/breakers. *Dep: probe, budget, breakers.*
15. **B15 → T1 / T3 / T16 (derived docs).** Generate the agent-protocol doc, the operator enable/disable doc, and the issue-handling/process doc **from this spec** (PRD is normative; docs are derived, regenerable). *Dep: implemented behavior.*

**Cross-cutting (every phase):** the cold-start drill (M4, R6.3) is a **release gate** — exercise it against the §8 state-machine table once Phase B lands. Shadow mode is the default for any newly-onboarded customer (never autonomous on first opt-in). Opt-in / disabled-by-default (R13.2) constrains every task.

---

## 16. Design risks a coder should know

1. **The cid is the only correctness mechanism — treat it as load-bearing (ADR-2).** Do NOT let any claim/lock/activation logic become a precondition for non-duplication. If you find yourself reasoning "the lock prevents two branches," stop — two branches with the *same cid* is the same branch, and two branches with *different cids for the same issue* is the bug (and means the cid derivation was non-deterministic). Unit-test the cid for determinism across HTTPS/SSH-remote and instance restarts first.
2. **`flock` is unavailable (bash 3.2) — `mkdir` is the mutex.** Never check-then-create the lock dir (TOCTOU). The atomicity is in `mkdir` itself.
3. **`orchestrator_lock_timeout (20m) ≠ max_task_runtime (4h)` (ADR-3, deviation from PRD prose).** The PRD R7.5.5 text says the machine-lock hang timeout is `max_task_runtime`. ADR-3 supersedes: because the lock is released at **spawn** (not held for the task's runtime), a 4h machine-lock hold would itself be the bug. Use a separate 20m timeout for the lock. **This is a `startup-artifact-gap` candidate** — the PRD prose and the ADR diverge; recorded here per the startup-gap-recovery obligation. Since no code exists yet, no prior sign-off is invalidated; the design simply adopts the ADR ruling. Flag to architect if the PRD prose is later treated as governing.
4. **Read-your-writes: never call Search on a correctness path.** Search is eventually-consistent and rate-limited (~30/min). Claim re-verify, idempotency precheck, cost summation, blast-radius, "branch exists?" — ALL must be REST-by-id. Search is cold-reconcile only. A coder who reaches for `gh search` on the hot path has introduced both a correctness bug and a scaling cliff.
5. **`ps` match must be alive-AND-command-match, never bare `kill -0` (O18).** A recycled PID would wedge the machine. The orchestrator must put the `hos-orchestrator` marker in its own argv so `ps -o command=` can see it; if you change how the cron invokes the script, keep that marker.
6. **Allowlist + label-actor checks use the GitHub-API-verified actor, never the envelope/self-reported field.** `from:` is routing only and is checked *after* the author allowlist passes. A label's authority comes from its `labeled` *event actor*, re-verified each cycle (no caching) — the body/label presence alone proves nothing.
7. **The `protected_surfaces.txt` edit (adding `hos-halt` + `PROJECT/hos-coordination.yaml`) is itself a protected-surface change.** Whoever commits it must route that PR to a human approver (the existing `require_human_approval.py` gate will fail it otherwise) and regenerate CODEOWNERS via `gen_codeowners.sh`.
8. **Detection degrades to PROPOSE_ONLY without the #152 follow-up status check (DEP).** Until the risk-tier-vs-ceiling status check ships (separate #152 track), `detect_server_side_gate` cannot confirm above-ceiling enforcement → every repo runs PROPOSE_ONLY. This is **safe** (fail-closed) but means auto-merge is inert until that track lands. Declare this dependency in deployment docs (R9.1.3-gc requires it).
9. **O10 is NOT decided — do not hard-code the human-only suppression class list as final.** Implement the mechanism (configurable list, default `security/privacy/license`) and surface `HUMAN-DECISION-REQUIRED: O10` so a human ratifies the final list before T12 ships. The loop must fail-closed (escalate, never self-suppress) on any class on the list.
10. **Estimation error is acceptable by design (O5) — do NOT add a model pre-pass to "fix" it.** The estimate is a cheap guardrail that errs high; R8.6 re-asks on overrun. A model call to estimate token spend would itself burn the budget the estimate is meant to protect — that is the failure mode being designed out.
11. **JSONL-first, Markdown-derived (R11.8).** If only the JSONL write succeeds, no data is lost; the Markdown is regenerable. Never treat the Markdown as a source of truth or edit it in place (append-only; roll-ups are separate regenerated artifacts).
12. **`hos-halt` is a FILE, not a label.** A label is bot-removable (defeating the emergency stop); the file is on the protected surface so branch protection blocks the bots from merging changes to it. Do not add an `hos-halt` *label* as a shortcut (decision in §13/O20: no such label, to avoid the false impression it is the switch).

---

## 17. Open items routing summary

| Item | Disposition |
|---|---|
| O4 (ledger layout) | **Resolved** — §9: `audit/automation/<customer>/runs/*.jsonl` + manifest, linked from `oversight-log.jsonl`. |
| O5 (estimation signals) | **Resolved** — §9: cheap heuristic + formula, no model pre-pass; historical-median floor. |
| O14 (ack patterns + corpus) | **Resolved** — §6: v1 default list + matching rule + `fixtures/ack_patterns.jsonl` test corpus. |
| O15 (API-call budget) | **Resolved** — §5: default 300 calls / rolling 1h / customer; quota-aware round-robin. |
| O17 (lock path + fallback) | **Resolved** — §4: `/tmp/hos-worker.lock`, fallback `${HOME}/.hos/worker.lock`, machine-global. |
| O18 (ps match pattern) | **Resolved** — §4: script-basename `hos_orchestrator.sh` AND argv marker `hos-orchestrator`. |
| O19 (CODEOWNERS lookup) | **Resolved** — §13: parse `.github/CODEOWNERS`, last-match-wins, team/wildcard/uncovered edge cases fail-closed. |
| O20 (label names + T2) | **Resolved** — §13: `hos-autowork-authorized` confirmed; full `hos-*` set + T2 provisioning; no `hos-halt` label. |
| **O10 (won't-fix human-only classes)** | **NOT decided — flagged for human.** §12: mechanism built (default `security/privacy/license`); `HUMAN-DECISION-REQUIRED: O10`. |
| #152 follow-ups (tier-vs-ceiling check, `provision_agent_account.sh`) | **Out of scope** (separate track, AGENT-IDENTITY §10b); declared as `DEP[#152-followup]` in §10. |

---

*Technical design authored by the technical-design agent from the GO-approved PRD + ADR set. Architect review of this contract is the next gate before any coder picks up Phase A.*
