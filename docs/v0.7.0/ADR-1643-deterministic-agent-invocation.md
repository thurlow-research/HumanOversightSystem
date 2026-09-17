# ADR-1643 — One invocation primitive, one registry schema, two runners: a dimension is real only when a script named it, a script ran it, and a script read its envelope

**Status:** ACCEPTED FOR DESIGN — binds `technical-design`. **Four items are held for the human** (§6):
ESC-1 (Q2's unconditional rerun does not fit one cron cycle — cost + latency), ESC-2 (the sweep becomes a
new top-level cron execution stage — deployment topology + operational burden), ESC-3 (does input-identity
reuse fall inside Q2's "unconditionally"? — ESC-1's arithmetic depends on the answer), ESC-4 (turning on
twelve review dimensions that have never executed is a step change in what blocks a merge — observation
window first, or straight to enforcing?). Everything else below is **BINDING**.

> **AMENDED 2026-09-15 — read §9 (Amendment 1) before implementing anything.** `technical-design`
> returned five escalations against this ADR (TECHNICAL-DESIGN-1643 §12: ESC-A, ESC-B, ESC-C, ESC-D,
> ESC-J), two of them blocking slice W1. All five are ruled in **§9**. **Where §9 and §2 differ, §9
> governs; where §9 and the technical design differ, §9 governs.** Every affected decision row in §2
> carries an inline pointer, and §9.7 lists exactly which technical-design clauses are superseded. A
> coder implementing AD-4 who has not read §9 will build the wrong classifier.

> **AMENDED 2026-09-16 — read §10 (Amendment 2) before touching `bootstrap/invoke_agent.sh`.** It rules
> on `technical-design`'s TD-D22/TD-D23 (the #1720 interpreter defect): the interpreter ladder is
> **inside** AD-1 (new clause **AD-1a**, the launch/logic boundary, §10.1); the fallback is **not** taken
> (§10.2); `INVOKE_AGENT_PYTHON` is **accepted under four binding conditions** (§10.3); AD-1's L3 bullet
> and the wrapper's header are **amended, with the replacement text written out** (§10.4). **Where §10
> and §2 differ, §10 governs; where §10 and the technical design differ, §10 governs.** §10.6 orphans two
> W1 sign-offs on PR #1720.

