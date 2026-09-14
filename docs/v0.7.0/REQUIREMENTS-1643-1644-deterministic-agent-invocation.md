# REQUIREMENTS-1643 + 1644 — Deterministic agent invocation: every review dimension and every build-pipeline step is a CLI call a script makes and a script judges, never a parent agent's discretion

**Status:** DRAFT for architect. **Eight product/boundary decisions escalated to the human (§5)** —
architect may proceed on the settled requirements but MUST NOT bind Q1, Q2, Q3, or Q7 before the
human rules them. The mechanism is **structural** for both epics (it introduces new gating decision
points, changes who may declare a step complete, and changes the permission posture under which
`coder` executes) and requires explicit human sign-off before `architect` binds it.
**Six §0 findings materially change what must be built** — **VF-1**, **VF-4**, **VF-7**, **VF-9**,
**VF-10**, **VF-12** — three of them contradict or sharpen an assumption stated in the source issues.
**Date:** 2026-09-14
**Author:** pm-agent
**Source issues:**
- **#1643** (open, `bug`/`needs-human`/`process-gap`/`priority:critical`, v0.7.0 — Quality). Body +
  its three 2026-09-14 comments (confirmed-mechanism, stuck-detection refinement, sibling-filed) are
  binding requirements input.
- **#1644** (open, `enhancement`/`needs-human`/`process-gap`/`priority:high`, v0.7.0 — Quality). Body
  only; **the issue has zero comments** (verified 2026-09-14 — the stuck-detection refinement the
  task brief attributes to it lives on **#1643**, and is treated here as binding on both).
- Context, cited not re-derived: #1357, #1358 (origin of "USE THE CODE, don't narrate"); #1604
  (origin of "detect stuck, don't blind-retry"); #1641 (the near-miss); #1594, #1615 (the
  register-self-report defect class); #1580 (the bounce gate this must not duplicate).
- Already-filed children to be re-scoped: **#1536**, **#1567 Gap 5 / #1642**, **#1621**, **#1626**,
  **#1629**.
**Target:** `architect` (next) → `technical-design` → decomposed `needs-ai` issues in v0.7.0.
**Consumers:** `architect`, then `technical-design`, then whoever files the decomposition in §6.
**Scope note:** This document says WHAT and WHY only. No function signatures, file layout, language
choice (bash vs. Python), JSON field names, model selection, or prompt text is specified here —
those are `architect`'s and `technical-design`'s. Every numeric default below is a **recommended
default with a stated floor**; the binding values are the human's (§5).

**Why one document for two epics.** Human instruction, 2026-09-14: *"Let's have spec team consider
them together and spawn work items as appropriate. That will promote common design and scripts where
possible."* The finding of §2 is that the two epics are not merely similar — they need the *same*
primitive, and six already-filed issues are each about to build a private copy of it. Handing
`architect` two separately-specified systems would guarantee the duplication this pass exists to
prevent.

---

## 0. Verification findings — where the two epics meet the repo

Every load-bearing claim in both epics and in the task brief was re-derived from the repository, not
taken as given. Citations are to this worktree's checkout of
`human-1564-sandbox-policy-audit-decision-log` unless noted; none of the cited files differ from
`origin/main` in the regions quoted.

