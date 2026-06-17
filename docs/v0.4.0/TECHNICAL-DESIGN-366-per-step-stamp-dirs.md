# Technical Design — SPEC-366 Per-Step Stamp Subdirectories

**Spec:** `docs/specs/SPEC-366-per-step-stamp-dirs.md`
**Issue:** #366
**Date:** 2026-06-16
**Author:** technical-design agent

SELF-FLAG: RISK: MEDIUM | CONFIDENCE: HIGH — confident in the script/gate contract
and the manifest-authoritative deploy logic; the structural element (installer
fail-closed on flat stamps) is the load-bearing risk and is specified below as a
pre-write hard stop.

Change class: **additive** (new path convention in `sign_off.sh` / `signoff_gate.py`
/ contract) + **structural** (installer fail-closed on upgrade — a new blocking gate
in the install path). The structural element is called out for human review in §7.

---

## 1. Scope and the one material deviation from the task brief

The task brief item **E** says "15 agent files reference the stamp path
`signoffs/<role>.stamp`; update the path examples." A repo grep
(`grep -rn 'signoffs/' .claude/agents/`) shows that **none** of the 15 named agent
files reference the committed stamp path `signoffs/<role>.stamp`. Every one of them
references the **ephemeral register** `.claudetmp/signoffs/step{N}-register.md`.

Per SPEC-366 §3.2 (normative): *"The `.claudetmp/signoffs/step{N}-register.md` files
are ephemeral and gitignored. They are unaffected by this change."* The committed
stamp path `signoffs/<role>.stamp` appears only in:

- `scripts/oversight/sign_off.sh`
- `scripts/oversight/signoff_gate.py`
- `signoffs/README.md`

**Design decision:** Item E updates **zero** agent files, because changing the
`.claudetmp/...register.md` references would violate spec §3.2 (out of scope) and
the task's own constraint *"Only the path in examples, not behavioral instructions."*
The register path is unchanged by this spec. The 15-file claim in spec §6.5 and the
brief is a stale inventory; the authoritative path inventory is the grep above. This
is recorded as a deviation in §8. `signoffs/README.md` (which *does* carry the stamp
path) is updated.

If the architect intends a separate rename of the ephemeral register, that is a
distinct spec and must not be folded in here.

---

## 2. Component map (contract, not implementation)

| # | Component | File | Change |
|---|---|---|---|
| A | sign_off.sh | `scripts/oversight/sign_off.sh` | add required `--step`; write `signoffs/<step>/<role>.stamp` |
| B | signoff_gate.py | `scripts/oversight/signoff_gate.py` | add `--step`; per-step PR mode; manifest-authoritative `--all`; orphan-dir fail |
| C | OVERSIGHT-CONTRACT §1 | `contract/OVERSIGHT-CONTRACT.md` | show `signoffs/<step-id>/<role>.stamp`; bump `contract_version` references where stated |
| D | Installer | `bootstrap/hos_install.sh` | pre-write hard stop: detect flat `signoffs/*.stamp` on upgrade → exit 1 |
| E | Agent files | `.claude/agents/*.md` | **no change** — see §1 |
| E′ | README | `signoffs/README.md` | path + command examples |
| F | Tests | `tests/oversight/test_signoff_gate.py` | new file, 3+ required cases |

---

## 3. Component A — `sign_off.sh`

### 3.1 Interface

```
scripts/oversight/sign_off.sh <role> --step <step-id> [--status STATUS] [--agent NAME] [--note "text"]
```

- `<role>` — positional, unchanged (must exist in `role_mappings`).
- `--step <step-id>` — **required**. Omission is a hard error: exit 2, message naming
  `--step` as required. (OQ-366-01.)

### 3.2 step-id validation

`<step-id>` must be filesystem- and URL-safe: `^[A-Za-z0-9][A-Za-z0-9-]*$`
(alphanumeric and hyphen, no leading hyphen, no slash, no space). A non-matching
value is exit 2 with a descriptive error. This prevents `../` traversal and stray
path separators from misrouting a stamp.

### 3.3 Output contract

- Compute `STAMP_DIR = signoffs/<step-id>`; `mkdir -p` it.
- Write stamp to `signoffs/<step-id>/<role>.stamp`. Stamp **body is unchanged**
  (role/agent/status/signed_at/head_at_signing/note).
- The trailing commit instruction must print the new path:
  `git add signoffs/<step-id>/<role>.stamp && git commit -m 'sign-off: <role> <STATUS>'`.
- The usage/header comment block must show `--step`.

### 3.4 Boundaries

