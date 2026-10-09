# ADR-2033: Cross-file chunked review for validate_agents.sh. A deterministic agent graph in every chunk, and chunks packed so every agent-to-agent reference is co-resident

**Status:** Proposed (architect). The decisions marked BINDING bind `technical-design`, `coder`, `code-reviewer`, and the reviewers once the gating ESC items in §9 are cleared on record. Nothing here is treated as ruled by the human.
**Date:** 2026-10-09
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #2033 (priority:high, v0.7.0) · **Risk tier: HIGH.** S3 touches `scripts/framework/**`, a protected surface, so human approval is required at merge whatever the computed tier.
**Origin:** #2015 architect ruling AR-6 (validate_agents' lens spans files and needs its own decision). #2014 AR-2 / ESC-7 / ESC-8 also route `review_self.sh` and `run_red_team.sh` here (see AD-12).
**Inputs read:** `docs/v0.7.0/TECHNICAL-DESIGN-2014-chunked-vendor-review.md` (all, including §13 AR-1 to AR-14), `docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md` (§2, §3, §7). #2015's TD, `validate_agents.sh`, and the diff were read from local branch `worker-2015-validators-vendor-invoke-261008083501-752797` at `f0533d233`. Also read: `scripts/framework/validate_agents.sh` on main at `a29f99a42`, `scripts/oversight/lib/vendor_invoke.sh`, `scripts/oversight/agents_static_logic.py`, `scripts/framework/check_agents_static.sh`, `scripts/oversight/validation_logic.py` (`compute_verdict`, `_cmd_process`), `scripts/framework/run_framework_validation.sh`, `scripts/framework/cut_release.sh:158`, `scripts/framework/install.sh`, `scripts/framework/framework_consumer_files.txt`, and `tests/framework/test_consumer_framework_files.py`.
**Next consumer:** `technical-design`, one TD covering S1 to S3 (§8).

---

## 0. Measurements and verification findings

All figures were measured on the working tree at `a29f99a42` on 2026-10-09. Simulations used byte-exact file sizes. Scratch scripts were not committed.

### 0.1 Corpus (full mode = `find .claude/agents -name '*.md'` + `docs/AGENTS.md` + `docs/OVERSIGHT-RUNBOOK.md`)

| Item | Bytes |
|---|---|
| 31 agent files (26 shipped, 5 hos-dev-pack) | 482,645 |
| `docs/AGENTS.md`: **largest single file** | 81,922 |
| `docs/OVERSIGHT-RUNBOOK.md` | 43,832 |
| **Total** | **608,399** |
| Largest agent file: `overseer.md` | 74,037 |
| Next largest: `oversight-evaluator.md`, `worker.md` | 68,022 · 65,705 |
| Current agy lens template (`validate_agents.sh:252-284`, excluding the package) | 1,742 |

Every single file is under the 180,000 B ceiling. The largest, `docs/AGENTS.md`, is 46% of the ceiling. No file is too large on its own. The problem is only the total.

**Release scope** is `cut_release.sh:158` → `--changed-only --base v0.6.0`. Today it is **91 files**, or 5,424,024 B as measured by #2015. Only **7** of the 91 are in the full-mode corpus: 5 agents and the 2 docs. The other 84 are design, ADR, spec, panel, and release-note files that `git diff --name-only BASE -- .claude/agents docs` (`validate_agents.sh:203`) picks up because it diffs **all of `docs/`**.

### 0.2 What a deterministic extractor can produce

Each figure was measured by running the existing `agents_static_logic` functions, or a single regex where noted, over the corpus.

| Candidate cross-file view | Size | Verdict |
|---|---|---|
| Escalation-verb edges (`extract_escalation_targets` + `classify_token`, agent sources only) | 36 directed edges, 8 cycles of length ≤ 3, < 1.2 KB | Precise but narrow. It misses most handoffs. |
| Mention edges: a backticked known agent name in file A, A ≠ B | 191 directed edges (116 agent↔agent pairs). Rendered with line refs: **8,653 B** | The main graph. |
| Path-reference table (`extract_path_refs` → `_clean_ref` → `filter_path_ref`, grouped by basename) | 48 basenames, 0 multi-variant today, **2,623 B** | Deterministic answer to lens item 4. |
| Backticked-term variant table (normalised by case, `_`/`-`, plural, basename) | 69 variant groups, **5,645 B**. Noisy. | Candidate generator for terminology drift. |
| Frontmatter + heading outline of every file | 30,329 B | Rejected (AD-2). Too costly per chunk for what it adds. |
| Verbatim "handoff lines" digest (every line naming an agent or a handoff verb) | **224,157 B** | Rejected. It is larger than the ceiling on its own. |

**VF-1 (a hazard the extractor must avoid).** `docs/AGENTS.md:1090` contains `name: agent-name` inside an example. A naive "any file's first `name:` line" rule turns that doc into a phantom agent with 20 edges. My first measurement did exactly this. Agent identity must come only from files under the agents directory, and only from the **leading frontmatter block** (AD-3).

