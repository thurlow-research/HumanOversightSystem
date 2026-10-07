# Technical Design — #1718 vendor prompt consumption guard

Status: APPROVED-WITH-CHANGES by architect (round 1, 2026-10-07). The changes are applied in the body below and listed
in "Architect review" at the end. **Merge is gated on human product-boundary clearance (AR-9).**
Issue: #1718 (priority:critical) · Related: ADR-1683 (vendor_invoke), #1737 (envelope salvage/metadata), #314 (decision logic in Python)
Change class: **additive** (new refusal path + new gate; no existing contract field removed or renamed)

## 1. Problem (restated as a contract gap)

`vendor_invoke` (scripts/oversight/lib/vendor_invoke.sh) reports `ok` when rc=0 and stdout is
non-empty. Nothing checks how much of the prompt the model actually received. Measured on
agy 1.2.3: a 793 KB prompt was silently truncated (envelope `usage.input_tokens` ≈ 68k, mid and
end sentinels absent) with `status: SUCCESS`. The observed agy ceiling is ≈ 68k input tokens ≈ 270 KB
for that content (≈ 3.97 B/token). `VENDOR_INVOKE_BYTES` measures bytes *written*, not *consumed*.

Measured exposure today (not hypothetical): `scripts/review_self.sh` builds a ≈ 417 KB corpus and
sends it to agy, so every self-review run since agy 1.2.x has reviewed roughly the first 65% of
its corpus and reported success.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | A per-vendor **byte ceiling enforced inside `vendor_invoke`**, checked before launch. Every caller inherits it. | One invocation site (ADR-1683 D-2). A caller cannot forget it. |
| D2 | Defaults: **agy 180,000 B**, **codex 1,048,576 B** (architect AR-1; was 180,000). | See §3. |
| D3 | Ceilings may be **lowered only** via env; never raised. Raising requires editing the reviewed constant. | Same precedent as #985 (threshold env may only strengthen). A raised ceiling recreates #1718. |
| D4 | A **consumption check** in `second_review_logic.py` (Python, unit-testable per #314), called from `run_agy_review` after salvage. Fails closed on a material shortfall. | The agy envelope `usage` is only available where the caller passes `--output-format json`, and only `run_second_review.sh` does that and already captures it (#1737). `vendor_invoke` stays flag-agnostic (it owns base command + stdin only). |
| D5 | Oversized input policy: **refuse and escalate** (fail closed). Chunking is deferred to a named follow-up (§9). | Fits one slice; no new aggregation semantics. `run_panel.sh` already chunks at 60 KB, so it is unaffected in practice. |
| D6 | Missing `usage` → status `unverified`: **does not fail**, but is recorded visibly as an advisory block. Never written as `verified`. | codex and the agy prose path have never had usage. Failing them would break every codex run. The byte ceiling is the bound on those paths. |

## 3. Ceiling justification

- agy's limit is in **tokens** (≈ 68k), so the byte ceiling must hold for **dense** content.
  At a worst-case benign density of 3.0 B/token (dense code/diffs), 68k tokens ≈ 204 KB.
  180,000 B ≈ 60k tokens at 3.0 B/token: about 12% under the observed token ceiling, and 33% under
  the observed 270 KB byte figure. A 48,249-token chunk was consumed whole, which is consistent
  with this ceiling.
- codex (architect AR-1): no consumption signal exists in the forms used here. `codex exec` is
  called with no flags, and every caller treats stdout as plain text. One limit **has** been
  measured, and it is loud rather than silent: codex's `turn/start` API rejects any input over
  1,048,576 characters with an explicit `input_too_large` error in about 3 s (#1384, recorded at
  `scripts/framework/validate_agents.sh` `CODEX_MAX_INPUT_CHARS`). The default ceiling is set to
  **1,048,576 bytes**. Bytes are always ≥ characters, so this never admits a prompt codex would
  reject on length. It refuses early only for multibyte-heavy content, which is the safe
  direction. This ceiling is a **deterministic-classification bound** (`harness/prompt_too_large`
  instead of `vendor/vendor_nonzero_exit`, and no wasted call). It is **not** a truncation bound.
  Below it, codex consumption is **unverified** and recorded as such (§6). A 180,000 B codex
  ceiling was rejected: it would deterministically break codex lanes that work today and sit
  under codex's measured loud cap, and there is no evidence of codex truncation (§7). It would
  turn a hypothetical defect into a certain outage. The earlier "fallback parity" argument does
  not hold: the codex fallback fires only when agy is *unavailable*, never when agy refuses, and
  the codex second-review prompt (diff plus about 1.5 KB) is strictly smaller than the agy prompt
  (diff plus spec plus digest plus about 3 KB). Whether codex's *token* context overflows silently
  between about 270 KB and 1 MiB is unmeasured. F2 must probe it.
- Agentic system-prompt overhead and multi-turn accumulation only **increase** `input_tokens`.
  That is the safe direction for D4's false-positive rate. **Correction (architect AR-3):** the
  overhead does *reduce* D2's margin if agy's limit is on total input tokens. The overhead
  shares the ≈ 68k budget, so 180,000 B at 3.0 B/token fits only if the overhead is ≤ ≈ 8k
  tokens. The measured data (67,117 and 68,359 input tokens on two ≈ 800 KB prompts, ≈ 273 KB
  consumed) also fits a **byte** cap on agy's stdin read (for example 256 KiB = 262,144 B). Under
  that reading, 180,000 B is safe at any density. 180,000 is kept because no data supports a
  tighter value, and tightening it widens the §7 outage. F2 must separate the two hypotheses
  (byte versus token cap) and measure the overhead.

## 4. Contract — `vendor_invoke` (scripts/oversight/lib/vendor_invoke.sh)

New constants in the library (read-only defaults):
`_VENDOR_INVOKE_DEFAULT_MAX_BYTES_AGY=180000`, `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_CODEX=1048576`.
Each constant carries a comment citing its evidence: #1718 for agy, and #1384 / `CODEX_MAX_INPUT_CHARS` for codex.

New env inputs (lower-only):
`VENDOR_INVOKE_MAX_BYTES_AGY`, `VENDOR_INVOKE_MAX_BYTES_CODEX`.
- Effective ceiling = `min(default, env)` when env is a positive decimal integer (`^[1-9][0-9]*$`).
- An env value that is unset or empty → default, silently.
- An env value that is malformed, zero, or larger than the default → default kept, plus a single
  stderr warning (`vendor_invoke: ignoring VENDOR_INVOKE_MAX_BYTES_AGY=<v> — may only lower the
  <default>-byte ceiling`). Falling back to the default is the stronger setting, so ignoring the
  bad value is safe.

New public function `vendor_invoke_max_bytes <vendor>`. It prints the effective ceiling on
stdout and is the **only** implementation of the clamp; `vendor_invoke` calls it internally.
For an unknown vendor it prints nothing and returns 1.

New output global, set on **every** call: `VENDOR_INVOKE_MAX_BYTES`. This is the effective ceiling
for the vendor, or `""` for `unknown_vendor`. It is added to the header's list of public globals
(six globals after this change).

New `VENDOR_INVOKE_DETAIL` value: **`prompt_too_large`**, class **`harness`**.
- Order of checks: argv guard → vendor resolution (`unknown_vendor`) → **ceiling check** →
  `command -v` → launch. Placing the ceiling before `command -v` means refusal is deterministic
  and testable without a binary, and the binary is **never launched**.
- Condition: `VENDOR_INVOKE_BYTES > VENDOR_INVOKE_MAX_BYTES` (strictly greater; equal passes).
- On refusal: `VENDOR_INVOKE_RC=""`, `CLASS=harness`, `DETAIL=prompt_too_large`, return 1.
  `VENDOR_INVOKE_STDERR` is set to the same single line that is echoed to stderr:
  `vendor_invoke: refused — prompt is <B> bytes, over the <C>-byte <vendor> ceiling (#1718: agy
  silently truncates oversized input). Narrow the input; do not re-run as-is.`
  When the effective ceiling came from a lowering env var, the line also names it, for example
  `(lowered by VENDOR_INVOKE_MAX_BYTES_AGY)`. An operator must be able to tell a reviewed
  constant from a local override (architect AR-4).
- Return contract is unchanged otherwise: 0 iff launched, rc=0, and stdout non-empty.

Why `harness`: the vendor is fine. This repo assembled a prompt the vendor cannot consume.
Re-running unchanged cannot succeed, which matches the existing harness summary
("fix the invocation, do not simply re-run").

## 5. Contract — consumption check (scripts/oversight/second_review_logic.py)

Pure function `assess_consumption(prompt_bytes: int, metadata: dict, max_bytes_per_token: float) -> dict`.
No I/O. Returns exactly these keys:
`status, prompt_bytes, input_tokens, cache_read_tokens, consumed_tokens, bytes_per_token, threshold, reason`.

Algorithm (evaluated in this order):
1. `usage = metadata.get("usage")`. If it is not a dict, or it has no `input_tokens` key →
   `status="unverified"`, reason `no_usage`.
2. `input_tokens` must be an `int` (not `bool`) and > 0. Otherwise → `status="invalid_usage"`.
   A SUCCESS envelope that claims zero or garbage input for a non-empty prompt is itself an anomaly.
3. `cache_read_tokens`: an int ≥ 0 if present, otherwise treated as 0. A present but non-int or
   negative value → `invalid_usage`. `consumed_tokens = input_tokens + cache_read_tokens` (the
   most generous reading).
   **Architect AR-3:** it is unmeasured whether agy's `input_tokens` *includes*
   `cache_read_tokens` (as Gemini's `promptTokenCount` includes `cachedContentTokenCount`) or
   excludes it. The only real envelope we hold (fixture `agy_envelope_w3_request_changes_high.json`)
   has `cache_read_tokens: 0` and `total_tokens = input_tokens + output_tokens`, so it cannot
   decide the question. If the count is inclusive, summing double-counts. That lowers the ratio
   and hides truncation, which is the **silent** direction. If it is exclusive, not summing
   inflates the ratio, which gives a loud false positive on any implicit-cache hit, and second
   review re-runs on the same diff are routine. Neither reading may be picked blind. Steps 5–7
   below therefore decide on both readings.
4. If `prompt_bytes <= 0` → `unverified`, reason `no_prompt_bytes`. This is defensive, since a
   launched call always has bytes.
5. `bytes_per_token = prompt_bytes / consumed_tokens` (the generous reading). If `> threshold`
   → `status="not_consumed"`. Both readings agree it was truncated, and accumulation or overhead
   can only lower this ratio, so this holds even for multi-turn calls.
6. If `metadata.get("num_turns")` is an `int` (not `bool`) and `> 1` → `status="unverified"`,
   reason `multi_turn`. Cumulative multi-turn input makes the ratio blind to truncation, so a
   pass here must not be written as `verified`.
7. If `cache_read_tokens > 0` and `prompt_bytes / input_tokens > threshold` →
   `status="unverified"`, reason `cache_semantics_unmeasured`. The two readings disagree.
8. Otherwise → `status="verified"`.
Add `"num_turns"` to the returned keys (the value, or `null`).

Threshold: default **6.0 B/token**. Env `SECOND_REVIEW_MAX_BYTES_PER_TOKEN` is lower-only. It is
accepted iff it is a finite float in `[2.0, 6.0]`; otherwise the default is kept with a stderr
warning. This follows the same #985 precedent.

False-positive analysis. The check fires when the average density exceeds 6 B/token over the
whole prompt.
- The ≈ 3 KB fixed prose template runs at ≈ 4–4.5 B/token.
- Source code and diffs run at ≈ 3–4.5 B/token.
- Non-ASCII UTF-8 (CJK at 3 bytes/char, emoji at 4 bytes) runs at ≤ 4 B/token.
- Base64 and hex blobs tokenize *worse* (≤ 3 B/token), which is the safe direction.
- The only benign content plausibly above 6 is very long whitespace or separator runs. Those
  cannot dominate a reviewable diff. A false positive surfaces as fail-closed `verdict: error`,
  which is loud and never silent.
- System-prompt overhead, multi-turn accumulation, and the retry's reinforcement text all
  increase `input_tokens` → lower the ratio → can only suppress a firing, never cause one.

Detection power (stated honestly). At a benign 4 B/token, the check fires when less than ≈ 67%
of the prompt was consumed. The measured case runs at 11.7 B/token and is caught. Partial
truncation of under ≈ 33% is **not** detectable this way. Agentic overhead dilutes the signal
further. Behind the D2 ceiling, the observed truncation mechanism should not engage at all. The
ratio is defence-in-depth against the vendor ceiling dropping. A sentinel-echo check that is
exact rather than statistical is follow-up F3.

CLI subcommand `consumption`:
`second_review_logic.py consumption --prompt-bytes N --metadata-file PATH [--max-bytes-per-token X]`
- `--max-bytes-per-token` is optional. The shell passes the raw env value, and the clamp in §5
  applies to it in Python.
- A missing or unreadable or non-JSON metadata file is treated as `{}` → `unverified`.
- It prints the result dict as one JSON line on stdout.
- **Exit 0** for `verified` or `unverified`. **Exit 1** for `not_consumed` or `invalid_usage`.
  **Exit 2** for an argparse error. The shell treats *any* non-zero exit as a failure, so the
  check fails closed by construction.

## 6. Contract — scripts/run_second_review.sh

**`run_agy_review`** (runs in a subshell). New 4th optional argument `consumption_file`, a path
the main scope creates with `vendor_invoke_tmpfile`, like `AGY_USAGE_METADATA_FILE`.

After the final salvage, and only when `raw` is non-empty (agy launched and answered on the last
attempt):
- Run `consumption --prompt-bytes "$VENDOR_INVOKE_BYTES" --metadata-file "$metadata_file"`.
  `VENDOR_INVOKE_BYTES` is the last attempt's byte count, which is the reinforced prompt on retry.
  Write stdout to `consumption_file`.
- If the exit code is non-zero, set `VENDOR_INVOKE_CLASS=vendor` and
  `VENDOR_INVOKE_DETAIL=prompt_not_consumed`, emit `second_review_failure_json "agy" "$lens"`, and
  return. **This replaces the salvaged review or the prose output.** A review of a truncated
  prompt must never surface as `approve`, `request_changes`, or `unparseable`.
- `vendor` class applies because the vendor accepted the input under the ceiling and silently
  dropped some of it.
- **No retry** on `not_consumed`. Truncation is deterministic, and re-sending spends quota for
  nothing.

**`second_review_failure_json`**. Add `"prompt_ceiling_bytes": VENDOR_INVOKE_MAX_BYTES` (int, or
`null` when empty). Add detail-specific `summary` text for exactly these two details:
- `prompt_too_large`: "Prompt exceeds the per-vendor ceiling (#1718). Re-running unchanged will
  fail again. Do NOT narrow with --files or a sub-range --diff to get a pass. The evaluator
  requires reviewed_range to equal the step's register range, and a narrowed review is a
  compliance failure. Escalate to a human, who may restructure the step."
  (Architect AR-2: `--files` on committed state records `HEAD..HEAD`, and a sub-range records a
  range that does not match the register. Both are a COMPLIANCE FAIL under
  `oversight-evaluator`'s range-match rule. Worse, they invite a coverage reduction that looks
  like a pass.)
- `prompt_not_consumed`: "Vendor reported consuming materially less input than was sent
  (silent truncation, #1718). Escalate to a human. Do not trust a re-run of the same input."
- For `prompt_not_consumed`, the record also carries `"consumption": <the assess_consumption
  dict>` (read from `consumption_file`), so the numbers that caused the failure are in the
  artifact (architect AR-3). The record is inside the `## agy` section and already has
  `verdict: error`, so the extra key changes nothing downstream.

Other details keep their current text. `outcome: invocation_failed`, `verdict: error`, and
`findings: []` are unchanged. That means `second_review_logic.py aggregate` already yields
`verdict: error`, and the existing **"Fail closed on a runtime reviewer error"** block exits 1.
No new exit code.

**Fail-closed stderr**. In the existing `verdict == error` block, before `exit 1`, add one line
when `$OUTFILE` contains `"outcome_detail": "prompt_too_large"` or `"prompt_not_consumed"`:
`  Input-size failure (#1718): re-running unchanged will not help — narrow the diff or escalate.`
This is a plain `grep -q` and adds no decision logic.

**Unverified visibility**. In the main scope, after the agy section is written:
- If `consumption_file` holds `status: unverified`, append a non-reviewer block:
  `## [ADVISORY] Prompt consumption unverified (#1718)`, followed by a copy of the JSON in a
  **plain** ```` ``` ```` fence. It must **not** be a ```` ```json ```` fence (architect AR-5).
  The heading does not start with `agy` or `codex`, so `_split_sections` and `aggregate` ignore
  it. However, `validation_logic.py extract_json_objects` scans **every** ```` ```json ```` fence
  in the whole file, regardless of section. It ignores the advisory today only because the
  advisory has no `findings`, `attacks`, or `verdict` key. The plain fence removes that
  dependency, and the advisory JSON must never carry the keys `verdict`, `findings`, `attacks`,
  or `error`. It does not change the verdict.
- When codex runs (primary or fallback), always append the same advisory with
  `{"status":"unverified","reason":"codex_no_usage_envelope","prompt_ceiling_bytes":<C>}`.
  `<C>` comes from `vendor_invoke_max_bytes codex` (§4). It cannot come from
  `VENDOR_INVOKE_MAX_BYTES`, because that global was set inside the reviewer's subshell and is
  lost in the main scope.
- A `verified` status writes nothing extra.

The token-usage section and `AGY_USAGE_METADATA_FILE` handling are unchanged.

## 7. Effect on other callers (rewritten by architect AR-2, measured 2026-10-07)

Prompt sizes were measured against the working tree, not estimated. "Refuses" means
`harness/prompt_too_large`, loud, with the binary never launched.

| Caller | Gate status | Prompt to agy | Prompt to codex | Effect |
|---|---|---|---|---|
| run_second_review.sh | **Mandatory pre-PR** (MEDIUM+ agy, HIGH+ codex) | template + spec + digest + diff, **no cap** | diff + ≈ 1.5 KB | Of the last 49 merged PRs, **4 (8%) exceeded 180 KB** (181–377 KB) and **2 exceeded the ≈ 270 KB truncation point**. Those 2 were already reviewed partially and reported a pass. Steps are subsets of PRs, so ≤ 8% of MEDIUM+ steps will now fail closed and need a human. Codex is unaffected below 1 MiB. |
| framework/validate_docs.sh (**release gate Phase 3**, via cut_release.sh → run_framework_validation.sh) | Required for a release cut | ≈ 660 KB (all agents ≈ 482 KB + 4 docs + patterns + decisions); ≈ 630 KB in a consumer install | same ≈ 660 KB | **agy lane refuses on every run → verdict error → exit 1 → release cut blocked.** This lane already reviews ≤ ≈ 40% of its input and reports a pass today. Codex lane unaffected (under 1 MiB). There is no `--skip-agy`. The only bypass is `cut_release.sh --skip-validation` + `HOS_ALLOW_UNVALIDATED=1`, which skips everything. |
| framework/validate_spec_compliance.sh (**release gate Phase 4**) | Required for a release cut | ≈ 730 KB | same | Same as Phase 3: agy lane refuses on every run and blocks the release. Codex unaffected. |
| framework/validate_agents.sh, framework/validate_scripts.sh (release gate Phases 1.5–2) | Required for a release cut | large | large | **Not covered.** Both call `agy` / `codex exec` directly and bypass `vendor_invoke`. D1's claim that "every caller inherits it" is false for them. They keep the #1718 exposure. Follow-up F5. |
| run_panel.sh / run_release_panel.sh | Outer loop / release panel | ≤ 60,000 B diff per chunk (`head -c "$CAP"`) + small template and context | same | **None.** The `head -c` bounds every prompt well under both ceilings. (The earlier claim that a single-file diff over 180 KB would now `die` was wrong. Such a file is silently cut to 60 KB by `head -c`, a separate harness-side truncation of the same class. Follow-up F6.) |
| review_self.sh / reverify_self.sh | Manual tools; no gate calls them | ≈ 411–417 KB (measured, `--dry-run`) | same | agy refuses (A3, intended). `--reviewer codex` keeps working under the 1 MiB ceiling. |
| run_red_team.sh, run_redteam_sample.sh | Milestone checkpoint (manual) | consumer-sized code sample, unbounded | same | agy refuses above 180 KB on large consumer apps. That is loud and names the cause. Covered by F1. |
| capture_session.sh | Manual | small (turn log) | small | None in practice. |
| scripts/oversight/lib/changeset.sh | comment reference only | — | — | None. |

scripts/framework/* is a protected surface and is **not edited** in this slice. Those callers
inherit the change through the sourced library.

**Release-gate consequence (AR-2, AR-9).** Under this design, cut_release.sh cannot pass
Phases 3 and 4 until F1 covers validate_docs.sh and validate_spec_compliance.sh. No exemption is
added to vendor_invoke. A per-caller bypass would recreate #1718 exactly where it is known to be
live. This is an **accepted, visible break**, conditional on human clearance (§11, AR-9). The
alternative is a release gate that keeps passing on ≤ 40% of its input.

## 8. Files (8)

1. `scripts/oversight/lib/vendor_invoke.sh` — §4.
2. `scripts/oversight/second_review_logic.py` — `assess_consumption` and the `consumption`
   subcommand (§5).
3. `scripts/run_second_review.sh` — §6.
4. `tests/oversight/test_vendor_prompt_consumption_guard.py` — **new** (§10).
5. `tests/oversight/test_second_review_vendor_invoke.py` — shrink **both**
   `test_oversized_prompt_reaches_the_reviewer_on_stdin` (line 154) **and**
   `test_argv_still_carries_no_prompt_content` (line 183) to `size=150_000`. Both currently use
   `size=200_000`. The second test would otherwise fail with "stub never ran" (architect AR-8). It must stay above
   131,072, the ADR-1683 point, and fall below the new 180,000 ceiling. Add an assert that the
   prompt byte count is in that window, so the two constraints cannot drift silently.
6. `tests/oversight/test_second_review_logic.py` — unit tests for `assess_consumption` (§10b).
7. `DECISIONS.md` — append one entry: ceiling values (agy 180,000 B per #1718; codex 1,048,576 B
   per #1384, a classification bound, not a truncation bound), lower-only env, the 6.0 B/token
   threshold and its two-reading cache rule, refuse-and-escalate policy, and the accepted
   release-gate break pending F1.
8. Prompt artifact for the coding step (per existing practice).

## 9. Out of scope / follow-ups (to be filed by the worker, not by this design)

- **F1** Chunked review for oversized input in `run_second_review.sh`, `review_self.sh`,
  `reverify_self.sh`, `run_red_team.sh`, **and the release-gate scripts
  `scripts/framework/validate_docs.sh` and `validate_spec_compliance.sh`** (protected surface,
  human-approved), using file-group chunks like run_panel's CAP, with a union of per-chunk
  verdicts. For run_second_review, all chunks must cover the step's full `reviewed_range`, and a
  skipped chunk is a failure. **F1 must be filed as blocking the next release cut** (AR-2).
- **F2** An opt-in live probe, `scripts/oversight/probe_vendor_consumption.sh`. It sends a
  sentinel-bracketed filler prompt at stepped sizes and records `input_tokens` and the sentinels
  echoed, to re-measure the agy and codex ceilings per CLI version. This is deferred because it
  spends real vendor quota and is not cheap enough to ship hermetically in this slice. Never run
  it in the inner loop.
- **F3** An exact sentinel-echo verification in the review prompt: a nonce placed after the
  diff, which the reviewer must echo in a JSON field.
- **F4** The `bootstrap/invoke_agent.sh` / claude path, which has the same question for the
  claude CLI.
- **F5** (architect AR-2) Migrate `scripts/framework/validate_agents.sh` (agy `--add-dir` file
  path and direct `codex exec`) and `validate_scripts.sh` (direct `agy -p` / `codex exec`) onto
  `vendor_invoke`, so they inherit D1. Until then they are live #1718 exposures in the release
  gate. Protected surface, human-approved.
- **F6** (architect AR-2) `run_panel.sh` `head -c "$CAP"` silently cuts any single-file chunk over
  60,000 B and still reports full coverage. This is harness-side truncation of the #1718 class.
  It must split or fail loudly.
- F2 scope addition (AR-1, AR-3): probe codex at about 300 KB, 600 KB, and 1 MiB with sentinels.
  Decide whether agy's cap is a byte cap or a token cap, and measure the agentic overhead.
  Determine whether `input_tokens` includes `cache_read_tokens` (send the same prompt twice).
- `run_spec_panel.sh` is excluded (#1136).

## 10. Tests

**(a) New hermetic script tests** in `tests/oversight/test_vendor_prompt_consumption_guard.py`.
The fake `agy` / `codex` stubs sit first on PATH, or on the minimal stub PATH from
`test_second_review_envelope_gate.py` so `gh` is excluded. The truncating stub:
- reads stdin;
- keeps only the first `KEEP` bytes;
- records whether `SENTINEL-START` and `SENTINEL-END` survived to a side file;
- emits an agy envelope with `status: SUCCESS`, a valid approve review in `response`, and
  `usage.input_tokens = KEEP // 4`.

The prompt is built from a `--files` target bracketed by the start and end sentinels.

- `test_ceiling_refusal_never_launches_binary`: a sourced-lib snippet with a 180,001-byte prompt
  and an `agy` stub that touches a marker file. Expect return 1, `harness`/`prompt_too_large`,
  `RC==""`, `MAX_BYTES==180000`, and no marker file.
- `test_ceiling_boundary_equal_passes`: 180,000 bytes are launched.
- `test_ceiling_applies_to_codex`: same as the refusal test, for `codex`, at 1,048,577 bytes
  (`MAX_BYTES==1048576`). Add a companion test: a 400,000-byte codex prompt **is** launched.
  This pins AR-1, so codex cannot silently regress to the agy ceiling.
- `test_env_may_lower_ceiling`: `VENDOR_INVOKE_MAX_BYTES_AGY=1000` refuses a 1,001-byte prompt.
- `test_env_cannot_raise_ceiling`: `=10000000` keeps the effective ceiling at 180000 and prints a
  stderr warning.
- `test_env_malformed_ceiling_keeps_default`: values `abc`, `0`, `-5`.
- `test_second_review_oversized_diff_fails_closed`: a 200 KB `--files` target. Expect exit 1, an
  agy record with `outcome_detail: prompt_too_large` and `failure_class: harness`, the stderr hint
  line, and the stub never ran.
- `test_truncating_stub_fails_closed` (the sentinel regression): a prompt of ≈ 150 KB, under the
  ceiling, with `KEEP=50_000`. The side file proves the end sentinel was dropped. Expect exit 1,
  `outcome_detail: prompt_not_consumed`, `verdict: error`, and the stub's approve review
  **absent** from the artifact.
- `test_full_consumption_passes`: the same prompt with `KEEP=all`. Expect exit 0, the approve
  verdict, and no advisory block.
- `test_missing_usage_is_unverified_not_failed`: the envelope has no `usage`. Expect exit 0, and
  the artifact contains `Prompt consumption unverified`.
- `test_codex_records_unverified_advisory`: a codex-only HIGH-tier run. Expect exit 0, and the
  advisory with `codex_no_usage_envelope`.
- `test_not_consumed_is_not_retried`: the stub counts invocations. Expect exactly 1.
- `test_not_consumed_record_carries_consumption` (AR-3): the agy failure record contains a
  `consumption` object with `status: not_consumed`.
- `test_advisory_block_is_verdict_inert` (AR-5): take an artifact with an approve agy section.
  Append the advisory block. `second_review_logic.py aggregate` and `validation_logic.py process
  --strict-empty` must give **identical** verdict, severity, and counts with and without the
  block. Also assert that the block's fence is not ```` ```json ````.
- `test_codex_advisory_never_verified` (AR-5): in both the codex-primary and codex-fallback runs,
  the artifact never contains `"status": "verified"`.
- `test_lowered_ceiling_named_in_refusal` (AR-4): the refusal line contains the env var name when
  the env var lowered the ceiling.

**(b) Unit tests** for `assess_consumption` in `test_second_review_logic.py`:
- `verified` at 4.0 B/token;
- `not_consumed` at 11.7 B/token (the 793,000 / 68,000 measured case);
- the boundary: exactly 6.0 is verified, 6.0001 is not consumed;
- `cache_read_tokens` (AR-3): with cache > 0, a generous ratio over T → `not_consumed`. A
  generous ratio ≤ T with an input-only ratio > T → `unverified`/`cache_semantics_unmeasured`.
  Both ratios ≤ T → `verified`;
- `num_turns` (AR-3): `num_turns=3` with a generous ratio ≤ T → `unverified`/`multi_turn`.
  `num_turns=3` with a generous ratio > T → `not_consumed`. `num_turns=True` is ignored (treated
  as absent);
- `input_tokens` of 0, `True`, or `"68000"` → `invalid_usage`;
- negative cache → `invalid_usage`;
- no `usage` → `unverified`;
- threshold clamp: env 9.0 is ignored and 3.0 is honoured;
- CLI exit codes 0/0/1/1 for the four statuses, and a missing metadata file → `unverified`.

**(c) Live probe**: deferred to F2. It is not part of the inner loop.

## 11. Risk tier

**HIGH.** The change touches the shared launch primitive used by every cross-vendor review gate
and changes the fail-closed surface of the mandatory pre-PR second review. It also introduces a
statistical threshold whose false positive blocks the pipeline. That false positive fails loud,
not silent.
- Required reviewers at HIGH per the manifest: code, security, and reliability.
- The `review_self.sh` behaviour change needs **human acknowledgement**: a working tool
  starts refusing.
- **Product-boundary checkpoint (architect AR-9) — human clearance required before merge**,
  covering two consequences: (a) **release cuts are blocked** (Phases 3 and 4 agy lanes) until
  F1 lands for the framework validators; (b) **up to about 8% of MEDIUM+ steps** will fail the
  pre-PR second review closed and need a human, which adds escalation load. The human may also
  choose to sequence F1 for the framework validators before this merges. That is a policy
  call, not a technical one.
- No protected surface is edited.

## 12. Open points for architect

- A1 Confirm `harness` for `prompt_too_large` and `vendor` for `prompt_not_consumed`.
- A2 Confirm the lower-only env (D3), rather than freely overridable as the issue text suggests.
- A3 Confirm that review_self/reverify_self should refuse now, rather than this slice adding
  F1 chunking to them.

## Architect review (round 1, 2026-10-07)

**Verdict: APPROVED-WITH-CHANGES.** The changes below are applied in the body above. The
technical rulings are final. **Merge is gated on the human product-boundary clearance in AR-9.**
That gate is the architect CORE checkpoint for decisions with user-visible or operational
consequences. It is not a reopening of the technical rulings.

Every claim below was checked against the code, not against this TD's description of it.

- **AR-1 (codex ceiling): REJECTED 180,000. Set to 1,048,576 B.** Evidence: codex's
  `turn/start` API rejects input over 1,048,576 chars **loudly** (#1384, `validate_agents.sh`
  `CODEX_MAX_INPUT_CHARS`, 1,500,169-char test). There is no evidence that codex truncates
  silently. A 180 KB ceiling would deterministically break codex lanes that work today:
  validate_docs (≈ 660 KB), validate_spec_compliance (≈ 730 KB), and `review_self --reviewer
  codex` (≈ 417 KB). The "fallback parity" rationale was wrong. The fallback fires only when agy
  is unavailable, and the codex prompt is strictly smaller than the agy prompt. Below 1 MiB,
  codex is recorded as `unverified`, never as `verified`. F2 must probe codex's token context.
- **AR-2 (agy blast radius): ceiling STANDS, with no exemption. The TD now enumerates the
  breaks (§7).** Measured: 4 of the last 49 merged PRs (8%) exceeded 180 KB, and 2 exceeded the
  ≈ 270 KB truncation point, so those 2 were already reviewed partially. **The release gate
  breaks deterministically:** the Phase 3 and Phase 4 agy lanes (≈ 660 and ≈ 730 KB) refuse →
  exit 1 → cut_release blocked. Those lanes are false passes today (≤ 40% consumed). Accepted
  as a visible break, conditional on AR-9. F1 is extended to the framework validators and must
  block the next release. Factual corrections made: (i) run_panel is entirely unaffected
  (`head -c 60000`), and its silent 60 KB cut is new follow-up F6; (ii) validate_agents.sh and
  validate_scripts.sh **bypass** vendor_invoke, so D1 does not cover them (new F5); (iii) the
  `prompt_too_large` summary no longer advises `--files` / sub-range narrowing. Under the
  evaluator's reviewed_range match, that narrowing is a COMPLIANCE FAIL and a covert reduction
  in coverage.
- **AR-3 (6.0 B/token): threshold VALUE approved; algorithm AMENDED.** The real agy `usage` has
  the keys `input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens`, and
  `total_tokens`, with `total = input + output`. Whether `input_tokens` includes the cached
  tokens is undeterminable from our only fixture (cache is 0 there). The TD's unconditional sum
  double-counts if the count is inclusive, which is the silent direction. The decision now uses
  both readings: `not_consumed` only when both agree; `verified` only when both agree;
  disagreement → `unverified`/`cache_semantics_unmeasured`. `num_turns > 1` →
  `unverified`/`multi_turn` unless already `not_consumed`. The §3 claim that overhead "does not
  loosen D2" was wrong and is corrected: overhead shares agy's token budget. 180,000 holds only
  if the overhead is ≤ ≈ 8k tokens, or if agy's cap is a byte cap (the 256 KiB hypothesis). F2
  must resolve this. Metadata provenance is acceptable: `salvage_with_metadata` takes `usage`
  from the authoritative envelope that the CLI wrote, so diff content cannot place it at the
  top level, and the ambiguous case is already `verdict: error`.
- **AR-4 (A2, lower-only env): APPROVED** (#985 precedent). Raising a ceiling requires a reviewed
  constant change backed by F2 evidence. Addition: the refusal line names the env var when one
  lowered the ceiling.
- **AR-5 (unverified advisory): CONFIRMED verdict-inert, with one hardening.** `aggregate` skips
  the `[ADVISORY]` heading. However, `validation_logic.extract_json_objects` scans every
  ```` ```json ```` fence file-wide, so inertness currently rests on key names alone. Now
  required: a plain fence; a ban on the keys `verdict`, `findings`, `attacks`, and `error`; and
  a with/without-block identity test. Codex never reaches `assess_consumption` and always gets
  `codex_no_usage_envelope`. A `verified` status is never written. No path mislabels codex.
- **AR-6 (A1): CONFIRMED.** `harness` for `prompt_too_large` (our prompt; re-running cannot
  help) and `vendor` for `prompt_not_consumed`. The `not_consumed` failure record now embeds the
  `consumption` dict, so the numbers are in the artifact.
- **AR-7 (A3): CONFIRMED.** review_self and reverify_self refuse on agy now. They are manual and
  no gate calls them. Codex remains usable for them under AR-1. Chunking stays in F1, and the
  human acknowledgement in §11 stands.
- **AR-8 (tests): CORRECTED.** `test_argv_still_carries_no_prompt_content` (line 183) also uses
  `size=200_000` and would break, so it is added to file 5. New tests are added for AR-1, AR-3,
  AR-4, and AR-5. Accepted edge case, not a defect: a first attempt within about 300 B of the agy
  ceiling that answers in prose refuses on the reinforced retry and fails closed as
  `prompt_too_large`.
- **AR-9 (product-boundary checkpoint): REQUIRED before merge.** The human must clear (a)
  blocked release cuts until F1 covers validate_docs and validate_spec_compliance, and (b) up to
  about 8% of MEDIUM+ steps escalating to a human at second review. The architect's
  recommendation is to clear both: the status quo is a pass recorded on partially-read input.
  Whether to sequence F1 for the framework validators *before* this merges is the human's
  policy call.

Risk tier remains **HIGH**. Reviewers: code, security, reliability. No protected surface is
edited in this slice. F1 (framework part) and F5 will touch protected surfaces, under human
approval.

