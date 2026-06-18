# Requirements Spec — Issue #376: Arbiter Ranks Panel Findings by Corroboration Strength

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #376
**Milestone:** v0.5.0 — Quality
**Date:** 2026-06-17
**Author:** pm-agent
**Research citations:** Charoenwet et al. 2026 (AgenticSCR, arXiv:2601.19138); Loker 2025 (CodeRabbit volume analysis)

---

## 1. Problem Statement

The HOS panel arbiter (`run_panel.sh` ARBITER stage, lines 423–451) currently deduplicates
findings from the cross-vendor roster and passes them to a Sonnet synthesis step, but the
resulting output applies no corroboration-based ordering. Every finding is presented to the
human at equal standing regardless of whether it was raised by one reviewer or confirmed
independently by multiple vendors.

Two empirical findings from the systematic literature review motivate this change:

1. **Volume problem:** CodeRabbit produces approximately 1.7× the issue volume of a
   single-reviewer baseline (Loker 2025). As the HOS panel roster grows with risk tier
   (MEDIUM: 2 reviewers; HIGH+: 4 reviewers), aggregate finding volume scales with roster
   size. Without signal filtering, human reviewer fatigue is the predictable failure mode.

2. **Precision lever:** AgenticSCR's detector→validator architecture raised precision
   while cutting comment volume by 81% by filtering low-grounding findings — those raised
   by only one reviewer without corroboration from a second independent source (Charoenwet
   et al. 2026). The mechanism is corroboration-gating: findings that at least two
   independent reviewers agree on are surfaced as primary signals; findings from a single
   reviewer are surfaced separately as secondary signals, not dropped.

HOS's cross-vendor panel is architecturally equivalent to the multi-agent setup in which
corroboration-gating was validated. The arbiter's deduplication pass already groups
findings by underlying issue; this spec adds the missing ranking step on top of that pass.

---

## 2. Scope

This spec covers exactly the following changes:

**In scope:**
- The arbiter synthesis step in `run_panel.sh` (currently lines 423–451): extend the
  Sonnet arbiter prompt to request and return a corroboration count per finding.