**Verification gaps, stated up front.** (a) `#1644` has **no comments** — the API returns an empty
comment list. The task brief's framing of #1644 as carrying the stuck-detection refinement is
inaccurate as to location; that refinement is #1643's second comment. Both are treated as binding on
both epics, which is what the comment itself asks for (*"This applies to whichever of the two
epic-scoping options gets picked"*). (b) No behavior was run under `bin/hos-cron`; the nesting-budget
finding (**VF-11**) is read from the launcher source, not observed in a live cycle. (c) The live
GitHub branch-protection required-check list was not queried; VF-5's claim about `signoff_gate.py` is
a repository-source claim (it appears in no workflow file), not a branch-protection claim.

---

**VF-1 — PARTIALLY CONTRADICTS #1643's confirmed-mechanism comment. `claude --print --agent <name>`
is a real flag, but a nested invocation does *not* inherit the parent session's authentication or
its permission trust, and both failures are silent-looking.**

`claude --help` lists `--agent <agent>  Agent for the current session. Overrides…` — the flag is
real, and the probe below shows it is accepted, not rejected as unknown. But the probe run from
inside this agent session returned:

```
Ignoring 9 permissions.allow entries from .claude/settings.json: this workspace has not been
trusted. Run Claude Code interactively here once and accept the trust dialog, or set
projects["…"].hasTrustDialogAccepted: true in /home/scott/.claude.json
{"…","is_error":true,"terminal_reason":"api_error","subtype":"success",
 "result":"Not logged in · Please run /login","permission_denials":[],"num_turns":1,…}
```

Three things follow, and all three are requirements, not trivia:

1. **Auth is not inherited from the parent Claude session.** It comes from the *environment*.
   `bin/hos-cron:884-887` sources `~/.config/hos/claude-auth.env` under `set -a`, so
   `CLAUDE_CODE_OAUTH_TOKEN` *is* exported into the cron role's environment and a nested call under
   cron would inherit it. A nested call from an interactive human session (keychain auth, no env
   token) fails exactly as above. **The primitive must therefore fail closed on an auth failure and
   must be usable — or must refuse loudly — outside cron.**
2. **The nested workspace is untrusted and `permissions.allow` is discarded.** A nested `--agent
   coder` starts with no tool permissions from the project settings. `bin/hos-cron:1764` passes
   `--permission-mode bypassPermissions` to the *parent*; a nested call inherits nothing of that.
   The permission posture of a nested invocation is an explicit choice someone has to make
   (escalated as **Q3**).
3. **`subtype` says `"success"` while `is_error` is `true`.** A caller that reads the wrong field
   reads a hard failure as a clean pass. The process *did* exit non-zero for this failure class
   (verified separately), so today's `rc -ne 0` guard in `validate_self.sh:245` would catch *this*
   case — but the envelope carries at least four independent failure signals (`is_error`,
   `terminal_reason`, `permission_denials`, `subagent_stats.refused`) and exit code alone is not
   specified to track all of them (e.g. `--max-turns` exhaustion, a usage-limit stop). **Fail-closed
   must be defined over the envelope, not over `rc` alone** (REQ-A6).

**VF-2 — CONFIRMED, search-first, no helper exists.** Searched `scripts/` (recursive),
`bootstrap/`, `bin/`, and `scripts/automation/lib/*.py` for any "invoke a claude agent via CLI and
parse its output" helper. **Found nothing.** There are exactly four `claude -p` invocation sites in
the entire repository — `scripts/run_panel.sh:146-147`, `scripts/framework/validate_scripts.sh:182`,
`scripts/framework/validate_self.sh:236`, `bootstrap/setup_clis.sh:148` (a smoke test) — and **none
of them uses `--agent`.** Every one invokes a bare model with a hand-assembled prompt. The primitive
both epics need does not exist in any form today.

**VF-3 — the four sites already carry three *different and inconsistent* reliability postures, plus
a duplicated timeout helper. This is the concrete cost of not having one wrapper.**

| Site | Timeout | Fail-closed on error/empty | Notes |
|---|---|---|---|
| `run_panel.sh:146-147` | **none** | **none** — stderr to a log, output used as-is | |
| `validate_self.sh:236` | **none** — unbounded | yes (`rc`/empty → synthesized `verdict:"error"`, #1362) | a hang here hangs all of framework validation |
| `validate_scripts.sh:182` | `run_capped` (`AI_REVIEW_TIMEOUT`, 300s) | yes, **tiered**: required lane → synthesized *blocking* finding; optional lane → non-blocking `error` (#669) | the most correct of the three |
| `setup_clis.sh:148` | none | n/a (smoke test) | |

Separately, `validate_agents.sh` and `validate_scripts.sh` each define their own private `run_capped`
+ `_TIMEOUT_BIN` pair, even though `scripts/oversight/run_with_retry.sh` already exports a
`with_timeout` for exactly this. That is a live instance of the duplicate-helper class #1575 audits.
**Three postures across four sites, and the two most-used gates disagree about whether an AI reviewer
may hang forever.** Adding six more private copies (the six children in §3.4) without a shared
wrapper is the predictable next step, and it is what this pass must prevent.

**VF-4 — ANSWERS #1643's OWN OPEN QUESTION, and the answer is worse than "trusts the register":
`decide_merge_authority()` does not consider review dimensions at all.**

#1643 asks: *"has anyone confirmed `decide_merge_authority()` actually can't be satisfied without a
real code-reviewer/security-reviewer pass, or does it currently trust the same register-based
self-report #1594/#1615 already found broken?"* Read in full at
`scripts/automation/lib/merge_authority.py:472-707`:

- Its 21 parameters include **no reviewer, sign-off, register, or dimension parameter of any kind.**
  The only review-shaped input is `oversight_verdict: str` — *"PROCEED" | "CONDITIONAL_PROCEED" |
  "ESCALATE"* — a **caller-supplied string**. It is checked once (`:599`) for `!= "PROCEED"`. Nothing
  verifies where the string came from or that any reviewer ran.
- `check_register_completeness()` (`:888`) — the function that *does* look at sign-offs — is a
  **separate** function that `decide_merge_authority()` never calls. Their only composition is prose:
  `overseer.md:272` (step 4a) and `:294` (step 5) tell the agent to call them in that order.
- **`merge_authority.py` has no `__main__`, no `argparse`, and no production caller anywhere.**
  Grepping `scripts/`, `bin/`, `bootstrap/`, and `.claude/agents/` for `decide_merge_authority`
  returns **only `.claude/agents/overseer.md`** — thirteen prose references, zero executions. This is
  #1357's finding, re-confirmed independently here. #1641 ("merge-authority slice 1 — invocable
  read-only primitives") is the in-flight fix for the invocability half.

**So the answer to #1643's question is: neither.** It does not require a real reviewer pass, and it
does not trust the register either — the register is checked by a different function in a different
step that an LLM is asked in prose to call first. The composition itself is the narration.

**VF-5 — and the register check it composes with is a presence-and-schema check on a gitignored,
worker-authored file. The one gate that reads *committed* evidence is wired to nothing.**

`check_register_completeness()` (`merge_authority.py:888-952`) reads
`.claudetmp/signoffs/step{N}-register.md` — `.gitignore:2` is `.claudetmp/` — and for each required
role asserts only: an entry exists, `Status`/`Agent`/`Artifact`/`Iterations` are non-empty, and an
`ESCALATED` status carries a `Human_resolution`. **It never inspects what the review found.** A
worker that writes `Status: APPROVED / Iterations: 1` for every role satisfies it completely. This is
precisely the register-based self-report #1594/#1615 found structurally broken (unreachable
cross-clone), now confirmed to *also* be substantively empty even where it is readable.

Meanwhile `scripts/oversight/signoff_gate.py` — which reads **committed** `signoffs/<ns>/<role>.stamp`
files with commit-timestamp freshness, i.e. durable, cross-clone-visible evidence — **appears in no
GitHub workflow.** Its only non-test reference is `scripts/automation/lib/pr_readiness.py`, the
*worker-side* self-assessment gate (`worker.md` step 8.9). The one mechanism in the repo built on
durable evidence is used only by the party it is meant to check.

**VF-6 — CONFIRMED, #1643's core gap: the overseer never runs any review dimension.**
`overseer.md` frontmatter `dispatches:` lists exactly two agents — `oversight-evaluator` and
`risk-assessor`. None of `code-reviewer`, `security-reviewer`, `privacy-reviewer`,
`reliability-reviewer`, `ops-reviewer`, `ui-reviewer`, `a11y-reviewer`, `infra-reviewer` appears.
`overseer.md:131` says explicitly: *"Run the full review chain yourself — dispatch
`oversight-evaluator`."* The overseer's entire knowledge of the eight AI review dimensions is
mediated by artifacts the worker wrote.

**VF-7 — CHANGES THE SHAPE OF #1643's WORK: the *routing* half of the dimension-checker already
exists in code and is deterministic. Only the *invocation* and *verdict* halves are missing.**

`scripts/framework/run_post_change_sweep.sh` already does, in bash, exactly what REQ-B1 needs:
`categorize()` (`:63-115`) maps each changed path to domains (framework / application-code /
migrations / templates / tests / infrastructure / design-pack / spec), and `:159-195` prints the
required agent set per domain, in dependency order (`code-reviewer` first, then
`security-reviewer` + conditional `privacy-reviewer` / `ui-reviewer` / `a11y-reviewer` /
`infra-reviewer` in parallel). Its final line is:

> `echo "To run: invoke the post-change-sweep agent in Claude Code."`

**That line is the seam.** The deterministic "which dimensions are required for this diff" decision
#1643's rule 1 demands is already written and already executable; the script then hands the
*execution* of that plan to an agent's discretion — which is rule 3's failure mode exactly.
#1643 should be scoped as **finishing this script**, not as building a new one. (Its category regexes
are visibly Django/consumer-shaped — `accounts|booking|erasure|pii`, `Specs/*design.pack/` — which is
a PACK-vs-CORE layering question for `architect`, not a reason to rewrite it.)

**VF-8 — the seam in `worker.md` is clean; #1644 does *not* require restructuring it.**
`worker.md`'s autonomous per-task chain (`:363-385`) is a numbered list in which **the deterministic
script-call pattern is already established and already interleaved with the prose-dispatch pattern**:

| Step | Form today |
|---|---|
| 7b. Create branch | `bash bootstrap/create_branch.sh …` — **script** |
| **8. Build chain** | *"dispatch `risk-assessor`, then `code-reviewer`, then parallel reviewers per the step manifest"* — **prose** |
| 8.4 Second review | `bash scripts/run_review_chain.sh --step N --tier …` — **script** |
| 8.7 Inner-loop test gate | `bash scripts/framework/run_tests_inner_loop.sh` — **script**, "HARD GATE" |
| 8.9 Self-assessment gate | `python -m scripts.automation.lib.pr_readiness …` — **script**, "deterministic — blocks PR creation" |
| 9. Open PR | `bash bootstrap/submit_pr.sh --app worker` — **script** |

Step 8 is the one prose step in a list of script calls, and `worker.md:373-378` says so itself: the
pre-coder gate *"is planned for v0.6.0 via triage agents (#558) and does not yet exist… the pipeline
discipline classification rule above is the sole enforcement mechanism"*, with the root-cause note
*"v0.4.0 #556: workers repeatedly self-exempted on this basis."* **#1644 is the mechanical gate that
paragraph says is missing.** Replacing step 8's prose with a script call in the same numbered list is
additive within an established pattern — not a restructure of `worker.md`.

**VF-9 — CORRECTS A LIKELY READING OF #1644: `run_framework_validation.sh`'s "hard pass cap of 3" is
not an in-script loop. It is a persisted counter with one pass per invocation, and the *caller*
re-runs.**

#1644 cites this as the proven precedent for its bounded loop, so its actual shape matters.
`validate_self.sh:129-131` increments a counter file (`$OUT_DIR/self-review-pass-count`), runs
**exactly one** review pass, and exits: `0` converged (counter deleted), `1` NEW blocking findings —
*caller should fix and re-run*, `3` cap reached while still non-converged — **escalate, do not
retry**. `validate_scripts.sh:236-247` is identical in shape. `run_framework_validation.sh:90-101,
116-126, 142-154` is the consumer: it maps `3` → *"a HUMAN must decide (fix / accept / file). Not
auto-retried"* and `1` → *"triage them… and re-run until converged."*

Two consequences. (a) **The convergence contract is an exit-code contract (0/1/3), not a loop.** Any
new mechanism should adopt the same three-outcome vocabulary rather than invent a fourth. (b) **The
thing that actually re-runs today is a human or an agent following prose** — which is the same
narration gap. #1644 must decide whether its loop is in-script or counter-based; the *proven* half of
the precedent is the counter and the exit-code contract, not an automated loop (escalated as **Q4**).

**VF-10 — CONFIRMS #1644's premise and finds the raw material, with an inverted sign: there is no
stuck detection anywhere in this repo, and the one function that produces the right signal currently
uses it to do the opposite.**

Searched every capped/retry mechanism: `scripts/oversight/run_with_retry.sh` (shared timeout+retry
for validators/gates — **blind** identical retry, `max_retries` only, no progress comparison);
`breakers.py:is_poisoned` (cross-cycle *failure* count per cid, not per-round progress);
`bounce_count()` (`merge_authority.py:1074`, caps overseer→worker bounces at 2 — a cap, not a
progress test); `validate_self.sh`/`validate_scripts.sh` pass caps (VF-9 — counters, not progress
tests). **None detects non-progress.**

But `scripts/oversight/validation_logic.py:170` already computes exactly the signal #1643's refinement
comment asks for: `fingerprint(finding)` → a stable key over `(sorted files, finding-class)`. Compare
round N's fingerprint set to round N-1's and you have *"the same finding recurred"* and *"the finding
count didn't decrease"* directly. **The catch is that its current semantics are the inverse of what a
convergence loop needs.** `load_ledger()` (`:210`) treats a recurring fingerprint with a resolving
disposition as **noise to be silenced** so the gate can converge. In a coder↔code-reviewer loop a
recurring fingerprint means *the coder's fix did not work* — a stuck signal that must **escalate**,
not be silenced. Reusing `fingerprint()` is right; reusing `load_ledger()`'s dedup semantics
unchanged would actively **mask** the stuck condition #1644 exists to catch. The architect must split
the two explicitly (REQ-C4, and **Q5**).

**VF-11 — NESTING BUDGET, unaddressed by either issue and potentially disqualifying for #1644's full
form.** `bin/hos-cron:1764` launches the role as `claude --print --permission-mode bypassPermissions`
under `HOS_CRON_MAX_SECONDS` (default **1800s**, `bin/hos-cron:39`). Every nested `claude --print
--agent` runs *inside* that one wall-clock budget, and inside one subscription-quota cycle. #1644's
full shape is plan phase (pm-agent → architect → technical-design = 3 sessions) plus code phase
(coder ↔ code-reviewer, up to 3 rounds = up to 6 sessions) — **up to 9 nested model sessions inside a
30-minute cycle**, before any of the worker's own turns. Related: the #1446 usage-limit breaker
greps `$_HOS_DIR/last-claude-output/${ROLE}-${PROJECT}`, i.e. the **parent's** captured stdout — a
nested session that hits the subscription limit is invisible to it unless the wrapper surfaces it.
This is a feasibility constraint on scope, not a detail (escalated as **Q6**).

**VF-12 — the permission posture of a nested `coder` invocation is a security decision, not a flag
choice.** Per VF-1, a nested session discards `permissions.allow` and inherits no permission mode.
The parent cron role runs `bypassPermissions`, justified in `bin/hos-cron:1757-1763` on the grounds
that *"the net is the GitHub App's scoped permissions + the overseer's merge guardrails — NOT the CLI
permission gate."* That justification was made for **one** session per cycle, launched by the
launcher. Extending it to N script-launched nested sessions — including `coder`, which writes code —
widens the surface in a way nobody has ruled on. Note also `coder`'s CORE prohibition on writing
agent-definition files, and CLAUDE.md's standing rule that a shipped CORE rule must not carry a
self-assessed exemption: a nested `coder` under `bypassPermissions` has no *mechanical* barrier to
`.claude/agents/**` beyond that prose rule and the protected-surface CODEOWNERS gate at merge.
**Q3.**

---

## 1. Context — what the two epics jointly are

Both epics are the same sentence applied at two pipeline positions:

> A step in the pipeline is *real* only if a deterministic caller invoked it, captured its result in a
> parseable form, and acted on that result by fixed control flow. A step an agent decided to take, and
> whose result an agent decided what to make of, is not a step — it is a claim about a step.

- **#1643 (overseer / gating side)** — mostly **one-shot**: for a finished diff, a fixed set of
  dimensions must each produce a real verdict, and a missing or failing dimension bounces or
  escalates. VF-7 shows the routing half is already built.
- **#1644 (worker / build side)** — inherently **iterative**: design can be rejected, code and review
  can go rounds. Needs a bounded, stuck-aware convergence contract on top of the same invocation.
  VF-8 shows the seam is a single prose step in an otherwise scripted list.

They are not the same *shape*. They need the same *primitive*. §2 is the argument for that claim; it
is the central question the human posed and this document's main deliverable.

---

## 2. The shared-mechanism recommendation

### 2.1 Recommendation: ONE invocation primitive, ONE result schema; TWO distinct control-flow shapes layered on top.

**One `invoke_agent` primitive** — the single canonical way anything in this repo runs a named Claude
agent as a subprocess and gets back a machine-readable verdict. Recommended as a shipped, tested,
`--body-file`-style wrapper in the same tier as `bootstrap/get_app_token.sh`,
`bootstrap/post_comment.sh`, and `bootstrap/submit_pr.sh` — i.e. it earns a row in CLAUDE.md's
"Canonical entry points by task" table and nothing else is permitted to invoke `claude --agent`
directly.

**Justification — five independent lines, in descending strength:**

1. **The duplication is already measurable and already inconsistent.** VF-3: four `claude -p` sites,
   three different reliability postures, two of them (`run_panel.sh`, `validate_self.sh`) with no
   timeout at all, plus a duplicated `run_capped` that ignores the existing `run_with_retry.sh`. Six
   more consumers are queued (#1536, #1567/#1642, #1621, #1626, #1629, plus #1643's general form and
   #1644's). Without a wrapper the *expected* outcome is ten sites and five postures.
2. **The failure semantics are subtle, safety-critical, and have already been gotten wrong twice in
   this repo, both as filed bugs.** #669 (a hung reviewer's empty output parsed as zero findings →
   approve) and #1362 (a failed `claude` invocation parsed as a clean pass) are the *same bug* found
   in two scripts a year apart, each fixed locally. VF-1 shows the nested-agent envelope adds a
   *third* variant of it (`subtype:"success"` alongside `is_error:true`). Fail-closed logic this
   delicate must exist once, be tested once, and be impossible to forget.
3. **Every consumer needs the identical non-obvious preamble.** Auth that is environment-borne and
   not inherited (VF-1.1); a `cd` to the repo root because agent discovery is cwd-based at process
   start (`bin/hos-cron:1772-1781`, #1126 — *"without this `cd`… the worker can dispatch none of its
   26 shipped agents and silently falls back to built-ins"*, the exact #608 specialist-substitution
   violation); an explicit permission posture (VF-1.2); a timeout; prompt-over-stdin because argv
   hits `ARG_MAX` at scale (#1368, `validate_self.sh:230-235`). Five ways to get a *silently
   degraded* result, in every consumer, forever.
4. **It is this repo's own stated rule.** CLAUDE.md, *"Shell usage under the sandbox" → "What to do
   instead"* item 5: *"Never inline logic that already exists as a script"*, and item 4: *"the second
   time you need it, it belongs in `scripts/` or `bootstrap/` with a test."* We are at the eighth
   time, not the second. AGENTS.md's *"Use the Code, Don't Roll It Yourself"* governs directly.
5. **Oversight needs one observation point.** Token/quota accounting (VF-11, `token_tracker.py` is
   already vendor-parameterized), audit events, prompt-artifact capture for `prompt_audit_risk.py`,
   and usage-limit-breaker visibility all want exactly one place where "an agent was invoked" is
   recorded. Ten call sites means ten places to forget it.

**Counter-argument considered and rejected.** One could argue the gating and build sides are
different enough to justify two wrappers. They differ in *control flow* — one-shot verdict vs.
multi-round convergence — but not in any property of the invocation itself: same binary, same flag,
same auth problem, same cwd problem, same timeout problem, same envelope, same fail-closed rules.
Splitting on control flow would duplicate 100% of the hard part to avoid sharing 0% of the easy part.

### 2.2 The loop question: NOT a second shared primitive. A thin, separately-specified layer.

The brief asks whether the bounded/stuck-aware loop should also be shared. **Recommendation: no
shared loop primitive — but a shared *convergence-result vocabulary*.** Reasons:

- **#1643 is overwhelmingly one-shot.** Rules 1-3 describe a checklist over a finished diff, not
  iteration. Where #1643 does iterate, it iterates through the **existing** `record_pr_bounce()` /
  `bounce_count() < 2` mechanism (`merge_authority.py:1074`, `overseer.md` steps 4a/4c) — a
  *cross-cycle, cross-process* bounce with the worker in between. That is a fundamentally different
  thing from #1644's *in-cycle, in-process* round loop, and #1626 already warns against inventing "a
  third disposition path."
- **#1644's loop is genuinely its own mechanism**, and is the only place stuck detection is needed.
- **But both must speak the same result vocabulary**, or the six children will diverge again: the
  three-outcome exit-code contract VF-9 already proves (`0` converged / `1` not converged, actionable
  / `3` escalate — human decides, do not auto-retry), plus the `fingerprint()`-based progress signal
  of VF-10.

So: **one invocation primitive (REQ-A), one shared result/verdict schema and exit-code contract
(REQ-A7/A8), a one-shot checker shape that mostly finishes an existing script (REQ-B), and a
convergence-loop shape that is #1644's alone (REQ-C).**

---

## 3. Functional requirements

### 3.1 REQ-A — The agent-invocation primitive (shared by both epics and all six children)

**REQ-A1 — Single canonical entry point.** Exactly one shipped, tested wrapper invokes
`claude --print --agent <name>`. After it exists, no other script, workflow, or agent-prose
instruction may invoke `claude --agent` directly. It is added to CLAUDE.md's "Canonical entry points
by task" table, and the four pre-existing `claude -p` sites in VF-3 are migrated onto it or explicitly
exempted with a recorded reason. *(Rationale: VF-2, VF-3, §2.1.)*

**REQ-A2 — Named-agent invocation is the unit.** The caller names a **shipped agent** (a file under
`.claude/agents/`), not a model and not a prompt-only invocation. A request for an agent whose
definition file is absent fails closed with a distinguishable "agent unavailable" outcome — never a
fallback to a general-purpose agent or a bare model. *(Rationale: `worker.md:225-239` already
hard-stops on missing specialists; #1126/#608 — silent fallback to built-ins is a governance
violation, and cwd-based discovery makes it easy to trigger accidentally.)*

**REQ-A3 — Input is a file path, never inline text.** The caller writes the assembled prompt/context
to a file and passes the path; the wrapper delivers it over **stdin**, not argv. *(Rationale: #1368 —
argv hits `ARG_MAX` at release scale; CLAUDE.md's `--body-file`-only convention for every other
canonical wrapper; sandbox-allowlistability, which forbids `"$(…)"` construction at call sites.)*

**REQ-A4 — The wrapper owns the environment preconditions, not its callers.** At minimum: repo-root
cwd (agent discovery, #1126); authentication presence verified **before** invocation with a
distinguishable "not authenticated" outcome (VF-1.1); the permission posture per **Q3**; a wall-clock
timeout (REQ-A5). A caller must not be able to get a degraded-but-plausible result by forgetting a
step. *(Rationale: VF-1, VF-3.)*

**REQ-A5 — Bounded wall-clock time, always, with a caller-settable cap and a non-infinite default.**
No invocation may run unbounded. Timeout is a **distinguishable outcome**, not merged into "failed".
It must reuse the repo's existing timeout helper rather than adding a fourth private copy.
*(Rationale: VF-3 — two of four existing sites are unbounded today; `run_with_retry.sh` already
exists; #1575 duplicate-helper class.)*

**REQ-A6 — Fail closed, defined over the result envelope, not over the exit code alone.** An
invocation that errors, times out, is refused, is not authenticated, exhausts its turn budget, hits a
usage limit, or returns empty/unparseable output MUST produce a *blocking* result — never "reviewed,
found nothing." The wrapper inspects the structured envelope's own error signals (at minimum
`is_error`, `terminal_reason`, and any permission-denial/refusal counters) in addition to the process
exit code. *(Rationale: VF-1.3 — `subtype:"success"` co-occurs with `is_error:true`; #669 and #1362
are the same bug already found twice; VF-11 — the #1446 usage-limit breaker cannot see nested
sessions.)*

**REQ-A7 — Two failure classes are reported distinctly, and the caller must be able to act on them
differently.** (i) **Invocation failure** — the tooling did not produce a review (auth, timeout,
crash, quota, unparseable). (ii) **Analysis finding** — the agent ran and reported a problem. Both
are blocking by default, but (i) means *"the check did not happen"* and routes toward
human/operator escalation, while (ii) means *"the check happened and failed"* and routes toward a
worker fix. *(Rationale: #1643 rule 3 distinguishes "bounces to the worker (fixable)" from
"escalates to the human (not worker-fixable — e.g. a configuration gap)"; `validate_scripts.sh`
already implements a required-vs-optional-lane version of this distinction and is the model.)*

**REQ-A8 — One result schema, structured, with a verdict field a caller reads without parsing prose.**
Every agent invoked through the primitive returns the same top-level shape: an unambiguous verdict, a
severity-ranked finding list, and enough per-finding identity to fingerprint it (at minimum: the
files implicated and a finding class). The schema is a **superset-compatible extension of the one
three validators already emit and `validation_logic.py` already parses** (`reviewer`, `lens`,
`findings[{severity, category, files, description, fix}]`, `verdict`, `summary`) — not a new one.
A caller MUST NOT determine pass/fail by reading the agent's narrative summary. *(Rationale: #1643's
mechanism comment — "the SCRIPT parses result.json's verdict — never a narrated summary";
`validation_logic.py:95-152` already extracts and ranks exactly this; VF-10 — `fingerprint()` needs
`files` + class to work.)*

**REQ-A9 — Schema conformance is enforced, and non-conformance is an invocation failure.** An agent
that returns unparseable output, or output missing the verdict field, produces a REQ-A7(i) failure —
never a default-pass and never a best-effort prose interpretation. *(Rationale:
`validation_logic.py`'s `--strict-empty` already encodes this for the existing validators, added as
the #669 fail-open fix; the new primitive must not regress it.)*

**REQ-A10 — Every invocation is observable and attributable.** At minimum: which agent, against what
input, when, outcome class, and resource usage — recorded through the repo's **existing** mechanisms
(`token_tracker.py`, which is already vendor-parameterized, and the per-entry audit log), not a new
one. *(Rationale: VF-11 — nested sessions are invisible to the parent's usage-limit breaker; §2.1
line 5; CLAUDE.md search-first.)*

**REQ-A11 — Nothing about REQ-A weakens an existing human gate.** The primitive changes *who invokes*
and *who judges*, never *who approves*. Protected-surface, security-surface, CRITICAL-tier, and
release gates, and every human-approval requirement in `merge_authority.py`, are untouched. An
`APPROVED` verdict from any agent invoked this way is evidence for a *bot-side* decision only and
never substitutes for a human approval. *(Rationale: ratchet; `overseer.md`'s "What you may NEVER
do"; #1643 rule 4 — "AI's role is analysis, not gatekeeping.")*

### 3.2 REQ-B — The one-shot dimension-checker shape (#1643)

**REQ-B1 — Code, not an agent, decides which dimensions are required for a given change.** The
required-dimension set is a deterministic function of the diff and the PR's metadata.
**This must extend `run_post_change_sweep.sh`'s existing `categorize()` routing rather than
re-deriving it** — VF-7 shows the mapping already exists and is already deterministic. Its
consumer-stack-shaped patterns are a CORE/PACK layering question for `architect`, not a reason for a
second implementation. *(Rationale: #1643 rule 1; VF-7; #1575.)*

**REQ-B2 — Deterministic dimensions run their existing gate; only judgment dimensions invoke an
agent.** lint, type-check, secret-scan, bash-check, portability and the rest keep running as
`scripts/oversight/gates/*.sh` / CI jobs. Only dimensions that genuinely require judgment
(code-review, security, privacy, reliability, ops, ui, a11y, infra, scope-conformance,
semantic-duplication) go through REQ-A. *(Rationale: #1643's mechanism comment sketch; don't spend a
model turn on a task `ruff` already answers.)*

**REQ-B3 — The result is captured and evaluated by the caller; a missing dimension is a failure, not
a silence.** For each required dimension, the checker records a real REQ-A8 result. Absence of a
result for a required dimension is treated identically to a blocking finding — never as "not
applicable" or "presumably fine". "Not applicable" is a verdict an agent must *state*, not an
inference a caller may draw from missing data. *(Rationale: #1643 rules 2 and 3; VF-5 — the current
register mechanism cannot distinguish "reviewed and clean" from "never ran".)*

**REQ-B4 — Verification means the analysis was performed in the verifying party's own context.** For
any dimension whose result gates merge, the result that counts is the one produced by an invocation
the *gating* side made — not an artifact the worker committed asserting a review occurred. *(Rationale:
#1643 rule 2, verbatim; #1536's ruling; VF-4/VF-5 — the current chain is
worker-writes-register → overseer-reads-register, with no independent execution anywhere.)*

**REQ-B5 — The disposition of a failed or missing dimension is fixed control flow with no
discretionary branch.** A failing dimension routes to the **existing** worker-bounce path
(`record_pr_bounce()` with the existing `bounce_count() < 2` budget and the SPEC-378 R1.2 structured
rationale fields) when worker-fixable, and to the **existing** `HUMAN_REQUIRED` escalation otherwise.
No new outcome class, no new disposition path, no "this one's probably fine" branch anywhere.
*(Rationale: #1643 rule 3; #1626's explicit instruction not to "invent a third disposition path";
#1580's bounce-before-escalate ordering, which this must preserve exactly.)*

**REQ-B6 — The merge decision must be unable to succeed without the dimension results.** Whatever
composes the dimension results with the merge-authority decision must make "no results" and "failing
results" unrepresentable as a merge-eligible state. The current composition — an LLM asked in prose to
call `check_register_completeness()` before `decide_merge_authority()`, where the latter accepts a
caller-supplied `oversight_verdict` string and has no reviewer input at all (**VF-4**) — does not
satisfy this. **How to close it (compose inside `decide_merge_authority()`, require a verified
results artifact as an input, or gate at a different layer) is the architect's call and interacts
directly with #1641's in-flight invocability work.** *(Rationale: VF-4; #1357; #1643 rules 1 and 3.)*

**REQ-B7 — The set of dimensions with no deterministic checker is enumerated, and the gaps are
filed.** #1643's own remaining non-child work is naming which dimensions lack any deterministic
checker today. On the evidence here, that is **all eight AI review dimensions** (VF-6) — none is
independently executed or verified anywhere on the gating side. That enumeration, with a filed issue
per genuine gap, is a deliverable of this epic.

### 3.3 REQ-C — The bounded, stuck-aware convergence-loop shape (#1644)

**REQ-C1 — Each step in the plan phase and the code phase is a REQ-A invocation, and the step's
completion is judged by the caller.** pm-agent, architect, technical-design, coder, code-reviewer are
invoked through the primitive; whether the step is complete is read from the REQ-A8 verdict, not from
a parent agent's summary of what happened. *(Rationale: #1644's first bullet.)*

**REQ-C2 — Every iterative loop has a hard round cap with a non-configurable-to-infinity ceiling.**
Recommended default **3**, matching `SELF_REVIEW_MAX_PASSES` / `SCRIPTS_REVIEW_MAX_PASSES`. Floor: the
cap must be finite and must have a documented maximum; an environment variable must not be able to
disable it. *(Rationale: #1644's second bullet; VF-9; the standing ratchet rule that a PROJECT layer
may tighten a cap but never raise it to effectively unbounded.)*

**REQ-C3 — The loop actively detects non-progress and bails immediately on detecting it, rather than
exhausting the remaining cap.** "Stuck" is defined at minimum as any of: (i) a finding with the same
fingerprint recurs across rounds; (ii) the blocking-finding count does not decrease round over round;
(iii) the reviewer's verdict is unchanged despite a materially changed diff. On detection, the loop
exits to escalation **on that round**. *(Rationale: #1643's refinement comment, verbatim; #1604's
"detect stuck, don't blind-retry" generalized.)*

**REQ-C4 — Stuck detection reuses `validation_logic.py:fingerprint()`, and must NOT reuse
`load_ledger()`'s dedup semantics unchanged.** VF-10: the fingerprint is the right signal, but the
ledger's current rule — a recurring fingerprint with a resolving disposition is *silenced as noise so
the gate can converge* — is the exact inverse of what a convergence loop needs, where a recurring
fingerprint means the fix failed and must **escalate**. The architect must make this split explicit
and must not let a convergence loop inherit silencing behavior. *(This is the single highest-risk
reuse in the whole design: done carelessly, the mechanism #1644 adds to catch stuck loops would
instead hide them.)*

**REQ-C5 — Non-convergence and stuck both exit to the *existing* deterministic escalation path.**
"A human decides fix / accept / file" — the same outcome `run_framework_validation.sh` already
produces on exit 3. Not a new outcome class. The escalation must carry the round-by-round record
(what each round found, what changed, what recurred) so the human can see *why* it did not converge
without re-deriving it. *(Rationale: #1644's fourth bullet; #1604's acceptance criterion that a
split/escalation must surface what it knows rather than hide it; `worker.md:277-295`'s red-baseline
policy is the in-repo model for "record the evidence before acting".)*

**REQ-C6 — The three-outcome exit-code vocabulary is shared with REQ-A/REQ-B.** converged /
not-converged-and-actionable / escalate-do-not-auto-retry. *(Rationale: VF-9; §2.2.)*

**REQ-C7 — Total resource cost per cycle is bounded, and the bound is enforced, not assumed.**
The mechanism must not be able to consume an entire cron cycle's wall-clock or subscription budget in
nested invocations. It must fail in a *recoverable, resumable* way when it does hit a bound — a cycle
that burns 30 minutes on nested sessions and produces nothing is a worse outcome than today's prose
dispatch. *(Rationale: VF-11 — up to 9 nested sessions inside a 1800s default cap; #1597's 3.5-hour
suspension is the precedent for what an unbounded-cost failure does to the project.)*

**REQ-C8 — Which parts of `worker.md`'s existing internal dispatch this replaces is bounded by one
rule: any dispatch whose outcome *gates* something must go through REQ-A.** Both issues explicitly
leave the replace-vs-keep tradeoff to the architect, and this document does not pre-empt it — but it
does bind the floor. A dispatch gates something if its result determines whether a step is declared
complete, whether coder may start, or whether a PR may open. Fast-feedback, non-gating, inner-loop
dispatch may remain Agent-tool-based at the architect's discretion. *(Rationale: #1643's mechanism
comment and #1644's scope paragraph both reserve this; VF-8 identifies step 8 as the gating one and
steps 8.4/8.7/8.9 as already-scripted.)*

### 3.4 REQ-D — Re-scoping the six already-filed children

**The binding rule (REQ-D0): no child may implement its own agent invocation, its own result parsing,
or its own fail-closed logic. Each child becomes "define this dimension's input, prompt, and
disposition; call the shared primitive."** Each child's issue body is amended to say so, and each
gains a dependency edge on the primitive's issue. *(Rationale: §2.1; this is the entire point of
considering the epics jointly.)*

| Issue | What it is | Recommended re-scope |
|---|---|---|
| **#1536** — overseer runs framework-validation itself, retires the stamp | Already an *overseer-executes-it* instance. Its entry point (`run_framework_validation.sh`) is the one script already containing a hand-rolled version of the primitive (VF-3, VF-9). | **Keep as-is in outcome; sequence it AFTER the primitive and make it the primitive's first migration target.** Its ruling (stop trusting attestation, overseer executes) is unchanged and needs no human re-ruling. Its four validate_*.sh invocation sites migrate onto REQ-A, which is also the cheapest way to fix VF-3's two unbounded-timeout sites. **Do not let it ship a private invocation path.** |
| **#1642** — `lint_check.sh`/`type_check.sh` fail on `main` | Pure deterministic-gate repair. No AI invocation involved. | **No re-scope. Unblocked by, and independent of, this work — ship it now.** It is REQ-B2's "deterministic dimensions keep their existing gate" lane. |
| **#1567 Gap 5** — promote `oversight-gate-lint`/`-type-check` to GitHub-required so `check_required_content_checks()` can bounce on them | Deterministic-dimension *enforcement wiring*. The #1641 near-miss. | **No re-scope, and do not let it wait on this design.** It is REQ-B2 + REQ-B5 already satisfied for the deterministic lane, and it is the highest-value/lowest-cost item in the entire set. Sequence: after #1642 turns the gates green. |
| **#1621** — `cut_release.sh` verifies human + overseer approval itself | Deterministic verification of *approval state*, not an AI judgment. | **Re-scope narrowly: confirm with `architect` that it needs no agent invocation at all.** On the evidence it is a `merge_authority.py`-style deterministic check and belongs with #1641's invocable-primitives work, not with REQ-A. **Flag it explicitly as NOT a REQ-A consumer** so nobody builds one into it. |
| **#1626** — overseer-executed PR-vs-issue/spec scope-conformance | A genuine REQ-A consumer. Already specifies overseer-side execution and explicitly says "reuse existing mechanisms, don't invent a third disposition path." | **Re-scope to: define the dimension (inputs: PR diff + issue body + linked spec docs), the "reasonable adjacent work vs. scope creep" boundary, and its disposition mapping. Invocation, schema, fail-closed, timeout all come from REQ-A.** Its own input choice — durably committed artifacts only — should be **promoted to a general REQ-B principle** (it is the correct generalization of the #1594/#1615 lesson). |
| **#1629** — overseer-executed semantic code-duplication | A genuine REQ-A consumer, same shape as #1626. | **Same re-scope as #1626.** Additionally: its "reasonable idiomatic repetition vs. should-be-shared" boundary is a **pm-agent/human product question**, not an architect question — and the shared primitive itself will be its first real test case (it should not flag REQ-A1's consolidation of four `claude -p` sites as duplication). |

**Additional child this pass identifies as missing (recommend filing):** per **REQ-B7**, all eight AI
review dimensions currently lack any independently-executed checker on the gating side (VF-6). #1626
and #1629 cover two *new* dimensions; nothing covers the eight existing ones. That is #1643's largest
unfiled gap.

---

## 4. Explicit non-goals

1. **Not changing what any reviewer agent looks for.** #1643 rule 4: the agents keep doing exactly
   what they do today. No review lens is widened, narrowed, or re-written by this work.
2. **Not weakening any human gate** (REQ-A11). No change to protected-surface, security-surface,
   CRITICAL-tier, release (NG3b), or `require-human-approval` behavior.
3. **Not replacing cross-vendor review.** `agy`/`codex` via `run_second_review.sh` / `run_panel.sh`
   provide vendor decorrelation that Claude-invoking-Claude structurally cannot
   (`validate_self.sh:16-20` says so explicitly). REQ-A is additional, never a substitute.
4. **Not re-litigating #1641's merge-authority invocability work.** REQ-B6 depends on it and must be
   sequenced behind it; it is not re-specified here.
5. **Not building a general agent-orchestration framework.** Scope is the named steps in #1643 and
   #1644 and the six children. Any further consumer is a separate issue.
6. **Not deciding bash vs. Python, file layout, flag names, or JSON field names.** `architect` and
   `technical-design`.
7. **Not moving AI review into CI.** #1216's ruling that subscription-CLI review is CI-incompatible
   stands; this runs in the overseer's/worker's own session, which is exactly why #1536's ruling works.

---

## 5. Product and boundary decisions escalated to the human

Architect may proceed on §3 but must not bind **Q1, Q2, Q3, Q7** before these are ruled.

**Q1 — Does a required dimension's *invocation failure* (REQ-A7(i)) block the merge, or degrade to a
warning when the tooling is unavailable?** A hard block is correct by the ratchet and is what
`validate_scripts.sh` does for its required lane — but combined with VF-1 (nested auth is not
inherited) it means a misconfigured environment stops all merges. The alternative (degrade to
warning) is the exact fail-open #669/#1362 were filed for. **PM recommendation: hard block, with the
failure routed to human/operator escalation rather than a worker bounce (the worker cannot fix an
auth problem).** Human must confirm, because the blast radius is "every PR stops."

**Q2 — Does REQ-B4 ("verified in the gating party's own context") mean the overseer re-runs
dimensions the worker already ran, accepting the duplicate model cost?** Independence says yes;
budget (VF-11) and latency say it hurts. Middle options exist (re-run a risk-tiered subset; re-run
only dimensions whose files the diff touches; re-run only on tier ≥ MEDIUM). **PM recommendation:
re-run, subset by risk tier, with the subset rule deterministic and not agent-chosen.** This is a
governance-vs-cost tradeoff and is the human's.

**Q3 — What permission posture does a nested agent invocation run under, and does `coder` get the
same one as a read-only reviewer?** VF-1.2/VF-12: nested sessions discard `permissions.allow` and
inherit no mode. The parent's `bypassPermissions` was justified for one launcher-started session per
cycle; extending it to N script-started sessions including a code-writing one is a security decision
nobody has made. **PM recommendation: reviewers (read-only) and `coder` (writes) get different,
explicitly specified postures; `coder`'s is the narrower.** Human ruling required — this is the
single largest new-attack-surface item in the design.

**Q4 — Is #1644's loop an in-script loop, or the proven counter-plus-exit-code contract (VF-9) that
some outer caller re-runs?** An in-script loop is more deterministic (nothing can decline to re-run)
but concentrates all cost inside one invocation (VF-11/REQ-C7). The counter form is proven in this
repo but today the re-runner is a human or an agent following prose — i.e. the narration gap again.
**PM recommendation: in-script loop for the code phase (where a re-runner is the failure mode), with
the same 0/1/3 exit contract at its boundary.** Architect may have grounds to differ; flagging as a
human-visible decision because it determines whether #1644 actually closes the gap it names.

**Q5 — When a convergence loop and the existing dedup ledger disagree, which wins?** VF-10: a
fingerprint recorded `fixed` in the ledger but recurring in round N+1 is, to the ledger, silenced
noise, and to the loop, proof the fix failed. **PM recommendation: within a convergence loop,
recurrence always wins and always escalates; the ledger's silencing applies only to the one-shot
validators it was built for.** Needs an explicit ruling because getting it backwards silently
disables REQ-C3.

**Q6 — What is the per-cycle budget for nested invocations, and what happens when it is exhausted
mid-build?** VF-11: up to 9 nested sessions inside a 1800s default cap, invisible to the #1446
usage-limit breaker. **PM recommendation: an explicit nested-invocation budget (count and wall-clock)
checked before each invocation, with exhaustion producing a resumable checkpoint + escalation rather
than a silently truncated build.** The numbers are the human's.

**Q7 — Do both epics ship together, or does #1643's gating side ship first?** They share the
primitive, so the primitive must ship first regardless. After that they are independent. **PM
recommendation: primitive → #1643 → #1644**, because #1643 carries the `priority:critical` label and
the #1641 near-miss, and because #1644's cost profile (Q6) is the riskier unknown. Human to confirm
the ordering, since it determines what lands in v0.7.0 versus what slips.

**Q8 — Is `#1629`'s "reasonable idiomatic repetition vs. should-be-shared" boundary a product
decision the human sets, or a technical one the architect sets?** #1629 asks for "a documented
boundary" and notes #1633 must reuse it. **PM recommendation: human sets the principle, architect
operationalizes it** — over-abstraction has a real cost and the line is a judgment about this
project's values, not about code. Low urgency; blocks #1629 only.

---

## 6. Recommended work-item decomposition (for the orchestrating session to file *after* architect and technical-design)

Sequenced, individually completable, each independently reviewable — following this session's
established practice (#1604, #1567's Gap 5 split, #1629/#1633 split) of small, linked, sequenced
items over one bundle. **Do not file these yet** — architect and technical-design may merge, split,
or reorder them.

**Track 0 — ships now, independent of this design (do not let it wait):**
- **W0a** — #1642 as filed: make `lint_check.sh`/`type_check.sh` green on `main`.
- **W0b** — #1567 Gap 5 / the required-check promotion, after W0a. *This is the direct fix for the
  #1641 near-miss and should not be sequenced behind an epic.*

**Track 1 — the shared primitive (everything else depends on this):**
- **W1** — The invocation primitive itself: REQ-A1 through REQ-A6 and REQ-A9. One wrapper, one
  timeout, fail-closed over the envelope, agent-unavailable handling, prompt-over-stdin, tests
  covering each failure class. *Blocked on: Q1, Q3.*
- **W2** — The shared result schema + verdict contract: REQ-A7, REQ-A8, and the 0/1/3 exit vocabulary
  (REQ-C6), specified as a superset-compatible extension of `validation_logic.py`'s existing schema.
  *Can be designed in parallel with W1; must land with or before it.*
- **W3** — Observability: REQ-A10, wiring nested invocations into `token_tracker.py` and the audit
  log, plus surfacing a nested usage-limit stop to the parent's #1446 breaker. *Depends on W1.*
- **W4** — Migrate the four existing `claude -p` sites (VF-3) onto the primitive and add the
  CLAUDE.md canonical-entry-point row. *Depends on W1. Low risk, high value — it fixes two unbounded
  timeouts as a side effect, and it is the primitive's first real proof.*

**Track 2 — #1643, the gating side:**
- **W5** — REQ-B1/B2: promote `run_post_change_sweep.sh`'s routing into the required-dimension
  decision, and split deterministic-gate dimensions from judgment dimensions. Includes the CORE/PACK
  layering question for its consumer-shaped regexes. *Depends on W1/W2.*
- **W6** — REQ-B3/B4/B5: run the judgment dimensions through the primitive on the gating side, capture
  results, map disposition onto the existing `record_pr_bounce()` / `HUMAN_REQUIRED` paths. *Depends
  on W5. Blocked on Q2.*
- **W7** — REQ-B6: make the merge decision unable to succeed without the dimension results. *Depends
  on W6 **and on #1641**; likely the highest-risk single item and a candidate for its own ADR.*
- **W8** — REQ-B7: enumerate the dimensions with no deterministic checker and file the gaps
  (audit + issue-filing; no code).
- **W9** — #1536 re-scoped: overseer runs framework-validation itself via the primitive; retire the
  stamp. *Depends on W1/W4.*
- **W10** — #1626 re-scoped (scope-conformance dimension definition only). *Depends on W6.*
- **W11** — #1629 re-scoped (semantic-duplication dimension definition only). *Depends on W6.
  Blocked on Q8.*
- **W12** — #1621 confirmed as a non-REQ-A deterministic check and annotated as such, so no agent
  invocation is built into it. *Small; can go any time after architect confirms.*

**Track 3 — #1644, the build side:**
- **W13** — REQ-C2/C6: the bounded-round contract and its exit-code vocabulary. *Depends on W2.
  Blocked on Q4.*
- **W14** — REQ-C3/C4: stuck detection over `fingerprint()`, with the ledger-semantics split made
  explicit. *Depends on W13. Blocked on Q5. **Highest-subtlety item in the set** — recommend its own
  technical-design section and adversarial review.*
- **W15** — REQ-C5: the round-by-round escalation record onto the existing escalation path. *Depends
  on W14.*
- **W16** — REQ-C7 + Q6: the nested-invocation budget and resumable-checkpoint behavior. *Depends on
  W3. Blocked on Q6. Recommend this lands **before** W17, not after — it is the guard on W17's cost.*
- **W17** — REQ-C1/C8 applied to the **code phase** (coder ↔ code-reviewer) only. *Depends on W13-W16.*
- **W18** — REQ-C1/C8 applied to the **plan phase** (pm-agent → architect → technical-design).
  *Depends on W17 — deliberately last: it is the least-proven and most expensive part, and W17 will
  teach us whether the cost model holds.*

**Recommended scope boundary if v0.7.0 runs short:** W0a, W0b, W1-W4, W5-W7, W9 is a coherent,
independently valuable release — it closes the #1641 class of near-miss and the #1357 narration gap
without taking on #1644's cost risk. W10-W11 and Track 3 can follow in v0.7.1.

---

## Human Review Required

**RISK: HIGH** — This document specifies a **structural** change to both the gating side and the build
side of the pipeline. It changes who invokes review agents, who judges their results, what may block a
merge, and (per Q3) the permission posture under which `coder` executes. It also re-scopes six
already-filed issues.

**CONFIDENCE: HIGH on the findings, MEDIUM on the recommendation.**
- *High* on §0: every VF was re-derived from the repository, with file-and-line citations, and VF-1 is
  backed by a live probe of the nested-invocation path rather than an inference. VF-4 in particular
  answers #1643's own open question from the source, not from the issue's framing.
- *Medium* on §2/§3: the single-primitive recommendation rests on five converging lines of evidence
  and I believe it is right, but two things could change it — a ruling on Q3 that gives `coder` a
  sufficiently different invocation posture that sharing becomes awkward, and the Q6 budget answer, on
  which #1644's feasibility in its full form genuinely depends. Neither would change REQ-A's contents,
  only #1644's scope.
- *Lower* on the numeric defaults (round cap 3, nested budget): these are extrapolated from
  `SELF_REVIEW_MAX_PASSES=3` and `HOS_CRON_MAX_SECONDS=1800`, not measured. They are flagged as
  recommendations with floors, and the binding values are the human's.

**Change classification: STRUCTURAL.** New gating decision points, a new class of nested process
execution, a changed permission surface, and a change to what "a step completed" means. Escalated to
the human before `architect` binds it, per the spec-update path. **Nothing in this document has been
applied to any agent definition, script, or configuration file** — it describes what `worker.md` and
`overseer.md` would need to change (VF-7, VF-8, REQ-C8) without editing either; those are protected
surfaces and the orchestrating session will authorize and land them after architect and
technical-design.

**Not done here, deliberately:** no test plan sign-off (there is nothing built to test yet); no
register entry (this is a requirements document, not a reviewed artifact).
