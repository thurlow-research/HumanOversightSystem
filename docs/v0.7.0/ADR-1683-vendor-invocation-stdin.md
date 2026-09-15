# ADR-1683 — Vendor CLI invocation moves to stdin; one bash launch primitive for agy/codex

**Status:** ACCEPTED (binding)
**Date:** 2026-09-15
**Issue:** #1683 (`priority:critical`) — instance of the class owned by #1364 (`priority:high`)
**Type:** bounded architect triage for a bug fix. This is a ruling document, not a full ADR.
**Binds:** `coder`, `code-reviewer`, `unit-test` for the #1683 PR.

---

## 1. Context

The bug is diagnosed in #1683 and is not re-litigated here. In one line:
`scripts/run_second_review.sh:595,601` pass the assembled agy prompt as a single argv
element; Linux caps one argv element at `MAX_ARG_STRLEN` = 131,072 bytes; on #1643's W1
slice the prompt was ~174,483 bytes, so `execve` returned `E2BIG` before agy started, and
`2>/dev/null` turned a one-line kernel error into the generic `"agy invocation failed"`.
The gate fails *closed*, so nothing merged on a false pass — but the mandatory cross-vendor
correctness review at MEDIUM+ is disabled on any large diff, with a misleading diagnosis.

Three facts discovered during triage change the shape of the fix from what #1683's scope
implies, and they are the reason this ruling reaches the conclusions it does:

1. **`scripts/oversight/` is installed to consumers by wholesale rsync**
   (`bootstrap/hos_install.sh`, the `scripts/oversight/` section), and `.hos-manifest`
   enumerates it with `find scripts/oversight -type f` (`enumerate_framework_files`).
   A new file under `scripts/oversight/lib/` is therefore shipped *and* manifest-tracked
   with **no installer change at all**. This removes the single strongest argument against
   a shared helper.
2. **A sanctioned shared bash invocation library already exists**:
   `scripts/oversight/run_with_retry.sh` (sourced, provides `with_timeout`, already used by
   `run_validators.sh` and the gates). ADR-1643 AD-5.3 already names it as the destination
   for the remaining `agy`/`codex` timeout wrapping. A new helper must *source* it, not add
   a third timeout implementation.
3. **ADR-1643's invocation primitive is `claude`-only.** Its argv contract
   (`TECHNICAL-DESIGN-1643` §3.5) is `claude --print --agent … --settings …`; AD-16's
   standing rule is *"nothing else in the repository invokes `claude --agent` directly."*
   It has no agy/codex path and no agent concept for them. A bash helper for agy/codex is
   therefore **not** a competing primitive — see D-7.

**Product-boundary checkpoint (my CORE obligation):** none of the decisions below alter
user-visible product behavior, the cost model (the D-3 digest *reduces* token cost),
deployment topology, data retention (the new failure detail lands only in gitignored
`.claudetmp/`), or operational obligations. No PM/human clearance gate is required before
these bind.

---

## 2. Decisions

### D-1 (Q-A) — One shared helper, created now at `scripts/oversight/lib/vendor_invoke.sh`; only `run_second_review.sh` migrates in this PR.

**Ruling.** The coder creates `scripts/oversight/lib/vendor_invoke.sh` and migrates
`run_second_review.sh` — and nothing else — onto it in this PR. Every other site listed in
§3 stays with #1364 and migrates onto the *same* helper there. No second implementation of
this logic is ever written.

**Installer impact: none.** `scripts/oversight/` is rsynced wholesale and manifest-enumerated
by `find`, so the new file ships and is tracked automatically. The coder must **not** add a
line to `scripts/framework/framework_consumer_files.txt` (that file is explicitly for
non-`scripts/oversight/` consumer files; adding it there would double-track the path in the
manifest). No `bootstrap/hos_install.sh` change is in scope, and none is needed as a child
issue either.

**Rationale.** The usual objection to extracting a library during a critical hotfix is that
it adds a shipped surface and an installer change; here it adds neither, because the shipped
home already exists. The remaining objection — designing an abstraction against one caller —
is answered by specifying the API in D-2 against the *full ten-site survey*, which I have and
#1364's future author would otherwise have to redo. The alternative (per-site fix now,
extract later) is how ten divergent copies of an invocation form get written: there are
already three variants of the agy flag string in the tree. D41's "one invocation site" is
satisfied from the first commit, and #1364 becomes a mechanical migration rather than a
redesign.

