# Finding: Give a non-deterministic reviewer its known-issues list, and it converges by construction

**Role:** oversight-mechanism — the difference between a gate that converges and one that churns forever

**First observed:** 2026-06-13, v0.1.1 release-gate convergence

---

## The finding

A non-deterministic adversarial reviewer (LLM self-review, or cross-vendor agy/codex) on a rich governance corpus **never reports nothing** — it keeps surfacing real findings, including ones already known and filed. The first defense was a **post-hoc dedup ledger**: let the reviewer report everything, fingerprint each finding, and filter out ones already dispositioned. It works, but it loses a race — the reviewer *spends its whole budget* re-deriving the same known issues every run, so each run still surfaces "new" blocking findings (a mix of genuinely-new and not-yet-fingerprinted variants of known ones), and the gate keeps failing.

The fix is to move the dedup **upstream, into the reviewer's own context**: fetch the open GitHub issues and inject them into the review prompt as *"these are already tracked — do NOT re-report them; only surface what's new."* The reviewer then never wastes attention on known issues and its output is, by construction, closer to "only genuinely new findings."

Measured directly during the v0.1.1 cut: the same scoped self-review that returned **2–3 new blocking findings per run** (dominated by re-reports of the tracked forgeable-human-gate and structural-gaming issues) dropped to **1 new** the run after the known-issues block was added — and that 1 was a *genuinely new* contradiction, not a re-report. The signal-to-noise inverted.

## Why it matters for scalable oversight

This is the operational key that makes "a gate built on a non-deterministic reviewer" actually shippable. Without it, the gate either never passes (the reviewer keeps finding known things) or you disable it (worst outcome). The two mechanisms compose:

- **Proactive (this finding):** feed the reviewer the issue tracker so it doesn't *generate* known-issue noise. Cheaper (no wasted reviewer budget), and it makes each run's output meaningful on its own.
- **Reactive (the dedup ledger):** still needed as a backstop, because the reviewer is non-deterministic — it may phrase a known issue differently than its tracked title, slip past the "skip these" instruction, or surface a genuinely-new variant. The ledger catches what leaks past the prompt.

Together they turn an adversarial reviewer from a *blocker* into a *triage funnel*: it reports mostly-new findings, the human/triage step dispositions them (fix / file / accept-residual), and the next run sees them as known. This is also exactly how a competent human reviewer is briefed — *"here's the known-issues list, tell us what's new"* — not *"re-find everything from scratch each time."*

## The mechanism

- Before building the review prompt, fetch open issues (`gh issue list --json number,title`) and inject a `=== KNOWN, ALREADY-TRACKED ISSUES — do NOT re-report ===` block (env-gated by `HOS_FEED_KNOWN_ISSUES`, default on). Applied to both the Opus self-review and the agy/codex cross-vendor reviewers.
- Keep the dedup ledger as the backstop (proactive context + reactive fingerprint).
- Guardrail (don't let it suppress real findings): the instruction is "skip a finding already *covered* by a tracked issue," not "skip anything touching these files." A genuinely-new problem in a file that also has a tracked issue must still be reported. And the issue list is the *human-curated* set — the reviewer is told what's tracked, it doesn't get to decide what's "known."

## The trap it avoids

Two failure modes. Without proactive context, the gate **churns** (re-reports known issues, never converges, gets disabled). With *too aggressive* a skip instruction ("ignore these areas"), the reviewer **goes blind** to new problems near old ones. The narrow correct framing — "these specific findings are tracked; report anything not covered by them" — keeps the reviewer adversarial about everything new while silent about everything already on the books.

## Provenance

Observed 2026-06-13 during v0.1.1 release-gate convergence: post-hoc ledger dedup was losing the race (2–3 new per run, mostly re-reports); adding the known-issues block to `validate_self.sh` + `validate_agents.sh` dropped it to 1 genuinely-new per run. Related: `nondeterministic-review-gate-converges-on-zero-new.md` (the reactive ledger this completes), #133 (the triage/accept disposition step), #131 (the daily async sweep that will lean on this so it doesn't re-file known issues), #78 (cross-vendor fingerprint reconciliation).
