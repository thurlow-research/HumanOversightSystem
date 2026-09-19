# ADR-1643 — AMENDMENT 6: which shipped agent fills `validate_scripts.sh`'s Opus seat (W4 §6.2)

**Status:** ACCEPTED — binding on `technical-design` (TD-1643 §6.2, §6.3), on `coder` for slice W4, and on the future slice W4c (#1756) defined below.
**Date:** 2026-09-19
**Author:** architect
**Amends:** **AD-16** — its enumeration of which `claude -p` sites migrate in W4. `scripts/framework/validate_scripts.sh` is **removed from W4** and becomes **W4c** (#1756), a third recorded exemption until W4c lands. AD-16's escape clause ("if promoting the lens to an agent is too large for W4, say so and split it — **not** add a bare-model escape hatch") is the mechanism being exercised, exactly as TD-F4 exercised it for `run_panel.sh`/W4b.
**Confirms without change:** **AD-3** (no bare-model path), AD-5.3, and W4 §6.1, §6.3, §6.4, §6.5, §6.6.
**Inputs:** `scripts/framework/validate_scripts.sh` (the `LENS` variable and `run_reviewer`); `.claude/agents/self-reviewer.md`; `.claude/agents/code-reviewer.md`; `.claude/agents/security-reviewer.md`; `TECHNICAL-DESIGN-1643-invocation-primitive.md` §6.1–§6.6; `tests/framework/test_agent_invocation_migration.py` T4.1.

---

## AD-16.1 — `self-reviewer` does not fill the scripts seat, and neither does any agent shipped today

`validate_scripts.sh`'s lens reviews **programs**: bash quoting under `set -euo pipefail`, empty-array
expansion on bash 3.2, BSD-vs-GNU `sed`/`mktemp`, fetch-execute integrity, and the Python validator
output-schema contract. `.claude/agents/self-reviewer.md` scopes itself to **governance text** — "Your
subject is a **rule**, not a program … 'Does this code work?' is not your question and never becomes your
question" — and routes application-code correctness to `code-reviewer` and exploitable vulnerabilities to
`security-reviewer` by name. Its seven categories are all properties of a rule; none of them can express
"this `sed -i` is GNU-only."

Pointing a deterministic, fail-closed lane at an agent whose own definition says the corpus is out of lane
produces a gate that *looks* like it is reviewing and is not. That is the exact failure epic #1643 exists
to eliminate, so it is not shippable, and `self-reviewer:13`'s "the rules encoded in framework scripts"
does not rescue it — a rule encoded in a script is still a rule, not the script's bash correctness.

## AD-16.2 — `code-reviewer` and `security-reviewer` are also unavailable for this seat

Rejected on their **input contract**, not merely on subject matter. Both carry the identical CORE block:

> **REVIEW INPUT (DIFF-CENTRIC — DO NOT CIRCUMVENT):** Your primary input is the git diff provided. Do not
> request full-repository context. … PROJECT may NEVER override, weaken, or remove this constraint.

`validate_scripts.sh` supplies the opposite: a whole-corpus package (every file matching
`bootstrap/*.sh`, `scripts/**/*.sh`, `scripts/oversight/**/*.py`), with **no diff**, no technical design
and no ADR — and in its default, non-`--changed-only` mode that is the entire script surface of the
repository. Invoking either agent on that package asks it to review in the one shape its CORE forbids.
Substituting a *non-overridable* constraint violation for a lane violation is not an improvement.

The shape is wrong in three further respects, each independently sufficient:
1. Both are **inner-loop** reviewers that iterate with the `coder` and write sign-off register entries.
   There is no coder, no build step, and no register here; iteration is the script's own ledger and
   `MAX_PASSES`. `self-reviewer` was authored with the correct one-shot shape precisely because that
   difference is real.
2. Both declare `model: sonnet`. This is the Opus seat, and its Opus-ness is a decorrelation property of
   the review panel, not a tuning knob.
3. The lens is **one** prompt, one document, one verdict, one ledger. Splitting it across
   `code-reviewer` (bullets 1, 2, 5) and `security-reviewer` (bullets 3, 4) would require two invocations
   and a merge rule for two verdicts that `run_reviewer` does not have and that W4 has no mandate to
   invent. **One seat, not two.**

## AD-16.3 — RULING: a new shipped agent, delivered as its own slice W4c (#1756)

The seat is filled by a **new shipped agent file**, working name `scripts-reviewer`: a one-shot,
read-only, whole-corpus adversarial reviewer of *shell and Python program correctness* in the framework's
own tooling. It is `self-reviewer`'s sibling — same invocation shape, same strict-JSON output contract,
same "package defines your scope" discipline, same no-`Write` posture — with the five-bullet program lens
in place of the seven governance categories, and reciprocal lane discipline (governance text →
`self-reviewer`; a consumer project's application diff → `code-reviewer`/`security-reviewer`).

A new `.claude/agents/*.md` is a **protected surface** and a change to what every consumer installs
(`scripts/framework/consumer_agents.txt`, `.hos-manifest`). It therefore requires human approval and
carries a product consequence, which is why it cannot ride inside W4 as a plumbing line. **W4c's scope:**
author `.claude/agents/scripts-reviewer.md`; register it in `consumer_agents.txt`; migrate
`validate_scripts.sh`'s `opus` branch to `invoke_agent.sh --agent scripts-reviewer`; remove
`scripts/framework/validate_scripts.sh` from T4.1's exemption set. Depends on W1. Blocked only on human
approval of the new agent file.

## AD-16.4 — What W4 ships now

- **§6.2 is reverted out of W4.** `validate_scripts.sh`'s `opus` branch keeps its raw `claude -p` for now.
- **§6.3 still lands in full.** `run_capped` and `_TIMEOUT_BIN` are deleted from `validate_scripts.sh` as
  designed; the unmigrated `opus` site uses `with_timeout` with its own explicit redirection, identically
  to the `agy`/`codex` sites:
  `printf '%s' "$prompt" | with_timeout "$AI_REVIEW_TIMEOUT" claude -p --model "$MODEL" > "$out" 2>/dev/null || rc=$?`.
  Two of `run_capped`'s three behaviours over `with_timeout` — the stdout-to-file redirect and the stderr
  discard — are supplied at the call site. **The third is not, and is lost: a correction to this
  document's first revision, which claimed the redirect and the discard were the only two.** `run_capped`
  also carried a portable poll / `kill -TERM` (2s grace) / `kill -KILL` fallback for hosts where neither
  `timeout` nor `gtimeout` is on `PATH`; `with_timeout` (`scripts/oversight/run_with_retry.sh:55-63`) has
  no such fallback — it accepts the timeout argument and runs the command **completely unbounded** in that
  case. The host class is real (stock macOS ships no `timeout`; `gtimeout` needs `brew install coreutils`,
  a gap `bootstrap/hos_bootstrap.sh:205-219` already documents and tolerates as warn-not-fail), and the
  consequence is that after W4 the three sibling validators diverge on such a host: `validate_agents.sh`
  bounded (it keeps its private `run_capped`), `validate_scripts.sh` **unbounded**, `validate_self.sh`
  bounded by the primitive's host-independent Python-level `killpg`. **The loss is ACCEPTED for W4** —
  it matches the repo's existing posture toward that gap, and the remedy belongs in the shared helper, not
  in a reinstated private copy in one caller. Remedy tracked at **#1757** (port the fallback into
  `with_timeout`), which **#1671 must not precede**: replacing `validate_agents.sh`'s `run_capped` with
  `with_timeout` before #1757 lands would remove hang protection from a third script. AD-5.3 is satisfied
  without §6.2. Note that TD §6.1's *"the unbounded timeout … is gone"* refers to `validate_self.sh`'s
  prior complete absence of any timeout — a different claim, and still correct.
- **The `command -v claude` preflight is restored** in `validate_scripts.sh`. Its removal was justified
  only by `invoke_agent.sh` taking over CLI resolution; with the site unmigrated, deleting it would leave
  the required lane with no CLI check at all.
- **T4.1 gains a third tracked exemption**, `scripts/framework/validate_scripts.sh`, commented as exempt
  **until W4c (#1756)** in the same form as the existing W4b entry, so the set shrinks automatically as slices land.
- **§6.1, §6.4, §6.5, §6.6 are unaffected** and need no rework.

## AD-16.5 — Startup-gap and affected sign-offs

**This should have been settled in the initial architecture review.** AD-16 enumerated the call sites but
assumed a single self-review lens covered both `validate_self.sh` and `validate_scripts.sh`; they are two
different lenses over two different corpora. ESC-J surfaced half of that gap and W4a closed it; this is
the other half, and it belongs to the same `startup-artifact-gap` class — annotate the existing
`startup-artifact-gap` record rather than opening a second one.

**Affected-sign-offs analysis:** no prior sign-off is orphaned. The `--agent self-reviewer` wiring in
`validate_scripts.sh` exists only as an uncommitted working-tree change and has been approved by no
reviewer; W4a's sign-offs cover `self-reviewer` for the `validate_self.sh` governance seat, which this
amendment confirms unchanged; §6.3/§6.5/§6.6 sign-offs were never taken against this decision. Nothing
already reviewed needs re-review — only the W4 diff currently in flight must be amended before review.
