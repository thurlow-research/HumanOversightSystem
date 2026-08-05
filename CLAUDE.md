# HumanOversightSystem — CLAUDE.md

This repo is the canonical home of the Human Oversight System (HOS): a portable framework for scaling human oversight of AI-generated code. Read this before any task.

---

## What this repo is

The HOS is simultaneously:
1. A **deployable framework** — install it into any project with `./bootstrap/hos_install.sh` (from a validated release)
2. A **contract specification** — defines what any compliant agent team must produce
3. A **research instrument** — empirical substrate for studying AI code oversight at scale

It is not dissertation work itself; that lives in `../VibeOversightDissertation`. The two repos are siblings. This repo owns the framework; the dissertation repo owns the research.

---

## Repo layout

```
AGENTS.md              Layer 1 self-flagging protocol (stable governance doc)
DECISIONS.md           Design decision log — the history of the system
METHODOLOGY.md         End-to-end pipeline explainer
contract/
  OVERSIGHT-CONTRACT.md  What any compliant agent team must produce
  step-manifest.template.yaml  Project config template
bootstrap/             The copy-to-machine bundle (the only thing you copy to a machine):
  hos_bootstrap.sh       MACHINE setup: Python/ScanCode/gh/pip; delegates to setup_clis.sh
  hos_install.sh         PROJECT install: fetches a validated RELEASE and scaffolds it into
                         a target repo (--release <tag> / --local). No sudo. Records
                         the installed tag at the target's .hos-release.
  setup_clis.sh          MACHINE bootstrap of agent CLIs (Node + claude/codex/agy + auth)
.claude/agents/        All shipped agents: 8 oversight layer agents (evaluator, orchestrator,
                       risk-assessor, etc.) + 16-agent base team (pm-agent, architect,
                       technical-design, coder, 8 reviewers, unit-test, system-test,
                       ops-designer, ux-designer). Each agent file is layered:
                       CORE (HOS-owned generic) / PACK:<name> (HOS-owned stack depth) /
                       PROJECT (consumer-owned). Region order is CORE → PACK → PROJECT.
packs/                 Stack-depth region bodies (body-only, no full agent files):
  <name>/              One directory per pack (e.g. packs/django/).
    <agent>.md         PACK:<name> region bodies for the agents that pack deepens.
    pack.toml          Pack metadata (name, version, supported agents).
scripts/
  run_panel.sh           Outer loop: post-PR cross-vendor panel (reads panel-context.md only)
  run_second_review.sh   Transition: pre-PR cross-vendor second review (machine-readable verdict)
  run_red_team.sh        Checkpoint: system-level adversarial red-team
  review_self.sh         Self-review: sends HOS to agy or codex (--reviewer flag)
  reverify_self.sh       Targeted re-review of fixes against original findings
  capture_prompt.sh      Prompt artifact capture
  prompt_audit.sh        Prompt provenance audit
  oversight/
    validators/          Risk scoring scripts (Python, deterministic):
      rn_calculator.py     Dai et al. Risk Number (nesting calibrated from bug data)
      complexity_metrics.py  Cyclomatic complexity (radon)
      function_metrics.py    Function length, param count, return paths
      n1_detector.py         Django N+1 query heuristic
      migration_scorer.py    Database migration risk classification
      static_analysis.py     bandit MEDIUM findings as scored risk signal
      diff_size.py           Change-size signal (review difficulty / blast radius); tier floor
      portability_check.py   Stack-specific portability signals (hardcoded paths, env assumptions)
      ip_check.py            IP/provenance: license gate (ScanCode) + prompt clean-room
                             + regurgitation stub (ai-gen-code-search, Level 3)
      prompt_audit_risk.py   Prompt ambiguity + fidelity surface scoring
      hallucination_surface.py  Version-sensitive API detection
      issue_query.py         Historical bug density from GitHub issues + git churn
      schema.py              Shared output schema, weights, tier thresholds (infra, not a dimension)
      regions.py             Shared region/parsing helpers (infra, not a dimension)
      brownfield.py          Brownfield scoring — present but NOT yet wired into run_validators.sh
    gates/               Blocking pre-review checks (bash)
    run_validators.sh    Orchestrate all validators (fail-closed CRITICAL if all fail)
    token_tracker.py     External CLI token usage tracking + subscription impact report
    requirements.txt     Python dependencies (ScanCode optional but recommended)
audit/                 Committed audit trail (oversight-log.jsonl + timestamped .md files)
contract/
  OVERSIGHT-CONTRACT.md       What any compliant agent team must produce
  step-manifest.template.yaml Project config template (includes UI/a11y + infra examples)
templates/
  base-agent-register-examples.md  Complete register entry examples for all 6 roles
```

