# ADR-032 — First-class Astro (JS/TS) stack support: node + astro packs, JS validator parity, framework-wide fail-hard tool resolution

**Status:** Accepted — ratified by ScottThurlow 2026-07-27
**Epic:** #1029 · **Milestone:** v0.6.0 — Astro & JS Support
**Supersedes/extends:** ADR-031 (pack selection) — extends its pack-resolution model with `requires` closure
**Author:** Architect · **Authored:** 2026-07-26 · **Ratified:** 2026-07-27

---

## 1. Context

HOS runs on an Astro consumer today only as "bare CORE." The oversight loop is stack-agnostic and works. What goes dark is the **deterministic signal layer**: on an all-`.astro`/`.ts`/`.js` changeset, every `PY_FILES`-gated validator in `run_validators.sh` skips (8 of 12 dimensions), and there is no `packs/astro/`.

Three structural facts shape every decision:
1. **Central, language-gated dispatch** in `run_validators.sh` (lines 83–88, 226–306); validators invoked via `$PYTHON` with `PYTHONPATH` = validators dir.
2. **Composite = weighted average over whatever result JSONs exist** (lines 316–396); `dimension` not used in composite math, only `score`+`weight`; `error=` excluded/renormalized; zero-file → CRITICAL.
3. **Two provisioning models coexist:** HOS-internal tools in the oversight venv (`ensure_venv` hard-fails on broken build); consumer tools resolved from the project; current gates fail-**open** when a tool is absent — which D1 changes.

## 2. D10 — Where JS validators live (resolved first; scope-shaping)

**Decision.** JS validators live in the shared `scripts/oversight/validators/` dir as new separate scripts (`complexity_metrics_js.py`, `function_metrics_js.py`, `static_analysis_js.py`, `hallucination_surface_js.py`, `rn_calculator_js.py`, `n1_detector_js.py`), dispatched by the central (now language-aware) `run_validators.sh`. NOT in `packs/node/validators/`; no pack-discovered validator infra in v0.6.0.

**Consequence.** S4–S9 depend only on S1 (routing) + S2 (tools), NOT on S13. Packs carry agent region bodies only — no executable validator code.

## 3. Decisions

**D1 — consumer-toolchain resolution + framework-wide fail-hard. [RATIFIED: immediate enforce in v0.6.0]** Shared tool-preflight (`scripts/oversight/lib/detect_stack.sh`) runs before validators + gates: detects depended-on tools via repo markers (`tsconfig`→tsc; `astro` in package.json / `.astro`→astro CLI + @astrojs/check; eslint config→eslint; `.py`+pyproject→venv python tools), resolves each, and **hard-fails loudly on any missing *required* tool** (writes fail-closed CRITICAL summary; structured actionable message; HOS never installs). **Node floor ≥ 22 [RATIFIED]** when a JS/Astro project is detected. **Rollout [RATIFIED — no warn-grace]:** immediate framework-wide `enforce` in v0.6.0 for BOTH the new JS surface and the existing Python gates/validators (which flip from fail-open to fail-hard now). Rationale accepted: HOS's own venv tools are already `ensure_venv`-guaranteed, so the real regression surface is small; a consumer missing a depended-on tool will hard-fail on upgrade, which is the intended, loud behavior. Every enforce-mode failure remains suspendable via the audited `check_suspension.sh` path. (`HOS_REQUIRE_TOOLS` env may still be implemented as an escape hatch, but the default is `enforce`.)

**D2 — provisioning.** Discover-only (`scripts/oversight/lib/resolve_node_tool.sh`): `./node_modules/.bin` → `npx --no-install` → PATH. Never auto-install, never ship `node_modules`, never force-install. HOS-internal JS analysis (tree-sitter, semgrep) lives in the oversight venv (pip); consumer-owned tools (eslint/tsc/astro) discovered from the consumer. (Name it `resolve_node_tool.sh`, not `ensure_node` — it provisions nothing.)

