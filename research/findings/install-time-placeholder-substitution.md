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

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — similar pattern: rules that appear correct but silently fail because the mechanism isn't there
- `tooling-drift-in-validation-pipelines.md` — another class of silent failure in framework tooling
