# Finding: Local Models Fail Toward Approval

**Role:** signal (verdict reliability). On a ground-truth code-review benchmark, every self-hosted coding model's errors were **misses**: dangerous "safe" calls, with no false alarms. Model size bought nothing, and one model's failure was not finishing at all. A local model is a poor verdict-giver, and its errors point exactly the way an oversight gate cannot afford. Used as a **test-case proposer**, with real data in and code doing the judging, two of five became useful.

**First observed:** 2026-11-08 (v1) and 2026-11-08/09 (v2), benchmark run for #1985 and #1455. The companion finding, about the inputs rather than the models, is `real-data-not-reviewer-diversity-caught-the-bug.md`.

---

## The Benchmark

- **12 model variants:**
  - 5 local coding models, served through Ollama on local hardware (about 112 GB of unified memory for the large models): `qwen3-coder` 30B, `qwen3-coder-next` (about 80B), `qwen2.5-coder` 32B, `devstral-small-2` 24B and `devstral-2` 123B;
  - 7 commercial: Claude Sonnet 5.5, Opus 5.5 and Fable 5.1, codex at its default, and Gemini via agy at its default and at two named tiers.
- **Byte-identical, frozen prompts,** three runs per item.
  - Local models ran at temperature 0.
  - The commercial models ran through their CLIs with no repository access.
- **Track A: eight items from one week of real review decisions.**
  - The items: a parser guard on a real capture, two "fixed" versions of it, a protected-list lookup with a positive control, an "issue fully implemented?" check, and a formatting-only diff with a planted twin.
  - Each answer was **verified by executing the code**, never by asking a model.
  - Each item was scored on its result, its cause and its verdict, with dangerous calls counted separately.
- **Track B:** models write tests from a spec, with and without one real capture, and a harness runs the tests against the buggy and fixed parsers.

## Results

**Track A: verdicts by reading** (24 runs per model)

| Group | Verdict correct | Dangerous "safe" calls | False alarms |
|---|---|---|---|
| Claude (3 models), codex, Gemini default | 24 / 24 each | **0** | 0 |
| Gemini named tiers | 21–23 | 1–3 | 0 |
| Local (5 models) | 12–15 | **6–9 each** | **0** |

1. **Local models fail in one direction.** Across all five local models, every wrong verdict was a miss. They said "safe", "complete" or "formatting-only" when the answer was the opposite, and none flagged a benign item. A reviewer that errs toward approval is worse for a gate than one that errs toward caution: the error is silent, and it lands on the merge path.
2. **They miss the easy items too.** On a plain lookup where the path *is* on the security list, two local models were wrong 3 of 3 times. A lookup belongs to a deterministic script, not to any model.
3. **Size bought nothing.** The 123B model was the slowest (about 91 s per call), the worst test writer, and no safer than the 24B model. The 30B was the best local model on both tracks, and among the fastest.
4. **"Did not finish" is a result.** `qwen3-coder-next` never finished two short prompts: all 10 attempts hit the gateway's 600 s lock, most likely a greedy-decoding repetition loop. Each attempt held the shared GPU for its full timeout. In production that is a reliability failure that also blocks other work, not missing data.
5. **A higher tier is not a safer tier (commercial).** Gemini's named "high" tier called the flawed A6 guard safe on all three runs, while its default caught it every time.

**Track B: test proposals, with code doing the judging**

| Condition | Bug caught, commercial | Bug caught, local |
|---|---|---|
| Spec only | 1 / 15 | 0 / 15 |
| Spec plus one real capture | **15 / 15** | 6 / 15 (the two best local models, every time) |

6. **With real data and a harness, local models become useful.** The two best local models caught the bug every time once they were given a real capture and the model no longer had to trace code. Real input matters more than which model is used.
7. **The filter is mandatory for local suites.** Every local suite raised false alarms against the known-good parser: wrong or invented expected values, and one suite even redefined the class under test. Commercial suites matched the spec on 95–100% of their tests, and only 2 of 30 commercial runs had a false alarm.

## Why local models fail this way (hypotheses, not tested yet)

Parked on #1455 as a research agenda:
- **no reasoning step:** the commercial CLIs appear to run hidden thinking modes, while the local runs answered in one pass;
- **quantization:** default local tags are typically 4-bit, which hurts precise multi-step tracing;
- **framing bias:** prompts that say "a PR adds a fix" prime approval;
- **tokenization against character-level regex:** the recurring error was believing `\bsession\b` matches "sessions".

Each hypothesis has a cheap discriminating test, and the planned v3 design runs them as separate arms, alongside approaches that may get more out of local models:
- tool use instead of mental tracing;
- plan, then do, with deterministic checks between stages;
- decomposition into tiny checkable units;
- an escalation cascade to a stronger model;
- self-consistency voting.

## Implications for research

1. **A reviewer's error direction matters as much as its error rate.** For a merge gate, a model whose failures are all approvals adds false confidence on exactly the path the gate protects. Benchmarks of review models should report dangerous calls and false alarms separately, not just accuracy.
2. **Use local models as generators inside a deterministic harness, never as judges.** Ruled by the human on #1455 (2026-11-08):
   - local models propose test cases only;
   - the harness feeds real captures and executes the tests;
   - a spec-grounded filter drops wrong expectations;
   - the output is advisory, and never suppresses a finding;
   - the default is `qwen3-coder:30b`.

   This is `llms-belong-inside-deterministic-orchestration.md` applied to model selection.
3. **The case for local is cost, not quality.** On this benchmark, commercial models did the same proposer job better and almost never needed the filter. A local lane is justified only by cost per correct answer, and that is what the v3 design measures (GPU-seconds per correct verdict).
4. **Every local call needs guardrails:** an output cap (`num_predict`), a wall-clock timeout shorter than the gateway lock, at most one retry, cancellation that actually reaches the host, and DNF recorded as an outcome. These are recorded on #1455, and the system tests for them on #2289 (item 3) and #1985.
5. **Pick models by measured behaviour, not by size or tier name.** Both "bigger" and "higher tier" were worse here.

## Caveats

- Eight items, three runs per cell, all from one week of one project's real work.
- Temperature 0 makes local repeats nearly identical, so local run-to-run variance is understated.
- The A6 answer key was corrected from "safe" to "unsafe" after the results came in (verified by execution), so there is no true safe control for the guard. False alarms were measured on two other items instead.
- Cause scores use pattern matching, and are approximate.
- The commercial CLIs do not report which model served a call; those rows show the requested or default model.
- The local inference server was upgraded after all local runs had completed, so reruns may differ.

## What changed

- **#1455:** local models are test-case proposers only; the guardrails are recorded; the v3 research agenda is parked (comment 6732332245).
- **#1985 (v0.7.2):** the local lane must expose the cap, timeout, cancellation and DNF hooks that system test #3 (#2289) drives.
- **#2289:** the system-test catalogue item 3 (local inference lane) is defined.

## Related findings

- `real-data-not-reviewer-diversity-caught-the-bug.md`: the same benchmark, from the input side
- `llms-belong-inside-deterministic-orchestration.md`: generator inside a harness, never the judge
- `agent-confidence-is-uninformative-for-defect-prediction.md`: self-assessment cannot stand in for measured behaviour
- `reviewer-agents-file-confident-non-reproducing-reports.md`: confidently wrong, here as confident "safe" calls
- `cost-gating-autonomous-oversight-loops.md`: the cost argument that justifies a local lane, if anything does
