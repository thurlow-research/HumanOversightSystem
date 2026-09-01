# Generated artifacts — enumeration and gate coverage

*Audit produced for #1414: "generated artifacts go stale silently while their
gates fail closed repo-wide." Read alongside `docs/GATE-COVERAGE-MECE.md`
(review-pipeline failure classes) — this document covers a narrower, adjacent
failure class: a **committed file that is a pure function of other committed
input**, where nothing forces regeneration at the point the input changes.*

## The pattern

1. Someone edits the input (an agent file, `protected_surfaces.txt`, a new
   script under `scripts/`).
2. A derived artifact must be regenerated to match. Nothing forces this at the
   moment of the change.
3. A gate compares derived-vs-actual and fails closed — correctly, in
   isolation.
4. If the gate is repo-wide (a required CI check) or runs at cycle-start
   (a baseline), the failure is not scoped to the change that caused it — it
   blocks unrelated work.

Every row below is *correct* to fail closed once a gate exists. The gap this
document tracks is asymmetry: **regeneration is manual, enforcement is
automatic** — not that any individual gate is wrong to fail.

`scripts/framework/regen_all.sh` is the single canonical entry point for the
two rows below that are safe to self-heal mechanically (pure functions of
on-disk state, no human judgment required): `SCRIPTS-INDEX.md` and
`.github/CODEOWNERS`. Default mode regenerates both in place and reports what
changed; `--check` mode regenerates into isolated temp locations and reports
staleness without touching the working tree (used as a freshness gate).
`scripts/framework/run_tests_inner_loop.sh` — the chokepoint both the
cycle-start baseline and the worker's own post-change step run through — calls
default mode before the pytest suite, so drift in these two artifacts no
longer halts the worker at cycle-start (#1413); it is fixed automatically
before `test_scripts_index.py` / `test_codeowners_current.py` even run.

## Enumeration

| Artifact | Generator | Input | Gate | Attributes the cause? | Blast radius if ungated |
|---|---|---|---|---|---|
| `SCRIPTS-INDEX.md` | `scripts/framework/gen_scripts_index.sh` | `bin/`, `bootstrap/` (top-level), `scripts/` (recursive) | `tests/framework/test_scripts_index.py` (byte-diff + independent re-scan floor) | Yes — lists the missing file(s) by path | Confirmed (#1413): a stale index halted the worker for ~40 min across 4 cycles when an untracked script was left behind by a prior dead cycle |
| `scripts/framework/validation-stamps/phase1-<hash>.stamp` | `check_agents_static.sh` (via `run_framework_validation.sh`) | `.claude/agents/*.md` content hash | `check_validation_current.sh` (CI check — status unverified, see caveat below) | Yes — prints the expected stamp filename and the remediation command | Confirmed (#1367): every open PR failed the "Validation stamps current" check regardless of what it touched |
| `.github/CODEOWNERS` | `scripts/framework/gen_codeowners.sh` | `scripts/framework/protected_surfaces.txt` | `tests/framework/test_codeowners_current.py` (added by #1414; byte-diff against a sandboxed regeneration) | Yes — the failure message names the stale file and the exact regeneration command | **Was unguarded before #1414.** This is the governance-critical member: CODEOWNERS is the static half of the AGENT-IDENTITY.md §9 human-approval gate. A silent drift here means a protected surface could stop requiring human review without any signal — worse than either confirmed instance above, because nothing would even fail loudly. |
| `.hos-manifest` | `bootstrap/hos_install.sh` (via `scripts/oversight/validators/regions.py`'s `assemble_manifest`) | The **consumer's** installed agent/pack files at install/upgrade time | `tests/framework/test_consumer_framework_files.py` (guards that the *source list* `framework_consumer_files.txt` the manifest enumerator reads matches what the installer ships) + `tests/framework/test_pack_install.py`, `test_regions_cli.py`, `test_plan_upgrade.py` (manifest-write correctness) | Partially — these tests guard correctness of the manifest-writer and its source list in *this* repo; they do not (and structurally cannot) detect a stale manifest in an already-installed consumer repo | Different failure shape from the other three: `.hos-manifest` is not a file *this* repo commits and re-derives on every PR. It is written once per install/upgrade in a *target* project. There is no "PR touched an input, manifest is now stale" scenario in this repo — the closest analogue (per #1389) is an install/upgrade path that produces a manifest with zero entries, which the pack-install/upgrade test suite already covers. Kept in this table because `gen_scripts_index.sh`'s own header names the manifest family as precedent, and because a broken assembler would be governance-relevant, not because it currently drifts unnoticed. |

**Caveat on the validation-stamp row's "required CI check" status:** an
independent audit could not confirm from in-repo source alone that
`check_validation_current.sh` / "Validation Stamp Check" is actually wired
into `scripts/framework/setup_branch_protection.sh`'s required-status-check
list — `required_status_checks.contexts` there is
`["require-overseer-approval", "require-human-approval", "require-tier-ceiling"]`,
and `tests/framework/test_branch_protection_contexts.py` only asserts those
three. A live `gh api repos/.../branches/main/protection` call to confirm the
actual GitHub-side setting returned 403 (insufficient permissions for this
token) rather than a definitive answer. This document does not claim the
validation-stamp check either is or isn't a required branch-protection check
— that needs a human with admin access to verify live branch-protection
settings.

## Outstanding question this table answers

**Can `.github/CODEOWNERS` silently drift from `protected_surfaces.txt`?**
No, as of #1414 — `tests/framework/test_codeowners_current.py` fails closed the
same way `test_scripts_index.py` already did for the script index. Before this
test existed, the answer was yes: nothing regenerated or checked CODEOWNERS
when `protected_surfaces.txt` changed, and CODEOWNERS decides which surfaces
require a human code owner (AGENT-IDENTITY.md §9) — the highest-consequence
member of this family, because a drift here loosens a control rather than
merely blocking a PR.

## What this document does not attempt

The self-healing / blast-radius question — *should a stale, purely-derived
artifact halt an unrelated worker cycle at all, or should the gate regenerate
it, or should such gates be scoped to the PR that caused the drift rather than
the cycle-start baseline?* — is now **closed for the two mechanically
safe artifacts**: `scripts/framework/regen_all.sh` self-heals
`SCRIPTS-INDEX.md` and `.github/CODEOWNERS` (both pure functions of on-disk
state, no human judgment required) and is wired into
`run_tests_inner_loop.sh`, so drift in either no longer halts the worker at
cycle-start (#1413).

The validation-stamp file remains explicitly **not** self-heal-safe — it is
only written after real AI/human review passes (Phase 2-4 of
`run_framework_validation.sh`), so auto-regenerating it on drift would defeat
the gate it exists to enforce. `check_validation_current.sh` already names the
expected filename and the exact remediation command, satisfying the
"names the cause" branch of the acceptance criterion for that artifact without
self-healing.

**#1415's distinct scope is unaffected**: a dead cycle's *other* debris
(uncommitted or untracked files unrelated to these two generated artifacts) is
a different failure class from the one this document and `regen_all.sh`
address, and remains #1415's scope.

*Maintenance: update this table whenever a new committed file becomes a pure
function of other committed input and gets its own freshness gate (or is
found to be missing one).*
