# Finding: Real Data, Not Reviewer Diversity, Caught the Bug

**Role:** oversight-mechanism. A reviewer, of any vendor or size, cannot find a defect that only appears on real data if the pipeline never shows it real data. Supplying the data is the oversight layer, and model diversity is secondary.

**First observed:** 2026-11-07 (PR #2268 / #2229), then measured on 2026-11-08 by a ground-truth model evaluation (#1985, #1455).

---

## The Finding

This qualifies `cross-vendor-review-finds-real-bugs.md` (decorrelated review catches same-vendor blind spots). Decorrelation is necessary but not sufficient. On this incident it was the reviewer's **input**, not its vendor, that decided whether the defect was caught.

- PR #2268 changed the parser behind the usage-pause gate, which runs before every autonomous cycle. Real `/usage` output had changed layout (new "tip" lines such as `  47%  Trim …/CLAUDE.md`), and the deny-by-default guard treated those lines as unrecognised limit lines. Every reading failed. Under the shipped default `fail_mode=closed`, that pauses **every** cycle.
- The whole review pipeline approved it: worker reviewers, overseer, and agy plus codex as cross-vendor second reviewers. Every lane saw the **diff** and the **synthetic** test fixtures. None saw the real capture that the poller writes every 5 minutes.
- The worker's own conditional item asked exactly the right question ("verify that no genuine /usage output trips the guard"). It went to the human as a thread, and nobody ran it until the human-proxy did.
- Given the real capture and that question, **agy and codex both caught it**: the correct result, all culprit lines, and an "unsafe" verdict.

## Evidence: the ground-truth evaluation (2026-11-08, #1985)

**Track A: find the defect by reading.** There were seven items with verified answers, all drawn from real review decisions that week:
- the #2268 guard on the real capture;
- a surface-list lookup and its positive control;
- an issue-vs-PR completeness check;
- a formatting-only diff and a planted non-formatting variant;
- a "corrected" guard.

| Model | Runs | Verdict correct | Dangerous "safe" calls |
|---|---|---|---|
| codex | 21 | 21 | 0 |
| agy (Gemini) | 21 | 18 | 3 |
| qwen3-coder-next (~80B, local) | 7 | 6 | 1 |
| devstral-2 (123B, local) | 7 | 6 | 1 |
| devstral-small-2 (24B, local) | 7 | 5 | 2 |
| qwen3-coder (30B, local) | 7 | 5 | 2 |
| qwen2.5-coder (32B, local) | 7 | 5 | 2 |

- **Every model passed the easy items.** Only the two regex-against-real-input items separated them. Passing easy review items is not evidence of review ability.
- **The evaluation's own answer key was wrong once.** The "corrected, safe" control guard accepted an in-block `  99%  Session limit reached` line. Only codex found it; agy and every local model called it safe. Ground truth must come from executing the code, not from the author's belief.
- **Size bought nothing measurable.** The 123B and 80B models made one fewer dangerous call than the 30B, which is noise at n=1. They were no better at identifying the cause, and cost 2–4× the memory.

**Track B: the model writes the tests, a harness runs them.**

| Condition | Bug caught |
|---|---|
| Spec only | 0 of 5 models |
| Spec plus one real capture | 4 of 5, always through the capture |

- Wrong expected values produced 1–13 false alarms per generated suite.
- One model redefined the function under test.

## A second, related observation

The defect was **visible the whole time**. The overseer's own cycle log printed `[USAGE-UNCHECKED] fail_mode=open read_failed:missing_session` on about 170 consecutive cycles (2026-11-06 to 2026-11-07), including the cycles that reviewed #2268. A local `fail_mode=open` override turned a persistent failure into one quiet line per cycle. The design's alert (a Grafana rule) existed only in the ADR and had never been deployed. A failure that is disclosed but never escalated behaves like no failure (compare `buried-disclosure-fails-like-no-disclosure.md`).

## Implications for research

1. **"Feed the reviewer real data" is its own oversight layer.** Under O2 (*blind to any dimension it has no layer for*), the pipeline had no layer that put environment data in front of a reviewer. Every lane, of every vendor, was blind in the same way. Diversity cannot decorrelate a blind spot that comes from the input.
2. **"Fails closed" is safe only when its blast radius is one PR.** The guard's comment ("a false positive fails closed, which is the safe direction") was accepted by every reviewer. For a gate in front of every cycle, a false positive means a total outage.
3. **Local models fit as test-case proposers, not reviewers.** Scott accepted this on 2026-11-08 (the formal ruling is to be recorded on #1455): local models propose test cases; the harness feeds real captures and executes them; a spec-grounded filter drops wrong expectations; the output is advisory and never suppresses a finding. Value comes from the data, not the model.
4. **Benchmarks of reviewers need executed ground truth.** Even the human-proxy's "known safe" control was unsafe.

## What changed

- **#2229:** the guard fix must accept real output, and refuse limit wording inside breakdown blocks (comment 6724540762).
- **#2269 (v0.7.10):** the worker runs checks before handing them to the human, and parsers of external output need real-capture fixtures.
- **#2274 (v0.7.10):** the overseer runs open verification items, checks parsers against real captures, and requires the fail-closed blast-radius rule.
- **#2273 (v0.7.0):** a local, loud signal when usage readings keep failing (ruling B on #2273: no GitHub calls from the poller).
- **#1455 / #1985:** the role of local models was accepted by Scott. The formal ruling is to be posted on #1455.
- **Pending:** a v2 benchmark adding Claude Sonnet, Opus and Fable plus OpenAI and Gemini model variants, with 3 runs each and frozen prompts. This finding's tables will be updated when it lands.

## Related findings

- `cross-vendor-review-finds-real-bugs.md`: qualified here (decorrelation is necessary, not sufficient)
- `llms-belong-inside-deterministic-orchestration.md`: corroborated (the harness executes, the model proposes)
- `buried-disclosure-fails-like-no-disclosure.md`: the 170-cycle silent signal
- `reviewer-agents-file-confident-non-reproducing-reports.md`: the confidently-wrong side, here as confident "safe" verdicts
- `the-ratchet-counts-human-attention-as-free.md`: the check the worker handed to the human went unrun
