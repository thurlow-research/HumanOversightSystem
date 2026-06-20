# Agent Availability Is a Setup Property, Not a Runtime Property

**Source:** Observed during v0.4.0 autonomous worker session, 2026-06-19  
**Issues:** #608, #609  
**Status:** Fix in v0.4.0 (validate_setup.sh); setup redesign in v0.5.0

---

## The Finding

Claude Code loads `.claude/agents/` from the working directory at session start. Agent availability is therefore determined entirely by the directory the session is rooted in — not by configuration, not by runtime state, not by any API call. If the working directory contains the right `.claude/agents/*.md` files, the specialists are available. If it doesn't, they silently aren't.

This makes agent availability a **setup property** — fixed at session creation time — not a runtime property that can be inspected or recovered from mid-session.

---

## The Incident

For an entire day (2026-06-19), the worker's autonomous cron sessions were rooted in `/Users/sthurlow/Code/HOS/Worker` — a clone of `ScottThurlow/HumanOversightSystem`, the old stub repo before the project moved to `thurlow-research/HumanOversightSystem`. The stub contains only a README redirect. It has no `.claude/agents/`.

Result: every cron invocation ran with **zero specialist agents available** — no architect, no pm-agent, no technical-design, no code-reviewer, no security-reviewer. The worker's pipeline discipline rules ("spec/behavioral changes → pm-agent + architect + technical-design") were unenforceable because the agents didn't exist in the session.

The worker didn't know this. It attempted to dispatch the architect (`Agent(subagent_type="architect")`) and silently fell back to `general-purpose` when the type wasn't found — posting the result as a binding architectural ruling. Every pipeline gate that depended on a specialist was bypassed by accident of configuration, not by intent.

---

## Why This Is Structurally Dangerous

The pipeline's safety model assumes that specialist agents exist and will be invoked when required. If agents are absent, the worker has two failure modes:

1. **Silent degradation** — the agent call fails or substitutes, the worker continues without specialist review
2. **Visible failure** — the worker detects the absence and stops

Mode 1 is indistinguishable from Mode 2 without a validation step. A worker that "completed" a session without any specialist invocations looks identical to one that ran all specialists and none were needed.

This is the same failure class as a safety check that always returns "safe" — the absence of a signal is mistaken for a clean signal.

---

## The Fix: Validate at Session Start, Block Before Spending Tokens

The correct pattern: run a shell-level preflight check **before Claude is invoked**. Zero token cost. Fail fast.

```bash
# bootstrap/validate_setup.sh
REQUIRED_AGENTS=(architect pm-agent technical-design coder code-reviewer security-reviewer oversight-evaluator)
for agent in "${REQUIRED_AGENTS[@]}"; do
  [[ -f ".claude/agents/${agent}.md" ]] || { echo "SETUP FAIL: ${agent} missing"; exit 1; }
done
```

The cron entry runs this script first; if it exits non-zero, Claude is never launched. The operator sees a clear error message with no token cost and no silent degradation.

For interactive sessions: same script, run manually before starting Claude or wired into a session-start hook.

---

## The Root Cause: Two Clones, One Correct

The intended architecture has two clones of the same repo (`thurlow-research/HumanOversightSystem`):

```
~/Code/HOS/
├── Worker/     ← clone of thurlow-research/HumanOversightSystem
└── Overseer/   ← clone of thurlow-research/HumanOversightSystem
```

Both clones are byte-for-byte identical — same agents, same scripts, same code. The only differences are:
- The **config file** (`~/.config/hos/apps.env` or project-level) — role-specific App IDs and PEM paths, never committed
- The **cron personality** — `--class worker` vs `--class overseer`

What existed instead: the Worker clone pointed at the old stub repo. When the repo moved from `ScottThurlow/HumanOversightSystem` to `thurlow-research/HumanOversightSystem`, the Worker clone's remote was never updated.

---

## Lessons

**1. Working directory is identity.** For Claude Code agent pipelines, the working directory determines what the agent can do. Treat it with the same care as credentials — point it at the wrong place and the entire capability set silently changes.

**2. Agent availability must be asserted, not assumed.** The worker cannot trust that specialists are available because it was configured to use them. It must verify. The verification must be pre-Claude (zero token cost) and hard-blocking (no fallback, no degradation).

**3. Specialist substitution is a governance violation.** Substituting `general-purpose` for `architect` because the architect agent type is unavailable is not a graceful degradation — it is a pipeline bypass. The output of `general-purpose` does not carry the authority, constraints, or accountability of the specialist it replaced. Any ruling produced under the wrong agent type must be treated as suspect and re-issued.

**4. Setup correctness determines pipeline correctness.** An autonomous agent running on a correctly-set-up machine and a correctly-pointed repo will naturally follow the pipeline. An autonomous agent running on a misconfigured machine will naturally bypass it — not maliciously, but because the tools it needs aren't there. Setup validation is therefore a governance control, not just an operational convenience.

---

## Related Findings

- `self-classification-cannot-gate-the-human-boundary.md` — why agents cannot self-authorize
- `working-state-invariant.md` — what must be true at the start of every build step
- `chat-history-as-unreliable-artifact.md` — why session state cannot substitute for durable checks