- Must not infer or default a step. No env-var fallback.
- Must not commit the stamp (unchanged).

---

## 4. Component B — `signoff_gate.py`

### 4.1 Interface

```
signoff_gate.py (--base REF | --all) [--step ID] [--manifest PATH] [--quiet]
```

- PR mode (`--base`): `--step <id>` is **required**. Omission is a hard error
  (argparse error / exit 2). Reads only `signoffs/<step-id>/` and checks only that
  step's `required_signoffs`.
- Deploy mode (`--all`): `--step` is **ignored if present** (deploy iterates the whole
  manifest). Accepting but ignoring `--step` in `--all` keeps a wrapper that always
  passes `--step` from breaking; document this.

### 4.2 New / changed functions

**`load_required_roles(manifest_path)` → keep signature, add a per-step variant.**
Add `load_steps(manifest_path) -> list[dict]` returning each step's
`(id, required_signoffs)`. The existing union behavior is removed from the gate's
PR path (REQ-366-05) but `load_required_roles` may remain for the role→agent map.
Concretely:

- `load_manifest(path) -> (role_map, steps)` where `steps` is a list of
  `{"id": str, "required": [role,...]}`. `id` is stringified (manifest ids may be int).

**Per-step check helper** `check_step(root, step_id, required_roles, role_map, newest_file_time, log, failures)`:
- Stamp path is `signoffs/<step-id>/<role>.stamp`.
- Same four checks as today, per role: exists → valid status → committed → not stale.
- Appends to a shared `failures` list.

### 4.3 PR mode (`--base`, `--step`)

1. Resolve the requested `--step` against the manifest. If `step-id` is **not** in
   the manifest → exit 1 (orphan/unknown step; REQ-366-09 applies to PR mode too),
   error names the step.
2. Build the changed-file set as today (excluding oversight artifacts).
3. Orphan-directory sweep (see §4.5) — applies in PR mode.
4. Run `check_step` for the requested step's `required_signoffs` only.
5. If the step's `required_signoffs` is empty, the gate passes for that step (no roles
   to satisfy) — but the orphan sweep still runs.

### 4.4 Deploy mode (`--all`) — manifest-authoritative (REQ-366-06)

1. Build the changed-file set = all tracked files (as today).
2. Iterate **steps from the manifest** (not disk). For each step with a non-empty
   `required_signoffs`, run `check_step`. A missing `signoffs/<step-id>/` directory
   or a missing/stale/invalid stamp for any required role → failure.
3. Disk enumeration of `signoffs/` subdirectories MUST NOT be the authoritative
   step source. (It is fail-open: a missing dir would be silently skipped.)
4. Orphan-directory sweep (§4.5) runs.

### 4.5 Orphan-directory sweep (REQ-366-09)

In both modes: enumerate the immediate subdirectories of `signoffs/` on disk. For
each subdirectory name that is **not** a manifest step-id → append a failure naming
the orphan directory; the gate exits 1. `signoffs/README.md` and any non-directory
entry at the top of `signoffs/` are ignored by this sweep (the README is expected;
a top-level flat stamp is the installer's concern, not the gate's — though if one is
present at gate time, it is simply a non-directory and ignored here).

### 4.6 Empty-suite guard

The current global guard "no required_signoffs found in manifest → exit 2" is
retained but evaluated against the **union across all steps** (purely to detect a
manifest that declares no sign-offs anywhere — a misconfiguration). A single step
with empty `required_signoffs` is legal and not an error.

### 4.7 Unchanged

- `OVERSIGHT_ARTIFACT_PREFIXES` keeps the `signoffs/` prefix (REQ-366-08): all
  `signoffs/<step>/<role>.stamp` paths still start with `signoffs/`, so they remain
  excluded from the changed-file set.
- `is_oversight_artifact`, `dirty_non_signoff_paths`, commit-timestamp semantics:
  unchanged (REQ-366-03).

---

## 5. Component C — `OVERSIGHT-CONTRACT.md` §1

The committed `signoffs/` tree is not currently shown in the §1 filesystem block
(only `.claudetmp/signoffs/...` appears). Add a committed-`signoffs/` stanza at the
top of the §1 block (alongside `audit/`, which is the other committed tree):

```
signoffs/                            ← COMMITTED to project repo (not gitignored)
  README.md
  <step-id>/                         ← one subdirectory per build step (id from step-manifest.yaml)
    <role>.stamp                     ← one stamp per role per step; committed
```

