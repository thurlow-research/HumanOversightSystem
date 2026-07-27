# Technical Design — Astro/JS Support, Wave 1 (S1, S2, S3)

**Milestone:** v0.6.0 — Astro & JS Support
**Epic:** #1029
**ADR:** [`docs/v0.6.0/ADR-032-astro-js-support.md`](../v0.6.0/ADR-032-astro-js-support.md) (ratified 2026-07-27)
**Status:** Approved for implementation — design-question dispositions below
**Author:** technical-design · **Date:** 2026-07-27

> Binding input is ADR-032; this design implements its D-rulings and does not relitigate them. Each of S1/S2/S3 is self-contained enough to become one child issue.

## Design-question dispositions

| DQ | Disposition |
|----|-------------|
| DQ-1 (JS ext match case-sensitive lowercase, mirrors `*.py`) | Accepted — `.TS`/`.ASTRO` need not match. |
| DQ-2 (preflight only in orchestrators; standalone gate calls bypass) | Accepted — pipeline always enters via `run_validators.sh`/`run_gates.sh`. |
| DQ-3 (D1 flip: preflight-only vs convert every SKIP branch) | **(a) preflight-only.** `ensure_venv` already hard-fails when the venv can't build, so venv tools are guaranteed present; the per-tool `SKIP` branches are dead safety nets. Preflight adds the missing *consumer-tool* fail-hard. Converting every SKIP branch is NOT in scope. |
| DQ-4 (`prompt_audit_risk.py` tolerates a JS positional arg) | Coder verifies before shipping S1.4; if it inspects file bodies Python-specifically, defer the prompt-ambiguity un-gate to S19 and ship S1 without S1.4. |
| DQ-5 (AC-2 composite golden source) | Coder: prefer the `test_validators_mocked.py` stable-composite baseline; else capture a golden from pre-S1 `main` during the S1 PR. |
| DQ-6 (`resolve_node_tool` `--version` probe) | Accepted for the tool set {eslint, tsc, astro} (all support `--version`). Do not add a tool lacking `--version` without revisiting. |
| DQ-7 (`requires` parser single-line only) | Accepted — document "single-line `requires` array" as a pack-authoring rule in S19. |
| DQ-8 (`regions.py` compose-order tweak) | **Deferred to v0.7.0** (cosmetic; correctness rests on additive pack authoring). Document in DECISIONS.md that PACK regions compose alphabetically and MUST be authored additively. |
| DQ-9 (installed `config.sh` path) | Coder confirms against `_subst_config` in `hos_install.sh` before asserting in the S3 test. |

## Overseer-review carry-ins (PR #1031)
- **D1 immediate framework-wide enforce is the governance-critical item.** It flips the control surface itself (`scripts/oversight/gates/**`, `run_validators.sh`) from fail-open to hard-fail. This is a **hard precondition** on the S1/S2 child slices: full review chain (code + security + reliability + ops), not a light pass.
- **Mixed-changeset double-counting must be measured in S20**, not merely revisited-if-distorted: a dimension present in both languages contributes twice to the weighted average, so the *realized* weighting differs from `WEIGHTS` on mixed diffs even though `WEIGHTS` is literally unchanged (AC-3 holds literally). S20's dogfood field report must record the mixed-diff composite behavior on Tutelare.

---

## S1 — Language-aware routing in `run_validators.sh`  [PROTECTED SURFACE — full review chain]

**Files:** `scripts/oversight/run_validators.sh` (modify); `tests/oversight/test_run_validators_js_routing.py` (new); `tests/oversight/test_run_validators_byte_identical.py` (new — AC-2 guard, **ships with S1**).

**S1.1 — `JS_FILES` derivation.** In the existing file-filter loop (~L82–88), leave `PY_FILES`/`ALL_FILES` derivation **byte-for-byte unchanged**; add a parallel `JS_FILES` pass. Single-source the extension set:
```bash
JS_EXTS_RE='\.(ts|tsx|js|jsx|astro|mjs|cjs)$'
# ... in the loop, alongside the UNCHANGED ALL_FILES/PY_FILES lines:
[[ "$f" =~ $JS_EXTS_RE && -f "$f" ]] && JS_FILES+=("$f")
```
Existing-files-only (`-f`), lowercase extensions (DQ-1).