**Date:** 2026-09-14 (original), amended 2026-09-15 (Amendment 1, §9)
**Author:** architect
**Inputs:** `docs/v0.7.0/REQUIREMENTS-1643-1644-deterministic-agent-invocation.md` (pm-agent, merged in
PR #1651) in full, including VF-1…VF-12; the human's **Q1–Q8 rulings** (#1643 comment 2026-09-14T20:09:14Z);
the human's **ESC-5 ruling** (#1643 comment 2026-09-14T19:37:22Z — from a prior architect pass whose ADR
was never committed; the artifact is lost, the ruling stands and is carried forward here in my own
numbering); the human's **registry-driven-orchestration** direction (#1643 comment 2026-09-14T18:46:07Z);
the three 2026-09-14 mechanism/refinement comments on #1643; my own re-verification against
`4f973c43` = `origin/main` (§0).
**Consumers:** `technical-design` (next), then the decomposed issues in §5.
**Source issues:** #1643 (this), #1644 (sibling — **out of scope**, §4 states the seam only), #1641/#1357
(the landed two-tier CLI pattern this copies), #1536, #1567 Gap 5, #1621, #1626, #1629 (children),
#1594/#1615 (the register-self-report defect class), #1580/#1626 (disposition paths this must not
duplicate), #1216 (AI review stays out of CI), #1349/#1354 (the stage-per-cycle pattern and the pending
label rename), #1446 (usage-limit breaker), #1542 (sandbox rollout).
**Explicitly does NOT re-litigate:** Q1–Q8 (ruled); ESC-5's entry-vs-binding model (ruled); #1641's
merge-authority invocability work (depended on, not re-specified); what any reviewer agent looks for
(non-goal 1); any human gate (non-goal 2); moving AI review into CI (non-goal 7, #1216 stands).
**Explicitly OUT OF SCOPE:** #1644 and REQ-C / Track 3 (W13–W18). The Q4+Q6 ruling changed #1644's
build-side mechanism; it is going back to `pm-agent`. §4 states what seam I leave and what property of
REQ-A makes it work. Nothing here binds #1644.

---

## 0. Verification findings — re-derived against `origin/main` = `4f973c43`

pm-agent's §0 is strong and I inherit VF-1…VF-12 rather than re-deriving them. I re-checked every
file:line I build on, because pm-agent's citations were made from a different worktree. Everything I
cite below is this checkout of `4f973c43`.

### Confirming pm-agent, where I depend on it

- **VF-2 CONFIRMED, re-run.** Searched `scripts/` (recursive), `bootstrap/`, `bin/`, and
  `scripts/automation/lib/*.py` for any agent-invocation helper: `invoke_agent`, `run_agent`,
  `dispatch_agent` → **the only hit in the entire repository is the string `invoke_agent` inside
  pm-agent's own requirements document.** Four `claude -p` sites exist and no more:
  `scripts/run_panel.sh:146-147`, `scripts/framework/validate_self.sh:236`,
  `scripts/framework/validate_scripts.sh:182`, `bootstrap/setup_clis.sh:148`. **None uses `--agent`.**
- **VF-3 CONFIRMED.** `scripts/oversight/run_with_retry.sh:56-63` exports `with_timeout`;
  `validate_agents.sh:151-160` and `validate_scripts.sh:96-99` each define a private
  `_TIMEOUT_BIN`+`run_capped` pair. Three copies, one shared helper ignored. See **AF-3** — the shared
  helper is also *insufficient* for this job, which changes REQ-A5's answer.
- **VF-4 CONFIRMED and now sharper after #1641.** `decide_merge_authority` (`merge_authority.py:497-529`)
  still has **no reviewer, sign-off, register, or dimension parameter**. `oversight_verdict: str` is a
  caller-supplied string checked exactly once, at `:632`. `check_register_completeness` (`:947`) is still
  a separate function it never calls. See **AF-4** for what #1641 did and did not change.
- **VF-5 CONFIRMED and worse than stated.** See **AF-5**.
- **VF-6 CONFIRMED.** `.claude/agents/overseer.md:14-16` — `dispatches:` lists exactly
  `oversight-evaluator` and `risk-assessor`. None of the eight review lenses appears.
- **VF-7 PARTIALLY CONFIRMED, and the "already built" half is weaker than it reads.** See **AF-6**.
- **VF-10 CONFIRMED.** `validation_logic.py:170` `fingerprint()`; `load_ledger():210` silences a recurring
  fingerprint with a resolving disposition. But see **AF-7** — the schema pm-agent asks me to extend is
  not quite the schema `validation_logic.py` parses.

### My own findings — these change the design

**AF-1 (HIGH — the two-tier CLI pattern this needs is already landed and reviewed; do not invent a
third shape).** #1641 merged as `a73090b3` and shipped exactly the tiering the primitive needs:
`scripts/automation/merge_authority_cli.py` (795 lines — **L2**: argparse, owns the record schema, owns
the exit codes, `sys.path` bootstrap making it cwd-immune) plus `bootstrap/merge_authority.sh` (140
lines — **L3**: fixed argv over a closed subcommand enum, mints the token, passes stdout and exit code
through byte-for-byte, and its header states *"This script must never grow a JSON literal, a printf/echo
to stdout, or any re-derivation of a field"*). Its exit vocabulary is `0` answered / `1` operational
failure / `2` usage error / `3` reserved. **The bash-vs-Python question posed to me is therefore already
answered by a landed precedent, not open.** AD-1 copies it.

**AF-2 (HIGH — the CLI has no `--max-turns`, so a runaway session is bounded by wall-clock alone).**
`claude --help` on the installed CLI lists `--agent`, `--output-format {text,json,stream-json}`,
`--permission-mode {acceptEdits,auto,bypassPermissions,manual,dontAsk,plan}`, `--allowed-tools`,
`--disallowed-tools`, `--settings <file-or-json>`, `--setting-sources`, `--system-prompt-file`,
`--agents <json>`, `--model`, `--session-id`. It does **not** list `--max-turns`. REQ-A6 names "exhausts
its turn budget" as a failure class; there is no flag to set a budget. `num_turns` is present in the
result envelope, so the condition is *observable after the fact* but not *bounded in advance*. Two
consequences: (a) wall-clock is the only real bound, which raises the stakes on AD-5; (b) the envelope's
`num_turns` becomes a post-hoc signal to record, not a guard.

**AF-3 (HIGH — `with_timeout` cannot do the job REQ-A5 assigns it, and reusing it here would be a
regression dressed as consolidation).** `with_timeout` is literally
`"$_TIMEOUT_BIN" "$timeout_sec" "$@"` (`run_with_retry.sh:56-63`) — no `--kill-after`, no
`--foreground`, no process-group kill. `timeout` signals only the direct child. A `claude --print`
session spawns tool subprocesses; killing the CLI without reaping its group leaves orphans holding the
worktree and, under `bin/hos-cron`'s own lock semantics, is exactly the class of residue #1616 chased.
Separately, `run_with_retry.sh` sources `lib/audit_log.sh` at `:52`, so `with_timeout` cannot be taken
without also taking an audit dependency. REQ-A5's *intent* (one implementation, no fourth copy) is
correct; its *prescription* (reuse `with_timeout`) is not achievable for this caller. AD-5 resolves it
in the direction that reduces the copy count anyway.

**AF-4 (HIGH — #1641 made the merge-authority primitives invocable but left the *composition* narrated,
and it exposed `check_register_completeness` as a peer subcommand, which makes the narration easier to
mistake for a fix).** `merge_authority_cli.py` ships eight subcommands: `gate`, `register`,
`bounce-count`, `human-approval`, `hold-directive`, `protected-surface`, `security-surface`,
`codeowners`. There is **no `decide` subcommand** — `decide_merge_authority` has no CLI anywhere
(`grep` for it across `scripts/`, `bootstrap/`, `bin/` returns only its own definition and a docstring
mention in `merge_config.py`). So the state after #1641 is: *the inputs* are invocable, *the decision*
is not, and the order in which they compose is still prose in `overseer.md`. Running
`merge_authority.sh register` and then `merge_authority.sh gate` in the right order remains something an
agent is asked to do. This is the shape REQ-B6 must close, and it is one step subtler than before #1641
because two real commands now exist to point at.

**AF-5 (HIGH — the register path cannot be REQ-B6's closure in this repo, because the manifest the
register gate reads does not exist here).** `check_register_completeness` resolves required roles from
`contract/step-manifest.yaml` (`merge_authority.py:962`) and returns `bounce_required=False` outright
when that list is empty (`:965-968` — *"Nothing is required for this step, so there is nothing to be
incomplete about"*). **HOS itself has no `contract/step-manifest.yaml`** — only
`contract/step-manifest.template.yaml`. So on this repository the register gate is structurally
incapable of bouncing anything, for every step. #1641's `_cmd_register` deserves credit for surfacing
this (`gate_evaluable: false` plus a `not_verified[]` entry naming the missing manifest,
`merge_authority_cli.py:318-352`) — but the *library* still returns "not required", so any consumer
reading `bounce_required` alone reads a pass. Combined with VF-5's finding that the register file itself
is gitignored and worker-authored, the conclusion is firm: **REQ-B6 must close on the dimension results,
not on the register.** AD-15.

**AF-6 (MEDIUM — VF-7's "the routing half already exists" is true about the *knowledge* and false about
the *interface*, and three of its routing rules are wrong or discretionary today).** Read in full at
`scripts/framework/run_post_change_sweep.sh`:
1. **Its output is prose on stdout**, not a machine-readable structure — `Domain routing:` /
   `Agents to invoke:` / `Track 2 — Code review (sequential then parallel):`. No caller can consume it.
   The routing *mapping* (8 regexes, `:63-114`) is the reusable asset; the script is not an API.
2. **It routes to `framework-validator`** (`:172`), which per CLAUDE.md and
   `scripts/framework/consumer_agents.txt` is **not shipped to consumers** — it belongs to the planned
   `hos-dev-pack`. Every consumer install's sweep names an agent that is not installed.
3. **Its privacy branch is discretionary by construction.** `:181-184` is
   `[[ -n "$HAS_CODE" ]] && grep -qE 'accounts|booking|erasure|pii' … && echo "privacy-reviewer (PII-relevant files detected)" || echo "privacy-reviewer (check if PII-relevant)"`.
   The `||` fires both when the grep misses *and* when `HAS_CODE` is empty, so the common outcome is a
   printed instruction telling a human or an agent to *decide*. That is rule 3's failure mode living
   inside the file VF-7 nominates as the deterministic half.
4. Its consumer/Django shape is not limited to the PII word list: `^Specs/.*design.pack/`,
   `^Specs/.*\.md$`, `^docker-compose\.yml$`, `^Caddyfile$`, `^scripts/backup\.sh$` are **one project's
   repo layout**, not a stack's idiom — so they are PROJECT-layer facts sitting in CORE. AD-11 splits
   them three ways, and the `Specs/`/`Caddyfile` group goes to PROJECT, not to a pack.
5. Its last line (`:200-201`) hands execution to an agent, as VF-7 says.

**AF-7 (MEDIUM — the schema I am told to extend is narrower than pm-agent describes, and the
difference is load-bearing).** REQ-A8 says to extend "the one three validators already emit and
`validation_logic.py` already parses (`reviewer`, `lens`, `findings[{severity, category, files,
description, fix}]`, `verdict`, `summary`)". Read at source: `validation_logic.py` reads **only**
`verdict`, `findings[]`, `attacks[]`, and per-finding `severity`, `category`-or-`type`, and
`files`-or-`file` (`compute_verdict:240-305`, `fingerprint:170`, `_files_of:148`, `_class_of_finding:158`).
It never reads `reviewer`, `lens`, `description`, `fix`, or `summary`. Those fields are *emitted* by
`validate_agents.sh`/`run_second_review.sh` and read by a **different** module — `panel_logic.py:197-258,
377-388` consumes `reviewer` and `lens`. So "the schema" is really two overlapping readers, and
superset-compatibility has to hold for both. It also means `extract_json_objects` is a *prose-tolerant
brace scanner* (`:105-143` — it deliberately tolerates commentary around a ```json fence because agy and
codex both prepend it), which is the right posture for a foreign vendor's stdout and the **wrong**
posture for our own primitive, which can and must be strict. AD-6 keeps the wire format compatible with
both readers while making the primitive's own parse strict.

**AF-8 (MEDIUM — the existing "self-determine not applicable, SKIP" pattern the registry is invited to
generalize is a fail-open, and generalizing it unchanged would build REQ-B3's failure mode into the
registry).** The human's registry comment cites `django_check`/`astro_check`/`expensive_gates_stub` as
already self-determining *"not applicable, SKIP"* rather than failing. They do — `django_check.sh:30-33`
prints `SKIP: manage.py not found` and `exit 0`. But `run_gates.sh:113-134` records
`{"gate":…,"exit_code":0,"suspended":false,…}` for that gate, **byte-identical to the record a gate that
ran and passed produces.** Downstream, "not applicable" and "reviewed and clean" are indistinguishable —
precisely the distinction REQ-B3 exists to force and VF-5 found missing. The pattern worth generalizing
is the *directory-discovery runner* (`run_gates.sh:80-142` finds `gates/*.sh`, runs each, emits one
record per item, aggregates one exit code — a registry runner in all but name). The pattern that must
**not** be generalized is SKIP-as-exit-0. AD-6 and AD-9 separate them.

**AF-9 (MEDIUM — packs have no mechanism to contribute anything except agent prose, so the
entry/binding registry is genuinely new structure, not a re-layering of something extant).**
`packs/<name>/` contains only `<agent>.md` region bodies plus `pack.toml` (`name`, `description`,
`version`, `requires`); `scripts/framework/install.sh` handles `PACK=` purely as an agent-region merge
key. There is no pack→gate, pack→validator, or pack→config contribution path today, which is exactly
why `django_check.sh` and `astro_check.sh` both live in CORE `scripts/oversight/gates/` and self-skip.
ESC-5's model is therefore the *first* data-layered pack mechanism in HOS. That raises its risk and is
why AD-9 binds a fail-closed loader with an explicit ownership check rather than a permissive merge.

**AF-10 (MEDIUM — the existing per-agent provenance hook cannot see a primitive invocation, so
observability does not come for free).** `.claude/settings.json` wires
`scripts/oversight/record_agent_model.py` as a `SubagentStop` hook; it emits
`{"agent_id":…,"agent_type":"code-reviewer","event":"subagent-model-resolved","model":"claude-sonnet-5"}`
(sample record verified in `audit/log/2026/09/`). A `claude --print --agent X` process launched by a
script is **not** a subagent of any session, so `SubagentStop` never fires and this provenance is lost
exactly where the invocation becomes deterministic. The replacement is in the envelope (`modelUsage`,
`num_turns`, `usage`), which only the primitive can see. AD-8. Note also that these records carry no
`timestamp` field, unlike the `cycle-*` records — a pre-existing inconsistency, not mine to fix.

**AF-11 (LOW, but it decides Q3's mechanism — the scoped-permission surface Q3 asks for already exists
as a shipped template).** `contract/sandbox-policy.template.json` is a settings document with
`permissions.defaultMode: "auto"`, `permissions.disableBypassPermissionsMode: "disable"`,
`additionalDirectories`, and a long literal `allow` list of `Bash(cmd *)` rules. `claude --settings
<file>` takes exactly this shape. So Q3's *"new invocation surfaces land as dedicated scripts with
scoped, explicit permissions"* needs no new mechanism: it needs named posture files in the same format,
in the same protected directory. AD-7.

### Measurements taken this session (for §3)

From the committed audit trail, `audit/log/2026/09/` (223 records, all roles):
- Worker `cycle-start` → next `cycle-start`: **n=85, min 547s, median 601s, max 4811s.** The cron
  interval is ~10 minutes.
- `cycle-claude-timeout`: **1 occurrence in 86 `cycle-start` records** (~1.2%) at the 1800s cap
  (`bin/hos-cron:39`, `:215`, `:1788`). Today's cycles fit their budget comfortably.
- **Zero overseer records in the September trail.** Every `cycle-*` record carries `role=worker`. I
  cannot tell from the audit trail whether the overseer has been running at all this month. Recorded as
  a gap, not a claim; it means I have **no** empirical overseer cycle-duration baseline.

### Verification gaps I could not close

- **How long one `claude --print --agent <reviewer>` takes over a real diff.** No such invocation has
  ever run in this repository (VF-2). Every wall-clock number in §3 is derived from the repo's own
  self-calibration (`AI_REVIEW_TIMEOUT=300`, `validate_agents.sh:141`, `validate_scripts.sh:54`), not
  from observation. **This is the single largest unknown in the ADR** and is why AD-13's first build
  slice is a measurement, not an enforcement.
- **Whether `--settings <file>` survives the untrusted-workspace discard VF-1.2 found for
  `.claude/settings.json`'s `permissions.allow`,** and whether `--agent <name>` enforces the agent
  file's frontmatter `tools:` list in a nested, untrusted workspace. Both are load-bearing for AD-7 and
  neither is documented. `technical-design` MUST probe both before binding AD-7's posture files; if
  `--settings` is also discarded, AD-7 needs a different mechanism and Q3's interim rule is harder to
  satisfy than it reads.
- **Live branch protection / required-check list.** Not queried (same wrapper gap ADR-1357 recorded).
- **Whether `subagent_stats.refused` is present on the envelope in this CLI version.** VF-1's probe
  output did not include it. AD-4's classifier is written so that its absence is harmless.

---

## 1. Context — what is actually being decided

pm-agent framed this as "build one wrapper." After §0 it is better framed as **deciding where the
system's knowledge of its own review obligations lives.**

Today that knowledge is in four places, none of them consultable: the eight lenses exist as agent files
nobody on the gating side invokes (VF-6); which lens applies to which file exists as prose printed by a
script whose last line delegates (AF-6); whether a lens ran exists as a worker-written, gitignored
register (VF-5); and whether that matters to a merge exists as a caller-supplied string
(VF-4, AF-4). Each hop is individually defensible and the chain end-to-end asserts nothing.

The question the human put to me — one registry and one runner for both roles, or not — resolves once
you ask what each role's sequence actually *is*. The overseer's is a **fan-out over a changeset**: which
checks apply to this diff, run them all, aggregate. That is the shape `run_gates.sh` and
`run_validators.sh` already implement twice (AF-8). The worker's, **under the Q4+Q6 ruling**, is a
**single-step advance over a durable work queue**: exactly one stage executes per cron cycle, its state
lives in GitHub labels and issue bodies, and order is everything. Those are not the same runner and
pretending otherwise would produce a runner that is a fan-out with a degenerate width of one, or a state
machine with eleven simultaneous current states.

What they *do* share is everything below the runner: how you invoke an agent, how you read what came
back, how you decide it failed, how ownership layers, and how a step declares itself inapplicable. That
is the unification that holds, and AD-12 states its boundary precisely rather than gesturing at it.

The governing constraint on the whole design is the one the human set in Q1: **an invocation failure
hard-blocks the merge.** Every fail-open in §0 — SKIP-as-exit-0 (AF-8), empty-manifest-as-satisfied
(AF-5), prose-as-routing (AF-6) — becomes a merge stopper the moment this lands. That is correct and it
is also why §3's arithmetic and ESC-4's rollout question are not optional paperwork.

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1 — The primitive is L2 Python + L3 bash, copying #1641's landed tiering verbatim. (BINDING — REQ-A1, REQ-A3; AF-1, Q3.)

- **L2 — `scripts/automation/agent_invoke_cli.py`.** Owns: argument validation, environment
  preconditions, subprocess launch, timeout and reaping, envelope classification, result-schema
  emission, exit codes, observability. Python because (a) #314's standing policy, quoted verbatim in
  `validation_logic.py`'s own docstring — *"prefer Python for logic, shell for launch"*; (b) v0.7.4's
  stated migration direction; (c) AD-4's classifier is a branchy allowlist that must be unit-tested
  against synthetic envelopes, which heredoc-free bash cannot do; (d) AF-1's landed precedent.
- **L3 — `bootstrap/invoke_agent.sh`.** Fixed argv over a closed flag set, no JSON literal, no
  re-derivation of any field, stdout and exit code passed through byte-for-byte. Mints **no** token
  (this surface performs no GitHub I/O). Earns the CLAUDE.md canonical-entry-point row REQ-A1 requires.
  **— AMENDED by §10.1/§10.4 (Amendment 2): L3 also resolves the interpreter that runs L2 (launch, not
  logic — clause AD-1a), and may contain no other logic. Implement §10.4's replacement bullet and header
  text, not this one. Note also §10.0: this bullet's "copy #1641's tiering verbatim" copied a bare
  `exec python3` whose safety was a property of `merge_authority_cli.py`'s stdlib-only import list — that
  precondition is now stated, and it is the root cause of #1720.**
- **Exit vocabulary is #1641's, unchanged:** `0` the invocation was attempted and a result document was
  produced (whatever it says) / `1` operational failure of the CLI itself / `2` usage error. **The
  pass/fail of the review is never an exit code** — it is the `verdict` field, read by the caller. This
  is `validation_logic.py`'s binding 3 (*"the shell owns the cap… the CLI emits process exit codes ONLY
  for operational failure"*) applied unchanged, so the whole repo keeps one convention.
- The prompt/context is written to a file by the caller and passed as `--input-file`; L2 delivers it on
  **stdin** (#1368 `ARG_MAX`, and CLAUDE.md's `--body-file`-only convention). Never argv, never `$(…)`.

*Why this could still go wrong:* L3 exists so an agent session can call the primitive with a
statically-allowlistable command. Under Q3/Q4 the primary caller is a script, so L3 risks being a wrapper
nobody uses. It is cheap (~140 lines by #1641's measure) and it is what makes a human's or an agent's
one-off single-dimension invocation possible without a second path. Keep it; do not grow it.

### AD-2 — The primitive is a top-level, stateless, one-shot process with no notion of round, loop, cycle, or parent session. (BINDING — REQ-A; Q4+Q6. **This is the property §4's seam rests on.**)

All state in is a file path; all state out is a file path plus an exit code. The primitive does not read
a counter, does not know whether it is round 1 or round 3, does not know whether a parent session exists,
and holds nothing between invocations. It is correct to invoke it from a script, from `bin/hos-cron`
directly, from a `claude` session, or from a human's terminal, and it behaves identically in all four.

This is bound as a *decision*, not observed as a property: it would be natural to give the primitive a
`--round` flag or a resume token, and doing so would make it unusable as a cron-driven one-shot step,
which is precisely the shape Q4+Q6 ruled #1644 into.

### AD-3 — A shipped, named agent is the only unit of invocation. Bare-model and inline-agent invocation are forbidden through this surface. (BINDING — REQ-A2. **Consequence ruled in §9.5:** where a migration target has no shipped agent describing its lens, the agent file is authored first — the prohibition is not relaxed and no existing agent is substituted for a different lens.)

- The caller names an agent; L2 resolves `.claude/agents/<name>.md` from the repo root and **verifies it
  exists and is non-empty before launching anything.** Absent ⟹ `outcome: invocation_failed`,
  `outcome_detail: agent_unavailable`, `verdict: error`. Never a fallback to a general-purpose agent,
  never a bare model (#1126/#608 — cwd-based agent discovery makes silent fallback to built-ins easy to
  trigger and it is a governance violation, not a degradation).
- **`--agents <json>` (inline agent definitions) is forbidden** and L2 must refuse a request carrying
  it. It would let a caller define an unreviewed reviewer at runtime, defeating the entire point of
  naming a shipped, region-layered, CODEOWNERS-protected agent file.
- L2 `cd`s to the repo root before launch (`bin/hos-cron:1772-1781`, #1126) and passes `--model` only
  when the caller explicitly overrides; otherwise the agent file's own `model:` frontmatter governs
  (`code-reviewer.md:4` is `sonnet`, `overseer.md:8` is `opus` — that tiering is deliberate and is also
  §3's cost lever).

### AD-4 — Fail-closed is an allowlist over the envelope, not a denylist. `subtype` is never read. (BINDING — REQ-A6, REQ-A7, REQ-A9; Q1; VF-1.3.)

> **THREE ROWS OF THE TABLE BELOW ARE SUPERSEDED BY §9.1 (Amendment 1, 2026-09-15).** The
> `terminal_reason` row, the `subagent_stats.refused` row, and the *"any envelope field the classifier
> does not recognise"* clause in the sentence immediately below were all written against an envelope
> nobody had probed. `technical-design` probed it (CLI 2.1.270) and returned ESC-A and ESC-B; I
> re-verified against the shipped CLI bundle (2.1.271) in §9.0. **Implement §9.1's table, not this one.**
> The original rows are kept, marked, so the change is visible rather than silently rewritten.

`outcome: "completed"` is produced **only** when every one of the following holds. Any miss, and any
envelope field the classifier does not recognise, produces `outcome: "invocation_failed"`.
*(— the unrecognised-**field** half of that sentence is **SUPERSEDED by §9.2**: unknown top-level fields
are recorded, not blocking; unknown **values and shapes in decision fields** remain blocking.)*

| Condition for `completed` | Failure ⟹ `outcome_detail` |
|---|---|
| process rc == 0 | `124` → `timeout`; anything else → `crash` |
| stdout is a single valid JSON object | `unparseable` |
| `is_error` absent or falsy | mapped from `terminal_reason`, else `crash` |
| ~~`terminal_reason` absent or in a **closed allowlist** of known-good values~~ — **SUPERSEDED by §9.2**: `terminal_reason` must be **present** and equal to a value in the closed good-value allowlist; absent is now blocking | that value verbatim (e.g. `api_error`, `usage_limit`, `refusal`, `max_turns`); absent ⟹ `terminal_reason_missing` |
| `permission_denials` absent or empty | `permission_denied` |
| ~~`subagent_stats.refused` absent or `0`~~ — **SUPERSEDED by §9.1**: absent, **or** the integer `0`, **or** a flat mapping every one of whose values is the integer `0` | `refused`; a non-integer value (including `null` and `true`/`false`) ⟹ `envelope_shape_violation` |
| the result payload parses **strictly** as a conforming AD-6 document | `schema_violation` |

Binding notes:
- **`subtype` is not an input.** VF-1.3's `subtype:"success"` alongside `is_error:true` is harmless here
  because the field is never consulted. Do not add it "for completeness."
- The `terminal_reason` check is an **allowlist of good values**, not a denylist of bad ones. A future
  CLI version that introduces a new terminal reason fails closed by default. This is the one design move
  that makes #669 and #1362 unrepeatable rather than re-fixed. **§9.0 confirms this empirically**: the
  shipped CLI bundle already contains four terminal reasons this ADR never named
  (`structured_output_retry_exhausted`, `turn_setup_failed`, `tool_deferred_unavailable`,
  `aborted_tools`), every one of which is a failure and every one of which this allowlist blocks with no
  code change. **§9.2 extends the rule to absence**: the good-value allowlist now also requires the field
  to be *there*.
- **`outcome: invocation_failed` always forces `verdict: "error"` in the emitted document** (AD-6). That
  single rule makes every existing `validation_logic.compute_verdict` consumer fail closed on a broken
  invocation for free, via the #670 error-block path it already implements (`:266-272`: an `error`
  verdict counts as one NEW blocking finding and is never dedup-silenced). Compatibility earning its
  keep, not decoration.
- **The two failure classes route differently, per Q1 (REQ-A7).** `invocation_failed` means *the check
  did not happen* → **hard block on the merge, escalate to human/operator via the existing
  `HUMAN_REQUIRED` path**; it is explicitly **not** a worker bounce, because a worker cannot fix an auth
  gap, a quota stop, or a missing agent file. `completed` + `verdict: request_changes` means *the check
  happened and failed* → the existing `record_pr_bounce()` path with the existing `bounce_count() < 2`
  budget (REQ-B5; #1580's bounce-before-escalate ordering preserved exactly; #1626's "no third
  disposition path" honoured — there are two, and both already exist).
- `--output-format json` is mandatory and L2 sets it; a caller may not override it.

### AD-5 — The primitive owns its own timeout, in Python, with process-group reaping. The two private `run_capped` copies are deleted. (BINDING — REQ-A5; AF-3, AF-2.)

REQ-A5 says reuse `with_timeout` rather than add a fourth copy. AF-3 shows `with_timeout` cannot reap a
process group and cannot be imported into Python anyway. The resolution honours REQ-A5's intent and
**reduces** the copy count:

1. L2 launches via `subprocess.Popen(..., start_new_session=True)`, enforces the cap itself, and on
   expiry sends `SIGTERM` to the **process group**, then `SIGKILL` after a fixed grace period. Timeout is
   a **distinguishable outcome** (`outcome_detail: timeout`), never folded into "failed".
2. The default cap is `300s` — not invented, taken from the repo's own `AI_REVIEW_TIMEOUT` calibration
   (`validate_agents.sh:141`, `validate_scripts.sh:54`). Caller-settable per dimension via the registry
   (AD-9). **Zero/unbounded is not an accepted value**; the floor is enforced in L2, not in the registry.
3. When `validate_agents.sh` and `validate_scripts.sh` migrate (AD-16), their private `_TIMEOUT_BIN` +
   `run_capped` pairs are **deleted** and their remaining `agy`/`codex` calls source
   `run_with_retry.sh`'s `with_timeout`. Net: three bash copies → one bash helper + one Python
   implementation that has a capability the bash one structurally lacks.
   **— PARTLY SUPERSEDED by §9.4 (ESC-D).** `validate_agents.sh` has no `claude` call site, so it never
   "migrates" and this clause had no migration to attach to. **W4 deletes `validate_scripts.sh`'s copy
   only**; `validate_agents.sh`'s deletion moves to a follow-up issue. The "net" sentence above therefore
   describes the end state *after that follow-up*, not the end state of v0.7.0's W4. See §9.4 for what W4
   actually delivers and what remains outstanding.
4. Given AF-2 (no `--max-turns`), wall-clock is the *only* bound on a runaway session. `technical-design`
   must not treat the cap as a formality.

### AD-6 — One result document: a strict superset of what `validation_logic.py` and `panel_logic.py` each already read, with outcome, applicability, and input identity as first-class separate fields. (BINDING — REQ-A8, REQ-A9, REQ-B3; AF-7, AF-8, VF-10.)

L2 emits exactly one JSON object per invocation. Field names are `technical-design`'s to finalise; the
**shape and its rules** are bound here.

- **Legacy-compatible core, semantics unchanged:** `verdict` ∈ `{approve, request_changes, error}` —
  the existing three-value domain, *not* extended; `findings[]` with per-finding `severity` (the
  canonical 7-rank ordering, `validation_logic.py:52`), `category`, `files[]`, `description`, `fix`;
  plus `reviewer`, `lens`, `summary` for `panel_logic.py`'s readers (AF-7). A legacy consumer reading
  this document gets a correct, conservative answer with no code change.
- **New, additive, and where the real information lives:**
  - `outcome` ∈ `{completed, invocation_failed}` and `outcome_detail` — AD-4's classification. **Rule:
    `invocation_failed` ⟹ `verdict: "error"`, always.** This is the compatibility bridge and it is
    non-negotiable.
  - `applicability` ∈ `{applicable, not_applicable}` with a mandatory machine-readable reason.
    **Rule: applicability is decided by the registry's file predicate (AD-9), never by the agent.** If
    the predicate matched files, the dimension runs; the agent has no authority to declare itself
    inapplicable. This closes the self-exemption hole `worker.md:373-378` records as having been
    exploited repeatedly (*"v0.4.0 #556: workers repeatedly self-exempted on this basis"*) and it is the
    correct form of REQ-B3's *"'Not applicable' is a verdict an agent must state, not an inference a
    caller may draw."* Here it is stated — by code, with a reason, at zero model cost.
    **Rule: `not_applicable` records are written and stored like any other.** Absence of a record is
    never `not_applicable`; it is a missing dimension, which is blocking (REQ-B3). This is AF-8's
    SKIP-as-exit-0 fail-open closed by construction.
  - `dimension` (registry entry id), `binding` (which binding produced it), `agent` (shipped agent name).
  - `input`: `head_sha`, `base_sha`, `predicate_matched_files[]`, and **`input_digest`** — a content hash
    over (the matched files' bytes, the prompt template version, the agent file's bytes, the registry
    entry's and binding's resolved bytes). Computing it forces AD-3's agent-existence check as a side
    effect, and it is AD-13's reuse key.
  - `invocation`: timestamps, duration, `model`, `num_turns`, `usage`, the **verbatim CLI envelope**,
    and the process exit code. AF-10's lost provenance, recovered.
  - `schema` + `schema_version`.
- **Parsing is strict on our side.** `validation_logic.extract_json_objects` is deliberately
  prose-tolerant because agy and codex prepend commentary (AF-7). Our own primitive must not inherit
  that: the agent's payload is extracted from the envelope's result field and parsed with a strict
  schema check. Non-conformance is `schema_violation` → `invocation_failed` → `verdict: error`
  (REQ-A9; do not regress `--strict-empty`'s #669 fix).
- **`fingerprint()` is reused; `load_ledger()` is not.** Per-finding `files` + `category` are present
  precisely so `validation_logic.fingerprint()` (`:170`) applies unchanged. Per Q5 and REQ-C4,
  **`load_ledger()`'s silencing semantics MUST NOT be applied to any result produced through this
  primitive.** Its dedup rule exists for the one-shot cross-vendor validators it was written for; a
  recurring fingerprint in a convergence context means the fix failed. This ADR imports the fingerprint
  function and nothing else from that module, and `technical-design` must make the split textually
  obvious so a future reader cannot reuse the wrong half by import convenience.

### AD-7 — Permission posture is a named settings profile under `contract/`, reusing the shipped sandbox-policy shape. `bypassPermissions` is never passed by this surface. (BINDING — Q3, REQ-A4; AF-11, VF-1.2, VF-12.)

- Postures are files in the format of `contract/sandbox-policy.template.json`, with
  `permissions.disableBypassPermissionsMode: "disable"` set in every one of them. A registry binding
  names its posture (AD-9); L2 passes it as `--settings <path>` together with an explicit
  `--permission-mode` from `{manual, dontAsk}` and an explicit `--allowed-tools`/`--disallowed-tools`
  pair. **L2 must refuse `--permission-mode bypassPermissions` outright** — not default away from it,
  refuse it — so the stopgap Q3 permits for legacy surfaces cannot leak into this one.
- Two postures suffice for everything in scope: **`review-read-only`** (filesystem read + local
  read-only shell, no network, no write tools, no `gh`) for the eight lenses and semantic-duplication;
  **`review-read-only+gh-read`** (adds the `query_issues.sh` read path) for scope-conformance (#1626),
  which must read the issue body and linked spec. `coder` gets **no** posture here: nothing in #1643's
  scope invokes a code-writing agent, and inventing its posture in advance of #1644's re-derivation
  would be exactly the premature binding Q7 warns against.
- The agent file's frontmatter `tools:` list is the second, independent layer (`code-reviewer.md:5-9` is
  already `Read, Grep, Glob, Bash` with no `Write`/`Edit`). Defence in depth, not a substitute.
- **`technical-design` MUST probe, before binding this,** whether `--settings <file>` survives the
  untrusted-workspace discard VF-1.2 observed for `.claude/settings.json`, and whether `--agent`
  enforces frontmatter `tools:` in that state. If either fails, AD-7 needs a different mechanism and
  that is a finding for the human, not something to work around locally.

### AD-8 — Observability goes through `token_tracker.py` and one per-entry audit record per invocation. No decision reads either. (BINDING — REQ-A10; AF-10; ADR-1604 AD-4 carried forward.)

- L2 calls `token_tracker.py record --vendor claude --stage dimension:<entry-id> --step <pr-or-step>`
  with `--actual-prompt-tokens`/`--actual-output-tokens` from the envelope's `usage` when present,
  falling back to the existing char estimate. `claude` is already an accepted `--vendor` value
  (`token_tracker.py:249`). **No new mechanism** (REQ-A10, CLAUDE.md search-first).
- L2 writes one per-entry audit record per invocation carrying agent, entry, binding, outcome,
  `outcome_detail`, model, duration, and `input_digest`. This restores AF-10's lost `SubagentStop`
  provenance for invocations the hook cannot see.
- **No decision in this design may read an audit event.** ADR-1604's AD-4 is carried forward verbatim,
  on the same grounds (AF-1/AF-2 there: a counter whose write is an instruction reads zero forever, and
  a deterministic write has already been observed lost). If an audit write is silently lost, this
  mechanism degrades to *less observable*, never to *not gating*.
- A nested session that hits the subscription limit is invisible to #1446's breaker, which greps the
  **parent's** captured stdout (VF-11). L2 surfaces `terminal_reason: usage_limit` as an
  `invocation_failed` outcome, which under Q1 stops the merge — the correct conservative behaviour.
  Wiring it into #1446's breaker proper is a separate item (§5, W3), not a silent assumption here.

### AD-9 — ONE registry: entries are CORE-owned and indestructible; bindings are layered and suppressible. ESC-5's ruling is incorporated. (BINDING — REQ-B1; ESC-5; AF-8, AF-9.)

**Re-derivation of the rules ESC-5 refers to, in this ADR's numbering.** HOS's standing layering ratchet
— stated in the boundary block of every shipped agent file — is that PROJECT may extend CORE and PACK
but *"may only ever make these STRICTER … never looser."* Call that the **narrow-only rule**. The trap it
exists to close is this: if a project could delete a required check outright, a compliant configuration
could require nothing, and the resulting clean run would be indistinguishable from a run in which
everything was checked and found sound. That is AF-8's SKIP-as-exit-0 fail-open promoted to a
configuration feature, and it is the same defect VF-5 found in the register. Call it the
**required-to-do-nothing trap**. The convention that closes it is that **CORE owns both the existence of
a check and its baseline** — every entry ships with at least one CORE binding.

**The human's ESC-5 ruling (2026-09-14T19:37:22Z) is a deliberate, narrow loosening of the narrow-only
rule, scoped to bindings only, and is incorporated here as binding design:**

- An **entry** is a review dimension (`lint`, `security`, `code-review`, `scope-conformance`, …). It has
  an id, a `kind` ∈ `{deterministic, judgment}`, and a CORE-owned baseline. **Only CORE declares
  entries.** A PACK or PROJECT file containing an `entries:` key is a **load error**, not a merge.
- A **binding** is `(entry, tool, applicability predicate, posture, timeout, owner)`. `tool` is either a
  gate/validator script (`kind: deterministic`) or a shipped agent (`kind: judgment`). CORE, PACK, and
  PROJECT may all contribute bindings. **Every binding whose predicate matches the diff fires.** A
  project with both the `django` and `astro` packs gets both bindings on a shared entry like `lint`,
  each firing on its own file predicate; a project with only `astro` gets that one pack binding.
- A PROJECT may **suppress a binding** — never an entry. Suppression requires the binding's id and a
  non-empty `reason`. Suppressing a `core:` binding is a **load error**. The entry keeps running and
  keeps blocking through its remaining bindings, so the required-to-do-nothing trap stays closed.
- **File layout — `contract/dimensions/`:** `core.yaml` (CORE, installer-owned, overwritten on upgrade),
  `pack-<name>.yaml` (PACK, injected by `--pack`, installer-owned), `project.yaml` (PROJECT,
  consumer-owned, **never** overwritten). Loader:
  `scripts/automation/lib/dimension_registry.py`. Merge order core → pack-\* → project, mirroring the
  agent-file region order, but as **data**, not text.
- `contract/**` is already the first-class protected surface (`scripts/framework/protected_surfaces.txt`
  line 2 → CODEOWNERS). So ESC-5's *"that suppression is a protected-surface edit under `contract/**`
  with a recorded reason"* is enforced by an existing human gate, with **no new mechanism**. The
  `reason` field is the recorded reason.
- **The loader fails closed, always.** A malformed file, an unknown owner, an entry with no binding
  definition, a binding naming an absent agent or script, a suppression of a `core:` binding, a
  suppression with no reason, or an `entries:` key outside `core.yaml` ⟹ the loader exits non-zero and
  the sweep does not run. Compare AF-5: a permissive loader would reproduce
  `check_register_completeness`'s "nothing required, therefore nothing incomplete" exactly.
- The loader emits the **resolved** registry as JSON, so resolution is one artifact, diffable in CI and
  attachable to a PR. `technical-design` should add a check that the resolved registry is stable and
  that every entry resolves at least one binding.

*Why this could still go wrong:* AF-9 — packs have never contributed data before, only prose. The
install-time merge, upgrade behaviour, and `--squash` interaction are unproven for data files.
`technical-design` must verify the three-way merge story for `contract/dimensions/` against
`hos_install.sh`'s actual region-merge implementation, not by analogy to it.

### AD-10 — Deterministic entries keep their existing gate; only judgment entries invoke an agent. (BINDING — REQ-B2; Q2.)

`lint`, `type-check`, `secret-scan`, `security-scan`, `bash-check`, `portability`, `template-refs`,
`collection-integrity` and the rest keep running as `scripts/oversight/gates/*.sh` and CI jobs, bound to
their entry with `kind: deterministic`. Per **Q2**, CI/CD-covered deterministic dimensions are **trusted
as already run once, correctly** — the overseer does not rerun them. Only `kind: judgment` entries go
through the primitive, and per Q2 the overseer reruns **every one of them, unconditionally**, in its own
context. REQ-B4's "subset by risk tier" recommendation is **overruled and must not be designed for.**

The existing cross-vendor second review is itself an entry: `cross-vendor-review`, `kind: deterministic`,
bound to `scripts/run_second_review.sh`. That is how Q5's *"route convergence confirmation through the
existing cross-vendor mechanism, never the same-vendor loop's self-report"* composes into this model
without a special case.

### AD-11 — `run_post_change_sweep.sh` is **absorbed**: its mapping becomes registry predicates, split three ways; the script survives only as `--explain` over the resolved registry. (BINDING — REQ-B1; AF-6.)

Not replaced (its human-facing value is real), not generated from (AF-6.1-3: it is prose output with two
wrong routes and one discretionary branch — it is not a source of truth). Its 8 regexes (`:63-114`) and
its dependency ordering (`:170-196`) migrate into `contract/dimensions/` as binding predicates, and the
script is rewritten to print a human-readable rendering of the **resolved registry's** plan for a diff.
One invocation site, one source of truth (D41).

**The CORE/PACK/PROJECT split of its patterns — my call, since VF-7 left it to me:**

| Today (all in CORE) | Layer | Why |
|---|---|---|
| `^\.claude/agents/`, `^scripts/framework/` (+ add `^bin/`, `^bootstrap/`, `^contract/`, `AGENTS.md`, `CLAUDE.md`) | **CORE** | These are HOS's own governance surfaces; they are identical in every install. |
| `^tests/`, `conftest\.py$` | **CORE** (generic) / **PACK** (language-specific globs) | "A test changed" is universal; `/test_.*\.py$` is a Python idiom and belongs to a pack. |
| `\.py$` application-code, `/migrations/.*\.py$`, `/templates/.*\.html$`, `manage.py` | **PACK: django** | Stack idioms, reusable across every Django project. Same slot the `astro`/`node` packs fill with `*.astro`, `src/pages/`, `astro.config.*`. |
| `erasure\|pii` (privacy-surface words) | **PACK: django** | Generic enough to be stack-level privacy vocabulary. |
| `accounts\|booking` | **PROJECT** | These are one application's module names. They are not a stack idiom and must not ship to every Django consumer. |
| `^Specs/.*design.pack/`, `^Specs/.*\.md$`, `^docker-compose\.yml$`, `^Caddyfile$`, `^scripts/backup\.sh$` | **PROJECT** | One project's repo layout (AF-6.4). Today every consumer inherits another project's directory names as CORE routing. |
| `framework-validator` as a routed agent | **removed from the consumer registry entirely** | It is not shipped to consumers (AF-6.2). It belongs to `core.yaml` only if and when the `hos-dev-pack` exists; until then it is a HOS-repo-only binding. |

The privacy branch's discretionary `|| echo "privacy-reviewer (check if PII-relevant)"` (AF-6.3) does not
survive the migration: under AD-6 the predicate either matches, in which case the dimension runs, or it
does not, in which case a `not_applicable` record with a stated reason is written. There is no third
output and nothing is left for a reader to decide.

### AD-12 — ONE registry schema and ONE loader; TWO runners. The unification the human asked about does not hold at the runner level, and here is exactly where it stops. (BINDING; answers the 2026-09-14T18:46:07Z comment directly.)

The human explicitly invited "say so and why" over a forced unification. Taking that option, with the
boundary drawn precisely rather than as a refusal:

**Shared, and genuinely so — built once, used by both roles:**
the invocation primitive (AD-1…AD-5); the result document (AD-6); the fail-closed classification (AD-4);
the registry *file format*, *ownership rules*, *predicate language*, and *loader* (AD-9); the posture
profiles (AD-7); the observability path (AD-8); `fingerprint()` and the prohibition on `load_ledger()`
(AD-6); the exit-code vocabulary (AD-1).

**Not shared — and forcing them together would produce a worse mechanism than either:**

| | Overseer (REQ-B) | Worker (#1644, under Q4+Q6) |
|---|---|---|
| Unit | a **set** of checks over one changeset | a **node** in a stage graph over a work queue |
| Execution per cycle | many entries, ideally all | **exactly one** stage |
| Ordering | mostly irrelevant (one soft dependency: code-review gates the parallel lenses) | **total** — the whole mechanism *is* the ordering |
| State | none between entries; the diff is the input | the durable state *is* the mechanism — GitHub labels, issue bodies, dependency edges |
| Termination | all entries have a record for the current input | the graph reaches a terminal stage |
| Failure of one item | record it, keep going, aggregate | stop the stage; the next cycle decides |
| Loop declaration | **none** — a fan-out has no rounds | the central concern |

The human asked specifically whether loop structure (`loopable`, `cap`, `stuck-criteria`) becomes a
declared registry property. **On the overseer side: no, and it must not be** — there is no loop to
declare, and adding the keys would invite someone to build one in the place Q4+Q6 just ruled loops out
of. On the worker side it is the right idea, but the properties it needs (`next_stage_on`,
`blocked_by`, `stage_label`, `cap`, `stuck_criteria`) describe a graph, not a set. Those keys belong to
#1644's registry file, sharing this one's *format, ownership model, and loader*, and nothing else.

So: **two runner implementations, one schema family.** The overseer's runner is AD-13. The worker's is
#1644's and is not designed here (§4).

### AD-13 — The sweep runner: a fan-out, executed as a script (not inside a model session), resumable across cron cycles, keyed by `input_digest`, with a per-cycle budget. (BINDING — REQ-B3, REQ-B4, REQ-B5; Q2, Q4; §3.)

- **`scripts/automation/dimension_sweep_cli.py`** (L2) + **`bootstrap/run_dimensions.sh`** (L3), same
  tiering as AD-1. It does **not** replace `run_gates.sh`/`run_validators.sh`; it *calls* them as
  deterministic bindings (AD-10), keeping those two proven runners intact.
- **It runs as a script, not from inside the overseer's `claude` session.** Under Q4+Q6's "no nested
  sessions" ruling and VF-11's nesting-budget finding, the sweep is a peer of the model session, not a
  child of it. This is a deployment-topology change to `bin/hos-cron` → **ESC-2**.
- **Resumable and idempotent, keyed by `input_digest` (AD-6).** Each cycle runs the entries that have no
  current record, up to a per-cycle wall-clock and count budget, writes each record durably as it
  completes (never batched at the end — a killed cycle must lose at most one invocation), and terminates
  cleanly. This is #1354's stage-per-cycle pattern generalised to a fan-out, and it is what makes §3's
  arithmetic fit **by construction** rather than by hope.
- **A record is current iff its `input_digest` matches.** A push that changes only files no binding's
  predicate selects does not invalidate that binding's record. This is an identity check on the
  overseer's **own** results — not trust in a worker artifact and not risk-tier subsetting — but it *is*
  a reading of Q2's "unconditionally", so it goes to the human as **ESC-3**.
- **Missing record = blocking.** Absence is never inferred as not-applicable (REQ-B3, AF-8). Only an
  explicit `applicability: not_applicable` record, written by the runner from the predicate, counts.
- **Disposition uses the two existing paths and adds none:** `verdict: request_changes` → the existing
  `record_pr_bounce()` with the existing `bounce_count() < 2` budget and SPEC-378 R1.2 rationale fields;
  `outcome: invocation_failed` → the existing `HUMAN_REQUIRED` escalation (Q1). No new outcome class
  (#1626), #1580's ordering preserved.
- Default per-entry concurrency is **1**. The runner may support a concurrency knob, but parallel fan-out
  is not designed here: it concentrates subscription-quota burn in a window the #1446 breaker cannot see
  (AD-8), and its wall-clock benefit is exactly what AD-13's resumability already buys without that risk.

### AD-14 — Dimension results live in a PR comment carrying a machine-readable envelope, written under the overseer's App identity. Never `.claudetmp/`. (BINDING — REQ-B3, REQ-B4; VF-5, Q4.)

VF-5 is decisive: `.claudetmp/` is gitignored, worker-authored, and unreachable cross-clone; the Q4
ruling says the same thing in general terms (*"records the decomposition durably (issue body/comments/
labels — not `.claudetmp`, per VF-5's lesson")*. And `overseer.md:7` forbids the overseer from opening
branches or PRs, so it cannot commit results to the PR branch alongside `signoffs/<ns>/<role>.stamp`.

- Results are posted as a PR comment using **`scripts/automation/lib/envelope.py`**'s existing
  machine-readable frontmatter block (`---hos-envelope`, `type`, `correlation-id`, idempotency via
  `correlation.py`), written through **`bootstrap/post_comment.sh --app overseer --body-file`**. All
  existing canonical entry points; **no new mechanism.**
- **Trust is the GitHub-API-verified comment author**, exactly as `envelope.py`'s header already
  specifies (*"Auth is done via the GitHub-API-verified comment/issue author (NOT the `from:` field)"*).
  A record not authored by the overseer App identity is not a record. This closes the forgery surface
  that a committed-artifact approach would open.
- Reads go through **`bootstrap/query_issues.sh --comments <n>`**. Never a hand-rolled `gh api` read.
- Records are append-only; the newest record for a given `(entry, input_digest)` wins. A comment is never
  edited to change a verdict.
- `technical-design` should size this: 12 entries × several pushes is a lot of comment traffic. A single
  rolling summary comment updated per cycle, with the per-entry documents attached to it, is acceptable
  **provided** the append-only audit property is preserved somewhere; choose and state one.

### AD-15 — REQ-B6 closes on the dimension results via a required, non-defaultable, verifying-constructor parameter on `decide_merge_authority()` — not on the register, and not by prose composition. (BINDING — REQ-B6; AF-4, AF-5, VF-4. Sequenced behind #1641, composed at ADR-1357 slice 2.)

Of the three candidate closures pm-agent named, the register-based one is eliminated outright by **AF-5**
(HOS has no `contract/step-manifest.yaml`, so that gate cannot bounce on anything here), and "gate at a
different layer" is eliminated by **AF-4** (a different layer is precisely where the narration currently
lives). The binding closure is the second, made structural:

1. `decide_merge_authority()` gains a **required positional parameter** — no default, no `Optional`, no
   `None` — carrying the resolved dimension results. "No results" becomes **unrepresentable at the call
   site**: the function cannot be called without one, in Python, at the signature level.
2. That parameter's type has exactly one constructor, and it **validates structure, not content**: every
   entry the resolved registry marks required for this diff has a record; every record's `input_digest`
   matches the current diff; every record is authored by the overseer identity (AD-14). Constructor
   failure ⟹ no object ⟹ no call ⟹ no merge.
3. **Content is branched on inside `decide_merge_authority()`,** not smuggled into the constructor, so
   the decision stays in the decision function and stays auditable there: any record with
   `outcome: invocation_failed` ⟹ `HUMAN_REQUIRED` (Q1); any record with `verdict ∈ {request_changes,
   error}` ⟹ the bounce path (REQ-B5). `oversight_verdict: str` survives but is demoted from "the only
   review-shaped input" to one input among two.
4. **Composition happens in ADR-1357's slice-2 `overseer_decide.py`**, which is already designated as
   the single place that fetches inputs fresh and calls the decision (R9.1.1's "never a cached result").
   It fetches the dimension results the same way and for the same reason. **This ADR does not add a
   second composition point.**
5. **Accepted, stated cost:** the signature change touches the 157 existing merge-authority tests
   (ADR-1357 VF-4). Their logic sign-offs stand; their call sites and expectations change. §8.

### AD-16 — Migration of the four `claude -p` sites: three migrate, one is exempted on the record. (BINDING — REQ-A1; VF-3.)

| Site | Disposition | Grounds |
|---|---|---|
| `scripts/framework/validate_self.sh:236` | **Migrate — first and highest value.** **Gated by §9.5 (ESC-J):** the `opus-self` seat needs a new shipped `self-reviewer` agent, which lands first as its own human-gated protected-surface change. | Unbounded timeout on the framework-validation critical path (VF-3: *"a hang here hangs all of framework validation"*). Also #1536's first target. |
| `scripts/framework/validate_scripts.sh:182` | **Migrate** | Already the most correct of the three postures; migration is a net simplification and deletes a `run_capped` copy (AD-5.3). |
| `scripts/run_panel.sh:146-147` | **Migrate**, with the panel's Claude seat promoted to a shipped named agent (AD-3 admits no bare-model path) | No timeout at all today, stderr to a log, output used as-is. Non-goal 3 is untouched: this changes *how* the same-vendor seat is invoked, not the cross-vendor property of the panel. If `technical-design` finds promoting the lens to an agent too large for W4, it must say so and split it — **not** add a bare-model escape hatch to the primitive. |
| `bootstrap/setup_clis.sh:148` | **EXEMPT, recorded** | It is a machine-bootstrap smoke test (`claude -p "Reply with exactly: OK"`) that runs *before* the primitive's preconditions can hold — possibly with no HOS project checked out at all, certainly before any agent file is installed. Routing it through the primitive would make the smoke test depend on the thing it exists to prove works. A one-line comment citing this ADR goes in the file so the exemption is visible where someone would otherwise "fix" it. |

After migration, CLAUDE.md gains one canonical-entry-point row for `bootstrap/invoke_agent.sh`, and the
standing rule is: **nothing else in the repository invokes `claude --agent` directly.**

---

## 3. Cost — Q2's unconditional rerun does not fit one cron cycle, and the design must absorb that rather than assume it away

This is the ADR's load-bearing feasibility question and I am not going to soften it.

**The count.** Judgment entries the overseer must rerun per PR under Q2: the eight review lenses VF-6
found unexecuted (`code-review`, `security`, `privacy`, `reliability`, `ops`, `ui`, `a11y`, `infra`),
plus `scope-conformance` (#1626) and `semantic-duplication` (#1629), plus the two the overseer already
dispatches and whose results gate (`oversight-evaluator`, `risk-assessor`) — which under AD-2 become
primitive invocations too. **Twelve.** A docs-only PR will see several resolve to `not_applicable` by
predicate at zero model cost; a PR touching code, templates and infra will see all twelve.

**The arithmetic, against measured constraints.**

| Quantity | Value | Source |
|---|---|---|
| `HOS_CRON_MAX_SECONDS` | **1800s** | `bin/hos-cron:39`, `:215`, `:1788` |
| Worker cron interval | **median 601s** (n=85, min 547) | §0 measurement, `audit/log/2026/09/` |
| Cycles hitting the cap today | **1 in 86** (~1.2%) | §0 measurement |
| Repo's own per-AI-review cap | **300s** | `validate_agents.sh:141`, `validate_scripts.sh:54` |
| Observed duration of one `claude --agent` review | **unknown — never run** | VF-2; §0 verification gap |

- Serial, at the repo's own 300s cap: **12 × 300 = 3600s = 2.0 × the cycle budget.**
- Serial, at a hypothetical 150s median: **1800s = exactly the budget, with zero left** for the
  overseer's PR fetch, gate checks, merge decision, comment posting, and its own model session.
- For the sweep to fit inside one 1800s cycle *alongside* existing overseer work, the per-dimension
  median would have to be ≤ ~60–75s across all twelve. **Nothing in the repository supports that
  assumption,** and the honest position is that I have no measurement at all (§0 gap).

**Conclusion: it does not fit, and the fix is structural, not a smaller timeout.** AD-13's resumable,
budgeted, multi-cycle sweep makes it fit by construction: at a 900s per-cycle budget and a 150s median,
~6 entries per cycle → 2 cycles; at the 300s worst case, ~3 per cycle → 4 cycles. At the measured 601s
interval that is **roughly 20–40 minutes of added merge latency per PR head SHA**. That is the same class
of latency tradeoff the human explicitly accepted in the Q4 ruling for the design chain (*"a 3-round
convergence now costs at least 3 cron intervals"*), so accepting it here is consistent rather than new —
but it is a real, user-visible timing change and it goes to the human as **ESC-1**.

**The multiplier nobody has costed.** Without AD-13's `input_digest` reuse, *every push* to a PR
re-runs all twelve. A PR with five pushes costs **60 model sessions**. With reuse, a push touching only
`docs/` re-runs only the entries whose predicates select changed files — typically one or two. The
difference between those two numbers is the difference between feasible and not, which is why **ESC-3**
(is reuse inside Q2's "unconditionally"?) is not a pedantic question.

**What I am binding rather than assuming:** AD-13's **first build slice is a measurement, not an
enforcement** — one entry, observation-only, recording durations and outcomes without gating anything.
That is ADR-1357's slice-3 shape reused deliberately (*"divergence … is measured, not assumed"*), and it
converts the largest unknown in this ADR into data before anything depends on it. **`technical-design`
must not calibrate the per-cycle budget from my estimates; it must calibrate from that slice's output.**

---

## 4. The seam left for #1644 — stated explicitly, per the scope brief

**What I am leaving:** #1644's build side gets the whole of §2's shared layer — the primitive (AD-1…AD-5),
the result document (AD-6), the fail-closed classification (AD-4), the posture profiles (AD-7), the
observability path (AD-8), the registry's format/ownership/loader (AD-9), `fingerprint()` plus the
standing prohibition on `load_ledger()`'s silencing (AD-6, Q5) — and it builds **its own runner** and
**its own registry file** on top. Nothing in §2 presumes a fan-out.

**The property of REQ-A that makes the seam work is AD-2:** the primitive is a top-level, stateless,
one-shot process. It has no round counter, no resume token, no parent-session dependency, and no
knowledge of what called it. A cron-driven stage advancer that executes exactly one stage per cycle can
therefore invoke it **identically** to the way AD-13's sweep does — which is the whole point, because
under Q4+Q6 that advancer is what #1644 becomes. Had the primitive carried loop state (the natural
design if it had been built for #1644 first), it would be unusable in the very shape the human's ruling
mandates.

**What I explicitly do not design, and flag as #1644's to close:** the human's own noted gap — nothing
guarantees the next cron cycle picks up the *expected* next stage rather than something else off the
queue, and nothing stops a coder invocation landing on a spec-only issue. That needs a stage-type label
mechanism, checked deterministically and cheaply before any model turn, plus explicit blocking/dependency
edges on decomposed issues — designed **together with** the pending `needs-ai` → `needs-worker`/
`needs-overseer` rename (#1349, DECISIONS.md 2026-09-06), not as a second parallel labelling scheme.
AD-9's loader and ownership model are available to it; its graph keys (`stage_label`, `blocked_by`,
`next_stage_on`, `cap`, `stuck_criteria`) are not declared here and must not be pre-empted (AD-12).

---

## 5. Build order

Wrappers before consumers; measurement before enforcement; the one item that changes what merges isolated
into its own PR. Each row is an intended issue boundary — filing "implement ADR-1643" as one issue would
reproduce #1354.

| # | Slice | Contents | Gate to proceed |
|---|---|---|---|
| **W1** | The primitive | AD-1, AD-2, AD-3, AD-4, AD-5. L2 + L3, with unit tests driving a **synthetic envelope per failure class in AD-4's table**, including VF-1's exact `subtype:"success"` + `is_error:true` shape. | Every AD-4 row has a failing-closed test. **Blocked on AD-7's probe** (§0 gap) only for the posture half. |
| **W2** | Result document | AD-6. Round-trips through `validation_logic.compute_verdict` and `panel_logic`'s readers unchanged; an `invocation_failed` document is proven to raise `new_blocking_count`. | Designed in parallel with W1; lands with or before it. |
| **W3** | Observability | AD-8: `token_tracker` wiring, per-entry audit record, nested usage-limit surfacing toward #1446. | Depends on W1. |
| **W4** | Migrate the three sites | AD-16; delete both `run_capped` copies; add the CLAUDE.md row. | Depends on W1. **Low risk, high value** — fixes two unbounded timeouts as a side effect and is the primitive's first real proof. |
| **W5** | Registry | AD-9 + AD-11: schema, fail-closed loader, three-layer merge, `core.yaml` + `pack-django.yaml` + `pack-astro.yaml`, `run_post_change_sweep.sh` reduced to `--explain`. **Verify the data-file merge against `hos_install.sh` (AF-9), do not assume it.** | Depends on nothing but W2's schema; **can run in parallel with W1**. |
| **W6** | **Measurement slice** | AD-13 runner, **one** judgment entry, **observation only** — records durations and outcomes, gates nothing. | **Do not skip for speed.** This is the only source of the number §3 lacks and the input to ESC-1's real answer. |
| **W7** | The sweep | AD-13 full + AD-14 result storage. Still non-gating. | Depends on W5, W6. **Blocked on ESC-2** (new cron stage) and informed by **ESC-3**. |
| **W8** | REQ-B6 | AD-15. **Its own PR, never bundled** — this is the slice that changes what merges. | Depends on W7 **and on ADR-1357 slice 2**. **Blocked on ESC-4.** |
| **W9** | REQ-B7 | Enumerate the entries with no deterministic checker; file one issue per genuine gap. Audit + issue-filing, no code. | Any time after W5. |
| **W10** | #1536 re-scoped | Overseer runs framework-validation itself via the primitive; retire the stamp. | Depends on W4. |
| **W11/W12** | #1626 / #1629 re-scoped | Dimension definition only — inputs, prompt, disposition, predicate. **No private invocation, parsing, or fail-closed logic** (REQ-D0). #1629 additionally blocked on Q8's operationalisation. | Depends on W7. |
| **W13** | #1621 annotated | Confirmed **not** a REQ-A consumer — it is a deterministic approval-state check and belongs with #1641's primitives. Annotate so nobody builds an agent invocation into it. | Any time. |

**Amended 2026-09-15 (§9) — three rows above changed scope:**
- **W1** — the classifier is specified by **§9.1 and §9.2**, not by AD-4's original table. W1 is otherwise
  unchanged and is **cleared to start**.
- **W4** — loses `validate_agents.sh`'s `run_capped` deletion (**§9.4**), and its `validate_self.sh`
  migration is gated on the new `self-reviewer` agent file (**§9.5**). W4's remaining contents
  (`validate_scripts.sh`, that file's `run_capped` deletion, the `setup_clis.sh` exemption comment, the
  CLAUDE.md row) are unblocked.
- **W4a (new)** — the `self-reviewer` agent file plus its ship-set registration (§9.5). Protected surface,
  human-gated, its own PR. Blocks W4's `validate_self.sh` half and nothing else.

**Track 0 is unaffected and must not wait:** #1642 (landed as `922a97a0`) and #1567 Gap 5 (the
required-check promotion, `33211f25`) are REQ-B2's deterministic lane and are independent of everything
above.

**If v0.7.0 runs short:** W1–W6 alone is a coherent, independently valuable release — it produces the
primitive, the registry, the migrations, and the measurement, and it closes VF-3's two unbounded
timeouts, without yet changing what merges.

---

## 6. Escalations — held for the human (I do not bind these)

### ESC-1 — Q2's unconditional rerun does not fit one cron cycle. (Cost model + user-visible latency. Product-boundary checkpoint.)

§3: twelve judgment entries, serial, at the repo's own 300s per-review cap is **3600s against an 1800s
cycle budget**; even at a 150s median it consumes the entire budget with nothing left for the overseer's
own work. I have **no measurement** of how long one `claude --agent <reviewer>` invocation actually takes,
because no such invocation has ever run here (VF-2).

**My binding technical answer is AD-13** — a resumable, budgeted, multi-cycle sweep, which makes it fit
by construction. **What is yours** is its consequence: **roughly 20–40 minutes of additional merge
latency per PR head SHA** at the measured 601s cron interval, and a per-PR spend of up to twelve model
sessions per head SHA. That is a user-visible timing change and a cost-model change, which is exactly
what the product-boundary checkpoint covers.

**Recommendation:** accept AD-13, and require W6's observation-only measurement slice before W7 depends
on any budget number. The tradeoff is the same one already accepted in Q4 for the design chain, so
accepting it is consistent — but it should be accepted knowingly rather than inherited from an ADR's
arithmetic.

### ESC-2 — The sweep becomes a new top-level execution stage in `bin/hos-cron`. (Deployment topology + operational obligation. Product-boundary checkpoint.)

AD-13 runs the sweep as a **script**, a peer of the overseer's model session rather than nested inside it
— which is the direct consequence of Q4+Q6's "no nested sessions" and VF-11's nesting-budget finding.
That means `bin/hos-cron --role overseer` grows a new execution stage, with its own wall-clock budget,
its own lock interaction, and its own failure surface. There is no measured overseer cycle baseline to
sit it beside (§0: **zero overseer records in the September audit trail**).

**Decisions that are yours:** (i) may `hos-cron` gain a script-execution stage outside the model session
at all; (ii) does it get its own wall-clock budget or share `HOS_CRON_MAX_SECONDS`; (iii) is the
overseer currently running, and if not, is its silence itself something to look at before adding load to
it. **Recommendation: yes to (i), a separate budget for (ii)** — sharing one cap means the sweep and the
model session starve each other unpredictably — and **(iii) should be checked before W7 ships**, since
a mechanism that only runs in a role that is not running is ADR-1604's AF-1 in a new costume.

### ESC-3 — Does `input_digest` reuse fall inside Q2's "unconditionally"? (Interpretation of your own ruling. **ESC-1's arithmetic depends on the answer.**)

Q2 ruled: *"every non-CI/CD-covered judgment dimension is rerun by the overseer in its own context,
unconditionally"*, dropping REQ-B4's risk-tier subsetting. AD-13 does not subset by tier and does not
trust any worker artifact — but it does skip re-running a dimension when **the overseer's own prior
record for that dimension has an identical `input_digest`**: same selected file bytes, same agent file,
same prompt template, same registry entry.

**My reading is that this is inside your ruling**, because it is neither of the two things you excluded
(it is not a tier subset, and the result being reused is the overseer's own, produced in its own
context). It is an input-identity check, the same principle as the existing head-SHA staleness rule on
human approvals. **But it is a conditional, and you said unconditionally**, so I am not binding the
interpretation myself.

**Why it matters concretely:** without reuse, a PR with five pushes costs **60 model sessions** instead
of roughly 12 plus a handful. If you rule against reuse, ESC-1's latency and cost figures multiply by the
push count and AD-13's per-cycle budget must be recalibrated.

### ESC-4 — Twelve review dimensions that have never executed become merge-blocking at once. (Operational + throughput. Product-boundary checkpoint.)

VF-6 is not "the overseer reruns some dimensions inconsistently" — it is that **none of the eight AI
review lenses has ever been independently executed on the gating side**, and #1626/#1629 add two more
that have never run at all. W8 turns all of them into hard merge blockers simultaneously, with Q1's
fail-closed rule on top. The predictable first effect is a large backlog of genuine, newly-surfaced
findings and a merge rate near zero for some period — findings that are *real*, which is the point, but
which arrive all at once.

**Options:** (a) land W8 enforcing; (b) run the full sweep in **observation-only** mode for a defined
window first — results recorded and posted, merge unaffected — then flip enforcement.

**Recommendation: (b)**, copying ADR-1357's slice-3 shape verbatim, for the same reason it was right
there: it converts an assertion into a measurement before anything depends on it, and it lets the
backlog be triaged deliberately rather than discovered by a stalled queue. W6 is already the one-entry
version of this; (b) is the twelve-entry version. The cost of (b) is one extra release cycle before the
gap actually closes, and the gap is `priority:critical`, so this is a genuine judgment call about risk
appetite and not one I should make.

---

## 7. Non-goals — named, with owners

- **#1644 and REQ-C / Track 3 (W13–W18)** — going back to `pm-agent` under the Q4+Q6 ruling. §4 states the
  seam; nothing here binds it. W16's nested-invocation budget in particular no longer describes a real
  unit of work.
- **What any reviewer agent looks for** — unchanged (non-goal 1). No lens is widened, narrowed, or
  rewritten. This changes who invokes them and who reads the answer.
- **Any human gate** — untouched (REQ-A11, non-goal 2). An `approve` verdict from any agent invoked this
  way is evidence for a *bot-side* decision only. Protected-surface, security-surface, CRITICAL-tier and
  release gates are unchanged, and AD-15 only ever *adds* reasons to escalate.
- **Cross-vendor review** — `run_second_review.sh` / `run_panel.sh` keep their decorrelation role
  (non-goal 3); AD-10 makes the second review a registry entry rather than replacing it, which is also
  how Q5's convergence-confirmation ruling composes.
- **#1641's merge-authority invocability work** — depended on, not re-specified (non-goal 4). ADR-1357's
  slice 2 remains the composition point; AD-15 supplies it one more required input.
- **A general agent-orchestration framework** — non-goal 5. Two runners, both named, both scoped.
- **AI review in CI** — #1216 stands (non-goal 7). This runs in the overseer's own environment.
- **The `hos-dev-pack`** — AD-11 removes `framework-validator` from the consumer registry; it does not
  create the pack that would eventually hold it.
- **`.claude/agents/**`, scripts, and config** — this session wrote exactly one file, this ADR. Every
  change described above is a protected-surface edit to be authored and human-gated later.

---

## 8. Startup-gap analysis and affected sign-offs

**"Should this have been settled in an initial architecture review, before design and code were built
against it?"** — asked of each item, per the CORE startup-gap rule.

- **The missing invocation primitive (VF-2).** Yes — this is the same original-design gap ADR-1357 §6
  recorded for `merge_authority.py`: capability built as a library or as prose with no executable surface.
  Four `claude -p` sites with three reliability postures accumulated because no primitive existed to use.
  **No superseded ADR of mine exists here, so no sign-off is orphaned**; the lesson attaches to the design
  phase and belongs in #1243's core-principles register alongside #1359's *"a control must be executed,
  not narrated."*
- **`run_post_change_sweep.sh`'s consumer-shaped routing in CORE (AF-6.2, AF-6.4).** Yes — a layering
  decision that should have been made when the script was written. Every consumer install has been
  routing against one project's directory names and naming an agent (`framework-validator`) that install
  never received. **No consumer sign-off exists to invalidate**; HOS's own sign-offs on the script stand
  (the code does what it was signed off to do), but AD-11 changes its scope and it must be re-reviewed
  as part of W5, not carried over. **A `startup-artifact-gap` issue should be opened** for the CORE/PACK/
  PROJECT layering of routing data, since AF-9 shows the pack mechanism to support it never existed.
- **`decide_merge_authority()`'s absent dimension parameter (VF-4, AD-15).** Yes — and it is the same
  finding ADR-1357 made about the same function from a different angle. **Sign-offs that stand:** the 157
  merge-authority unit tests' logic sign-offs; AD-15 changes the signature and their call sites, not the
  decision logic being tested. **Sign-offs flagged for re-review:** any test whose *expectation* encodes
  "a merge-eligible decision is reachable without reviewer input" — that expectation becomes wrong, in the
  same way `test_merge_authority_detection.py`'s docstring encoded the stub state ADR-1357 VF-4 found.
  `technical-design` must enumerate those specifically rather than re-running the suite and calling it
  green.
- **The lost prior architect pass (the ESC-5 ADR).** The artifact is gone; the human's ruling on it
  stands and is carried forward in AD-9 with the AD-3/AF-9/AF-15 reasoning re-derived in this ADR's own
  numbering (the narrow-only rule and the required-to-do-nothing trap). **No design or code was built
  against the lost ADR** — #1643 is unstarted — so **no sign-off is orphaned by its loss.** Recording it
  here is the only durable trace that the ruling has a home; if a future reader finds ESC-5 referenced
  from #1643's comments with no ADR behind it, AD-9 is where it landed.
- **Nothing else.** W1–W13 are all new build.

---

## 9. Amendment 1 — rulings on the technical-design escalations (2026-09-15)

`technical-design` produced `docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md` (merged, PR #1658)
and routed five escalations back to me in its §12, two of them blocking the coder on slice W1. This
section rules all five, disposes of the three non-blocking ones, and states exactly which
technical-design clauses it supersedes. **Where this section and §2 differ, this section governs. Where
this section and the technical design differ, this section governs.**

Read this section before implementing AD-4. It is written for a coder with no session context.

### 9.0 What I verified myself this pass — not taken from the technical design

Symbols and literals, never line numbers (PR #1658's review found the technical design's line citations
had drifted by one to two lines; the lesson is applied here).

- **The installed CLI is `2.1.271`** — one patch release ahead of the `2.1.270` the technical design
  probed, **on the same day**, with the resolved binary under `~/.local/share/claude/versions/`.
  ESC-B's premise demonstrated itself inside a single design chain. Nothing about this design may pin a
  CLI version.
- **`subagent_stats.refused` is an object and its key set is open.** The 2.1.271 bundle contains the
  initialiser literal `refused:{depth_limit:0,concurrency_limit:0,budget:0}`; the accumulator's method is
  `recordRefused(e){this.#e.refused[e]+=1}` — a **dynamic key** — and its `snapshot()` emits
  `refused:{...e.refused}`, a spread. Only three call sites exist today
  (`recordRefused("budget")`, `recordRefused("concurrency_limit")`, `recordRefused("depth_limit")`), so
  the three keys are exhaustive **for this version only**. TD-F1 is confirmed independently of the probe,
  and §9.1 derives from this a consequence the probe could not show.
- **`terminal_reason` carries at least four failure values this ADR never named** —
  `structured_output_retry_exhausted`, `turn_setup_failed`, `tool_deferred_unavailable`, `aborted_tools`
  — all present as string literals in the bundle. AD-4's allowlist-of-good-values blocks all four with no
  code change. A denylist would have missed all four. The design move is vindicated, not merely defended.
- **`terminal_reason` is conditionally emitted by at least one composer**
  (`...s.terminal_reason!==void 0&&{terminal_reason:s.terminal_reason}`), adjacent to a comment about
  *"Remote Control bridge's per-turn synthetic results, and from older producers"*. This is the one piece
  of evidence **against** §9.2's presence requirement. §9.2 states how it is handled rather than omitting
  it.
- **`validate_agents.sh` has no `claude` call site.** Its only `claude` occurrences are the
  `.claude/agents` path in its usage text and in `AGENTS_DIR`; its `run_capped` is called exactly twice,
  once for `agy` and once for `codex`. TD-F5 confirmed. A third private `_TIMEOUT_BIN` exists in
  `bin/hos-cron`.
- **`validate_self.sh` is installed into consumer projects** (`scripts/framework/install.sh` copies it),
  while **`framework-validator` is not** in `scripts/framework/consumer_agents.txt`. That pair of facts
  decides §9.5.
- **`code-reviewer`'s diff-centric input contract is a CORE clause carrying "PROJECT may NEVER override,
  weaken, or remove"**, and its `description` states it does not cover the other lenses. That decides
  §9.5's rejection of the reuse option.

### 9.1 ESC-A / TD-F1 — `subagent_stats.refused`: the reading is CONFIRMED, with the value rules made explicit. (Supersedes AD-4's `refused` row. Blocking W1 — now unblocked.)

**Ruling.** TD §3.7 C6 is correct and is adopted. `subagent_stats.refused` satisfies the condition for
`completed` when it is **absent**, **or** is the integer `0`, **or** is a flat mapping every one of whose
values is the integer `0`.

`technical-design` was right to escalate rather than implement: under Q1 a literal `refused == 0` would
have failed every healthy invocation closed and stopped every merge in the repository. That is the
correct instinct and the correct route.

**The value rules, which the escalation did not fully state and which are binding:**

1. **The rule quantifies over values, never over a known key set.** Do not write an allowlist of
   `{depth_limit, concurrency_limit, budget}`. §9.0 shows the CLI increments `refused[<reason>]` by
   dynamic key and emits the object by spread, so a refusal reason we have never seen will appear as a
   key we have never seen. Quantifying over values blocks it with no code change; quantifying over keys
   would ignore it. This is the same allowlist-not-denylist move as AD-4's `terminal_reason` row, applied
   one level down.
2. **"The integer `0`" excludes booleans.** In Python `isinstance(True, int)` is `True` and `False == 0`
   is `True`. A naive implementation reads `refused: {"budget": false}` as healthy. A boolean value is
   `envelope_shape_violation`.
3. **`null` is not zero — and it is the most likely wire shape of a brand-new refusal reason.** Derived
   from §9.0: a fourth reason increments an uninitialised key, `undefined + 1` is `NaN`, and
   `JSON.stringify` emits `NaN` as `null`. Any non-integer value ⟹ `envelope_shape_violation` ⟹
   `invocation_failed`. This rule is the reason the loosening is safe.
4. **Only a flat mapping of scalars is accepted.** A nested mapping, a list, or a string ⟹
   `envelope_shape_violation` (TD §3.7's detail rule 3, unchanged).
5. **Absence remains harmless** (AD-4's original position). TD test T1.16 stands. §9.2 explains the
   asymmetry between this negative marker and the one positive marker.

**The safety property that survives the loosening, stated precisely.** The row exists to detect that the
CLI **refused to spawn a subagent the reviewer asked for** — i.e. work the reviewer intended was not
done, so the review is partial while presenting itself as complete. "Scalar zero" and "every value zero"
are the same statement: *no refusal of any kind was recorded*. Nothing capable of carrying a refusal
count is skipped, because rule 1 quantifies over every value present. What is **not** loosened is the
unknown case: an unrecognised type is never read as healthy — it is a shape violation, which is blocking.

**The amended AD-4 classifier table — implement this one.** `outcome: "completed"` is produced only when
every row holds; any miss ⟹ `outcome: "invocation_failed"` ⟹ `verdict: "error"` (AD-6's non-negotiable
rule, unchanged).

| # | Condition for `completed` | Miss ⟹ `outcome_detail` |
|---|---|---|
| A1 | our own wall-clock cap did not fire | `timeout` |
| A2 | stdout parses as **exactly one** JSON object (surrounding whitespace tolerated, nothing else) | `unparseable` |
| A3 | `is_error` is absent or falsy; if present it must be a JSON boolean | true ⟹ `crash`; present and not a boolean ⟹ `envelope_shape_violation` |
| A4 | `terminal_reason` is **present**, is a string, and is in `GOOD_TERMINAL_REASONS = {"completed"}` (**§9.2**) | absent ⟹ `terminal_reason_missing`; not a string ⟹ `envelope_shape_violation`; any other string ⟹ blocking, labelled per TD §3.7's detail rule 4 |
| A5 | `permission_denials` is absent or an empty list | non-empty ⟹ `permission_denied`; present and not a list ⟹ `envelope_shape_violation` |
| A6 | `subagent_stats.refused` is absent, **or** the integer `0`, **or** a flat mapping all of whose values are the integer `0` (rules 1–5 above) | any value non-zero ⟹ `refused`; any disallowed type ⟹ `envelope_shape_violation` |
| A7 | process exit code == 0 | `crash` |
| A8 | the agent payload extracted from `result` parses **strictly** as a conforming AD-6 body | `schema_violation` |
| A9 | — | unknown **top-level** fields do not affect the outcome (**§9.2**) |

`subtype` is still never an input (AD-4's binding note and TD test T1.23 stand). TD §3.7's
`outcome_detail` precedence list is otherwise unchanged; it gains `terminal_reason_missing` (§9.2).

**Tests that pin this ruling.** TD §9.1's T1.12–T1.16 stand as written, plus three new ones, all of which
are part of W1's slice gate:

| New test | Fixture | Asserts | Pins |
|---|---|---|---|
| **T1.13b** | `refused = {"depth_limit":0,"some_future_limit":7}` | `invocation_failed`, detail `refused` | rule 1 — key-universality; a key-allowlisted implementation passes this envelope and fails this test |
| **T1.15b** | `refused = {"depth_limit":0,"budget":null}` | `invocation_failed`, detail `envelope_shape_violation` | rule 3 — the `NaN`→`null` wire shape is never zero |
| **T1.15c** | `refused = {"budget":false}` | `invocation_failed`, detail `envelope_shape_violation` | rule 2 — the Python boolean-is-an-int trap |

### 9.2 ESC-B / TD-F2 — unknown envelope fields: the interim contract is RATIFIED, with one tightening that pays for it. (Supersedes AD-4's unrecognised-field clause and its `terminal_reason` row. Blocking W1 — now unblocked.)

**Ruling, in three parts.**

**(a) Unknown top-level envelope fields are recorded and do not block.** TD §3.7's interim contract is
adopted as binding: an unrecognised top-level field is recorded in
`invocation.envelope_unknown_fields[]` (and in the verbatim envelope AD-6 already stores) and has no
effect on the outcome. An unrecognised **value or shape in a decision field** (A3–A8) still blocks. **TD
test T1.24 stands as written**; it is no longer conditional on this ruling.

**(b) The tightening: `terminal_reason` must be PRESENT.** AD-4's row said *"absent or in a closed
allowlist"*. It now reads: present, a string, and in `GOOD_TERMINAL_REASONS = {"completed"}`. Absent ⟹
`outcome_detail: terminal_reason_missing` ⟹ `invocation_failed`. Insert it into TD §3.7's precedence
list at rule 4's position — it replaces rule 4's absent case and sits ahead of the `is_error`,
`permission_denials` and `refused` details, because a missing success marker is a more fundamental
statement about the envelope than any individual negative signal.

**(c) Recording obligations, so drift is discoverable instead of silent.** Both of these go in the AD-6
result document **and** in AD-8's per-invocation audit record:
- `invocation.envelope_unknown_fields[]` — the sorted list of top-level keys not in the known set.
- `invocation.cli_version` — from `claude --version`, captured per invocation. **Diagnostic only, never a
  decision input.** Do not gate on it, do not pin a supported version, do not refuse an unknown version:
  that would manufacture exactly the merge-stopping failure mode this ruling exists to avoid.
- **Standing maintenance obligation:** when a new top-level field appears in the trail, HOS classifies it
  as telemetry or as decision-relevant, and if decision-relevant it joins A3–A8 with a test. That is a
  maintenance task with a visible trigger, which is what the literal clause was trying and failing to buy.

**Why the field/value asymmetry preserves the safety property — the part that has to be right.**

- **#669 and #1362 were both *value*-level fail-opens**: a field we *did* read carried a value we did not
  handle, and the handler's default was "pass". Every path of that kind is closed by A3–A8's allowlists,
  which this ruling leaves fully intact and in one case (A4) strengthens. The class of defect behind those
  two issues is not reintroduced here in any form.
- **A field-level block guards a different risk**: a future CLI signalling failure through a field we do
  not read. That risk is real, but the literal clause's cost is certain, immediate and systemic — under
  Q1 it turns *any* telemetry addition into a total merge stop. This is not hypothetical twice over:
  2.1.270 already shipped eight fields no ADR-era reader knew, and §9.0 found the installed CLI had moved
  to 2.1.271 within the same day. A rule that halts the merge queue on a patch bump nobody chose is not
  fail-closed behaviour; it is a denial of service on ourselves, and the predictable response is that
  someone routes around the classifier — which is strictly worse than either alternative.
- **The residual risk the loosening leaves is the rename/relocation case**: a decision signal moves to a
  field we do not read, our field goes absent, and "absent is harmless" reads it as healthy. **(b) closes
  it for the field that matters.** `terminal_reason` is the envelope's *positive* statement that the turn
  ended normally. Require it present and good, and a renamed or removed success signal surfaces as
  `terminal_reason_missing` — blocking, loud, and diagnosable from the very same record, because
  `envelope_unknown_fields[]` in that record names the field that replaced it. The fail-open becomes a
  fail-closed with its own diagnosis attached.

**Why only `terminal_reason`, and not all four decision fields.** `terminal_reason` is a **positive**
marker: its good value asserts that something went right. `is_error`, `permission_denials` and
`subagent_stats.refused` are **negative** markers: their absence means "nothing bad was reported".
Requiring one positive marker converts absence-of-evidence into failure, which is the whole point.
Requiring the negative markers as well buys much less — a renamed `permission_denials` is invisible to us
either way — while multiplying the ways a healthy invocation can be rejected under a hard-block rule.
**One positive marker is required; negative markers may be absent.** Cost check: `terminal_reason` is
present on every probed healthy run of exactly our invocation shape (TD §0.2 probes A, C, K, L), so the
requirement costs nothing today.

**The honest residual, and how it is bounded.** §9.0 found a composer that omits `terminal_reason` when
undefined, beside a comment about synthetic results and older producers. That is not our path — we run
local `claude --print --output-format json` — but if the assumption is wrong the symptom is a **uniform**
`terminal_reason_missing` on every invocation. **AD-13's W6 observation-only measurement slice is exactly
where that surfaces, and W6 precedes everything that gates.** `technical-design` must add *"count of
`terminal_reason_missing` observed"* to W6's reported outputs. If W6 sees any, A4 reverts to tolerating
absence and the rename risk goes back on the record, unmitigated and stated. That is a cheap, reversible
bet taken in observation mode rather than on a live merge queue — which is the only reason I am willing to
tighten a presence requirement against a vendor artifact at all.

**Tests.** T1.24 stands. Two new, both in W1's slice gate:

| New test | Fixture | Asserts |
|---|---|---|
| **T1.9b** | envelope with **no** `terminal_reason` key, everything else clean, rc 0 | `invocation_failed`, detail `terminal_reason_missing`, `verdict: error` |
| **T1.24b** | an unknown top-level field **together with** a failing decision field (e.g. `permission_denials` non-empty) | still blocks on the decision field; the unknown field is recorded and masks nothing |

Plus a W3 test asserting `envelope_unknown_fields` and `cli_version` reach the audit record.

### 9.3 ESC-C / TD-F3 — the auth pre-flight: the design is ADOPTED, the caller obligation is made mandatory, and REQ-A4 needs a pm-agent amendment. (MEDIUM.)

**Ruling on the architecture.** TD §3.4's resolution is correct and is adopted: the pre-flight environment
check is **opt-in** via `--require-env-auth`, and post-hoc detection of `not_authenticated` is
**unconditional**.

There is no fourth option, and the three alternatives are rejected on the record so nobody re-opens this:
(i) a trial `claude --print` probe before each invocation *is itself an invocation* — circular, and at
twelve judgment entries it doubles the session count against a cron budget §3 already shows does not fit;
(ii) reading the keychain is platform-specific and undocumented; (iii) inspecting `~/.claude.json` or a
credentials file binds HOS to a vendor's internal file layout — precisely the coupling §9.2 was just
written to avoid.

**REQ-A4's intent is preserved in full.** The requirement exists so that an auth failure is a
*distinguishable, fail-closed outcome* and never a silent pass. The post-hoc path delivers exactly that.
What is not satisfiable is the requirement's *timing* word — "before".

**Added obligation (binding, and stronger than the technical design's wording).** TD §3.4 says cron
callers "should" pass `--require-env-auth`. **"Should" is not a mechanism.** Passing
`--require-env-auth` is **mandatory for every non-interactive caller**: `bin/hos-cron` in either role,
AD-13's sweep runner, and any script a cron cycle executes. It is optional only for a human at a terminal
and for an agent session invoking L3 by hand. The flag's default stays off. When AD-13's runner is built,
a test must assert the flag is in the argv it constructs; until then the obligation lands on W4's two
migration sites, which run under cron, so both pass it. Rationale: under Q1 an auth gap hard-blocks the
merge either way — the difference is that the pre-flight costs nothing and the post-hoc path costs one
launched session *per dimension*, i.e. up to twelve wasted sessions per cycle for one expired token.

**Requirements amendment: YES — and it is a correction, not a weakening.** `pm-agent` must amend REQ-A4
so its verification-timing clause reads: authentication is verified pre-flight when the caller asserts an
environment-token contract (`--require-env-auth`, mandatory for non-interactive callers), and is always
detected post-hoc as a distinguishable `not_authenticated` outcome. **I have not edited the requirements
document** — that is `pm-agent`'s, and the worker routes it. **W1 is not blocked on the amendment:** the
architecture is ruled here and REQ-A4's intent is met. The amendment exists so a later compliance check
does not read a true implementation as a requirements deviation.

### 9.4 ESC-D / TD-F5 — `validate_agents.sh`'s `run_capped` deletion MOVES OUT of W4. (Amends AD-5.3. LOW.)

**Ruling.** W4 does not touch `validate_agents.sh`. AD-5.3 is amended: **W4 deletes
`validate_scripts.sh`'s `_TIMEOUT_BIN` + `run_capped` only** — that copy *is* attached to a real
migration — and the `validate_agents.sh` copy moves to a follow-up issue.

Grounds:
1. **AD-5.3's justification does not transfer.** The deletion was justified *as a consequence of
   migration*: the copy count falls because the `claude` consumer is gone. §9.0 confirms
   `validate_agents.sh` has no `claude` consumer to remove. What remains is an unrelated refactor of the
   cross-vendor validation path, and it is not free — `run_capped` redirects stdout to a file and
   discards stderr while `with_timeout` does neither, so each of the two call sites grows hand-written
   redirection on the path that produces HOS's cross-vendor evidence. Risk without benefit.
2. **It buys no capability.** `with_timeout` has no `--kill-after`, no `--foreground` and no
   process-group kill either (AF-3). This is consolidation, not repair. The repair is AD-5.1, it is in
   Python, and it ships in W1.
3. **It would pollute the primitive's first proof.** W4's value is that its diff reads as *"the migration
   worked"*. An unrelated bash refactor in the same PR costs that legibility for nothing.

**The copy ledger after W4, so nobody misreads the state.** One Python implementation (AD-5.1, new); one
shared bash helper (`with_timeout`); and **two** remaining private bash copies — `validate_agents.sh`'s
(the follow-up) and `bin/hos-cron`'s. **`bin/hos-cron`'s copy is deliberately out of scope of both W4 and
the follow-up**: it bounds a whole cron cycle rather than an AI review, and replacing it changes the cron
harness's own failure semantics (#1146's territory). The follow-up issue must say so in its body, so
nobody "finishes the job" while looking at a ledger that appears one short.

### 9.5 ESC-J — the `opus-self` seat is filled by a NEW shipped agent, `self-reviewer`. Reuse of `code-reviewer` is rejected. (MEDIUM; blocks TD §6.1 only.)

The escalation asks what the self-review lens *is*, so that is answered first.

**What the lens is.** `validate_self.sh` asks its reviewer for findings in exactly seven categories —
`contradiction`, `governance-hole`, `unenforceable`, `loop`, `gaming`, `stale-status`, `ownership` — over
a package of **framework text** (agent definitions, contract, governance docs, scripts), with a
known-issues list to suppress re-reports and an instruction to be *"honest, not reassuring"*. Every one of
those categories is a property of a **rule**, not of a **program**: whether a rule contradicts another
rule, whether it can be enforced, whether it can be gamed, who owns it. **The lens is adversarial review
of governance text.** It is distinct from every lens HOS ships, and it is the lens HOS's own governance
depends on.

**Ruling: a new shipped agent, `.claude/agents/self-reviewer.md`.** Option (b), reusing `code-reviewer`,
is rejected, and the grounds matter more than the choice:

- `code-reviewer`'s CORE region binds it to a **diff-centric** input contract in a clause explicitly
  marked *"PROJECT may NEVER override, weaken, or remove this constraint"* (*"Your primary input is the
  git diff provided. Do not request full-repository context."*), and to reviewing application code
  **against the technical design and the ADR**. `validate_self.sh` supplies no diff, no technical design
  and no ADR — it supplies a whole-corpus package of governance prose. The agent would be operating
  outside its own binding input contract on every single invocation.
- Its `description` states a closed non-scope; governance text is not in scope either.
- **Substituting an agent whose lens differs from the seat's is the exact failure this epic exists to
  close.** The check would run, produce a document, satisfy the classifier, and answer a *different
  question* — "a mechanism that looks like it is reviewing and is not", which §0 found in four separate
  places and which this ADR's RISK block names as the worse of its two failure modes. Under AD-3 the
  agent **name** is the unit of governance. Naming the wrong one is not a shortcut around AD-3; it is the
  governance violation AD-3 exists to prevent, performed through AD-3's own front door.
- A third candidate, `framework-validator`, *does* describe this lens and is **rejected on ship-set
  grounds**: §9.0 confirms it is not in `scripts/framework/consumer_agents.txt` while `validate_self.sh`
  **is** installed into consumer projects. Binding the seat to it reproduces **AF-6.2 exactly** — an
  installed script naming an agent the install never shipped. **Whichever agent fills this seat must be
  in the consumer ship set.** That constraint is binding on any future revisit of this ruling.

**What the new agent must be:**
- `.claude/agents/self-reviewer.md`, CORE region, `model: opus` — the seat is `opus-self` and
  `validate_self.sh` passes `--model "$MODEL"` explicitly, which AD-3 permits as an override on a *named*
  agent.
- Lens: adversarial review of governance text for the seven categories above. It reviews rules, not code.
- Tools: read-only (`Read, Grep, Glob`), consistent with the `review-read-only` posture AD-7 assigns it.
  It writes nothing, files nothing and fixes nothing.
- Added to `scripts/framework/consumer_agents.txt`, which is the single source of truth for both the
  install copy-loop and `.hos-manifest` (#225) — so the installer and the manifest cannot disagree.
- **The prompt does not move into the agent file.** `validate_self.sh` keeps composing the review package,
  the known-issues list and the output schema, and passes them via `--input-file`. The agent file supplies
  the lens and the posture; the script supplies the corpus. The other split would put a review package
  the agent cannot see into the agent file.

**Sequencing.** This is a protected-surface change (`.claude/agents/**` is the first entry in
`scripts/framework/protected_surfaces.txt` → CODEOWNERS) plus a ship-set change, so it lands as **W4a**:
its own PR, human-gated at merge through the existing gate, and authored by the top-level session per
CLAUDE.md's rule that agent-definition edits are never delegated to `coder`. **W4a does not block W1**,
and it blocks only the `validate_self.sh` half of W4 — TD §6.2, §6.3, §6.5 and §6.6 proceed without it,
as `technical-design` correctly observed. TD-O1 is closed by this ruling.

**Flagged to the human, not a gate.** W4a adds a 27th agent to every consumer install, and TD §6.4's W4b
adds two more for the panel seats. That is a deliberate consequence of AD-3 — a seat with no named agent
must acquire one — and the existing protected-surface gate is the control. It is flagged so that growth of
the shipped roster is a noticed decision rather than a side effect of three separate migrations.

### 9.6 Non-blocking escalations — disposition

- **ESC-E (`scripts/automation/**` is not in the consumer ship-set): ACCEPTED as recorded, no design
  change.** HOS is the only consumer of the primitive in v0.7.0, and both L2 modules live where decision
  logic belongs. Routed to W7's ship-set decision, exactly as `technical-design` routed it. **Binding
  constraint carried forward: the coder must not relocate `agent_invoke_cli.py` or
  `dimension_sweep_cli.py` to make them ship.** Moving decision logic out of `scripts/automation/` to
  reach the ship-set would break AD-1's tiering and, given ESC-G's finding that `contract/**` is a
  protected surface while `scripts/automation/**` is not, would move it across a protection boundary in
  the wrong direction. If the ship-set is the problem, the ship-set changes; the layering does not.
- **ESC-H (`--max-budget-usd` exists on 2.1.270): NOTED, deliberately not adopted in W1–W5.** A cost cap
  converts a cost overrun into an invocation failure, which under Q1 is a hard merge block — a new
  merge-stopping failure mode whose `terminal_reason` on trip is unprobed and would therefore hit A4's
  catch-all and block with an unhelpful label. AF-2's `--max-turns` finding stands and is not disturbed.
  Cost **observability** is already delivered without any new failure mode: the envelope carries
  `total_cost_usd` and `modelUsage`, and AD-8 records them. **Revisit after W6**, when a measured cost
  distribution exists to set a bound *from* — setting one from §3's estimates is precisely what §3
  forbids.
- **ESC-I (`--json-schema <schema>` exists, unprobed): NOTED, not adopted.** AD-6's strict parse is a
  tested safety property of ours (`schema_violation` ⟹ `invocation_failed` ⟹ `verdict: error`).
  Delegating shape enforcement to the vendor CLI would move a fail-closed decision into a tool whose
  behaviour on violation nobody has observed. It may later be added as an **additional** belt in front of
  our parse — never as a replacement — and only after a probe establishes what the envelope looks like
  when the schema is violated. Not in W1–W5.
- **TD-F4 / W4b (`run_panel.sh` split out): ACKNOWLEDGED and correct.** AD-16's escape clause was written
  for exactly this case and `technical-design` exercised it as instructed: it split the work and added no
  bare-model escape hatch. W4b's two new agent files carry the same protected-surface, human-gated,
  ship-set obligations as §9.5's, and **W4b must not land before W4a**, so the pattern is established once.
  Non-goal 3 is untouched — the panel's cross-vendor decorrelation property is unchanged.
- **ESC-F, ESC-G, ESC-K:** addressed to the orchestrating session, not to me; the worker is filing issues.
  I add nothing beyond noting that ESC-G's protection asymmetry is the reason ESC-E's constraint above is
  binding rather than advisory.

### 9.7 What the technical design must correct — and what a reviewer reviews against in the meantime

The technical design is **not** rewritten by this amendment; it needs a targeted correction pass on the
clauses below. **This does not block W1.**

| Technical-design clause | What changes | Needed before |
|---|---|---|
| §3.7 C4 | `terminal_reason` required present; new detail `terminal_reason_missing` (§9.2) | W1 |
| §3.7 C6 | ratified; add the explicit value rules — key-universal, int-not-bool, `null` blocks, flat mapping only (§9.1) | W1 |
| §3.7 `outcome_detail` precedence list | insert `terminal_reason_missing` at rule 4's position, replacing rule 4's absent case | W1 |
| §3.7 "Unknown envelope fields" paragraph | *"Interim implementable contract, pending the architect's ruling"* → **ruled and binding** (§9.2); add the `cli_version` and `envelope_unknown_fields[]` obligations | W1 |
| §3.4 P7 | ratified; *"which cron callers should pass"* → **MUST**, for every non-interactive caller (§9.3) | W1 |
| §4.2 field contract | add `invocation.cli_version`; confirm `invocation.envelope_unknown_fields[]` | W2 |
| §5.2 audit record | add `envelope_unknown_fields` and `cli_version` | W3 |
| §6.1 | the agent is `self-reviewer`; TD-O1 closed by §9.5; add the W4a dependency | W4 |
| §6.3, §9.4, §11 | drop `validate_agents.sh`'s `run_capped` deletion from W4 (§9.4) | W4 |
| §9.1 test table | T1.24 stands; **add T1.9b, T1.13b, T1.15b, T1.15c, T1.24b** | W1 |
| W6's reported outputs (AD-13) | add *"count of `terminal_reason_missing` observed"* (§9.2's residual) | W6 |

**Review standard while the correction pass is outstanding.** For the clauses named above, **this
amendment is the standard**. `code-reviewer` reviews W1's classifier against §9.1 and §9.2, **not**
against the superseded rows in TD §3.7, and must not record a deviation finding against an
implementation that follows this amendment. `technical-design`'s correction pass may run in parallel with
W1; it **must** complete before W4 begins, because §9.4 and §9.5 change W4's *scope*, not merely its
wording.

### 9.8 Startup-gap analysis and affected sign-offs

*"Should this have been settled in the initial architecture review, before design was built against it?"*
— asked of each ruling, per the CORE startup-gap rule.

- **ESC-A and ESC-B — yes, and the gap is mine.** §0's own "Verification gaps I could not close" names
  *"Whether `subagent_stats.refused` is present on the envelope in this CLI version"* — and AD-4 then
  bound a comparison against that field anyway, with a note claiming *"AD-4's classifier is written so
  that its absence is harmless"*, which covered **absence** and said nothing about **shape**. I bound a
  fail-closed classifier against an unprobed external tool's output contract. A 90-second probe, or the
  bundle grep in §9.0, was available the entire time.
- **ESC-C — yes, at the requirements stage.** REQ-A4 asserted a pre-invocation auth check without
  establishing that authentication state is observable pre-invocation.
- **ESC-D and ESC-J — yes, at this ADR's own AD-5.3 and AD-16.** One asserted a consequence of a
  migration that does not exist; the other assumed a named agent that does not exist.

**A `startup-artifact-gap` issue should be opened** (the worker files it) carrying all four, and the
generalisable rule they share: **no fail-closed classifier may be bound against an external tool's output
contract that has not been probed, or read out of the shipped artifact, in the same pass.** That rule
extends past this ADR and belongs with #1359's *"a control must be executed, not narrated"* in #1243's
core-principles register.

**Affected sign-offs:**
- **Stand, unaffected:** every sign-off on PR #1651 (requirements) except REQ-A4's, and every sign-off on
  PR #1658 (technical design) except the sections in §9.7. Nothing in AD-1, AD-2, AD-6 through AD-15 is
  touched by this amendment.
- **Flagged for re-review — orphaned approvals until the §9.7 pass lands:** the #1658 sign-offs covering
  TD §3.4, §3.7, §6.1, §6.3, §9.1, §9.4 and §11. Those sections were approved against ADR rows this
  amendment supersedes. They must not be cited as current for those sections, and the correction pass's
  own review is what re-establishes them.
- **Flagged for amendment, not re-review:** REQ-A4 in PR #1651 (§9.3).
- **No code sign-off is orphaned, because no code exists.** W1 is unstarted. This is the last moment at
  which every one of these corrections is free, which is the only good news in this section.

### 9.9 What happens next

1. **`coder` starts W1** against §9.1, §9.2 and TD §3.1–§3.9 as corrected by §9.7. **W1 is blocked by
   nothing in this amendment.**
2. `technical-design` runs the §9.7 correction pass. It must complete before W4 starts.
3. The worker files: the `startup-artifact-gap` issue (§9.8); the `validate_agents.sh` `run_capped`
   follow-up (§9.4); the REQ-A4 amendment routed to `pm-agent` (§9.3); and **W4a**, the `self-reviewer`
   agent file plus its ship-set registration (§9.5). ESC-F, ESC-G and ESC-K are already the worker's.
4. **Nothing in this amendment touches ESC-1 through ESC-4.** They remain held for the human, and W1–W6
   remain cleared to proceed without them.

---

## Human Review Required

**Amendment 1 (§9) adds no new item held for the human.** Its five rulings are technical calls inside my
authority; the one item with a product consequence — a larger shipped agent roster (§9.5, plus W4b's two)
— is flagged in §9.5 and is controlled by the existing protected-surface gate rather than by a new one.
The four items below are unchanged.

Four items, all from §6, none of which I may bind: **ESC-1** (Q2's rerun does not fit a cycle — accept
AD-13's multi-cycle latency and cost?), **ESC-2** (a new top-level cron execution stage), **ESC-3** (is
`input_digest` reuse inside "unconditionally"? — ESC-1's numbers depend on it), **ESC-4** (twelve
never-executed dimensions become blocking at once — observation window first, or straight to enforcing?).
Slices **W1–W6 are cleared to proceed** without any of these answers, and W6 produces the measurement
ESC-1 actually needs.

**RISK: HIGH.** This design makes twelve review dimensions that have never executed into hard merge
blockers, adds a new class of script-launched model process, adds a new protected-surface configuration
file family, and changes the signature of the single highest-stakes decision function in HOS. The failure
mode of getting it wrong is not "reviews are noisy" — it is either a stalled merge queue (Q1's hard block
firing on a misconfiguration) or, far worse, a mechanism that looks like it is reviewing and is not,
which is the exact condition §0 found in four separate places already (SKIP-as-exit-0, AF-8;
empty-manifest-as-satisfied, AF-5; prose-as-routing, AF-6; caller-supplied-verdict, VF-4/AF-4). Four
specific routes to the latter are closed positively rather than cautioned about: fail-closed is an
allowlist over the envelope with `subtype` never read (AD-4); applicability is decided by code and
recorded explicitly, so absence is never silence (AD-6, AD-13); entries cannot be configured out of
existence (AD-9); and "no results" is unrepresentable at the merge-decision call site, in Python, at the
signature level (AD-15).

**CONFIDENCE: HIGH** on §0 — every finding was re-derived against `4f973c43` this session, including the
four that correct or sharpen pm-agent (**AF-1** finds the bash/Python question already answered by
#1641's landed tiering; **AF-3** finds REQ-A5's prescribed helper unable to do the job it is prescribed
for; **AF-5** finds the register gate structurally unable to bounce in this repo at all; **AF-7** finds
the schema I was told to extend is two readers, not one). **HIGH** on AD-1 through AD-11 and AD-16, which
follow from those findings and from rulings already made. **HIGH** on AD-12's answer to the
one-runner question — the divergence table is derived from the Q4+Q6 ruling's own shape, not from taste.
**MEDIUM-HIGH** on AD-13 and AD-14: the resumable-sweep and PR-comment-envelope shapes are sound and
reuse proven mechanisms, but neither has been built here and AD-14's comment-volume question is
genuinely open. **MEDIUM** on AD-9's install-time mechanics — AF-9 shows packs have never contributed
data, only prose, so the three-way merge for `contract/dimensions/` is unproven and must be verified, not
assumed. **LOW — and I want this read as a warning, not a hedge — on every wall-clock number in §3.**
No `claude --agent` invocation has ever run in this repository. W6 exists to replace those numbers with
measurements before anything depends on them, and `technical-design` must not calibrate a budget from
them.

**BLAST RADIUS:** every PR's merge path (AD-15); `bin/hos-cron`'s overseer role (AD-13, ESC-2);
`.claude/agents/overseer.md`'s entire review chain; `contract/**` gains a new protected-surface file
family; `scripts/framework/run_post_change_sweep.sh`, `validate_self.sh`, `validate_scripts.sh`,
`scripts/run_panel.sh`, `scripts/oversight/run_with_retry.sh`; `scripts/automation/lib/merge_authority.py`
and its 157 tests; the installer's pack path; and the subscription quota, which this design will consume
materially more of.

**Change classification: STRUCTURAL.** New gating decision points, a new class of script-launched model
process, a new configuration surface with its own ownership rules, and a change to what "this PR was
reviewed" means. Per the product-boundary checkpoint, ESC-1 (cost model + user-visible latency), ESC-2
(deployment topology + operational obligation), ESC-3 (interpretation of a human ruling that ESC-1's
numbers depend on) and ESC-4 (throughput) must be cleared by the human before the corresponding slices
bind. W1–W6 are unaffected by all four, which is why they are ordered first.

---

## 10. Amendment 2 — the launch/logic boundary in L3, and the interpreter ladder (2026-09-16)

**Trigger.** PR #1720 (W1) was bounced with CI `tests` red: `bootstrap/invoke_agent.sh` ends with
`exec python3 …` (a bare PATH lookup) and `agent_invoke_cli.py:61` does `import yaml`, which the
`actions/setup-python` 3.12 interpreter does not carry. `technical-design` returned **Amendment A**
(TD-D22, TD-D23) and routed the *interpretation of AD-1's prohibition* to me, because I own that text.
This amendment rules on it. **Where §10 and §2 differ, §10 governs; where §10 and the technical design
differ, §10 governs.**

**Scope.** Four rulings, all inside my authority, none with a product consequence: no user-visible
behaviour, cost, topology, retention or operational obligation changes — the primitive is not yet reached
by any caller (TD-VF-6: `scripts/automation/**` and `bootstrap/invoke_agent.sh` are not in the consumer
ship-set). No product-boundary checkpoint is required and none is claimed as cleared.

### 10.0 What I verified myself this pass

- `bootstrap/invoke_agent.sh:56-61` at `60360661` — the `command -v python3` guard and the bare
  `exec python3` are both present, exactly as described.
- `scripts/automation/agent_invoke_cli.py:61` — `import yaml` at module scope, after the `sys.path`
  bootstrap, guarded by nothing.
- `bootstrap/merge_authority.sh:135` — the precedent AD-1 copies **also** execs a bare `python3`. It gets
  away with it because `merge_authority_cli.py` imports **stdlib only** (`argparse`, `importlib.util`,
  `json`, `re`, `sys`, `dataclasses`, `datetime`, `pathlib`, `typing`) plus first-party
  `scripts.automation.lib`. **AF-1's "copy #1641's tiering verbatim" therefore copied a launch line whose
  safety was a property of the *other* module's import list, not of the pattern.** That is the actual
  root cause of #1720 and it is mine, not the coder's (§10.5).
- The two-rung venv/PATH ladder is this repo's established idiom, at source:
  `scripts/oversight/run_gates.sh:35-44` (`-x .venv/bin/python` → `command -v python3` → exit 1) and
  `scripts/prompt_audit.sh:22-27`.
- An **environment interpreter override is also established idiom here**, in four places:
  `scripts/oversight/gates/secret_scan.sh:95` and `gates/check_suspension.sh:31` (`OVERSIGHT_PYTHON`),
  `gates/django_check.sh:36` (`DJANGO_PYTHON`), `gates/collection_integrity.sh:74`
  (`COLLECTION_PYTHON`). `INVOKE_AGENT_PYTHON` is not a novel mechanism on this repo's surfaces.
- `.github/workflows/tests.yml:67` runs `ensure_venv.sh` and installs no PyYAML into the `setup-python`
  environment — so TD's T1.55 fence describes the current state, not a change.

### 10.1 Ruling 1 — TD-D22's ladder is OUTSIDE AD-1's prohibition. `technical-design`'s reading is CONFIRMED. (Amends AD-1.)

Confirmed, and not narrowly: the reading is correct on AD-1's wording *and* on what AD-1 exists to
protect.

- **On the wording.** Clause 1 forbids *"a JSON literal, a `printf`/`echo` to stdout, or any
  re-derivation of a field."* Interpreter resolution emits no field and writes nothing to stdout. Clause 2
  forbids *"a `case` statement, a flag of its own, or any validation/default/re-derivation of a
  caller-supplied flag."* The ladder never reads `$@`. Neither clause is engaged.
- **On the purpose, which matters more than the wording.** AD-1's prohibition exists so that **L3 never
  becomes a second source of truth about the result document or the flag contract** — the two things a
  consumer parses. An `if [[ -x … ]]` over an interpreter path is not a second source of truth about
  anything a consumer reads; it is the act of starting L2 at all.
- **On precedent inside this very design.** §3.9 step 2 has contained an interpreter `if` since the
  original technical design, it shipped in `60360661`, and no review treated it as an AD-1 violation.
  TD-D22 changes *which* interpreter is chosen, not the category of thing L3 does.
- **On structural necessity.** L2 cannot make this choice: by the time L2 executes, the interpreter is
  already fixed. A prohibition read to forbid the ladder would forbid the choice from being made
  anywhere, which is not a reading of AD-1 — it is a defect.
- **On #314.** *"Prefer Python for logic, shell for launch"* is the policy AD-1 cites to justify the
  L2/L3 split at all. Choosing the interpreter is the launch half by definition.

**AD-1a (NEW, BINDING — the launch/logic boundary, stated so it is not re-litigated).** L3 may contain
**only** logic whose inputs are (a) its own location on disk and (b) the host's ability to start L2, and
whose outputs are **only** the `exec`, or a non-zero exit with one stderr line. Concretely, L3 may:
resolve its own directory and the repo root; select an interpreter; and fail with one stderr line when it
cannot. L3 may **not**, ever: read or branch on any element of `$@`; write to stdout; emit or compose
JSON; re-derive, default, or validate any flag or field; add a flag of its own; grow a `case` statement;
mint or revoke a token; or mutate its environment (no `pip install`, no venv build or repair —
`ensure_venv.sh` is *named* in an error message and never *invoked*).

The test for any future addition to L3 is a single question: **does this read the caller's arguments, or
produce a value a consumer parses?** If either, it belongs in L2. If neither, and it is required to start
L2 at all, it is launch and it may live in L3. **The ladder is the maximum L3 grows under this ADR** —
three rungs over interpreter paths plus two error lines, ~40 lines total. TD-D22's own warning is
adopted verbatim as binding: *"it is only launch logic" is exactly how a wrapper that must not grow,
grows.*

**One consequence I bind explicitly, because AF-1 got it wrong (§10.0):** a bare `exec python3` is
acceptable in an L3 wrapper **only** when its L2 module imports nothing outside the standard library and
first-party `scripts.*`. `merge_authority.sh` satisfies that today; `invoke_agent.sh` does not and never
did. A future L3 copying either shape must check the L2 import list, not the wrapper.

### 10.2 Ruling 2 — I am NOT taking the fallback.

Plainly: **the pre-stated fallback (rung 2 alone behind an `-x` guard) is rejected.** Build TD-D22's
three-rung ladder as specified. Rung 3 is load-bearing — it is what makes the consumer-host contract and
CI exercise the *unfit-interpreter* path rather than route around it, and dropping it would delete the
only place in the system where P0 is proven to fire (T1.52, T1.55). Rung 1's fate is ruled in §10.3.

### 10.3 Ruling 3 — `INVOKE_AGENT_PYTHON` is ACCEPTED on this surface, under four binding conditions. (Amends AD-1, AD-6.)

The architecture question posed is the right one: does the deterministic-invocation guarantee require the
interpreter to be a pure function of repo state? **No — and it never did.** What ADR-1643 guarantees is
*what* is invoked (AD-3: a shipped, named, CODEOWNERS-protected agent file, verified present and
name-matching before launch), *how* it is invoked (AD-1/AD-7: fixed argv, a named posture, no
`bypassPermissions`, no inline agents), and *how the result is classified* (AD-4: a closed allowlist over
the envelope; AD-6: strict schema, `invocation_failed ⟹ verdict: error`). Not one of those reads the
interpreter. Determinism here is a property of the **record**, not of the launch path.

What makes the varying launch path safe is **TD-D23's P0**, not trust: an interpreter unfit to run L2
produces exit 1, empty stdout, no document, one stderr line — so the ladder's only reachable outcomes are
"a correct document" or "no document and a loud failure". There is no interpreter that yields a
plausible-but-wrong record. That is the architectural condition, and it is why §10.2 keeps rung 3 as well
as §10.3 keeping rung 1. **If P0 is ever weakened, rungs 1 and 3 both lose their justification and this
ruling is void.**

Four conditions, all binding:

1. **A dedicated variable name — `INVOKE_AGENT_PYTHON`, and specifically NOT `OVERSIGHT_PYTHON`.** The
   repo already exports `OVERSIGHT_PYTHON` as a general gate-layer override (§10.0). Reusing it would let
   an environment set for an unrelated gate silently redirect the interpreter of every future AI review —
   the exact class of coupling this design exists to eliminate. One variable, one surface.
2. **L2 must never read it.** `agent_invoke_cli.py` contains no reference to `INVOKE_AGENT_PYTHON`, for
   any purpose, including diagnostics. Its only consumer is L3 rung 1. Pin with a source test alongside
   T1.53.
3. **No committed non-interactive caller may set it.** It is a human/diagnostic/test seam only: it must
   not appear in `bin/hos-cron`, the sweep runner (W6), any committed script, any workflow, any posture
   file's environment passthrough, or any installed consumer artifact. The only permitted committed use
   is inside the test suite. **Pin this mechanically with a source test** (repo-wide grep: the only hits
   outside `tests/` are `bootstrap/invoke_agent.sh` and documentation). This is what keeps `technical-
   design`'s reachability argument true *over time* rather than true on the day it was written — the
   argument that an `VAR=… bash bootstrap/invoke_agent.sh …` string does not match
   `Bash(bash bootstrap/invoke_agent.sh *)` is correct, and it is a statement about today's callers, which
   a test is what preserves.
4. **The interpreter becomes an auditable field of the result document.** AD-6's `invocation` block gains
   **`interpreter`** (`sys.executable`) and **`interpreter_version`** (`platform.python_version()`),
   recorded beside `cli_version` and for the same reason. **No decision may read either** (AD-8). This is
   the price of a ladder on a governance surface: if which interpreter ran can vary by host, every record
   must say which one ran. TD §4.2 and §5.2 (the audit record) both take these two fields.

I do **not** pre-empt `security-reviewer`, and this ruling is not a security clearance. It is the
architecture judgment that the mechanism is admissible on this surface *given conditions 1–4*. If
`security-reviewer` finds a reachable path by which an unattended committed caller can set the variable,
condition 3 has failed, rung 1 is removed, and T1.52 must find another seam (a temporary tree, or
invoking `agent_invoke_cli.py` directly under the unfit interpreter) — that is a mechanical consequence,
not a new ruling.

### 10.4 Ruling 4 — AD-1's text and the wrapper header ARE amended. Both are written here.

Yes. Re-litigating a prohibition at the point of first contact with a real dependency is the failure this
amendment closes; the boundary goes in the text.

**AD-1's L3 bullet (§2) is amended to read** — this supersedes the corresponding bullet above:

> - **L3 — `bootstrap/invoke_agent.sh`.** Fixed argv over a closed flag set, no JSON literal, no
>   re-derivation of any field, stdout and exit code passed through byte-for-byte. Mints **no** token
>   (this surface performs no GitHub I/O). **It resolves the interpreter that runs L2 — that is launch,
>   not logic, and it is inside this ADR (AD-1a, §10.1). It may contain no other logic.** Earns the
>   CLAUDE.md canonical-entry-point row REQ-A1 requires.

**`bootstrap/invoke_agent.sh`'s header paragraph is replaced with the following text, verbatim** (the
coder writes exactly this; it is governance text, not implementation detail):

> ```
> # BOUNDARY (ADR-1643 AD-1 + AD-1a, §10.1). This script may contain only
> # logic whose inputs are its own location on disk and the host's ability to
> # start agent_invoke_cli.py, and whose outputs are only the exec or a
> # non-zero exit with one stderr line. Concretely it MAY: resolve its own
> # directory and the repo root; select the interpreter (the three-rung
> # ladder below); fail with one stderr line when it cannot. It must NEVER:
> # read or branch on any element of "$@"; write to stdout; compose or emit
> # JSON or re-derive any field (the record schema is agent_invoke_cli.py's
> # alone — adding a document field is a change to that module, never to this
> # one); validate or default a caller-supplied flag; add a flag of its own;
> # grow a `case` statement; mint or revoke a token; or mutate its
> # environment (no pip install, no venv build or repair — ensure_venv.sh is
> # named in the error message and never invoked here).
> #
> # The test for any proposed addition: does it read the caller's arguments,
> # or produce a value a consumer parses? If either, it belongs in
> # agent_invoke_cli.py. The ladder is the maximum this file grows —
> # "it is only launch logic" is how a wrapper that must not grow, grows.
> #
> # INVOKE_AGENT_PYTHON is a diagnostic/test seam only (ADR-1643 §10.3). It
> # is deliberately NOT the repo-wide OVERSIGHT_PYTHON; agent_invoke_cli.py
> # never reads it; and no committed non-interactive caller may set it.
> ```

**Not amended: `bootstrap/merge_authority.sh`.** Its header is #1641's and is correct for its own module
(§10.0). AD-1a is stated over *this* ADR's L3. Generalising the boundary to every L3 wrapper in HOS is a
real follow-up — the worker files it as a docs/`AGENTS.md` item, referencing §10.1's one-question test and
§10.0's stdlib-only caveat — and it is **not** a blocker for W1.

### 10.5 TD-D23 (P0) — RATIFIED as written, with one addition.

Not asked of me, but the coder implements against it, so it is cleared here rather than left implicit.
TD-D23 follows directly from AD-1's exit vocabulary (*"1 — operational failure of the CLI itself"*) and
from AD-6's rule that a document asserts an invocation was attempted. A missing PyYAML means the #608
anti-confusion check (P4) cannot run, so the module must not emit a record claiming anything. Exit 1,
empty stdout, one stderr line naming the interpreter and `ensure_venv.sh`, no traceback — correct, and the
generalisation to *every* module-level third-party import (T1.54) is the part that stops this recurring.

**Addition:** the same rule binds every future L2 in this design family — `dimension_sweep_cli.py`
(AD-13) and `dimension_registry_cli.py` (AD-9) each take a P0 of their own the moment either acquires a
non-stdlib import, and their L3s take the ladder. `technical-design` states this once in TD §8's error
contract rather than three times.

### 10.6 Startup-gap analysis and affected sign-offs

*"Should this have been settled in the initial architecture review, before design and code were built
against it?"* — **Yes, and the gap is mine.**

AD-1 directed `technical-design` to *"copy #1641's landed tiering verbatim"* and cited AF-1's line count
as evidence of its cheapness. I did not read the one line that mattered: `merge_authority.sh:135` execs a
bare `python3`, and that is safe only because `merge_authority_cli.py` imports stdlib only (§10.0). I
copied a launch line without its precondition, onto a module I also required to parse YAML frontmatter
(P4/TD-D3 was authored *after* AD-1, which is how the two passed each other). Meanwhile the repo's own
two-rung venv idiom was sitting in `run_gates.sh` and `prompt_audit.sh`, unread by me, and the ADR's
§0 verification pass never asked "what does L2 import, and does the interpreter L3 picks have it?"

**Generalisable rule, for the same register as §9.8's** (the worker adds it to the existing
`startup-artifact-gap` issue rather than opening a second one): **a wrapper's launch line is only as
portable as its callee's import list — when an ADR mandates copying a landed pattern, it must name the
precondition that made the pattern safe, not just the pattern.** Sibling to §9.8's *"no fail-closed
classifier may be bound against an unprobed external contract."*

**Affected sign-offs — explicit:**

- **Stand, unaffected:** every requirements sign-off on PR #1651; every technical-design sign-off on
  PR #1658 *except* the sections named below and in §9.7; every sign-off touching AD-2 through AD-16,
  which this amendment does not alter.
- **ORPHANED — must be re-reviewed against §10, not merely re-run:** the W1 code sign-offs on **PR #1720**
  covering `bootstrap/invoke_agent.sh` and `agent_invoke_cli.py`'s module-import block and `main()`
  entry. They were recorded against a wrapper whose launch contract this amendment changes and against an
  L2 with no P0. Any approval of those two surfaces on #1720 is **not current** and must not be cited as
  such. The rest of #1720's approvals (the classifier, posture loading, argv construction, the document
  writer) stand — §10 does not touch them. `code-reviewer` re-reviews the two named surfaces against
  §10.1, §10.3, §10.4 and TD-D23; `security-reviewer` reviews §10.3's condition 3 as a first-class item.
- **Flagged for amendment, not re-review:** TD §4.2 and §5.2 (add `invocation.interpreter` and
  `interpreter_version`, §10.3 condition 4); TD §8 (the P0 generalisation, §10.5); TD §3.9 (delete
  *"pending the architect's ruling"* — it is ruled).
- **Test-suite consequence, stated so it is not discovered late:** TD's T1.50 *reverses* an existing
  passing test's expectation. A reversed expectation is the one change a re-run cannot catch, so it is
  re-read, not re-run, and the reviewer records that it was re-read.

### 10.7 What the coder builds, immediately and without further escalation

1. TD-D22's **three-rung ladder** in `bootstrap/invoke_agent.sh`, exactly as §3.9 specifies, plus §10.4's
   header text verbatim. Rung 1 is `INVOKE_AGENT_PYTHON`, not `OVERSIGHT_PYTHON`.
2. TD-D23's **P0** in `agent_invoke_cli.py`, exactly as §3.4 specifies — guarded import, sentinel,
   `main()`'s first statement, exit 1, one stderr line, no traceback, nothing on stdout.
3. `invocation.interpreter` and `invocation.interpreter_version` in the result document and in the
   per-invocation audit record (§10.3 condition 4).
4. The **two source tests** §10.3 requires: L2 never references `INVOKE_AGENT_PYTHON` (condition 2), and
   no committed non-test caller sets it (condition 3) — alongside T1.50–T1.56.
5. `.github/workflows/tests.yml` stays untouched (T1.55). Do not fix CI by installing PyYAML into the
   `setup-python` environment; that would make the defective path green and delete the fence.

**Nothing in §10 is escalated to the human, and nothing in §10 blocks W1.** ESC-1 through ESC-4 are
unchanged and still held.
