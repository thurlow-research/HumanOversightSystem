# ADR-2033: Cross-file chunked review for validate_agents.sh. A deterministic agent graph in every chunk, and chunks packed so every directed agent-to-agent reference is co-resident

**Status:** Proposed (architect), **round 4**, revised after the technical-design review (round 2: REQUEST_CHANGES; rounds 3 and 4: APPROVE_WITH_CONDITIONS on `6d2b4e163` and `18cefbb10`; see §12, Revision log). Decisions marked BINDING bind `technical-design`, `coder`, `code-reviewer`, and the reviewers once their gating ESC items (§9) are cleared on record. Decisions marked **PROVISIONAL (ESC-n)** are drafted on the recommended answer. None is treated as ruled by the human.
**Date:** 2026-10-09
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #2033 (priority:high, v0.7.0) · **Risk tier: HIGH.** S3 touches `scripts/framework/**`, a protected surface, so human approval is required at merge whatever the computed tier.
**Origin:** #2015 architect ruling AR-6 (validate_agents' lens spans files and needs its own decision). #2014 AR-2 / ESC-7 / ESC-8 also point `review_self.sh` and `run_red_team.sh` at this design. Their disposition is ESC-6.
**Inputs read:**
- `docs/v0.7.0/TECHNICAL-DESIGN-2014-chunked-vendor-review.md` (all, including §13 AR-1 to AR-14).
- `docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md` (§2, §3, §7).
- #2015's TD, `validate_agents.sh`, and `tests/framework/test_framework_validators_vendor_invoke.py`, read from local branch `worker-2015-validators-vendor-invoke-261008083501-752797` at `f0533d233`.
- On main at `a29f99a42`: `scripts/framework/validate_agents.sh`, `scripts/oversight/lib/vendor_invoke.sh`, `scripts/oversight/agents_static_logic.py`, `scripts/framework/check_agents_static.sh`, `scripts/oversight/validation_logic.py` (`compute_verdict`, `_cmd_process`), `scripts/framework/run_framework_validation.sh`, `scripts/framework/cut_release.sh:146-160`, `scripts/framework/install.sh`, `scripts/framework/framework_consumer_files.txt`, `scripts/framework/consumer_agents.txt`, `tests/framework/test_consumer_framework_files.py`, and `scripts/run_second_review.sh:734-739` (the reinforce suffix).

**Next consumer:** `technical-design`, one TD covering S1 to S3 (§8).

---

## 0. Measurements and verification findings

All figures were re-measured on the working tree at `a29f99a42` on 2026-10-09, using the pinned definitions in AD-3. Simulations used byte-exact sizes. Unit headers (`=== FILE: <path> ===\n`, 37 to 48 B each) are **included** in every unit and pair size below. A whole pair therefore carries about 80 B of headers. Scratch scripts were not committed.

### 0.1 Corpus

Full mode is `find .claude/agents -name '*.md'` + `docs/AGENTS.md` + `docs/OVERSIGHT-RUNBOOK.md`.

| Item | Bytes (content only) |
|---|---|
| 31 agent files: 27 shipped (`consumer_agents.txt`) + 4 HOS-dev-only (`doc-validator`, `framework-setup-validator`, `framework-validator`, `spec-compliance-validator`) | 482,645 |
| `docs/AGENTS.md`: **largest single file**. 9 h2 parts, largest part 57,789, outline 2,147 | 81,922 |
| `docs/OVERSIGHT-RUNBOOK.md`: 14 h2 parts, largest part 18,065, outline 1,238 | 43,832 |
| **Total** | **608,399** |
| Largest agent file: `overseer.md` | 74,037 |
| Next largest: `oversight-evaluator.md`, `worker.md` | 68,022 · 65,705 |
| Current agy lens template (`validate_agents.sh:252-284`, excluding the package) | 1,742 |
| Known-issues block today (100 open titles; measured by the TD reviewer) | 13,324 |

All 31 agent files have a `name:` in their leading frontmatter block. No single file exceeds the ceiling, or any budget derived in AD-6. The problem is only the total.