**S1.2 — Extend `RUN_VALIDATORS_FILELIST_ONLY` seam** (~L111–115) to also emit `JS_FILES\t<f>` lines, appended after the existing `ALL_FILES`/`PY_FILES` emissions (existing seam parsers unaffected). This is the deterministic regression harness.

**S1.3 — JS dispatch block**, inserted after the Python dispatch (~after L238), guarded `[[ ${#JS_FILES[@]} -gt 0 ]]`. `run_validator` NAME carries the `_js` suffix → distinct outfile (`complexity_js.json`). Reuse `RN_EXTRA` for `risk_number_js` (same guard pattern as the Python RN call). Calls: `risk_number_js`, `complexity_js`, `function_metrics_js`, `n1_queries_js`, `static_analysis_js` (120s), `hallucination_js` → `$VALIDATORS_DIR/*_js.py`. `run_validator` SKIPs a missing script cleanly, so **S1 is shippable ahead of S4–S9**.

**S1.4 — Un-gate `prompt_ambiguity`** (stack-neutral): change its guard (~L302) to `[[ ${#PY_FILES[@]} -gt 0 || ${#JS_FILES[@]} -gt 0 ]]` and pass the union `_PA_FILES=(PY_FILES + JS_FILES)`. AC-2 safe: on a Python-only changeset `JS_FILES` is empty, so `_PA_FILES == PY_FILES` and the argv is identical. `portability` un-gate stays S19. (DQ-4: verify `prompt_audit_risk.py` tolerates a JS path arg first.)

**S1.5 — Aggregator: NO change.** It globs `*.json` and reads `dimension`/`score`/`weight`/`error` (filename-agnostic). The distinct-filename design means no merge logic. **Mixed-changeset double-count is accepted (ADR §4) → document in DECISIONS.md as part of S1, and flag the S20 measurement (overseer carry-in).**

**Tests.** (1) seam-level: Python-only diff → `JS_FILES==[]`, `ALL_FILES`/`PY_FILES` identical (mechanical AC-2). (2) composite golden: full run on a mocked Python-only fixture == pre-S1 baseline (the actual AC-2 assertion; DQ-5). (3) routing: mixed diff → all 7 exts in `JS_FILES`, `PY_FILES` unaffected. (4) JS-only with `*_js.py` absent → still exits 0 (SKIP), non-CRITICAL if any `ALL_FILES` validator succeeds.

**AC:** AC-2 (both tests, mandatory), AC-1 routing foundation, AC-3 (no schema/aggregator edit).

---

## S2 — Tool preflight + resolver (D1 + D2)  [framework-wide fail-open→fail-hard flip — full review chain]

**Files:** `scripts/oversight/lib/detect_stack.sh` (new); `scripts/oversight/lib/resolve_node_tool.sh` (new); `run_validators.sh` + `run_gates.sh` (source + call); tests (new).

**S2.1 — `resolve_node_tool.sh` (discover-only; provisions NOTHING).** Sourced lib. `resolve_node_tool <tool>` resolution order (D2): `./node_modules/.bin/<tool>` → `npx --no-install <tool>` (probe `--version`, no network install) → `PATH`; prints an invocable command + rc0 when found, rc1 + nothing when not. Never installs, never ships `node_modules`. Safe under caller `set -euo pipefail`.

**S2.2 — `detect_stack.sh`** (sourced). `detect_required_tools()` maps repo markers → required-tool keys per ADR D1: `tsconfig.json`→`tsc`; `astro` in `package.json` deps **or** any `.astro`→`astro`+`astro-check`; eslint config→`eslint`; any JS/Astro marker→`node-floor` (Node **≥ 22**). Python venv tools are NOT listed (ensure_venv-guaranteed). `tool_preflight_or_fail()`: honors `is_suspended "tools"` audited escape hatch; resolves each required tool; on any missing → structured actionable stderr + rc1. Default `enforce`; `HOS_REQUIRE_TOOLS=warn` downgrades to non-fatal WARN (escape hatch, not default). Detection keys off **repo markers**, not lone file extensions.

**S2.3 — Wire into `run_validators.sh`:** source the lib; call `tool_preflight_or_fail` **after** the `RUN_VALIDATORS_FILELIST_ONLY` seam (so the regression harness in a bare tmp repo never triggers a tool check) and **before** the validator loop. On failure, write the same fail-closed CRITICAL `summary.json` shape as the zero-file path, then `exit 1`.

