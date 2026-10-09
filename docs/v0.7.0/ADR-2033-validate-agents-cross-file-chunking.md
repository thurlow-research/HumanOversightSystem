# ADR-2033: Cross-file chunked review for validate_agents.sh. A deterministic agent graph in every chunk, and chunks packed so every directed agent-to-agent reference is co-resident

**Status:** Proposed (architect), **round 2**, revised after the technical-design review's REQUEST_CHANGES (see §12, Revision log). Decisions marked BINDING bind `technical-design`, `coder`, `code-reviewer`, and the reviewers once their gating ESC items (§9) are cleared on record. Decisions marked **PROVISIONAL (ESC-n)** are drafted on the recommended answer. None is treated as ruled by the human.
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

Packing simulation: greedy cover, AD-5 invariant, docs always split, doc edges soft.

| Scope | Required directed edges | B = 139.8 KB (today, AD-6) | B = 122,766 (worst-case bound, AD-6) |
|---|---|---|---|
| Full mode | 136 | **12 chunks**, 1 section fallback, 1.52 MB of units | **15 chunks**, 3 fallbacks, 1.60 MB |
| Release focus, v0.6.0 (5 agents + 2 docs) | 58 | **9 chunks** | **10 chunks** |

No edge comes near `edge_too_large` at either budget. The largest fallback is 92,669 B, which leaves about 30 KB of margin even at the worst-case bound. These counts come from a greedy approximation. The binding constraints are the invariant and the cap (AD-5, AD-9), and S3 re-measures with the real planner.

