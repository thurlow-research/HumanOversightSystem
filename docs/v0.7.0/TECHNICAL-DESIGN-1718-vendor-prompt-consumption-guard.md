# Technical Design — #1718 vendor prompt consumption guard

Status: DRAFT — awaiting architect review (round 1)
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
| D2 | Defaults: **agy 180,000 B**, **codex 180,000 B**. | See §3. |
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
- codex: no consumption signal exists in the forms used here. `codex exec` is called with no
  flags, and every caller treats stdout as plain text. No truncation ceiling has been measured.
  Its context window is believed to be larger than agy's, but this is unverified. The default is
  set to the same 180,000 B. That is conservative, keeps agy/codex-fallback behaviour identical
  in `run_second_review.sh` (the codex fallback reviews the same diff), and can be lowered
  further by env. Raising it needs a measured probe (follow-up F2).
- Agentic system-prompt overhead and multi-turn accumulation only **increase** `input_tokens`.
  That is the safe direction for D4. It does not loosen D2, because D2 is a byte check on the
  caller's prompt alone.

## 4. Contract — `vendor_invoke` (scripts/oversight/lib/vendor_invoke.sh)

New constants in the library (read-only defaults):
`_VENDOR_INVOKE_DEFAULT_MAX_BYTES_AGY=180000`, `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_CODEX=180000`.

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
   negative value → `invalid_usage`. `consumed_tokens = input_tokens + cache_read_tokens`.
   Cached tokens were received; leaving them out would inflate the ratio. That would be a false
   positive on a retry that hits the cache.
4. If `prompt_bytes <= 0` → `unverified`, reason `no_prompt_bytes`. This is defensive, since a
   launched call always has bytes.
5. `bytes_per_token = prompt_bytes / consumed_tokens`. If `> threshold` → `status="not_consumed"`.
   Otherwise → `status="verified"`.

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
- `prompt_too_large`: "Prompt exceeds the per-vendor ceiling. Narrow the review (--files /
  a smaller --diff range) or escalate to a human. Re-running unchanged will fail again."
- `prompt_not_consumed`: "Vendor reported consuming materially less input than was sent
  (silent truncation, #1718). Narrow the review or escalate. Do not trust a re-run of the
  same input."

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
  `## [ADVISORY] Prompt consumption unverified (#1718)`, followed by a fenced copy of the JSON.
  The heading does not start with `agy` or `codex`, so `_split_sections` and `aggregate` ignore
  it. It does not change the verdict.
- When codex runs (primary or fallback), always append the same advisory with
  `{"status":"unverified","reason":"codex_no_usage_envelope","prompt_ceiling_bytes":<C>}`.
  `<C>` comes from `vendor_invoke_max_bytes codex` (§4). It cannot come from
  `VENDOR_INVOKE_MAX_BYTES`, because that global was set inside the reviewer's subshell and is
  lost in the main scope.
- A `verified` status writes nothing extra.

The token-usage section and `AGY_USAGE_METADATA_FILE` handling are unchanged.

## 7. Effect on other callers (inherit D1 only; no code change)

| Caller | Typical prompt | Effect |
|---|---|---|
| run_panel.sh | ≤ 60 KB chunks (CAP) | None, unless a single file diff is over 180 KB. That now fails loudly via `die` instead of truncating silently. |
| review_self.sh / reverify_self.sh | ≈ 417 KB (measured) | **Now refuses** with `prompt_too_large`. This is intended: it currently reviews ≈ 65% of its corpus silently. Follow-up F1 adds chunking. |
| run_red_team.sh, run_redteam_sample.sh, capture_session.sh, validate_docs.sh, validate_spec_compliance.sh | varies | They are refused above 180 KB, and their existing `VENDOR_INVOKE_DETAIL` reporting names the cause. |
| scripts/oversight/lib/changeset.sh | comment reference only | None. |

scripts/framework/* is a protected surface and is **not edited** in this slice. Those callers
inherit the change through the sourced library.

## 8. Files (8)

1. `scripts/oversight/lib/vendor_invoke.sh` — §4.
2. `scripts/oversight/second_review_logic.py` — `assess_consumption` and the `consumption`
   subcommand (§5).
3. `scripts/run_second_review.sh` — §6.
4. `tests/oversight/test_vendor_prompt_consumption_guard.py` — **new** (§10).
5. `tests/oversight/test_second_review_vendor_invoke.py` — shrink
   `test_oversized_prompt_reaches_the_reviewer_on_stdin` to `size=150_000`. It must stay above
   131,072, the ADR-1683 point, and fall below the new 180,000 ceiling. Add an assert that the
   prompt byte count is in that window, so the two constraints cannot drift silently.
6. `tests/oversight/test_second_review_logic.py` — unit tests for `assess_consumption` (§10b).
7. `DECISIONS.md` — append one entry: ceiling values, lower-only env, 6.0 B/token threshold,
   refuse-and-escalate policy.
8. Prompt artifact for the coding step (per existing practice).

## 9. Out of scope / follow-ups (to be filed by the worker, not by this design)

- **F1** Chunked review for oversized input in `run_second_review.sh`, `review_self.sh`, and
  `reverify_self.sh`, using file-group chunks like run_panel's CAP, with a union of per-chunk
  verdicts.
- **F2** An opt-in live probe, `scripts/oversight/probe_vendor_consumption.sh`. It sends a
  sentinel-bracketed filler prompt at stepped sizes and records `input_tokens` and the sentinels
  echoed, to re-measure the agy and codex ceilings per CLI version. This is deferred because it
  spends real vendor quota and is not cheap enough to ship hermetically in this slice. Never run
  it in the inner loop.
- **F3** An exact sentinel-echo verification in the review prompt: a nonce placed after the
  diff, which the reviewer must echo in a JSON field.
- **F4** The `bootstrap/invoke_agent.sh` / claude path, which has the same question for the
  claude CLI.
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
- `test_ceiling_applies_to_codex`: same as the refusal test, for `codex`.
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

**(b) Unit tests** for `assess_consumption` in `test_second_review_logic.py`:
- `verified` at 4.0 B/token;
- `not_consumed` at 11.7 B/token (the 793,000 / 68,000 measured case);
- the boundary: exactly 6.0 is verified, 6.0001 is not consumed;
- `cache_read_tokens` is counted;
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
- No protected surface is edited.

## 12. Open points for architect

- A1 Confirm `harness` for `prompt_too_large` and `vendor` for `prompt_not_consumed`.
- A2 Confirm the lower-only env (D3), rather than freely overridable as the issue text suggests.
- A3 Confirm that review_self/reverify_self should refuse now, rather than this slice adding
  F1 chunking to them.