**S2.4 — Wire into `run_gates.sh`:** source + call before the gate loop; on failure exit 1 (structured stderr already emitted).

**S2.5 — Venv additions are S4–S6 scope, not S2.** `tree_sitter` + `tree-sitter-typescript` + pinned semgrep ruleset (and the `ensure_venv` smoke-test + disk-floor bump) land with S4–S6 per ADR §6.3. S2 does not touch `ensure_venv.sh`.

**Tests:** detect table (tsconfig→tsc,node-floor; .astro→astro,astro-check,node-floor; no JS→empty); preflight all-present/missing/node<22/warn/suspended; resolver order (node_modules/.bin vs PATH); AC-2 non-regression (`RUN_VALIDATORS_FILELIST_ONLY=1` in a bare Python repo still exit 0 — preflight is after the seam).

**AC:** AC-4 (eslint/`astro check`/`tsc` become required in a JS/Astro project, no-op elsewhere); D1 immediate enforce (default `enforce`, `warn` escape hatch, `check_suspension "tools"` audited bypass); Node ≥ 22 floor.

---

## S3 — Installer `requires`-closure (D3)  [PROTECTED SURFACE — full review chain]

**Files:** `bootstrap/hos_install.sh` (modify — insert closure step R2c between R2 ~L1147 and R2b ~L1154; tweak R4 ~L1186); `tests/framework/test_requires_closure.py` (new); throwaway fixture packs `packs/testpack-dep` (`requires=["testpack"]`), `packs/testcycle-a`/`-b` (mutual).

**S3.1 — `_pack_requires(dir)`:** parse single-line `requires = [...]` from `pack.toml` via grep/sed (no TOML lib, bash 3.2 safe); missing key → `[]` (django/testpack unchanged). Single-line array only (DQ-7 → pack-authoring rule).

**S3.2 — Closure expansion (R2c):** DFS post-order (deps-first), deduped, cycle → hard error (in-progress stack). Runs on `_resolved_packs` (populated from either the `--pack` path or the flagless upgrade path that reads `config.sh PACK=`), then replaces `_resolved_packs` with the closure. `--pack astro`→`(node astro)`; `--pack node`→`(node)`. Unknown pack in the walk → hard error (same surface as R3).

**S3.3 — R4 tweak:** warn on "untested multi-pack" only when the **operator-selected leaf count** `_leaf_count > 1`, not when a single leaf's closure expanded to >1 (that's intended dependency layering).

**S3.4 — R5 UNCHANGED:** `config.sh PACK=` records the **leaf** only (single-value); the closure is re-derived on every upgrade. Coder must NOT widen `PACK=` to multi-value.

**S3.5 — `regions.py` compose-order:** DEFERRED (DQ-8). Pack bodies MUST be authored additively (node = generic JS/TS, astro = astro-specific, never contradicting); alphabetical compose order is then semantically irrelevant. Document in DECISIONS.md.

**Tests (fixtures, no dependency on S13/S16):** `--pack testpack-dep` injects both `PACK:testpack` and `PACK:testpack-dep`; standalone leaf → no phantom deps; flagless upgrade reconstructs closure from `config.sh PACK=` (leaf); cycle → hard error, nothing written; `config.sh` records leaf only (DQ-9). **The real `--pack astro`→node assertion is deferred to S16** (packs/astro doesn't exist until then) — flag this in both the S3 and S16 child issues so AC-5 isn't "done" until the real assertion lands.

**AC:** AC-5 (mechanism proven via fixtures; concrete astro→node in S16).

---

## Sequencing within Wave 1
- **S1 first** (ADR §6.1) — the byte-identical guard must land before any JS validator. S1's JS dispatch references `*_js.py` that don't exist until S4–S9; they SKIP cleanly, so S1 is independently green.
- **S2** independent of S1 except two source+call lines near the top of `run_validators.sh` — merge S1 first, then rebase S2.
- **S3** fully independent (installer only).

## Protected-surface note
S1 (composite scoring), S2 (framework-wide fail-hard flip of the control surface), and S3 (installer) each require the **full review chain** (code + security + reliability + ops/infra), per ADR §8 and the overseer's PR-#1031 carry-in — not a light pass.
