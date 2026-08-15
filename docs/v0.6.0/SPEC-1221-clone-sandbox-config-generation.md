# SPEC-1221 — Generate a clone's sandbox config from the in-repo template

**Status:** DRAFT for architect. **Date:** 2026-08-04. **Author:** pm-agent. **Issue:** #1221 (v0.6.0, `needs-ai`, `priority:high`).
**Consumers:** `architect` (next), then `technical-design`.
**Change class:** **additive** — this specifies behavior #1221 already required but left unwritten. Two items are **structural** and are therefore *deferred, not decided* (§7).
**Scope note:** WHAT and WHY only. No file layout beyond the one entry point, no language choice, no function signatures — those are architect's and technical-design's.

RISK: MEDIUM — the artifact under generation is a security boundary. A wrong generated policy fails in two directions: over-blocking (session friction, visible) or under-blocking (a control silently absent, invisible — the exact failure `docs/SANDBOX-POLICY.md` §1 exists to end).
CONFIDENCE: HIGH on scope and sequencing; MEDIUM on permission-glob matching semantics (unverified — see §5, and `docs/SANDBOX-POLICY.md` §4 item 7). The §5 resolutions are chosen to be *safe under that uncertainty* rather than to depend on resolving it.
BLAST RADIUS: the Human clone's live sandbox config; nothing else at runtime. No consumer project is affected.

---

## 1. Problem and goal