### D-2 — The helper's contract, bound here so #1364's migrations need no redesign.

```
source "$(dirname "${BASH_SOURCE[0]}")/oversight/lib/vendor_invoke.sh"   # from scripts/*.sh

vendor_invoke <vendor> <timeout_sec> <prompt_file> <stdout_file> [extra argv...]
```

- `<vendor>` ∈ `{agy, codex}`. The helper owns the **base command and the stdin contract**;
  the caller owns lens flags. The base forms — the single place in the repo where they live:
  - `agy`   → `agy -p` with `< "$prompt_file"`
  - `codex` → `codex exec` with `< "$prompt_file"`
- **No prompt content ever reaches argv through this function.** Enforced, not merely
  intended: the helper **rejects any `extra argv` element longer than 4,096 bytes**, failing
  with `VENDOR_INVOKE_DETAIL=argv_content_detected`, `CLASS=harness`, and a loud stderr line.
  This is #1364's "runtime guard" implemented at the one choke point, and it is strictly
  better than a prompt-size check: it makes *reintroducing* the bug through this path
  impossible rather than merely detectable.
- Timeout via `with_timeout` from `run_with_retry.sh` (source it; do **not** add a third
  timeout implementation — ADR-1643 AD-5.3). `run_second_review.sh` passes
  `${SECOND_REVIEW_VENDOR_TIMEOUT:-900}`. 900s is deliberately well above agy's own
  `--print-timeout` default of 5m, so the wrapper catches only a genuine hang and does not
  newly truncate legitimate long reviews.
- Returns 0 **iff** the child exited 0 *and* stdout is non-empty. Always sets, on every call:

  | Variable | Values |
  |---|---|
  | `VENDOR_INVOKE_RC` | raw child exit status |
  | `VENDOR_INVOKE_CLASS` | `ok` \| `harness` \| `vendor` |
  | `VENDOR_INVOKE_DETAIL` | `ok` \| `binary_not_found` \| `not_executable` \| `exec_failed` \| `argv_content_detected` \| `vendor_nonzero_exit` \| `timeout` \| `empty_output` |
  | `VENDOR_INVOKE_STDERR` | redacted, single-line, ≤500-byte tail (D-5) |
  | `VENDOR_INVOKE_BYTES` | byte size of `<prompt_file>` |

- Classification rule (exact): `command -v <vendor>` fails → `harness`/`binary_not_found`
  (before any launch). rc 126 → `harness`/`not_executable`. rc 127 → `harness`/`exec_failed`.
  rc 124 → `vendor`/`timeout`. rc ≠ 0 otherwise → `vendor`/`vendor_nonzero_exit`.
  rc 0 with empty stdout → `vendor`/`empty_output`.

