# Session Log — 2026-06-11
## HOS Bootstrap, Pipeline Hardening, and First Self-Governance Run

**Duration:** ~7.5 hours (14:56–22:33 PDT)
**Commits:** 24 commits, from repo initialization to template/portability gate hardening
**Branch:** `framework-bootstrap`

---

## What was built

### Phase 1 — Bootstrap (14:56–15:47)

The HumanOversightSystem repository was initialized and the core framework committed in a single large commit (`c87cef6`):

- **6 oversight agents:** `risk-assessor`, `dep-mapper`, `risk-historian`, `oversight-evaluator`, `oversight-orchestrator`, `spec-red-team`
- **9 risk validators:** RN calculator, complexity metrics, function metrics, N+1 detector, migration scorer, hallucination surface, static analysis, prompt audit risk, portability check
- **4 blocking gate scripts:** lint, type, security scan, secrets scan
- **Cross-vendor review scripts:** `run_second_review.sh` (agy at MEDIUM+, codex at HIGH+), `run_red_team.sh` (checkpoint red-teams)
- **Token usage tracker** with subscription impact reporting
- **Portability contract** (`OVERSIGHT-CONTRACT.md`) + step manifest template
- **`install.sh`:** single-command machine setup and project install

Vendor allocation established: agy (Gemini, $20→$100 subscription) = conditional screening at MEDIUM+; codex (OpenAI, $20 reserve) = adversarial probe at HIGH+ only.

### Phase 2 — Architecture documentation (17:01)

`ARCHITECTURE.md` added with Mermaid diagrams showing the two-layer oversight model (self-flagging + independent cross-vendor review) and the agent roles.

### Phase 3 — First self-governance run (17:15–17:45)

The framework was run against *itself* using `review_self.sh`. **This was the first use of the methodology on its own codebase.** Results:

**agy review (`review-20260611T154228.md`, `review-20260611T165546.md`):**
- Found nested function double-counting in the Risk Number calculator (critical — would cause incorrect risk scores)
- Found stale validator output reads (high — risk-assessor was reading wrong-timestamped files)
- Found missing panel handoff consumption in oversight-orchestrator
- Found token tracking errors (incorrect field names)
- Found a contract contradiction: oversight-evaluator and oversight-orchestrator both disclaimed responsibility for GitHub issue creation, leaving a gap
- Found an unenforceable "human concurrence" requirement for lowering risk tiers — no mechanism to check if human actually granted it

**All findings fixed in commits `c90ff97`, `9a2dde6`, `8525409`, `46f41fa`.**

`reverify_self.sh` was then written (`08c4876`) to enable targeted re-review of only the changed files, avoiding re-reviewing the whole codebase after each fix.

**codex review (high-risk adversarial pass):**
- Found Tier 2/3 issues (lower severity) — fixed in `3b4c040`, `3206471`
- Some findings were disputed rebuttals (false positives documented)

### Phase 4 — Framework generalization (17:46–18:32)

Three significant changes:

1. **`dep-mapper` generalized** (`457accf`) — the dep-mapper agent had Django-specific grep patterns and import analysis baked in. This was wrong: dep-mapper is a framework-level agent that should work with any language. Django-specific content was removed; the CondoParkShare copy retains it.

2. **`install.sh` rewritten** (`1ce7eea`) — the initial install.sh was not portable (hardcoded paths, macOS-only assumptions). Rewrote as platform-aware (macOS brew / Ubuntu apt / Fedora dnf / pacman) with proper Python/Node/gh/ScanCode installation paths.

3. **Audit trail wired to contract and install** (`d63a5a4`) — `audit/oversight-log.jsonl` added to the project scaffold; contract updated to require it.

### Phase 5 — Prompts-as-artifacts integration (18:23–18:32)

`risk-assessor.md` updated to read `Prompt-Artifact:` git trailers from commits and invoke `prompt-fidelity` subagent at MEDIUM+. `oversight-evaluator.md` updated to fail compliance if MEDIUM+ commits lack `Prompt-Artifact:` trailers. `oversight-orchestrator.md` updated to include prompt artifact summaries in the panel context document.