`contract/sandbox-policy.template.json` (#1185) is a path-templated copy of the Human role's proven sandbox/permission profile. Nothing reads it. The live `Human/.claude/settings.local.json` is still hand-edited, gitignored, and machine-specific, so the policy is unreviewable, unreproducible, and unverifiable — and today the *gap between them is undetectable*.

**Goal:** one command turns the tracked template into a clone's live policy, and one command tells you whether a clone's live policy still matches the template. After this, "installed" is a maintained property, not a one-time event.

**Not the goal:** applying any policy to `worker` or `overseer` (#1146), any `bin/` migration (#1202), or any consumer-project behavior.

## 2. Which installer — resolved

**Neither.** The generator is a new standalone entry point under `scripts/framework/` (working name `gen_sandbox_config`), invoked explicitly per clone.

- `bootstrap/hos_install.sh` is the **consumer-project** installer. Its existing `.claude/settings.json` handling merges consumer *agent-tool* permissions — a different mechanism, a different file's meaning, and a different audience. The three HOS dogfooding clones are not consumer projects. Folding this in would couple a consumer feature to HOS's own operational layout.
- `bootstrap/hos_setup_partner.sh` is **one-time, per-project, run from the parent directory**, and it has no notion of a Human clone at all (`--worker-*`/`--overseer-*` only). A config that must be *re-generated on every template change* cannot live in a one-shot setup path — that reproduces the "one-time event" failure #1221 §3 names.
- `scripts/framework/` is where this repo already puts tracked-source → live-artifact generators and their currency checks (`gen_codeowners.sh`, `check_validation_current.sh`). It is also already a protected surface (`scripts/framework/**`, `contract/**` in `protected_surfaces.txt`), so this PR is HUMAN_REQUIRED by construction — correct for a security-boundary change, and requires no new protected-surface entry.

**FR-1.** A single entry point performs both generation and checking. Modes: generate (write) and `--check` (compare, write nothing).
**FR-2.** Role and target clone are **explicit required inputs**. No inference from directory name or cwd. A generator that guesses which role it is configuring is a generator that can hand `worker`'s clone `human`'s policy.
**FR-3.** Wiring the generator into any setup script is **out of scope for this PR** (see FR-2's rationale and §2 above); it is a follow-on once >1 role is generatable.

## 3. Per-role parameterization — the narrowest correct answer

The template encodes exactly one role's *rule set*: Human's, in which Human is a read-only observer of the other two (`Read(__HOS_ROOT__/Worker/**)` allowed, `Edit(__HOS_ROOT__/Worker/**)` **denied**). Generating `worker`'s config from it unchanged would deny the worker write access to its own clone — obviously wrong, and wrong *silently*, presenting as unexplained tool failures. `docs/SANDBOX-POLICY.md` §4 item 1 records the per-role matrix as unresolved, and resolving it is #1146.

Therefore, for this PR, "per-role" means **role-driven placeholder substitution only**:

**FR-4.** The role selects the values substituted for `__ROLE__`, `__PROJECT_ROOT__`, `__HANDOFF_DIR__`, `__CLAUDE_PROJECT_STATE__` (and the machine-wide `__HOS_ROOT__`, `__CONFIG_DIR__`, `__HOME__`). No role-conditional rule content.
**FR-5.** `--role human` generates. **`--role worker` and `--role overseer` MUST fail closed** with an error naming #1146 as the blocker. This *is* "per-role differences explicit rather than implied": the difference is declared and enforced rather than silently inherited from a profile that does not describe those roles.
**FR-6.** Any `__NAME__` surviving substitution is a hard failure; no partially-substituted file is ever written (`docs/SANDBOX-POLICY.md` §4 item 6, #1114). `--check` likewise fails if the live file contains any `__`.
**FR-7.** The generator refuses to overwrite an existing live file without an explicit force flag, and writes a timestamped backup when it does. It is overwriting a hand-tuned production security config.

## 4. Currency check — local, not CI

**Correction to a common assumption:** there is *no* CI currency check for `gen_codeowners.sh`. The real precedent is `check_validation_current.sh` + `.github/workflows/validation-check.yml`, and that works only because its inputs are tracked. Here the live file is **gitignored and machine-specific** — CI has nothing to compare against, and never will.

**FR-8.** `--check` exits non-zero on any divergence between the live file and a fresh generation, and prints the divergence (rule-level, not a raw byte diff).
**FR-9.** `bootstrap/validate_setup.sh` — already the session-start preflight — invokes `--check` and reports divergence **loudly on stderr without blocking session start**. This matches the precedent set for `hos_repo_sync.sh` (#1200: a failure does not block the session, but the residual is always reported loudly). Promoting it to blocking is E-2 (§7).
**FR-10.** No CI workflow, for the reason above. Not a deferral — it is not achievable.

## 5. The two genuine deltas — resolved

Both are resolved by one principle, applied asymmetrically because the two lists are not symmetric in risk:

> **`permissions.deny`: take the union of the live and template spellings. `permissions.allow`: take the template only.**
> A deny is monotonic — adding one can only narrow capability, so under unresolved glob-matching semantics the union is strictly the safer direction. An allow is not monotonic: importing a live-only allow *grants* capability that no reviewer approved.

**FR-11 — `bin/**` deny.** Emit all three spellings: relative `Edit(./bin/**)`, single-slash absolute (natural substitution output), and double-slash absolute (the live, production-proven form). `docs/SANDBOX-POLICY.md` §4 item 7 flags relative-vs-absolute and single-vs-double-slash matching as **unverified**; emitting all three makes the deny correct under every candidate semantics at zero capability cost. The generator must carry an inline comment saying the redundancy is deliberate and may be pruned once #1146 verifies the matcher. `CLAUDE.md` refers only to `./bin/**`; that stays true — the extra entries are belt-and-braces, as is the existing OS-level `denyWrite: __PROJECT_ROOT__/bin`.
**FR-12 — force-push globs.** Emit the union of all five forms: `Bash(git push* -f*)`, `Bash(git push*--force*)`, `Bash(git push * --force*)`, `Bash(git push * -f)`, `Bash(git push -f *)`. Neither existing set is a superset (the template's `Bash(git push * -f)` requires a terminal `-f`; the live `Bash(git push* -f*)` does not). Accepted consequence, recorded rather than discovered later: `--force-with-lease` matches `*--force*` and is therefore denied. This is already true of the live config, so it is not a regression, and it is intended — a lease-guarded force push is still a force push.
**FR-13 — allows.** `Bash(claude *)` is live-only and is **intentionally not carried over**; whether nested-`claude` invocation belongs in the shared profile is explicitly deferred to #1146 by `docs/SANDBOX-POLICY.md` §4 item 7. Impact is low: with `autoAllowBashIfSandboxed: true` the allow list is advisory, not enforcing.
**FR-14.** The template itself is updated so the reconciled deny set is the tracked source of truth. `Edit(./bin/**)` is **retained** (#1202 sequencing; the escalation path is currently closed and removing the rule while tidying would open it). No `bin/` migration, no deny removal, in this PR.

## 6. Acceptance criteria (testable)

1. `--role human --check` against the live Human clone exits non-zero **before** the template is reconciled and zero **after** the generator has written it — demonstrating the check actually detects divergence rather than always passing.
2. `--role worker` and `--role overseer` exit non-zero with a message naming #1146; neither writes any file.
3. A template with a deliberately misspelled placeholder causes a hard failure and leaves no output file (not even a partial one).
4. Generated output for `human` is a **semantic superset** of the pre-existing live file: every live `allow` present, every live `deny` present, plus exactly the FR-11/FR-12 additions and minus exactly the FR-13 removal. The PR records this as an explicit delta table.
5. Running the generator twice produces identical output (deterministic; stable key/array ordering).
6. Re-running against an existing live file without the force flag exits non-zero and does not modify it; with the flag, a backup exists afterwards.
7. `validate_setup.sh` on a divergent clone prints the divergence to stderr and still exits successfully.

**#1221 acceptance criteria deliberately deferred, with reason:**
- *"writes both `settings.json` and `settings.local.json`"* → **`settings.local.json` only.** Generating `settings.json` rests on #1202's "Decision 4", which is a recommendation, not a human-ratified decision, and #1202 is marked *do not start implementation*. It also removes a file from git review — structural. See E-1.
- *"reproduced byte-for-byte"* → replaced by criterion 4. Byte-equality became the wrong property the moment §5 chose union: the generator now deliberately emits denies the live file lacks. Semantic-superset plus a recorded delta table is the stronger claim.

## 7. Escalations (deferred, not decided here)

- **E-1 — should `.claude/settings.json` become generated-and-untracked?** Structural: it removes a governance-relevant file from git review, and the only support for it is unratified shorthand in an open, explicitly-blocked issue. Needs a human ruling on #1202 before any implementation. **Nothing in this PR touches `settings.json`.**
- **E-2 — should a stale sandbox config block session start?** Fail-closed is this repo's ethos, but a hard block on the operator's own interactive session is high blast radius, and a legitimate pending hand-edit would lock the human out of the clone they need in order to fix it. FR-9 ships the warning; promoting it to blocking is a human call once the check has run clean for a while.

## 8. Non-goals

Applying any policy to `worker`/`overseer` (#1146) · any `bin/` migration or deny removal (#1202) · sync cadence (#1201/#1202) · CI wiring (§4) · `settings.json` generation (E-1) · any change to `hos_install.sh`'s consumer settings merge · resolving `strictAllowlist`, `disableBypassPermissionsMode` vs. `bin/hos-cron`, or `.claude/agents/**` editability (`docs/SANDBOX-POLICY.md` §4 items 2–4, all #1146).

**Expected footprint:** ~9 files (generator, its tests, template reconciliation, `validate_setup.sh` hook, `docs/SANDBOX-POLICY.md` status update, this spec + ADR + technical design). Within the ≤15 files / ≤10 commits budget.