**The agy flag form must be verified empirically before the PR is opened.** `agy --help`
documents `-p` as a short alias for `--print` with no stated value, and #1683 verified only
`echo … | agy`. The coder runs a trivial check —
`printf 'Reply with exactly: OK' > /tmp/claude/p.txt`, then
`agy --sandbox --output-format json -p < /tmp/claude/p.txt` — and records the observed output
and `agy --version` in a comment above the vendor table in the helper, exactly as
`run_second_review.sh:585-591` documents `--output-format json`. If `-p` turns out to require
a value on the installed build, the verified fallback is to **drop `-p`** (a non-TTY stdin
already triggers print mode, per #1683's verified `echo … | agy`). Getting this wrong would
replace a silent `E2BIG` with a silent arg-parse failure, which is the same class of defect
this ADR exists to remove — so it is verified, not assumed.

### D-3 (Q-C) — `VALIDATOR_SUMMARY` is replaced by a derived digest. The full document does not belong in the prompt.

**Ruling.** `run_second_review.sh` no longer interpolates
`.claudetmp/oversight/validators/summary.json` verbatim. It interpolates a digest produced by
a new subcommand on the module that already owns this script's Python logic:

```
python3 scripts/oversight/second_review_logic.py digest-validators --file <summary.json>
```

The digest is built in three deterministic tiers, each announced, never by byte-slicing JSON
(the prompt must never contain a truncated JSON object):

| Tier | Content | Measured size on the W1 slice |
|---|---|---|
| 1 | top-level `composite_score`, `tier`, `validator_count`, `successful_validators`; per result: `dimension`, `score`, `weight`, `tier_floor`, `error`, `raw_value`, and the integer counts `evidence_count`, `finding_count`, `checklist_count` | **7,938 B** (from 53,665 B) |
| 2 | tier 1 minus `raw_value` | **2,963 B** |
| 3 | top-level scalars plus a `dimension: score` list only | < 1 KB |

Tier 1 is used unless it exceeds **16,384 bytes**, then tier 2, then tier 3. The emitted
object always carries `"_digest_tier": 1|2|3` and `"_digest_note"` naming what was dropped, so
the reviewer model and any human reading the artifact see the degradation. Every degradation
below tier 1 also prints one line to the script's stderr:
`run_second_review: validator digest degraded to tier N (full summary NNNNN B > 16384 B cap)`.
Silence is not acceptable and is not permitted here.

**Rationale, and it is not primarily about bytes.** What gets dropped at tier 1 is `evidence`,
`findings`, and `checklist_items` — arrays of `file:line:message` pointers. Those are precisely
the **anchoring** content, and passing them contradicts the independence rule stated in this
script's own header (*"Do NOT pass internal reviewer findings to these reviewers. Independence
is the value"*). The prompt currently labels the block *"NOT internal reviewer findings"* —
that label is a tell that someone already worried about this; the digest makes the label
*true*. What is kept — composite score, per-dimension scores and weights, aggregate
`raw_value` stats — is the actual risk context, and is the only part of it with any bearing on
a correctness+spec-adherence lens. An 85% size reduction is a welcome side effect, not the
justification. Since stdin removes the `E2BIG` constraint, nothing here is load-bearing for
correctness of the fix; it is load-bearing for review *quality*.

**`DIFF_CONTENT` is never truncated.** The diff is the review's subject; silently shortening it
would destroy the review to protect a byte budget. If a diff is genuinely too large for the
model, agy now returns a real error, and D-4 reports it as `vendor`/`vendor_nonzero_exit` with
the vendor's own message — which is exactly the non-silent outcome #1364 asks for.

**Telemetry must follow.** `run_second_review.sh:778` estimates `PROMPT_CHARS` from
`${#VALIDATOR_SUMMARY}`. It must use the digest's length instead. Misleading token telemetry is
one of the things that wasted diagnosis time in #1683; leaving it stale would reintroduce that.

### D-4 — Failure taxonomy: `harness` vs `vendor`, expressed in ADR-1643 AD-6's vocabulary.

**Today** (both causes collapse into one string):

```json
{"reviewer":"agy","error":"agy invocation failed","findings":[],"verdict":"error"}
```

**Required shape.** Two examples, one per class:

```json
{
  "reviewer": "agy",
  "lens": "correctness+spec",
  "verdict": "error",
  "findings": [],
  "outcome": "invocation_failed",
  "outcome_detail": "binary_not_found",
  "failure_class": "harness",
  "exit_code": 127,
  "prompt_bytes": 174483,
  "stderr_tail": "",
  "error": "agy could not be invoked (binary_not_found) — no independent judgment was produced",
  "summary": "Harness defect: fix the invocation, do not simply re-run."
}
```

```json
{
  "reviewer": "agy",
  "lens": "correctness+spec",
  "verdict": "error",
  "findings": [],
  "outcome": "invocation_failed",
  "outcome_detail": "vendor_nonzero_exit",
  "failure_class": "vendor",
  "exit_code": 3,
  "prompt_bytes": 174483,
  "stderr_tail": "auth: credentials expired; run `agy login`",
  "error": "agy ran and failed (vendor_nonzero_exit, rc=3) — no independent judgment was produced",
  "summary": "Vendor-side failure: resolve the vendor condition and re-run."
}
```

- `outcome` and `outcome_detail` are **ADR-1643 AD-6's** field names and AD-6's rule
  (`invocation_failed ⟹ verdict:"error"`, always) is honoured verbatim. Inventing a parallel
  vocabulary for the same concept in the same milestone would be a self-inflicted divergence.
  `failure_class` is the one-word operational answer AD-6 does not carry: *who fixes this*.
- The codex path gets the identical shape with `"reviewer":"codex"`.
- **Nothing breaks.** `second_review_logic.py:_aggregate_full` keys on
  `data.get("verdict") == "error" or data.get("error")`, both of which are preserved; additive
  fields are ignored. I grepped `tests/` and `.claude/agents/` — **nothing** matches on the
  literal `"agy invocation failed"` (`validate_self.sh:264` greps only its own
  `"claude invocation failed"`, in a different file, untouched here).
- **Both still fail closed.** `verdict:"error"` propagates to the aggregate, and the existing
  `FINAL_VERDICT == "error"` guard exits 1. `create_finding_issues` iterates `findings[]`, which
  is `[]` on both, so no GitHub write occurs on a failure record.
- The `unparseable` path (vendor responded with prose) is **unchanged**. That is a real review,
  not a failure, and must not be pulled into this taxonomy.

### D-5 — stderr is captured, redacted, bounded, and never silently discarded.

- The helper redirects child stderr to its own temp file — never to the terminal raw, never to
  `/dev/null`.
- On failure it derives `VENDOR_INVOKE_STDERR` as: **last 10 lines** → collapse all whitespace
  runs to single spaces → redact → truncate to **500 bytes** with a trailing `…`.
- Redaction, applied before truncation (order matters — truncating first can split a token into
  something the patterns no longer match): `gh[pousr]_[A-Za-z0-9]{20,}`,
  `github_pat_[A-Za-z0-9_]{20,}`, `sk-[A-Za-z0-9_-]{20,}`, `AKIA[0-9A-Z]{16}`,
  `ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.` (JWT), `[Bb]earer +[A-Za-z0-9._-]{12,}`, each
  → `[REDACTED]`; and `$HOME` → `~`.
- Destination: the `stderr_tail` field of the failure record in `$OUTFILE`
  (`.claudetmp/second-review/`, gitignored), **plus one line to the script's own stderr** so an
  operator watching the run sees the real cause immediately. That line is what would have saved
  the hour #1683 describes.
- **#1679 boundary.** `oversight-orchestrator` composes `handoff.md` from these artifacts, so a
  tail *could* travel toward a public surface. Redacting at the source means that even if it
  does, it is already scrubbed and ≤500 bytes — strictly better than today, where the
  alternative under consideration (raw stderr) would have made #1679 worse. Redaction at the
  *publication* boundary remains #1679's; this ADR neither solves nor worsens it. The coder must
  not add `stderr_tail` to any PR-comment or issue-body composition.

### D-6 — Temp-file hygiene via a chained trap, covering the failure paths.

The codex path's `rm -f "$tmpfile"` runs only on the success path and leaks otherwise (#1683
scope item 1). Bound:

