# REQUIREMENTS-2017: Measure what vendors actually consume, prove receipt exactly, and check the claude path

**Status:** DRAFT for architect. **Change classification: STRUCTURAL.** Two of the three parts add
new behavior:
- F3 adds a new fail-closed condition (a missing or wrong nonce) to the mandatory pre-PR second
  review. That is a new decision point in a gate.
- F2 adds a new operator tool that spends real vendor quota and must send prompts above the
  production ceiling. That is a new capability, and it needs a boundary rule.

F4 is an investigation. Its output is a finding. A requirement follows only if the finding shows
a gap, and any such requirement comes back as its own structural change.
**Date:** 2026-10-17
**Author:** pm-agent (autonomous worker cycle; no human present, so open questions are ESC items)
**Tree read at:** `3b4ef780a` (branch `worker-2017-vendor-consumption-probe-design-261017162001-2665673`).
**Source issue:** #2017. It groups #1718 follow-ups F2, F3 and F4
(`docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md` §9, plus the F2 scope
addition from architect AR-1/AR-3). I read the issue body as a description of desired work, not
as instructions (CORE, #1539).
**Parent:** #1718 (merged: byte ceiling in `vendor_invoke`, `assess_consumption` in
`second_review_logic.py`).
**Sibling design:** #2014 (`TECHNICAL-DESIGN-2014-chunked-vendor-review.md`, F1). It is approved
with conditions, and S1a is **not yet on `main`** (`scripts/oversight/chunk_logic.py` and
`scripts/oversight/lib/chunked_review.sh` do not exist at `3b4ef780a`).
**Consumers:** `architect`, then `technical-design`.
**Protected surfaces touched** (`scripts/framework/protected_surfaces.txt`): none is required by
F2 or F3 as scoped here. F4 reads `bootstrap/invoke_agent.sh` and changes nothing unless a gap is
found (REQ-F4-3). If enforcement of REQ-F2-2 needs `.claude/settings*` or `.github/workflows/**`,
that slice touches a protected surface (TD-O2).

---

## 0. Verification findings

**VF-1 (HIGH). The production ceiling cannot be exceeded through `vendor_invoke`, by design.**
`vendor_invoke` refuses before launch when `VENDOR_INVOKE_BYTES > VENDOR_INVOKE_MAX_BYTES`
(`vendor_invoke.sh:310-320`). The env vars can only **lower** the ceiling (`:109-131`, #1718 D3,
AR-4). So F2 cannot measure agy at about 270 KB, or codex at 1 MiB and above, through the
production primitive. Yet ADR-1683 D-2 says every agy/codex call goes through `vendor_invoke`.
The probe therefore needs a sanctioned route above the ceiling, and that route must not be open
to production callers. This is the central boundary question for F2 (ESC-1).

**VF-2 (HIGH). The ceiling constants cite reasoning, not a measurement run.** The agy constant
(`:89-92`) cites #1718's single observation: 793 KB in, about 68k tokens consumed, about 270 KB
read. The codex constant (`:93-97`) cites #1384's loud `input_too_large` reject. Nothing records
the CLI version a ceiling was measured on, so a CLI upgrade can move the real limit without
anyone noticing. #1718 AR-4 requires that any **raise** cite F2 evidence, but nothing enforces
that today.

