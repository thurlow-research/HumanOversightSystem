# Technical Design — #2014 chunked cross-vendor review for oversized input (#1718 F1)

Status: round 1, **architect-reviewed 2026-10-08: APPROVED WITH CONDITIONS** (§13, AR-1..AR-14).
The coder may start slice S1a now. S1b and S2 are gated on the human ESC items listed in §13.
Issue: #2014 (priority:high, v0.7.0). Parent: #1718 (design §9 F1, rulings AR-2/AR-7/AR-9).
Related: #2016 / ADR-1340 carve-out (c) (panel chunking), #2015 (F5), #2033 (validate_agents, out of
scope), #2032 and #2036 (open aggregation bugs; this design depends on neither), #314 (Python for logic).
Change class: **additive** for the primitive. **Structural** for the two release validators (their
prompt is decomposed). That part goes to a human before coding (§9, ESC-1..3).

RISK: HIGH. CONFIDENCE: MEDIUM. The byte accounting and coverage proofs are exact. The weak points
are cross-chunk recall (§6) and wall time (§7), and neither can be measured hermetically.

## 1. Problem (restated as a contract gap)

`vendor_invoke` refuses any agy prompt over `vendor_invoke_max_bytes agy` (180,000 B), returning
`harness/prompt_too_large` (scripts/oversight/lib/vendor_invoke.sh:308-320). No caller in scope can
split its input, so a legitimately large input is refused outright.

Measured on the working tree, 2026-10-08:

| Caller | agy prompt | Lens shape | Consequence today |
|---|---|---|---|
| framework/validate_docs.sh (release Phase 3) | ≈ 660 KB: 31 agent files 482 KB, 4 docs 159 KB (docs/AGENTS.md 82 KB), patterns 7 KB, decisions 11 KB | doc ↔ agent pairs | Refused, so **release cut blocked** |
| framework/validate_spec_compliance.sh (Phase 4) | ≈ 730 KB: governance 93 KB (METHODOLOGY 57 KB), agents 482 KB, 4 scripts 158 KB | requirement ↔ implementation pairs | Refused, so **release cut blocked** |
| run_second_review.sh (mandatory pre-PR) | template + spec + digest + diff | per-file diff | Diff over ≈ 170 KB is refused. Last 54 merge commits on main: 4 had a diff over 180 KB, and in 2 of them a **single file** was over 170 KB (both large design docs, 181 KB and 376 KB) |
| review_self.sh | ≈ 417 KB | cross-file consistency | agy refused; codex works (AR-7) |
| reverify_self.sh | ≈ 411 KB | per-finding vs fix diff | agy refused; codex works |
| run_red_team.sh | consumer code, `head -30` files | cross-component attack chains | agy refused above 180 KB |

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **One planning primitive**: new `scripts/oversight/chunk_logic.py` (pure Python, stdlib) renders every chunk's **final prompt file** and measures it in bytes. **One launch loop**: new sourced `scripts/oversight/lib/chunked_review.sh`. | #314: decision logic in Python. Measuring the rendered file (not an estimate) is the only exact way to keep each prompt under the ceiling. |
| D2 | The ceiling is never restated. The shell passes `--max-bytes "$(vendor_invoke_max_bytes <vendor>)"`. `vendor_invoke` still re-checks every chunk at send. | #1718 §4: `vendor_invoke_max_bytes` is the only implementation of the clamp. |
| D3 | **Reuse, don't re-implement** (§3): diff parsing from `panel_logic.py`; salvage, consumption check, and aggregation from `second_review_logic.py` / `validation_logic.py`. No new verdict aggregator. | AGENTS.md "Use the Code". A third aggregator would be a third place for #2032/#2036-class bugs to live. |
| D4 | Two modes. **pack** (1-D, order-preserving greedy) for per-file lenses. **grid** (reference × target) for **bipartite** pairwise lenses, so every (reference, target) pair shares exactly one chunk. Each grid axis is packed **first-fit-decreasing** (AR-3), not order-preserving. | The release validators' lenses are bipartite (doc ↔ agent, requirement ↔ implementation), not per-file. Plain file-group packing would separate a doc from the agent it describes. The grid keeps every cross-axis pair together. It does **not** preserve same-axis relations (agent ↔ agent), which is the AR-6 class on #2033. So the grid is approved only for lenses with no same-axis relation (AR-2). |
| D5 | **Oversize unit ⇒ fail loudly**, named detail, never truncated, never sampled. The only exception is the markdown-section split for audited docs (`split-md-h2`, ESC-3). Hunk splitting stays in run_panel only. | Issue requirement; F6. Panel/second-review reconciliation in §5. |
| D6 | **Fail closed on coverage.** Any refused, failed, unconsumed, or (except in second review) unparseable chunk, or any chunk missing from the results, fails the whole run. A partial pass is never possible. | Issue requirement; SPEC-219. |
| D7 | In **run_second_review** (agy and codex lanes), `n = 1` is the common path and must be **byte-identical** to today's prompt and report file. This is a hard golden-test requirement (AR-5). Chunk markers render to empty strings and no header or section is added. The diff body is normalised exactly as today's `$(git diff …)` does (§8.3). For the validators byte-identity is **not** required, because their unit order changes from `find` order to sorted (§4.1). | Removes a separate unchunked code path for the gate that runs on every MEDIUM+ step, and regressions are caught by a golden test. |
| D8 | Per-run **chunk cap**, lower-only via env. Exceeding it fails loudly (`chunk_cap_exceeded`). Calls are sequential. | Bounds cost and wall time (§7); protects the codex reserve. |

## 3. Reuse survey (searched scripts/, bootstrap/, bin/, scripts/automation/lib/)

- `scripts/oversight/panel_logic.py:683-727` (`_split_lines`, `_file_name`, `_parse_sections`) parses
  a unified diff into per-file sections. **Reused by import, read-only.** `chunk_diff` (`:768-840`) is
  **not** reused as a whole for three reasons. It never packs several files into one chunk (above the
  cap, every file becomes its own chunk, so a 40-file step would mean 40 agy calls). It splits
  oversize files by hunk, which D5 forbids here. Its cap is the diff size, not the rendered prompt.
  `panel_logic.py` is **not edited**: the ADR-1340 frozen engine span and the #2016 carve-out stay as
  they are.
- `scripts/oversight/release_panel_logic.py:322-345,646-658` has the `chunks_attempted ==
  chunks_completed` check. Same intent, but it is a count check, and it would pass a duplicated chunk.
  D6 uses per-chunk-id records instead (§6.3).