- The helper creates all temp files under one per-process directory,
  `${TMPDIR:-/tmp}/hos_vendor_invoke.$$`.
- On **first** use it installs a cleanup trap on `EXIT INT TERM` that removes that directory.
  It must **chain**, not clobber: read any existing handler with `trap -p EXIT` and compose.
  (`run_second_review.sh`, `run_panel.sh`, and `run_red_team.sh` currently set no trap — I
  checked — but the helper is shared and must not assume that of its future callers.)
- The guard is idempotent: re-sourcing the helper, or calling it twice, installs one trap.
- `run_second_review.sh`'s own `mktemp` in the codex path is deleted; the helper owns it now.

### D-7 — Two invocation primitives, disjoint vendor sets. This is deliberate.

`claude` invocations go through ADR-1643's `bootstrap/invoke_agent.sh` /
`scripts/automation/agent_invoke_cli.py`, which carry agent resolution, posture files, and
`--settings` — concepts agy and codex do not have. agy/codex invocations go through
`vendor_invoke.sh`. Neither may grow a path into the other's vendor set. The coder puts a
one-sentence comment stating this boundary, and citing this ADR and ADR-1643 AD-16, at the top
of `vendor_invoke.sh`. Whether the two should eventually converge is a real question; it is not
this PR's, and it is not #1364's either — it belongs with whoever owns the primitive after
#1643 W4 lands.

---

## 3. (Q-B) Work list — file by file

### In scope for the #1683 PR (6 files; limits are ≤15 files / ≤10 commits)

