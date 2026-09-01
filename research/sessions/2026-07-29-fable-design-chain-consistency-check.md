# Session record — Fable design-chain consistency pass (2026-07-29)

> **Archival note (committed 2026-07-31).** Verbatim record of a manual design-chain
> consistency check, moved here from the gitignored `.claudetmp/design/` so it is
> durable evidence rather than local working state. Content below is unmodified.
>
> - Model: **Fable** (Claude family, rank 4). Same family as the authoring chain —
>   this pass added review *scope and framing*, not vendor independence.
> - Generalized lesson: `research/findings/cross-artifact-drift-survives-per-artifact-review.md`
> - Mechanism proposal: **#1078** · comparative result + confound: **#1082** ·
>   governing-artifacts-under-review: **#1079**
> - Motivated the completeness lens in **ADR-033** (dual-lens spec-review gate).
> - **This is a different event from the 2026-07-14 whole-codebase audit** that
>   produced issues **#972–#1002**. Do not conflate them.

---

## 🔴 Fable consistency pass — BLOCKER found. Do NOT apply the corrected decomposition as written.

Run 2026-07-29 as a manual design-chain consistency check over ADR-032 → epic spec → corrected decomposition → tickets #1060–#1074. Fable was given the seven already-known defects and asked to find what that list *misses*. This is the first real exercise of the mechanism proposed in #1078, run deliberately out of process.

### 🔴 BLOCKER — B1: the Task-4 action table swaps #1072 and #1073

**Verified against GitHub:**
- **#1072** = `[S16] packs/astro: agent pack body + pack.toml requires=["node"] + installer integration` — the **mega-ticket**
- **#1073** = `[S17] packs/astro: review-agent 'find-the-defect' framing + execution output` — the **micro-ticket**

The decomposition states the opposite, consistently — in the intro (*"closes four micro-tickets (#1070/#1071/**#1072**/#1074)"*), in the Task-4 table (*"| **#1073** | S16 packs/astro+install | SPLIT into 3 |"*), and in three section headers (*"split from filed S16 **#1073**"*).

Because the document instructs *"treat the table, not the S-labels, as authoritative"*, **verbatim application would close the astro pack mega-ticket as a folded micro-ticket, and split the tiny framing ticket into three.** Every #1072/#1073 reference must be swapped before anything is applied.

### MAJOR

**M1 — #1063/#1064 direct in-place edits of Python validators, contradicting ratified D10 and already-merged code.** #1064 says *"Extend `rn_calculator.py` to accept the JS metric inputs"*; #1063 says *"Extend `hallucination_surface.py`'s version-sensitive API table"*. D10 rules JS validators are **new separate scripts** (`rn_calculator_js.py`, `hallucination_surface_js.py`), and the merged S1 dispatcher **already calls those filenames** (`run_validators.sh:285-293`). As written the tickets cannot be implemented without breaking the wiring, and in-place edits endanger AC-2 byte-identical. The decomposition's own S7/S8 sections use `_js` filenames but its EDIT rows don't strike the extend-in-place language.

**M2 — the tree-sitter venv addition is orphaned.** S-AST claims *"Depends: S2 (tree-sitter in the oversight venv)"* — false. S2/#1035 (merged) shipped preflight + resolver only; `scripts/oversight/requirements.txt` has `semgrep>=1.50` and **no tree-sitter**. The venv work lives in #1060, which the decomposition makes depend on S-AST — so S-AST needs a library installed by a ticket that depends on S-AST. ADR §6.3's pin + `ensure_venv` smoke-test items have no owner.

**M3 — #1066 preserves the fail-open behavior D1 ratified away.** #1066 says *"exit 0 when the tool is absent"*; D1 explicitly changed gates from fail-open to hard-fail on a missing **required** tool. The S10 edit adds the S2 dep but keeps the exit-0 language without distinguishing **no linter configured** (legitimate no-op) from **configured-but-unresolvable** (must hard-fail). This re-imports pre-D1 epic wording over a ratified ruling.

**M4 — the #1081 additive-only decision breaks S13's stated content.** S13's node bodies carry *"eslint/tsc expectations"*, but D9 rules `type_check.sh` **DEFERS/SKIPs** on Astro projects (`astro_check.sh` owns them). Under additive-only (just decided in #1081), **the astro body cannot retract node's tsc guidance** — astro consumers get composed agents carrying "expect `tsc --noEmit`" prose that contradicts actual gate behavior. Same shape for node's "vitest/**jest**" vs astro's vitest-only Container API.

> **This is the most consequential finding after B1.** The additive-discipline AC currently sits only on S14/S15/S16 — the **astro** side, which is precisely the side that *cannot* fix it. The fix belongs on the **node** side: S13 needs an AC requiring its bodies be phrased framework-conditionally ("…unless a framework checker owns type-checking"). Direct downstream consequence of the #1081 ruling, surfaced within hours of making it.

### MINOR

- **m1** — stale "S11" references survive the S6b rename: S9's text says *"unawaited-rejection is S11"*, but S11 is the type_check gate (#1067). Applied verbatim, the boundary note points at the wrong ticket.
- **m2** — silently dropped requirements: *"coverage targets mapped to pack conventions"* (epic Phase 3 + #1074) is absent from S15's AC; #1070's second improvement (*"hand the reviewer actual test/execution output, not just the diff"*) survives only as the unexpanded phrase "#1037 framing present" and is never named in any fold-target AC.
- **m3** — #1061 still carries pre-ADR tool candidates (`ts-morph`, `@typescript-eslint/typescript-estree`, `@astrojs/compiler`) contradicting ratified D4/D5 (tree-sitter via venv pip; **pure-Python** fence extraction). The EDIT row doesn't strike them.
- **m4** — table miscount: *"#1069 … expand from **4** to all 12"* — #1069 actually enumerates 5.

### ✅ Where the chain is sound

- **Epic → ADR is clean.** Every ADR deviation from the epic (D10's shared-dir validators; D9's `sync`+`check`; Node ≥22 answering the ≥20 open question) is an explicit ruled decision, not silent drift.
- **All six epic ACs are reachable.** AC-1's load-bearing `prompt_ambiguity` un-gating is already delivered (`run_validators.sh:363-367`, merged with #1034). `portability_check` is still `PY_FILES`-gated (line 353), so S17 is genuinely needed for the 11–12 count — but AC-1 (≥10) holds without it.
- **S14+S15 partition exactly the django 12** with no gap or overlap (verified against `packs/django/`), and the wave graph is internally consistent.

---

**Method note for #1078.** Fable found B1, M1, M2, M3 and M4 — none of which agy, codex, or the `technical-design` agent caught, across three prior review passes. B1 in particular is a pure cross-artifact referential error: every individual document is coherent, but the table's issue numbers don't match reality. That is exactly the inter-artifact drift class #1078 exists to catch, and it argues the deep-reasoning consistency pass earns its place in that panel.