---

## The two bootstraps

Both live in `bootstrap/` — the copy-to-machine bundle. Everything else is fetched from a release.

**Machine bootstrap** (`./bootstrap/hos_bootstrap.sh`): installs the machine prerequisites (Python 3.10+, ScanCode, gh, pip analysis packages) and — via `bootstrap/setup_clis.sh` — the agent CLIs (claude, codex, agy) + Node runtime. May need sudo. Run once per machine.

**Project install** (`./bootstrap/hos_install.sh [<path>]`): installs the full agent pipeline — AGENTS.md, all 26 shipped agents (oversight layer + base team), scripts, contract, PR template — into a target project. By default it installs from a **fetched, validated release** (not the local working copy); use `--release <tag>` to pin a version or `--local` for a dev install. Pass `--pack <name>` (e.g. `--pack django`) to inject stack-depth PACK regions into the relevant agents; `--no-pack` to install bare CORE only. The installed pack is recorded in `config.sh` as `PACK=` and re-applied on upgrades. No sudo — it checks prerequisites and points back to `hos_bootstrap.sh` if any are missing. Records the installed tag at the target's `.hos-release`. Run once per project (and on release bumps). On an interactive install it delegates project configuration to `scripts/framework/install.sh` (the `config.sh` generator), so one run produces a fully-configured project (#87). The install performs a **three-way region merge**: CORE and PACK regions are always taken from HOS (hard-stop on drift unless `--squash`); PROJECT regions are preserved as-is (consumer-owned, never overwritten).

---

## The contract

Any agent team that wants full oversight support must implement the contract defined in `contract/OVERSIGHT-CONTRACT.md`. The contract defines:
- **Filesystem protocol**: where sign-off register, temp files, and test declarations live
- **Self-flag format**: what code-producing agents must emit (RISK/CONFIDENCE/BLAST RADIUS)
- **Sign-off schema**: what reviewing agents must write to the register on approval
- **Role mappings**: which agent fills which oversight role (code-review, security, privacy, etc.)
- **Step manifest**: project config describing each build step, risk tier, and required sign-offs

Teams using the framework's own agent templates (see `.claude/agents/`) get contract compliance automatically.

---

## Agents in this repo