| File | Change |
|---|---|
| `scripts/oversight/lib/vendor_invoke.sh` | **NEW.** D-2 contract; sources `run_with_retry.sh` for `with_timeout`; D-5 stderr handling; D-6 trap; D-7 boundary comment; the empirically-verified agy form. |
| `scripts/run_second_review.sh` | Migrate **both** agy calls (`~595`, `~601`) and the codex call (`~674-686`) onto `vendor_invoke`. Emit D-4 records. Drop the local `mktemp`/`rm -f`. Replace `${VALIDATOR_SUMMARY}` in the prompt with the D-3 digest. Fix the `PROMPT_CHARS` estimate at `~778` to use the digest length. Update the stale comment block at `~585-591`. |
| `scripts/oversight/second_review_logic.py` | **NEW subcommand** `digest-validators --file <path>` implementing D-3's three tiers. Pure function + thin CLI; no file I/O in the tier logic. |
| `tests/oversight/test_second_review_vendor_invoke.py` | **NEW.** §4 shell-level tests. |
| `tests/oversight/test_second_review_logic.py` | Add unit tests for `digest-validators` (tier selection at the 16,384 B boundary, `_digest_tier` present, no `evidence`/`findings`/`checklist_items` keys survive, output is valid JSON at every tier). |
| `docs/v0.7.0/ADR-1683-vendor-invocation-stdin.md` | This file. |

The codex path in the same file is migrated **even though it is already stdin-safe**: leaving
two invocation idioms in one file is how the agy path drifted in the first place, and it is
where D-6's leak lives.

### Deferred to #1364 — nine sites, all migrating onto the same helper

| File:line | Invocation | Shipped to consumers? |
|---|---|---|
| `scripts/run_red_team.sh:358` | `agy -p "$AGY_PROMPT"` | **yes** |
| `scripts/run_panel.sh:148` | `agy -p "$prompt"` | **yes** |
| `scripts/review_self.sh:248` | `agy -p "$PROMPT"` | **yes** |
| `scripts/reverify_self.sh:263` | `agy -p "$PROMPT"` | **yes** |
| `scripts/run_redteam_sample.sh:169` | `agy -p "$AGY_PROMPT"` | no (HOS-internal) |
| `scripts/capture_session.sh:168` | `agy -p "$PROMPT"` | no (HOS-internal) |
| `scripts/framework/validate_spec_compliance.sh:211` | `agy -p "$(cat "$tmpfile")"` | no — explicitly excluded by `framework_consumer_files.txt` |
| `scripts/framework/validate_docs.sh:191` | `agy -p "$(cat "$tmpfile")"` | no — same |
| `scripts/framework/validate_scripts.sh:183` | `run_capped … agy --sandbox -p "$prompt"` | no — same |

I verified each of these still reads as listed, and verified the shipped/not-shipped column
against `bootstrap/hos_install.sh`'s copy loop (`run_panel.sh run_second_review.sh
run_red_team.sh review_self.sh reverify_self.sh capture_prompt.sh prompt_audit.sh`) and
`scripts/framework/framework_consumer_files.txt` (which names `validate_*.sh` under
*"Internal HOS-dev tooling (must stay OUT of consumer installs)"*).

Notes the worker **must record on #1364** when this PR lands:

- The shared helper now exists at `scripts/oversight/lib/vendor_invoke.sh` with the D-2
  contract; #1364 is a **mechanical migration onto it**, not a design exercise. Each migration
  is: delete the local invocation, call `vendor_invoke`, map `VENDOR_INVOKE_CLASS`/`DETAIL`
  into that script's own error-JSON shape (which differs per script — `run_red_team.sh` uses
  `exploitable_findings`, `run_panel.sh` uses `die`, `validate_scripts.sh` distinguishes a
  required Opus lane from optional 3P lanes; the helper deliberately does not own these).
- `validate_spec_compliance.sh:211` and `validate_docs.sh:191` write a tmpfile and then `cat`
  it straight back into argv. Those two are near-one-line migrations and the most obviously
  armed of the nine.
- `run_panel.sh` chunks its input, so it may be under the cap *today*. #1364 must **measure**
  each site's realistic maximum as the repo grows, not assume the chunking is sufficient.
- `run_capped` in `validate_scripts.sh` and `validate_agents.sh`: ADR-1643 W4 deletes
  `validate_scripts.sh`'s copy; ADR-1643 §9.4 (ESC-D) moved `validate_agents.sh`'s to a
  follow-up. #1364's migration must not race that — coordinate, do not duplicate.
- **Flag for the human:** nine armed sites remain after this PR, in a class now confirmed live
  in production. Whether #1364 moves from `priority:high` to `priority:critical` is a
  prioritisation call for the human, not for me to make unilaterally.

---

## 4. Test requirements

All tests are **hermetic**: no test may require agy or codex to be installed or authenticated.
Follow the established stub pattern in `tests/oversight/test_red_team_fail_closed.py` and
`tests/oversight/test_second_review_request_changes_gate.py` — write an executable stub named
`agy` into a tmp `bin/`, prepend it to `PATH`, and drive the real script as a subprocess with
`cwd=tmp_path`.

**The headline regression test (required by #1683's acceptance).** The key property that makes
this testable without a vendor CLI: `E2BIG` is raised by the kernel at `execve`, *independently
of what the target binary is*. A `#!/bin/sh` stub is therefore just as unable to be launched
with a 174 KB argv element as the real agy. The test fails before the fix and passes after.

