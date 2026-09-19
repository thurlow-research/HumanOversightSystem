# ADR-1643 — AMENDMENT 6: W4's ruling record — the scripts-review seat, `validate_scripts.sh`'s retained timeout copy, and `validate_self.sh`'s auth routing

This document has grown beyond its original title's subject (AD-16.1–16.3, which shipped agent fills
`validate_scripts.sh`'s Opus seat) to record every ruling made against W4 in flight: AD-16.4/AD-16.6 on
`validate_scripts.sh`'s private timeout copy, and AD-16.7 on `validate_self.sh`'s env-auth routing. It is
retitled to match — the ruling text of every section (AD-16.1 through AD-16.7) is unchanged; only this
title and the summary metadata below have been updated to describe the full contents accurately. The
filename is kept as-is so existing references (issues, the TD, `tests/framework/test_agent_invocation_migration.py`) still resolve.

**Status:** ACCEPTED — binding on `technical-design` (TD-1643 §6.2, §6.3), on `coder` for slice W4, and on the future slice W4c (#1756) defined below.
**Date:** 2026-09-19
**Author:** architect
**Amends:** **AD-16** — its enumeration of which `claude -p` sites migrate in W4. `scripts/framework/validate_scripts.sh` is **removed from W4** and becomes **W4c** (#1756), a third recorded exemption until W4c lands. AD-16's escape clause ("if promoting the lens to an agent is too large for W4, say so and split it — **not** add a bare-model escape hatch") is the mechanism being exercised, exactly as TD-F4 exercised it for `run_panel.sh`/W4b.
Also amends **AD-5.3** — its deletion of `validate_scripts.sh`'s private `run_capped` is **SEQUENCED behind #1757**, not cancelled (AD-16.4, AD-16.6).
Also amends **Amendment 1 §9.3** — its default-off framing of `--require-env-auth` is **SUPERSEDED** for `validate_self.sh` and every future HOS-shipped primitive caller: the default is now on, with an explicit opt-out (AD-16.7).
**Confirms without change:** **AD-3** (no bare-model path), and W4 §6.1, §6.4, §6.5, §6.6.
**Inputs:** `scripts/framework/validate_scripts.sh` (the `LENS` variable and `run_reviewer`); `scripts/framework/validate_self.sh` (`REQUIRE_ENV_AUTH_FLAG` and its argument parser); `.claude/agents/self-reviewer.md`; `.claude/agents/code-reviewer.md`; `.claude/agents/security-reviewer.md`; `TECHNICAL-DESIGN-1643-invocation-primitive.md` §6.1–§6.6; ADR-1643 Amendment 1 §9.3; `tests/framework/test_agent_invocation_migration.py`.

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
- **§6.3 does NOT land for `validate_scripts.sh` in W4 — its `run_capped` and `_TIMEOUT_BIN` stay,
  verbatim, and all three of its reviewer sites keep using them.** This **reverses this document's own
  earlier acceptance** of the unbounded-fallback loss (see AD-16.6, which records both the original
  acceptance and why it did not survive contact with the cross-vendor review). `with_timeout`
  (`scripts/oversight/run_with_retry.sh:55-63`) accepts the timeout argument and then runs the command
  **completely unbounded** when neither `timeout` nor `gtimeout` is on `PATH`; `run_capped` carried a
  portable poll / `kill -TERM` (2s grace) / `kill -KILL` fallback for exactly that host, and that
  behaviour is **not** suppliable at the call site (the stdout-to-file redirect and the stderr discard,
  its other two behaviours, are). **AD-5.3's deletion binding is therefore SEQUENCED, not satisfied:** it
  is deferred until `with_timeout` provides host-independent enforcement (**#1757**), at which point
  `validate_scripts.sh` and `validate_agents.sh` delete their private copies together. **#1671 must not
  precede #1757** for the same reason. Note that TD §6.1's *"the unbounded timeout … is gone"* refers to
  `validate_self.sh`'s prior complete absence of any timeout — a different claim, and still correct.
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

---

## AD-16.6 — Reversal of the accepted `with_timeout` risk, on cross-vendor challenge (2026-09-19)

**Ruling: option (b) — `validate_scripts.sh` keeps its private `run_capped` until #1757 lands.**

**What changed.** The first revision of AD-16.4 accepted the loss of `run_capped`'s TERM/KILL fallback,
resting on `bootstrap/hos_bootstrap.sh:205-219`'s warn-not-fail tolerance of a missing `coreutils`.
`reliability-reviewer` concurred, both framing it as **availability**. The HIGH-tier cross-vendor second
review (codex, CWE-400, `validate_scripts.sh:172`) reframed it as a **reachable denial of service on a
required, fail-closed oversight lane**. That framing was not before me when I accepted the risk, and it
defeats the precedent I relied on: `hos_bootstrap.sh` tolerates the gap for a *convenience* path during
machine setup, not for a gate whose entire contract is that it terminates with a verdict. A control that
can be made to never return is not an availability nuisance — it is the gate failing open by not
finishing.

**Three findings decide it:**

1. **The hang is attacker-influenceable, not merely unlucky.** `run_reviewer`'s prompt package embeds
   `KNOWN_ISSUES`, assembled from live `gh issue list` titles — content any issue-filer can write —
   alongside the whole script corpus. An input that reliably stalls a model or its tool loop is therefore
   reachable by someone who never touches the repository. codex is right that this is a security finding,
   not a portability one.
2. **The exposed population is consumers, not just this repo.** `validate_scripts.sh` ships to consumer
   projects (`ARCHITECTURE.md:95`, `tests/framework/test_consumer_framework_files.py:22`), so the exposed
   host class is every consumer install on a macOS machine without `coreutils` — an ordinary developer
   machine, not an exotic one.
3. **Option (a) is the wrong change to make inside this slice.** `with_timeout` has five live callers
   beyond this one — `run_validators.sh`, `run_second_review.sh`, `lib/vendor_invoke.sh`, and the two
   **blocking gates** `gates/secret_scan.sh` and `gates/security_scan.sh`. On the affected host class
   their timeout argument is inert today; porting the fallback would newly let those gates return 124
   where they previously ran to completion. That is a behaviour change to blocking gates, and it deserves
   its own slice, its own tests and its own review — not a line inside a migration PR. **#1757 remains the
   right home for the fix; it is not the right work for W4.**

**Why (b) over (c).** The governing principle is a ratchet: *an existing control is not removed before its
replacement demonstrably provides equivalent enforcement.* AD-5.3 mandated the deletion on the premise
that `with_timeout` was an equivalent shared replacement. That premise is false on a supported host, so
the binding is honoured by **sequencing** it behind #1757 rather than by executing a deletion whose
justification has evaporated. Amendment 1 §9.4 is the precedent for amending a binding when its factual
basis changes. Option (b) also leaves `validate_scripts.sh` and `validate_agents.sh` consistent — both
bounded by their private copies, both deleting them together once #1757 lands — rather than divergent.

**Concrete change for `coder` (W4):** revert §6.3's edits to `scripts/framework/validate_scripts.sh` in
full. Restore `_TIMEOUT_BIN` and `run_capped` verbatim; restore all three `run_reviewer` branches
(`opus`, `agy`, `codex`) to their original `run_capped "$AI_REVIEW_TIMEOUT" "$out" …` form; drop the
`source "$ROOT/scripts/oversight/run_with_retry.sh"` line and the per-call-site `> "$out" 2>/dev/null`
redirections added for `with_timeout`. Replace the §6.3 comment block with a short note that the private
copy is **deliberate and temporary**, citing AD-5.3, this section, and **#1757**, so no future reader
"finishes the job" early. `validate_agents.sh` is untouched (#1671). Everything else in W4 —
§6.1, §6.4, §6.5, §6.6, and §6.2's revert with the `command -v claude` preflight restored — is unaffected.
**Net effect: W4 changes `validate_scripts.sh`'s timeout behaviour not at all**, which is the intent.

**Affected sign-offs:** any W4 sign-off taken against the `with_timeout` version of
`validate_scripts.sh` is invalidated by this reversal and must re-review the reverted file. No other file
in the slice is affected.

---

## AD-16.7 — `validate_self.sh`'s env-auth routing: explicit flag, fail-closed default (2026-09-19)

**Ruling: adopt codex's second option — default to `--require-env-auth`, add an explicit
`--allow-keychain-auth` opt-out, and delete the TTY/`CI`/`HOS_CYCLE_ROLE` inference.** codex's first
option (autonomous callers opt *in*) is rejected: its failure mode is inverted, so a new or forgetful
autonomous caller silently gets keychain auth, which is the defect being reported.

**Reasoning.** Identity routing must not be inferred from ambient environment shape, because every signal
available — a pty, an unset `CI`, a supervisor that preserves terminal fds — is controllable by the
caller being classified. The only sound default for a control that distinguishes bot credentials from
human ones is the strict branch, with a deliberate, named opt-out. `security-reviewer` is right that a
missed flag still fails closed post-hoc, which correctly bounds this to HIGH rather than CRITICAL, but
fail-closed-eventually is not an answer to *which identity the gate ran under* — that is the question
codex asked, and it is the right one.

**`HOS_CYCLE_ROLE` is retained, in one direction only: as a veto on the opt-out, never as a router.**
When `HOS_CYCLE_ROLE` is set and `--allow-keychain-auth` was passed, the run is refused. That use can
only ever make a run *stricter*, so codex's "do not infer" objection does not reach it: a false positive
fails closed and is corrected by unsetting a variable, whereas the inference being deleted had a false
*negative* that silently weakened the control. Retaining it as a belt-and-braces *router* alongside the
explicit flag is rejected — that would reinstate exactly the heuristic being removed.

**The human-workflow cost is accepted, conditionally.** A maintainer running `validate_self.sh` by hand
must now pass `--allow-keychain-auth`. This is a contract change on a script that ships to consumer
projects, so it is accepted **only if the failure names the remedy**: the failure path must emit one
stderr line naming `--allow-keychain-auth` verbatim and saying why, and the script's usage block and
header must document both flags. An undiscoverable fail-closed is a worse outcome than the heuristic.
`scripts/framework/**` is a protected surface, so the human approval gate on this PR is where the
contract change gets its product sign-off; it needs no separate routing.

**Amends Amendment 1 §9.3.** That ruling's sentence *"The flag's default stays off"* is **SUPERSEDED**
for `validate_self.sh` and for every future HOS-shipped caller of the primitive: the default is **on**,
and the opt-out is explicit. §9.3's substance is otherwise confirmed in full — the pre-flight remains
opt-*out* rather than mandatory-always (a human path still exists), post-hoc `not_authenticated`
classification remains unconditional, and §9.3's rejection of the three probe/keychain/file-layout
alternatives stands untouched. §9.3's framing of the flag as a **caller obligation** is strengthened, not
weakened: an obligation discharged by default cannot be forgotten.

**Exact change for `coder` (W4):**
1. In `scripts/framework/validate_self.sh`, delete the `REQUIRE_ENV_AUTH_FLAG` inference block
   (`HOS_CYCLE_ROLE` / `CI` / the three-way `! -t` conjunction) and the comment explaining it.
2. Initialise `REQUIRE_ENV_AUTH_FLAG="--require-env-auth"`. Add `--allow-keychain-auth` to the argument
   parser; when passed, set it empty.
3. Veto: if `HOS_CYCLE_ROLE` is non-empty **and** `--allow-keychain-auth` was passed, print a one-line
   explanation to stderr and exit 2. Never the reverse — `HOS_CYCLE_ROLE` alone changes nothing.
4. Name `--allow-keychain-auth` verbatim on stderr in the auth-failure path, and document both flags in
   the usage block and the file header.
5. Tests: the default argv contains `--require-env-auth`; `--allow-keychain-auth` omits it; the
   `HOS_CYCLE_ROLE` + opt-out combination exits non-zero; no `-t 0`/`-t 1`/`-t 2` or `CI` test remains in
   the file's auth routing.

**Scope.** `validate_scripts.sh` is unaffected in W4 — its `REQUIRE_ENV_AUTH_FLAG` stanza is reverted out
with §6.2 (AD-16.4). **W4c (#1756) must adopt this same contract** when it migrates that site; it does not
get to reinvent the routing. **#1758** (the primitive does not record which auth branch it took) remains
complementary and is not satisfied by this ruling: this decides which branch is taken, #1758 makes the
branch observable after the fact.