`.claude/agents/` contains **26 shipped agents** in two groups — the oversight layer (10 agents) and the base development team (16 agents). As of v0.3.0 HOS ships the canonical base team; the consumer no longer hand-rolls it. The canonical agent list is `scripts/framework/consumer_agents.txt` (single source of truth for the installer + `.hos-manifest`, #225). Every agent file is layered: **CORE** (HOS-owned generic) / **PACK:\<name\>** (HOS-owned stack depth) / **PROJECT** (consumer-owned). Stack depth for a given stack lands in `packs/<name>/` as body-only region files injected during install.

### Oversight layer (10 agents — invoked by the pipeline, not the base team)

| Agent | Role | When invoked |
|---|---|---|
| `worker` | Single human entry point for building work **and** the autonomous build agent. Routes implementation/design/review to specialists — never does that work itself. Two modes: INTERACTIVE (human-driven) and AUTONOMOUS (`bin/hos-cron --role worker` picks up `needs-ai` issues, builds, opens a PR) | Interactive session start, or per cron cycle |
| `overseer` | Autonomous PR review + merge authority. Evaluates what the worker built and decides what may merge; auto-merges up to `OVERSEER_CEILING` (default `HIGH`) when checks are green, routes `CRITICAL`/protected-surface to HUMAN_REQUIRED. Never opens branches or PRs | `bin/hos-cron --role overseer` per cron cycle, or interactive PR-status queries |
| `risk-assessor` | Scores code, directs reviewers, validates risk tier. Calls `prompt_audit_risk.py` + `ip_check.py` in Phase 2; calls `prompt-fidelity` at MEDIUM+ | After coder produces code, before review chain |
| `dep-mapper` | Dependency/blast-radius analysis (generic; projects override with stack-specific version) | Subagent of risk-assessor at HIGH+ |
| `risk-historian` | Historical bug density from GitHub issues + git churn | Subagent of risk-assessor |
| `prompt-fidelity` | Semantic prompt-vs-code comparison: unexplained additions, missing specs, loose interpretations | Subagent of risk-assessor at MEDIUM+ when prompt artifact exists |
| `spec-red-team` | Adversarial spec review before coding (uses agy for independence) | Per build step, pre-coding |
| `oversight-evaluator` | Phase 1: compliance (sign-off register, §3 required fields, prompt artifacts, human authorization). Phase 2: quality (convergence failures, resolved findings, confidence gaps) | After system tests pass |
| `oversight-orchestrator` | Acts on evaluator recommendation. Writes two separate files: `panel-context.md` (structural signals only, for panel) and `handoff.md` (full picture, for human/PR) | After evaluator produces recommendation |
| `post-change-sweep` | Orchestrates the full review suite after a change set — categorizes the diff, dispatches the right agents in dependency order | After any batch of changes, before commit |

### Base development team (16 agents — shipped by HOS, used by the consumer project)

| Agent | Role |
|---|---|
| `pm-agent` | Requirements and acceptance criteria |
| `architect` | Architecture decisions and ADRs |
| `technical-design` | Detailed technical design per build step |
| `coder` | Implementation (self-flags per AGENTS.md) |
| `code-reviewer` | General code quality review |
| `security-reviewer` | Security lens |
| `privacy-reviewer` | Privacy and data-handling lens |
| `reliability-reviewer` | Resilience to external-dependency failures |
| `ops-reviewer` | Telemetry-spec conformance (enforces `TELEMETRY-SPEC.md`) |
| `ui-reviewer` | UI/UX conformance review |
| `a11y-reviewer` | Accessibility review |
| `infra-reviewer` | Infrastructure and deployment review |
| `unit-test` | Unit test authoring and coverage |
| `system-test` | System/e2e test authoring |
| `ops-designer` | Observability/telemetry authority; produces `TELEMETRY-SPEC.md` |
| `ux-designer` | UX design authority; produces `UX-DESIGN-READINESS.md` |

> The framework-dev validators (`framework-validator`, `doc-validator`, `spec-compliance-validator`, `framework-setup-validator`) are **not** shipped to consumers — they belong to the planned `hos-dev-pack` (v0.3.0 dogfooding). They live in `.claude/agents/` in this source repo only.

---

## Pipeline position of each script

```
SPEC PHASE
  spec-red-team agent  →  spec-gap issues (uses agy for independence)

INNER LOOP (per build step)
  gates/*.sh           →  blocking (lint/type/secret/security-HIGH)
  run_validators.sh    →  12 signal dimensions (12 scripts, one each); fail-closed CRITICAL if all validators fail
                          includes: rn_calculator, complexity, N+1, migrations, diff_size,
                          portability_check,
                          ip_check (ScanCode license gate + prompt clean-room),
                          prompt_audit_risk (ambiguity score + fidelity surface)
  risk-assessor agent  →  composite score + inspection brief;
                          calls prompt-fidelity subagent at MEDIUM+
  [base-team review agents: code-reviewer, security-reviewer, privacy-reviewer,
   reliability-reviewer, ops-reviewer, ui-reviewer, a11y-reviewer, infra-reviewer]
  sign-off register updated (all entries must include Status/Agent/Artifact/Iterations)

TRANSITION (post inner loop, pre-PR)
  system tests
  run_second_review.sh  →  agy (MEDIUM+), codex (HIGH+); machine-readable verdict
                           header; fail-closed when agy unavailable at MEDIUM+
  oversight-evaluator   →  Phase 1: compliance; Phase 2: quality → PROCEED / CONDITIONAL / ESCALATE
  oversight-orchestrator → writes panel-context.md (structural signals only)
                           and handoff.md (full picture for human)
                           → opens PR or escalates to human

OUTER LOOP (per PR)
  run_panel.sh          →  reads panel-context.md only (no internal findings);
                           agy + codex + IP agent (ip_check.py, Level 1+2 active) + Copilot
  PR thread resolution  →  human gate
  audit/oversight-log.jsonl  ← append-only event log committed on each merge

CHECKPOINT (milestone: after steps 3, 6, 10, 11)
  run_red_team.sh       →  system-level adversarial + "not exploitable" attestations required
```

---

## Working in this repo

- When writing or editing scripts, follow the conventions in `bootstrap/setup_clis.sh` (colours, idempotency, platform detection).
- Agent files in `.claude/agents/` follow the contract in `contract/OVERSIGHT-CONTRACT.md`. CORE and PACK regions are HOS-owned — consumer project logic belongs only in PROJECT regions. Stack depth belongs in `packs/<name>/`, not in the base agent files.
- `DECISIONS.md` is append-only. New decisions go at the bottom with a date header.
- Do not commit `.claudetmp/`, `.ai-local/`, or any `.salt` files.

### Shell usage under the sandbox

This session runs inside an OS-enforced sandbox. Filesystem and network boundaries
are enforced by the kernel, so **permission prompts are not the security control —
they are friction.**

**The rule: a command can be allowlisted only if its full text is known before it
runs.** Claude Code matches the command against rules like `Bash(git *)`. If any
part is determined at runtime, no rule can match.

In an **interactive** session a human is present, so it prompts *every time*,
regardless of what is in the settings file. On **Worker and Overseer**, which run
unattended under `claude --print`, there is no one to answer an interactive
prompt, so none appears: the command is **denied outright**, the denial is
reported back to the model, and the cycle continues having silently skipped that
step. Measured 2026-08-01 (Test B, #1146): an unmatched Bash call exited 0 under
a 90s timeout, where a genuine hang would have surfaced as exit 124 — there is no
hang. The silent skip is the real failure mode to guard against, not a hang. This
is distinct from a genuine timeout — an *allowed* command that stalls on network,
a subprocess, or a lock. That is not a permission event and no permission rule
catches it; it's `HOS_CRON_MAX_SECONDS`' job (currently optional, no
`--kill-after`, no process-group kill — tracked in #1146).

**The tell (interactive sessions):** if the prompt has no "Always allow" button,
the command was unallowlistable. No configuration change fixes it — rewrite the
command.

#### What breaks allowlisting

| Pattern | Example |
|---|---|
| Command substitution | `--body "$(cat <<'EOF' … EOF)"` |
| Heredocs | `cat <<'EOF' > file` |
| Variable expansion in paths | `> "$TMPDIR/out.json"` |
| Backslash line continuations | `gh pr create \` … |
| Loops | `for r in Worker Overseer; do … done` |
| Sourcing a runtime-named file | `source /tmp/claude/hos_auth.sh` |
| Chained unrelated steps | `cmd1 && cmd2 && cmd3` |

#### What to do instead

1. **Search first, and state what you found — this is required, not optional.**
   Before writing any multi-step shell command *or* filing an issue that
   proposes new tooling, search `scripts/` (recursively), `bootstrap/`, `bin/`,
   and `scripts/automation/lib/` (Python library functions live there — grep
   `scripts/automation/lib/*.py`, not just `scripts/*.sh`) for something that
   already does it, and say what the search found (including "searched X, Y,
   Z — found nothing") before proceeding. `SCRIPTS-INDEX.md` (generated by
   `scripts/framework/gen_scripts_index.sh` — see "Canonical entry points by
   task" below) is a directory-grouped starting point, but it can lag; a live
   grep of the four locations above is the authoritative check. This is not
   hypothetical: #1213 proposed a new `bootstrap/gh_query.sh` for reads that
   `scripts/automation/lib/github.py` already implemented, retry/backoff/
   rate-limit handling included — a search would have caught it before the
   issue was filed.
2. **Use an existing script.** If `scripts/` or `bootstrap/` already does it, call
   it: `bash scripts/oversight/smoke_test.sh`
3. **If none fits, write one, then call it.** Put loops, substitutions and
   multi-step logic *inside the file*, reviewed once at commit time rather than
   approved individually at runtime.
4. **If you would write that script again next session, commit it.** A committed
   script is reviewed once and reused; a script recreated ad hoc is **unreviewed
   every time** and accumulates no capability. Rule of thumb: **the second time you
   need it, it belongs in `scripts/` or `bootstrap/` with a test**, not in
   `/tmp/claude/`. This is D41's "one invocation site" applied to tooling.
5. **Never inline logic that already exists as a script.** Token minting goes
   through `bootstrap/get_app_token.sh`, never a hand-built JWT — hand-rolling it
   produces a pipeline whose covering rules (`Bash(curl *)`, `Bash(openssl *)`,
   `Bash(source *)`) amount to arbitrary shell plus arbitrary network. To verify
   a mint succeeded, check `$?` and/or the script's own stderr confirmation line
   — never open or grep the sourced token output file; it holds a live
   installation token (#1086). Issue and PR creation go through
   `bootstrap/create_issue.sh` and `bootstrap/submit_pr.sh` (both
   `--body-file`-only, never hand-composed `gh issue create`/`gh pr create` +
   token mint + revoke) — see their headers for usage. `submit_pr.sh --app human`
   requires `--confirmed`: only pass it when a human has given explicit
   per-instance authorization for that specific push. Issue/PR comments go
   through `bootstrap/post_comment.sh --number <n> --body-file <path> --app
   <role>` (same pattern) — never `gh api --field body=@path` /
   `-f body=@path`, which silently posts the literal `@path` string instead
   of the file's contents (#1155). Issue/PR metadata edits (labels, milestone,
   title, state, assignees) go through `bootstrap/edit_issue.sh --number <n>
   --app <role> [--add-label ...] [--remove-label ...] [--milestone
   <title-prefix>|none] [--title ...] [--state open|closed] [--assignee ...]`
   — milestones are matched by **prefix**, not exact title, since this repo's
   milestone titles contain an em dash. Reads (single/multiple issues,
   milestone-scoped listings, PR-filtered, comments, assignable users) go
   through `bootstrap/query_issues.sh --app <role> (--issue <n[,n,...]> |
   --list [--milestone <prefix>|--milestone-less] [--label ...] [--state ...]
   | --comments <n> | --assignable-users)` — never hand-rolled `gh api` reads
   (#1175, #1192, #1204).
6. **Write long text to a file, then pass the path.** This is what forces heredocs.
   Use `--body-file /tmp/claude/body.md`, never `--body "$(…)"`.
7. **One command per Bash call.** No `&&`/`;` chaining of unrelated steps — each
   subcommand is evaluated independently, so one unallowlistable stage prompts for
   the whole thing.
8. **Use literal paths.** Write `/tmp/claude/out.json`, never `"$TMPDIR/out.json"`.

#### Canonical entry points by task

Short and hand-maintained — the "one invocation site" set (D41), not a full
listing. This changes rarely; for the full inventory (all ~140 scripts, with
generated one-line descriptions), see `SCRIPTS-INDEX.md` at the repo root
(regenerate with `scripts/framework/gen_scripts_index.sh`; it can lag, so
prefer a live search when in doubt — see item 1 above). Entry points already
named above (token minting, issue/PR creation, comments, metadata edits,
issue/PR reads) are not repeated here.

| Task | Entry point |
|---|---|
| Authenticated GitHub reads at the library level (retry/backoff/rate-limit handling, not a CLI wrapper) | `scripts/automation/lib/github.py` |
| Branch creation for autonomous work | `bootstrap/create_branch.sh` |
| Posting a resolvable PR review thread | `bootstrap/post_review_thread.sh` |
| Repo sync (fetch + fast-forward the default branch) | `bootstrap/hos_repo_sync.sh` |
| Dependency/environment health check | `scripts/oversight/smoke_test.sh` |
| Running the PR-required test suite | `scripts/framework/run_tests_inner_loop.sh` |
| Running blocking pre-review gates | `scripts/oversight/run_gates.sh` |
| Running risk-assessment validators | `scripts/oversight/run_validators.sh` |
| Post-change review sweep (dispatches the right review agents) | `scripts/framework/run_post_change_sweep.sh` |
| CODEOWNERS regeneration | `scripts/framework/gen_codeowners.sh` |
| Full script/module index regeneration | `scripts/framework/gen_scripts_index.sh` |

#### When a prompt does appear

This applies verbatim to interactive sessions. On Worker and Overseer there is no
prompt UI — the same three causes surface instead in the denial text reported
back to the model, with no "Always allow" button to check.

Diagnose before asking for a rule. Three causes; only one is fixed by adding rules.
**Report which one it is.**

| Prompt says | Cause | Fix |
|---|---|---|
| "Contains command_substitution / simple_expansion / backslash-escaped whitespace" | Unallowlistable command | Rewrite it |
| "Path is outside allowed working directories" | Path scope, not the command | Ask the operator to add the path |
| Plain command, has "Always allow" | Genuinely missing rule | Ask the operator to add it |

Do not ask for a broad rule to silence a prompt you could have avoided by writing
the command differently.

#### Failing safely

If something is blocked, **say so and stop.** Do not retry with
`dangerouslyDisableSandbox` (disabled by policy; attempting it prompts). Do not
route around a boundary you have concluded is misconfigured — report it. Do not
assume a read failure means a file is absent: outside allowed paths, blocked reads
surface as `No such file or directory`, **not** a permission error, so `ENOENT`
here often means *masked*, not *missing*.

A blocked operation reported plainly is useful. A boundary quietly routed around is
not.

### Submitting a PR

**Merge from the base branch, resolve conflicts, then submit.** This applies to
every PR author — the autonomous `worker` and `overseer`, and interactive
human-proxy sessions alike.

`origin/main` moves while you work. The autonomous roles run on cron, so a long
session can end with the local clone many commits behind without any signal
reaching you. A branch built on a stale base does not merely miss that work — its
PR **proposes reverting it**, and the PR looks entirely normal.

This is not hypothetical. On 2026-08-01 a branch was built while the worker was
merging PRs concurrently; `git diff --stat origin/main <branch>` showed **6,114
deletions** across four of the worker's merged PRs. It was caught by inspecting
the diff before pushing. Nothing in the tooling would have stopped it.

Before opening any PR:

1. `git fetch origin` — always, regardless of when you last synced.
2. Merge the base into your branch and resolve any conflicts.
3. **Check the diff before pushing:** `git diff --stat origin/main <branch>`.
   **Unexpected deletions are the tell** — purely additive work must show zero.
   If you see deletions in files you never touched, your base is stale; stop and
   rebuild rather than pushing.

`scripts/automation/pre_pr_stale_check.py` does **not** cover this. It detects
commits *already present* in `main` (redundant commits) and rebases them away —
a different failure. In the stale-base case the commits are unique and the *base*
is old, so that check passes clean. The two are complementary.

Mechanical enforcement in `bootstrap/submit_pr.sh` is tracked as **#1162**; until
it lands, step 3 is the only defence. Note that a periodic `git fetch` alone is
**not sufficient** — it updates refs, which makes you *aware*; it does not
integrate the base *into* an already-built branch.

<!-- HOS:HUMAN-PROXY start -->
## HOS: Human-proxy session identity

You are the **human-proxy orchestrator** for this project, running in the Human
clone at `/home/scott/Code/HumanOversightSystem/Human`. You authenticate as the
Human GitHub App bot: `scottthurlow-claude[bot]`.

**Session start (`bin/hos-human` handles this automatically):**
1. Preflight: `bootstrap/validate_setup.sh --repo .`
2. Auth: `get_app_token.sh --app human` via temp-file source — never `source <(...)`
3. Identity guard: abort if `HOS_BOT_LOGIN != HOS_EXPECTED_BOT_LOGIN` (both exported by `get_app_token.sh`)
4. Sync: `bootstrap/hos_repo_sync.sh` (best-effort; a sync failure does not block the session, but a residual behind-count is always reported loudly on stderr, with the cause classified structural — e.g. sandbox write-protection, will not resolve by retrying — or transient/benign — e.g. network, dirty tree, retry next session; #1200)
5. Orient: read `.claudetmp/HANDOFF.md` before acting

**This is not an autonomous role.** `bin/hos-cron --role human` is rejected. Do
not wire this session into cron.

**Human-approval gate:** `scottthurlow-claude[bot]` is listed in `BOT_ACCOUNTS`
and is excluded from the human-approval gate. Approvals from this bot identity do
NOT count as human approval. Do not remove it from `BOT_ACCOUNTS`.
<!-- HOS:HUMAN-PROXY end -->