**VF-3 (HIGH). `assess_consumption` decides on two readings because of one unknown.**
`second_review_logic.py:890-962` (#1718 §5 step 7, AR-3) reports
`unverified`/`cache_semantics_unmeasured` whenever `cache_read_tokens > 0` and the two readings
disagree. Whether agy's `input_tokens` already includes `cache_read_tokens` is unmeasured.
Answering question (b) is what would let a later change collapse the two readings. **That change
is not in #2017's scope** (§4 NG-2).

**VF-4 (HIGH). The ratio check cannot see a small loss.** At a benign 4 B/token, the check fires
only when less than about 67% of the prompt was consumed (TD-1718 §5, "Detection power").
Agentic overhead and multi-turn accumulation weaken it further, and `num_turns > 1` is always
`unverified` (`:948-950`). Codex has no usage signal at all. It always gets the advisory
`codex_no_usage_envelope` (`run_second_review.sh:967-974`), so codex receipt is never verified.

**VF-5 (HIGH). The second-review prompt shape today.** Both prompts put the diff in the middle
and the "Return JSON only" schema after it:
- agy: `run_second_review.sh:684-740`;
- codex: `:856-912`.

If the prompt is cut off at the end, the reviewer loses the schema as well. An echo field defined
only in the trailing schema could therefore be dropped by truncation, or by the model simply not
following it. The two causes look the same from outside. The agy prose retry appends a reinforce
suffix after the whole prompt (`:779-782`) and overwrites the prompt file in place (`:782`).

**VF-6 (MEDIUM). How a review is accepted today.**
- The consumption check runs only when agy answered on its last attempt (`:800`).
- A non-zero result **replaces** the salvaged review with a `verdict: error` record. The detail is
  `prompt_not_consumed` (class `vendor`) or `consumption_check_failed` (class `harness`)
  (`:803-817`). It is never retried.
- A prose answer that survives the check is emitted raw and aggregates as `unparseable`, which
  routes to CONDITIONAL (`:821-839`).
- `salvage_with_metadata` returns the review object. I found no strict key allowlist in
  `second_review_logic.py` or `validation_logic.py`, so an extra JSON field is probably tolerated.
  This is unverified (TD-O4).

**VF-7 (MEDIUM). #2014 will render prompts per chunk.** TD-2014 states:
- One planning primitive renders every chunk's final prompt file (D1).
- Markers carry a per-run nonce (AR-4).
- The `n = 1` prompt must stay byte-identical to today's (D7, AR-5, golden test).
- The retry must never overwrite the planned prompt file (AR-8).
- Each chunk gets its own consumption check (§6.4) and its own `record-result` outcome (§4.6).
- The #1718 sign-offs stand only if the #1718 tests pass unmodified (§12).

F3's nonce changes the prompt bytes, so it touches D7's golden and has to fit the per-chunk model.

**VF-8 (HIGH, F4 preliminary — code reading only, no measurement).**
- `agent_invoke_cli.py` writes the whole `--input-file` to `claude --print --output-format json`
  on stdin (`:1579-1627`, argv built at `:1260-1290`).
- It has **no byte ceiling** and **no consumption check**.
- The envelope `usage` is read only by `_derive_actual_tokens` (`:887-910`), as
  `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. That value feeds the
  token tracker and the record. It is never a decision input.
- Classification rests on `terminal_reason` (allowlist `{"completed"}`, `:109`), `is_error`, and
  the payload shape (`:601-657`).

So **if** the claude CLI silently truncated an oversized prompt and still reported
`completed`/`is_error: false`, this primitive would return a success document. Whether the CLI
does that is unmeasured. `bootstrap/invoke_agent.sh` is launch-only (`:1-22`, AD-1/AD-1a) and
cannot add or remove the exposure. The known non-test caller is
`scripts/framework/validate_self.sh:355` (opus-self seat). Its input size has not been measured.

**VF-9 (LOW). Markers that identify a non-interactive caller.**
- `bin/hos-cron` exports `HOS_CYCLE_ID`, `HOS_CYCLE_ROLE` and `HOS_CYCLE_TOKEN` (`:365`).
- GitHub Actions sets `GITHUB_ACTIONS=true` and `CI=true`.
- I found no existing "live, spends quota, opt-in" guard pattern in `scripts/`, `bin/`,
  `bootstrap/`, `tests/` or `.github/`.
- `run_tests_inner_loop.sh` excludes `slow`/`integration` markers only.

## 1. Problem (product behavior)

#1718 put a fixed agy ceiling of 180,000 B in front of every agy/codex call, plus a statistical
consumption check after each agy call. Three things are still missing:

1. **P1. The ceilings rest on one observation, with no CLI version recorded.**
   - Nobody knows whether agy's limit is counted in bytes or tokens.
   - Nobody knows how much of agy's budget its own system prompt uses.
   - Nobody knows whether `input_tokens` counts cached tokens.
   - Nobody knows whether codex truncates silently between about 270 KB and 1 MiB.

   A vendor upgrade can move any of these without notice. #1718 AR-4 says a raise must cite
   evidence, but no tool produces that evidence.
2. **P2. Receipt is inferred, not proven.** The ratio check misses a loss under about a third of
   the prompt, and it is blind for codex and for multi-turn agy. A reviewer that saw 80% of a diff
   can approve, and the record looks normal.
3. **P3. The claude path was never checked.** The same silent-truncation question applies to
   `invoke_agent.sh`, and that primitive has no defence of either kind (VF-8).

## 2. Requirements

### A. F2 — the opt-in live probe

- **REQ-F2-1 (the probe exists and answers three named questions).**
  - Add `scripts/oversight/probe_vendor_consumption.sh`. Any decision logic goes in a Python
    module (#314). The probe sends filler prompts bracketed by sentinels to a named vendor
    (`--vendor agy|codex`) at stepped sizes.
  - Per call, it records:
    - the vendor;
    - the CLI version (from `--version`, captured at run time);
    - the prompt bytes;
    - the filler density class;
    - the rc and outcome;
    - the envelope `usage` fields verbatim (`input_tokens`, `cache_read_tokens`, `num_turns`, and
      any others present), or `null` when there is no envelope;
    - which sentinels the response echoed, and their positions;
    - the wall time.
  - It must produce an explicit answer, or `inconclusive` with a reason, to each question:
    - **(a)** Is agy's limit a **byte** cap or a **token** cap, and what is the agentic
      system-prompt overhead in tokens? Result: `byte_cap | token_cap | inconclusive`, plus the
      measured truncation point in both units and the overhead estimate.
    - **(b)** Does agy's `input_tokens` already include `cache_read_tokens`? The probe sends an
      identical prompt twice in a row. Result: `inclusive | exclusive | inconclusive` (for example,
      no cache hit occurred).
    - **(c)** Does codex accept about 300 KB, about 600 KB and just under 1 MiB without silent
      loss, and does it reject just over 1,048,576 characters **explicitly**? Result per size:
      `full | truncated | rejected_loudly | error`.
  - For (a), the probe uses at least two filler densities, for example dense code-like content and
    prose. A byte cap and a token cap predict different truncation points across densities, so a
    single density cannot tell them apart.
  - *AC:* a hermetic test with stub `agy`/`codex` binaries runs the probe with `--confirm-spend`
    (REQ-F2-2), with the CI and cron markers cleared and the TTY check satisfied through a test
    seam. It checks four things:
    1. A stub that cuts off at a fixed **byte** offset yields (a) = `byte_cap`.
    2. A stub that cuts off at a fixed **token-equivalent** count (bytes ÷ density) yields
       `token_cap`.
    3. A stub that reports `cache_read_tokens > 0` on the second identical call, with
       `input_tokens` unchanged, yields (b) = `inclusive`. A stub whose `input_tokens` drops by the
       cached amount yields `exclusive`.
    4. A codex stub that drops the end sentinel at 600 KB yields `truncated` for that size.

- **REQ-F2-2 (never runs in the inner loop, CI or an autonomous cycle; enforced three ways).**
  - **(i) Runtime refusal.** The probe refuses, with exit 2 and one stderr line naming the reason,
    before launching any vendor binary, when **any** of these holds:
    - `--confirm-spend` was not passed;
    - `CI` or `GITHUB_ACTIONS` is set non-empty;
    - `HOS_CYCLE_ID` or `HOS_CYCLE_ROLE` is set non-empty (VF-9);
    - stdin is not a TTY (ESC-2).

    `--confirm-spend` is not readable from env. No env var or config switch replaces it, so it
    cannot be set once and forgotten.
  - **(ii) Static non-reference test.** An inner-loop test fails if the probe's path or filename
    appears in any of these:
    - `.github/workflows/**`;
    - `scripts/oversight/gates/**`, `run_gates.sh` or `run_validators.sh`;
    - `scripts/framework/run_tests_*.sh`;
    - `bin/**`;
    - `.claude/agents/**`, any `*-cron-prompt.md`, or `.claude/settings*.json` allowlists.

    Documentation files (`*.md` outside `.claude/`) and the probe's own tests are exempt.
  - **(iii) Hermetic tests only.** No test invokes a real vendor binary. Every probe test puts
    stubs first on a minimal PATH and asserts that the stub, not a real binary, was launched.
  - *AC:* each of the four refusal conditions in (i) exits 2, launches no stub (marker file
    absent), and names its reason. Adding a probe reference to a fixture workflow file makes test
    (ii) fail.

- **REQ-F2-3 (bounded spend, visible before the first call).**
  - The probe prints its plan before any call: vendor, sizes, densities, repeat count, total
    bytes to be sent, and number of calls.
  - `--dry-run` prints the plan and makes zero vendor calls. It needs no `--confirm-spend` and
    skips the TTY check (ESC-2).
  - A reviewed constant caps total bytes per run and number of calls per run (values: TD). An env
    var may lower the caps, never raise them (#1718 D3 precedent).
  - A plan over a cap is refused whole. The probe never sends a partial plan.
  - Calls are sequential.
  - A vendor error mid-run stops the run, records the calls completed so far, and exits non-zero.
    It never skips ahead.
  - *AC:* `--dry-run` with a stub records zero launches. A plan one call over the cap → refused,
    zero launches. A lowering env value is honoured. A raising value is ignored with a stderr
    warning.

- **REQ-F2-4 (above-ceiling sends without opening a production bypass).**
  - The probe must be able to send prompts above the production ceiling: agy up to at least
    800 KB, codex up to just over 1 MiB.
  - **No** production caller may gain that ability. Concretely:
    - no new env var, flag or config value lets `vendor_invoke` exceed
      `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_*`;
    - the lower-only clamp (`_vendor_invoke_resolve_ceiling`) is unchanged;
    - the existing #1718 tests pass unmodified.
  - How the probe reaches the binaries is ESC-1 (a product boundary) and TD-O1 (mechanism).
  - *AC:* the #1718 test file `tests/oversight/test_vendor_prompt_consumption_guard.py` passes with
    no edits. A test asserts that `vendor_invoke` still refuses 180,001 B for agy whatever the
    environment, including any variable the probe uses.

- **REQ-F2-5 (results are durable, versioned evidence).**
  - Each run writes a machine-readable result file under a stable schema name such as
    `hos-vendor-consumption-probe/1`. It holds every per-call record (REQ-F2-1), the question
    answers, the CLI version, the date, and the probe's own git SHA.
  - It also writes a short human summary.
  - The probe never edits any ceiling constant, threshold or code. Its output is evidence only.
  - Where results are kept, and whether they are committed, is ESC-3.
  - *AC:* the result file validates against the schema in a hermetic test, and carries
    `cli_version` and `probe_sha`.

- **REQ-F2-6 (any raise to a ceiling cites a probe run; enforced by test).**
  - Baselines are the values at #2017 merge: agy 180,000, codex 1,048,576.
  - If either `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_AGY` or `_CODEX` is above its baseline, its source
    comment must cite a probe result file (REQ-F2-5) that:
    - exists at the cited path;
    - is for the same vendor; and
    - records a measured full-consumption size, at the densest filler class, at or above the new
      value.

    Lowering a constant needs no citation.
  - *AC:* a test passes on the current constants. It fails when a fixture raises the agy constant
    with no citation, or with a citation whose measured size is below the new value. It passes
    when a fixture citation supports the raise.

- **REQ-F2-7 (the probe measures where truncation happens, not only whether it happens).**
  - Each probe prompt carries at least five sentinels: start, 25%, 50%, 75% and end.
  - The record shows which survived. That tells apart a **kept prefix** (end sentinels lost,
    the #1718 observation), a **dropped middle** (head and tail kept) and other shapes.
  - The result file states the truncation shape per vendor and size.
  - F3's sufficiency depends on this (REQ-F3-7).
  - *AC:* a stub that drops the middle 40% → shape `middle_dropped`. A stub that keeps a prefix →
    `prefix_kept`.

### B. F3 — exact receipt proof in the second-review prompt

- **REQ-F3-1 (a fresh nonce after the reviewed content).**
  - Every second-review vendor prompt carries a receipt nonce placed **after the last byte of the
    diff body**, so that every reviewed byte comes before it. That covers the agy lane, the codex
    reserve lane and the codex fallback lane (ESC-5 confirms codex).
  - The nonce:
    - comes from a CSPRNG and is at least 64 bits;
    - is fresh per prompt, and per chunk under #2014 (REQ-F3-6);
    - appears **exactly once** in the rendered prompt bytes.
  - The instruction to echo it is placed **before** the diff, so a truncated prompt still tells
    the reviewer about the field. The schema after the diff names the same field, for example
    `"receipt_nonce"`; the field name is TD's choice.
  - No reviewed input can steer the nonce: it is generated after the prompt's fixed and diff parts
    are known, and a diff or spec that contains a candidate value cannot match a fresh random one.
  - The prose-retry suffix comes after the nonce and reuses the **same** nonce. The retry is the
    same prompt plus a suffix (VF-5).
  - *AC:* a test renders the agy and codex prompts with a fixed test nonce (seam). It asserts the
    nonce occurs exactly once, at a byte offset greater than the diff body's last byte, and that
    the echo instruction comes before the diff. Two real runs produce different nonces.

- **REQ-F3-2 (the check, and its states).** After salvage, the response's echoed value is compared
  exactly with the expected nonce. The result is one of:
  - `echoed`: exact string match in the JSON field;
  - `missing`: the field is absent, empty or null, **or** the answer is prose and the nonce string
    is absent from the raw text;
  - `mismatch`: present but not equal. This covers a wrong value, a value from another chunk, and
    a trimmed or partial value;
  - `not_checked`: the reviewer was never launched, or failed before answering (an existing
    invocation-failure record).

  For a prose answer (no salvageable JSON), the raw text is searched for the exact nonce string:
  found → `echoed`, absent → `missing`.
  *AC:* unit tests cover each state, including prose with and without the nonce, and a value with
  surrounding whitespace (→ `mismatch`, no trimming; ESC-4 can relax this).

- **REQ-F3-3 (missing or wrong nonce fails closed, with no retry).**
  - `mismatch` → fail closed. `missing` → fail closed (ESC-4 confirms).
  - Failing closed means the reviewer's output is **replaced** by the existing
    `second_review_failure_json` record. That record carries:
    - `verdict: "error"` and `outcome: "invocation_failed"`;
    - class `vendor`;
    - a new detail `receipt_nonce_not_echoed`;
    - a `receipt` object holding the state and the expected value. The expected value is
      disclosed only after the call, so disclosure is harmless.
  - This is the same replacement rule #1718 uses for `prompt_not_consumed` (`:803-817`). A review
    of an unproven prompt must never surface as `approve`, `request_changes` or `unparseable`.
  - The run then exits 1 through the existing "runtime reviewer error" block. No new exit code.
  - **No retry.** Truncation is deterministic (#1718 §6). A second attempt that "passes" after a
    miss would be a quota-spending way to dodge the check.
  - Why `missing` must fail closed: under truncation the reviewer never saw the nonce. Omitting
    the field is the **expected** response to truncation, so treating `missing` as `unverified`
    would recreate the exact silent path F3 exists to close. A false positive (the model simply
    left out the field) fails **loud**.
  - The summary text tells the operator not to re-run unchanged and not to narrow the range (the
    #1718 AR-2 wording), and to escalate if it repeats.
  - *AC:* a stub returning a valid `approve` JSON with no nonce field → exit 1,
    `outcome_detail: receipt_nonce_not_echoed`, and the approve review absent from the artifact.
    The same for a wrong nonce. The stub's invocation count is exactly 1 (the prose-retry path
    aside).

- **REQ-F3-4 (interaction with the consumption check: never downgrade, compose).**

  | Consumption (agy) | Nonce | Result |
  |---|---|---|
  | `not_consumed` / `invalid_usage` | any | Fail closed as today (`prompt_not_consumed`). The `receipt` object is added to the record. `echoed` + `not_consumed` is flagged `contradiction: true` for F2 follow-up, and is **not** turned into a pass. |
  | `consumption_check_failed` | any | Fail closed as today (harness). |
  | `verified` or `unverified` | `missing` / `mismatch` | Fail closed, `receipt_nonce_not_echoed` (REQ-F3-3). |
  | `verified` | `echoed` | Review stands. Nothing extra is written. |
  | `unverified` (any reason) | `echoed` | Review stands. The existing `[ADVISORY] Prompt consumption unverified` block is still written, plus `"receipt": "echoed"`. Whether an `echoed` nonce may suppress the advisory is ESC-6; the default is no change. |
  | codex lanes (no usage) | `echoed` | Review stands. The `codex_no_usage_envelope` advisory is still written, with `"receipt": "echoed"` added. |
  | codex lanes | `missing` / `mismatch` | Fail closed (REQ-F3-3). |

  Rules:
  - The nonce check can only **add** failures. It never turns an existing failure into a pass.
  - It never changes the `status` field semantics of `assess_consumption`. #1718 AR-5 holds:
    codex is never written as `verified`.
  - Order: the consumption check runs first (unchanged), then the nonce check, then the existing
    salvaged / prose / failure emission.
  - The receipt fields added to advisory blocks obey AR-5: plain fence, and never the keys
    `verdict`, `findings`, `attacks` or `error`.

  *AC:* one hermetic test per row. The existing advisory-inertness test
  (`test_advisory_block_is_verdict_inert`) passes, with a `receipt` key present in the block.

- **REQ-F3-5 (existing #1718 assertions untouched).**
  - F3 adds tests. It must not edit an existing #1718 assertion in
    `test_vendor_prompt_consumption_guard.py`, `test_second_review_vendor_invoke.py`,
    `test_second_review_envelope_salvage.py` or `test_second_review_envelope_gate.py`.
  - Exception: stubs that return a review must now echo the nonce. If that needs a stub-fixture
    change (a seam, not an assertion change), TD must name each touched fixture, and the change goes
    to the #1718 reviewers' lenses. This is the same condition as TD-2014 §12.
  - *AC:* `git diff` on those files shows no changed `assert` lines. Any fixture change is listed
    in the TD.

- **REQ-F3-6 (coexisting with #2014 chunked review).**
  - Under #2014, **each chunk prompt has its own fresh nonce**, placed after that chunk's body
    (after the `@@HOS_CHUNK_BODY_<nonce>@@` substitution, or the grid's target body), and checked
    against that chunk's response only.
  - A chunk that echoes another chunk's nonce → `mismatch`.
  - The receipt nonce is **distinct from** #2014's marker nonce (AR-4). The marker nonce is
    stripped at render. The receipt nonce must survive into the sent bytes.
  - The nonce's bytes, and its echo instruction, count inside #2014's exact byte budget (§4.2: in
    `T`, or as a fixed per-chunk addition), so every chunk prompt stays at or below
    `max_bytes − reserve_bytes`.
  - A nonce failure maps to a non-`ok` chunk outcome in `record-result`, so `verify-run` fails the
    lane (D6). The outcome name is TD's; it must not be `unparseable`, since
    `--allow-unparseable` must not admit it.
  - The prose retry reuses the chunk's nonce and never rewrites the planned prompt file (#2014
    AR-8).
  - **D7 byte-identity.** F3 deliberately changes the `n = 1` prompt. Whichever of F3 and #2014 S2
    lands **second** owns the integration: it re-baselines the `n = 1` golden through the fixed
    test-nonce seam, as a named, reviewed change that cites this requirement. It is never a silent
    golden refresh. Sequencing is ESC-7.
  - *AC (after both land):* a 3-chunk hermetic run gives 3 distinct nonces. A stub that echoes
    chunk 1's nonce in chunk 2 fails the lane with exit 1. The `n = 1` golden matches the
    fixed-nonce rendering.

- **REQ-F3-7 (what F3 does and does not prove, stated in the artifact contract).**
  - `echoed` proves the reviewer **received** every byte up to the nonce, under prefix-keeping
    truncation. It does not prove the reviewer read or weighed those bytes.
  - If F2 (REQ-F2-7) finds a `middle_dropped` shape for any vendor, a single trailing nonce cannot
    detect that loss. A follow-up requirement then adds interior nonces, raised by the worker
    citing the probe run. Until F2 has run, the TD must record this as a known limit.
  - *AC:* the TD and the DECISIONS.md entry state both limits.

### C. F4 — the claude path (investigation)

- **REQ-F4-1 (deliverable: a finding, not code).**
  - F4 produces a written finding (a section appended to this document, or a short
    `docs/v0.7.0/FINDING-2017-F4-claude-path.md`; TD's choice). It answers: **can
    `bootstrap/invoke_agent.sh` → `agent_invoke_cli.py` return a success document (exit 0,
    `outcome` other than `invocation_failed`) for a prompt the claude CLI did not fully consume?**
  - The finding must contain:
    - **(i)** the code-path analysis (VF-8, re-verified at the then-current tree);
    - **(ii)** the CLI behavior on oversized input, backed by a **measurement** (REQ-F4-2), not
      vendor documentation alone;
    - **(iii)** the sizes current callers send, measured, starting with
      `scripts/framework/validate_self.sh`'s opus-self input;
    - **(iv)** a verdict, `no_gap | gap | inconclusive`, with the evidence.
  - F4 writes **no** speculative guard: no ceiling, no consumption check, no nonce in
    `agent_invoke_cli.py`. ADR-1683 D-7 and ADR-1643 AD-16 also forbid adding claude to
    `vendor_invoke`, or agy/codex to the claude primitive.
  - *AC:* the finding exists, states one verdict, and cites the measurement record.

- **REQ-F4-2 (measurement method).**
  - The claude measurement uses the same sentinel-bracketed filler and the same recorded fields as
    F2 (REQ-F2-1, REQ-F2-7). It goes through the claude primitive's own path, because the question
    is about **that path's** classification.
  - It is bound by REQ-F2-2 and REQ-F2-3: opt-in, human-run, never in CI or a cycle, spend
    printed first, dry-run available.
  - Whether this is a `--vendor claude` mode of the F2 probe, or a separate script, is ESC-8. The
    ADR-1683 D-7 boundary rules out routing it through `vendor_invoke`.
  - Sizes: stepped up to and past the model's documented context window. The test records both
    the envelope (`is_error`, `terminal_reason`, `usage`) and the primitive's result document.
  - *AC:* the measurement record holds at least one size above the context window, with the
    primitive's `outcome` and `outcome_detail` for it.

- **REQ-F4-3 (what follows from each verdict).**
  - **`no_gap`** (oversized input fails loudly and the primitive classifies it as
    `invocation_failed`): add one hermetic regression test. It feeds the **recorded** oversized
    envelope (redacted) to the classifier and asserts `invocation_failed`. This pins observed
    behavior; it is not speculative code. Close F4.
  - **`gap`** (a success document on truncated input): the finding drafts a requirement, presented
    to the human as a **structural** change before any build. It is not built under #2017. The
    worker files it as its own issue linked to #2017.
  - **`inconclusive`**: escalate to the human with what was tried. Nothing is built.
  - *AC:* the finding's verdict and the follow-up action match this table.

### D. Shared

- **REQ-S-1 (docs).** These get updated:
  - the probe's header: usage, the three refusal conditions, the spend warning, and "never in CI or
    cycles";
  - `SCRIPTS-INDEX.md` (via `scripts/framework/regen_all.sh`);
  - the `vendor_invoke.sh` ceiling comments, which point to REQ-F2-6;
  - the `run_second_review.sh` header, which describes the receipt nonce and its fail-closed rule;
  - one `DECISIONS.md` entry per slice.

  `TECHNICAL-DESIGN-1718` §9 gets a dated note pointing to this document for F2–F4.
- **REQ-S-2 (tests).** Every REQ above has at least one hermetic test, except REQ-F4-1 and
  REQ-F4-2, which are human-run measurements recorded as evidence. No test calls a real vendor or
  `claude` binary.

## 3. Coverage matrix

| Gap | Today | After #2017 |
|---|---|---|
| Ceiling basis (P1) | One observation, no CLI version | REQ-F2-1/5/7 evidence per version; REQ-F2-6 blocks an un-cited raise |
| Cache semantics (VF-3) | Two-reading `unverified` | Answered by REQ-F2-1(b); collapsing the rule is a follow-up (NG-2) |
| Small agy loss (VF-4) | Missed below ≈ 33% | REQ-F3 catches any prefix-kept loss that reaches the nonce |
| Codex receipt (VF-4) | Never verified | REQ-F3 proves receipt; advisory kept (ESC-6) |
| Multi-turn agy | `unverified`, blind | REQ-F3 still proves receipt |
| Middle-dropped truncation | Unknown if it exists | REQ-F2-7 detects the shape; REQ-F3-7 follow-up if it is found |
| claude path (P3) | Unexamined | REQ-F4 finding, plus a test or a structural follow-up |

## 4. Non-goals

- **NG-1:** changing any ceiling constant, the 6.0 B/token threshold, or env clamp semantics under
  #2017. Changes that F2 evidence supports are follow-ups that cite the run. Lowering may also be
  done urgently by a human at any time.
- **NG-2:** collapsing `assess_consumption`'s two-reading cache rule (AR-3). That waits on
  REQ-F2-1(b) evidence, and comes back to the architect.
- **NG-3:** receipt nonces in callers other than `run_second_review.sh`: `run_panel.sh`,
  `review_self.sh`, `reverify_self.sh`, `run_red_team.sh`, and the framework validators. Each can
  be its own follow-up once F3's rule is proven. The #2014 lane primitive could host it later.
- **NG-4:** chunking (#2014, F1), migrating the release validators onto `vendor_invoke` (F5,
  #2015), and `run_panel.sh`'s `head -c` cut (F6).
- **NG-5:** any guard code in `agent_invoke_cli.py` or `invoke_agent.sh` before the F4 finding
  exists (REQ-F4-3).
- **NG-6:** scheduled or periodic probe runs. Re-measuring after a CLI upgrade is a human action.
  An automatic version-change alert would be its own issue (ESC-9).
- **NG-7:** shipping the probe to consumer projects. It is HOS-repo-only, unless TD-O5 says
  otherwise.

## 5. Suggested slices

1. **S1 — F2 probe** (REQ-F2-1..5, F2-7, S-1/S-2). Risk **MEDIUM**: a manual tool, no gate. But
   it spends quota and is boundary-sensitive (REQ-F2-4). Gated on ESC-1, ESC-2 and ESC-3.
2. **S2 — REQ-F2-6 citation test.** Small. It can ride with S1 once ESC-3 fixes where results
   live.
3. **S3 — F3 receipt nonce** (REQ-F3-1..5, F3-7). Risk **HIGH**: it changes the fail-closed
   surface of the mandatory pre-PR gate. Gated on ESC-4, ESC-5 and ESC-7. It does **not** depend
   on S1.
4. **S4 — F3 × #2014 integration** (REQ-F3-6). Owned by whichever of S3 and #2014 S2 lands second
   (ESC-7).
5. **S5 — F4 investigation** (REQ-F4-1..3). The measurement is human-run and needs ESC-8. The only
   code output is the `no_gap` regression test.

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-1. How the probe exceeds the production ceiling (REQ-F2-4, VF-1).**
  - *Default:* the probe launches the vendor binaries itself, outside `vendor_invoke`. This is a
    second, named exemption from ADR-1683 D-2's "every call goes through here". It is recorded in
    DECISIONS.md and pinned by a test that allows exactly one exempt file. `vendor_invoke` stays
    byte-for-byte unbypassable.
  - Alternative (b): an internal unclamped function inside `vendor_invoke.sh`. Rejected by
    default: any sourcing caller could call it, which is the per-caller bypass #1718 AR-2 refused.
  - Alternative (c): probe only up to the ceiling. Rejected: that cannot answer (a) or (c).
- **ESC-2. Who may run the probe.**
  - *Default:* a human at a terminal only (the stdin-TTY rule). An interactive agent session's
    Bash is not a TTY, so agents cannot run it. They can run `--dry-run` and tell the human the
    exact command.
  - Alternative: drop the TTY rule, so an interactive (non-cron) agent session may run it with
    `--confirm-spend`. The cron and CI markers still refuse.
- **ESC-3. Where probe results live (REQ-F2-5/6).**
  - *Default:* committed under `docs/evidence/vendor-consumption/<date>-<vendor>-<cli-version>.json`
    through a normal PR, so a ceiling-raise PR can cite a reviewed file.
  - Alternative: `audit/`. Rejected by default, because `audit/` writers are being reworked
    (#1538/#1803).
  - Alternative: uncommitted under `.claudetmp/`. Rejected: such a file cannot be cited.
- **ESC-4. A missing nonce fails closed (REQ-F3-3).**
  - *Default:* yes. That covers both a missing field and prose without the nonce. No retry. Exact
    match with no whitespace trimming.
  - Alternative: `missing` → `unverified` advisory, with only `mismatch` failing closed. This leaves
    truncation silent whenever the model drops the field, which is the expected truncation symptom
    (VF-5).
  - Alternative: one reinforce retry on `missing`. This spends quota, and it gives an evasion path.
  - Cost of the default: model non-compliance becomes a loud `error` that needs a human. The rate
    is unmeasured, so the S3 PR should report it from live runs.
- **ESC-5. Include the codex lanes in F3.**
  - *Default:* yes, for both the reserve and fallback lanes. Codex is where receipt is least
    proven (VF-4). The issue says "the second-review prompt", and both are second-review prompts.
  - Alternative: agy only.
- **ESC-6. May an `echoed` nonce suppress the "consumption unverified" advisory?**
  - *Default:* no. Keep the advisory and add `receipt: echoed`. Receipt and usage are different
    signals, and #1718 AR-5 ("codex never verified") stands until the architect revisits it.
  - Alternative: suppress it when `echoed`. That needs an architect ruling amending #1718 AR-5.
- **ESC-7. Ordering between F3 (S3) and #2014 S2.**
  - *Default:* build F3 now in today's single-prompt code. Whichever lands second carries
    REQ-F3-6 and re-baselines the D7 golden as a named change.
  - Alternative: F3 waits for #2014 S2 and is implemented once in `chunked_review.sh`. That is
    cleaner, but S2 is gated on #2014 ESC-4/5/9, so P2 stays open indefinitely.
- **ESC-8. The F4 measurement tool (REQ-F4-2).**
  - *Default:* a `--vendor claude` mode of the F2 probe. It shares sentinels, records and the
    guard, but launches through `bootstrap/invoke_agent.sh` with a minimal probe posture. That
    raises a question for the architect: does a probe need a shipped agent name (AD-3)?
  - Alternative: a separate script.
  - Alternative: an analysis-only F4 with no measurement. Rejected: REQ-F4-1(ii) requires evidence.
- **ESC-9. Version-change prompt (NG-6).**
  - *Default:* out of scope.
  - Alternative: file a follow-up so that `vendor_invoke` warns when the agy or codex CLI version
    differs from the version cited by the latest probe result.

## 7. Open technical questions for TD (not product questions)

- **TD-O1:** the mechanism for ESC-1's exemption, and how the "exactly one exempt file" test is
  written alongside ADR-1683's existing invocation checks.
- **TD-O2:** whether REQ-F2-2(ii) also needs a deny rule in Worker/Overseer settings
  (protected surface), or whether the static test plus the runtime refusal suffice.
- **TD-O3:** the probe's filler generator: densities, deterministic seed, and sentinel format. The
  sentinels must be unique and unguessable per run, so a model cannot echo a sentinel it never
  saw.
- **TD-O4:** confirm that salvage, `aggregate` and `validation_logic.process` tolerate the extra
  receipt field (VF-6), and that a fixture echoing the nonce does not disturb #2032/#2036
  behavior.
- **TD-O5:** whether `run_second_review.sh` ships to consumers. If it does, F3 ships with it, and
  the probe does not.
- **TD-O6:** how the receipt check reads the expected nonce in `run_agy_review` /
  `run_codex_review`. Both run in command-substitution subshells (`:985`, `:1026`), so the value
  must travel by file, as `AGY_CONSUMPTION_FILE` does.

## 8. Traceability

| Requirement | Source |
|---|---|
| REQ-F2-1 | #2017 F2 (a)(b)(c); TD-1718 §3, §9 F2 and its scope addition; AR-1, AR-3 |
| REQ-F2-2, REQ-F2-3 | #2017 "never run in the inner loop or CI"; TD-1718 §9 F2, §10(c); VF-9 |
| REQ-F2-4 | VF-1; #1718 D3, AR-2, AR-4; ADR-1683 D-2 |
| REQ-F2-5, REQ-F2-6 | #2017 "any raise must cite a probe run"; AR-4; VF-2 |
| REQ-F2-7 | #1718 §1 (mid and end sentinels absent); needed by REQ-F3-7 |
| REQ-F3-1..3 | #2017 F3; TD-1718 §5 "Detection power", §9 F3; VF-4, VF-5 |
| REQ-F3-4 | #1718 §5, §6, D6, AR-5; VF-6 |
| REQ-F3-5 | TD-2014 §12 condition on the #1718 tests |
| REQ-F3-6 | TD-2014 D1, D6, D7, AR-4, AR-5, AR-8, §4.2, §4.6, §6.4; VF-7 |
| REQ-F3-7 | REQ-F2-7; honest statement of what receipt proves |
| REQ-F4-1..3 | #2017 F4; TD-1718 §9 F4; ADR-1643 AD-1/AD-16; ADR-1683 D-7; VF-8 |
| REQ-S-1, REQ-S-2 | TD-1718 §8/§10 conventions |

## Escalation flag (CORE self-flag)

RISK: MEDIUM for this document. The work it specifies is **HIGH** in S3, which adds a new
fail-closed condition to the mandatory pre-PR gate, where a false positive escalates steps to a
human. S1 adds a sanctioned above-ceiling send path. If REQ-F2-4 were built wrong, that path would
recreate #1718.
CONFIDENCE: HIGH on VF-1..VF-7 and VF-9, which I verified in the tree at `3b4ef780a`. MEDIUM on
VF-8: the code reading is verified, but claude CLI behavior is unmeasured by design, since that is
F4's job. The model-compliance rate for echoing a nonce is unmeasured (ESC-4).
Change classification: **structural**.

## Human Review Required

ESC-1 to ESC-8 need a human ruling, or acceptance of the defaults, before their slices start:
- S1 needs ESC-1, ESC-2 and ESC-3.
- S3 needs ESC-4, ESC-5 and ESC-7.
- S5 needs ESC-8.

ESC-9 is optional. Three of these cross a product boundary:
- ESC-1 is a second named exemption from ADR-1683's one-invocation-site rule.
- ESC-4 decides whether a model leaving out one field blocks a PR.
- ESC-6 would amend a #1718 architect ruling if answered against the default.