- A new Python module (or extension of the existing `panel_logic.py` module planned by
  #333) that implements the corroboration-counting and tier-ranking logic.
- The panel summary comment posted to the PR: presentation order and section structure.
- The line-level review threads posted to the PR: Tier 1 findings are posted first.
- The `arbiter.json` artifact written to `.ai-local/panel/pr<N>-*/`: extended schema.

**Out of scope:**
- The reviewer fan-out logic (REVIEWERS stage) — no change to how reviewers are invoked.
- The deduplication logic already performed by the arbiter — corroboration ranking is
  applied after deduplication, not instead of it.
- Merge blocking rules — Tier 2 findings do not change merge-block semantics (see §6).
- The triage stage, SQC sampling, or risk-level computation.
- Any change to how reviewers format their output JSON.

This spec depends on #333 (Python extraction refactor) reaching the point where a
`panel_logic.py` module exists or is being co-developed. If #333 is not yet started,
the Python corroboration module introduced here can be the seed of that module.

---

## 3. Requirements

### R1 — Corroboration counting

The system must, for each deduplicated finding in the arbiter output, count the number of
independent reviewers that contributed at least one raw finding matched to that
deduplicated finding. The count is an integer ≥ 1. Reviewers from the same vendor CLI
invoked under different lenses (e.g., `codex:security` and `codex:adversary`) are counted
as one independent reviewer for corroboration purposes, because they share a model and
training origin. Reviewers from different vendor CLIs (e.g., `agy` vs `codex`) are counted
as independent.

The corroboration count must be attached to each finding in the `arbiter.json` output as
a field named `corroborated_by` (integer) and a field named `corroborating_reviewers`
(array of reviewer name strings).

### R2 — Tiered ranking

The system must classify each deduplicated finding into one of two tiers based on the
corroboration count produced by R1:

- **Tier 1 (MUST surface first):** `corroborated_by >= 2` — confirmed by at least two
  independent reviewers.
- **Tier 2 (SHOULD surface second):** `corroborated_by == 1` — raised by exactly one
  reviewer with no independent corroboration.

Within each tier, findings must be ordered by severity (tier1 severity before tier2/3/4
severity, using the existing four-level severity scale). The tier classification must be
attached to each finding in `arbiter.json` as a field named `corroboration_tier`
(integer: 1 or 2).

### R3 — Output format

**PR summary comment:** The summary comment posted to the PR must present findings in two
clearly separated sections:

```
### Tier 1 — Cross-vendor confirmed findings (N)
> Confirmed by ≥ 2 independent reviewers. Address before merge.

[finding list]

### Tier 2 — Single-reviewer findings (N)
> Raised by one reviewer. Review and address where warranted.

[finding list]
```

If a tier has zero findings, its section is omitted entirely (no empty heading).

The existing arbiter `summary` field (the Sonnet-written markdown overview) is retained
and appears above both tier sections.

**Line-level threads:** Tier 1 findings must be posted as line-level review threads before
Tier 2 findings. Within each tier, severity ordering (most severe first) is preserved.
Individual thread bodies must include the corroboration tier label:
`Tier 1 — cross-vendor confirmed` or `Tier 2 — single reviewer`.

**`arbiter.json` schema extension:** Each finding object in the `findings` array of
`arbiter.json` must include `corroborated_by` (int), `corroborating_reviewers` (array of
strings), and `corroboration_tier` (int: 1 or 2).

### R4 — Python module for ranking logic

The corroboration-counting and tier-ranking logic (R1 and R2) must be implemented as
named functions in a Python module, not as inline shell or jq logic. The module must be
locatable at `scripts/oversight/panel_logic.py` (consistent with #333 and the #314
principle: shell scripts are launchers, not logic containers).

The minimum required public interface is:

```python
def count_corroboration(
    raw_findings: list[dict],
    deduplicated_finding: dict,
) -> tuple[int, list[str]]:
    """
    Given the full list of raw findings from all reviewers and one deduplicated
    finding, return (corroborated_by_count, corroborating_reviewers_list).
    Reviewers from the same vendor are collapsed to one (see R1).
    """

def rank_findings(
    findings: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Given a list of findings already annotated with corroboration fields,
    return (tier1_findings, tier2_findings), each sorted by severity.
    """
```

The `run_panel.sh` shell script invokes this module via a Python subprocess call after the
arbiter raw output is parsed. The shell script must not re-implement the ranking logic.

---

## 4. Acceptance Criteria

**AC1 — Corroboration counts are correct:**
Given a set of raw findings where finding F was raised by both `agy` (correctness lens)
and `codex` (security lens), the deduplicated finding for F has `corroborated_by = 2` and
`corroborating_reviewers = ["agy", "codex"]`. Given a finding G raised only by `agy`,
G has `corroborated_by = 1` and `corroborating_reviewers = ["agy"]`. Given finding H
raised by `codex:security` and `codex:adversary` (same vendor, two lenses), H has
`corroborated_by = 1` (same vendor collapsed per R1).

**AC2 — Tier assignment and ordering are correct:**
A finding with `corroborated_by >= 2` is assigned `corroboration_tier = 1`. A finding
with `corroborated_by == 1` is assigned `corroboration_tier = 2`. The `findings` array
in `arbiter.json` is ordered: all Tier 1 entries before all Tier 2 entries, and within
each tier entries are ordered by severity (tier1-severity > tier2-severity > tier3 >
tier4).

**AC3 — PR comment sections are correctly structured:**
In a dry-run (`--dry-run`) execution with at least one Tier 1 and at least one Tier 2
finding, the console output contains both section headings (`Tier 1 — Cross-vendor
confirmed findings` and `Tier 2 — Single-reviewer findings`) in the correct order, with
Tier 1 first. In a run where all findings are Tier 2, only the Tier 2 section heading
appears.

**AC4 — Python module is independently callable:**
The function `rank_findings` in `scripts/oversight/panel_logic.py` can be imported and
called in a Python unit test (without running `run_panel.sh`) with a synthetic finding
list and returns the correctly partitioned and ordered tuples. No subprocess invocation
or shell context is required to exercise the ranking logic.

---

## 5. Non-Requirements

The following behaviors are explicitly outside the scope of this spec:

- **No finding is filtered out.** Both Tier 1 and Tier 2 findings surface in the PR
  comment and as threads. Corroboration-gating controls presentation order and visual
  prominence only; it does not suppress findings.
- **Tier 2 findings do not block merge independently.** The existing merge-blocking
  mechanism (required review thread resolution, branch policy D12) applies to all posted
  threads regardless of corroboration tier. This spec does not add a Tier 1-only merge
  gate. A Tier 2 thread still requires resolution before merge under the existing policy.
- **This spec does not change the reviewer roster or fan-out logic.** The number of
  reviewers invoked per risk level remains unchanged.
- **This spec does not require the arbiter (Sonnet) to perform the corroboration
  counting.** The arbiter's prompt may be extended to include corroboration hints, but the
  authoritative corroboration count is computed deterministically by the Python module
  from the raw findings JSON, not inferred by Sonnet.

---

## 6. Open Questions

**OQ-1 — Definition of "same finding" for corroboration matching**

To count corroboration, the system must determine whether a raw finding from reviewer A
and a raw finding from reviewer B describe the same underlying issue. Two candidate
approaches:

- **File + line proximity:** Two findings match if they reference the same file path and
  their line numbers are within ±5 lines of each other. This is deterministic, fast, and
  requires no LLM call.
- **Semantic similarity:** Two findings match if their `title` or `detail` fields are
  semantically equivalent (requires embedding or LLM comparison).

**Proposed default:** file + line proximity (same file, |line_A − line_B| ≤ 5). This
is deterministic and consistent with how the existing deduplication prompt instructs
Sonnet ("same file/line/cause"). The ±5 tolerance accommodates minor off-by-one
differences between reviewers citing slightly different line positions within the same
code block.

**This is flagged as an open question for the architect.** The file+line±5 heuristic may
produce false positives (two distinct issues on adjacent lines treated as corroborated)
or false negatives (the same logical issue at different call sites). The architect should
decide whether the deduplication step that Sonnet already performs is sufficient to make
file+line±5 safe as a post-dedup matching key, or whether a different approach is
warranted.

---

## 7. Context for Architect

- The arbiter stage is currently in `run_panel.sh` lines 423–451. The Sonnet prompt
  (lines 426–439) asks for deduplication but not corroboration counting.
- The raw findings array written to `$RUN_DIR/findings.raw.json` (line 420) contains
  `reviewer` and `lens` tags on every finding (added at line 417). This is the input
  the Python module reads for corroboration counting.
- Issue #333 proposes `panel_logic.py` as the module for extracted panel logic. This
  spec's R4 assumes that module path. If #333 introduces a different path, R4 should
  be updated to match.
- Issue #314 establishes the principle that shell scripts should be launchers, not logic
  containers. R4 is the application of that principle to this feature.
- The `--dry-run` flag (line 72) already suppresses all posting; AC3 must be verifiable
  in dry-run mode without touching the GitHub API.