**D3 — installer `requires` resolution (net-new).** Add a requires-closure expansion after pack resolution: transitive closure, deps-first, deduped (`astro`→`[node,astro]`); cycle → hard error; missing `requires` key → `[]` (django/testpack unchanged). `config.sh PACK=` stays **single-value**, records the leaf pack (`astro`); the closure is re-derived on both the `--pack` path and the flagless upgrade path. Region-merge: author pack bodies **additively** (node = generic JS/TS, astro = astro-specific, never contradict) so alphabetical compose order is semantically irrelevant (binding correctness guarantee). Optional/recommended: enhance `regions.py _canonical_order_key` to order PACK regions dependency-first (cosmetic; must keep django output byte-identical).

**D4 — JS complexity.** tree-sitter AST (`tree_sitter` + `tree-sitter-typescript`, venv pip), count decision points. dimension="complexity", weight=WEIGHTS["cyclomatic"] (0.08). Reuses the same AST as D5/D8.

**D5 — AST + .astro.** Same tree-sitter parse for function metrics (length/params/returns/nesting). For `.astro`: extract frontmatter fence + `<script>` blocks in pure Python, feed to tree-sitter. `@astrojs/compiler` optional, not required. dimension="function_metrics" (0.07). Documented limit: inline template expressions not scored.

**D6 — static analysis. [RATIFIED: semgrep]** `static_analysis_js.py` runs semgrep (JS/TS security rulesets, venv pip) → MEDIUM+ → dimension="static_analysis" (0.15). Pin semgrep + a vendored ruleset version (rule drift changes scores). Bump the `ensure_venv` disk-space floor for semgrep's footprint; add to the venv smoke test.

**D7 — RN calibration (provisional). [RATIFIED]** `rn_calculator_js.py` reuses Python-derived nesting weights + tree-sitter JS metrics; explicitly marked provisional in `raw_value` (`"calibration": "provisional-js-reuses-python-weights"`) and in DECISIONS.md. dimension="risk_number" (0.18). Follow-up: recalibrate from JS defect data; the provisional flag must reach the risk-assessor's inspection brief.

**D8 — N+1 analog.** Lightweight heuristic (`n1_detector_js.py`): await/fetch/DB-client calls inside loop bodies (`for`/`while`/`.forEach`/`.map`/`.filter`). dimension="n1_queries" (0.08), `raw_value.heuristic="provisional"`. AC-1 met without it → additive insurance, lowest priority; may degrade to `error=`/N/A if noisy.

**D9 — astro_check.sh.** `astro sync` then `astro check` (Django `manage.py check` analog; no `astro build`). No-op when not an Astro project. Division of labor: `type_check.sh` (S11) does `tsc --noEmit` for plain-TS and DEFERS (SKIP) when Astro detected; `astro_check.sh` (S12) owns Astro projects; `lint_check.sh` (S10) resolves consumer eslint via the D2 resolver.

## 4. Validator interface contract

Each JS validator: a Python script in `validators/` that emits the `make_result()` envelope with the **same `dimension` string + `weight=WEIGHTS[...]`** as its Python sibling (WEIGHTS/TIER_THRESHOLDS read-only — AC-3); dispatched by the extended `run_validators.sh` (S1 derives `JS_FILES` parallel to the **unchanged** `PY_FILES`/`ALL_FILES`, guarded `[[ ${#JS_FILES[@]} -gt 0 ]]`); writes a distinct filename per (dimension, language) e.g. `complexity_js.json`.

**AC-2 mechanism.** Python-only changeset → `JS_FILES` empty → JS block skipped → no `*_js.json` → aggregator sees identical inputs → identical composite/tier. S1 must leave `PY_FILES`/`ALL_FILES` derivation exactly as-is and extend the `RUN_VALIDATORS_FILELIST_ONLY` seam to also emit `JS_FILES` (regression guard).

