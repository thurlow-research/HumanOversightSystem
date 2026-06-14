# Finding: Framework Files With Project-Specific Content Silently Corrupt New Installations

**Role:** signal-generation (engineering) — install-correctness, a benefit, not the oversight research subject

**First observed:** 2026-06-12, issues #17 and #18 (reported by CondoParkShare)
**Documented in:** `scripts/framework/install.sh`, `DECISIONS.md` D27/D28

---

## The Finding

A framework that ships agent files containing project-specific content — either hardcoded project names, hardcoded feature lists, or unsubstituted placeholders — silently produces broken or misleading installations for any project other than the reference one. The failure is silent because:

1. The agent files copy without error
2. The placeholders look syntactically valid until an agent actually tries to use them
3. A freshly installed project has no way to know which content is generic and which is specific to the reference project

Two instances in this framework:

**Instance 1 — unsubstituted placeholders:** `spec-red-team.md` and `ux-designer.md` contained `{SPEC_FILE}` and `{DESIGN_PACK_DIR}` placeholders. `install.sh` collected project-specific values (PROJECT_NAME, DESIGN_PACK_PATH) but never substituted them into the copied files. A freshly installed project would have `spec-red-team` run `cat {SPEC_FILE}` and `ux-designer` reference `{DESIGN_PACK_DIR}/DESIGN.md` — both failing silently.

**Instance 2 — replicated project-specific content:** `ux-designer.md` contained a hardcoded feature audit checklist derived from CondoParkShare's spec (booking flow, TOTP, HOA portal, etc.). An agent in any other project would audit against the wrong feature list — producing a readiness document that covered CondoParkShare features rather than the actual project's features.

---

## Why This Is Hard to Catch

The failure doesn't surface at install time — it surfaces when the agent runs. By then:
- The install is complete
- The human may assume the framework works out of the box
- The agent may produce plausible-looking output that's simply wrong for this project

This is a class of configuration error that looks like success until it produces incorrect behavior at a later stage. It's the same class as environment variables that have sensible-looking defaults that happen to be wrong for the deployment context.

---

## The Fix Pattern

**For unsubstituted placeholders:** substitution must happen at install time, not documentation time. A note in SETUP.md saying "manually replace `{SPEC_FILE}`" is insufficient — it will be missed. The installer must perform the substitution automatically.

**For replicated project-specific content:** replace static content with self-directing instructions. Instead of hardcoding a feature list, instruct the agent to derive the list from the spec file at runtime. This is more accurate (tracks the actual spec), requires no substitution, and is more durable as the project evolves.

**Implementation:** `perl -i` for cross-platform in-place substitution. `sed -i` has different syntax on macOS vs. Linux; `perl -i` is consistent on both.

---

## The Self-Directing Prompt Pattern

The most important resolution here is not the placeholder substitution — it's the replacement of a static feature list with a runtime instruction. The before/after:

**Before (static, project-specific):**
> "Walk every user-visible feature in SPEC-1 (§§3–11). Work through this list:
> - Resident search results — spot card states: available, booked...
> - Booking flow — confirmation, gate-blocked states..."

**After (self-directing, generic):**
> "Walk every user-visible feature in `{SPEC_FILE}`. For each feature section, enumerate: all primary flow states, all failure/blocked states, all empty states..."

The after version:
- Works for any project
- Tracks the actual spec (stays current as requirements evolve)
- Produces a more thorough audit (the agent reads the real spec, not a frozen summary)
- Requires no maintenance when the spec changes

This generalizes: **agent prompts that replicate spec or design content statically should be replaced with references to the source documents**. The agent can read the documents at runtime; the prompt should tell it where to look, not what to find.

---

## Implications for Research

1. **Framework portability requires distinguishing generic from specific.** A framework file that contains project-specific content is not a framework file — it is a project file that happens to live in the framework. The distinction must be enforced at the file level, not documented in prose.

2. **Silent failures are worse than loud failures.** A placeholder that causes a shell error immediately is better than one that produces plausible-but-wrong output. Framework design should prefer early, visible failures over late, silent ones.