ScanCode Toolkit added to machine setup (`9961a1a`) to support Level 1 IP checking (dependency license gate).

### Phase 6 — Portability hardening (21:22–22:33)

Response to issue #8 — five defect classes identified in CondoParkShare Step 10 that the existing gates wouldn't have caught:

- **`template_refs_check.sh`** (new blocking gate): static check that template names referenced in Python source actually exist on disk. Caught 18 missing templates in CondoParkShare Step 10.
- **`portability_check.sh`** (new blocking gate): greps for hardcoded absolute paths in source files (catches `/Users/name/`, `/home/name/`, `C:\Users\`).
- **`django_check.sh`** (new blocking gate): runs `manage.py check --deploy` to catch Django configuration errors before any reviewer time.
- **`PYTHONSAFEPATH=1` hardening**: all inline Python heredocs updated to prevent implicit `.` path injection.

---

## Key decisions

**Decision: vendor allocation is asymmetric by design.** agy fires at MEDIUM+ (frequent) and is subscription-based ($20→$100/month); codex fires at HIGH+ only (infrequent, reserve). This is a deliberate cost/quality tradeoff: agy has a large context window suited to whole-codebase correctness review; codex is reserved for adversarial security probes where its different training distribution matters most.

**Decision: the framework must govern itself.** Before being applied to CondoParkShare, the framework was run through its own review pipeline. This caught real bugs in the framework code. The principle: a governance system that can't govern itself isn't credible. `review_self.sh` is the mechanism.

**Decision: dep-mapper stays generic in HOS.** The framework repo is the master; project-specific content (Django import patterns, ORM models) belongs in the project's customized copy. This was the first explicit instance of the HOS/project-repo separation principle.

**Decision: `reverify_self.sh` for targeted re-review.** Rather than re-running the full self-review after each fix (expensive, redundant), a targeted re-review script was written that only reviews the changed files. This establishes a pattern: fix → targeted verify → fix → targeted verify, rather than fix → full review.

---

## Surprises

1. **The framework had real bugs on its first self-review.** The Risk Number calculator double-counted nested functions, which would have produced inflated risk scores for complex code. This was found within the first hour of the first self-review run. The irony: the oversight tool had bugs that only its own oversight process caught.

2. **Contract gaps appear even in carefully-designed systems.** The oversight-evaluator and oversight-orchestrator both disclaimed responsibility for GitHub issue creation, leaving that responsibility to "base agents or scripts" — which also wasn't explicitly assigned. A gap in a two-line contract section, caught by agy.

3. **Portability was an afterthought in the initial design.** The first `install.sh` assumed macOS, had a hardcoded project path, and wasn't idempotent. This was recognized and fixed in a single session, but it illustrates that portability requires explicit design attention even for a tool built by an experienced developer using an AI assistant.

4. **The "unenforceable requirement" problem.** `risk-assessor.md` said "you can only lower the risk tier with human concurrence" but provided no mechanism to check whether human concurrence had been granted. The validator would either always refuse to lower risk (too conservative) or defer to the AI's judgment about what "human concurrence" means (the anti-pattern we're trying to prevent). Fixed by introducing a flag-file convention (`.claudetmp/oversight/human-tier-override.md`).

---

## Artifacts produced

| Commit | What |
|---|---|
| `c87cef6` | Full framework bootstrap — 6 agents, 9 validators, 4 gates, review scripts, token tracker, install.sh |
| `fcaa4fe` | `ARCHITECTURE.md` with Mermaid diagrams |
| `c90ff97`–`46f41fa` | agy findings fix cycle |
| `08c4876` | `reverify_self.sh` — targeted re-review script |
| `3b4c040`–`3206471` | codex findings fix cycle |
| `457accf` | dep-mapper generalized |
| `1ce7eea` | `install.sh` rewritten (portable, platform-aware) |
| `d63a5a4` | Audit trail wired |
| `a6eab26` | Prompts-as-artifacts integrated into oversight pipeline |
| `9961a1a` | ScanCode Toolkit in machine setup |
| `7e4d2b8` | ip_check Level 3 stub corrected |
| `7827de8`–`457ebf2` | Portability hardening + 3 new blocking gates |
