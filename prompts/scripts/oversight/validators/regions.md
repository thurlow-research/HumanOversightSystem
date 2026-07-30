# Prompt Artifact — regions.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/validators/regions.py` |
| **Description** | Advisory PACK conflict detection: negation-vs-recommendation heuristic (#1081 Option 3) |
| **Date** | 2026-07-30 |
| **Model** | claude-sonnet-4-6 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Autonomous HOS worker cron cycle. Step 2 selected issue #1081 (priority:high,
needs-ai, v0.6.0) — "Pack composition: should dependent packs inherit/override
their base, or stay additive-only? (ADR-level)". The issue's own analysis
recommends a 3-option sequence: (1) #1080 ordering fix — already merged; (2)
Option 3, make PACK-body contradictions *detectable* rather than structurally
prevented — implement now; (3) Option 2, full inheritance/override semantics —
explicitly deferred to an ADR-level decision via #1078, not to be settled here.

Implement Option 3: an advisory (non-fail-closed) check in regions.py that
flags when one PACK region body for an agent explicitly contradicts another
PACK region body for the same agent, so ADR-032 D3's "author additively,
never contradict" rule — currently pure human-reviewed discipline — gets a
verification mechanism per research/findings/unenforceable-rules-need-
verification-mechanisms.md.
```

## Constraints Specified

- Follow existing `regions.py` conventions: pure function + thin CLI subcommand pattern (`_cmd_*` + `build_parser()`), `Result`/`Region` dataclass style, stdlib-only (no new deps).
- Must NOT be fail-closed / block installs — the issue text explicitly says detection here is heuristic ("will have false negatives... probably needs a model-based check rather than a regex"), so findings are advisory only, distinct exit code from `EXIT_INVALID`.
- Must not regress ADR-032 D3's real, currently-correct pack bodies (`packs/node`, `packs/astro`) — i.e. must not fire on legitimate additive layering.
- Test against the actual shipped pack content, not just synthetic fixtures.

## Refinement History

v1: considered a broad co-occurrence heuristic (flag any two PACK bodies for the same agent that mention the same known tool/library term from a curated category table, e.g. jest vs. vitest, npm vs. yarn). Rejected after empirically running it against the real `packs/node/unit-test.md` + `packs/astro/unit-test.md` bodies: PACK:node presents both jest and vitest as acceptable ("do not assume one over the other; use whichever the project already has installed") while PACK:astro recommends vitest specifically for Container-API rendering tests — legitimate additive depth, not a contradiction. A co-occurrence check would have false-positived on the framework's own correctly-authored packs on day one.

vFinal: narrowed to high-precision / low-recall — only flag an EXPLICIT negation in one PACK body ("do not use X" / "don't use X" / "never use X") paired with an EXPLICIT affirmative recommendation of the same term ("use X" / "prefer X" / "target X") in another PACK body for the same agent. Verified empirically: zero findings against every real `pack.toml requires`-closure shipped today (only `astro→node`), and correctly flags a synthetic true-positive (one body saying "never use jest", another saying "use jest").

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/oversight/validators/regions.py`
4. Note any drift in a new version artifact (`regions.v1.md`)