3. **Install-time substitution is the boundary.** The framework's job is to be deployable. Everything project-specific must be either (a) substituted at install time, (b) explicitly marked for human customization, or (c) replaced with self-directing instructions that work for any project.

4. **Consumer projects as integration tests.** CondoParkShare discovered both of these gaps by actually installing and running the framework. This confirms the value of the reference implementation as an empirical test of the framework's deployability claims — not just its design claims.

---

## Update (2026-06-13): the regression, and why substitution must be idempotent

The CPS real-world run (HOS#99, and the user's design sketch in #110) re-surfaced this from a new angle. By then the installer had been split: `bootstrap/hos_install.sh` scaffolds from a validated release, while the *substitution* still lived only in the legacy `scripts/framework/install.sh`. The consequence:

1. **A fresh `hos_install.sh` install never substituted at all (#87)** — it copied the templates with raw `{SPEC_FILE}` tokens and stopped. The substitution step was stranded in a different installer.
2. **`--force` *re-introduced* raw tokens over already-substituted files (#99).** CPS had `spec-red-team.md` correctly substituted to `Specs/SPEC-1-pilot.md`; a `--force` framework update copied the raw template back over it, re-breaking the live `$(cat {SPEC_FILE} …)` command. A human caught it only because the placeholder grep fired.

The fix is the rule this finding already implies, made operational: **substitution is not a one-time install step, it is an invariant the installer must re-establish on every run.** `hos_install.sh` now re-substitutes after every scaffold — fresh or `--force` — sourcing values from env overrides or the project's persisted `scripts/framework/config.sh`, leaving any value it doesn't have as the literal token (never blanking it).

**Sub-lesson — verify the generated artifact, not just that the generator ran.** The first cut of the fix had a bug that *only* surfaced by inspecting the output: a bash default `${_sf:-{SPEC_FILE}}` closes the `${…}` at the first `}`, so a set value became `Specs/SPEC-1-pilot.md}` — a stray brace that would have silently broken the very `$(cat {SPEC_FILE} …)` command it was meant to fix. Every "did the installer run?" check passed; only diffing the *produced file* caught it. A code-generation / substitution step must be tested on its output, because its failure mode is a plausible-looking corruption, not an error — the same silent-failure thesis this finding is about, applied one level up to the fix itself.

**Design resolution (#110) — declare the placeholder set, manage config non-destructively.** The forward-proof fix recognizes that the placeholder set *grows* as the framework iterates (every new `{TOKEN}` in an agent is a future silent break), and that you **cannot discover them by regex** — agent prompts also carry runtime tokens (`{N}` ×42, `{HEAD_SHA}`, `{BASE_SHA}`) and JSON examples (`{role}`) that must never be substituted. (Proof it was already drifting: `{ADR_FILE}` shipped in an agent template but the hardcoded 3-token substitution never handled it.) So:

1. **Declare, don't guess.** `scripts/framework/placeholders.manifest` is the single source of truth for *which* tokens are install-time placeholders. Adding a new one is a one-line manifest change; the installer handles it automatically thereafter.
2. **Non-destructive config management.** On every install/upgrade the installer ensures the project's `config.sh` has a key for each declared placeholder, **appending missing keys (empty) without ever touching an existing value** — so an upgrade that introduces a new variable extends config completely without clobbering. This is the "append new vars, keep existing" property #110 asked for; it makes "extract before update" unnecessary because values persist in `config.sh` and are re-applied each run.
3. **Substitute generically; warn precisely.** Every declared placeholder with a value is substituted (env override > `config.sh`); a value we lack leaves the literal token. The "still raw" warning fires only for tokens that *actually remain in a scaffolded agent*, not for declared-but-absent ones — so noise scales with real exposure, not the manifest size.

The general lesson: **a code-generation input set that grows over time must be declared in one managed place, and the generator must extend its config non-destructively** — otherwise every framework iteration is a fresh opportunity to silently ship a raw token or clobber a value, and the pain compounds with each upgrade.

---

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — similar pattern: rules that appear correct but silently fail because the mechanism isn't there
- `tooling-drift-in-validation-pipelines.md` — another class of silent failure in framework tooling
