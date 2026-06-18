# Technical Design — SPEC-267: Structural-Override Auth File Enumeration

**Spec:** `docs/specs/SPEC-267-structural-override-auth-enumeration.md`
**Issue:** #267
**ADR / Architect ruling:** GO (bindings recorded below)
**Author:** technical-design
**Date:** 2026-06-17
**Status:** For architect review

---

## 0. Architect bindings (authoritative constraints)

These four bindings from the architect's ruling govern the design. Where the spec
and a binding could be read differently, the binding wins.

1. **Exact-path match only.** Path comparison uses exact-string equality after
   canonicalization — no prefix match, no basename match, no directory-containment
   match. Canonicalization (§3.1) is applied to **both** sides before comparing.
2. **Single edit site in the evaluator.** The behavior change lands in the
   **structural-override skip predicate at evaluator line ~137**. The
   **effective-human-gate at line ~116 is NOT touched.** A disambiguating comment is
   added so a future reader does not conflate the two human-gate code paths.
3. **Grandfathering keyed on commit-era, not field-absence.** Whether a missing
   `reviewed_files:` field is a FAIL or a WARN is decided by **when the auth file was
   committed relative to this spec's ship**, not merely by whether the field is
   present. And: **the skip denial is unconditional** — when the enumeration does not
   overlap the diff, condition 10 runs even if the era ruling only produced a WARN. The
   audit signal (WARN/FAIL) and the gate (skip allowed?) are independent.
4. **Contract schema update.** `reviewed_files:` is added as a **required** field of
   the human-authorization file schema in `OVERSIGHT-CONTRACT.md`, with an explicit
   legacy-WARN note for pre-ship files.

---

## 1. Problem restated (contract terms)

Contract §7 condition 10 fires a COMPLIANCE FAIL when the diff carries a
structural-override signature (§2a) and no covering human-authorization artifact
exists. The evaluator's condition-10 **skip** (evaluator ~line 137) currently accepts
any present, non-empty `step{N}-human-authorization.md` as sufficient coverage. The
skip is justified by *existence*, not by *coverage of the diff*. This design tightens
the skip predicate so the auth file must *enumerate* a file that is actually in the
diff before the skip is honored.

This is a tightening of an existing condition, not a new condition. No new compliance
condition number is introduced; no condition is reordered or removed.

---

## 2. Data model — auth file schema (contract)

### 2.1 File: `.claudetmp/oversight/step{N}-human-authorization.md`

| Field | Type | Required | Constraint |
|---|---|---|---|
| `Authorized:` | ISO-8601 date string | yes (existing) | unchanged |
| `Decision:` | freeform text | yes (existing) | unchanged; no format validator |
| `Authorized by:` | string (name) | yes (existing) | unchanged |
| `reviewed_files:` | YAML-style list | **yes (new, era-gated)** | ≥1 entry; see §2.2 |

### 2.2 `reviewed_files:` field grammar

```
reviewed_files:
  - {path}
  - {path}
```

- The field header is the literal line `reviewed_files:` (case-insensitive on the key,
  matching the evaluator's existing tolerant `grep -i` field parsing).
- Each entry is a line whose first non-whitespace content is `- ` followed by a path.
- Entry paths are **relative to the project root**, matching the form emitted by
  `git diff --name-only`.
- **Empty list** (`reviewed_files:` header present, zero `- ` entries) is treated
  **identically to an absent field** (§3.4 R3).

**Invariant:** the field's *presence and non-emptiness* is a schema concern (drives
WARN/FAIL era ruling); the field's *overlap with the diff* is a gate concern (drives
skip allowed/denied). The two are evaluated independently (binding 3).

---

## 3. Algorithms

### 3.1 Path canonicalization (binding 1)

Applied to every path on both sides (auth-file entries and diff entries) before any
comparison:

1. Strip leading and trailing ASCII whitespace from the path token.
2. Strip surrounding quotes if the whole token is quoted (`"..."` or `'...'`) — git
   may quote paths containing special characters; auth-file authors may quote by habit.
3. Strip a single leading `./` if present.
4. Do **not** alter case, do **not** resolve symlinks, do **not** collapse `..`, do
   **not** lowercase. Comparison is case-sensitive and byte-exact after the above.

Comparison operator: exact string equality of two canonicalized paths. No prefix,
basename, or containment matching (binding 1).

### 3.2 Diff file set

The diff surface for the step is the set:

```
git diff --name-only {BASE_SHA}..{HEAD_SHA}
```

`BASE_SHA` / `HEAD_SHA` come from the register header's commit range — the same range
condition 10 already uses for `change_classifier.py`. Each output line is canonicalized
per §3.1. Call this set `D`.

### 3.3 Enumeration set

Parse `reviewed_files:` from the auth file: collect every `- ` entry line under the
`reviewed_files:` header until a non-list, non-blank line or EOF. Canonicalize each per
§3.1. Call this set `R`.

### 3.4 Skip predicate (evaluator ~line 137) — replaces the existing predicate

Let an auth file `step{N}-human-authorization.md` be **present** (exists and non-empty).

```
if not present:
    skip is NOT taken → condition 10 runs (unchanged existing behavior, R3/AC-5)
else:
    parse R from reviewed_files
    compute overlap = R ∩ D   (exact-match per §3.1)
    if overlap is non-empty:
        SKIP condition 10  → report the overlapping file(s) used (AC-1, AC-8)
    else:
        DO NOT SKIP → condition 10 runs (AC-2, AC-3, AC-4)
        report: diff files that triggered the structural signal,
                and R entries that did not match D (R3 / AC-2)
```

**The skip denial in the else branch is unconditional** with respect to the era
ruling (binding 3): even when §3.5 yields only a WARN (legacy file), the skip is still
denied whenever `overlap` is empty. Condition 10 then runs and may itself FAIL on an
uncovered structural signal — that is the existing condition-10 behavior, not new.

### 3.5 Commit-era WARN/FAIL ruling (binding 3, R1)

This ruling produces the **audit signal** (WARN vs FAIL) for a present auth file whose
`reviewed_files:` field is absent or empty. It does **not** decide whether the skip is
taken (that is §3.4, which already denied the skip whenever overlap is empty).

Determine the auth file's **commit era** relative to the spec ship commit:

- **Ship marker:** the commit that merges this SPEC-267 change to the integration
  branch. The evaluator determines era by the commit that introduced the auth file
  into the diff range. Concretely:

```
# Did the auth file get committed, and when, relative to ship?
AUTH_COMMIT_DATE = git log -1 --format=%cI -- .claudetmp/oversight/step{N}-human-authorization.md
```

Because `.claudetmp/` is untracked, an auth file usually has **no commit history**. The
era rule therefore resolves as:

| Situation | Era | Field absent/empty ⇒ |
|---|---|---|
| Auth file has a commit predating the SPEC-267 ship commit | BEFORE ship | **COMPLIANCE WARN** (grandfathered, R1) |
| Auth file committed at/after ship, OR untracked/created after ship | AFTER ship | **COMPLIANCE FAIL** (R1, AC-6 transition note) |

**Operational determination the evaluator uses** (since `.claudetmp` is untracked, the
common case is "created now"):

1. If the auth file is tracked in git AND its introducing commit predates the
   SPEC-267 ship commit → **WARN**.
2. Otherwise (untracked working-tree file, or committed at/after ship) → the file is
   being authored under the new schema → **FAIL** when `reviewed_files:` is
   absent/empty.

**Rationale for keying on commit-era not field-absence:** a field-absence-only rule
would WARN forever and never graduate to FAIL, leaving the schema permanently
optional. Keying on era means: histories sealed before the spec stay valid (no
retroactive FAIL, R1/§4), while any file an agent or human writes *now* is held to the
required-field standard.