**Release scope** is `cut_release.sh:158` → `--changed-only --base v0.6.0`, used for minor and patch bumps only (#130, `cut_release.sh:146-151`). Major bumps use the full corpus. Today the release scope is **91 files**, or 5,424,024 B as measured by #2015. Only **7** of them are in the full-mode corpus: 5 agents and the 2 docs. The other 84 are design, ADR, spec, panel, and release-note files. `validate_agents.sh:203` picks them up because it diffs **all of `docs/`**.

### 0.2 What a deterministic extractor produces

All counts use the pinned mention rule (AD-3).

| Index section | Size | Notes |
|---|---|---|
| (a) Agent graph: directed mention edges with line refs | **191 directed edges in total; 136 are agent→agent, forming 116 unordered pairs.** Rendered size 8,588 B. | Main graph. |
| `[esc]` subset (`extract_escalation_targets` + `classify_token`) | 36 directed edges, 8 cycles of length ≤ 3 | Precise but narrow. |
| (c) Path-reference table | 48 basenames, 0 multi-variant, 2,623 B | Deterministic answer to lens item 4. |
| (d) Backticked-term variant table | 69 groups, 5,645 B, noisy | Drift candidate generator. |
| Rejected: frontmatter and outline digest of every file | 30,329 B | AD-1 (R4). |
| Rejected: verbatim handoff-line digest | 224,157 B | Larger than the ceiling. |

Total index today is about **17.4 KB** (bound 24,576 B).

**VF-1.** `docs/AGENTS.md:1090` holds `name: agent-name` inside an example. Any rule of the form "any file's `name:` line" turns that doc into a phantom agent. Agent identity is therefore pinned to the leading frontmatter of files under the agents directory (AD-3).

### 0.3 Hub edges and packing (round 2: re-measured under the pinned rule)

Round 1's fallback sizes (132,139 / 128,340 / 113,107 / 93,695) were computed with a raw substring rule. That rule did not match the edge rule, so those numbers are **withdrawn**. Under the pinned rule, `worker.md` contains no `` `overseer` `` span, and `oversight-evaluator.md` names neither hub. Only three hub edges exist:

| Directed edge (A names B) | Line refs in A | Whole pair, with headers | Section fallback: A's naming sections + B whole + ~120 B excerpt label |
|---|---|---|---|
| `overseer` → `oversight-evaluator` | L131 | 142,152 | **69,301** (1 of 14 sections) |
| `overseer` → `worker` | L130 | 139,822 | **66,971** (1 of 14) |
| `worker` → `oversight-evaluator` | L380, L942 | 133,818 | **92,669** (2 of 11) |

None of the reverse edges exist, so no hub pair needs a fallback in both directions.

**Which edges need the fallback today (round 3).** Today's B_budget is about **139.65 KB**. That is the technical-design reviewer's exact figure, and it supersedes my round-2 estimate of ≈ 139.8 KB. At that budget the `overseer` + `worker` whole pair (139,822 B) does **not** fit, so **2 edges need the section fallback today**: `overseer` → `oversight-evaluator` and `overseer` → `worker`. The `overseer` + `worker` pair sits within about 0.2 KB of the boundary, so known-issues churn can flip it from run to run. At the worst-case bound, all 3 hub edges need the fallback.

**Chunk counts (approximate).** These come from two independent greedy planners: the architect's and the technical-design reviewer's. Both use the AD-5 invariant, always-split docs, and soft doc edges.

| Scope | Required directed edges | Today's budget (≈ 139.65 KB) | Worst-case bound (122,766) |
|---|---|---|---|
| Full mode | 136 | **11 to 12 chunks**, 2 section fallbacks, ≈ 1.5 MB of units | **13 to 15 chunks**, 3 fallbacks, ≈ 1.6 MB |
| Release focus, v0.6.0 (5 agents + 2 docs) | 58 | **8 to 9 chunks** | **10 chunks** |

These counts are approximate. The binding constraints are the invariant and the cap of 24 (AD-5, AD-9). **S3's live `plan --dry-run` is the measurement of record.** No edge comes near `edge_too_large` at either budget: the largest fallback is 92,669 B, which leaves about 30 KB of margin at the worst-case bound.

**VF-2 (a correction on record to #2015 AR-11 / ESC-2).** #2015 says both validators "ship to consumers (`test_consumer_framework_files.py:21-22`)". Those lines are in `_HOS_DEV_ONLY`, the never-ship list. The release installer does not ship `validate_agents.sh`. The legacy `scripts/framework/install.sh --source` copy loop (L99-115) still copies it, but without `scripts/oversight/**`. The worker annotates #2015. AD-11 below makes a missing dependency fail loudly.

---

## 1. Decision summary

| # | Decision |
|---|---|
| AD-1 | Cross-file coverage comes from a **deterministic cross-file index in every agy chunk**, plus **edge-cover packing** over directed agent→agent edges. There is no AI summary pass. (BINDING) |
| AD-2 | The index is a pointer, not evidence. Findings must be confirmed in visible text. (BINDING) |
| AD-3 | New pure module `agent_graph_logic.py`, with one pinned mention rule and one pinned naming-section rule. It reuses `agents_static_logic` read-only. (BINDING) |
| AD-4 | New `cover` mode in #2014's `chunk_logic.py`. It states exactly what is reused unchanged and what is new, and adds a per-chunk result-file interface required of #2014's lane loop (§4.5). (BINDING) |
| AD-5 | Coverage invariant over the **placed set**, per directed edge. The section fallback keeps B whole. A run fails loudly if an edge cannot fit. (BINDING) |
| AD-6 | Budget follows #2014 §4.2. Known issues are deterministically capped at 16,384 B. Feasibility is proven at the worst-case bound. (BINDING) |
| AD-7 | Docs are **always** split at `## ` (a new trigger, reusing the split function). Doc edges are soft. (BINDING) |
| AD-8 | `--changed-only` narrows to the corpus and plans focus plus required neighbours. Context-only findings are non-blocking. (PROVISIONAL, ESC-2) |
| AD-9 | Sequential calls. Cap 24 (lower-only). Never sampled. (BINDING; cost is ESC-4) |
| AD-10 | Per-chunk blocks: Python re-serialisation for success, `_agents_vi_failure_json` shape for failure. The block verdict after routing is pinned, so the result is correct whether or not #2032 is fixed. Coverage gate exits 1 and is not counted as a pass. #2036 stays inert. (BINDING) |
| AD-11 | Codex is not chunked. Its input is a stated contract in both modes. (BINDING) |
| AD-13 | Composition with #2015: S3 reuses #2015's lane machinery and never absorbs it. The meaning of "hold" is ESC-7. (BINDING except where marked) |

AD-12 from round 1 (declining `review_self.sh` and `run_red_team.sh`) is withdrawn as a binding and is now **ESC-6**.

---

## 2. AD-1 / AD-2: how cross-file coverage is preserved (BINDING)

**Decision.** Every agy chunk prompt contains, in this order:
1. the lens, rewritten for chunks, with a bound of 4,096 B pinned by a test;
2. the known-issues block, capped as in AD-6;
3. the **CROSS-FILE INDEX** (deterministic, identical in every chunk of a run);
4. the cover-mode preamble (§4.3);
5. the chunk's units.

The index has four sections, each sorted deterministically:
- **(a) Agent graph.** Every directed mention edge `A -> B @ Lx,Ly…`, with up to 12 line refs and a `+N` count beyond that. Escalation-verb edges are marked `[esc]`. Doc-sourced edges are included as references.
- **(b) Escalation cycles.** Every elementary cycle of length ≤ 4 in the `[esc]` subgraph.
- **(c) Path-reference table.** Basename → every distinct cleaned path spelling, with the files using each.
- **(d) Term-variant table.**

The lens must say: *"The index is machine-extracted and may be incomplete or include false matches. Never report a finding on the index alone. Confirm it in the text you can see. If the confirming text is not in this chunk, still report it, set `cross_chunk: true`, and name the file and line you would need."* The JSON schema gains an optional `cross_chunk` boolean. The fingerprint ignores unknown keys.

**Why deterministic.** An AI summary is a second, unreviewed, lossy model output sitting between the reviewer and the text, and its loss cannot be measured. The deterministic index can be wrong in only two ways: a missed edge or a false edge. Both are reproducible and testable. And it only says *where* to look, never *what* the text says.

**Rejected alternatives.**
- **(R1)** AI summary pass, then a cross-check pass. Rejected for the reasons above, plus one extra call per agent or group.
- **(R2)** A global AI pass over the index alone. It produces findings no reviewer can ground in text, which is the fabrication-prone direction.
- **(R3)** A verbatim handoff-line digest: 224,157 B, larger than the ceiling.
- **(R4)** An outline digest: 30,329 B per chunk, for headings that are visible anyway wherever the file is placed.
- **(R5)** #2014 grid. It loses every same-axis (agent↔agent) relation, which is the AR-6 objection.

### 2.1 Coverage by finding class, and residual loss (stated, not waved away)

| Lens class | Mechanism | Caught when | Residual loss (named) |
|---|---|---|---|
| 1 Escalation loops | Index (b) lists `[esc]` cycles of length ≤ 4. Cycles of length ≤ 3 are required co-resident (AD-5). | The cycle is in the `[esc]` graph, length ≤ 3. | Loops without a backticked name or an escalation verb. Length-4 cycles are listed but not guaranteed co-resident. |
| 2 Dead ends | Deterministic: `check_agents_static.sh` §4 (Phase 1, blocking). Semantic: as class 3. | The target exists but does not describe the handoff. | Roles named in prose without backticks. |
| 3 Cross-file mismatches | Every directed agent→agent edge is co-resident (AD-5). | Always, for pinned-rule mentions between agent files. | (i) Mentions without an exact-name span, for example `` `overseer.md` `` or "the overseer". (ii) Doc→agent edges are soft; Phase 3 validate_docs owns the pairwise check once #2014 S1b lands. (iii) Section-fallback edges: B is whole, but A is seen only through its naming sections, so a contract in A's *other* sections that bears on B is missed. Today that is 2 edges (`overseer` → `oversight-evaluator`, `overseer` → `worker`); at the worst-case bound, 3. |
| 3b Hub pairs in fallback **in both directions** | Each direction gets its own fallback chunk, so A and B are never whole together. | Each one-directional claim, against the other side's full text. | Reasoning that needs **both full contracts at once**, for example a loop exit spread across non-naming sections of both files. **Today: 0 such pairs at either budget** (no reverse hub edges, §0.3). The [COVERAGE] section names any that arise. |
| 4 File-path inconsistency | Index (c) everywhere; `check_agents_static.sh` §3/§5. | Backticked paths. | Paths in prose without backticks. |
| 5 Pipeline ordering | As class 3, along each edge. | Adjacent pairs. | Chains of three or more steps that are not a cycle. |
| 6 Invocation gaps ("no agent handles S") | `cross_chunk` + preamble + index. | Gaps local to a chunk. | **Both directions.** False positives are loud (cf. #2014 AR-11). False negatives occur when a gap is visible only corpus-wide. This is the largest loss. |
| 7 Terminology drift | Index (d); full text within a chunk. | Backticked variants anywhere. | Prose synonyms across chunks. |

**Partial backstop.** Codex (AD-11) sees the whole placed set in one call. Its lens is different, its consumption is unverified, and it is absent under `--skip-codex`. It does not close the gaps above. Recurring class-6 false positives come back to the architect. They must never be fixed by down-ranking `cross_chunk` findings (#2014 AR-11).

---

## 3. AD-3: `scripts/oversight/agent_graph_logic.py` (BINDING)

**Pinned definitions.** One rule is used for the edges, the naming sections, the index, and the tests.

- **Mention.** A *code span* is the regex `` `([^`\n]+)` `` applied per line. That means a single backtick, single-line, non-greedy span, matched anywhere in the file, **including inside fenced blocks**. A code span is a mention of agent N iff its captured content **equals** N byte-for-byte: no trimming, no case folding, no substring match. So `` `overseer` `` is a mention, while `` `overseer.md` ``, `` `the overseer` ``, and a bare overseer are not. This is the rule that reproduces 191 / 136 / 116.
- **Directed edge A→B.** A is any unit (an agent or a doc), B is an agent, A ≠ B, and A contains ≥ 1 mention of B. An edge is **required** iff A is an agent. A doc-sourced edge is **soft**.
- **Naming sections of A for B.** The h2 sections of A, split by #2014's split-md-h2 cut rule (a line starting `## ` outside a fence, using the `_split_sections` fence rule; the text before the first `## ` is section 1). A section is a naming section iff it contains ≥ 1 mention of B under the same span rule.
- **Agent identity.** A unit is an agent iff its path is under `--agents-dir` **and** its leading `---` frontmatter block has a `name:` line.
  - This differs from `check_agents_static.sh`, which takes `grep -m1 '^name:'` anywhere in the file. A file where the two rules disagree is classed as a doc, and S1 prints a WARN naming it. Today all 31 agree.
  - An agents-directory `.md` file with no leading frontmatter `name:` is a **doc unit**: it is reviewed and split, but has no agent identity, and gets a WARN.
  - Docs never yield identities (VF-1).

**Reuse, read-only by import** (#2014 AR-1 idiom): `extract_escalation_targets`, `classify_token`, `extract_path_refs`, `filter_path_ref`, and `_clean_ref` (#1846's single source of cleaning). A test imports all five so a rename breaks loudly. **`agents_static_logic.py` is not edited.**

**Inputs passed from the shell, never hard-coded in Python:** `NON_AGENT_TOKENS` (including `PROJECT_NON_AGENT_TOKENS`), `KNOWN_LABELS`, `KNOWN_SHORT_AGENTS`, **`EXTERNAL_AGENTS`** (for `classify_token`), and **the `OUTPUT_DOCS` list** (the `output_docs` argument of `filter_path_ref`). All are the same values `check_agents_static.sh` uses. Follow-up (d) gives them a single source.

**New in this module:**
- mention-edge extraction;
- cycle enumeration;
- term normalisation;
- index rendering;
- emission of edge JSONL, hyperedge JSONL, and unit JSONL for `chunk_logic` (§4.1);
- a `split-findings --focus FILE` subcommand for AD-8.

**Determinism.** The same input bytes give the same index, edges, and units, and shuffling the file order changes nothing.

**Bound.** If the index is over **24,576 B**, the module first collapses (d) to group counts. If it is still over, it exits 3 `fixed_context_too_large`. It never silently truncates. Today it is about 17.4 KB.

## 4. AD-4 / AD-5 / AD-7: `cover` mode in `chunk_logic.py` (BINDING)

### 4.1 Reused unchanged vs. new

**Reused unchanged from #2014:**
- the `markers` subcommand, nonce, and exactly-once rule (AR-4);
- the §4.2 render-and-measure budget, including `--reserve-bytes`;
- `--out-dir` emptiness;
- exit codes 0/2/3/4;
- the `hos-chunk-manifest/1` envelope;
- `record-result` (AR-8);
- `verify-run`'s per-chunk-id record check;
- `resolve_max_chunks`;
- `plan --dry-run`;
- split-md-h2's **cut function**: cut points, fence rule, byte-exact recombination assertion, `part i/j` labels, and heading outline (counted in P_max);
- the `chunked_review.sh` lane loop (salvage → single reinforce retry → consumption check), under ESC-1 = yes. **Round 3: this is reuse plus a required interface, not "unchanged".** The loop must emit the per-chunk result file defined in §4.5, which TD-2014 does not define today.

**New, and not "unchanged":**
1. **Unit JSONL gains two additive fields:** `{"path","header","kind":"agent"|"doc","split":"h2-always"|"never"}`. #2014's pack and grid modes ignore them. `agent_graph_logic` emits `kind:"agent"` with `split:"never"` for agents, and `kind:"doc"` with `split:"h2-always"` for `*.md` docs. Non-markdown extras get `split:"never"`. There is no `--split-kind` flag.
2. **Split trigger (AD-7).** #2014 §4.3 splits a unit only when it is over capacity. Under that rule `docs/AGENTS.md` (81,922 < B) would never split. Cover mode splits every `h2-always` unit **unconditionally**, using the same cut function.
   - *Why:* doc sections ride with the agents they name. In the round-1 simulation, a whole `docs/AGENTS.md` landed alone in a chunk with no agent.
   - *Cost:* a whole-doc omission claim can read falsely in one part. The outline mitigates this, and such false positives fail loud (as #2014 §6.5).
3. **Edge JSONL:** `{"src": <repo-relative path>, "dst": <repo-relative path>, "kind": "mention"|"esc", "required": bool, "lines": [1-based…], "naming_sections": [1-based section indices of src], "section_count": n}`.
   - `naming_sections` is computed by `agent_graph_logic` under the pinned rule (AD-3). `chunk_logic` never re-derives the mention rule, so agent semantics stay in one module.
   - `chunk_logic` only applies #2014's cut function to `src` and checks that it yields `section_count` sections.

   Endpoints are **unit paths**, never agent names. Agent names appear only in the rendered index. Hyperedge JSONL: `{"members": [paths], "kind": "esc-cycle"}`. Focus file: one repo-relative path per line.
4. **Mode `cover`:** `plan --mode cover --units F --edges F [--hyperedges F] [--focus F --placed F] …`. Units may appear in several chunks. Pack mode's "every unit exactly once" proof does not apply.
5. **Section-fallback units**, rendered as `EXCERPT: sections i,j of n of <A> (A is reviewed whole in chunk-NNN)`. In the manifest, each chunk's `units` list records every entry with a `role`:
   - `{"path": P, "role": "whole", "sha256": …}`
   - `{"path": P, "role": "part", "part": i, "of": n, "sha256": …}` (doc parts)
   - `{"path": A, "role": "excerpt", "for_edge": [A, B], "sections": [i, j, …], "of": n, "sha256": <sha of the concatenated section bytes>}`

   That gives `verify-run` everything it needs to check a fallback (§4.4).
6. **The cover preamble (§4.3)** and **`verify-run --cover-inputs DIR`** (§4.4).

### 4.2 Coverage invariant (AD-5), asserted in `plan` and recomputed by `verify-run`

The planner input is **directed edges**: 136 required agent→agent edges today.

- **Placed set P.** In full mode, P is every unit. In focus mode (AD-8), P is the focus units, plus both ends of every required edge incident to a focus unit, plus every member of a required cycle that contains a focus unit. Units outside P are **context-only**: they feed the index and the preamble but are never placed. P is computed by `agent_graph_logic.py placed-set` (S1). `plan` takes it as `--placed F` and verifies it; it does not recompute it (AD-11).
1. Every agent in P appears **whole** in ≥ 1 chunk. Every doc in P appears as its complete set of parts, each part in ≥ 1 chunk.
2. For every required directed edge A→B with A or B in the focus set (every edge in full mode), some chunk contains **B whole** and either **A whole** (the preferred form, used whenever `pair_bytes(A, B) ≤ B_budget`) or **every naming section of A for B** (section fallback). The fallback always keeps the *referenced* agent B whole, because B's full contract is what the claim in A is checked against. If only A→B exists, only A→B gets a placement. If both A→B and B→A exist and neither whole pair fits, each direction gets its own fallback placement. That is the both-directions row in §2.1.
3. Every required hyperedge (an `[esc]` cycle of length ≤ 3 that intersects the focus set, or every such cycle in full mode) has all members whole in one chunk. If they do not fit, it degrades to its member edges under rule 2, and the degradation is recorded.
4. If `excerpt_pair_bytes(A, B)` is over B_budget → exit 3 `edge_too_large`, naming both paths and the byte counts.

**One shared size function (round 4, C4).** `chunk_logic` defines exactly one pair of functions, used by `plan`'s fits test, by `plan`'s post-render assertion, and by `verify-run`'s fallback check. No other code computes these sizes.
- `pair_bytes(A, B)` is the bytes A and B contribute to a rendered chunk body: each unit's header line, its content, and the separator that follows it, exactly as #2014's renderer emits them.
- `excerpt_pair_bytes(A, B)` is the same for B whole plus A's excerpt: the `EXCERPT:` label line, the naming sections, and the separators.

A test asserts that each function equals the byte length of the corresponding rendered fragment. `overseer` + `worker` (139,822 B, against today's ≈ 139,650 B budget) is the live boundary case. It is pinned by a test at budgets one byte below, equal to, and one byte above `pair_bytes`. **Agents are never reviewed only as fragments.** An excerpt is always *in addition to* a whole appearance, so #2014 D5 holds.

**Manifest `coverage` (cover mode):**
```
{budget_bytes: B_budget, max_bytes, reserve_bytes, fixed_bytes: T, p_max_bytes,
 placed: [...], context_only: [...],
 edges_required, edges_whole, edges_section_fallback: [{src, dst, chunk}],
 hyperedges_required, hyperedges_whole, hyperedges_degraded: [...],
 soft_edges, soft_edges_coresident, input_sha256s: {units, edges, hyperedges, focus}}
```

**Packing.** Deterministic greedy weighted edge cover:
- Seed each new chunk with the unit that has the most uncovered requirements (ties: bytes desc, path asc).
- Add units by uncovered requirements per byte, then soft edges per byte, then placing a not-yet-placed unit.
- Emit units within a chunk in path order.

The TD may improve the heuristic. It may not weaken the invariant, and it must remain independent of input order (shuffled-input test).

### 4.3 Cover-mode preamble (replaces #2014 §4.4's third line in cover mode only)

```
CHUNKED REVIEW: this is chunk k of n of ONE review. You see only this chunk.
This chunk contains: <paths, part i/j, EXCERPT labels>, each tagged [FOCUS] or [CONTEXT] in focus mode
Reviewed whole in OTHER chunks of this run (not visible to you): <P minus this chunk>
In the corpus but NOT reviewed in this run (index only): <context-only units; line omitted when empty>
<the #2014 cross_chunk instruction, unchanged>
```

The two inventory lines together list the corpus minus this chunk, so #2014 AR-7's `P_max` bound and collapse rule carry over unchanged: an 8,192 B bound, then collapse, then exit 3. In full mode the third line is always omitted. The statement "reviewed in other chunks" is therefore never false.

### 4.4 `verify-run` for cover mode

- **`--cover-inputs DIR` is the plan's `--out-dir`**: the same directory that holds `chunk-manifest.json`. `plan` copies its exact inputs into `DIR/inputs/` (units, edges, hyperedges, focus, placed) and records their sha256 values in `coverage.input_sha256s`. The copies follow #2014 §4's atomicity rule: everything is computed before anything is written, so **a failed plan (any non-zero exit) leaves no `inputs/` copies**, as well as no manifest and no prompt files. `verify-run` refuses (exit 2) a `DIR` that is not the manifest's own directory.
- `verify-run --manifest M --results R --lane L --cover-inputs DIR`:
  - re-hashes the input copies against the manifest;
  - re-reads every placed unit from disk and compares each unit's sha256 to the manifest, which detects a tree that changed mid-run;
  - recomputes invariant rules 1 to 4 from the copied inputs, using the manifest's `budget_bytes`. **"Whole whenever it fits" is checked, not just preferred:** for every edge in `edges_section_fallback`, `verify-run` asserts `pair_bytes(A, B) > budget_bytes`, using the same shared function `plan` used (C4) over the units re-read from disk. A fallback used where the whole pair fits is a coverage failure;
  - checks every `excerpt` entry: `sections` must equal that edge's `naming_sections` from the copied edges file; `of` must equal its `section_count`; and re-cutting A from disk with #2014's cut function and concatenating those sections must reproduce the entry's `sha256`. An excerpt that is missing a naming section therefore fails;
  - runs the unchanged per-chunk-id record check.
- `--cover-inputs` is required in cover mode, and is mutually exclusive with #2014's `--input` (pack/grid).
- Any mismatch → exit 1 with a JSON line, as in #2014 §4.6.
- **Trust level (stated plainly).** The input copies, the manifest, and the results file all live in one writable directory. The re-hash catches **accidents**: a tree edited mid-run, a truncated copy, a planner bug. It does **not** catch deliberate tampering by anyone who can write that directory, because they can rewrite the manifest too. This is the same trust level as #2014's manifest and results. It is not a security boundary.

### 4.5 Per-chunk result interface required of `chunked_review.sh` (round 3, N2)

S3 needs three things per chunk: the `VENDOR_INVOKE_*` values (for `_agents_vi_failure_json`), the salvaged object (for `split-findings` and re-serialisation), and a failure cause finer than #2014's `record-result` outcome set. TD-2014 defines none of these. **Binding:**

- **Where it lives.** It is a requirement on #2014 S1a's `chunked_review.sh`. If S1a has merged without it, **S2 adds it to `chunked_review.sh` additively**: a new output file and no change to existing behaviour, with every #2014 test passing unmodified. Neither S3 nor any other caller may build a second lane loop to obtain it (#2014 D3, AR-14).
- **The file.** For each chunk and lane, the loop writes `<out-dir>/chunk-NNN.<lane>.result.json`. Python encodes it; it is never built in shell:
  ```
  {chunk_id, lane, vendor,
   outcome:  ok|unparseable|refused|failed|unconsumed|consumption_check_failed,   # #2014 set, unchanged
   detail:   <finer cause, below>,
   vi: {class, detail, rc, bytes, max_bytes, stderr_tail},   # VENDOR_INVOKE_* of the LAST attempt
   consumption: <assess_consumption dict> | null,
   salvaged: <reviewer object> | null,
   stdout_prefix: <first 200 chars of the envelope "result" field; of raw stdout only when no envelope parsed>}
  ```
- **`detail` values.** `record-result --detail` already carries a free-form detail, so the outcome set is unchanged:

  | `outcome` | `detail` |
  |---|---|
  | `failed` | `timeout`, `vendor_nonzero_exit`, any other `vendor_invoke` detail, or `empty_output` |
  | `refused` | `prompt_too_large` |
  | `unparseable` | `unparseable_output` |
  | `unconsumed` | `prompt_not_consumed` |
  | `consumption_check_failed` | `consumption_check_failed` |

- **Empty-output rule: a per-caller option, default OFF (round 4, N4).** The shared lane loop gains an opt-in flag (named by the TD, for example `--empty-output-fails`).
  - **Default OFF.** #2014's behaviour is unchanged for every other caller. A text-but-no-JSON reply, including an envelope whose `result` is empty, takes the single reinforce retry (TD-2014 §6.3, `run_second_review.sh:734`) and ends as `unparseable`, which second review tolerates under `--allow-unparseable`. So when #2014 S2 moves second review onto the lib, the mandatory pre-PR gate's outcome does not change. This makes the result file purely additive.
  - **ON (validate_agents opts in; preserves #2015 T12).** The result is `failed`/`empty_output`, with **no reinforce retry**, if raw stdout is whitespace-only, **or** an envelope parses but its `result` is missing, non-string, or whitespace-only. Salvage is not attempted.
  - For validate_agents both settings fail closed, because it does not pass `--allow-unparseable`. The option only fixes which detail is reported.
  - A #2014 lib test pins that the default leaves an empty-`result` envelope on the retry → `unparseable` path.
- S3 maps each result file: on `ok`, run `split-findings` (AD-8) on `salvaged`, then re-serialise. Otherwise, write `_agents_vi_failure_json` built from `vi.*`, `detail`, and `stdout_prefix`.

**Rejected alternatives.**
- **(R6)** A parallel chunker. Rejected: #2014 D1/D3.
- **(R7)** Fail on any infeasible whole pair. That would disable the gate whenever a hub agent grows.
- **(R8)** ±N-line excerpts. Those are arbitrary cuts; h2 sections are the authored unit.
- **(R9)** Undirected pair cover. It cannot say *which* side must be whole, and the fallback is inherently directional.

## 5. AD-6: byte budget (BINDING formula; recomputed at true bounds)

`B_budget = 180,000 − R − T − P_max` (#2014 §4.2), computed per run by `plan` from the rendered template.

| Term | Today (measured) | Worst-case bound | Source of the bound |
|---|---|---|---|
| R: reinforce suffix | ≈ 0.3 KB | **401** | A safe upper bound. The three source lines that build the suffix (`run_second_review.sh:736-738`) are **258 B**, so the real suffix is smaller still. The real value comes from `chunked_review_reserve_bytes`. (Round 2 wrongly said those lines were 401 B.) |
| T: lens | ≈ 3.3 KB | **4,096** | S3 test pins the lens template ≤ 4,096 B |
| T: known issues | 13,324 | **16,384** | **New deterministic cap** (below) |
| T: index | ≈ 17.4 KB | **24,576** | AD-3 bound |
| P_max: inventory lines | ≈ 2.4 KB (54 units, 1,795 B of paths) | **8,192** | #2014 AR-7 |
| P_max: heading outlines of split docs | 3,385 | **3,585** (outlines + labels) | **measured, not capped.** It grows with the docs' headings, and `plan` counts it exactly. |
| **B_budget** | **≈ 139.65 KB** (technical-design reviewer's figure) | **122,766** | |

**Known-issues cap (new, S3).** Today's block is up to 100 titles of ≤ 256 chars each, about 27 KB unbounded. A small Python helper renders it:
- the **16,384 B cap covers the whole rendered block**: the ≈ 240 B heading (`=== KNOWN, ALREADY-TRACKED ISSUES … ===` plus its instructions), every title line, and the trailer;
- keep whole title lines in `gh`'s order until the next line would push the block past 16,384 B once the trailer is counted;
- then append `(+N more open issues not listed)`.

The cap is deterministic for a given input and never cuts a line. It applies to both lanes. Its consequence is only noise: an omitted known issue may be re-reported (loud, ledger-dedupable). It is never fail-open.

**Consequences:**
- At the worst-case bound, the three hub edges all need fallback. Each fits, with a maximum of 92,669 B against 122,766 B.
- **No combination of issue-title length, index size, or lens size up to their bounds can cause `edge_too_large` on today's tree.** Round 1's outage scenario is closed.
- Planning uses the actual B_budget, as #2014 does. Plans can therefore vary with the live known-issues block. Each run records its plan (`input_sha256`). On today's tree the chunk count is approximately 11 to 15 (§0.3), well under the cap of 24. S3's live run is the measurement.

**Single file over budget:**
- An agent over B_budget → `unit_too_large`, exit 3. The fix is a human authoring decision.
- A doc part over B_budget → exit 3.
- A fallback over B_budget → `edge_too_large`, exit 3.
- Nothing is ever truncated or sampled. The known-issues cap is advisory context, not reviewed content.

## 6. AD-8: release scope and context units (PROVISIONAL, ESC-2)

**Corpus.** `--changed-only` selects `changed ∩ corpus` and never widens. The **focus set** is that intersection. The placed set and the rules follow §4.2. Measured for v0.6.0: 58 required edges, approximately 8 to 9 chunks (10 at the worst-case bound). If the intersection is empty, today's WARN-then-full-mode fallback (`validate_agents.sh:204-207`) stays.

**Context units.** These are unchanged neighbours placed whole so that edges can be checked.
- **Lens labelling.** Focus mode tags every unit `[FOCUS]` or `[CONTEXT]` in the preamble (§4.3). The lens says: *"Report a finding only if it involves at least one [FOCUS] unit. A defect that lies entirely within [CONTEXT] units is pre-existing and out of scope for this run."*
- **Deterministic routing.** `agent_graph_logic.py split-findings --focus F` partitions each salvaged reviewer object:
  - A finding whose `files` share no path with the focus set goes to a verdict-inert `## [CONTEXT] Pre-existing findings on unchanged files (#130)` section and does not block.
    - **#2014 AR-5 applies to this section.** It contains **no JSON objects** and none of the keys `verdict`, `findings`, `attacks`, or `error`.
    - Each routed finding is rendered as one plain-text line inside a plain fence: `- [<severity>] <category|type> | <files, comma-joined> | <description> | <fix>`.
    - Every field has backticks replaced by `'` and newlines collapsed to spaces, so nothing in it can open a fence or be parsed as a block.
  - Everything else stays in the reviewer's json block and goes through `process` as normal.
  - **Fail-closed rules:** if `files` is missing, empty, or not a list, the finding stays blocking. Only a finding whose **every** listed file resolves to a CONTEXT unit is routed out.
  - **Path resolution (round 4, C3).** Each listed string is matched against the unit inventory with **exact byte equality**: no trimming, no case folding, no normalisation of `./` or `\`. It resolves to a unit if it equals:
    - **(a)** a unit's repo-relative path, or
    - **(b)** a unit's basename (`os.path.basename` of the path), and that basename belongs to **exactly one** unit in the corpus.

    A listed string stays blocking, so the whole finding stays blocking, if:
    - it matches nothing;
    - it is a basename shared by more than one corpus unit;
    - it resolves to a **FOCUS** unit, whether by path or basename;
    - it resolves to a unit that is in the corpus but **context-only / index-only**, meaning outside P. Only units in P and tagged [CONTEXT] can be routed. The reviewer never saw an index-only unit's text, so a finding about it cannot be pre-existing-in-view.

    Doc parts resolve through their parent doc's path. A string such as `docs/AGENTS.md#3` matches nothing, so it blocks.
  - **Block verdict after routing (round 3, N1). This is pinned so the result does not depend on whether #2032 is fixed.** Let V be the reviewer's block-level `verdict`, compared after `str(...).strip().lower()`. Let BF be the set of its findings (both `findings` and `attacks`) whose severity, under the **same** `strip().lower()` normalisation, is in `validation_logic.BLOCKING_SEVERITIES` (`("critical","high","blocking")`, `validation_logic.py:62`). That one set applies to **every** lane, agy and codex alike, imported rather than restated (round 4, C2).
    - `error` → unchanged.
    - `approve` → unchanged.
    - `request_changes` → becomes `approve` **only if** BF was non-empty **and** every member of BF was routed to [CONTEXT]. In every other case it stays `request_changes`. That includes the #2032 shape (no findings, or only non-blocking findings): routing never turns a request with no stated blocking basis into an approval.
    - When it downgrades, the re-serialised block records `routed_from_verdict: "request_changes"` and `context_routed: <count>`. The routed findings stay visible in [CONTEXT].
    - *Why this is not a #683 laundering path:* #683 forbids downgrading a blocking verdict on the strength of a dedup or count. Here the downgrade happens only when the **entire stated blocking basis** has been moved to a section a human sees, and the move follows the deterministic rules above. It is never ledger-driven.
    - **It is model-influenced** (round 4, C5). The rules are deterministic, but their input, each finding's `files`, is written by the reviewer. A FOCUS defect that the reviewer attributes only to CONTEXT files is routed out, and can therefore downgrade the block. That is the **ESC-2 attribution residual** (the "Residual (named)" bullet below). The mitigations are the C3 rules (any FOCUS, ambiguous, unknown, or index-only path keeps the finding blocking) and the [CONTEXT] section, which keeps the routed finding in front of the human. ESC-2 asks the human to accept this residual.
    - *Coupling:* today `compute_verdict` ignores the block verdict (#2032), so an un-rewritten block would *happen* to be non-blocking. Once #2032 is fixed, it would block, and #130 scoping would be undone. This rule makes the outcome identical under both. Without it the design would fail **loud**, not open, but it would still have been wrong to claim independence from #2032 (AD-10).
- **Residual (named).** A reviewer that lists only context files for a defect that is really in a focus file has that finding routed to [CONTEXT], visible but non-blocking. This is model-controlled attribution. The [CONTEXT] section keeps it in front of the human.
- **Full mode** (major releases, ad hoc runs) has no context units, and every finding can block.

*Why.* #130 (`cut_release.sh:146-151`) scoped release convergence to "zero-new since the release diff" because the full corpus keeps surfacing real pre-existing holes. If neighbours were placed whole and blocking, that scoping would be undone through the back door.

*If ESC-2 is answered no:* the 84 extra files become extra doc units with no required edges, about 40+ chunks, over the cap. Codex is refused at 5.4 MB. Phase 2 cannot pass at a minor or patch release.

## 7. AD-9 / AD-10 / AD-11: cost, aggregation, codex

**AD-9: cost and caps (BINDING; the cost model is ESC-4).** Calls are sequential. The reviewed constant for validate_agents is **24**, lowerable via `FRAMEWORK_VALIDATION_MAX_CHUNKS` (clamped per caller by `resolve_max_chunks`).

| Mode | agy calls today (worst-case bound) | agy input | Worst case at cap |
|---|---|---|---|
| Full (major release, ad hoc, `framework-validator`) | ≈ 11 to 12 (13 to 15) | ≈ 2.0 MB (≈ 2.45 MB) | 24 × 300 s = 2 h; 4 h with prose retries |
| Release focus (minor/patch) | ≈ 8 to 9 (10) | ≈ 1.5 MB | same |

These counts are approximate (§0.3). S3's live `plan --dry-run` is the measurement of record.

For comparison, today's full mode is 1 call, and it is refused under #2015. A minor release cut with #2014 S1b in place is about 9 + 18 + 9 ≈ **36 agy calls** across Phases 2 to 4. `run_framework_validation.sh` prints the `plan --dry-run` before Phase 2.

**AD-10: output, aggregation, fail-closed coverage (BINDING).**
- **Which path writes each per-chunk block.** For agy, it is the `chunked_review.sh` lane loop (#2014), not #2015's `_vi_lane`/`_vi_neutralize_output`.
  - **Success:** the salvaged object, after AD-8 routing, is re-serialised by Python (`json.dumps`). Then every backtick character is replaced by its six-character JSON escape (backslash, `u`, `0060`), which is #2015's AR-3 policy. Raw vendor stdout is never written inside a json fence (#2014 AR-9). `_vi_neutralize_output` stays only on the codex lane, which is #2015's approved path and is unchanged.
  - **Failure:** S3 writes the chunk's record with **`_agents_vi_failure_json`, keeping its exact keys and its `error`/`summary` strings**.
    - The record is built from the chunk's §4.5 result file: `vi.*` supplies the `VENDOR_INVOKE_*` values, `detail` becomes `outcome_detail`, and `stdout_prefix` is used for `unparseable_output`. The outcome-to-detail mapping is the §4.5 table.
    - It adds `chunk_id`, `chunk_k`, and `chunk_n`.
    - **Plan failures** (before any launch) use the same helper, with `failure_class: "harness"` and `outcome_detail` set to `unit_too_large`, `fixed_context_too_large`, `edge_too_large`, `chunk_cap_exceeded`, or `chunk_plan_failed`. Detail-specific numeric keys replace `prompt_bytes`/`max_bytes`:

      | Detail | Keys |
      |---|---|
      | `unit_too_large` | `unit_path`, `unit_bytes`, `budget_bytes`, `max_bytes` (= the vendor ceiling) |
      | `fixed_context_too_large` | `fixed_bytes`, `max_bytes` |
      | `edge_too_large` | `src`, `dst`, `edge_bytes`, `budget_bytes` |
      | `chunk_cap_exceeded` | `chunks_required`, `max_chunks` |

    - Their stderr lines, exactly:
      - `WARN: agy not launched: <path> is <U> bytes, over the <B>-byte per-chunk budget under the <C>-byte ceiling (unit_too_large, #2033) — recorded as error, continuing`
      - `WARN: agy not launched: fixed context is <F> bytes, over the <C>-byte ceiling (fixed_context_too_large, #2033) — recorded as error, continuing`
      - The other details follow the same `agy not launched: … (<detail>, #2033)` pattern.

  - The record goes under that chunk's section heading, `## agy — Consistency + Completeness [chunk k/n]`. When n = 1 the heading has no suffix. A heading never contains "skipped".
- **Coverage gate.** After the lane, the shell keeps `verify-run`'s exit status. If it is non-zero, the shell:
  - appends one lane-level block **after** all chunk sections (`reviewer: "agy"`, `outcome_detail: "chunk_coverage_failed"`, `verdict: "error"`, the verify-run JSON as `chunk_coverage`);
  - prints FAIL;
  - writes **no stamp**;
  - exits **1** regardless of the finalizer;
  - **does not count the run as a review pass** (the pass counter is restored), so it never exits 3.

  Plan failures (exit 2/3/4) take the same path with their detail, and no vendor is launched. When n > 1, a verdict-inert `## [COVERAGE] Chunked review (#2014/#2033)` section in a plain fence lists the placed and context-only units, every fallback edge, and every degraded cycle.
- **Timeout guard.** #2015's `_vi_unenforceable_reason agy` runs **once, before `plan`**. If it is non-empty, the shell writes one `timeout_unenforceable` record and launches nothing.
- **Verdict.** One `validation_logic.py process --strict-empty` run over all blocks. **No verdict may be written to the header before `process`.** The header starts at `pending`, which keeps **#2036 inert** for this caller.
- **#2032 is live here, and the design is coupled to it (round 3 correction).** `compute_verdict` ignores a block-level `request_changes` that has null or empty findings, and chunking multiplies the number of blocks. Round 2 said this design "neither fixes #2032 nor depends on its fix". That was **false** for focus mode: the non-blocking [CONTEXT] rule silently relied on #2032's bug. The AD-8 verdict-after-routing rule removes that dependence, so the gate outcome is the same before and after #2032 is fixed.
  - **Note for #2032** (recorded by the worker):
    - (a) Its fix covers validate_agents, so its tests should include a multi-block chunked fixture.
    - (b) A fixed `compute_verdict` must honour a routed block's rewritten `verdict`. It must not reconstruct `request_changes` from `routed_from_verdict`, which is an audit field, not a verdict.
    - (c) A routed block with `routed_from_verdict` set must never have zero routed findings, because AD-8 forbids the downgrade in that case. A #2032 test can assert this.
- **Dedup and convergence.** The fingerprint and ledger are unchanged. Hub files appear in about 2.5 chunks on average, so duplicate findings inflate `blocking_count` until dispositioned. That triage cost is accepted. The pass cap counts runs, not chunks.

**AD-11: codex lane (BINDING).** The codex lane is **not chunked** and gets no index. It stays #2015's single `_vi_lane codex attacks` call under the 1,048,576 B ceiling, with #2015's output path. **Input contract:**
- **Full mode:** every corpus unit whole, in path order, under today's `=== FILES TO ATTACK ===` marker, plus the capped known-issues block. That is about 0.63 MB, 60% of the ceiling.
- **Focus mode:** exactly the **placed set P**, whole and in path order. Docs in P are sent whole, not as parts. A `FOCUS: <paths>` / `CONTEXT: <paths>` header goes before the marker, together with the same "findings must involve a FOCUS unit" instruction.
  - **Round 3: P does not come from `plan`.** It is computed by `agent_graph_logic.py placed-set --focus F` (S1). That is a pure graph computation over focus, edges, and cycles, with no packing, so it **cannot fail for size reasons**. `chunk_logic` **takes P as an input** (`plan --placed F`, round 4 note (a)) and does not recompute it, so there is one implementation (#2014 D3). It **verifies** P element by element:
- closure: every focus unit, both ends of every required edge incident to a focus unit, and every member of a required cycle containing one, are all in P;
- justification: every unit in P is one of those.

A failed check is `chunk_plan_failed` on the agy lane.
  - **When `plan` fails** (exit 2/3/4, with or without agy enabled), codex is unaffected: it still runs on P. Under `--skip-agy`, `plan` is not run at all.
  - If `placed-set` itself fails (exit 2: bad input, I/O), **both** lanes record `chunk_plan_failed` and nothing is launched.
  - **Codex output in focus mode.** #2015's `_vi_lane` path runs unchanged up to `_vi_neutralize_output`. If the neutralised stdout yields **exactly one** reviewer-shaped object, using the same `validation_logic` parser #2015 already uses to accept it, S3 applies `split-findings` and the verdict-after-routing rule (AD-8), then re-serialises the object (AD-10's success path).
  - If it yields more than one such object, S3 does **not** route. It writes #2015's neutralised output as today, so every attack can block. That is fail-closed, and the stderr names it.
  - Full mode keeps #2015's output path unchanged.
- P ⊆ corpus, so focus input ≤ full input.
- Above the ceiling, the lane fails loudly with `prompt_too_large` (#2015). It is not silently decomposed. Extending `cover` mode to codex would need a new decision.
- *Why not chunked:* its adversarial lens is the most cross-file of all (#2014 AR-12), and it fits whole.

## 8. Slices (each ≤ 15 files, ≤ 10 commits)

**S1: `agent_graph_logic.py`.**
- Risk HIGH (it defines a release gate's coverage guarantee). Not protected. Not gated on #2014, #2015, or any ESC, because there is no caller yet.
- Reviewers: code, reliability.
- Files (6): `scripts/oversight/agent_graph_logic.py` (new) · `tests/oversight/test_agent_graph_logic.py` (new) · `DECISIONS.md` · `SCRIPTS-INDEX.md` · prompt artifact · this ADR (status line).
- Tests:
  - the five-name import pin;
  - the pinned span rule: `` `overseer` `` counts; `` `overseer.md` ``, `` ` overseer` ``, `` `the overseer` ``, and bare words do not; spans inside fences count;
  - VF-1, and the frontmatter-less agents-dir file → doc + WARN;
  - the identity-rule disagreement with `grep -m1` → doc + WARN;
  - determinism and shuffle independence;
  - the index bound and collapse, and over the bound → exit 3;
  - cycles on a synthetic graph;
  - `split-findings`: every fail-closed case (no/empty/non-list `files`, unknown path) stays blocking;
  - verdict after routing (AD-8, round 3):
    - `request_changes` with all blocking findings routed → `approve`, with `routed_from_verdict` and `context_routed`;
    - one blocking focus finding left → stays `request_changes`;
    - `request_changes` with no findings, or only non-blocking findings (the #2032 shape) → stays `request_changes`;
    - `error` is never touched;
  - [CONTEXT] rendering: no JSON object and no `verdict`/`findings`/`attacks`/`error` key in the section, and a backtick-laden description cannot open a fence (AR-5);
  - `placed-set`: focus plus edge ends plus cycle members, size-independent, with exit 2 only on bad input;
  - edge JSONL `naming_sections`/`section_count`, checked against the pinned rule on fixtures;
  - on the live tree: **136 directed agent→agent edges, 116 unordered pairs, 191 directed edges in total**, and index ≤ 24,576 B. The live counts are asserted as ≥ to tolerate growth, with the exact values recorded in the PR.

**S2: `cover` mode in `chunk_logic.py`.**
- Risk HIGH. Not protected. **Gated on #2014 S1a merged.**
- Condition: all #2014 S1a tests pass **unmodified**.
- Reviewers: code, security, reliability.
- Files (≤ 8): `scripts/oversight/chunk_logic.py` · `tests/oversight/test_chunk_logic_cover.py` (new) · `DECISIONS.md` · `SCRIPTS-INDEX.md` · prompt artifact.
  - **Only if #2014 S1a merged without §4.5:** also `scripts/oversight/lib/chunked_review.sh` (additive result file) and `tests/oversight/test_chunked_review_result_file.py` (new).
- Tests:
  - invariant rules 1 to 4, including the both-directions case and the "B stays whole" fallback direction;
  - the manifest records `budget_bytes`. `verify-run` fails a manifest that uses a fallback where the whole pair fits;
  - `verify-run` fails an excerpt entry that is missing a naming section, or whose sha does not re-derive from disk;
  - `verify-run` refuses a `--cover-inputs` directory that is not the manifest's own;
  - §4.5 result file: every outcome/detail row; whitespace-only stdout and an empty-`result` envelope give `empty_output` with no retry; `stdout_prefix` comes from `result`; `vi.*` is from the last attempt;
  - unconditional doc split, recombining byte-exact;
  - focus placed set and context-only units, with preamble lines that are never false;
  - `verify-run --cover-inputs`, failing on a tampered input, a tampered manifest that drops an edge, or a unit changed on disk;
  - `edge_too_large` → exit 3;
  - shuffle independence;
  - every prompt ≤ max − reserve;
  - n > M → exit 4;
  - a hub-heavy 400 KB synthetic corpus at `--max-bytes 180000`.

**S3: validate_agents.sh wiring.**
- Risk HIGH. **Protected** (human approval at merge).
- **Gated on:** S1 merged · S2 merged · #2014 S1a merged · #2015 per AD-13 · **ESC-1 answered yes** (a "no" returns this design to the architect, because `chunked_review.sh` has no non-envelope agy path; #2014 §6.4) · ESC-2, -3, -4, -5, -7 answered on record.
- Reviewers: code, security (index, known-issues, and attacker-influenceable prompt text; re-serialisation; `split-findings` attribution), reliability (coverage gate, timeout guard, wall time). Cross-vendor second review applies.
- Files (≤ 10): `scripts/framework/validate_agents.sh` · `scripts/framework/run_framework_validation.sh` (dry-plan print; #2014 S1b edits the same file, and whichever lands second rebases) · known-issues cap helper (location chosen by the TD, under `scripts/oversight/`) · `tests/framework/test_validate_agents_chunked.py` (new) · `tests/framework/test_framework_validators_vendor_invoke.py` (amend per §10) · `docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md` (dated §7 annotation) · `DECISIONS.md` · `prompts/scripts/framework/validate_agents.md` **(new)** · prompt artifact.
- Hermetic tests:
  - a ~400 KB fixture with two ~70 KB hub agents → ≥ 3 agy calls, each stdin ≤ 180,000 B; every fixture agent is whole in some stdin; every fixture edge is satisfied per §4.2;
  - all approve → exit 0 and stamp;
  - one chunk fails → its `_agents_vi_failure_json`-shaped record, then `chunk_coverage_failed`, exit 1, no stamp, pass counter not advanced;
  - an unterminated JSON chunk followed by a `request_changes` chunk → exit 1;
  - a prose chunk → exit 1;
  - no `timeout` binary → no plan and no launch;
  - codex called once, with no index in its stdin, full corpus in full mode, exactly P in focus mode;
  - focus mode where `plan` fails with `unit_too_large`: codex still runs on P;
  - `--skip-agy` focus mode: codex runs on P and `plan` is never invoked;
  - a codex reply in focus mode with two reviewer objects → no routing, all attacks blocking;
  - plan-failure records carry the AD-10 numeric keys and stderr wording;
  - focus mode: unrelated unchanged files are not placed; neighbours are placed with a [CONTEXT] tag; a context-only finding is non-blocking and visible; an empty-`files` finding blocks;
  - `docs/v9/X.md` changes are excluded;
  - the header is `pending` before `process`;
  - the known-issues cap holds at 300 titles of 256 chars;
  - the lens template is ≤ 4,096 B.
- **Acceptance (live, recorded on the PR):**
  - `plan --dry-run` on the current repo shows n ≤ 24 and every `prompt_bytes ≤ 180,000 − R`;
  - one full-mode run whose agy lane completes with every chunk `ok` and `verify-run` exit 0;
  - every blocking `cross_chunk: true` finding is listed with a human's true/false judgement (#2014 AR-11).

**AD-13: composition with #2015 (BINDING except the item marked ESC-7).**
- S3 re-implements nothing from #2015: the `vendor_invoke` sourcing, `_vi_unenforceable_reason`, `_agents_vi_failure_json`, and the codex `_vi_lane` with its output path all stay #2015's.
- **If #2015 is merged first:** S3 branches from main. Until then, the full-mode agy lane fails closed (`prompt_too_large`), which #2015 ESC-1 has already accepted.
- **If #2015 is not yet merged when S3 is coded:** S3 is **stacked on #2015's branch**. The merge order is strictly #2015 then S3, as separate PRs with separate review records. What a #2015 "hold" ruling requires before #2015 may merge is the human's call (ESC-7). The architect does not interpret it.
- **If #2015 is rejected or materially reworked:** S3 stops and returns to the architect. It never absorbs #2015's lane migration.

## 9. Escalations (human): each a yes/no question

These are product-boundary checkpoints. pm-agent assesses product impact. The human decides.

- **ESC-1 (consumption flags; answer jointly with #2014 ESC-1).** May validate_agents' agy chunks run `--sandbox --output-format json` through `chunked_review.sh`, so every chunk gets a real #1718 consumption check? *Recommended: yes, with one ruling for all three validators.* **S3 is conditional on yes.** "No" returns the design to the architect, because #2014's lane loop defines agy only in that form.
- **ESC-2 (AD-8 release scope and context units).** Should `--changed-only` narrow to the agent corpus (today it covers all of `docs/**`: 91 files, 5.4 MB, 84 of them design history) and switch to focus mode? In focus mode, changed units' neighbours are placed whole for cross-reference. Findings that lie entirely in those unchanged neighbours are shown in a non-blocking [CONTEXT] section and do **not** block the release (consistent with #130). A defect the reviewer attributes only to context files is also non-blocking. *Recommended: yes.* If "no" on narrowing: Phase 2 cannot pass at a minor or patch release. If "no" on non-blocking context findings: neighbours' pre-existing findings block release cuts, which undoes #130's scoping.
- **ESC-3 (coverage model).** Is the §2.1 model an acceptable basis for release Phase 2? It consists of: every exact-name agent↔agent mention co-resident, with section fallback (2 edges today, 3 at the worst-case bound); doc↔agent edges best-effort; and the named residuals, including possible "handled nowhere" false positives. *Recommended: yes.*
- **ESC-4 (cost model).** Accept about 12 agy calls (≈ 2.0 MB) per full run where today there is 1, up to 15 at the worst-case bound; about 9 per minor/patch release cut; a cap of 24; and a worst case of 2 h (4 h with retries), sequential? With #2014 S1b, that is about 36 agy calls per release cut. *Recommended: yes.*
- **ESC-5 (operational obligation).** `framework-validator` (`.claude/agents/framework-validator.md:42`, reached via `post-change-sweep`) runs full-mode `validate_agents.sh` inside a Bash call capped at 600 s. Twelve sequential calls will usually exceed that, and the kill leaves no verdict. Accept this, with a follow-up issue (protected `.claude/agents/**`) to move that invocation to focus mode run in the background, or to a human-run step, filed before S3 merges? *Recommended: yes.*
- **ESC-6 (scope; supersedes round-1 AD-12).** #2014 ESC-7 and ESC-8, still awaiting the human, propose deferring `run_red_team.sh` and `review_self.sh` "to the #2033 cross-file design". Should #2033 **exclude** them? Cover mode takes its edges as an input file, so each could adopt it later with its own edge extractor (agents↔scripts↔contract path references; component call edges), under a separate issue and decision. *Recommended: yes, exclude.* Their lenses need different edge extractors, and bundling them would put two more callers behind a protected HIGH slice. If the human rules "include", the architect adds slices S4/S5 here.
- **ESC-7 (#2015 "hold" semantics; supersedes round-1 AD-13 interpretation).** If #2015 ESC-1 is ruled "hold until chunking lands", is the hold satisfied when S3 is **approved and mergeable** (then merge #2015 and immediately S3), or only when S3 has **merged**? S3 is stacked on #2015, so "merged" would require S3 to absorb #2015, which AD-13 forbids. *Recommended: approved-and-mergeable.*

## 10. Affected sign-offs and startup-gap check

- **Startup gap: no.** Chunking was deliberately deferred at #1718 (F1) and at #2015 (AR-6). No prior ADR is revised.
- **#2015's sign-offs** stand as approvals of #2015's diff. S3's HIGH-tier reviewers re-review the rewritten agy lane.
- **#2015's tests**, in `tests/framework/test_framework_validators_vendor_invoke.py`, for the `script="agents"` parameter. Every assertion is listed below as superseded or preserved.

  **Superseded** (S3 amends these, citing this ADR):
  - **T1: only the argv assertion changes.** The agents argv `["--sandbox"]` becomes `["--sandbox","--output-format","json"]` (ESC-1).
    - *Round 2 was wrong here.* The 150,000 B fixture is **not** `unit_too_large`. The harness sets `HOS_FEED_KNOWN_ISSUES=0` and uses one agent and no docs, so B_budget is about 175 KB and the fixture fits in one chunk.
    - The fixture size and both stdin assertions (marker, and the 150,000-byte run arriving intact) are **unchanged**. That preserves T1's purpose: a prompt over `MAX_ARG_STRLEN` (131,072) arrives on stdin intact.
  - **T3, default mode** (200,000 B single agent, over B_budget): `unit_too_large`, a plan failure with no launch. Assertions kept: `not invoked`, `verdict == "error"`, `header_verdict == "request_changes"`, `returncode == 1`, and `b["max_bytes"] == 180000` (AD-10: `max_bytes` is the vendor ceiling). Assertions replaced:

    | Old assertion | New assertion |
    |---|---|
    | `outcome_detail == "prompt_too_large"` | `== "unit_too_large"` |
    | `prompt_bytes > max_bytes` | `b["unit_bytes"] > b["budget_bytes"]` |
    | stderr `prompt is \d+ bytes` | `is \d+ bytes, over the \d+-byte per-chunk budget` |
    | stderr `over the 180000-byte ceiling` | `under the 180000-byte ceiling` (AD-10 wording) |

  - **T3, lowered mode** (`VENDOR_INVOKE_MAX_BYTES_AGY=1000`, 2,000 B fixture): the fixed context alone exceeds 1,000 B, so the result is `fixed_context_too_large`. Assertions kept: `not invoked`, `verdict == "error"`, `request_changes`, exit 1, `b["max_bytes"] == 1000`, and stderr `over the 1000-byte ceiling` (AD-10's wording matches it). Assertions replaced:

    | Old assertion | New assertion |
    |---|---|
    | `outcome_detail == "prompt_too_large"` | `== "fixed_context_too_large"` |
    | `prompt_bytes > max_bytes` | `b["fixed_bytes"] > b["max_bytes"]` |
    | stderr `prompt is \d+ bytes` | `fixed context is \d+ bytes` |
  - **T8:** the agents count of `vendor_invoke agy` call sites goes from 1 to 0, because the call moves into `chunked_review.sh`. The `vendor_invoke codex` count of 1 and every launch-pattern assertion stay.

  **Preserved with unchanged assertions** (because of AD-10's record shape, the guard placement, and the fact that the n = 1 fixtures stay below B_budget; `block("agy")` returns the first, per-chunk, record):
  - T6 (timeout mapping);
  - T7 (one `timeout_unenforceable` record per lane, nothing launched, exit 1);
  - T9 (quote/backslash-safe `stderr_tail`);
  - T11, T11b, T11c (budget guard);
  - T12 (`empty_output`). The `blank` stub mode prints a bare `\n` and is **exempt from envelope wrapping**, because it models a vendor that printed nothing. §4.5's empty-output rule classifies whitespace-only stdout, and also an envelope with an empty `result`, as `failed`/`empty_output` with no reinforce retry. So T12 holds whether or not the stub wraps;
  - T14 (`vendor_nonzero_exit`, rc 3, keys per lane);
  - T16 (`unparseable_output` + `stdout_prefix`, after the single reinforce retry). **Pinned:** `stdout_prefix` is the first 200 characters of the envelope's `result` field, which is the model's text (§4.5). It is taken from raw stdout only when no envelope parsed. The wrapped stub puts `Looks fine to me, \`ship it\`.` in `result`, so `"Looks fine to me" in b["stdout_prefix"]` holds;
  - T17 (a raw fenced approve is salvaged as approve, exit 0);
  - T4, T10, T15 (codex lane, unchanged).

  **Fixture-only change:** under ESC-1 = yes, the agy stub wraps its output in the agy JSON envelope (output as the `result` string, with a `usage` consistent with the stdin size) for the `approve`, `raw`, and `fail` modes. The `blank` and `sleep` modes are not wrapped. That is a helper change, not an assertion change. Any other edit to #2015's assertions voids this ruling and needs re-review against #2015 AR-2/AR-3/AR-4.
- **#2014's sign-offs** stand, on S2's unmodified-tests condition.
- **VF-2:** the worker annotates #2015. No code or gate change follows from it.

## 11. Follow-ups (the worker files these; the architect files nothing)

- (a) The ESC-5 `framework-validator` invocation change.
- (b) Annotate #2032 with the validate_agents coupling (AD-10).
- (c) Annotate #2015 with VF-2.
- (d) A single source for `NON_AGENT_TOKENS`, `KNOWN_LABELS`, `KNOWN_SHORT_AGENTS`, `EXTERNAL_AGENTS`, and `OUTPUT_DOCS` (AD-3).
- (e) If ESC-6 is "exclude", annotate #2014 ESC-7/ESC-8 so they no longer point at #2033.

## 12. Revision log

**Round 2 (2026-10-09)**, responding to the technical-design review (REQUEST_CHANGES, 5 MUST_FIX, 6 SHOULD_FIX, 4 notes). Every number below was re-measured on `a29f99a42`.

| # | Finding | Disposition |
|---|---|---|
| 1 | Mention and naming-section rules undefined and inconsistent; fallback numbers used a substring rule | **Fixed.** AD-3 pins one rule: an exact-content single-line code span, counted inside fences too, used for edges, naming sections, the index, and tests. §0.3 recomputed: 69,301 / 66,971 / 92,669. Round-1 figures withdrawn. `worker` → `overseer` is not an edge. Header bytes (≈ 80 B per pair) are stated as included. |
| 2 | 116 pairs vs 136 directed edges; fallback direction | **Fixed.** Planner input is directed edges (136). The fallback always keeps the referenced agent B whole. One placement per existing direction; both directions get separate fallbacks. S1 test pins 136/116/191. |
| 3 | "split-md-h2 unchanged" contradicts always-split docs; flag, unit kind, and edge endpoints undefined | **Fixed.** §4.1: the cut function is reused, but the unconditional trigger is new and stated as such. Unit JSONL gains `kind` and `split`. `--split-kind` dropped. Edge endpoints are repo-relative unit paths. |
| 4 | Focus mode breaks rule 1; `verify-run --input` shape; false preamble | **Fixed.** Invariant restated over the placed set P (§4.2). New `verify-run --cover-inputs DIR`, with input copies and hashes (§4.4). Cover preamble separates "reviewed in other chunks" from "not reviewed (index only)" (§4.3). |
| 5 | Superseded #2015 tests incomplete | **Fixed.** AD-10 keeps `_agents_vi_failure_json`'s exact shape per chunk, adds chunk fields, and writes the coverage block last. §10 lists every agents-parameter assertion as superseded (T1, T3, T8) or preserved (T4, T6, T7, T9 to T12, T14 to T17), plus the envelope-stub fixture change. |
| 6 | Worst case is not the worst case | **Fixed.** AD-6 recomputed at true bounds: R 401, lens 4,096, known issues **capped deterministically at 16,384** (new), index 24,576, P_max 8,192 + 3,585 outlines → B_budget 122,766. All fallbacks fit (max 92,669). 15 chunks at that bound. |
| 7 | Focus mode brings pre-existing neighbour findings into the release gate | **Fixed.** [FOCUS]/[CONTEXT] tagging, deterministic fail-closed `split-findings` routing to a non-blocking [CONTEXT] section, residual named, consequence stated in ESC-2. |
| 8 | Codex input under `--changed-only` unspecified | **Fixed.** AD-11 input contract: full corpus in full mode, exactly P in focus mode, with a FOCUS/CONTEXT header and the same routing. Plan computed even under `--skip-agy`. |
| 9 | Two incompatible output paths; mangled escape text | **Fixed.** AD-10 names `chunked_review.sh` salvage plus Python re-serialisation for agy chunk blocks. `_vi_neutralize_output` stays codex-only. The escape is now spelled out in words so the text cannot be mangled. |
| 10 | ESC-1 "no" branch undefined | **Fixed.** S3 is conditional on ESC-1 = yes; "no" returns to the architect. |
| 11 | AD-12 and AD-13's "hold" reading bind human-pending decisions | **Fixed.** AD-12 withdrawn → ESC-6. The "hold" semantics → ESC-7. AD-13 keeps only the technical stacking and order rules. |
| 12 | 27 + 4, not 26 + 5 | **Fixed** (§0.1, from `consumer_agents.txt`). |
| 13 | `EXTERNAL_AGENTS` / `output_docs`; identity-rule difference; frontmatter-less files | **Fixed** (AD-3). |
| 14 | Mark the prompt doc as new | **Fixed** (S3 files). |
| 15 | §2.1 row for both-directions fallback | **Fixed** (row 3b; 0 such pairs today). |

No finding was declined.

**Round 3 (2026-10-09)**, responding to the technical-design review's APPROVE_WITH_CONDITIONS on `6d2b4e163`. The `T1`/`T3`/`T12`/`T16` claims were verified against `git show worker-2015-validators-vendor-invoke-261008083501-752797:tests/framework/test_framework_validators_vendor_invoke.py`, covering the harness (`HOS_FEED_KNOWN_ISSUES=0`, one agent `coder.md`, an empty `docs/`) and the stub modes. The 258 B figure was measured with `sed -n 736,738p scripts/run_second_review.sh | wc -c`.

| # | Condition | Disposition |
|---|---|---|
| N1 | The non-blocking [CONTEXT] rule silently depends on #2032 staying unfixed | **Fixed.** AD-8 pins the block verdict after routing: `request_changes` → `approve` only if the block had ≥ 1 blocking finding and *all* of them were routed. The #2032 shape (no findings, or only non-blocking ones) is never downgraded, and `error` is never touched. Audit fields are added. The ADR explains why this is not a #683 laundering path. AD-10's independence claim is corrected and the #2032 note extended to items (a) to (c). |
| N2 | The lane loop is not "reused unchanged"; outcome and detail mismatch; no `VENDOR_INVOKE_*` or salvaged-object interface | **Fixed.** New §4.5: a per-chunk `result.json` interface, with a detail table inside #2014's unchanged outcome set and `vi.*` / `salvaged` / `stdout_prefix`. It is stated as a requirement on #2014 S1a's lib; if S1a merged without it, S2 adds it additively (S2 files updated). §4.1 no longer says "unchanged". |
| §10-T1 | The 150 KB fixture is not `unit_too_large` | **Fixed.** Only the argv assertion changes. The fixture and the MAX_ARG_STRLEN purpose are kept. |
| §10-T12 | Envelope-wrapping `blank` mode would turn `empty_output` into `unparseable_output` | **Fixed, both ways.** `blank` is exempt from wrapping, and §4.5 also treats an envelope with an empty `result` as `empty_output` with no retry. |
| §10-T3 | `prompt_bytes`/`max_bytes` and the stderr regexes cannot hold | **Fixed.** AD-10 defines plan-failure numeric keys and exact stderr wording. §10 lists every kept and replaced T3 assertion for both modes. |
| §10-T16 | `stdout_prefix` source not pinned | **Fixed.** It is the envelope's `result`, falling back to raw stdout only if there is no envelope (§4.5, §10). |
| F4-a | Manifest must record B_budget; is "whole when it fits" verified? | **Fixed.** The manifest records `budget_bytes`, `max_bytes`, `reserve_bytes`, `fixed_bytes`, and `p_max_bytes`. `verify-run` **checks** that every fallback edge's whole pair exceeds `budget_bytes`. |
| F4-b | Excerpt representation in the chunk's units list | **Fixed.** Each entry has a `role` (`whole`, `part`, or `excerpt` with `for_edge`/`sections`/`of`/`sha256`). Edge JSONL carries `naming_sections`/`section_count`. `verify-run` checks section equality and re-derives the sha from disk. |
| F4-c | Is `--cover-inputs DIR` the `--out-dir`? | **Fixed.** Yes. `verify-run` refuses any other directory. |
| F4-d | A shared writable dir means accidents, not tampering | **Fixed.** Stated explicitly in §4.4, at the same trust level as #2014. |
| S-1 | 2 fallbacks today, not 1 | **Fixed.** Today's B_budget is ≈ 139.65 KB. `overseer` → `worker` (139,822) also falls back. §0.3, §2.1, §5, and ESC-3 updated. |
| S-2 | Chunk counts disagree with an independent planner | **Fixed.** Stated as approximate ranges (full 11 to 12 / 13 to 15; release 8 to 9 / 10). S3's live run is the measurement of record. Cap 24 unchanged. |
| S-3 | Codex behaviour when `plan` fails under `--skip-agy` | **Fixed.** P now comes from `agent_graph_logic placed-set` (pure graph computation, no size failure). Codex runs on P whether or not `plan` fails, and `plan` is not run under `--skip-agy`. A `placed-set` failure stops both lanes. Codex focus-mode routing and its fail-closed multi-object case are specified (AD-11). |
| S-4 | R = 401 wording | **Fixed.** The lines are 258 B; 401 is kept as a safe bound. |
| S-5 | Is the known-issues heading inside the cap? | **Fixed.** Inside. The 16,384 B cap covers heading, titles, and trailer. |
| S-6 | Does #2014 AR-5 apply to [CONTEXT]? | **Fixed.** Yes. The section holds plain-text lines only, with no JSON objects and no `verdict`/`findings`/`attacks`/`error` keys, and backticks are neutralised. |

No condition was declined.

**Round 4 (2026-10-09, final)**, responding to APPROVE_WITH_CONDITIONS on `18cefbb10`. Only the listed items were changed. `BLOCKING_SEVERITIES` was verified at `validation_logic.py:62`.

| # | Condition | Disposition |
|---|---|---|
| N4 | §4.5's empty-output rule changes the shared lane loop and would make second review exit 1 | **Fixed (per-caller option, as preferred).** The rule is an opt-in lib flag, **default OFF**, which keeps #2014's retry → `unparseable` path for every other caller, second review included. validate_agents opts in. A #2014 lib test pins the default. No #2014 contract change, so no #2014 sign-off is affected. |
| C2 | Contradictory "blocking finding" definition | **Fixed.** Every lane uses `validation_logic.BLOCKING_SEVERITIES` (`critical`, `high`, `blocking`), imported, with severities compared after `strip().lower()`. The `request_changes` comparison uses the same normalisation. |
| C3 | Path matching for routing not pinned | **Fixed.** Exact byte equality. A string resolves by repo-relative path, or by basename only if that basename belongs to exactly one corpus unit. Any of the following keeps the finding blocking: an ambiguous basename, an unmatched string, any FOCUS resolution, or an index-only (outside P) unit. Only [CONTEXT] units in P can be routed. |
| C4 | Plan's fits test and verify-run's check could disagree at the boundary | **Fixed.** One shared `pair_bytes` / `excerpt_pair_bytes` in `chunk_logic` covers headers, separators, and labels, exactly as rendered. It is used by plan's fits test, the post-render assertion, and verify-run. The boundary test uses `overseer` + `worker` at −1/0/+1 bytes. |
| C5 | The #683 rationale misstated who controls routing | **Fixed.** The text now says routing is deterministic but model-influenced (the reviewer writes `files`). A mis-attributed FOCUS defect can be routed out, and the text points to the ESC-2 attribution residual and its mitigations. |
| (a) | One implementation of P | **Fixed.** `plan --placed F` takes P from `placed-set` and verifies closure and justification element by element. It does not recompute P. |
| (b) | Atomicity of `inputs/` copies | **Fixed.** A failed plan writes no `inputs/` copies, following #2014 §4. |

No condition was declined.

**Status: Proposed (architect), round 4.** S1 may go to `technical-design` and `coder` now. S2 waits for #2014 S1a. S3 waits for its §8 gates, including ESC-1 = yes. Any deviation from AD-1 to AD-11 and AD-13 comes back to the architect.