**VF-2 (a correction on record to #2015 AR-11 / ESC-2).** #2015 says both validators "ship to consumers (`test_consumer_framework_files.py:21-22`)". Those lines are in `_HOS_DEV_ONLY`, the never-ship list. The release installer does not ship `validate_agents.sh`. The legacy `scripts/framework/install.sh --source` copy loop (L99-115) still copies it, but without `scripts/oversight/**`. The worker annotates #2015. AD-11 below makes a missing dependency fail loudly.

---

## 1. Decision summary

| # | Decision |
|---|---|
| AD-1 | Cross-file coverage comes from a **deterministic cross-file index in every agy chunk**, plus **edge-cover packing** over directed agent→agent edges. There is no AI summary pass. (BINDING) |
| AD-2 | The index is a pointer, not evidence. Findings must be confirmed in visible text. (BINDING) |
| AD-3 | New pure module `agent_graph_logic.py`, with one pinned mention rule and one pinned naming-section rule. It reuses `agents_static_logic` read-only. (BINDING) |
| AD-4 | New `cover` mode in #2014's `chunk_logic.py`. What is reused unchanged and what is new are stated exactly. (BINDING) |
| AD-5 | Coverage invariant over the **placed set**, per directed edge. The section fallback keeps B whole. A run fails loudly if an edge cannot fit. (BINDING) |
| AD-6 | Budget follows #2014 §4.2. Known issues are deterministically capped at 16,384 B. Feasibility is proven at the worst-case bound. (BINDING) |
| AD-7 | Docs are **always** split at `## ` (a new trigger, reusing the split function). Doc edges are soft. (BINDING) |
| AD-8 | `--changed-only` narrows to the corpus and plans focus plus required neighbours. Context-only findings are non-blocking. (PROVISIONAL, ESC-2) |
| AD-9 | Sequential calls. Cap 24 (lower-only). Never sampled. (BINDING; cost is ESC-4) |
| AD-10 | Per-chunk blocks: Python re-serialisation for success, `_agents_vi_failure_json` shape for failure. Coverage gate exits 1 and is not counted as a pass. #2036 stays inert; the #2032 exposure is recorded. (BINDING) |
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
| 3 Cross-file mismatches | Every directed agent→agent edge is co-resident (AD-5). | Always, for pinned-rule mentions between agent files. | (i) Mentions without an exact-name span, for example `` `overseer.md` `` or "the overseer". (ii) Doc→agent edges are soft; Phase 3 validate_docs owns the pairwise check once #2014 S1b lands. (iii) Section-fallback edges: B is whole, but A is seen only through its naming sections, so a contract in A's *other* sections that bears on B is missed. Today that is 1 edge; at the worst-case bound, 3. |
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
- the whole `chunked_review.sh` lane loop, under ESC-1 = yes.

**New, and not "unchanged":**
1. **Unit JSONL gains two additive fields:** `{"path","header","kind":"agent"|"doc","split":"h2-always"|"never"}`. #2014's pack and grid modes ignore them. `agent_graph_logic` emits `kind:"agent"` with `split:"never"` for agents, and `kind:"doc"` with `split:"h2-always"` for `*.md` docs. Non-markdown extras get `split:"never"`. There is no `--split-kind` flag.
2. **Split trigger (AD-7).** #2014 §4.3 splits a unit only when it is over capacity. Under that rule `docs/AGENTS.md` (81,922 < B) would never split. Cover mode splits every `h2-always` unit **unconditionally**, using the same cut function.
   - *Why:* doc sections ride with the agents they name. In the round-1 simulation, a whole `docs/AGENTS.md` landed alone in a chunk with no agent.
   - *Cost:* a whole-doc omission claim can read falsely in one part. The outline mitigates this, and such false positives fail loud (as #2014 §6.5).
3. **Edge JSONL:** `{"src": <repo-relative path>, "dst": <repo-relative path>, "kind": "mention"|"esc", "required": bool, "lines": [1-based…]}`. Endpoints are **unit paths**, never agent names. Agent names appear only in the rendered index. Hyperedge JSONL: `{"members": [paths], "kind": "esc-cycle"}`. Focus file: one repo-relative path per line.
4. **Mode `cover`:** `plan --mode cover --units F --edges F [--hyperedges F] [--focus F] …`. Units may appear in several chunks. Pack mode's "every unit exactly once" proof does not apply.
5. **Section-fallback units**, rendered as `EXCERPT: sections i,j of n of <A> (A is reviewed whole in chunk-NNN)`.
6. **The cover preamble (§4.3)** and **`verify-run --cover-inputs DIR`** (§4.4).

### 4.2 Coverage invariant (AD-5), asserted in `plan` and recomputed by `verify-run`

The planner input is **directed edges**: 136 required agent→agent edges today.

- **Placed set P.** In full mode, P is every unit. In focus mode (AD-8), P is the focus units, plus both ends of every required edge incident to a focus unit, plus every member of a required cycle that contains a focus unit. Units outside P are **context-only**: they feed the index and the preamble but are never placed.
1. Every agent in P appears **whole** in ≥ 1 chunk. Every doc in P appears as its complete set of parts, each part in ≥ 1 chunk.
2. For every required directed edge A→B with A or B in the focus set (every edge in full mode), some chunk contains **B whole** and either **A whole** (the preferred form, used whenever `|A| + |B| ≤ B_budget`) or **every naming section of A for B** (section fallback). The fallback always keeps the *referenced* agent B whole, because B's full contract is what the claim in A is checked against. If only A→B exists, only A→B gets a placement. If both A→B and B→A exist and neither whole pair fits, each direction gets its own fallback placement. That is the both-directions row in §2.1.
3. Every required hyperedge (an `[esc]` cycle of length ≤ 3 that intersects the focus set, or every such cycle in full mode) has all members whole in one chunk. If they do not fit, it degrades to its member edges under rule 2, and the degradation is recorded.
4. If B whole plus A's naming sections is over B_budget → exit 3 `edge_too_large`, naming both paths and the byte counts. **Agents are never reviewed only as fragments.** An excerpt is always *in addition to* a whole appearance, so #2014 D5 holds.

**Manifest `coverage` (cover mode):**
```
{placed: [...], context_only: [...],
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

- `plan` copies its exact inputs into `DIR/inputs/` (units, edges, hyperedges, focus) and records their sha256 values in `coverage.input_sha256s`.
- `verify-run --manifest M --results R --lane L --cover-inputs DIR`:
  - re-hashes those copies against the manifest;
  - re-reads every placed unit from disk and compares each unit's sha256 to the manifest, which detects a tree that changed mid-run;
  - recomputes invariant rules 1 to 4;
  - runs the unchanged per-chunk-id record check.
- `--cover-inputs` is required in cover mode, and is mutually exclusive with #2014's `--input` (pack/grid).
- Any mismatch → exit 1 with a JSON line, as in #2014 §4.6.

**Rejected alternatives.**
- **(R6)** A parallel chunker. Rejected: #2014 D1/D3.
- **(R7)** Fail on any infeasible whole pair. That would disable the gate whenever a hub agent grows.
- **(R8)** ±N-line excerpts. Those are arbitrary cuts; h2 sections are the authored unit.
- **(R9)** Undirected pair cover. It cannot say *which* side must be whole, and the fallback is inherently directional.

## 5. AD-6: byte budget (BINDING formula; recomputed at true bounds)

`B_budget = 180,000 − R − T − P_max` (#2014 §4.2), computed per run by `plan` from the rendered template.

| Term | Today (measured) | Worst-case bound | Source of the bound |
|---|---|---|---|
| R: reinforce suffix | ≈ 0.3 KB | **401** | the three source lines that build it, `run_second_review.sh:736-738`, used as an upper bound. The real value comes from `chunked_review_reserve_bytes`. |
| T: lens | ≈ 3.3 KB | **4,096** | S3 test pins the lens template ≤ 4,096 B |
| T: known issues | 13,324 | **16,384** | **New deterministic cap** (below) |
| T: index | ≈ 17.4 KB | **24,576** | AD-3 bound |
| P_max: inventory lines | ≈ 2.4 KB (54 units, 1,795 B of paths) | **8,192** | #2014 AR-7 |
| P_max: heading outlines of split docs | 3,385 | **3,585** (outlines + labels) | **measured, not capped.** It grows with the docs' headings, and `plan` counts it exactly. |
| **B_budget** | **≈ 139.8 KB** | **122,766** | |

**Known-issues cap (new, S3).** Today's block is up to 100 titles of ≤ 256 chars each, about 27 KB unbounded. A small Python helper renders it:
- keep whole title lines in `gh`'s order until the next line would exceed **16,384 B** minus the trailer;
- then append `(+N more open issues not listed)`.

The cap is deterministic for a given input and never cuts a line. It applies to both lanes. Its consequence is only noise: an omitted known issue may be re-reported (loud, ledger-dedupable). It is never fail-open.

**Consequences:**
- At the worst-case bound, the three hub edges all need fallback. Each fits, with a maximum of 92,669 B against 122,766 B.
- **No combination of issue-title length, index size, or lens size up to their bounds can cause `edge_too_large` on today's tree.** Round 1's outage scenario is closed.
- Planning uses the actual B_budget, as #2014 does. Plans can therefore vary with the live known-issues block. Each run records its plan (`input_sha256`). The chunk count stays within 12 to 15 on today's tree.

**Single file over budget:**
- An agent over B_budget → `unit_too_large`, exit 3. The fix is a human authoring decision.
- A doc part over B_budget → exit 3.
- A fallback over B_budget → `edge_too_large`, exit 3.
- Nothing is ever truncated or sampled. The known-issues cap is advisory context, not reviewed content.

## 6. AD-8: release scope and context units (PROVISIONAL, ESC-2)

**Corpus.** `--changed-only` selects `changed ∩ corpus` and never widens. The **focus set** is that intersection. The placed set and the rules follow §4.2. Measured for v0.6.0: 58 required edges, 9 chunks (10 at the worst-case bound). If the intersection is empty, today's WARN-then-full-mode fallback (`validate_agents.sh:204-207`) stays.

**Context units.** These are unchanged neighbours placed whole so that edges can be checked.
- **Lens labelling.** Focus mode tags every unit `[FOCUS]` or `[CONTEXT]` in the preamble (§4.3). The lens says: *"Report a finding only if it involves at least one [FOCUS] unit. A defect that lies entirely within [CONTEXT] units is pre-existing and out of scope for this run."*
- **Deterministic routing.** `agent_graph_logic.py split-findings --focus F` partitions each salvaged reviewer object:
  - A finding whose `files` share no path with the focus set goes to a verdict-inert `## [CONTEXT] Pre-existing findings on unchanged files (#130)` section, in a **plain** fence, and does not block.
  - Everything else stays in the reviewer's json block and goes through `process` as normal.
  - **Fail-closed rules:** if `files` is missing, empty, or not a list, the finding stays blocking. A path that is not in the corpus, or not recognised as a unit path or a `basename.md` of one, also stays blocking. Only a finding whose every listed file is a known context unit is routed out.
- **Residual (named).** A reviewer that lists only context files for a defect that is really in a focus file has that finding routed to [CONTEXT], visible but non-blocking. This is model-controlled attribution. The [CONTEXT] section keeps it in front of the human.
- **Full mode** (major releases, ad hoc runs) has no context units, and every finding can block.

*Why.* #130 (`cut_release.sh:146-151`) scoped release convergence to "zero-new since the release diff" because the full corpus keeps surfacing real pre-existing holes. If neighbours were placed whole and blocking, that scoping would be undone through the back door.

*If ESC-2 is answered no:* the 84 extra files become extra doc units with no required edges, about 40+ chunks, over the cap. Codex is refused at 5.4 MB. Phase 2 cannot pass at a minor or patch release.

## 7. AD-9 / AD-10 / AD-11: cost, aggregation, codex

**AD-9: cost and caps (BINDING; the cost model is ESC-4).** Calls are sequential. The reviewed constant for validate_agents is **24**, lowerable via `FRAMEWORK_VALIDATION_MAX_CHUNKS` (clamped per caller by `resolve_max_chunks`).

| Mode | agy calls today (worst-case bound) | agy input | Worst case at cap |
|---|---|---|---|
| Full (major release, ad hoc, `framework-validator`) | 12 (15) | ≈ 2.0 MB (≈ 2.45 MB) | 24 × 300 s = 2 h; 4 h with prose retries |
| Release focus (minor/patch) | 9 (10) | ≈ 1.5 MB | same |

For comparison, today's full mode is 1 call, and it is refused under #2015. A minor release cut with #2014 S1b in place is about 9 + 18 + 9 ≈ **36 agy calls** across Phases 2 to 4. `run_framework_validation.sh` prints the `plan --dry-run` before Phase 2.

**AD-10: output, aggregation, fail-closed coverage (BINDING).**
- **Which path writes each per-chunk block.** For agy, it is the `chunked_review.sh` lane loop (#2014), not #2015's `_vi_lane`/`_vi_neutralize_output`.
  - **Success:** the salvaged object, after AD-8 routing, is re-serialised by Python (`json.dumps`). Then every backtick character is replaced by its six-character JSON escape (backslash, `u`, `0060`), which is #2015's AR-3 policy. Raw vendor stdout is never written inside a json fence (#2014 AR-9). `_vi_neutralize_output` stays only on the codex lane, which is #2015's approved path and is unchanged.
  - **Failure:** S3 writes the chunk's record with **`_agents_vi_failure_json`, keeping its exact keys and its `error`/`summary` strings**, built from that chunk's `VENDOR_INVOKE_*` values. It adds `chunk_id`, `chunk_k`, and `chunk_n`. The detail mapping is:

    | Chunk outcome | `outcome_detail` |
    |---|---|
    | `timeout` | `timeout` |
    | `refused` | `prompt_too_large` |
    | vendor failure | `vendor_nonzero_exit` and the vendor's other details |
    | empty stdout | `empty_output` |
    | prose after the single reinforce retry | `unparseable_output`, plus `stdout_prefix` |
    | not consumed (ESC-1) | `prompt_not_consumed` |
    | consumption check failed (ESC-1) | `consumption_check_failed` |

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
- **#2032 is live here.** `compute_verdict` ignores a block-level `request_changes` that has null or empty findings. Chunking multiplies the number of blocks. This design neither fixes #2032 nor depends on its fix. The worker records the coupling on #2032.
- **Dedup and convergence.** The fingerprint and ledger are unchanged. Hub files appear in about 2.5 chunks on average, so duplicate findings inflate `blocking_count` until dispositioned. That triage cost is accepted. The pass cap counts runs, not chunks.

**AD-11: codex lane (BINDING).** The codex lane is **not chunked** and gets no index. It stays #2015's single `_vi_lane codex attacks` call under the 1,048,576 B ceiling, with #2015's output path. **Input contract:**
- **Full mode:** every corpus unit whole, in path order, under today's `=== FILES TO ATTACK ===` marker, plus the capped known-issues block. That is about 0.63 MB, 60% of the ceiling.
- **Focus mode:** exactly the **placed set P** from the same `plan`, whole and in path order. Docs in P are sent whole, not as parts. A `FOCUS: <paths>` / `CONTEXT: <paths>` header goes before the marker, together with the same "findings must involve a FOCUS unit" instruction. The attacks go through the same `split-findings` routing. The plan is computed (no vendor call) even under `--skip-agy`, so codex always has P.
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
  - on the live tree: **136 directed agent→agent edges, 116 unordered pairs, 191 directed edges in total**, and index ≤ 24,576 B. The live counts are asserted as ≥ to tolerate growth, with the exact values recorded in the PR.

**S2: `cover` mode in `chunk_logic.py`.**
- Risk HIGH. Not protected. **Gated on #2014 S1a merged.**
- Condition: all #2014 S1a tests pass **unmodified**.
- Reviewers: code, security, reliability.
- Files (≤ 6): `scripts/oversight/chunk_logic.py` · `tests/oversight/test_chunk_logic_cover.py` (new) · `DECISIONS.md` · `SCRIPTS-INDEX.md` · prompt artifact.
- Tests:
  - invariant rules 1 to 4, including the both-directions case and the "B stays whole" fallback direction;
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
- **ESC-3 (coverage model).** Is the §2.1 model an acceptable basis for release Phase 2? It consists of: every exact-name agent↔agent mention co-resident, with section fallback (1 edge today, 3 at the worst-case bound); doc↔agent edges best-effort; and the named residuals, including possible "handled nowhere" false positives. *Recommended: yes.*
- **ESC-4 (cost model).** Accept about 12 agy calls (≈ 2.0 MB) per full run where today there is 1, up to 15 at the worst-case bound; about 9 per minor/patch release cut; a cap of 24; and a worst case of 2 h (4 h with retries), sequential? With #2014 S1b, that is about 36 agy calls per release cut. *Recommended: yes.*
- **ESC-5 (operational obligation).** `framework-validator` (`.claude/agents/framework-validator.md:42`, reached via `post-change-sweep`) runs full-mode `validate_agents.sh` inside a Bash call capped at 600 s. Twelve sequential calls will usually exceed that, and the kill leaves no verdict. Accept this, with a follow-up issue (protected `.claude/agents/**`) to move that invocation to focus mode run in the background, or to a human-run step, filed before S3 merges? *Recommended: yes.*
- **ESC-6 (scope; supersedes round-1 AD-12).** #2014 ESC-7 and ESC-8, still awaiting the human, propose deferring `run_red_team.sh` and `review_self.sh` "to the #2033 cross-file design". Should #2033 **exclude** them? Cover mode takes its edges as an input file, so each could adopt it later with its own edge extractor (agents↔scripts↔contract path references; component call edges), under a separate issue and decision. *Recommended: yes, exclude.* Their lenses need different edge extractors, and bundling them would put two more callers behind a protected HIGH slice. If the human rules "include", the architect adds slices S4/S5 here.
- **ESC-7 (#2015 "hold" semantics; supersedes round-1 AD-13 interpretation).** If #2015 ESC-1 is ruled "hold until chunking lands", is the hold satisfied when S3 is **approved and mergeable** (then merge #2015 and immediately S3), or only when S3 has **merged**? S3 is stacked on #2015, so "merged" would require S3 to absorb #2015, which AD-13 forbids. *Recommended: approved-and-mergeable.*

## 10. Affected sign-offs and startup-gap check

- **Startup gap: no.** Chunking was deliberately deferred at #1718 (F1) and at #2015 (AR-6). No prior ADR is revised.
- **#2015's sign-offs** stand as approvals of #2015's diff. S3's HIGH-tier reviewers re-review the rewritten agy lane.
- **#2015's tests**, in `tests/framework/test_framework_validators_vendor_invoke.py`, for the `script="agents"` parameter. Every assertion is listed below as superseded or preserved.

  **Superseded** (S3 amends these, citing this ADR):
  - **T1:** the agents argv `["--sandbox"]` becomes `["--sandbox","--output-format","json"]` (ESC-1). The 150,000 B single-agent fixture is now over B_budget (`unit_too_large`). The fixture shrinks to ≤ 100,000 B; the stdin-marker assertions stay.
  - **T3 (both modes):** an oversized single agent is now `unit_too_large`, a plan failure with no launch, and the 1,000 B lowered ceiling is `fixed_context_too_large`, in place of `prompt_too_large`. The "not invoked", `verdict: error`, `request_changes`, and exit 1 assertions stay.
  - **T8:** the agents count of `vendor_invoke agy` call sites goes from 1 to 0, because the call moves into `chunked_review.sh`. The `vendor_invoke codex` count of 1 and every launch-pattern assertion stay.

  **Preserved with unchanged assertions** (because of AD-10's record shape, the guard placement, and the fact that the n = 1 fixtures stay below B_budget; `block("agy")` returns the first, per-chunk, record):
  - T6 (timeout mapping);
  - T7 (one `timeout_unenforceable` record per lane, nothing launched, exit 1);
  - T9 (quote/backslash-safe `stderr_tail`);
  - T11, T11b, T11c (budget guard);
  - T12 (`empty_output`);
  - T14 (`vendor_nonzero_exit`, rc 3, keys per lane);
  - T16 (`unparseable_output` + `stdout_prefix`, after the single reinforce retry);
  - T17 (a raw fenced approve is salvaged as approve, exit 0);
  - T4, T10, T15 (codex lane, unchanged).

  **Fixture-only change:** under ESC-1 = yes, the agy stub wraps its output in the agy JSON envelope for every mode, with a `usage` consistent with the stdin size. That is a helper change, not an assertion change. Any other edit to #2015's assertions voids this ruling and needs re-review against #2015 AR-2/AR-3/AR-4.
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

**Status: Proposed (architect), round 2.** S1 may go to `technical-design` and `coder` now. S2 waits for #2014 S1a. S3 waits for its §8 gates, including ESC-1 = yes. Any deviation from AD-1 to AD-11 and AD-13 comes back to the architect.