### 3.6 Reporting (R3, AC-2, AC-8)

When the skip is denied because overlap is empty, the evaluator's Phase-1 output lists:

- `structural_signals` files from `change_classifier.py --structural-only` (the diff
  files that triggered the signal), and
- the `reviewed_files:` entries that did not intersect `D` (the coverage gap).

When the skip is taken, the output names the overlapping file(s) that justified it
(AC-8).

---

## 4. Interface / route surface

No runtime route or endpoint changes. Affected surfaces are documents:

| Surface | Change | Section |
|---|---|---|
| `.claude/agents/oversight-evaluator.md` ~line 137 | Replace skip predicate; add disambiguating comment vs line ~116 | §3.4, §3.5 |
| `contract/OVERSIGHT-CONTRACT.md` §1 (auth file note) + auth schema | Add `reviewed_files:` required field + legacy WARN note | §2 |
| `contract/OVERSIGHT-CONTRACT.md` §7 condition 10 | Restate skip as enumeration-overlap, not existence | §3.4 |
| `.claude/agents/oversight-orchestrator.md` ESCALATE block | Add `reviewed_files:` to the example + guidance note | §5 |

**Boundary — line ~116 effective-human-gate is OUT of scope (binding 2).** Line ~116
governs *whether a human-authorization file must exist at all* (gate-firing). Line ~137
governs *whether an existing auth file is sufficient to skip condition 10*
(skip-sufficiency). They are different determinations on the same artifact and must not
be merged. A disambiguating comment is added at line ~137 stating this.

---

## 5. Orchestrator ESCALATE prompt contract (R4, AC-7)

The CRITICAL STEP AUTHORIZATION REQUIRED block's example file content must include the
`reviewed_files:` field with example entries, and the instruction text must direct the
human to list **only the files they actually reviewed from the diff** — not the whole
repo, not unrelated files. Exhaustive coverage is not required (a single overlapping
file satisfies the gate, §4 non-requirement), but the listed files must be real diff
files the human read.

---

## 6. Acceptance-criteria traceability

| AC | Satisfied by |
|---|---|
| AC-1 | §3.4 overlap non-empty → skip; §3.6 reports overlap |
| AC-2 | §3.4 else branch + §3.6 reporting |
| AC-3 | §3.5 era ruling → WARN legacy / FAIL new; §3.4 still runs cond 10 |
| AC-4 | §2.2 empty list ≡ absent; §3.4 else branch |
| AC-5 | §3.4 not-present branch (unchanged) |
| AC-6 | §3.5 era ruling, FAIL for new file lacking field; overlapping new file passes |
| AC-7 | §5 orchestrator example |
| AC-8 | §3.6 names overlapping file used for the skip |

---

## 7. HOS self-flag

**Classification:** `clarifying` for condition 10 (tightening an existing skip
predicate, no new condition), `additive` for the contract schema field and the
orchestrator example.

RISK: MEDIUM — the change governs an anti-gaming human gate; an over-broad match
(prefix/basename) could re-open the gaming hole the spec closes, and an over-strict era
ruling could retroactively FAIL sealed histories. Both are bounded by binding 1
(exact-match) and binding 3 (era-keyed grandfathering).
CONFIDENCE: HIGH — the edit sites are localized and the predicate is deterministic.
BLAST RADIUS: oversight-evaluator condition-10 skip path; contract auth schema;
orchestrator ESCALATE example. No application-code path; no migration.

## Human Review Required

- Confirm the SPEC-267 ship-commit marker used for the commit-era ruling (§3.5) is the
  intended boundary, since `.claudetmp/` auth files are normally untracked and resolve
  to "AFTER ship ⇒ FAIL on missing field."
- Confirm exact-match-only is acceptable given humans may hand-type `reviewed_files:`
  paths (a typo yields no overlap → skip denied → condition 10 runs). This is the
  fail-toward-review direction and is intended.