### 0.3 Packing simulation (greedy edge cover, docs split at `## `)

At a unit budget of B = 141,000 B (derived in AD-6):

| Scope | Required edges | Chunks | Unit bytes sent (replication) | Infeasible whole pairs |
|---|---|---|---|---|
| Full mode | 116 agent↔agent pairs | **12** | 1,535,075 B (2.51×) | 1: `overseer` + `oversight-evaluator` = 142,139 B |
| Release, v0.6.0 focus (7 changed units) | 51 | **9** | 1,199,847 B (2.09×) | same pair |
| Full mode with doc↔agent edges also required | 226 | 18 | 2,289,771 B (3.75×) | same pair |

Using the AD-5 section fallback, each hub edge fits. Measured sizes for "the sections of A that name B, plus B whole":

| Directed edge | Bytes |
|---|---|
| `worker` → `overseer` | 132,139 |
| `overseer` → `worker` | 128,340 |
| `overseer` → `oversight-evaluator` | 113,107 |
| `worker` → `oversight-evaluator` | 93,695 |

These counts come from a greedy approximation, not the binding algorithm. The binding constraints are the coverage invariant and the cap (AD-5, AD-9). S3's acceptance re-measures with the real planner.

**VF-2 (a correction on record to #2015 AR-11 / ESC-2).** #2015's TD says both validators "ship to consumers (`tests/framework/test_consumer_framework_files.py:21-22`)". Those lines are in `_HOS_DEV_ONLY`, the list of files that must **never** ship. The release installer does **not** ship `validate_agents.sh`. The legacy `scripts/framework/install.sh --source` copy loop (L99-115) still does, but without `scripts/oversight/**`. So a validate_agents copied that way already lacks `vendor_invoke.sh` once #2015 lands. Consumer exposure is therefore narrower than #2015 ESC-2 states, but not zero. The worker should annotate #2015 with this. It does not change #2015's code. Here, AD-11 makes the missing-dependency case fail loudly.

---

## 1. Decision summary

| # | Decision (BINDING unless marked) |
|---|---|
| AD-1 | Cross-file coverage comes from two things: a **deterministic cross-file index in every chunk**, and **edge-cover packing** that puts the two ends of every agent↔agent reference in the same chunk. There is no AI summary pass. |
| AD-2 | The index contains only machine-extracted facts with file:line evidence. It is a pointer, not evidence. Reviewers must confirm everything in visible text. |
| AD-3 | New pure module `scripts/oversight/agent_graph_logic.py` builds the index and the edge set. It **reuses** `agents_static_logic` read-only and does not edit it. |
| AD-4 | New packing mode `cover` in #2014's `chunk_logic.py`. Units may repeat across chunks. Everything else in #2014 is reused unchanged. |
| AD-5 | Coverage invariant: every unit appears whole in ≥ 1 chunk, and every required directed edge A→B is co-resident, either whole or as A's naming sections plus B whole. If neither fits, the run fails loudly. |
| AD-6 | Byte budget comes from #2014 §4.2 unchanged. The index has its own bound of 24,576 B. Today B ≈ 141 KB. |
| AD-7 | Docs are split at `## ` (#2014 split-md-h2). Doc↔agent edges are **soft**: a packing preference, not guaranteed. |
| AD-8 | `--changed-only` **narrows** to the full-mode corpus (PROVISIONAL, ESC-2). It selects *edges incident to changed units*, not just the files that changed. |
| AD-9 | Calls are sequential. Cap 24 (lower-only env). Over the cap → `chunk_cap_exceeded`. Never sampled. |
| AD-10 | Aggregation uses the existing `validation_logic.py process` and #2014's `verify-run`. Coverage failure exits 1 and does not count as a pass. #2036 stays inert, and the exposure to #2032 is recorded. |
| AD-11 | The codex lane is **not chunked**. It stays a single whole-corpus call under the 1 MiB ceiling. |
| AD-12 | Scope: validate_agents only. `review_self.sh` and `run_red_team.sh` are not adopted, but `cover` mode is built so they can adopt it later. |
| AD-13 | Composition with #2015: S3 reuses #2015's lane machinery and never re-implements it. It works whether #2015 merges first or is held (§8). |

---

## 2. AD-1 / AD-2: how cross-file coverage is preserved (BINDING)

**Decision.** Every agy chunk prompt contains, in this order:
1. the lens, rewritten for chunks;
2. the known-issues block (unchanged);
3. **the CROSS-FILE INDEX** (deterministic, identical in every chunk);
4. #2014's preamble (chunk k of n, plus the unit inventory minus this chunk, AR-7);
5. the chunk's units.

The index has four sections, each sorted deterministically:
- **(a) Agent graph.** Every directed mention edge `A -> B @ Lx,Ly…`, with up to 12 line refs per edge and a `+N` count beyond that. Escalation-verb edges are marked `[esc]`. Edges from docs are included, so they show up as references.
- **(b) Escalation cycles.** Every elementary cycle of length ≤ 4 in the `[esc]` subgraph.
- **(c) Path-reference table.** Basename → every distinct cleaned path spelling, with the files using each.
- **(d) Term-variant table.** Normalised token → every backticked spelling, with a file count.

The lens must state: *"The index is machine-extracted and may be incomplete or include false matches. Never report a finding on the index alone. Confirm it in the text you can see. If the confirming text is not in this chunk, still report it, set `cross_chunk: true`, and name the file and line you would need."* The JSON schema gains an optional `cross_chunk` boolean. The fingerprint already ignores unknown keys (#2014 §6.5).

**Why deterministic and not an AI summary.** An AI-generated per-agent summary is a second unreviewed model output that is lossy, and that loss cannot be measured. It would sit between the reviewer and the text, and a summary that omits "B only accepts X after sign-off" makes the reviewer approve a mismatch it never saw. The deterministic index can be wrong in only two auditable ways: a missed edge or a false edge. Both are reproducible from the extractor and the input, and both are testable. The index also tells the reviewer *where* to look. It never claims *what* the text says, which is why AD-2 forbids index-only findings.

**Rejected alternatives.**
- **(R1) AI summary pass, then cross-check pass** (#2015 AQ-3's example). Rejected for the reason above. It also costs one extra call per agent or group.
- **(R2) A separate global AI pass that sees only the index and outlines.** It would produce findings no reviewer could ground in text, which is the hallucination-prone direction (cf. MEMORY: agy fabricating citations). The index already reaches every chunk, so a global pass adds a call and no evidence.
- **(R3) Verbatim handoff-line digest in every chunk.** It measured 224,157 B, larger than the ceiling (§0.2).
- **(R4) Outline digest, 30,329 B.** It costs about 21% of the unit budget in every chunk. The packing analysis shows that space is better used keeping hub pairs whole. Headings are visible anyway wherever the file is in the chunk.
- **(R5) #2014 grid.** It loses every same-axis (agent↔agent) relation. That is exactly the AR-6 objection.

### 2.1 What each finding class gets, and what is lost (stated, not waved away)

| Lens class | Mechanism | Caught when | Residual loss (named) |
|---|---|---|---|
| 1 Escalation loops | Index (b) lists every `[esc]` cycle of length ≤ 4. Cycles of length ≤ 3 are **required co-resident** (AD-5). | The cycle is in the `[esc]` graph and has length ≤ 3: all members are whole in one chunk. | A loop expressed in prose with no backticked name, or with no escalation verb, is not in the graph. It is caught only if packing happens to co-locate it. Cycles of length 4 are listed but not guaranteed co-resident. |
| 2 Dead ends | Deterministic part: `check_agents_static.sh` §4 (Phase 1, blocking) already fails on an unknown target. Semantic part: same as class 3. | The target exists but never describes the handoff: co-resident by AD-5. | A dead end to a role named in prose without backticks. |
| 3 Cross-file mismatches | **Every directed agent→agent mention edge is co-resident** (AD-5). | Always, for backticked references between agent files. | (i) References without backticks. (ii) Doc→agent edges are soft (AD-7); the guaranteed pairwise check is Phase 3 validate_docs once #2014 S1b lands. (iii) Edges covered in section fallback mode: B is whole, but A is seen only through its naming sections (A is reviewed whole in another chunk). |
| 4 File-path inconsistency | Index (c) gives full-corpus visibility in every chunk. `check_agents_static.sh` §3/§5 also checks deterministically. | Always, for backticked paths. | Paths in prose without backticks. |
| 5 Pipeline ordering | Same as 3, along each edge. | Adjacent pairs. | Chains of three or more steps that are not a cycle. The reviewer sees each adjacent pair, not always the whole chain. |
| 6 Invocation gaps (universally quantified: "no agent handles S") | `cross_chunk` reporting + inventory + index. | Gaps local to the chunk. | **Both directions.** False positives: "handled nowhere" when the handler is in another chunk. That is loud, and at blocking severity it fails the run (cf. #2014 AR-11). False negatives: a gap only visible across the whole corpus. This is the class with the largest loss. |
| 7 Terminology drift | Index (d) for backticked terms. Within a chunk, the full text. | Backticked variants anywhere. Prose variants inside one chunk. | Prose synonyms across chunks (for example "sign-off register" in one file and "approval log" in another). Not detectable deterministically. |

**Partial backstop.** The codex lane (AD-11) still reads the whole corpus in a single call. Its adversarial lens (contradictions, responsibility vacuum, missing loop exits) overlaps classes 1, 3 and 6. It is a backstop, **not** an equivalent: it has a different lens, its consumption is unverified (#1718 D6), and it is absent under `--skip-codex` or when codex is not installed. The design does not claim it closes the gaps above.

Per #2014 AR-11, recurring false positives from class 6 come back to the architect. They must never be "fixed" by down-ranking `cross_chunk` findings.

---

## 3. AD-3: `scripts/oversight/agent_graph_logic.py` (BINDING)

- Pure Python, stdlib only. The logic functions do no I/O; a CLI shim does it (#314, same shape as SPEC-336).
- **Reuse, read-only by import** (repo-root `sys.path` idiom, #2014 AR-1). The imported functions are `extract_escalation_targets`, `classify_token`, `extract_path_refs`, `filter_path_ref`, and `_clean_ref`. `_clean_ref` is #1846's single source of truth for cleaning, so the module must not re-derive it. A test imports all five names so a rename breaks loudly. **`agents_static_logic.py` is not edited.** Its "no behaviour change" contract stays intact.
- **New in this module.** Mention-edge extraction (backticked token ∈ known agents, with line numbers). Cycle enumeration. Term normalisation. Index rendering. Emission of the edge set as JSONL for `chunk_logic` (`{"src","dst","kind":"agent|doc","lines":[...]}`) and of cycles as hyperedges.
- **Agent identity (VF-1).** A unit is an agent if, and only if, its path is under `--agents-dir` **and** its leading `---` frontmatter block has `name:`. Docs never produce agent identities. The non-agent token lists (`NON_AGENT_TOKENS`, `KNOWN_LABELS`, `KNOWN_SHORT_AGENTS`) are passed in by the shell as `check_agents_static.sh` does, never re-hardcoded in Python. Moving them into one shared place is a follow-up, not part of this slice.
- **Determinism.** Identical input bytes produce identical index bytes and identical edge JSONL. A test pins this.
- **Bound.** If the rendered index is over **24,576 B**, the module first collapses (d) to group counts. If it is still over, it exits 3 with `fixed_context_too_large`. It never silently truncates (#2014 AR-7 pattern). Measured today: about 17.4 KB, which leaves about 30% headroom.

## 4. AD-4 / AD-5: `cover` mode in `chunk_logic.py` (BINDING)

**What is reused unchanged from #2014:**
- the `markers` subcommand and per-run nonce (AR-4);
- the exactly-once marker rule;
- the template-render-and-measure byte budget (§4.2) and `--reserve-bytes` from `chunked_review_reserve_bytes`;
- the preamble and inventory (§4.4, AR-7);
- `split-md-h2` and its fence rule (§4.3);
- the `--out-dir` emptiness rule;
- exit codes 0/2/3/4;
- the `hos-chunk-manifest/1` envelope;
- `record-result` (AR-8, hashing in Python);
- `verify-run` (one record per chunk id, outcome, sha);
- `resolve_max_chunks` (lower-only);
- `plan --dry-run` (AR-3);
- the whole `chunked_review.sh` lane loop: salvage, single prose retry, consumption check, never retrying on `unconsumed`.

**What is new:**
- **Mode `cover`.** `plan --mode cover --units FILE --edges FILE [--hyperedges FILE] [--focus FILE] --split-kind doc …`.
- **Units may appear in more than one chunk.** The pack-mode proof "every unit exactly once" is replaced by the invariant below.
- **Coverage invariant (AD-5), asserted in `plan` and recomputed by `verify-run --input`:**
  1. Every unit (agents whole; docs as their full set of h2 parts) appears in ≥ 1 chunk. An agent's appearance must be **whole**.
  2. For every **required** directed edge A→B, some chunk contains B whole and either A whole (the preferred form) or **every h2 section of A that names B**. That second form is the *section fallback*, rendered with the label `EXCERPT: sections i,j of n of <A> (A is reviewed whole in chunk-NNN)`.
  3. Every required hyperedge (an `[esc]` cycle of length ≤ 3) has all members whole in one chunk. If that does not fit, it degrades to its member edges under rule 2, and the degradation is recorded.
  4. If B whole plus A's naming sections is still over B (the budget), exit 3 `edge_too_large`, naming both files and the byte counts. **Agents are never cut except as a section fallback that is *in addition to* a whole appearance**, so #2014 D5's "agents are the source of truth and are never cut" holds: no agent is ever reviewed only as fragments.
- **Manifest `coverage` for cover mode:**
  ```
  {units_whole_covered: true,
   edges_required, edges_whole, edges_section_fallback: [{src, dst, chunk}],
   hyperedges_required, hyperedges_whole, hyperedges_degraded: [...],
   soft_edges, soft_edges_coresident}
  ```
- **Packing algorithm.** Deterministic greedy weighted edge cover:
  - Seed each new chunk with the unit that has the most uncovered required edges (ties: bytes desc, path asc).
  - Add units by uncovered required edges per byte, then soft edges per byte, then placing a not-yet-placed unit.
  - Emit units within a chunk in path order.

  The TD may improve the heuristic. It may not weaken the invariant, and it must remain independent of input order (a shuffled-units test, as #2014 AR-3).

**Rejected alternatives.**
- **(R6) A parallel chunker for validate_agents.** Rejected: #2014 D1/D3, one planning primitive.
- **(R7) Fail loudly on any infeasible whole pair** (#2014 D5 applied literally). Today's ~1 KB overshoot on `overseer` + `oversight-evaluator`, and the 1.3 KB margin on `overseer` + `worker`, would disable the gate on the next edit to any hub agent.
- **(R8) Line-window excerpts (±N lines).** Arbitrary cut points that split instructions mid-rule. h2 sections are the authored unit, and the machinery already exists.

## 5. AD-6: byte-budget arithmetic (BINDING formula; figures measured or bounded)

`B = 180,000 − R − T − P_max` (#2014 §4.2 unchanged), computed **per run** by `plan` from the rendered template. It is never estimated in code. Today:

| Term | Value | Source |
|---|---|---|
| Ceiling | 180,000 | `vendor_invoke_max_bytes agy` (never restated, #2014 D2) |
| R (reinforce suffix) | ≈ 0.3 KB | `chunked_review_reserve_bytes` |
| T: lens | ≈ 3.3 KB | 1,742 measured + about 1.5 KB of chunk instructions |
| T: known issues | ≤ about 13 KB | live, `gh issue list --limit 100`, measured in T each run |
| T: index | ≈ 17.4 KB (bound 24,576) | §0.2: 8,653 + 2,623 + 5,645 + cycles |
| P_max | ≈ 4.5 KB (bound 8,192) | #2014 AR-7 inventory over 54 unit names |
| **B** | **≈ 141 KB** | |

Consequences, stated plainly:
- The largest agent (74,037 B) is 52% of B, so no single agent comes close to `unit_too_large`.
- The hub pairs are at the boundary: 142,139 is about 1 KB over B, and 139,822 is about 1.3 KB under. **Section fallback is a routine path on today's tree, not an edge case.** The [COVERAGE] section reports it every run.
- Because the known-issues block is live, the same tree can plan differently on different days. Every run records its plan in the manifest (`input_sha256`), which is acceptable. The worst-case tightening (index at its bound plus 13 KB of issues) gives B ≈ 134 KB. Every measured section-fallback edge (≤ 132,139 B) still fits.
- **What happens if a single file exceeds the budget:**
  - An agent over B → `unit_too_large`, exit 3, loud. Fixing it means splitting the agent definition, which is a human-visible authoring decision.
  - A doc over B → split at `## `. A single section over B → exit 3.
  - An edge whose fallback is over B → `edge_too_large`, exit 3.
  - Nothing is ever truncated or sampled.

## 6. AD-7 / AD-8: docs and release scope

**AD-7 (BINDING, consequence in ESC-3).** `docs/AGENTS.md`, `docs/OVERSIGHT-RUNBOOK.md`, and any configured `DESIGN_PACK_PATH`/`EXTRA_REVIEW_FILES` `*.md` files are doc units, split with `split-md-h2`. Non-markdown extras are single units, and if over budget, `unit_too_large`. Doc→agent edges are **soft**: the packer prefers to put each doc part with the agents it names, but this is not required.
- *Why.* Making them required raises full mode from 12 to 18 chunks (2.29 MB, §0.3). The pairwise doc↔agent check is validate_docs' job: #2014 §8.1 puts both docs on its ref axis, and every doc↔agent pair is co-resident there. Keeping docs whole was rejected: in simulation, `docs/AGENTS.md` ended up alone in a chunk with no agent, which is the worst placement for a consistency lens.

**AD-8 (PROVISIONAL, ESC-2).**
- **Corpus.** `--changed-only` selects within the full-mode corpus and never widens it: `changed ∩ corpus`.
- **Focus mode.** The chunk plan then covers:
  - the changed units, each whole;
  - every required edge incident to a changed unit, in either direction;
  - every required cycle that contains a changed unit.

  The rest of the corpus feeds the index and the inventory but is not placed.
- Measured for v0.6.0: 51 edges, **9 chunks**. If the intersection is empty, today's WARN-then-full-mode fallback (`validate_agents.sh:204-207`) stays.
- *Why.* (i) The lens is agents plus the two governance docs. The other 84 release-scope files (ADRs, TDs, panels) are not its subject, and reviewing them would take about 35 more chunks for noise. (ii) Today's `--changed-only` reviews a changed agent *without* its counterparts, which is the exact AR-6 failure. Focus mode reviews every changed agent next to every agent it references or that references it.
- *If ESC-2 is answered no.* The 84 extra files become additional doc units in cover mode, with no required edges. Release Phase 2 then needs about 40+ chunks, which is over the cap of 24. It would fail as `chunk_cap_exceeded` until the cap is raised by a reviewed change. And the codex lane (AD-11) stays refused at 5.4 MB. So "no" in practice means Phase 2 cannot pass at release.

## 7. AD-9 / AD-10 / AD-11: cost, aggregation, codex

**AD-9: cost and caps (BINDING; the cost model is ESC-4).**
- Calls are sequential (#2014 §7).
- Cap: reviewed constant **24** for validate_agents. It may be lowered via the existing `FRAMEWORK_VALIDATION_MAX_CHUNKS`, clamped per caller by `resolve_max_chunks`. Raising it requires a reviewed edit.

| Mode | agy calls (measured plan) | agy input (approx.) | Worst case at cap |
|---|---|---|---|
| Full | 12 (today: 1, refused under #2015) | ≈ 2.0 MB | 24 × 300 s = 2 h; 4 h if every chunk takes the prose retry |
| Release, focus | 9 | ≈ 1.55 MB | same |

- A release cut with #2014 S1b in place therefore makes about 9 + 18 + 9 ≈ **36 agy calls** across Phases 2–4.
- The single codex call is unchanged.
- Full-mode n grows roughly with the number of hub agents and their edge count, not with total bytes alone. `plan --dry-run` prints n before the run (#2014 AR-3), and `run_framework_validation.sh` prints it before Phase 2.

**AD-10: aggregation, verdict, and fail-closed coverage (BINDING).**
- **Sections.** One per chunk: `## agy — Consistency + Completeness [chunk k/n]`. The heading never contains "skipped". When n > 1, a verdict-inert `## [COVERAGE] Chunked review (#2014/#2033)` section goes in a **plain** fence (#2014 §6.6, AR-5 key rules). It lists every section-fallback edge and degraded cycle.
- **Re-serialisation (#2014 AR-9 + #2015 AR-3).** Every block written inside a ```` ```json ```` fence is the salvaged object re-serialised by Python, with backticks escaped to ```. Raw vendor stdout never goes inside a json fence. An unparseable chunk is a coverage failure (#2014 AR-6: validate_agents is not a prose-tolerant caller, so no `--allow-unparseable`).
- **Verdict.** Unchanged. A single `validation_logic.py process --strict-empty` runs over all blocks, so a chunk block is just another block. **validate_agents must not write any verdict into the header before `process`.** The header starts at `pending`, so `process`'s no-downgrade ratchet has nothing to hold. That keeps **#2036 inert** for this caller. A pre-aggregation step would make it live, and is forbidden.
- **#2032 is live here.** Unlike validate_docs, this caller *does* use `compute_verdict`, which ignores a block-level `request_changes` that comes with null or empty findings. Chunking leaves the per-block semantics unchanged but multiplies the number of blocks, so exposure rises. This design neither fixes #2032 nor depends on its fix. **Coupling to record (worker → #2032):** #2032's fix covers validate_agents, and its tests should include a multi-block chunked fixture.
- **Coverage gate.** After the agy lane, the shell keeps `verify-run`'s exit status. If it is non-zero:
  - append the failure block (`verdict: error`, `chunk_coverage` payload, built by #2015's `_agents_vi_failure_json` pattern);
  - print FAIL;
  - write **no stamp**;
  - exit **1**, regardless of the finalizer;
  - **do not count the run as a review pass**, so it never exits 3 "did not converge" for what is an operational failure. The pass counter is restored.

  Plan failures (exits 2/3/4) take the same path with their named detail, and no vendor is launched.
- **Timeout guard.** #2015's `_vi_unenforceable_reason agy` (AD-16.6, AR-1/AR-4) is checked **once, before `plan`**. If the reason is non-empty, write one error block and launch nothing.
- **Dedup and convergence.** The fingerprint (sorted files, class) and the ledger are unchanged. Hub files appear in about 2.5 chunks on average, so the same finding can come back from several chunks. Before it is dispositioned it inflates `blocking_count`; one `--record` dedups every same-fingerprint copy. Copies with different `files` lists need separate records. That is a real triage cost, accepted and not hidden. The pass cap (`EXTERNAL_REVIEW_MAX_PASSES`) counts runs, not chunks.

**AD-11: codex lane (BINDING).**
- The codex lane is **not chunked**, and it receives no index.
- It stays #2015's single `_vi_lane codex attacks` call under the 1,048,576 B ceiling (#1718 AR-1).
- Full-mode prompt: 608,399 B of corpus plus headers, template, and known issues ≈ 0.63 MB. That is 60% of the ceiling, with about 400 KB of headroom.
- Under AD-8, release scope is ≤ full mode.
- *Why.* Its adversarial lens (bypass chains, vacuum, contradictions) is the most cross-file lens of all (#2014 AR-12), and it currently fits whole.
- Above 1 MiB it fails loudly with `prompt_too_large` (#2015). It is not silently decomposed. When that happens, extending `cover` to codex needs a new decision.

## 8. Slices (each ≤ 15 files, ≤ 10 commits)

**S1: `agent_graph_logic.py`.**
- Risk HIGH: its output defines a release gate's coverage guarantee, and a missed edge silently lowers it. Not protected.
- **Not gated** on #2014, #2015, or any ESC. No caller, so merging it changes no behaviour.
- Reviewers: code, reliability.
- Files (6): `scripts/oversight/agent_graph_logic.py` (new) · `tests/oversight/test_agent_graph_logic.py` (new) · `DECISIONS.md` · `SCRIPTS-INDEX.md` (via `regen_all.sh`) · prompt artifact · `docs/v0.7.0/ADR-2033-…` (status line only).
- Tests:
  - the five-name import pin;
  - VF-1 (a doc carrying `name:` is not an agent);
  - determinism (same input, same index bytes; shuffled file order, same output);
  - the index bound and collapse; over the bound → exit 3;
  - cycles on a synthetic graph;
  - a path variant detected;
  - on the live tree: ≥ 116 agent↔agent edges and index ≤ 24,576 B.

**S2: `cover` mode in `chunk_logic.py`.**
- Risk HIGH. Not protected.
- **Gated on #2014 S1a merged.** It extends that module, never forks it.
- Condition (cf. #2014 §12): every #2014 S1a test passes **unmodified**, so the pack and grid modes stay byte-identical.
- Reviewers: code, security, reliability.
- Files (≤ 6): `scripts/oversight/chunk_logic.py` · `tests/oversight/test_chunk_logic_cover.py` (new) · `DECISIONS.md` · `SCRIPTS-INDEX.md` · prompt artifact.
- Tests:
  - every required edge co-resident;
  - every unit whole at least once;
  - section fallback exactly when the whole pair is over B, with the excerpt label naming the whole-copy chunk;
  - `edge_too_large` → exit 3 naming both;
  - cycle co-residency and its degradation;
  - focus mode restricts edges correctly;
  - shuffled input gives an identical manifest;
  - every prompt ≤ max − reserve;
  - `verify-run --input` recomputes the cover proof and fails when a manifest is tampered with to drop an edge;
  - n > M → exit 4;
  - a 400 KB synthetic corpus with hub nodes plans under `--max-bytes 180000`.

**S3: validate_agents.sh wiring.**
- Risk HIGH. **Protected** (human approval at merge).
- **Gated on:** S1 merged · S2 merged · #2014 S1a (`chunked_review.sh`) merged · #2015 per AD-13 · ESC-1, -2, -3, -4, -5 answered on record.
- Reviewers: code, security (index and known-issues text are attacker-influenceable prompt content; re-serialisation), reliability (coverage gate, timeout guard, wall time). Cross-vendor second review applies at HIGH.
- Files (≤ 9): `scripts/framework/validate_agents.sh` · `scripts/framework/run_framework_validation.sh` (dry-plan print before Phase 2. #2014 S1b edits the same file, and whichever lands second rebases) · `tests/framework/test_validate_agents_chunked.py` (new) · `tests/framework/test_framework_validators_vendor_invoke.py` (amend, see §10) · `docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md` (dated §7 annotation: "validate_agents: chunked, #2033") · `DECISIONS.md` · `prompts/scripts/framework/validate_agents.md` · prompt artifact.
- Hermetic tests:
  - a fixture corpus of about 400 KB with two 70 KB hub agents gives ≥ 3 agy stub calls, each stdin ≤ 180,000 B; every fixture file appears whole in some stub stdin, and every fixture edge's two ends share one stdin;
  - all approve → exit 0 and stamp;
  - one chunk stub fails → exit 1, no stamp, `chunk_coverage_failed`, pass counter not advanced;
  - an unterminated JSON chunk followed by a `request_changes` chunk → exit 1 (AR-9);
  - a prose chunk → exit 1;
  - no `timeout` binary → no plan and no stub launched;
  - codex stub called exactly once, with no index in its stdin;
  - `--changed-only` against a fixture base: unchanged unrelated files are not placed, and changed files' neighbours are;
  - release-style `docs/v9/X.md` changes are excluded (AD-8);
  - the header is `pending` before `process` runs (#2036 guard).
- **Acceptance (live, recorded on the PR, issue requirement):**
  - `plan --dry-run` on the current repo shows n ≤ 24 and every `prompt_bytes ≤ 180,000 − R`;
  - one full-mode `validate_agents.sh` run whose agy lane **completes** with every chunk `ok` and `verify-run` exit 0;
  - every blocking `cross_chunk: true` finding is listed with a human's true/false judgement (#2014 AR-11).

**AD-13: composition with #2015 (BINDING).**
- S3 does not re-implement anything #2015 introduces: the `vendor_invoke` sourcing, `_vi_unenforceable_reason`, `_agents_vi_failure_json`, backtick neutralisation, or the codex `_vi_lane`.
- **If #2015 is merged first** (its ESC-1 = merge fail-closed now): S3 branches from main. Until S3 merges, the full-mode agy lane fails closed with `prompt_too_large`, which #2015 ESC-1 has already accepted.
- **If #2015 is held** (ESC-1 = hold until chunking): S3 is **stacked on #2015's branch**, and the merge order is strictly #2015 then S3, as separate PRs with separate review records. #2015's "hold" condition is met when S3 is *approved and mergeable*, not when it is merged. There is no deadlock.
- **If #2015 is rejected or materially reworked:** S3 stops and returns to the architect. It must not silently absorb #2015's lane migration.

## 9. Escalations (human): each a yes/no question

These are product-boundary checkpoints. pm-agent assesses product impact. The human decides.

- **ESC-1 (consumption flags; answer jointly with #2014 ESC-1).** May validate_agents' agy chunks run `--sandbox --output-format json`, so every chunk gets a real #1718 consumption check through `chunked_review.sh`? #2015 D2 chose `--sandbox` alone, and that leaves consumption permanently `unverified`. *Recommended: yes, with one ruling for all three validators.* If no, the chunks run `--sandbox` with consumption recorded as `unverified`, and the 180,000 B ceiling is the only bound on truncation.
- **ESC-2 (AD-8 release scope).** Should `--changed-only` narrow to the full-mode corpus (agents + the two docs + configured extras)? Today it reviews all of `docs/**`: 91 files, 5.4 MB, 84 of them design and ADR history. In exchange, it gains focus-mode neighbour coverage. *Recommended: yes.* "No" leaves release Phase 2 unable to pass (§6).
- **ESC-3 (coverage model).** Is the §2.1 coverage model an acceptable basis for release Phase 2? It has four parts: every backticked agent↔agent reference co-resident, with section fallback for hub pairs (a routine path today); doc↔agent edges best-effort, with Phase 3 owning the pairwise check; cross-chunk prose synonyms and corpus-wide "handled nowhere" gaps not guaranteed; and "handled nowhere" false positives that can fail a run until a human dispositions them. *Recommended: yes.* The alternative is no agy lane at all in full mode.
- **ESC-4 (cost model).** Accept about 12 agy calls (≈ 2.0 MB) per full-mode run where today there is 1, and about 9 per release cut? Cap 24 per run, worst case 2 h (4 h with retries), sequential. Together with #2014 S1b, that is about 36 agy calls per release cut. *Recommended: yes.* Release cuts are manual and infrequent, and #1146 owns cycle deadlines.
- **ESC-5 (operational obligation).** `framework-validator` (`.claude/agents/framework-validator.md:42`, reached via `post-change-sweep`) runs `validate_agents.sh` in full mode inside an agent Bash call, which is capped at 600 s. Twelve sequential calls will usually exceed that. The kill leaves no verdict, so "not validated" must be read from the missing PASS line. Accept this, with a follow-up issue (protected surface `.claude/agents/**`) to move that invocation to focus mode run in the background, or to a human-run step? *Recommended: yes, with the follow-up filed before S3 merges.*

## 10. Affected sign-offs and startup-gap check

- **Startup gap: no.** Chunking was deliberately deferred at #1718 (F1) and at #2015 (AR-6), and that consequence was cleared there. This ADR revises no prior ADR.
- **#2015's sign-offs** on validate_agents' agy lane: they stand as approvals of #2015's diff. S3 rewrites that lane, so S3's own HIGH-tier reviewers re-review it. Three #2015 test assertions that concern **validate_agents' agy lane only** are superseded, and S3 must amend them explicitly, citing this ADR. Those are T1 (argv exactly `["--sandbox"]`, which changes if ESC-1 is yes), T3 (oversized → `prompt_too_large`, which becomes chunked), and T8 (exactly one `vendor_invoke agy` call site in validate_agents.sh, which moves into `chunked_review.sh`). Every validate_scripts assertion, and every codex-lane assertion, stays unmodified. Any other edit to #2015's tests voids this ruling and needs re-review against #2015 AR-2/AR-3/AR-4.
- **#2014's sign-offs:** they stand, on the S2 condition that the S1a tests pass unmodified.
- **#2015 AR-11 factual correction (VF-2):** the worker annotates #2015. It does not change #2015's code or the merge gate. It only narrows the stated consumer exposure.

## 11. AD-12: scope boundaries and follow-ups (the worker files these; the architect files nothing)

- `review_self.sh` and `run_red_team.sh` were routed here by #2014 AR-2, ESC-7, and ESC-8. They are **not adopted** in #2033. `cover` mode takes its edges as an input file, so either script can adopt it later with its own edge extractor (agents↔scripts↔contract path references, or component call edges). That needs a separate issue and a separate decision for each.
- Follow-ups:
  - (a) the ESC-5 `framework-validator` invocation change;
  - (b) annotate #2032 with the validate_agents coupling (AD-10);
  - (c) annotate #2015 with VF-2;
  - (d) a single shared source for `NON_AGENT_TOKENS`, `KNOWN_LABELS`, and `KNOWN_SHORT_AGENTS`, which today live in `check_agents_static.sh` and will be passed into S1's module (AD-3).

**Status: Proposed (architect).** S1 may go to `technical-design` and `coder` now. S2 waits for #2014 S1a to merge. S3 waits for its gates in §8 and for ESC-1 to ESC-5 on record. Any deviation from AD-1 to AD-13 comes back to the architect.
