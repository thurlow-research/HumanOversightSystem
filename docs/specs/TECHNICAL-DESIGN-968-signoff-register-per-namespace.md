# Technical Design — #968: Per-Namespace Sign-off Register

**Issue:** #968
**Status:** For implementation (v0.5.1 patch)
**Milestone:** v0.5.1
**Date:** 2026-06-29
**Author:** technical-design (hos-worker)

---

## 1. Overview

The committed sign-off register is today **9 fixed-path files** — `signoffs/<role>.stamp`
for every reviewer role. The sign-off gate (`scripts/oversight/signoff_gate.py`) keys
freshness off the **git commit timestamp** of each stamp, so every PR re-signs all 9 stamps
against its own head — i.e. every PR rewrites the same 9 paths. Any two changes in flight
therefore collide on the register on merge, even when their code is completely disjoint
(O(n²) friction; observed in CondoParkShare #190 vs #191).

This is the identical pathology the audit log hit and solved in #888: many independent
writers forced through a fixed shared path. The fix is the same shape — **move each writer
to its own path so disjoint changes can never textually collide** — applied to the sign-off
register.

This design migrates the register from `signoffs/<role>.stamp` to
**`signoffs/<namespace>/<role>.stamp`**, where the namespace is a per-branch slug. Two
concurrent PRs are on two branches → two distinct directories → they never share a stamp
path, so they merge in either order without a register conflict. Freshness semantics are
unchanged: within a branch the stamp's commit timestamp is still compared against the
branch's changed files.

Note: `git config merge.ours.driver` is **not** set in this repo, so the `merge=ours`
attribute already present for `scripts/framework/validation-stamps/*.stamp` is a no-op —
a `.gitattributes` band-aid would not actually resolve the conflict. The structural fix
prevents the conflict regardless of git configuration, which is why it is preferred here
and why the issue explicitly asks to refactor *off* shared fixed-path files.

---

## 2. Namespace

```
signoff_namespace(override, branch, head_sha) -> str
    # 1. override  : --namespace flag or $HOS_SIGNOFF_NAMESPACE (highest precedence)
    # 2. branch    : `git rev-parse --abbrev-ref HEAD`, when not "HEAD" (detached)
    # 3. head_sha  : `git rev-parse --short HEAD`  (detached-HEAD / CI fallback)
    # then sanitize: lower-case nothing; replace every char not in [A-Za-z0-9._-] with "-",
    #                collapse repeats, strip leading/trailing "-".  Never empty.
```

The same derivation is implemented once in Bash (`sign_off.sh`) and once in Python
(`signoff_gate.py`); both must agree. Example: branch
`fix/968-signoff-register-per-namespace` → `fix-968-signoff-register-per-namespace`.

The override exists for CI checkouts that are detached HEAD but know the logical branch
(e.g. `HOS_SIGNOFF_NAMESPACE="$GITHUB_HEAD_REF"`).

---

## 3. Two read scopes

Freshness is judged differently in the two modes, and the migration must respect that:

- **PR / CI mode (`signoff_gate.py --base REF`)** — *namespace-scoped*. The gate resolves
  the current branch's namespace and reads only `signoffs/<ns>/<role>.stamp`. It must NOT
  aggregate across namespaces: a stamp from another branch signed *different* code and must
  not satisfy this PR. Because an unrelated PR merging to `main` touches neither this
  branch's changed-file set nor this branch's stamp directory, the gate stays green — a
  disjoint PR never needs re-signing. This is the core acceptance criterion.

- **Deploy mode (`signoff_gate.py --all`) and release gate
  (`release_artifact_logic.py`)** — *aggregating*. These ask "is the tree on `main`
  fully signed?", where `main` accumulates every merged branch's stamp directory. For each
  role they consider the union of `signoffs/*/<role>.stamp` (plus the legacy flat path) and
  take, per role, the newest valid committed stamp (deploy: must be ≥ newest tracked file;
  release: must merely exist with a valid status — release logic checks existence + status,
  not freshness). The most-recently-merged PR signed all roles against the then-current
  head, so its stamps are the newest and satisfy the tree — preserving today's guarantee,
  with the disjoint-PR relaxation the issue explicitly endorses.

---

## 4. Migration / back-compat

There are currently **no committed `*.stamp` files** in the repo, so there is no on-disk
data to migrate. For branches already in flight that wrote a legacy flat
`signoffs/<role>.stamp`, every reader treats the repo root as an implicit namespace:

- PR mode: if `signoffs/<ns>/<role>.stamp` is absent, fall back to legacy
  `signoffs/<role>.stamp`.
- Aggregating modes: the glob set includes the legacy flat path.

Consumers updated (the complete in-repo set):

| Consumer | Change |
|---|---|
| `scripts/oversight/sign_off.sh` | write `signoffs/<ns>/<role>.stamp` |
| `scripts/oversight/signoff_gate.py` | PR mode namespace-scoped (+legacy fallback); `--all` aggregates |
| `scripts/oversight/release_artifact_logic.py` | per-role existence aggregated across namespaces (+legacy) |
| `contract/OVERSIGHT-CONTRACT.md` | document `signoffs/<namespace>/<role>.stamp` (supersedes per-step #366) |
| `signoffs/README.md` | document new layout + workflow |

`scripts/deploy.sh` and `.github/workflows/signoff-gate.yml` named in the issue do **not**
exist in this repo; nothing to change there. `signoffs/validators/step{N}/summary.json`
(validator artifacts, #555) is a different surface and is untouched.

---

## 5. Acceptance mapping

- *Two disjoint PRs merge in either order without a register conflict* — each PR signs into
  its own `signoffs/<branch>/` directory; the paths are disjoint, so git never 3-way-merges
  a shared stamp. ✓
- *Freshness/staleness preserved* — PR mode keeps the commit-timestamp comparison, now
  scoped to the branch namespace; a role still goes stale if code is committed after the
  stamp without re-signing. ✓
- *Migration path specified* — §4. ✓