1. `test_oversized_prompt_reaches_the_reviewer_on_stdin`
   - Write `target.py` of **≥ 200,000 bytes** into `tmp_path` (not a git repo, so the script's
     `--files` cat-fallback makes it `DIFF_CONTENT`).
   - Stub `agy` as: read all of stdin; if the byte count is `> 131072`, print a clean
     `verdict: approve` review JSON; otherwise print nothing.
   - Run `bash scripts/run_second_review.sh --files target.py --step 3 --tier MEDIUM --score 0.5`.
   - Assert: exit 0; the artifact under `.claudetmp/second-review/` contains
     `verdict: approve`; and — the literal acceptance criterion — the artifact contains **no**
     `invocation failed` and no `"outcome": "invocation_failed"`.

2. `test_argv_still_carries_no_prompt_content` — the stub records `"$#"` and the length of the
   longest argument to a side file; assert the longest argv element is < 4,096 bytes. This pins
   the property directly rather than inferring it from a size threshold, so it keeps holding if
   the cap ever changes.

3. `test_vendor_nonzero_exit_is_classified_vendor` — stub exits 3 and writes a recognisable
   line to stderr. Assert the record carries `failure_class: vendor`,
   `outcome_detail: vendor_nonzero_exit`, `exit_code: 3`, a `stderr_tail` containing that line,
   and that the script exits **1** (fail closed).

4. `test_missing_binary_is_classified_harness` — no `agy` on a minimal `PATH`. Assert
   `failure_class: harness` (this may resolve via the script's existing `AGY_AVAILABLE`
   pre-check rather than the helper; either is acceptable, but the test must pin that it is
   *not* reported as a vendor failure).

5. `test_stderr_tail_is_redacted_and_bounded` — stub writes `ghp_` + 30 chars and 200 lines of
   noise to stderr. Assert `stderr_tail` is ≤ 500 bytes, is a single line, and contains neither
   the token nor the literal `ghp_`.

6. `test_no_temp_files_leak_on_failure` — point `TMPDIR` at a tmp dir, run the failing case
   (test 3), assert the directory is empty afterwards.

7. Digest unit tests in `tests/oversight/test_second_review_logic.py` per §3's row — including
   one fixture that forces tier 2 and one that forces tier 3, asserting `_digest_tier` and the
   stderr degradation line.

---

## 5. Explicitly out of scope

- **The other nine argv sites** — #1364 (§3). This PR fixes one site and builds the shared
  mechanism the rest migrate onto; it does not migrate them.
- **The mechanical/lint check that would catch a reintroduction** — #1364's "durable
  prevention". D-2's 4,096-byte argv guard covers the helper's own callers at runtime; it does
  not cover a site that bypasses the helper. That is exactly what the mechanical check is for,
  and it belongs with the sweep that has the full site inventory.
- **#1281 (`run_second_review.sh` skips a step with no audit-log range and reports "passed")** —
  a genuinely independent second reason this gate can be hollow. Do not touch it here; #1364's
  acceptance already requires verifying both.
- **#1679's redaction-at-publication boundary** — D-5 redacts at the source and does not make
  #1679 worse; it does not close it.
- **`create_finding_issues`' inline `gh issue create --title/--body`** (`~443-451`). It violates
  the repo's `--body-file`-only convention and is a (small, bounded) content-into-argv site of
  the same family. Not fixed here — the worker files it as a separate issue referencing #1364
  and `CLAUDE.md` §"Shell usage under the sandbox" item 6.
- **Any change to ADR-1643's `claude` primitive, to `bootstrap/hos_install.sh`, or to
  `framework_consumer_files.txt`** — see D-1 and D-7.
- **Any change to the `$OUTFILE` machine-readable header fields.** Prompt size is surfaced via
  the reviewer JSON block's `prompt_bytes` and via stderr. Adding a new top-level header line
  would touch a contract the evaluator and `panel_logic` readers depend on, for no benefit this
  fix requires.