No `contract_version` field exists inside `OVERSIGHT-CONTRACT.md` itself (it is a
prose `# Oversight Contract v1` title). The version bump that §5.3 of the spec calls
for is carried in `contract/step-manifest.template.yaml`'s `contract_version` field
and is a separate release decision; this design does **not** silently change a
version string. Flag to architect: confirm whether `contract_version` should bump to
`"2"` in the template now or at release cut. Until confirmed, leave as `"1"` and note
the breaking change in the contract prose.

---

## 6. Component D — `bootstrap/hos_install.sh` flat-stamp hard stop

### 6.1 Placement

Insert immediately after the git-repo validation (after the `[[ ! -d
"$TARGET_REPO/.git" ]]` block, ~line 356) and **before** any framework file is
copied. This guarantees the upgrade writes nothing until the operator migrates.

### 6.2 Logic

```
flat-stamp detection (upgrade only):
  if compgen -G "$TARGET_REPO/signoffs/*.stamp" matches at least one file:
    err "flat sign-off stamps detected — per-step migration required (#366)"
    print each offending file
    print the §5.1 migration steps (mv to signoffs/<step-id>/, git add+commit)
    exit 1
```

- "Upgrade only" = guard on a pre-existing install. A fresh install of a project that
  happens to carry flat stamps is still the same hazard, so the simplest correct
  contract is: **if `signoffs/*.stamp` exists at all, hard-stop.** Use `compgen -G`
  (glob match) so the absence of the directory is a clean no-match (exit 0 path).
- Respect `--dry-run`: in dry-run, print what would block but still exit non-zero so
  CI dry-runs surface the condition. (Match existing dry-run conventions; if dry-run
  must exit 0 elsewhere, emit a `dry_run` warning line and continue — choose the
  variant that matches the installer's existing dry-run exit policy. Default: hard
  stop regardless of dry-run, because a silent dry-run pass would hide the blocker.)
- Only top-level `signoffs/*.stamp` counts (glob does not recurse), so already-migrated
  `signoffs/<step-id>/<role>.stamp` does not trip it. This is exactly the spec's
  definition (§5.1: "files matching `signoffs/*.stamp` at the top level").

### 6.3 Boundaries

- Must not auto-migrate (spec forbids silent handling; operator must move stamps).
- Must not skip on `--force` — `--force` overwrites framework files, it does not
  waive a contract-integrity migration.

---

## 7. Human Review Required

**`bootstrap/hos_install.sh` (~line 356) — new fail-closed upgrade gate.** A new
blocking check in the install path is structural: it can halt every consumer upgrade
if the detection glob is wrong (false positive blocks a clean upgrade; false negative
lets a broken consumer past the gate). The detection is deliberately broad
(any top-level `signoffs/*.stamp`). Confirm the dry-run exit policy (§6.2) against the
installer's existing convention before merge.

**`contract/step-manifest.template.yaml` `contract_version`** — breaking-change bump
deferred to architect/release decision (§5). Do not auto-bump.

---

## 8. Deviations from brief

1. **Item E updates zero agent files** (not 15). The 15 named files reference the
   *ephemeral register* (`.claudetmp/signoffs/...register.md`), explicitly out of
   scope per spec §3.2. Updating them would change register paths the spec says are
   unaffected. `signoffs/README.md` — the actual carrier of the committed stamp path —
   is updated instead.
2. **`contract_version`** left at `"1"` pending architect ruling (§5).

---

## 9. Test contract — `tests/oversight/test_signoff_gate.py` (Component F)

New file. Mirrors `test_gate_compliance.py` loading style (load the module from path).
The gate is a script with a `main()`; tests construct a temp git repo, write a
manifest + stamps, and invoke the gate via `subprocess` (it shells to `git`), or call
helpers directly where pure. Required cases:

- `test_step_required_in_pr_mode_errors` — `--base X` without `--step` → exit 2.
- `test_deploy_mode_manifest_authoritative_missing_dir_fails` — manifest declares a
  step with required roles, no `signoffs/<step>/` on disk → `--all` exits 1
  (REQ-366-06: not silently skipped).
- `test_orphan_step_directory_fails` — `signoffs/<bogus>/` on disk, not in manifest →
  exit 1 in `--all` (REQ-366-09).
- `test_per_step_isolation` (additive) — step 1 stamps present, step 2 missing;
  `--step 1 --base` passes, `--step 2 --base` fails (REQ-366-01 isolation).
- `test_pr_unknown_step_fails` — `--step nope` not in manifest → exit 1.

Each case builds a throwaway repo with `git init`, commits source + stamps so commit
timestamps exist, and asserts on exit code + stderr substring.
