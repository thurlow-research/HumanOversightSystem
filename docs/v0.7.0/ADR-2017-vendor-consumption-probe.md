# ADR-2017: The probe is a human-only, HOS-only tool in `scripts/dev/` that launches agy/codex itself, under a new enforced launch-site ledger. `vendor_invoke` logic stays unchanged. The receipt nonce is a 128-bit token minted and rendered in Python, read only from the model's answer, and never seeded by a test hook. F3 lands first in today's single-prompt code. F4 measures the real opus-self seat through `invoke_agent.sh`

**Status:** APPROVED WITH AMENDMENTS. AD-1 to AD-9 bind `technical-design`. AR-1 to AR-17 (§5) amend the requirements and are applied in place in `REQUIREMENTS-2017-vendor-consumption-probe.md`, each tagged with its AR id. Two items are **PROVISIONAL**:
- AD-6's enforcement start depends on ARCH-ESC-2: enforce at merge, or run a shadow soak first.
- AD-3's "a raise must cite evidence" is a **tripwire, not a control**, until ARCH-ESC-1 is answered.

These parts are not open to any ESC answer or agent-side waiver:
- AD-1's ledger equality;
- AD-1's rule that `vendor_invoke`'s ceiling has no bypass;
- AD-5's ban on a nonce test hook, including any env var or flag;
- AD-5's rule that the check reads the model's answer only;
- AD-6's rule that the check never downgrades a result.

**Date:** 2026-10-17
**Author:** architect (autonomous worker cycle; no human present, so open decisions are ESC/ARCH-ESC items with recommended defaults)
**Issue:** #2017 (#1718 follow-ups F2, F3, F4) · **Parent:** #1718 · **Sibling:** #2014 (F1) · **Milestone:** v0.7.0
**Risk tier:** S2 (F3) is **HIGH**, because it adds a fail-closed condition to the mandatory pre-PR gate, and that gate ships to consumers. S1 (F2) is **MEDIUM**, with `security-reviewer` mandatory. S3 is HIGH and S4 is MEDIUM. **As designed, no slice touches a protected surface** (`scripts/framework/protected_surfaces.txt`). If the human selects ARCH-ESC-1 (a), it adds one protected slice, S0.
**Inputs.** `docs/v0.7.0/REQUIREMENTS-2017-vendor-consumption-probe.md` (VF-1 to VF-9, REQ-F2-1 to REQ-S-2, ESC-1 to ESC-9, TD-O1 to TD-O6), read in full. Files read for this ADR:
- `docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md` (whole, including AR-1 to AR-9);
- `docs/v0.7.0/TECHNICAL-DESIGN-2014-chunked-vendor-review.md` (whole, including AR-1 to AR-14 and §12);
- `docs/v0.7.0/ADR-1683-vendor-invocation-stdin.md` (whole: D-1 to D-7, §5);
- `scripts/oversight/lib/vendor_invoke.sh` (whole);
- `scripts/run_second_review.sh:601-1060`;
- `scripts/oversight/second_review_logic.py:654-700,833-962`;
- `scripts/oversight/validation_logic.py:140-160,361`;
- `bootstrap/invoke_agent.sh` (whole) and `scripts/automation/agent_invoke_cli.py:1-140,887`;
- `scripts/framework/validate_self.sh:330-390`;
- `tests/framework/test_agent_invocation_migration.py:1-140` (T4.1 ledger) and `tests/framework/test_vendor_argv_sweep.py` (whole);
- `bootstrap/hos_install.sh:1858,1866-1895`;
- `scripts/framework/protected_surfaces.txt`.

**Consumers:** `technical-design`, then `coder`, then the review chain.
- `security-reviewer` is mandatory on S1, S2 and S3. S1 adds a sanctioned above-ceiling launcher. S2 and S3 change a fail-closed gate and parse model output.
- `reliability-reviewer` is mandatory on S2 and S3, which add a new false-positive surface to a gate that runs on every MEDIUM+ step.

**Explicitly does NOT re-litigate:**
- #1718's ceilings, its 6.0 B/token threshold, the two-reading cache rule (NG-1, NG-2), and #1718 AR-5's advisory rules;
- TD-2014's D1 to D8 and AR-1 to AR-14;
- ADR-1683 D-2's base forms and D-7's disjoint vendor sets;
- ADR-1643 AD-3, which allows only shipped agents.

---

## 0. Verification findings (working tree at `04a301220`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.**
  - The ceiling check runs before launch (`vendor_invoke.sh:308-320`).
  - The clamp can only lower the ceiling (`:109-131`).
- **VF-5 CONFIRMED.**
  - The agy prompt is `READ-ONLY` (`:686`), then context and spec, then `## Diff` (`:718`), then `Return JSON only` (`:723`).
  - The codex prompt has `## Diff` at `:890` and the schema at `:895`.
  - The retry overwrites the prompt file in place (`:782`).
- **VF-6 CONFIRMED.** The consumption block is at `:803-817`. Codex lanes run at `:1005` (fallback) and `:1026` (reserve), both in command-substitution subshells.
- **VF-8 CONFIRMED.**
  - The only non-test caller of `invoke_agent.sh` is `validate_self.sh:355`. It uses `--agent self-reviewer --posture review-read-only --dimension self-review --lens self-review`.
  - `GOOD_TERMINAL_REASONS = {"completed"}` (`agent_invoke_cli.py:103`).
  - `_derive_actual_tokens` (`:887`) feeds telemetry only.
- **TD-O4, partly answered.**
  - `validation_logic.fingerprint` (`:361`) keys on each finding, never on the whole review object, so a top-level `receipt_nonce` cannot disturb dedup or the ledger (#2036).
  - `_is_review_dict` (`:140-143`) tests whether the review keys are present, not for an exact key set.
  - The TD must still confirm that `loads_strict`'s duplicate-key rejection (`:113-122`) handles a model that emits `receipt_nonce` twice. It should fail closed.
- **TD-O5 ANSWERED.**
  - `run_second_review.sh` ships through the installer's explicit copy loop (`hos_install.sh:1858`).
  - `second_review_logic.py` ships through the wholesale `scripts/oversight/` rsync (`:1866-1895`).
  - **F3 therefore changes every consumer's pre-PR gate on upgrade.** That is a product consequence (§6).

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): the launch-path rule ESC-1 would add an "exemption" to is not enforced anywhere.**
- ADR-1683 D-2 says every agy/codex call goes through `vendor_invoke`. ADR-1683 §5 deferred the mechanical check to #1364. #1364 built `test_vendor_argv_sweep.py`, which bans **content in argv**. It does **not** ban launch sites.
- There are four prompt-carrying direct launchers today:
  - `scripts/framework/validate_agents.sh:311,391`;
  - `scripts/framework/validate_scripts.sh:220-221`;
  - `bootstrap/setup_clis.sh:153,155`;
  - `vendor_invoke.sh:298-299` itself.
- The pm default's "a test that allows exactly one exempt file" would be **false on the day it lands**. A new production caller could already launch `agy` directly, unseen.
- AD-1 creates the missing ledger. The probe joins it as one named entry.