- `second_review_logic.py`: `salvage` CLI (`:1068-1119`, envelope + `--metadata-file`) and
  `consumption` CLI (#1718 §5). Reused per chunk. `_split_sections`/`_aggregate_full`
  (`:135-303`) already take error > request_changes > unparseable > approve across **every**
  `## agy…`/`## codex…` section, so per-chunk sections aggregate as a union with no code change.
- `validation_logic.py`: `extract_json_objects` (`:140-157`) + `compute_verdict` (`:312-393`)
  already union every ```` ```json ```` block, so chunk blocks are just more blocks.
- `scripts/automation/lib/*.py`: GitHub and automation only. No chunking or aggregation. Nothing else
  found in bootstrap/ or bin/.

## 4. Contract — `scripts/oversight/chunk_logic.py` (new)

Pure functions over **bytes**. The CLI shim does all file I/O. Everything is computed before anything
is written, so a non-zero exit leaves no manifest and no prompt files (the same atomicity as
`_run_chunk_diff`).

### 4.1 `plan` subcommand

```
chunk_logic.py markers --mode pack|grid [--nonce HEX]          # AR-4
chunk_logic.py plan --mode pack|grid --template FILE --marker-nonce HEX --max-bytes N [--reserve-bytes R]
    --max-chunks M --out-dir DIR --label TEXT [--oversize fail|split-md-h2] [--split-axis ref|target]
    ( --diff-file F | --units FILE )            # pack
    --ref-units FILE --target-units FILE        # grid
```
- `--units` files are JSONL `{"path": "<repo-relative>", "header": "<line written before the content>"}`.
  Content is read raw from `path`. Units are **sorted by path** (find order is not deterministic).
  `--diff-file` units are `_parse_sections` sections, kept in **diff order**, plus any preamble.
- `--template` is the caller's fully rendered prompt (every fixed field already interpolated), with
  literal markers: pack uses `@@HOS_CHUNK_PREAMBLE_<nonce>@@` and `@@HOS_CHUNK_BODY_<nonce>@@`; grid uses
  `@@HOS_CHUNK_PREAMBLE_<nonce>@@`, `@@HOS_CHUNK_REF_<nonce>@@`, `@@HOS_CHUNK_TARGET_<nonce>@@`.
  **Each marker must occur exactly once in the template bytes, otherwise exit 2.** This stops fixed
  content (for example a spec that happens to contain a marker) from steering where units are placed.
  Substitution is a single split on the template, so unit content is never re-scanned.
- **AR-4: the markers carry a per-run nonce.** A new subcommand `chunk_logic.py markers` prints the
  marker set for a fresh `secrets.token_hex(8)` nonce as one JSON line, and the caller interpolates them.
  `plan --marker-nonce HEX` must receive the same nonce. Tests pass a fixed nonce. With fixed markers,
  any fixed-context file that quotes the marker text (this TD does; `scripts/framework/decisions.md`
  or a consumer `SPEC_FILE` easily could) would make every run exit 2 permanently. That would be a
  self-inflicted, fail-closed outage of the release gate or of second review.
- `--out-dir` must not exist or must be empty; otherwise exit 2. Two runs that land on the same
  timestamped report name must never share a results file.
- Exit codes: **0** planned; **2** usage, I/O, or template error (`chunk_plan_failed`); **3**
  `unit_too_large` / `unit_pair_too_large` / `fixed_context_too_large` (the stderr line names the
  path(s) and the byte counts); **4** `chunk_cap_exceeded` (names the required n and M). On 0, one
  JSON summary line is printed: `{"n": .., "mode": .., "max_prompt_bytes": .., "manifest": ..}`.

### 4.2 Byte budget (exact)

`T = len(template) − len(markers)`. `P_max` is the byte length of the preamble rendered for the
**worst case**: k = n = M (digit width only), the full unit inventory (§4.4, AR-7), and every
heading outline that a split could add. Because the inventory does not depend on n, `P_max` has no
circular dependency on the packing result. Budget for unit bytes in one
chunk: `B = max_bytes − reserve_bytes − T − P_max`. If `B ≤ 0` → exit 3 `fixed_context_too_large`.
After packing, each real preamble (which is ≤ `P_max`) is rendered and every final prompt is
**asserted** `≤ max_bytes − reserve_bytes`. A failed assertion is an internal error (exit 2), never a
send. `reserve_bytes` is for a caller that appends text on retry. run_second_review passes the byte
length of its reinforce suffix (run_second_review.sh:736-738). This closes #1718 AR-8's edge case.

### 4.3 Packing

- **pack**: greedy and order-preserving. Append units to the current chunk until the next unit would
  exceed `B`, then start a new chunk. A unit with `len(header)+len(content) > B` → exit 3
  `unit_too_large`, unless `--oversize split-md-h2` applies. If n > M → exit 4.
- **grid**: first apply split-md-h2 (below) if enabled. Then let `rmax`/`tmax` be the largest
  reference/target units. If `rmax + tmax > B` → exit 3 `unit_pair_too_large`, naming both units.
  Otherwise choose the reference-bin capacity `cR` from `rmax … B − tmax` in 1,024-byte steps. Pack
  each axis **first-fit-decreasing** (AR-3), sorting units by (bytes desc, path asc, part index asc):
  ref with `cR`, target with `B − cR`. Keep the `cR` that minimises `bins_ref × bins_target`, then
  `bins_ref`, and break any remaining tie with the larger `cR`, so the result is deterministic. Within a
  bin, units are emitted in path order (then part order), not packing order. Chunks = the Cartesian
  product, ordered ref-major. If n > M → exit 4.
- **split-md-h2** (ESC-3; allowed on one named axis only): it runs **before** the `cR` search, and
  it applies to a unit on the split axis exactly when that unit's bytes exceed `B − tmax`, which is the
  largest capacity that axis can ever receive. Such a unit is cut at **every** line starting `## `
  outside a code fence. The fence rule is the one in `second_review_logic._split_sections` (a line whose
  `lstrip()` starts with three backticks toggles the fence). The parts then go through FFD as
  ordinary units, labelled `part i/j`. Parts concatenate byte-exact to the file, and this is asserted.
  A fence misdetection can therefore move a cut point but can never drop bytes. A single part still
  over capacity → exit 3. Every chunk containing a part also gets that file's **heading outline** (all
  `#`/`##`/`###` lines outside fences), counted inside `P_max`, so the reviewer knows which sections
  exist elsewhere.

### 4.4 Preamble (required by the issue; empty when n = 1)

```
CHUNKED REVIEW: this is chunk k of n of ONE review. You see only this chunk.
This chunk contains: <unit paths, part i/j where split>
Also in this review but NOT visible to you (reviewed in other chunks): <every other unit path, grouped by axis in grid mode>
Review only what is in this chunk. Do not approve or reject anything on the basis of content you
cannot see. If a finding depends on content you cannot see — including a claim that something is
missing or "not covered anywhere" — still report it, set "cross_chunk": true, and name the file you
would need.
```
**AR-7:** the third line is the run's unit **inventory** minus this chunk's units. It is not a
per-chunk map. The per-chunk map stays in the manifest. The inventory is bounded by the number of
units, not by n, which removes `P_max`'s dependence on M. In the grid it is also what a reviewer
needs: which docs or agents exist outside its view. If the list is over 8,192 B, it is collapsed to
`dir/ (N files)` for the top two directory levels. If it is still over 8,192 B → exit 3
(`fixed_context_too_large`). It is never silently truncated.

### 4.5 Manifest (`DIR/chunk-manifest.json`, schema `hos-chunk-manifest/1`)

`{schema, label, mode, max_bytes, reserve_bytes, max_chunks, input_sha256, units:[{path, axis,
bytes, sha256, whole, parts, chunks:[ids]}], chunks:[{id:"chunk-001", k, n, prompt:"chunk-001.prompt",
prompt_bytes, prompt_sha256, units:[...]}], coverage:{...}}`.
- `coverage` for pack/diff: `{"concat_sha256": sha(concat of chunk bodies in order), "equals_input": true}`.
  The bodies concatenate byte-exact to the input diff.
- `coverage` for grid: `{"pairs": |R|×|T|, "pairs_covered": .., "each_pair_once": true}`.
- Every unit's `chunks` list has length 1 in pack mode. **This is the coverage proof: every input
  file appears in exactly one chunk.**

### 4.6 `record-result` and `verify-run` subcommands

- `record-result --results FILE --chunk-id ID --lane L --vendor V --outcome O --detail D
  --prompt-file F [--consumption-status C]` appends one JSONL line. Python does the JSON
  encoding and **computes `prompt_sha256` from F itself** (AR-8). The shell never builds JSON or
  hashes by hand. F is the planned `chunk-NNN.prompt`, which the lane loop must never overwrite. The
  reinforce retry writes planned bytes + suffix to a **separate** tmpfile. Today's
  `run_agy_review` overwrites its prompt file in place (run_second_review.sh:739); if that carried
  over, every retried chunk would fail its sha check.
  `O ∈ {ok, unparseable, refused, failed, unconsumed, consumption_check_failed}`.
- `verify-run --manifest M --results FILE --lane L [--allow-unparseable] [--input F]` exits 0 only
  if, for lane L, every manifest chunk id has **exactly one** record, with outcome `ok` (or
  `unparseable` when the flag is given), and with `prompt_sha256` equal to the manifest's. With
  `--input`, the coverage proof is also recomputed from scratch. Otherwise it exits 1 and prints one
  JSON line `{lane, missing:[..], duplicate:[..], failed:[{id,outcome,detail}], sha_mismatch:[..]}`.
  A crash exits 2, and callers treat any non-zero exit as failure.

## 5. Oversize policy per caller, and reconciliation with #2016

| Caller | Unit | Oversize unit | Why |
|---|---|---|---|
| run_panel.sh (unchanged) | file, split by hunk then line | **split** (#2016, ADR-1340 c) | `CAP=60000` (run_panel.sh:82) is a reviewer-attention cap, a third of the vendor ceiling. Single files over 60 KB are routine (14 of the last 54 merges had one over 60 KB), so failing would disable the outer loop. Panel findings are line-anchored threads that a human resolves one by one, with an arbiter. A hunk fragment still has exact file+line. |
| run_second_review.sh | whole file diff section | **fail loudly** | The verdict certifies the whole `reviewed_range` (SPEC-219). A fragment of one file's diff hides the file's own invariants from the reviewer. A file whose diff alone is over about 170 KB is a step-shape problem for a human. The issue requires this. Consequence stated plainly: the 2 observed cases (both TDs) **still fail closed** (ESC-4). |
| validate_docs.sh | doc file (ref, split axis); agent file (target) | agent: fail. Doc: `split-md-h2` + outline (ESC-3) | Measured (architect, 2026-10-08): docs/AGENTS.md is 81,922 B, overseer.md is 74,037 B, and fixed context T = 21,757 B. 81,922 + 74,102 (with header) + 21,757 is already about 177.8 KB before any preamble, so the pair does not fit 180,000 B under any packing. After the split, the largest AGENTS.md part is the `## Agents` section (57,789 B), and the pair fits. Agents are the source of truth and are never cut. |
| validate_spec_compliance.sh | governance file (ref); agent/script (target) | fail | The largest pair (56.5 + 74 KB) fits. |
| reverify_self / validate_scripts | file (pack) (§8) | fail | Same as the second review. |
| review_self / run_red_team | — (not chunked, AR-2) | agy refused as today | Cross-file lenses (#2033 class). |

## 6. Aggregation and fail-closed coverage

### 6.1 Sections
Each chunk's output is written as its own reviewer section with the caller's existing heading. When
n > 1 the heading gets the suffix ` [chunk k/n]` (for example `## agy — Correctness + Spec Adherence
[chunk 2/4]`). The suffix must never contain "skipped" (`_aggregate_full` skips headings containing
that word, second_review_logic.py:197). Per-lane union and most-severe verdict then come from code
that already exists:
- run_second_review: `aggregate` (error > request_changes > unparseable > approve; max severity; sum
  of counts) followed by `process` (ledger-aware union over every json block).
- validate_docs / validate_spec_compliance: their in-script finalizers (validate_docs.sh:348-390,
  validate_spec_compliance.sh:383-425) already loop over every json block, so any
  `request_changes`/`non_compliant`/`error` or any blocking severity fails the run.
- **AR-9 (validators: canonical blocks only).** Those finalizers extract blocks with
  ```` re.findall(r'```json\s*(\{.*?\})\s*```', …, re.DOTALL) ```` and `continue` on a JSON parse
  error. A raw block that starts with `{` but never closes with `}` + fence (truncated or malformed
  vendor output) makes the lazy match run on into the **next** block. That block can be another
  chunk's `request_changes` or the coverage-failure `error` block. `json.loads` then fails on the
  merged text and **both blocks are silently dropped**. This is fail-open, and chunking multiplies the
  number of adjacent blocks. So in chunked validators, every ```` ```json ```` block written to the
  report must be **Python-re-serialised** (`json.dumps` of the salvaged object, one line, backticks
  escaped as in run_second_review.sh:624). Raw vendor stdout is never written inside a json fence. An
  unparseable chunk writes its failure record, not its raw text. The raw text may go in a plain fence
  for the human.
- **AR-9 (validators: independent coverage verdict).** The validator shell keeps the `verify-run`
  exit status in a variable. If it is non-zero, the script prints FAIL, writes no stamp, and exits 1
  **regardless of what the finalizer computed**. The appended error block stays (it puts the reason in
  the report), but pass/fail no longer depends on a regex finding it.

### 6.2 #2032 / #2036
Chunking adds blocks. It changes no aggregation semantics, so it can neither fix nor worsen either
bug, and **no part of this design depends on their fixes**:
- #2032 (`compute_verdict` ignores a `request_changes` with null findings): in run_second_review,
  `aggregate` reads the block verdict directly, and `process`'s no-downgrade ratchet
  (validation_logic.py:462-471) keeps it. The two validators do not call `compute_verdict`.
  Exposure grows with the number of blocks, but behaviour per block is unchanged. **Coupling to
  record:** if #2036 is fixed by letting `process` own the verdict outright (#2036 option 2), #2032
  becomes live in second review at every chunk. That fix must land #2032 first. This is noted for
  both issues, not solved here.
- #2036 (ledger convergence impossible): it is equally impossible for a chunked review. No worse.
`chunk_logic` **never computes or writes a verdict**. It can only *add* a failure block (§6.3), so it
cannot downgrade anything.

### 6.3 Coverage gate (D6)
After each lane, the caller runs `verify-run`. On a non-zero exit it sets
`VENDOR_INVOKE_CLASS=harness` and `VENDOR_INVOKE_DETAIL=chunk_coverage_failed`, appends the caller's
own failure-JSON block (`verdict: "error"`) carrying the verify-run line as `chunk_coverage`, and lets
the normal finalizer fail the run. Plan failures (§4.1 exits 2/3/4) take the same path with their
named detail, and no vendor is launched. Chunk outcome mapping in the lane loop: vendor_invoke
non-zero → `refused` (detail `prompt_too_large`) or `failed`; consumption exit non-zero →
`unconsumed` / `consumption_check_failed`; salvage found nothing after retry → `unparseable`.
**Only run_second_review (and reverify_self, whose output is prose by design) passes
`--allow-unparseable`.** That keeps today's prose → `unparseable` → CONDITIONAL routing
(run_second_review.sh:786-795). The validators' finalizers silently skip a non-JSON block, so there an
unparseable chunk must be a failure.

**AR-10 (second review: the coverage-failure block's heading).** In run_second_review the
coverage-failure or plan-failure record must be written under a heading that starts with the lane's
vendor name, for example `## agy — Chunk coverage (#2014)`, and never contains "skipped". `_aggregate_full`
only reads sections whose heading starts `agy`/`codex` (second_review_logic.py:191-198). Under any
other heading, aggregate ignores the block. `process` would still see `verdict: error`, but
`compute_verdict` turns an error block into one new blocking finding, which gives `request_changes`
(validation_logic.py:340-345, 380-385). The run would then exit **2** ("disposition the findings")
instead of **1** ("reviewer errored"). That still fails closed, but it routes the operator wrongly.
A hermetic S2 test pins exit 1 for a coverage failure.

### 6.4 Consumption check on every chunk (#1718)
- agy lanes run with `--sandbox --output-format json`. Each chunk goes through `salvage
  --metadata-file`, then `consumption --prompt-bytes $VENDOR_INVOKE_BYTES`, exactly as
  run_second_review.sh:757-776 does today. That needs ESC-1 for the two protected validators, which
  today call agy without `--output-format json`, so their consumption is always `unverified`.
- Codex has no usage envelope (#1718 D6). Each codex chunk records `consumption_status=unverified`
  and the existing advisory is written (plain fence, AR-5). It is never written as `verified`.
- Not retried on `not_consumed` (#1718 §6).

### 6.5 Findings lost across chunk boundaries (stated, not waved away)
- **Pack (per-file):** a defect that spans files in different chunks (a caller changed in chunk 1, the
  callee in chunk 3) can be missed. Mitigations: (a) the diff stays in git's path order, so files in
  the same directory tend to share a chunk; (b) the preamble lists every other chunk's files; (c)
  `cross_chunk: true` findings are kept at their stated severity. They are ignored by the
  fingerprint (validation_logic.py:223-228) and are never down-ranked. Residual risk: real and
  unmeasurable hermetically. It is recorded per run (§6.6).
- **Grid (pairwise):** every (doc, agent) and every (requirement, implementation) pair is co-resident,
  so pairwise findings are kept. Three-way reasoning (agent A ↔ agent B ↔ doc) is only seen when both
  agents land in the same target bin. Neither validator's agy lens asks for agent ↔ agent reasoning
  (validate_docs.sh:166 scopes the lens to how completely each doc covers each agent, and agents are
  never checked against each other; the REQ checks at validate_spec_compliance.sh:189-221 are each
  decidable per implementation file). That is why the grid
  does not collide with AR-6 here when it would for validate_agents. **Universally quantified checks
  become false positives:** validate_docs lens 6 ("not reflected anywhere in the documentation
  files", :203), a "requirement implemented nowhere" result, and a REQ-007 `gap` when the named
  file sits in another bin. In a chunk that lacks the covering file, such a check reads as missing. That is the loud direction,
  and at `blocking` severity it fails a release cut. The inventory line (§4.4) and the `cross_chunk`
  instruction are the only mitigation. **AR-11:** the S1b live acceptance run is also the
  false-positive measurement. If Phase 3 or 4 fails on a blocking `cross_chunk: true` finding that a
  human judges false, the result goes back to the architect before release, rather than being
  dispositioned ad hoc. It must not be "fixed" by down-ranking `cross_chunk` findings in code: a
  down-rank would also silence true pack-mode findings in second review.
- **md-h2 split:** a whole-doc omission ("the doc never mentions mode X") can be reported falsely
  when another section covers it. The outline mitigates this. False positives fail loud.

### 6.6 What is recorded
When n > 1, the report gains a header line `chunks: <n>` (after `reviewed_range:` in
run_second_review, which is additive; the evaluator ignores unknown lines) and a verdict-inert section
`## [COVERAGE] Chunked review (#2014)`. That section holds, in a **plain** fence, the manifest
summary (unit → chunk id, `input_sha256`, `coverage`, per-lane outcomes). AR-5 rules apply: it must
never carry the keys `verdict`/`findings`/`attacks`/`error`. The manifest and results JSONL stay in
`<report>.chunks/` next to the report, so `verify-run --input` can be re-run afterwards.

## 7. Cost, caps, and timeouts

| Caller / lane | `--max-chunks` default (env, lower-only) | Expected n today | Worst-case wall time |
|---|---|---|---|
| second review agy | 6 (`SECOND_REVIEW_MAX_CHUNKS_AGY`) | 1 for about 92% of steps; 3 for the 377 KB case | 6 × 900 s, ×2 if every chunk takes the prose retry |
| second review codex (reserve) | **2** (`SECOND_REVIEW_MAX_CHUNKS_CODEX`) | 1 (codex ceiling 1 MiB) | 2 × 900 s |
| validate_docs agy | **32** (`FRAMEWORK_VALIDATION_MAX_CHUNKS`) | **18** (3 doc bins × 6 agent bins), about 2.9 MB of agy input per run | 32 × 300 s (`AI_REVIEW_TIMEOUT`), ×2 with prose retries |
| validate_spec_compliance agy | **32** (same var) | **9** (1 governance bin × 9 target bins), about 1.6 MB | 32 × 300 s, ×2 with retries |
| validators codex | **1** (AR-12) | 1 (≈ 730 KB < 1 MiB) | 1 × 300 s |
| reverify_self agy | 8 | 3–4 | 8 × 900 s |

**AR-3 (measured, not estimated).** The architect re-derived these counts from the live tree on
2026-10-08, using byte-exact unit sizes and this section's packing rules. Inputs: 31 named agent files,
484,729 B with headers. Docs: 159,477 B. validate_docs fixed context: T = 21,757 B. P_max: about
4.5 KB under AR-7. The draft's "8–12 each" was wrong. Under the draft's order-preserving grid with a
per-chunk other-chunks map, validate_docs planned **24** chunks (exactly the draft's cap of 24), or
**28** once P_max reached about 11 KB, which is over the cap. So Phase 3 would have failed closed on
`chunk_cap_exceeded` on the first agent added after merge. FFD packing plus the AR-7 inventory gives 18. The cap of 32 leaves about 75%
headroom and is a reviewed constant (lower-only env). The grid is inherently close to quadratic.
The relaxed lower bound is ⌈159 KB / cR⌉ × ⌈485 KB / (B − cR)⌉, which gives at least about 14 for
validate_docs, and the 74 KB `overseer.md` forces B − cR ≥ 74 KB. Agent growth therefore raises n
linearly. S1b must add `chunk_logic.py plan --dry-run`, which prints n and per-chunk bytes with no
vendor call, and `run_framework_validation.sh` must print that plan before Phase 3 and Phase 4 run.
These costs are a cost-model change and go to the human in ESC-5.

- Env values follow #1718 D3: positive decimal, may only **lower** the reviewed constant, malformed or
  raising values are ignored with one stderr warning. The clamp is in Python (`resolve_max_chunks`),
  and the shell passes the raw value.
- Calls are **sequential**. No parallel fan-out: agy quota and rate limits are shared, and a single
  sequential loop makes the result order deterministic.
- Over the cap → `chunk_cap_exceeded`, exit as the caller's fail-closed path. **Never sample a subset.**
- Codex reserve: codex lanes chunk only above codex's own ceiling. Second review's codex lane is capped
  at 2. The validators' codex lanes are capped at **1** (AR-12), so above 1 MiB they fail loudly
  rather than chunk. The per-chunk
  token-tracker records use the real `VENDOR_INVOKE_BYTES` per chunk, so reserve burn is visible.
- An unattended worker cycle can hit the worst case above. `HOS_CRON_MAX_SECONDS` is optional today
  (#1146). This design adds no deadline knob and flags the interaction in ESC-5.

## 8. Per-caller contract

**8.1 validate_docs.sh** (protected). Grid. Ref = docs (`docs/AGENTS.md`, `OVERSIGHT-RUNBOOK.md`,
`SETUP.md`, `CUSTOMIZATION.md`, with headers as today at :99), `--split-axis ref --oversize
split-md-h2`. Target = agent files that have `name:` (headers as at :82). Patterns and decisions stay
fixed context in the template. The agy prompt (:162-229) becomes a template with the three markers in
place of `${AGENT_CONTENT}`/`${DOC_CONTENT}`. One lane loop through `chunked_review.sh`, one section
per chunk, `verify-run`, then the existing finalizer. The codex lane uses the same primitive with
`--max-chunks 1` (AR-12): its adversarial lens hunts bypass chains across files, which is the #2033
class. The stamp (:403-406) is written only on PASS **and** a zero `verify-run` exit (AR-9), and every
json block is re-serialised (AR-9).

**8.2 validate_spec_compliance.sh** (protected). Grid. Ref = `METHODOLOGY.md`, `AGENTS.md`,
`scripts/framework/decisions.md` (:80-82). Target = agent files + the 4 scripts (:99-109). Oversize:
fail. The three-part governance block in the prompt (:168-177) becomes `@@HOS_CHUNK_REF@@`. The
"Agent files" and "Scripts" blocks are merged into `@@HOS_CHUNK_TARGET@@` with each file's header
kept. The REQ list (:189-221) stays fixed context. The objective's tie-break on fewer reference bins
(§4.3) keeps all three governance files in one bin on the current tree (measured: 1 × 9). Codex lane:
same primitive, `--max-chunks 1` (AR-12). AR-9 applies as in 8.1.

**8.3 run_second_review.sh.** Pack, `--diff-file`, oversize fail.
- In each branch that sets `REVIEWED_RANGE` (:296-360), the same `git diff` writes
  `<report>.chunks/input.diff` directly. B3 holds: the diff source and the recorded range come from
  one branch. `DIFF_CONTENT` is read from that file for the emptiness check (:362) and the token
  estimate. Command substitution strips trailing newlines, so the file is the only exact input.
- **AR-5 (normalisation for byte-identity).** Today the reviewer receives `$(git diff …)`, which has
  **all trailing newlines stripped**. The raw file keeps them. `plan --diff-file` therefore
  canonicalises its input as `data.rstrip(b"\n")`. Both `input_sha256` and the §4.5 concat proof are
  defined over that canonical input, and `verify-run --input` applies the same rule. Without this
  rule, the n = 1 golden test cannot pass. Note also that the `--files` branch's
  `|| cat "${FILES[@]}"` fallback (:314) yields file text, not diff text. `_parse_sections` then finds no
  `diff --git` line, so the whole input becomes one preamble unit. That is correct for coverage, and
  it fails loudly if over budget. A test pins this.
- The agy template is today's prompt (:641-697), with `@@HOS_CHUNK_PREAMBLE@@` placed directly
  before `## Diff` and `@@HOS_CHUNK_BODY@@` replacing `${DIFF_CONTENT}` (nonce-suffixed, AR-4).
  `--reserve-bytes` is the byte length of the reinforce suffix. `chunked_review.sh` owns that suffix and exports
  `chunked_review_reserve_bytes`, so every caller gets the value from that one function and none restates it (D2
  pattern). The codex template follows the same pattern (:803-855).
- `run_agy_review` takes a prompt **file** in place of building the prompt itself, and runs once per
  chunk. Its salvage → single retry → consumption body moves into `chunked_review.sh`, so one
  implementation serves all callers (S1a adds the function; S2 makes run_second_review call it and
  deletes the copy).
- Per chunk: one section, one #1718 advisory when unverified, `create_finding_issues`,
  `log_context_advisory`, and one token-tracker record.
- `second_review_failure_json` gains summary text for `unit_too_large`, `fixed_context_too_large`,
  `chunk_cap_exceeded`, `chunk_coverage_failed`, `chunk_plan_failed`. The `prompt_too_large` "do not
  narrow with --files" guidance (#1718 AR-2) applies to all of them. The fail-closed stderr hint
  (:1109) is extended to these details by the same plain `grep -q`.
- `reviewed_range` is unchanged. The chunks cover it by construction (§4.5 concat proof).

**8.4 review_self.sh / reverify_self.sh** (ESC-8, revised by AR-2). **review_self: not chunked
under #2014.** Its lens is cross-file consistency among the implementation files themselves (agents ↔
scripts ↔ contract, :92-112). In a grid those files are all on the target axis, so their mutual
relations are split across bins. That is exactly the same-axis relation that AR-6 on #2015 ruled
cannot be file-chunked. It keeps the agy refusal and `--reviewer codex` as the supported path (#1718
AR-7), and it joins the #2033 cross-file design. **reverify_self: pack** over the fix diff (:78-103),
with the original findings and the mapping as fixed context. Its lens is per finding against the fix
hunk. A fix spread across chunks can make the reviewer report a finding as "not fixed" in the chunk
that lacks the fix, which is the loud direction. Output is prose: each chunk's output goes under
`## Chunk k/n`, and the run exits 1 if `verify-run` fails (with `--allow-unparseable`).
`--reviewer codex` stays unchunked when under 1 MiB.

**8.5 run_red_team.sh** (ESC-7). Recommended: **not chunked under #2014.** Its lens is end-to-end
attack chains across components, which is the #2033 class, and its scope paths are
CondoParkShare-specific, so it fails closed on HOS anyway (:135-142). It keeps today's loud refusal.

**8.6 validate_scripts.sh** (ESC-6, conditional on #2015 merging). Pack over `FILES`
(validate_scripts.sh:174), oversize fail. The per-file lens matches AR-6.
**validate_agents.sh: out of scope** (#2033).

## 9. Escalations (human), each a yes/no question

- **ESC-1** May the two protected release validators switch their agy lane to `--sandbox
  --output-format json`, so that every chunk gets a real #1718 consumption check instead of a
  permanent `unverified`? (Recommended: yes.)
- **ESC-2** (revised by AR-2/AR-11) Is the grid decomposition an acceptable basis for release
  Phases 3 and 4? Under it, every doc↔agent and requirement↔implementation pair is reviewed together.
  Three-way cross-file reasoning happens only within a bin. And "not covered anywhere" checks can
  raise **false-positive blocking findings** that fail a release cut until a human dispositions them,
  with the S1b acceptance run used as the measurement. (Recommended: yes. The alternative is the
  AR-6/#2033 architecture, which delays release cuts.)
- **ESC-3** May validate_docs split an audited **doc** (today only docs/AGENTS.md) at `## `
  boundaries with a heading outline, given that without it Phase 3 fails loudly on every run because
  no packing fits the AGENTS.md + overseer.md pair? (Recommended: yes. Agent files are never split.)
- **ESC-4** Keep "a single file over the ceiling fails loudly" in run_second_review, accepting that the
  only observed cases (2 of the last 54 merges, both large design docs) still fail closed and need a
  human? (Recommended: yes, per the issue. A follow-up could allow md-h2 splitting for `*.md` in
  second review.)
- **ESC-5** (revised by AR-3; this is a product-boundary cost-model checkpoint) Accept the chunk caps
  and costs in §7? (a) Second review: up to 6 × 900 s per lane plus retries, inside unattended cron
  cycles, with no new deadline knob. (b) Each release cut: about **18 agy calls (≈ 2.9 MB of input)
  for Phase 3 and 9 calls (≈ 1.6 MB) for Phase 4** on today's tree, with a cap of 32 per phase and a
  worst case of about 2.7 h per phase at the cap (5.3 h if every chunk takes the prose retry). Phase 3's count grows roughly linearly with agent
  bytes. (Recommended: yes. #1146 owns the cycle deadline. Release cuts are manual and infrequent.)
- **ESC-6** Widen #2014 to include validate_scripts.sh chunking as conditional slice S5, built only
  after #2015 merges (architect AR-6 on #2015)? (Recommended: yes.)
- **ESC-7** Narrow #2014 to exclude run_red_team.sh, keeping its loud refusal and deferring it to the
  #2033 cross-file design? (Recommended: yes. This narrows scope the issue names, so the human
  decides.)
- **ESC-8** (revised by AR-2) Narrow #2014 so that **review_self.sh is not chunked**? It stays
  agy-refused, `--reviewer codex` remains its supported path (#1718 AR-7), and it moves to the #2033
  cross-file design. Its lens is the AR-6 class. And should **reverify_self.sh** be chunked (pack) for
  agy? (Recommended: yes to both. This narrows scope the issue names, so the human decides.)
- **ESC-9** Should a chunked second review be recorded in the artifact (`chunks:` + `[COVERAGE]`)
  **without** changing oversight-evaluator routing in #2014 (no edit to `.claude/agents/`)?
  (Recommended: yes. A routing change would be a separate, protected issue.)

## 10. Slices (each ≤ 15 files, ≤ 10 commits). Release blockers first.

**AR-13: S1 is split into S1a and S1b.** The primitive is not a protected surface. The validators are.
Bundling them would put a new, unprotected decision module behind a human merge gate that is
really about the two validators, and would make the human approve both at once.

**S1a — primitive + lib (no caller).** Risk **HIGH** (new fail-closed decision logic that two gates
will depend on). Not protected. **Not gated on any ESC.** No caller is wired, so merging it changes
no behaviour. Required reviewers: code, security, reliability. Second review MEDIUM+ applies.
Files (7): `scripts/oversight/chunk_logic.py` (new) · `scripts/oversight/lib/chunked_review.sh` (new) ·
`tests/oversight/test_chunk_logic.py` (new) · `tests/oversight/test_chunked_review_lib.py` (new) ·
`DECISIONS.md` · `SCRIPTS-INDEX.md` (regen via `scripts/framework/regen_all.sh`) · prompt artifact.

**S1b — release validators (Phases 3/4).** Risk **HIGH**. Protected surface (human approval at
merge). Gated on S1a merged and ESC-1/2/3/5. Required reviewers: code, security, reliability.
Files (7): `scripts/framework/validate_docs.sh` · `scripts/framework/validate_spec_compliance.sh` ·
`scripts/framework/run_framework_validation.sh` (prints the dry plan, AR-3) ·
`tests/framework/test_validate_docs_chunked.py` (new) ·
`tests/framework/test_validate_spec_compliance_chunked.py` (new) · `DECISIONS.md` · prompt artifact.

Hermetic tests (chunk_logic and lib → S1a; validators → S1b):
- chunk_logic: pack keeps order, puts every unit in exactly one chunk, and passes the concat proof;
  **400 KB synthetic diff (40 × 10 KB files) with `--max-bytes 180000` gives n ≥ 3**, and every
  `prompt_bytes ≤ max − reserve`; a 200 KB unit → exit 3 naming it; n > M → exit 4; a missing or
  duplicated marker (including one injected through fixed content) → exit 2; n = 1 gives an empty
  preamble and a prompt byte-identical to the template with markers removed; grid covers every pair
  exactly once; an infeasible pair → exit 3 naming both; an md-h2 split recombines byte-exact; an
  over-cap section → exit 3; preamble collapse and its bound; same input gives the same manifest;
  env cap: raising is ignored with a warning, lowering is honoured.
- Added by the architect review: a template whose fixed content quotes the **nonce-less** marker text
  still plans (AR-4); `--marker-nonce` mismatch → exit 2; a non-empty `--out-dir` → exit 2; grid FFD
  is deterministic and independent of input order (shuffled `--units` give an identical manifest);
  the `bins_ref` tie-break (AR-3); split-md-h2 fires only when the unit is over `B − tmax`, and a `## `
  inside a fence is not a cut point; `--diff-file` with trailing `\n\n` gives the same
  `input_sha256` as without it (AR-5); input with no `diff --git` line becomes one unit (AR-5);
  `record-result` hashes the file and ignores any hash on argv (AR-8); a retried chunk's planned prompt
  file is byte-unchanged after the retry (AR-8); `P_max` with 40 units and M = 32 is within the 8,192 B
  inventory bound (AR-7).
- verify-run: missing, duplicate, `refused`, `failed`, `unconsumed`, and sha-mismatch records each →
  exit 1; all `ok` → 0; `unparseable` → 1 without the flag and 0 with it.
- lib (stub agy emits an envelope and logs each stdin size): 3 chunks, all consumed → 3 `ok`; the
  truncating stub on chunk 2 (#1718 fixture pattern) → `unconsumed` and run failure; a chunk is
  never retried on `unconsumed`.
- validate_docs / validate_spec_compliance (fixture corpus about 400 KB): ≥ 3 agy calls, each stdin
  ≤ 180,000 B, every fixture file seen by the stub; all approve → exit 0 and the stamp is written;
  **one chunk's stub exits non-zero → exit 1, no stamp, report contains `chunk_coverage_failed`**;
  a chunk that answers in prose → exit 1; the codex lane is called once.
  AR-9: a stub chunk emitting `{"verdict": "approve", "findings": [` (unterminated) followed by a
  `request_changes` chunk → exit 1, and that unterminated text is not found inside any json fence of the report;
  `verify-run` failing while every json block approves → exit 1 and no stamp (pass/fail does not
  depend on the finalizer seeing the error block); codex lane over 1 MiB → loud failure, not 2 calls
  (AR-12).
Acceptance (live, by the human or worker, recorded on the PR): `chunk_logic.py plan --dry-run`
for both validators on the current repo shows n ≤ cap (the architect measured 18 and 9). Then
`run_framework_validation.sh` Phases 3 and 4 complete. Every blocking `cross_chunk: true` finding
is listed on the PR with a human's true/false judgment (AR-11).

**S2 — run_second_review.sh.** Risk **HIGH** (mandatory pre-PR gate, fail-closed surface). Not
protected. Gated on ESC-4/5/9.
Files (6): `scripts/run_second_review.sh` · `tests/oversight/test_second_review_chunked.py` (new) ·
`tests/oversight/test_second_review_vendor_invoke.py` (golden for the n = 1 prompt) · `DECISIONS.md`
· `SCRIPTS-INDEX.md` · prompt artifact.
Hermetic tests: **400 KB step diff → ≥ 3 agy chunks**, each ≤ 180,000 B, union of stub stdins
contains every diff section exactly once, exit 0 on all approve, `reviewed_range` unchanged;
**chunk 2 stub fails → verdict `error`, exit 1**; truncating stub on one chunk →
`prompt_not_consumed`, exit 1; one chunk `request_changes` + others approve → exit 2; one chunk prose
→ `unparseable`, not a coverage failure; single 200 KB file → `unit_too_large`, stub never launched,
exit 1, stderr hint; over the cap → `chunk_cap_exceeded`, exit 1; n = 1 prompt and artifact
byte-identical to pre-change (golden); `[COVERAGE]` block is verdict-inert (aggregate + `process
--strict-empty` identical with and without it, and the fence is not `json`); the 400 KB diff goes to
codex as **one** call. Architect additions: a coverage failure (stub chunk missing from results)
→ verdict `error`, **exit 1, not 2** (AR-10); the n = 1 golden covers both agy and codex prompts and
a step diff that ends in a blank line (AR-5); a test that greps that `run_second_review.sh` no longer
contains its own salvage → retry → consumption body (A5, one implementation).

**S3 — reverify_self.sh only** (AR-2). Risk **MEDIUM** (manual tool, no gate). Gated on ESC-8.
Files (3): `scripts/reverify_self.sh` · `tests/oversight/test_reverify_self_chunked.py` (new) · prompt
artifact.
Tests: ≥ 2 chunks via stub; one failed chunk → exit 1 and no report claiming completion; `--dry-run`
prints the plan (n, per-chunk bytes) with no vendor call; `--reviewer codex` makes one call.

**S4 — run_red_team.sh.** Only if ESC-7 is answered **no**. Risk **MEDIUM**. Pack, with the §6.5
caveat printed in the report. Files: script, `tests/oversight/test_red_team_fail_closed.py`
(extended), prompt artifact.

**S5 — validate_scripts.sh.** Only if ESC-6 is yes **and** #2015 has merged. Risk **HIGH**
(protected, release gate). Files: script, `tests/framework/test_validate_scripts_chunked.py` (new),
`DECISIONS.md`, prompt artifact.

## 11. Open points for the architect (answered in §13: A1 → AR-1, A2 → AR-2/AR-3, A3 → AR-6, A4 → AR-5, A5 → AR-8)

- A1 Module placement: `chunk_logic.py` imports `panel_logic`'s `_parse_sections`/`_split_lines`/
  `_file_name` read-only and does not edit `panel_logic.py` (ADR-1340 frozen span untouched). Is
  importing private names acceptable, or should `panel_logic` gain public aliases in a separate,
  panel-owned change?
- A2 Confirm the grid as the decomposition for the pairwise validators (D4), and the
  `cR`-minimising search in §4.3.
- A3 Confirm that `unparseable` is a coverage failure everywhere except run_second_review (§6.3).
- A4 Confirm the n = 1 byte-identity invariant (D7) as a hard test requirement rather than a goal.
- A5 Confirm that moving `run_agy_review`'s salvage/retry/consumption body into `chunked_review.sh`
  in S1/S2 is a refactor inside the #1718 contract and not a change to it.

## 12. Affected sign-offs

None yet: nothing has been built against this contract. #1718's sign-offs stand. This design consumes
#1718's contract (`vendor_invoke_max_bytes`, `consumption`, AR-5 advisory rules) without changing it.
#2016's panel chunker is untouched (§5).

Architect addendum (startup-gap check, CORE): this review does not revise an ADR. Chunking was not
missed at #1718's initial review. It was identified there as F1, deferred on purpose, and its
consequences were cleared through #1718 AR-9. It is **not** a `startup-artifact-gap`. S2's move of
`run_agy_review`'s body into `chunked_review.sh` touches code that #1718's reviewers signed off.
Those sign-offs **stand**, on the condition that the #1718 tests (`tests/oversight/test_second_review_vendor_invoke.py`,
`test_vendor_prompt_consumption_guard.py`, `test_second_review_envelope_salvage.py`,
`test_second_review_envelope_gate.py`) pass **unmodified** apart from the golden addition. Any edit to an existing
#1718 assertion in S2 voids this and requires re-review against #1718 AR-3/AR-5/AR-8.

## 13. Architect review (round 1, 2026-10-08)

Rulings are binding on technical-design, coder, code-reviewer, and the reviewers. Every claim below was
checked against the code or measured on the live tree, not taken from this TD. The architect's packing
simulation used byte-exact unit sizes from the working tree and reproduced §4.3 both as drafted and as
amended. Sections changed by a ruling have been edited in place, so the document is self-consistent.

**Verified and correct as drafted:** the vendor_invoke ceiling check (vendor_invoke.sh:308-320, before
`command -v`); the `_split_lines`/`_file_name`/`_parse_sections` spans (panel_logic.py:683-727); the
count-only coverage check in release_panel_logic.py:322-345 and :646-658; `_aggregate_full`'s precedence
and its skip of headings containing "skipped" (second_review_logic.py:275-295, :197); the `process`
ratchet (validation_logic.py:462-471); the validators' finalizers reading the block verdict inline,
not through `compute_verdict`. So #2032's trigger does not reach validate_docs or
validate_spec_compliance, and the issue's list of callers overstates this. The §6.2 coupling note is
also correct: if #2036 is fixed by letting `process` own the verdict, then #2032 must land first. The
worker should cross-reference that on both issues. The architect does not post comments.

- **AR-1 (A1, private imports): APPROVED as drafted, with two constraints.** Import
  `_split_lines`/`_parse_sections`/`_file_name` read-only, using the repo-root `sys.path` idiom from
  release_panel_logic.py:44-49. Do not add public aliases in panel_logic.py: that would be an edit
  in #2016's newly carved-out span, made by a non-panel issue. The coupling risk is a future panel
  edit changing how sections parse. That risk is contained because `plan` asserts its byte-exact concat proof on
  every run, so any drift fails closed instead of losing bytes. Constraint: `_file_name`'s output is
  display-only (manifest, preamble), and grouping must never depend on it (ADR-1340 c5 says the same
  for the panel). Constraint: S1a gets a test that imports the three names, which pins the dependency so a
  rename breaks loudly.
- **AR-2 (A2, grid vs AR-6): APPROVED for validate_docs and validate_spec_compliance only.** The grid
  keeps every cross-axis pair and loses every same-axis relation. AR-6 on #2015 objected to splitting
  agent ↔ agent relations, and neither validator's agy lens has one (§6.5). So the grid does not collide
  with AR-6 here, and it would collide for validate_agents. The draft's ESC-8 grid for **review_self**
  does collide: its corpus is cross-file consistency among agents, scripts, and contract, all on one
  axis. So review_self is removed from #2014 (§8.4, ESC-8 revised, S3 reduced), and so is run_red_team
  (ESC-7, unchanged). The cost of the grid is false-positive blocking findings from "covered nowhere"
  checks. That cost is stated in ESC-2 and measured under AR-11.
- **AR-3 (A2, packing and cap): CORRECTED.** The §7 claim "about 8–12 each" was false. Measured
  under the draft's rules, validate_docs planned 24 chunks (= the cap) or 28 (> the cap), so the release
  gate would have been re-blocked as soon as the tree grew. Amended: grid axes are packed
  first-fit-decreasing; the objective is n, then `bins_ref`, then larger `cR`. This gives
  validate_docs = 18 and validate_spec_compliance = 9 on today's tree. The validator agy cap is
  raised to 32, and `plan --dry-run` output is printed before each phase. Pack mode for diffs stays
  order-preserving, because path locality is the only cross-file mitigation that pack mode has (§6.5).
  The `cR`-minimising search itself is approved.
- **AR-4 (marker collision): CHANGED.** Fixed markers plus the exactly-once rule turn any fixed-context
  file that quotes the markers into a permanent exit 2 for that gate. This TD would do it, and so could
  `scripts/framework/decisions.md` (a validate_docs fixed input) or a consumer `SPEC_FILE`. Markers
  carry a per-run 16-hex nonce (§4.1). The exactly-once check stays.
- **AR-5 (A4, n = 1 byte-identity): CONFIRMED as a hard test requirement, for run_second_review only**
  (both lanes, D7 revised). It is feasible only if the diff body is canonicalised the way `$(git diff)`
  canonicalises it: all trailing `\n` stripped (§8.3). As drafted, D7 contradicted §8.3's own
  "the file is the only exact input". For the validators it is not required. Their input order moves
  from `find` order to sorted order, and per-file `$(cat)` newline stripping changes, so a golden would
  only pin an accident.
- **AR-6 (A3, unparseable): CONFIRMED.** `unparseable` is a coverage failure everywhere except
  run_second_review, and reverify_self, whose expected output is prose. The validators' finalizers `continue` on a
  parse error (validate_docs.sh:363-366, validate_spec_compliance.sh:398-401), so in them, prose that is
  tolerated is prose that is silently dropped.
- **AR-7 (preamble): CHANGED.** The other-chunks list is replaced by the run's unit inventory minus
  this chunk (§4.4). This removes `P_max`'s circular dependence on M, lowers `P_max` from about 9–11 KB to
  about 4.5 KB, and gives a grid reviewer the information it needs (what exists outside its view). The
  preamble now names absence claims explicitly as `cross_chunk`.
- **AR-8 (A5, moving the #1718 body): CONFIRMED as a refactor inside the #1718 contract, with
  conditions.** (a) The #1718 tests pass unmodified (§12). (b) The retry never overwrites the planned
  prompt file, and `record-result` hashes the file itself (§4.6). As drafted, the moved code
  (run_second_review.sh:739) would have made every prose-retried chunk fail its sha check. (c) The
  reinforce suffix and its byte length live in the lib and nowhere else. For the **validators**, gaining
  `--sandbox`, the prose retry, and the consumption check is a contract **extension** to new callers,
  not a refactor, and it is gated by ESC-1.
- **AR-9 (validators' fail-closed aggregation): CHANGED; this was the design's real hole.** The finalizer's
  lazy `` ```json\s*(\{.*?\})\s*``` `` match lets an unterminated raw block swallow the next block,
  and the `continue` then drops both. Under chunking, the swallowed block can be another chunk's
  `request_changes` or the coverage `error` block itself, which would pass the gate. Required: only
  Python-re-serialised JSON inside json fences, and a pass/fail decision that consults `verify-run`'s
  exit directly (§6.1, §8.1). With both, aggregation is fail-closed. In run_second_review the
  equivalent risk is already contained by the fence-aware `_split_sections` (#982) and the per-section
  `_fenced_body`.
- **AR-10 (second review coverage block routing): CHANGED.** The failure block goes under an `agy`/`codex`
  heading, so a coverage failure exits 1 (`error`), not 2 (§6.3).
- **AR-11 (false positives at the release gate): REQUIRED measurement.** The S1b live acceptance
  records every blocking `cross_chunk` finding with a human's true/false judgment. A recurring false
  positive comes back to the architect. It is never fixed by down-ranking `cross_chunk` findings (§6.5).
- **AR-12 (codex lanes of the validators): CHANGED to `--max-chunks 1`.** Their adversarial lens
  (bypass chains, validate_spec_compliance.sh:291-312) is cross-file in the #2033 sense. Below 1 MiB
  (today ≈ 730 KB) nothing changes. Above 1 MiB they must fail loudly rather than be silently decomposed.
- **AR-13 (slices): CHANGED.** S1 splits into S1a (primitive + lib, 7 files, HIGH, not protected, no ESC
  gate, no caller) and S1b (validators, 7 files, HIGH, protected, gated on ESC-1/2/3/5). Release
  blockers still come first: S1a → S1b → S2. All slices are ≤ 15 files. Tiers: S1a HIGH, S1b HIGH,
  S2 HIGH, S3 MEDIUM, S5 HIGH. These are confirmed. S4 exists only if ESC-7 is answered no.
- **AR-14 (reuse): CONFIRMED, no re-implementation found.** Searched scripts/, scripts/oversight/lib/,
  scripts/automation/lib/, bootstrap/, and bin/ for chunking, packing, manifest, and coverage helpers.
  The only candidates are `panel_logic.chunk_diff` (correctly rejected in §3 for D5 and its CAP
  semantics) and the release-panel count check (correctly superseded by per-id records). The draft
  itself re-implemented one thing, the salvage → retry → consumption body, and S2's deletion test
  (one implementation) closes that.

**ESC changes made by this review:** ESC-2 revised (states the false-positive release-blocking
consequence). ESC-5 revised and reclassified as a product-boundary cost-model checkpoint (release cut
≈ 18 + 9 agy calls, ≈ 4.5 MB of input per cut, cap 32 per phase, worst case 2.7 h per phase at the cap,
5.3 h with retries). ESC-8 revised (review_self narrowed out, reverify_self kept). ESC-1, -3, -4, -6,
-7, and -9 are unchanged. No ESC removed. No new ESC added.

**Gating.** S1a: none, so the coder may start now. S1b: S1a merged, plus human answers to ESC-1, -2,
-3, and -5, plus human approval at merge (protected surface). S2: S1a merged, plus ESC-4, -5, and -9.
S3: ESC-8. S5: ESC-6 and #2015 merged.

**Status: APPROVED WITH CONDITIONS** — APPROVED for coder (slice S1a) under AR-1, AR-3, AR-4,
AR-5 (the canonicalisation rule lives in `plan`), AR-7, and AR-8. S1b and S2 must not be coded until
their ESC gates above clear. Any deviation from AR-1..AR-14 comes back to the architect.
