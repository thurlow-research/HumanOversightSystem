# SPEC-366 — Per-Step Stamp Subdirectories

**Issue:** #366
**Status:** Draft — architect open questions resolved 2026-06-16; ready for technical design
**Date:** 2026-06-16
**Classification:** Additive — fills a structural gap implied by the per-step sign-off model

---

## 1. Problem Statement

`signoffs/` is a flat directory of role-keyed stamp files (`<role>.stamp`). The
gate (`signoff_gate.py`) treats the union of all steps' `required_signoffs` as
a single global set, so every PR commits every role stamp. When any PR merges
to main, every in-flight PR immediately has a conflict on every stamp file. The
correct resolution is always `--ours` (each PR's stamps are authoritative for
that PR), but git cannot infer this, so every rebase or merge requires a manual
conflict resolution cycle. In a busy session with ~15 open PRs, this happened
5+ times in a single day (PRs #133, #135, #138, #139).

The root cause is a design mismatch: stamps are step-scoped in intent (each
step's reviewers sign off on that step's changes) but repo-scoped in layout (a
single flat namespace shared by all concurrent PRs). Fixing the layout to match
the intent eliminates the conflict class entirely.

---

## 2. Decision: Option A — Per-Step Stamp Subdirectories

The preferred fix is **per-step stamp subdirectories**: `signoffs/<step-id>/`.

Rationale for preferring A over the other options:

- **Option B** (single file per PR, branch-slug) moves the conflict problem
  rather than eliminating it — it requires the gate to know which PR it is
  evaluating and adds branch-name parsing. It also doesn't survive branch
  renames.
- **Option C** (move to `.claudetmp/`, gitignored) removes the git-timestamp
  enforcement that is the entire basis of the gate's security model. This
  design decision is load-bearing; losing it is not acceptable.
- **Option D** (document `--ours`) mitigates, does not fix. It also requires
  every worker to carry that knowledge; the current worker does not.

Option A preserves every aspect of the existing security model (git commit
timestamps, committed stamps, gate logic) and eliminates the conflict class by
ensuring concurrent PRs never write to the same files.

---

## 3. New Path Convention

### 3.1 Stamp file location

Current:
```
signoffs/<role>.stamp
```

New:
```
signoffs/<step-id>/<role>.stamp
```

Where `<step-id>` is the `id` field from `contract/step-manifest.yaml` — a
short string or integer (e.g. `1`, `auth`, `scaffold`). The step-id must be
URL-safe and filesystem-safe: alphanumeric characters and hyphens only, no
spaces, no slashes.

Example (step id = `3`, role = `security`):
```
signoffs/3/security.stamp
```

### 3.2 Step-register files (no change)

The `.claudetmp/signoffs/step{N}-register.md` files are ephemeral and
gitignored. They are unaffected by this change.

### 3.3 Sign-off command

The `sign_off.sh` invocation gains a required `--step <id>` argument:

```bash
scripts/oversight/sign_off.sh <role> --step <step-id> [--status STATUS] [--agent NAME] [--note "text"]
```

The script creates `signoffs/<step-id>/` if absent and writes the stamp there.
The commit instruction in the script output updates to reflect the new path.

### 3.4 Gate invocation

`signoff_gate.py` gains a required `--step <id>` argument for PR/CI mode. In
per-step mode it reads only `signoffs/<step-id>/` and checks only the
`required_signoffs` for that step. In `--all` (deploy) mode it checks every
step subdirectory against its respective step's required roles.

`--step` is a required argument; omission is a hard error. See OQ-366-01 in §7.

---

## 4. Behavioral Requirements

### REQ-366-01: Stamp isolation
A stamp written for step N must not be read when evaluating step M (N ≠ M).
Stamps in `signoffs/<step-id>/` are scoped to that step only.

### REQ-366-02: Conflict elimination
Two concurrent PRs for different steps must never write to the same stamp path.
The directory structure guarantees this if each PR's build corresponds to a
distinct step-id. (PRs for the same step still conflict — this is intentional;
same-step concurrent work is already disallowed by the worker protocol.)

### REQ-366-03: Timestamp semantics preserved
The git commit timestamp mechanism is unchanged. Stamps are committed; the gate
reads commit timestamps, not file mtimes. No change to the security model.

### REQ-366-04: NOT_APPLICABLE stamps persist
A role that is explicitly N/A for a step still requires a committed
`signoffs/<step-id>/<role>.stamp` with `status: NOT_APPLICABLE`. The re-signing
requirement on subsequent changes is unchanged.

### REQ-366-05: Gate reads required_signoffs per step
The gate must read the `required_signoffs` list for the specific step being
evaluated, not the union of all steps. This is a behavioral change from the
current implementation, which reads the union.

### REQ-366-06: Deploy mode covers all steps (manifest-authoritative)
In `--all` (deploy) mode, the gate iterates the step-id set from
`step-manifest.yaml`. For every step with a non-empty `required_signoffs` list,
if `signoffs/<step-id>/` does not exist or does not contain passing stamps for
all required roles, the gate MUST exit 1 (GATE FAIL). Disk enumeration of
`signoffs/` subdirectories is explicitly prohibited as the authoritative source
for this check — it is fail-open (a missing directory is silently skipped,
leaving unsigned steps undetected). The manifest is the only authoritative step
enumeration source.

### REQ-366-07: ESCALATED has no stamp (unchanged)
An unresolved escalation has no passing stamp. The gate fails on a missing stamp
for a required role. This behavior is unchanged.

### REQ-366-08: OVERSIGHT_ARTIFACT_PREFIXES updated
`signoff_gate.py`'s `OVERSIGHT_ARTIFACT_PREFIXES` tuple must remain prefixed
with `signoffs/` (not a specific step subdirectory) so that all stamp files
across all steps are excluded from the changed-file set that stamps must beat.

### REQ-366-09: Orphan step directory is a gate failure
When `signoffs/<step-id>/` exists on disk but `<step-id>` has no matching entry
in `step-manifest.yaml`, the gate MUST exit 1 (GATE FAIL) and emit an error
message that names the orphan directory. This applies in both PR mode and deploy
(`--all`) mode. Warn-and-pass is explicitly prohibited: an orphan directory
indicates a step was removed from the manifest after stamps were committed, which
is a contract integrity failure requiring operator intervention.

---

## 5. Migration

### 5.1 Existing flat stamps

At the time of this writing the `signoffs/` directory contains only a
`README.md` — no existing stamp files are present in the repo. Migration of
live flat stamps is therefore not required for this repo.

For consumer projects that have already deployed the flat layout, `hos_install.sh`
MUST detect committed flat stamps — files matching `signoffs/*.stamp` at the top
level of `signoffs/` (i.e., outside any step subdirectory) — on upgrade and MUST
FAIL loudly (non-zero exit, descriptive error) with the migration instructions
below. Silent skip is explicitly prohibited: a silent skip leaves the consumer
unable to satisfy the new gate because the gate will not find stamps in the
expected per-step subdirectory paths, and the consumer will not know why.

The upgrade MUST NOT proceed past the flat-stamp detection check until the
operator has completed the migration. This is a breaking contract change; the
`contract_version` must increment (see §5.3).

Required migration path for operators:

1. For each existing `signoffs/<role>.stamp`, determine which step it belongs to
   by inspecting the branch's build history or `.claudetmp/signoffs/` register files.
2. Move the stamp: `mv signoffs/<role>.stamp signoffs/<step-id>/<role>.stamp`
3. `git add signoffs/ && git commit -m "migrate: per-step stamp subdirectories (#366)"`
4. The commit timestamp of the moved stamps is the migration commit time — this
   means stamps will be treated as signed at migration time. Any source files
   committed after this point in the same PR will require re-signing.

If a step cannot be determined, the stamp should be moved to a step subdirectory
that covers the files it was originally signing, or dropped and re-signed.

### 5.2 README.md

`signoffs/README.md` moves to `signoffs/README.md` unchanged (repo-level, not
step-level). Step subdirectories do not require their own README.

### 5.3 Contract version bump

The change to the stamp file path is a **breaking change** to the filesystem
protocol (contract §8: "Changing the sign-off register file path or format").
`OVERSIGHT-CONTRACT.md` §1 must update the `signoffs/` layout to show the
subdirectory structure, and `contract_version` must increment.

---

## 6. Impact on Consumers

### 6.1 `sign_off.sh`

Requires a new `--step <id>` argument. The script must:
- Accept `--step <id>` as a required parameter; omission is a hard error (non-zero
  exit, descriptive message). See OQ-366-01 in §7.
- Create `signoffs/<step-id>/` if absent.
- Write to `signoffs/<step-id>/<role>.stamp`.
- Update the commit instruction in output.

### 6.2 `signoff_gate.py`

Requires changes to:
- `SIGNOFFS_DIR` handling — stamp path becomes `signoffs/<step-id>/<role>.stamp`.
- `load_required_roles` — must return per-step required roles, not the union.
- `main` — must accept `--step <id>`; in PR mode only check that step's stamps.
- `--all` (deploy) mode — MUST iterate the step-id set from `step-manifest.yaml`
  (manifest-authoritative). For each step with a non-empty `required_signoffs`,
  a missing or incomplete `signoffs/<step-id>/` is a GATE FAIL (exit 1). Disk
  enumeration of `signoffs/` subdirectories is explicitly prohibited as the
  authoritative source — enumerating only directories that exist on disk is
  fail-open and must not be used.
- `OVERSIGHT_ARTIFACT_PREFIXES` — keep `signoffs/` prefix as-is (covers all
  subdirectories).
- `is_oversight_artifact` — behavior unchanged; `signoffs/<step-id>/...` still
  starts with `signoffs/`.

### 6.3 `signoffs/README.md`

Update path examples and command examples to reflect the new layout.

### 6.4 `contract/OVERSIGHT-CONTRACT.md` §1

The filesystem protocol block must update the `signoffs/` tree:

```
signoffs/
  README.md
  <step-id>/
    <role>.stamp         ← one stamp per role per step; committed
```

### 6.5 Agent instructions referencing stamp paths

All agent instruction files (`.claude/agents/*.md`) that include the stamp
path `signoffs/<role>.stamp` must update to `signoffs/<step-id>/<role>.stamp`.
From the file scan, this applies to: `system-test.md`, `code-reviewer.md`,
`security-reviewer.md`, `infra-reviewer.md`, `ops-reviewer.md`, `pm-agent.md`,
`a11y-reviewer.md`, `oversight-evaluator.md`, `overseer.md`, `ui-reviewer.md`,
`post-change-sweep.md`, `privacy-reviewer.md`, `worker.md`,
`reliability-reviewer.md`, `unit-test.md`.

### 6.6 `check_agents_static.sh`

From inspection, `check_agents_static.sh` does not directly read `signoffs/`.
It performs structural checks on agent files. No change required unless the
architect determines that the static checker should validate stamp paths in
agent instructions.

### 6.7 `METHODOLOGY.md`

The pipeline description table (listing `sign_off.sh` and `signoff_gate.py`)
must update the stamp path examples. The "Gotchas" section (stamp-file
collisions, cited in issue #366) must be updated to note the fix.

---

## 7. Open Questions — RESOLVED

All five open questions are resolved per architect ruling (2026-06-16). The
resolutions are normative and are reflected in the requirements above.

**OQ-366-01 — Is `--step` required or has a default? — RESOLVED**
Ruling: `--step <id>` is a required argument in both `sign_off.sh` and
`signoff_gate.py`. Omission is a hard error (non-zero exit, descriptive message).
No default step is provided. This prevents silent routing to a wrong step during
rollout. Scripts that do not yet pass `--step` must be updated before the gate
is activated. Rationale: a default silently misdirects stamps; "required" is
cleaner and the migration window is controlled.

**OQ-366-02 — Deploy mode: what steps are "all"? — RESOLVED**
Ruling: manifest-authoritative (option b). Deploy mode iterates the step-id set
from `step-manifest.yaml`. Disk enumeration of `signoffs/` subdirectories is
explicitly prohibited as the authoritative source — it is fail-open. See
REQ-366-06 and §6.2.

**OQ-366-03 — Same-step, multiple PRs? — RESOLVED**
Ruling: the existing worker protocol already prohibits concurrent same-step work.
No additional disambiguation layer (branch-slug nesting) is introduced by this
spec. If the worker protocol is violated and two PRs cover the same step, they
will conflict on stamp files — this is intentional and surfaces the protocol
violation. Adding branch-slug nesting is deferred; it reintroduces Option B
complexity and is out of scope for this spec.

**OQ-366-04 — Consumer install / upgrade path? — RESOLVED**
Ruling: `hos_install.sh` MUST detect committed flat stamps and MUST fail loudly
with migration instructions. Silent skip is prohibited. See §5.1. This is a
breaking contract change; `contract_version` increments per §5.3.

**OQ-366-05 — Gate behavior when step-id does not exist in manifest? — RESOLVED**
Ruling: gate MUST exit 1 (GATE FAIL) and name the orphan directory in the error
message. Warn-and-pass is prohibited. See REQ-366-09.

---

## 8. Out of Scope

- Option B, C, D are not implemented by this spec.
- Changes to the `.claudetmp/signoffs/step{N}-register.md` ephemeral register
  format are not in scope. That system is already step-scoped.
- Per-step stamp expiry or TTL policies are not in scope.
- Parallelizing the gate across multiple steps simultaneously is not in scope.