**AF-2 (HIGH): the ceiling constants are mutable globals.**
- `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_AGY` (`:92`) is a plain shell assignment. Any sourcing caller can reassign it after `source` and lift the ceiling with no env var and no flag. REQ-F2-4's "no new env var" does not cover this.
- The env side is safe, because the `source` line overwrites any exported value.
- `readonly` is the wrong fix. `vendor_invoke.sh` is sourced more than once per process (#2014's `chunked_review.sh` will source it as well), and a readonly re-assignment aborts the shell under `set -e`.
- AD-1 bans the reassignment statically instead.

**AF-3 (HIGH): `scripts/oversight/` ships to every consumer.**
- ADR-1683 fact 1 records that the installer rsyncs `scripts/oversight/` wholesale and that `.hos-manifest` enumerates it with `find`.
- REQ-F2-1's path (`scripts/oversight/probe_vendor_consumption.sh`) would therefore ship a quota-spending tool to consumers, which contradicts NG-7.
- `scripts/dev/` is not copied by the installer (`hos_install.sh` has no `scripts/dev` reference) and is not protected. Its existing tenant (`commit_onto_base.sh`) is HOS-internal (AD-2).

**AF-4 (HIGH): a test hook for the receipt nonce would be a production bypass.**
- REQ-F3-1's AC asks for a "fixed test nonce (seam)". In a shell-driven gate, a hook means an env var or flag. A known, fixed nonce defeats F3: a diff author who knows it can plant `"receipt_nonce": "<it>"` early in the diff, and a reviewer of a truncated prompt can echo it back from the part it *did* see.
- The hermetic tests do not need a hook. A stub receives the whole prompt on stdin, so it can extract the nonce and echo it, as a real model would.
- The same reasoning rules out REQ-F2-1's "TTY check satisfied through a test seam". Tests allocate a real pty instead (AD-4, AD-5).

**AF-5 (HIGH): scanning "the raw text" for the nonce can pass on a prompt echo.**
- REQ-F3-2 searches a prose answer's raw text.
- For agy, `raw` is the `--output-format json` envelope, not the model's words. For codex, whether `codex exec` stdout ever carries a transcript containing the prompt is **unverified** on the installed build.
- If any vendor output echoes its input, the nonce is "found" without the model ever having read up to it. That is a silent pass, the exact failure F3 exists to remove.
- AD-5 limits the search to the model's answer and adds a contamination rule.

**AF-6 (MEDIUM): the ceiling raise rule sits entirely on unprotected surface.**
- `vendor_invoke.sh` (`scripts/oversight/lib/`) is not in `protected_surfaces.txt`, and neither is any `tests/**` file.
- A LOW-to-HIGH tier PR that raises the constant can also weaken REQ-F2-6's citation test in the same diff, and the overseer can auto-merge it.
- REQ-F2-6 is therefore a reviewer-visible tripwire, not a control. This is the same class as ADR-2047-2048 AF-1, and it belongs to the #1574/#1935 surface-classification work. ARCH-ESC-1 asks the human. §6 records it as a startup gap in my #1718 review.

**AF-7 (MEDIUM): prose is the expected truncation symptom, so the prose rows matter most.**
- The #1718 observation kept a prefix. Under a kept prefix the trailing `Return JSON only` schema (`:723`, `:895`) is the **first** thing lost, and a reviewer that never saw the schema answers in prose.
- Today prose becomes `unparseable`, which routes to CONDITIONAL (`:821-839`).
- Under F3, prose without the nonce must fail closed. REQ-F3-4's table did not have this row, so a TD could have left prose on the CONDITIONAL path, which is the silent path. AR-12 adds it.

**AF-8 (MEDIUM): under #2014, rendering the nonce at send time breaks the planned-prompt hash.**
- TD-2014 AR-8 requires the sent prompt to be the planned `chunk-NNN.prompt`, hashed by `record-result`.
- A receipt nonce substituted after planning changes those bytes, so every chunk would fail `sha_mismatch`.
- The nonce must be rendered **at plan time**, inside the byte budget (AD-7).

**Reuse search (CLAUDE.md item 1).** I searched `scripts/`, `scripts/oversight/lib/`, `scripts/automation/lib/`, `bootstrap/`, `bin/` and `tests/framework/` for six things. Results:
- **A launch-site ledger for agy/codex.** None exists. The nearest are `test_vendor_argv_sweep.py`, which checks argv content only, and T4.1, which covers claude only. AD-1 follows T4.1's equality-ledger idiom.
- **A "live, opt-in, spends quota" guard.** None exists (VF-9).
- **A nonce or token minting helper.** TD-2014 plans `chunk_logic.py markers` (`secrets.token_hex(8)`), but it is not on main and is the wrong width for this use. AD-5 mints in `second_review_logic.py`, which ships.
- **A pty test helper.** None exists. Python's stdlib `pty`/`os.openpty` is enough.
- **A timeout wrapper.** `run_with_retry.sh:with_timeout` exists. The probe reuses it (ADR-1643 AD-5.3), and no third timeout implementation is added.
- **A claude envelope recorder.** None exists. AD-8 uses a PATH tee-shim and does not touch `agent_invoke_cli.py`.

---

## 1. Organizing principle

**Prove three things separately.**
- **The bound.** `vendor_invoke` stays the only sanctioned way to send a production prompt, and its ceiling has no bypass.
- **The evidence.** A human-only tool may cross the bound, but only from a ledgered file that nothing else references.
- **The receipt.** A per-prompt secret, placed after the last reviewed byte, must come back in the model's own answer.

Each check can only add a failure. None can relax another.

---

## 2. Decisions

### AD-1: An enforced launch-site ledger for agy/codex. The probe is one named, permanent entry. `vendor_invoke` logic is unchanged, and nothing outside it may write its ceiling variables. (BINDING, not waivable. ESC-1, TD-O1, REQ-F2-4, AF-1, AF-2.)

- **Ruling on ESC-1: (a), the probe launches the binaries itself**, as the pm-agent default proposed.
  - (b), an unclamped internal function, is rejected for the pm-agent's reason: any sourcing caller can call it.
  - A "base-argv accessor" exported from `vendor_invoke.sh` is rejected for the same reason. An accessor is a bypass that no literal-match scan can see.
  - (c), probing only up to the ceiling, cannot answer questions (a) or (c).
- **New test `tests/framework/test_vendor_launch_sites.py`**, in the style of T4.1 (code lines only, exemption set asserted for **equality**). It runs three checks.
  - **Ledger.** The set of files under `scripts/`, `bootstrap/` and `bin/` that launch `agy` or `codex` with a prompt must equal exactly this set:

    | File | Kind |
    |---|---|
    | `scripts/oversight/lib/vendor_invoke.sh` | The primitive |
    | `bootstrap/setup_clis.sh` | Permanent: the machine-bootstrap smoke test, which runs before the primitive's preconditions hold (the T4.1 §6.5 precedent) |
    | `scripts/framework/validate_agents.sh` | Until F5 / #2033 |
    | `scripts/framework/validate_scripts.sh` | Until F5 / #2015 |
    | `scripts/dev/probe_vendor_consumption.sh` | Permanent: human-only (AD-4) |

    - A launch is the vendor name at command position, including after `run_capped …`, `with_timeout …`, `exec` or `sh -c '…'`, and including in Python argv lists.
    - `--version` probes and `vendor_invoke agy …` (the vendor as an argument) do not count.
    - As F5 lands, entries are removed and the assertion tightens.
  - **Ceiling-variable writes.** No file except `vendor_invoke.sh` assigns `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_*`, `_VENDOR_INVOKE_CEILING` or `_VENDOR_INVOKE_CEILING_LOWERED_BY` (AF-2). That includes `declare`/`export`/`readonly` forms and `local` shadowing.
  - **Guard the guard.** Fixture lines for each launch form and each assignment form must match the patterns. The migrated `vendor_invoke agy "$T" …` form must not.
- **`vendor_invoke.sh` changes in comments only** (REQ-S-1: the ceiling comments point to REQ-F2-6 and the evidence path). `test_vendor_prompt_consumption_guard.py` passes unmodified.
- **REQ-F2-4's AC stands as written.** It adds an assertion that every environment variable the probe reads is set while `vendor_invoke` still refuses 180,001 B for agy.

### AD-2: The probe lives in `scripts/dev/`, is HOS-only, and does no launching for production callers. Decision logic is in Python. (BINDING. NG-7, TD-O5, REQ-F2-1, AF-3.)

- **Files.**
  - `scripts/dev/probe_vendor_consumption.sh`: argument parsing, refusal guards (AD-4), launch, and file moves. No decision logic.
  - `scripts/dev/vendor_probe_logic.py`, pure stdlib with a thin CLI, provides:
    - `plan` (sizes, densities, repeats, totals, `plan_id`);
    - `filler` (deterministic from a seed, with per-run CSPRNG sentinels);
    - `classify-call`;
    - `answer` (questions a, b, c and the truncation shape);
    - `write-result` (schema `hos-vendor-consumption-probe/1`);
    - `summary`.
- **Launch parity (AR-2).**
  - The probe sends with exactly production's argv: `agy --sandbox --output-format json < file` and `codex exec < file`.
  - It sends through `with_timeout`, sourced from `run_with_retry.sh`.
  - It runs with cwd = the repo root, as `run_second_review.sh` does. Context files that the vendor loads from cwd are part of the agentic overhead that question (a) must measure.
  - A hermetic **parity test** drives both `run_second_review.sh` and the probe against a stub that records argv, and asserts that the vendor argv is identical. Drift between the probe and the measured path fails the build.
- **Sentinels and filler (TD-O3, AR-6).**
  - Sentinels are `PROBE-<k>-<32 hex>`, CSPRNG-generated per run, at ≥ 5 positions (start, 25%, 50%, 75%, end).
  - The instruction to list every `PROBE-` token seen goes **at the start** of the prompt, so it survives a kept prefix.
  - Filler comes in ≥ 2 densities (code-like dense, and prose) and is seed-deterministic, so a run can be reproduced.
- **Classification honesty (AR-6).** A missing sentinel is a **recall miss** until it is corroborated.
  - For agy, `truncated` requires a usage shortfall consistent with the loss: the consumed tokens fall short of what the bytes up to the first missing sentinel predict at the measured density.
  - For codex, which has no usage, `truncated` requires the same sentinel to be missing on **every** repeat (repeat count ≥ 2 for codex).
  - Otherwise the result is `recall_miss` or `inconclusive`.
  - Long-context recall is imperfect, so a missing token on its own is not evidence of truncation.
- **Stderr.** The probe reuses `vendor_invoke.sh`'s redaction (`_vendor_invoke_process_stderr`) by sourcing the library. That sourcing is for helpers only. The launch stays in the probe's ledgered file.

### AD-3: Evidence lives in `docs/evidence/vendor-consumption/` and is committed through a normal PR. A ceiling raise must cite it, with margin. (BINDING on the format and the margin rule. PROVISIONAL as a control, pending ARCH-ESC-1. REQ-F2-5, REQ-F2-6, ESC-3.)

- **I concur with ESC-3's default.** The path is `docs/evidence/vendor-consumption/<UTC-date>-<vendor>-<cli-version>.json`, plus a `.md` summary.
  - The result holds only filler, sentinels, usage numbers and redacted stderr tails. It has no secrets and no repo content.
  - The probe writes into `.claudetmp/vendor-probe/`. **The human** copies the result into `docs/evidence/` in a PR. The probe never writes into a tracked path itself, which keeps it from producing commits.
- **Margin (AR-7).** A raise to value V for a vendor must cite a result file for that vendor that is **git-tracked on the PR's base**. V must not exceed either of:
  1. the largest size measured `full` at the **densest** filler class;
  2. 0.85 × the smallest size measured `truncated` or `rejected_loudly` at **any** density, when one was observed.

  The 15% margin mirrors #1718's 180 KB vs ≈ 270 KB choice, which was 33%, and leaves room for CLI drift between the run and the merge.
- **The citation test** goes in `tests/oversight/test_vendor_ceiling_citation.py`. It parses the two constants and their comments from `vendor_invoke.sh` and applies the rule above. Lowering a constant never needs a citation.

### AD-4: The probe refuses before any launch unless a human at a terminal confirms the exact plan. (BINDING on the mechanism. ESC-2 still needs a human. REQ-F2-2, REQ-F2-3, TD-O2.)

- **Refusal conditions (exit 2, one stderr line, zero launches):**
  - `--confirm-spend <plan_id>` is absent, or its value differs from the `plan_id` of the plan about to run (AR-4);
  - `CI` or `GITHUB_ACTIONS` is set non-empty;
  - any of `HOS_CYCLE_ID`, `HOS_CYCLE_ROLE` or `HOS_CYCLE_TOKEN` is set non-empty;
  - stdin is not a TTY;
  - the plan exceeds a cap.
- **The `plan_id`.** `--dry-run` prints the plan and its `plan_id`, a short hash over vendor, sizes, densities, repeats and the probe's git SHA. A spend therefore needs a deliberate copy of a value that changes whenever the plan changes. No shell alias and no `--confirm-spend yes` can be "set once and forgotten".
- **No test hook (AF-4).** No env var, flag or file can satisfy the TTY check. Tests use a real pty (`os.openpty`/`pty`). A test pins that `HOS_PROBE_*`-style variables, or any variable the probe reads, cannot stand in for a TTY.
- **Caps (TD values; suggested).** At most 16 calls per run and 8 MiB sent per run, as reviewed constants. Env may only lower them, following the #1718 D3 pattern.
  - The suggested agy plan: {150, 200, 250, 300, 400, 800} KB × 2 densities, plus one identical-prompt pair for question (b). That is 14 calls, about 4.4 MB.
  - The suggested codex plan: {300 KB, 600 KB, 1,000,000 B, 1,048,600 B}, repeated twice for the AR-6 corroboration rule. That is 8 calls, about 5.9 MB.
- **TD-O2 ANSWERED: no settings deny rule.**
  - Cron's Bash is non-TTY and carries `HOS_CYCLE_*`, and CI carries `CI`, so the runtime refusal already stops both.
  - A deny rule would add a protected-surface edit for no additional property.
  - REQ-F2-2(ii)'s static test (widened by AR-5) keeps the probe out of every allowlist.

### AD-5: The receipt nonce: 128 bits, a fixed-length token, minted and rendered in Python, checked only against the model's answer, and never set by a hook. (BINDING, not waivable. REQ-F3-1, REQ-F3-2, AF-4, AF-5.)

- **Form (AR-8).** `HOS-RCPT-<32 lowercase hex>`, from `secrets.token_hex(16)`.
  - It is a fixed 41 bytes, so #2014's budget can count it as a constant.
  - It is distinct in form from #2014's 16-hex marker nonce.
- **Pure functions in `second_review_logic.py`, plus CLI subcommands:**
  - `mint_receipt_nonce()`.
  - `render_receipt(prompt: bytes, nonce: str) -> bytes`. It substitutes exactly one `@@HOS_RECEIPT@@` placeholder and asserts that the nonce occurs exactly once in the output. On a collision it re-mints, up to 3 tries, and then raises.
  - `assess_receipt(expected: str, review: dict | None, answer_text: str | None, instruction_sentence: str) -> dict`, which returns `{state, expected, observed, contaminated}`.
  - The shell never composes the nonce and never compares it.
- **Placement.**
  - The echo instruction comes immediately after the `READ-ONLY` paragraph (`:686`), before the risk context, the spec and the diff. It carries a fixed **instruction sentence** that appears nowhere else.
  - The nonce line comes after the closing fence of `## Diff` and before `Return JSON only`, in both the agy and codex prompts.
  - The schema names `"receipt_nonce"`.
  - The instruction also says that a prose answer must still carry the line `receipt_nonce: <value>`.
- **What the check reads (AR-10).** It reads the model's answer only.
  - **JSON path:** the `receipt_nonce` field of the **exact object salvage selected and will emit**. The multi-candidate resolution (`second_review_logic.py:672-683`) chooses that object, and the check never searches other candidates.
  - **Prose path, agy:** only the envelope's `response` text, never the whole stdout.
  - **Prose path, codex:** stdout. This stands only because S2 must record one live `codex exec` run on the PR, demonstrating that stdout carries the final message only. If that run shows a prompt transcript, codex prose becomes `missing` (fail closed) until a fix lands.
  - **Contamination rule.** If the answer text contains the instruction sentence verbatim, it contains a prompt echo. The state is then `missing` with `contaminated: true`, never `echoed`.
- **No hook (AF-4).**
  - Shipped code reads no env var, flag or file that fixes the nonce.
  - Unit tests pass the nonce as a function argument.
  - Shell tests use a stub that extracts the `HOS-RCPT-…` token from its own stdin and echoes it.
  - Goldens normalise the token to a fixed placeholder before comparing.
  - A static test asserts that `run_second_review.sh` and the receipt functions read no environment variable.
- **Expected-nonce transport (TD-O6).** The main scope creates a per-lane file with `vendor_invoke_tmpfile`, as `AGY_CONSUMPTION_FILE` does. The reviewer subshell writes the minted nonce to it, and the check reads it back. **The file never enters a prompt.**

### AD-6: Composition: consumption first, receipt second. The receipt check only adds failures. Its own crash is a harness failure. (BINDING on composition. PROVISIONAL on the enforcement start, ARCH-ESC-2. REQ-F3-3, REQ-F3-4, AF-7.)

- **Order, inside each reviewer function, on the final attempt and only when `raw` is non-empty:**
  1. `consumption` (agy only; unchanged);
  2. `receipt`;
  3. the existing emission (salvaged JSON, prose, or failure record).

  A consumption failure is emitted as today. The `receipt` object is added to that record, never in place of it.
- **Verdict table (REQ-F3-4, completed by AR-12):**

  | Consumption | Answer | Receipt | Result |
  |---|---|---|---|
  | `not_consumed` / `invalid_usage` | any | any | `prompt_not_consumed`, as today, plus `receipt`. `echoed` sets `contradiction: true` |
  | `consumption_check_failed` | any | any | as today (harness) |
  | `verified` / `unverified` / codex | JSON | `echoed` | Review stands. The existing advisories (agy unverified, codex `codex_no_usage_envelope`) are written unchanged, with `"receipt": "echoed"` added |
  | `verified` / `unverified` / codex | JSON | `missing` / `mismatch` | **Fail closed**, `receipt_nonce_not_echoed`, class `vendor` |
  | `verified` / `unverified` / codex | prose | `echoed` | Prose stands: `unparseable`, CONDITIONAL, as today |
  | `verified` / `unverified` / codex | prose | `missing` (including contaminated) | **Fail closed**, `receipt_nonce_not_echoed` |
  | any launched answer | — | check crashed, or expected-nonce file unreadable | **Fail closed**, `receipt_check_failed`, class `harness` (AR-11) |

- **No retry** on a receipt failure (REQ-F3-3). The prose-retry is unchanged and reuses the same nonce. Its suffix comes after the nonce line.
- **The failure record** uses `second_review_failure_json` with `verdict: "error"`, `outcome: "invocation_failed"`, `failure_class`, `outcome_detail` and `receipt: {state, expected, observed (≤ 64 chars, backticks stripped), contaminated}`. The run exits 1 through the existing runtime-error block. The fail-closed stderr hint (`grep -q`) gains the two new details.
- **ESC-6 resolved: no suppression.** An `echoed` receipt never removes the consumption advisory. #1718 AR-5 stands.
- **Enforcement start (ARCH-ESC-2).** If the human chooses a shadow soak, S2 ships with a **reviewed code constant** `RECEIPT_ENFORCE = False` in `second_review_logic.py`, and no env switch. A miss then writes a verdict-inert `## [ADVISORY] Receipt nonce not echoed (#2017)` block, with a plain fence and no AR-5-banned keys. A later one-line PR flips the constant, citing the soak data.

### AD-7: Ordering with #2014: F3 is built first in today's code. Under chunking the nonce is rendered at plan time. Whichever lands second owns the integration. (BINDING. ESC-7, REQ-F3-6, AF-8.)

- **ESC-7 resolved: build F3 now.** #2014 S2 is gated on human ESCs 4, 5 and 9. Waiting would leave P2 open for an unbounded time, and the defects F3 fixes are live.
- **Integration contract, binding on whichever of {#2017 S2, #2014 S2} lands second:**
  - `chunk_logic plan` renders each chunk's receipt by calling `second_review_logic.render_receipt` on the chunk prompt, **before** writing `chunk-NNN.prompt`. The planned file is therefore the sent file, and TD-2014 AR-8's hash holds.
  - The fixed 41-byte nonce, plus its line, counts inside `T` as a per-chunk constant. The final-prompt assertion (`≤ max_bytes − reserve_bytes`) covers it.
  - The expected nonces go to `<report>.chunks/receipts.json` (mode 0600), keyed by chunk id. That file is never a prompt input. `record-result` gains an outcome `receipt_failed`, which is not `unparseable`, so `--allow-unparseable` never admits it.
  - The `@@HOS_RECEIPT@@` placeholder sits after the body marker in the template. TD-2014 AR-4's exactly-once rule applies to it.
- **If #2014 S2 lands second:** its "one implementation" grep test (TD-2014 §10, S2) also asserts that `chunked_review.sh` calls the receipt check and that `run_second_review.sh` no longer carries its own copy.
- **D7 golden.** If F3 lands first, S2 creates its golden from the F3 prompt, with the nonce normalised, and no re-baseline is needed. If F3 lands second, it re-baselines the golden as a named change that cites REQ-F3-6.
- TD-2014 S1a is **unaffected**. A dated note on TD-2014 §12 is required in S2 (FU-2).

### AD-8: F4 measures the real opus-self path through `bootstrap/invoke_agent.sh`, using the `self-reviewer` agent and no new agent. (BINDING. ESC-8, REQ-F4-2.)

- **ESC-8 resolved: a `--vendor claude` mode of the same probe.** It shares filler, sentinels, guards (AD-4), caps and the result schema.
- **The launch is `bash bootstrap/invoke_agent.sh` with `validate_self.sh:355`'s exact argv:** `--agent self-reviewer --posture review-read-only --dimension self-review --lens self-review --timeout … --model …`. Recording the effective `--model` is mandatory.
  - That is the only production caller, so measuring it answers REQ-F4-1's question for the path that exists.
  - AD-3 (shipped agents only) is satisfied, no T4.1 exemption is added, and no `claude -p` appears.
  - A probe-only agent is rejected. It would be a protected `.claude/agents/**` and `consumer_agents.txt` addition, and it would measure a system prompt that production does not use.
- **Envelope capture (REQ-F4-2).**
  - The probe puts a pass-through `claude` shim first on `PATH`, inside its own temp dir. The shim execs the real binary, resolved before the shim was installed, and tees stdout to a capture file, preserving the exit status (`pipefail`).
  - The probe records two artifacts: the raw envelope (`is_error`, `terminal_reason`, `usage`, `num_turns`), and the primitive's result document from stdout.
  - **No change to `agent_invoke_cli.py` or `invoke_agent.sh`** (NG-5).
  - The shim contains no `claude -p`/`--print` literal. It forwards `"$@"`.
- **Sizes.** The probe steps up from about 50% of the documented context window to beyond it, using the token estimate from the measured density.
  - Sentinel echo is **advisory** for claude, because the self-reviewer's output contract is governance findings and it may not list tokens.
  - The decision evidence is the envelope's `usage` against the bytes sent (the #1718 ratio method), plus the primitive's `outcome` above the window.
- **Caller sizes (REQ-F4-1(iii)).** Measure `validate_self.sh`'s opus-self input with its own dry-run, or a byte count of `tmp_prompt` under a local run. If neither exists, the measurement is a manual `wc -c` recipe in the finding.

### AD-9: Slices, docs and audit. (BINDING. REQ-S-1, REQ-S-2.)

- **Slices:** see §4. **DECISIONS.md:** one entry per slice.
- **No new audit event.**
  - The probe result file is the evidence.
  - The receipt state lives in the second-review artifact (`.claudetmp/second-review/`), the same place as #1718's records.
- **REQ-S-1 docs:**
  - the probe's header (refusals, `plan_id`, "never in CI or cycles", spend);
  - the `run_second_review.sh` header (receipt rule and fail-closed);
  - the `vendor_invoke.sh` ceiling comments, pointing to REQ-F2-6 and AD-3's path;
  - a dated note on TD-1718 §9;
  - a dated note on TD-2014 §12 (S2);
  - `docs/evidence/vendor-consumption/README.md`, with the schema and the margin rule (S1).

---

## 3. Threat model and failure modes

**Trust boundaries.**
- Diff, spec and model output are untrusted.
- The nonce is a secret until the call returns.
- The trusted inputs are this repo's base code, the CSPRNG and the vendor envelope's `usage`. The `usage` field comes from the CLI, not from the model's text (#1718 AR-3).

| Threat or failure | Control | Direction |
|---|---|---|
| A production caller sends above the ceiling through the probe's launcher | The probe is referenced by no executable or config file (AR-5), refuses non-TTY, cron and CI callers, and requires `plan_id` | Closed |
| A new production file launches `agy`/`codex` directly | Launch-site ledger equality (AD-1) | Closed (test) |
| A sourcing caller reassigns `_VENDOR_INVOKE_DEFAULT_MAX_BYTES_*` | Static write ban (AD-1) | Closed (test) |
| A ceiling raised without evidence | Citation test with margin (AD-3) | **Tripwire only** until ARCH-ESC-1 |
| Truncation that keeps a prefix and drops the nonce, with the reviewer answering in JSON | `missing`, which fails closed | Closed |
| The same truncation, with the reviewer answering in prose (the expected symptom) | `missing` on the prose path, which fails closed (AR-12) | Closed |
| A vendor echoes the prompt, carrying the nonce | Answer-only scope plus the contamination rule (AD-5) | Closed |
| A diff pre-plants a nonce value | 128-bit fresh nonce and no hook (AF-4) | Closed |
| A chunk echoes another chunk's nonce | `mismatch` (AD-7) | Closed |
| The model leaves out the field when not truncated | Fails **loudly** as `error`, and a human escalates (ESC-4, ARCH-ESC-2) | Loud false positive |
| The receipt check crashes, or the nonce file is missing | `receipt_check_failed`, harness | Closed |
| A dropped middle (head and tail kept) | **Not detected** by a trailing nonce (REQ-F3-7). F2's shape answer decides the follow-up | **Open (R-1)** |
| claude path silent truncation | Unknown until the F4 finding. NG-5 forbids a speculative guard | **Open (R-2)** |

**Residuals.**
- **R-1.** A dropped middle (REQ-F3-7).
- **R-2.** The claude path, until F4 reports.
- **R-3.** Before ARCH-ESC-1, a single auto-mergeable PR can raise a ceiling and weaken its citation test together.
- **R-4.** Codex receipt rests on one live run showing that its stdout carries only the answer (AD-5). A CLI update could change that, which is an argument for ESC-9's follow-up.

---

## 4. Slices (each ≤ 15 files including tests, ≤ 10 commits, independently mergeable)

| # | Slice | Files (indicative) | Tier | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|---|
| **S0** *(only if ARCH-ESC-1 = a)* | Protect the ceiling definition and its citation test | `scripts/framework/protected_surfaces.txt`, `.github/CODEOWNERS` (regenerated), `DECISIONS.md`: **3** | MEDIUM computed | **Yes**: `scripts/framework/**`, `.github/CODEOWNERS`. CODEOWNER review | S1 (the test must exist) | ARCH-ESC-1 |
| **S1** | F2 probe, launch-site ledger, citation test (REQ-F2-1 to F2-7, AD-1 to AD-4) | `scripts/dev/probe_vendor_consumption.sh` (new), `scripts/dev/vendor_probe_logic.py` (new), `tests/oversight/test_probe_vendor_consumption.py` (new: refusals over a real pty, `plan_id`, caps, dry-run, the four stub questions, shapes, parity), `tests/oversight/test_vendor_probe_logic.py` (new), `tests/framework/test_vendor_launch_sites.py` (new, AD-1), `tests/framework/test_vendor_probe_not_referenced.py` (new, AR-5), `tests/oversight/test_vendor_ceiling_citation.py` (new, AD-3), `scripts/oversight/lib/vendor_invoke.sh` (comments only), `docs/evidence/vendor-consumption/README.md` (new), `SCRIPTS-INDEX.md`, `DECISIONS.md`, `TECHNICAL-DESIGN-1718` §9 note, prompt artifact: **13** | **MEDIUM** (`security-reviewer` mandatory) | No | — | ESC-2, ESC-3 |
| **S2** | F3 receipt nonce in today's single-prompt code (REQ-F3-1 to F3-5, F3-7; AD-5, AD-6) | `scripts/run_second_review.sh`, `scripts/oversight/second_review_logic.py`, `tests/oversight/test_second_review_receipt_nonce.py` (new: one test per §2 AD-6 row, contamination, no hook, nonce once and after the diff, instruction before the spec, retry reuse), `tests/oversight/test_second_review_logic.py` (unit), `tests/oversight/receipt_stub.py` (new shared stub snippet), fixture-only edits (REQ-F3-5, each named in the TD) to `test_vendor_prompt_consumption_guard.py`, `test_second_review_vendor_invoke.py`, `test_second_review_envelope_gate.py`, `test_second_review_request_changes_gate.py`, `test_second_review_env_threshold_clamp.py`, `DECISIONS.md`, `TECHNICAL-DESIGN-1718` §9 note, prompt artifact: **13** | **HIGH** (code, security, reliability; second review HIGH+) | No | — (independent of S1) | ESC-4, ESC-5, ARCH-ESC-2. The live codex stdout run is recorded on the PR (AD-5) |
| **S3** | F3 × #2014 integration (REQ-F3-6, AD-7) | Carried inside whichever of {#2014 S2, #2017 S2} lands second | **HIGH** | No | #2014 S1a, and both of the above | #2014 ESC-4/5/9 |
| **S4a** | F4 `--vendor claude` mode (AD-8) | `scripts/dev/probe_vendor_consumption.sh`, `scripts/dev/vendor_probe_logic.py`, `tests/oversight/test_probe_vendor_consumption.py` (claude mode: guards, shim tee preserves rc, argv equals `validate_self.sh`'s), `DECISIONS.md`: **4** | **MEDIUM** | No (`bootstrap/invoke_agent.sh` is only called, never edited) | S1 | — |
| **S4b** | F4 finding plus verdict follow-up (REQ-F4-1, REQ-F4-3) | `docs/v0.7.0/FINDING-2017-F4-claude-path.md`; **only on `no_gap`:** `tests/automation/test_agent_invoke_oversize_envelope.py` + one redacted fixture: **1 to 3** | **LOW** | No | S4a, plus a human measurement run | The human run |

**Order.**
- S1 and S2 can be coded now, in parallel.
- S4a follows S1.
- The operator steps are: run the probe (agy, codex), then commit the evidence in a PR; run the claude mode, then S4b.
- S0 follows S1, if the human selects it.

**Not touched by any slice:**
- `bootstrap/invoke_agent.sh`, `scripts/automation/agent_invoke_cli.py` and `scripts/framework/validate_self.sh` (read and called only);
- `vendor_invoke.sh` logic (comments only);
- `.claude/agents/**`, `.claude/settings*.json` and `.github/workflows/**`.

### Test obligations (all hermetic: stubs first on a minimal PATH, no real vendor or `claude`)

- **S1:**
  - Each refusal condition (no or wrong `plan_id`, `CI`, `GITHUB_ACTIONS`, each `HOS_CYCLE_*`, non-TTY, over-cap) → exit 2, stub marker absent, reason named.
  - A real pty plus the correct `plan_id` → launches.
  - `--dry-run` → zero launches, `plan_id` printed.
  - Byte-cap and token-cap stubs → `byte_cap`/`token_cap`. Cache stubs → `inclusive`/`exclusive`. The codex 600 KB drop → `truncated` only when it repeats; once only → `inconclusive`.
  - Middle-drop → `middle_dropped`. Prefix → `prefix_kept`.
  - The result validates against the schema, with `cli_version` and `probe_sha`.
  - Parity: agy and codex argv equal `run_second_review.sh`'s.
  - Ledger equality, the variable-write ban, and guard-the-guard.
  - AR-5's not-referenced test, with a fixture workflow reference → fail.
  - Citation: the current constants pass; an un-cited raise → fail; a raise above 0.85 × truncation → fail; a supported raise → pass.
  - `vendor_invoke` refuses 180,001 B with every probe env var set.
- **S2:**
  - Every AD-6 row.
  - The stub extracts the nonce from stdin. Approve-JSON without the field → exit 1, `receipt_nonce_not_echoed`, approve absent, invocation count 1.
  - Wrong nonce → `mismatch`. Whitespace-padded → `mismatch`.
  - Prose with the `receipt_nonce:` line → `unparseable` stands. Prose without it → exit 1.
  - The agy envelope's `response` lacks the nonce while another envelope field contains it → `missing`.
  - An answer quoting the instruction sentence plus the nonce → `missing`, `contaminated: true`.
  - Nonce file deleted → `receipt_check_failed`, harness, exit 1.
  - `test_advisory_block_is_verdict_inert` passes, with `receipt` present.
  - The nonce occurs once, after the diff body's last byte. The instruction comes before `<spec>`.
  - Two runs give different nonces.
  - No env var is read by the receipt path (static).
  - The #1718 assertion lines are unchanged (`git diff` check in review).
- **S4a:** argv identical to `validate_self.sh:355` (minus timeout and model values); the shim preserves rc on a failing stub; all AD-4 refusals apply.
- **S4b (`no_gap`):** the recorded oversize envelope, fed to `classify`, → `invocation_failed`.

---

## 5. Requirement amendments (applied in place in the requirements doc, each tagged `[AR-n]`)

- **AR-1 (ESC-1, TD-O1, REQ-F2-4; AF-1, AF-2).** (a) is adopted. The "exactly one exempt file" test is replaced by an equality **launch-site ledger** of five entries (AD-1), plus a static ban on writing the ceiling variables. No accessor and no internal unclamped function.
- **AR-2 (REQ-F2-1).** The probe uses production's exact argv, stdin, `with_timeout` and cwd. A parity test pins it.
- **AR-3 (REQ-F2-1, NG-7, TD-O5; AF-3).** The path moves to `scripts/dev/probe_vendor_consumption.sh` and `scripts/dev/vendor_probe_logic.py`. TD-O5 is answered: F3 ships, the probe does not.
- **AR-4 (REQ-F2-2(i), REQ-F2-1 AC; AF-4).** `--confirm-spend <plan_id>`, matched against the plan. `HOS_CYCLE_TOKEN` is added. The TTY "test seam" is withdrawn in favour of a real pty.
- **AR-5 (REQ-F2-2(ii)).** Stricter and simpler: no tracked file references the probe's filename except the probe, its logic module, its tests, `SCRIPTS-INDEX.md` and `*.md` docs outside `.claude/`.
- **AR-6 (REQ-F2-1, REQ-F2-7).** `truncated` requires corroboration: an agy usage shortfall, or a codex miss on every repeat (≥ 2). Otherwise `recall_miss`/`inconclusive`. The sentinel-report instruction goes at the start of the prompt.
- **AR-7 (REQ-F2-6).** A raise is allowed only up to min(the largest `full` size at the densest class, 0.85 × the smallest truncated or rejected size), citing a git-tracked file under `docs/evidence/vendor-consumption/`.
- **AR-8 (REQ-F3-1).** The nonce is `HOS-RCPT-<32 hex>` (128 bits, fixed 41 B), minted and rendered in `second_review_logic.py`. The instruction goes before the spec and the diff. Prose must carry a `receipt_nonce:` line. A collision re-mints.
- **AR-9 (REQ-F3-1 AC, REQ-F3-5).** No fixed-nonce hook in shipped code. Stubs extract the nonce from stdin. Goldens normalise it. Unit tests pass it as an argument.
- **AR-10 (REQ-F3-2; AF-5).** The check reads the answer only: the selected object's field; the agy envelope `response` for prose; codex stdout, verified by one live run. The contamination rule makes an echoed instruction sentence `missing`.
- **AR-11 (REQ-F3-3).** A receipt-check crash or a missing nonce file → `receipt_check_failed`, class `harness`, fail closed.
- **AR-12 (REQ-F3-4; AF-7).** Prose rows are added: prose + `echoed` keeps `unparseable` (CONDITIONAL); prose + `missing` fails closed.
- **AR-13 (REQ-F3-6, ESC-7; AF-8).** Under #2014 the nonce is rendered at **plan** time into the planned prompt, and the expected nonces go to a 0600 sidecar. The chunk outcome is `receipt_failed`. If F3 lands first, S2's golden is born with a normalised nonce.
- **AR-14 (REQ-F4-2, ESC-8).** The claude mode goes through `invoke_agent.sh --agent self-reviewer` with `validate_self.sh`'s argv. The envelope is captured by a PATH tee-shim. No primitive change and no new agent.
- **AR-15 (§5 slices).** Re-cut as §4: S1 absorbs the citation test; S4 splits into S4a (code) and S4b (finding); S0 is added, conditional on ARCH-ESC-1.
- **AR-16 (TD-O2).** No settings deny rule.
- **AR-17 (TD-O4).** Partly answered (§0.1). The TD verifies duplicate-key handling only.

Endorsed as written: REQ-F2-3 (with AR-4's caps), REQ-F2-5, REQ-F2-7 (with AR-6), REQ-F3-5, REQ-F3-7, REQ-F4-1, REQ-F4-3, REQ-S-1, REQ-S-2, and NG-1 to NG-7.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible or operational, routed to the human (not mine to sanction):**
  - **F3 adds a new way for the mandatory pre-PR gate to fail closed, in HOS and in every consumer on upgrade** (TD-O5).
    - The false-positive rate (a model leaving out the field) is unmeasured.
    - A prose answer without the nonce moves from CONDITIONAL to `error`.
    - These are ESC-4, ESC-5 and ARCH-ESC-2.
  - **Quota spend.** The probe spends agy, codex and Claude quota, and only a human at a terminal can run it (ESC-2). Per AD-4's suggested caps, one run costs at most 16 calls and 8 MiB per vendor.
  - **Data retention.** Probe results are committed under `docs/evidence/` (ESC-3). They contain filler and numbers only.
- **Cost.** No new service, credential or scheduled job (NG-6). F3 adds about 500 B per second-review prompt. A prompt within about 500 B of the 180,000 B agy ceiling now refuses. That is a negligible shift and is loud.
- **Startup gap: yes, in my #1718 review (AF-6).**
  - #1718 AR-4 required that "raising requires a reviewed constant change backed by F2 evidence", but placed the constant on a surface the overseer can auto-merge, with no protected backing.
  - ADR-1683 D-2's "every call goes through here" was never enforced (AF-1). That is a gap in ADR-1683 §5's deferral to #1364, which built only the argv half.
  - **Recommendation to the worker:** open or annotate a `startup-artifact-gap` issue against #1718/#2017, and cross-reference #1574/#1935 (surface classification). I have not filed it, per this task's instructions.
- **Affected sign-offs.**
  - **#1718 code sign-offs stand for S1.** `vendor_invoke.sh` changes in comments only, and its tests are unmodified.
  - **#1718 sign-offs on `run_agy_review` and its tests are re-reviewed for the S2 delta.** S2 edits stub fixtures in four #1718 test files (REQ-F3-5). The same `security-reviewer` and `reliability-reviewer` lenses must confirm that no assertion changed (the TD-2014 §12 condition).
  - **ADR-1683 D-2 and D-7 stand.** AD-1 enforces D-2 and AD-8 respects D-7.
  - **ADR-1643 AD-3 and AD-16 stand.** No agent is added and no exemption is added.
  - **TD-2014 S1a stands.** TD-2014 S2's design gains AD-7's integration obligation. S2 is unbuilt, so no approval is orphaned.

---

## 7. Open human escalations

pm-agent's ESC-1 to ESC-9, with the architect's positions:

| ESC | Architect | Resolved by architecture? | Gates |
|---|---|---|---|
| ESC-1 | **(a), with the ledger (AD-1)** | **Yes.** It is the technical mechanism, and spend is gated by ESC-2 | S1 |
| ESC-2 | **Concur: TTY-only**, plus `plan_id` (AD-4) | No. It decides who may spend quota, which is policy | S1 |
| ESC-3 | **Concur: `docs/evidence/vendor-consumption/`**, human-committed | No. It is a data-retention surface | S1 |
| ESC-4 | **Concur: `missing` fails closed, no retry, exact match.** Prose rows per AR-12 | No. It is a new user-visible failure mode | S2 |
| ESC-5 | **Concur: include both codex lanes**, with AD-5's live-run condition | No. It extends the failure mode to codex lanes | S2 |
| ESC-6 | **No suppression** | **Yes.** It keeps #1718 AR-5 and changes nothing visible | — |
| ESC-7 | **F3 first**, AD-7 integration contract | **Yes** | S2, S3 |
| ESC-8 | **`--vendor claude` mode through `invoke_agent.sh --agent self-reviewer`** (AD-8) | **Yes.** No agent is needed, so the AD-3 question is moot | S4a |
| ESC-9 | **Concur: out of scope.** Suggested follow-up (FU-3) | **Yes** | — |

Architect items (tier `hard-tradeoff`):

- **ARCH-ESC-1 (protect the ceiling definition).**
  - **(a)** Add `scripts/oversight/lib/vendor_invoke.sh` and `tests/oversight/test_vendor_ceiling_citation.py` to `protected_surfaces.txt` (S0, a protected slice). Only edits to those two files become human-gated. Migrations that change callers only (#1364, F5, #2014) are unaffected.
  - **(b)** Leave them unprotected. REQ-F2-6 stays a reviewer-visible tripwire (R-3).
  - **(c)** Defer to the #1574/#1935 surface-classification work.
  - *Recommended: (a).* The constant is a control, and AR-4 of #1718 already said that loosening it needs reviewed evidence.
- **ARCH-ESC-2 (F3 enforcement start).**
  - **(a)** Enforce at S2 merge (the pm default).
  - **(b)** Shadow soak. S2 ships with `RECEIPT_ENFORCE = False`, a reviewed code constant with no env switch: a miss is advisory-only. A one-line flip PR follows after **15 consecutive real second-review runs** (any mix of agy and codex lanes, recorded on the flip PR) show zero unexplained `missing`/`mismatch`. Every miss must be explained as a real truncation or harness defect.
  - *Recommended: (b).* The compliance rate is unmeasured and the gate runs on every MEDIUM+ step, in consumers too. During the soak, the #1718 ceiling and ratio check remain the active controls, so no protection is removed relative to today.
  - Under (a), S2 ships with enforcement on, and the AD-6 table applies from merge.

```yaml
adr: ADR-2017
issue: 2017
verdict: APPROVED_WITH_AMENDMENTS
codable_now: [S1, S2]
design_now_merge_after: {S1: [ESC-2, ESC-3], S2: [ESC-4, ESC-5, ARCH-ESC-2], S4a: [S1], S4b: [S4a, "human claude measurement run"], S0: [S1, ARCH-ESC-1]}
integration: {S3: "carried by whichever of #2014 S2 / #2017 S2 lands second (AD-7)"}
operator_steps: ["run probe for agy and codex (TTY, plan_id); commit results under docs/evidence/vendor-consumption/ via PR", "run probe --vendor claude; author FINDING-2017-F4 (S4b)", "S2 PR: record one live codex exec run proving stdout carries no prompt echo (AD-5)"]
protected_slices: [S0]
hard_constraints_not_waivable: ["AD-1 ledger equality + ceiling-variable write ban", "AD-5 no nonce hook, answer-only scope, contamination rule", "AD-6 never downgrade; receipt crash = harness fail-closed"]
not_touched: [bootstrap/invoke_agent.sh, scripts/automation/agent_invoke_cli.py, scripts/framework/validate_self.sh, ".claude/**", ".github/workflows/**", "vendor_invoke.sh logic"]
escalations:
  - {id: ESC-1, resolved_by: architect, ruling: "(a) + launch-site ledger"}
  - {id: ESC-2, tier: hard-tradeoff, recommended: tty-only-plus-plan-id, gates: [S1]}
  - {id: ESC-3, tier: hard-tradeoff, recommended: docs/evidence/vendor-consumption, gates: [S1]}
  - {id: ESC-4, tier: hard-tradeoff, recommended: fail-closed-no-retry-exact, gates: [S2]}
  - {id: ESC-5, tier: hard-tradeoff, recommended: include-both-codex-lanes, gates: [S2]}
  - {id: ESC-6, resolved_by: architect, ruling: no-suppression}
  - {id: ESC-7, resolved_by: architect, ruling: f3-first}
  - {id: ESC-8, resolved_by: architect, ruling: "claude mode via invoke_agent.sh --agent self-reviewer"}
  - {id: ESC-9, resolved_by: architect, ruling: out-of-scope}
  - {id: ARCH-ESC-1, tier: hard-tradeoff, options: {a: protect, b: tripwire, c: defer}, recommended: a, gates: [S0]}
  - {id: ARCH-ESC-2, tier: hard-tradeoff, options: {a: enforce-at-merge, b: shadow-15-runs}, recommended: b, gates: [S2]}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **FU-1 → F5 (#2015/#2033).** When `validate_agents.sh` and `validate_scripts.sh` migrate onto `vendor_invoke`, each PR removes its row from AD-1's ledger. The test tightens automatically.
- **FU-2 → #2014.** TD-2014 §12 gets a dated note pointing to AD-7: plan-time receipt rendering, the `receipt_failed` outcome, and the one-implementation test extension.
- **FU-3 → ESC-9.** A version-drift warning: when `agy --version` or `codex --version` differs from the latest evidence file's `cli_version`, emit one stderr line. It needs a version call per run, which would add a non-prompt launch to `vendor_invoke`. That is a design question for its own issue. R-4 adds weight to it.
- **FU-4 → NG-2.** Once a probe result answers question (b) on the installed agy, the worker raises the two-reading collapse with the architect, citing the file.
- **FU-5 → REQ-F3-7.** If the evidence shows `middle_dropped` for any vendor, interior receipt nonces follow. AD-5's `render_receipt` is written to take N placeholders, so that follow-up adds no new primitive.
- **N-1.** The probe runs vendors at cwd = repo root for parity (AD-2). The agentic CLIs run there in read-only or sandboxed form, exactly as in production. The probe adds no new exposure.

## Escalation flag (CORE self-flag)

RISK: HIGH for S2 and MEDIUM for S1. S2 adds a fail-closed condition to a mandatory gate that ships to consumers. S1 adds the only sanctioned above-ceiling launcher. Defects in either could have these effects:
- an S1 defect that lets a production path reach the probe's launcher re-creates #1718;
- an S2 defect that reads the nonce from a prompt echo re-creates silent truncation behind a "proof".

CONFIDENCE:
- HIGH on §0: every citation was read in this session at `04a301220`.
- HIGH on AF-1, AF-2 and AF-3, which were verified by grep and by reading the installer.
- MEDIUM on two points that need live evidence:
  - the codex stdout content (AD-5's live-run condition);
  - the model echo-compliance rate (ARCH-ESC-2).

BLAST RADIUS:
- every MEDIUM+ second review, in HOS and in consumers (S2);
- the agy/codex launch surface repo-wide (the S1 ledger);
- no production path for S4.

Change classification: STRUCTURAL.

## Human Review Required

- **ESC-2 and ESC-3** before S1 merges.
- **ESC-4, ESC-5 and ARCH-ESC-2** before S2 merges.
- **ARCH-ESC-1** decides whether S0 exists.

ESC-1, ESC-6, ESC-7, ESC-8 and ESC-9 are resolved by architecture (§7). S1 and S2 may be designed and built now. No slice as designed touches a protected surface. S0 does, if you choose it.