**Mixed changeset.** A dimension present in both languages contributes twice to the weighted average (accepted: biases toward more scrutiny, never less; never affects single-language paths so AC-2 stands). Document in DECISIONS.md; revisit only if dogfood shows distortion — do not pre-build merge logic.

**Un-gate stack-neutral dimensions:** `prompt_audit_risk` (prompt_ambiguity) also fires on `JS_FILES`; `portability_check` gets a JS-aware extension (S19).

**AC-1 count (≥10/12 on all-JS):** 5 new JS validators (risk_number, complexity, function_metrics, static_analysis, hallucination_surface) + 4 already `ALL_FILES`-agnostic (migration_risk, historical_density, ip_check, diff_size) + prompt_ambiguity = **10**; +n1_queries +JS portability = **11–12**. Met with margin.

## 5. Pack architecture

- `packs/node/` (`requires=[]`) — generic JS/TS region bodies for the 12 agents the django pack covers (vitest/playwright, lint/type expectations, npm review lenses).
- `packs/astro/` (`requires=["node"]`) — Astro depth layered **additively** on node (islands/`client:*`, SSR/SSG/hybrid, content collections, endpoints/middleware, `set:html`/`PUBLIC_` security, view transitions/scoped styles, adapters).
- Layering realized by D3's `requires`-closure. No executable code in packs.

## 6. Migration / rollout

1. **S1 first**, regression-guarded (byte-identical Python fixture, AC-2) before any JS validator is wired.
2. **D1 immediate enforce** framework-wide in v0.6.0 (JS + existing Python), single preflight enforcement point; audited suspension retained.
3. **Venv additions** (tree-sitter, tree-sitter-typescript, semgrep + pinned rules) with S2/S4–S6: pin versions, add to `ensure_venv` smoke test, raise disk floor for semgrep.
4. **Packs after validators**; S3 (`requires` resolution) before S16 (`packs/astro` install).
5. **Dogfood last (S20)** on a real Astro consumer — the evidence for the mixed-weighting, RN-provisional, N+1-heuristic, and fence-extraction assumptions.

## 7. Consequences summary

- schema.py WEIGHTS/TIER_THRESHOLDS: **unchanged** (AC-3).
- Python-only changesets: **byte-identical** composite/tier (AC-2), test-guarded.
- All-JS changesets: **11–12/12** dimensions emit real signal (AC-1).
- Gates: eslint + `astro check`/`tsc` block in an Astro project, no-op elsewhere (AC-4).
- `hos_install.sh --pack astro` resolves+injects node; `--pack node` standalone (AC-5).
- **New framework-wide behavior:** depended-on-but-missing tools hard-fail immediately (D1); Node floor ≥22.
- **New venv weight:** tree-sitter + semgrep.

## 8. Governance note

Net-new capability — no orphaned sign-offs. The one cross-cutting item (D1 fail-hard applied to existing Python gates/validators, now immediate) is a framework-wide correction; technical-design must treat the `run_validators.sh` routing change and any `regions.py` compose-order tweak as governance-critical (full review chain, not a light pass).

## 9. Ratified decisions (previously open)

1. **D1 rollout — immediate framework-wide enforce in v0.6.0** (no warn-grace). ✅ ratified 2026-07-27.
2. **D6 — semgrep** (accept heavier venv). ✅ ratified 2026-07-27.
3. **Node floor — ≥ 22.** ✅ ratified 2026-07-27.

Everything else is architect-decided and ready for `technical-design` and `coder`.

## Grounding paths
- `scripts/oversight/run_validators.sh` (S1), `validators/schema.py` (AC-3), `validators/regions.py` (D3 ~604–631), `ensure_venv.sh` (D2/D4/D6), `gates/{lint,type,django}_check.sh` (D1/D9), `bootstrap/hos_install.sh` (D3 ~1091–1211), `packs/django/pack.toml`
