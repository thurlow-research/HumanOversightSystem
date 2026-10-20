# ADR-1605 — Two gates, not a flag; bandit's verdict comes from a file it wrote, never from a stream it decorated; dependency posture leaves the diff entirely

**Status:** ACCEPTED FOR DESIGN — binding on `technical-design`, `coder`, `unit-test`, `system-test` for issue #1605. Nothing below is advisory. Items 1–2 are **flagged for the overseer/human in the PR body** rather than gated. Item 3 (AD-12a/AD-12b: a new label and a new operator obligation) is a product-boundary item and **gates the merge of the implementation PR** on explicit human clearance.

**Amendment D-5 (2026-10-20, architect), from the human's scope ruling D-5 on #1605:** the scheduled run now pauses and alerts. It is no longer report-only. New decisions **AD-15..AD-23** are in §2b. AD-10 and AD-12 gain notes; no existing AD is renumbered. AD-22 is a new **binding sequencing finding**: Part 2 predates #1776 and must carry #1776's exemption roster. AD-23 (the ship vehicle, Q-D5-1) is a **recommendation pending the human, not a decision**. The new human items are §6 items 4–7. The affected sign-offs are in §5 under "D-5".

**Date:** 2026-09-22
**Author:** architect
**Issue:** #1605 (v0.7.0, `priority:high`). Parent #1567; per-check job pattern #1571; the vulnerabilities themselves #1504.
**Inputs:** issue #1605's body; the worker's brief (`/tmp/claude/brief-1605.md`); `docs/v0.7.0/REQUIREMENTS-1605-bandit-gate-split.md` (pm-agent, 2026-09-22, 31 ACs) — **accepted in full except where §2 states otherwise**; `docs/v0.7.0/TECHNICAL-DESIGN-1759-run-gates-diff-parsing.md` (Ruling H, row 7, gap **D4**); my own re-measurement against this branch (§0).
**Consumers:** `technical-design` → `coder` → `unit-test` / `system-test` → the review chain.
**Scope note:** pm-agent ruled **S-1 (the bandit stdout fail-open fix) IN SCOPE**, and the worker has confirmed that ruling for this cycle and will flag it in the PR body. This ADR designs against that. It does not re-litigate S-1, S-3 (promotion deferred), the non-goals, or I-1 (two scripts, not a flag) — all adopted.

---

## 0. Verification — what I re-derived myself, and the two findings that move design

I did not inherit the measurements. Run on this branch against `scripts/oversight/.venv/bin/bandit` (**bandit 1.9.4**, Python 3.12.3).

| # | Finding | Status |
|---|---|---|
| AV-1 | At 201 `.py` files, stdout begins `Working... ━━━…━ 100% 0:00:00` and the JSON written by `-o` is **clean** (`{\n  "errors": [],`). The bar and the JSON are on **different channels**, not interleaved on one. | **CONFIRMED** (pm-agent V-1/V-5) |
| AV-2 | bandit's `[main] INFO …` chatter goes to **stderr**, not stdout. So the existing `2>/dev/null` was never what protected the parse — the bar on stdout is. | **NEW** |
| AV-3 | `-o <path>` **truncates and overwrites** an existing file (seeded `STALE`, ended clean JSON). | **NEW — load-bearing for retries** (a stale file must not be readable as a fresh result; see AD-4) |
| AV-4 | rc semantics: **rc 0** = scan completed, no findings at the selected severity; **rc 1** = scan completed, findings present; **rc ≥ 2** = error/usage. Confirmed live: 202 clean files → rc 0; one B602 file → rc 1. | **CONFIRMED** |
| AV-5 | **bandit does not error on non-Python input.** `bandit -lll -o out.json README-shaped.md` → **rc 0**, `results: []`, and the file recorded in `errors` as `"syntax error while parsing AST from file"`. A file that could not be parsed is therefore reported as *scanned-and-clean* by every counter the current gate consults. | **NEW — this is a second silent-negative, distinct from S-1. See AD-5.** |
| AV-6 | **The obvious HIGH fixture is not HIGH.** `subprocess.Popen("ls", shell=True)` (literal) → **zero** results at `-lll`. `subprocess.Popen(cmd, shell=True)` (variable) → `B602 / HIGH`, rc 1. | **NEW — binding on the AC-5/AC-6 fixtures (AD-8).** A test written with the literal form would pass while proving nothing. |
| AV-7 | `contract/gate-suspension.md` does not exist in this repo (only `contract/gate-suspension.template.md`), so **no gate is suspended here** and both halves genuinely execute in every local `run_gates.sh` run. | **CONFIRMED** (brief fact 4) |
| AV-8 | `run_gates.sh:190` derives the gate name as `basename "$script" .sh`. A new gate file needs **no registration** in `run_gates.sh`, `gate_compliance.py`, or `pr_readiness.py` — none of them carries a hardcoded gate list. | **CONFIRMED** (S-4 holds by construction) |
| AV-9 | `ensure_venv.sh` installs `requirements*.txt` **by default**; `HOS_SKIP_PROJECT_REQUIREMENTS=1` exists specifically so a job building the venv from **content it does not control** (a PR head, #1380) opts out. | **CONFIRMED — load-bearing for AD-12** |

**AV-5 and AV-6 change the design.** AV-5 adds a required fail-closed branch nobody had specified (a `.py` bandit could not parse is currently indistinguishable from a clean one). AV-6 changes the test fixtures — without it, AC-5 and AC-6 would be written, pass, and pin nothing.

**One correction to the brief.** The brief calls stdout-contamination "the obvious fix … `-o`". It is, but the brief's framing ("bandit emits a progress bar *before* the JSON") suggests the JSON and the bar share one stream and could be separated by scrubbing. AV-1 shows they do not share a stream once `-o` is used. That distinction is why AD-3 forbids scrubbing outright rather than treating it as a weaker alternative.

---

## 1. Context — what is actually being fixed

Three defects are braided together in one file, and the issue only names one:

1. **Structural (the issue's ask).** `security_scan.sh` bundles a deterministic, file-scoped, offline check (bandit `-lll`) with a network-dependent, repo-scoped one (`pip-audit`). The bundle is why neither reaches CI.
2. **Fail-open (S-1).** The bandit lane parses **stdout**, which bandit decorates with a progress bar once the scan exceeds roughly a second — a *duration* trigger (pm-agent V-2), i.e. exactly the condition a shared CI runner maximises. Parse fails → `|| echo "0"` → `OK: no HIGH severity findings`.
3. **Silent-negative on unparsed files (AV-5, new).** Independently of (2), any file bandit cannot parse is counted as scanned-and-clean.

(2) and (3) are the same governance defect in two costumes: **the gate manufactures affirmative evidence of safety it did not gather.** pm-agent's S-1 reasoning ("a green that is not evidence") applies to (3) verbatim, so (3) is in scope under S-1's own bound (b) — "fail-closed handling when that JSON is unparseable" — read as what it must mean: *the verdict must be derived only from files bandit demonstrably scanned.* This is a one-branch addition, not a re-audit of the gate (which S-1 excludes).

---

## 2. Decisions (BINDING)

### AD-1 — Two gate scripts. Names and suspension keys, final.

pm-agent's I-1 (two scripts, not a flag) is **upheld**, and I-2's non-binding naming is **adopted as binding**, with the key for the new half named here:

| | Script | Gate name (`gate-results.json`, from AV-8) | Suspension key | Scope | In `FILE_LIST_GATES`? |
|---|---|---|---|---|---|
| Bandit half | `scripts/oversight/gates/security_scan.sh` (**modified, not renamed**) | `security_scan` | `security` (**unchanged**) | file-scoped | **yes** (unchanged) |
| Dependency half | `scripts/oversight/gates/dependency_audit.sh` (**new**) | `dependency_audit` | `dependencies` (**new**) | repo-scoped | **no** |

Rationale for not renaming the bandit half: every pinned list (`FILE_LIST_GATES`, `DEFAULTING_STRING_GATES`), both #976 tests, the `security` suspension key and its reviewer-role counterpart in `docs/OVERSIGHT-RUNBOOK.md:149` already point at the half that keeps needing them. A rename would edit four registries to relocate a name and would leave the `security` key — the one with a reviewer-role twin — attached to the *network* half, which is the half a reviewer's sign-off has nothing to do with.

`dependencies` follows the existing key vocabulary (`lint`, `secrets`, `types`, `template-refs`, `portability`, `django`): subject noun, hyphenated only when multiword. **Neither key is added to `AUTO_CHECKABLE_GATES`** (AC-7; `security`'s exclusion is deliberate, and `dependencies` is network-dependent so a pass is not reproducible on demand). The CI job is **`oversight-gate-security-scan`**.

### AD-2 — `dependency_audit.sh` is **repo-scoped**, and repo-scoped means the `django_check.sh` shape exactly.

> **AMENDED 2026-09-22 by AD-2a (§2a) — the second paragraph of this decision is REVERSED.** The gate
> honours the explicit `--empty-changeset` token and skips (NOT CHECKED, exit 0). The first paragraph
> (repo-scoped, file arguments ignored) stands unchanged. Read AD-2a before implementing this.

AC-10 upheld. It takes no file arguments, ignores `"$@"`, does **not** source `changeset.sh`, and does **not** call `hos_changeset_parse`. It checks suspension first (`is_suspended "dependencies"`), then runs. It prints one line stating that it is repo-scoped and that any arguments are ignored — a reader who types `dependency_audit.sh foo.py` must not be left to infer that.

~~Consequence, ruled and accepted: `run_gates.sh --empty-changeset` (and any empty resolution) now reaches this gate, where the bundled version short-circuited.~~ **REVERSED by AD-2a.** The rest stands: this **supersedes** the INV-SELECTOR comment in today's `security_scan.sh` ("STATUS=empty skips pip-audit too … keeps the empty path fast and side-effect-free") *as a statement about a file-scoped gate's changeset status*; AD-2a re-establishes the same observable behaviour on a different and narrower basis (an explicit runner mode signal, not a file-count inference). `technical-design` must carry that distinction into `dependency_audit.sh`'s header, not delete the rationale silently.

---

## 2a. AD-2a — AMENDMENT: the gate honours `--empty-changeset` and skips. AD-2's unconditional clause is reversed.

**Raised by:** the coordinator, after implementation, on a failing pre-existing test that neither I nor `technical-design` found: `tests/oversight/test_run_gates_artifact.py::test_empty_changeset_full_run` (TC-A2, #1759).

**RULING: option (b). `dependency_audit.sh` skips on the explicit `--empty-changeset` token.** Do not narrow TC-A2. Do not add a 15th file.

### Why the invariant wins

1. **TC-A2 is not incidental scaffolding; it is the pin for #1759's TD-D8/TD-D9 contract** — "a run in which nothing was checked is exit 0, is explicitly *not* a pass, and no gate fell into its full-project default." Its `exit_code == 0` clause is the *proxy that detects a gate quietly whole-repo-scanning on the empty path*. Narrowing it to exempt repo-scoped gates would not just accommodate my gate — it would permanently remove that detector for every future repo-scoped gate. I am not spending a live invariant to buy a signal I am simultaneously moving to a weekly workflow.

2. **The pattern "my new artefact breaks a pinned invariant, so I narrow the invariant" is the exact failure this pipeline exists to catch**, and it is disqualifying unless the invariant is *wrong*. It is not wrong. `run_gates.sh` returning 1 on a run that checked nothing is indistinguishable, to every caller (`pr_readiness._check_gates` among them), from a run that checked something and found a defect. That is a false *negative* signal, the mirror of the false green this whole PR exists to remove. I will not introduce one while removing the other.

3. **My own AD-2 rationale does not actually reach this case.** "Dependency posture is not a property of a diff" is an argument against *scoping by file list* — which is why the gate still ignores every path argument. `--empty-changeset` is not a file list and not a diff scope: per TD-D9 it is the runner's explicit declaration that *this entire invocation verifies nothing*. Honouring a mode signal is not inferring scope from a file count. I conflated the two when I ruled, and the conflation is mine, not `technical-design`'s.

4. **`technical-design`'s objection is answered, not overridden.** "An environment verdict must not change because a step deleted files" is right, and under this amendment the verdict does not change *to green* — it changes to **NOT CHECKED**, in TD-D7's own vocabulary, inside a run that already prints `GATE NOT RUN: … nothing was checked (this is not a pass)`. No evidence of dependency safety is manufactured anywhere on this path. Had the skip produced a `GATE PASS`, I would have ruled the other way and taken the 15th file.

5. **The lost signal is ~zero, and by this PR's own design.** The only runs affected are those where nothing changed. Authoritative dependency posture now comes from `dependency-audit.yml` (AD-10) on a fixed weekly cadence that does not care whether anyone committed anything. That is the entire point of #1605: dependency posture left the diff. Having left it, the local gate need not fire on a no-op run to preserve it.

6. **Coordinator's point 2 sharpens this rather than weakening it.** TC-A3 already concedes that shared-venv advisory noise pollutes gate verdicts on the *non-empty* path. The empty path is the one surface deliberately kept clean of that noise. Extending the pollution to it would leave #1759 with no clean path at all.

### The exact change (binding)

In `scripts/oversight/gates/dependency_audit.sh`, **after** the `is_suspended "dependencies"` check and **before** any pip-audit work:

- Scan `"$@"` for the **literal token `--empty-changeset`**. If present: print
  `dependency_audit: NOT CHECKED — empty changeset (nothing was checked; this is not a pass)` and `exit 0`.
- **Only that token suppresses the run.** A bare no-argument invocation (`bash gates/dependency_audit.sh`) must still **run** — that is a direct operator call, not a runner no-op declaration, and it is how the gate is invoked from the runbook. Zero-argv must never be read as empty-changeset.
- Every other argument stays ignored, exactly as AD-2's first paragraph says. Do **not** source `changeset.sh`; do **not** call `hos_changeset_parse`. The message string deliberately mirrors `hos_changeset_not_checked`'s vocabulary (TD-D7/TD-D8) without taking the dependency; a comment must say so, so a later reader does not "fix" it into a parse call.
- Header comment must record *why*: the skip is on the runner's explicit mode signal, not on a file count — the distinction that makes this compatible with "dependency posture is not derived from a diff".

**TC-A2 is not touched.** `outcome` / `changeset_mode` / `files_forwarded` are runner-derived (coordinator's point 3) and stay correct; `exit_code` returns to 0; overall rc returns to 0. **No 15th file.**

**Two test cases** go in the already-budgeted `tests/oversight/test_security_scan_split.py`, using the `HOS_PIP_AUDIT_BIN` seam (AD-6) pointed at a stub that touches a marker file when invoked:

| Case | Assertion |
|---|---|
| `dependency_audit.sh --empty-changeset` | rc 0; `NOT CHECKED — empty changeset` present; **marker file absent** (pip-audit never invoked); no `GATE PASS` line |
| `dependency_audit.sh some/file.py` | marker file **present** — a path argument is ignored, not read as a scope, and does not suppress the run |

### Downstream record-keeping

- **This ADR:** amended in place (above). AD-2's reversed clause is struck, not deleted — the reasoning trail is the point.
- **`TECHNICAL-DESIGN-1605`:** must carry AD-2 **as amended**. Its "reason 2 — the newly-red surface is narrower than it looks" paragraph is **withdrawn**; replace it with AD-2a's reasoning. A design that still argues for the unconditional run is building against a superseded ruling.
- **`DECISIONS.md` (commit 9):** the entry must record the reversal explicitly — that AD-2 first ruled the gate unconditional, that TC-A2 pinned the opposite, and that the invariant was upheld rather than narrowed. A silent reversal teaches a future reader nothing; the near-miss is the instructive part.
- **`docs/OVERSIGHT-RUNBOOK.md`:** the AD-14 note changes. It no longer says "an empty-changeset run now makes a network call"; it says the gate is repo-scoped, ignores path arguments, and skips only the runner's explicit empty-changeset no-op run.
- **`pm-agent`, for the record (not a gate):** AC-10's *consequence paragraph* ("a local `run_gates.sh` run on an empty changeset now makes a network call where it previously short-circuited … MUST be noted in the runbook") is superseded. AC-10's binding MUST — ignore file arguments, resolve its own applicability — is fully satisfied. This is the conservative direction (status-quo-preserving), so it does not need product clearance before proceeding; it is flagged in the PR body under §6 item 2, which is **downgraded accordingly**: there is no longer a newly-reachable red on the empty path.

### Startup-gap note

Yes — this should have been settled in the initial ruling. The gap is that I reasoned about *live behaviour* ("marginal in practice") on a path that had an *explicit test*, and did not grep the artifact suite for it. The corrective is narrow and already applied here. **Affected sign-offs:** nothing approved elsewhere was built against AD-2's reversed clause — the implementation is unmerged and no reviewer has signed off on it, so there are no orphaned approvals. `technical-design`'s reason 2 is the only downstream artefact carrying the superseded reasoning, and it is withdrawn above.

### AD-3 — The JSON acquisition channel is **`-o <file>`**. Stdout is never read. Scrubbing is forbidden.

`bandit -f json -lll -o "$BANDIT_JSON" "${FILES[@]}" >/dev/null 2>"$BANDIT_LOG"`.

- **Stdout is redirected to `/dev/null` and is never parsed, filtered, stripped, or regexed.** Any design that reads stdout and removes a prefix is rejected: it makes correctness depend on matching an undocumented, version-specific rendering (Rich's bar is TTY-, width- and locale-sensitive), i.e. it re-creates the defect with an extra step. AV-1 shows the two channels are already separate; we simply stop reading the wrong one.
- **stderr goes to a log file, not `/dev/null`** (AV-2 — it is where bandit's diagnostics actually are). On any failure branch the gate prints the last few lines of that log. Today's `2>/dev/null` discards the only evidence of why a run failed.
- The gate **must not** use `>` to a temp file plus a stdout parse in any form, and **must not** contain the string `|| echo "0"` (or any default-on-parse-failure constant) anywhere. This is a construction rule on both gate files (S-2).

### AD-4 — The fail-closed contract, and exactly how it sits inside `run_with_retry`.

The unit of work is `_run_bandit`. It succeeds **only** when all of the following hold; anything else is a failed attempt:

1. rc ∈ {0, 1} (AV-4 — rc 1 is a *successful scan with findings*, never a crash);
2. the `-o` file parses as JSON;
3. the parsed object has a **list** `results`, a **dict** `metrics`, and a **list** `errors`;
4. the single extraction step (below) emits three integers.

Mechanics `technical-design` must implement:

- **Truncate the output file at the top of every attempt** (`: > "$BANDIT_JSON"`). AV-3 shows bandit overwrites on a completed run, but a timeout-killed attempt may leave attempt *N-1*'s file in place; reading that as attempt *N*'s result is a fail-open through the back door.
- **One extraction, not three.** A single `$OVERSIGHT_PYTHON` invocation reads the file and prints exactly `high=<int> errors=<int> scanned=<int>` (where `scanned = len(metrics) - 1`, excluding `_totals`). The shell validates all three against `^[0-9]+$` **before** any numeric comparison. Rationale: `[[ "" -gt 0 ]]` evaluates false — an empty capture is a silent pass. Three separate `python -c` pipes are three chances to fail open; one is one chance, and it is guarded.
- **Record the attempt's rc in `BANDIT_LAST_RC`** (the `DS_LAST_RC` pattern from #1759 Ruling H), and map "completed but unparseable/unextractable" to a distinct synthetic rc (**65**) so exhaustion can name the true cause. Preserve **124** so `run_with_retry` logs `timeout`.
- `run_with_retry "bandit" "$GATE_RETRIES" "true" _run_bandit` — `required=true`, unchanged.
- Retrying rc 65 is accepted (at most two extra scans, bounded by `GATE_TIMEOUT`) for uniformity with the pip-audit lane's existing "expected rc **and** valid JSON" precedent in the same file. Do not special-case it.

On exhaustion, the gate exits **non-zero** with one of three messages — all three must be distinguishable, and **none of them may be reachable from a path that also prints an OK line**:

| Cause | Message |
|---|---|
| `BANDIT_LAST_RC == 2` | `GATE FAIL: bandit rejected its arguments (exit 2 — a usage error, not tool flakiness). Nothing was scanned; do not retry.` |
| `BANDIT_LAST_RC == 65` | `GATE FAIL: bandit completed but its JSON output could not be parsed — nothing was verified. Zero findings are NOT inferred from a parse failure.` |
| otherwise (124, other) | `GATE FAIL: bandit did not complete after retries` |

The exit-2 split closes #1759's row-7 item, which was specified there and never landed; it is message-only (both paths already fail) and costs one branch plus one stub test.

### AD-5 — A file bandit could not parse is a **scan failure**, not a clean file. Two parts.

1. **Filter the changeset to Python first.** `security_scan.sh` joins `KIND_FILTER_GATES` with kind `"Python"`, emitting `hos_changeset_skip_kind security_scan Python <matched>` (exit 0) when no supplied file is `.py`. Without this, CI would hand every `.md` in a docs PR to bandit and part (2) would go red on every documentation change. With it, anything left in `errors` is a file we *intended* to scan.
2. **Non-empty `errors` ⇒ `GATE FAIL`**, listing `filename: reason` per entry: `GATE FAIL: bandit could not scan N file(s) — these were not checked.` (AV-5).

And the green line must be evidence, not an assertion: `OK: no HIGH severity findings (<scanned> file(s) scanned, 0 unscannable)` — where `scanned` comes from **bandit's own `metrics`**, not from our argv length. A gate that reports what it actually covered cannot quietly cover nothing.

Add `"security_scan": "Python"` to `KIND_FILTER_GATES` in `tests/oversight/test_gate_arg_grammar.py`. `FILE_LIST_GATES` and `DEFAULTING_STRING_GATES` are unchanged — the `--all`/no-selector project enumeration (`find . -name "*.py"`) stays exactly as it is, so AC-3's two #976 cases are untouched.

### AD-6 — `dependency_audit.sh` stays **blocking on findings** locally. The ratchet decides this, not convenience.

`suspension_manager.py`'s RATCHET PRINCIPLE: the system may auto-tighten, never auto-loosen, and **suspension is the only sanctioned loosening path** — a human-written `SUSPENDED:` line, with a `review-by` date, visible to `--census`. Converting today's blocking `GATE FAIL: N dependency vulnerability(ies) found` into a warning inside a refactor PR is an auto-loosening performed by the system on its own authority, with no suspension record, no expiry and no census visibility. It is exactly the move the principle exists to forbid. **Findings ⇒ exit 1, unchanged.** (AV-7: nothing is suspended in this repo, so this is live behaviour today, and it stays live.)

Two refinements that are *not* loosenings:

- **Execution failure remains non-blocking** (`run_with_retry … "false"`, as today) — a missing network must not fail an offline developer's inner loop. But the final line changes from today's `GATE PASS` to **`GATE NOT RUN: dependency audit did not complete — nothing was checked (this is not a pass)`**, exit 0. Same exit code, honest sentence. This is #1759's TD-D8 vocabulary applied to the new artefact (S-2 construction requirement), not a behaviour change.
- The same no-default-constant rule as AD-3/AD-4: the vulnerability count comes from one guarded extraction; `|| echo "0"` does not appear.

Seam: **`HOS_PIP_AUDIT_BIN`**, same contract as AD-7 — required, because the NOT-RUN branch is otherwise untestable without disabling the network.

### AD-7 — The test seam is `HOS_BANDIT_BIN`, and it closes #1759's **D4** by name.

Precedent is `HOS_DETECT_SECRETS_BIN` (#1759 Ruling H) and the successor action D4 already names this seam. Resolution order, **no PATH fallback** (today's gate is venv-only; adding a PATH fallback would change what runs in the real pipeline and is out of scope):

```
BANDIT_BIN=""
if   [[ -n "${HOS_BANDIT_BIN:-}"   ]]; then BANDIT_BIN="$HOS_BANDIT_BIN"
elif [[ -x "$VENV_BIN/bandit"      ]]; then BANDIT_BIN="$VENV_BIN/bandit"
fi          # else: the existing SKIP line, unchanged
```

Header comment must say, as `secret_scan.sh` does: off by default, inert in the real pipeline, present only so the fail-closed branches can be pinned. **Inertness is itself a test case** (the #1759 TC-P6 twin).

### AD-8 — Stub contract for AC-4/AC-5 (binding on `unit-test`; a wrong stub proves nothing).

The stub is a short shell script that **parses its own argv for `-o <path>` and writes there**. That is not incidental — a stub that writes only to stdout would make a *correct* implementation fail, and would make an incorrect one pass for the wrong reason.

| Case | Stub behaviour | Required assertion |
|---|---|---|
| **AC-5** (the defect, pinned) | print `Working... ━━━━ 100% 0:00:02` to **stdout**; write fixture JSON containing **one HIGH result** to the `-o` path; exit **1** | `GATE FAIL`, the finding's `file:line [B602]` named, rc ≠ 0. Faithful to AV-1: real bandit puts the bar on stdout and the JSON in the file. |
| **Contamination immunity** | write valid `results: []` JSON to `-o`; write a *HIGH-finding* JSON to **stdout**; exit 0 | `OK: no HIGH severity findings (… scanned)`, rc 0 — proves stdout is never consulted. |
| **AC-4** (unparseable) | write `not json` to the `-o` path; exit 0 | rc ≠ 0; the AD-4 rc-65 message present; **`OK: no HIGH severity findings` absent**; `did not complete after retries` absent. |
| **Exit 2** | write nothing; exit 2 | rc ≠ 0; the usage-error message present; `did not complete after retries` absent. |
| **AV-5 errors** | write JSON with `results: []` and one `errors` entry; exit 0 | rc ≠ 0; `could not scan` present; no OK line. |
| **Inertness** | seam unset | real venv resolution used (skip-guarded on bandit's presence). |

**AC-6** (real-bandit positive control) uses `subprocess.Popen(cmd, shell=True)` with a **variable** command (AV-6) padded out with ~200 generated `.py` files, marked slow/opt-in, and **must not** gate CI on timing.

### AD-9 — The CI job: `oversight-gate-security-scan`, file-scoped, wired but not required.

Step-for-step identical to the existing file-scoped jobs (AC-12): checkout PR head `fetch-depth: 0`, Python 3.12, `ensure_venv.sh` with **`HOS_SKIP_PROJECT_REQUIREMENTS: "1"`** (#1380 — the PR head is content we do not control), fetch base, `git diff --name-only "origin/$BASE...HEAD"`, skip cleanly on empty, then `bash scripts/oversight/gates/security_scan.sh "${FILES[@]}"`. `permissions: contents: read` is inherited from the workflow's top-level block; the job adds none.

> **Note (2026-10-14, security design review M-2/S-1).** "Step-for-step identical" is amended: `oversight-gate-security-scan` **deliberately diverges** from its file-scoped siblings in exactly two ways, and no others. (1) It adds a **scanner-presence assertion step**, which fails the job if bandit is absent from the venv, so a missing scanner cannot pass as a clean scan. (2) It lists changed files with **`git diff -z`** read through **`mapfile -d ''`** (NUL-delimited) rather than `git diff --name-only` with newline splitting. The primary reason is git's default path quoting (`core.quotepath`): without `-z`, a path containing non-ASCII bytes is emitted C-quoted (wrapped in double quotes, with octal escapes), so a non-ASCII `.py` file no longer ends in `.py` and is skipped as non-Python (TD §10.1 SEC-M2, TD R-5). `-z` disables that quoting, and also passes filenames containing whitespace or newlines intact. The siblings' listing defect (`core.quotepath` quoting plus unquoted, newline-split handling) is **not** fixed here. It is recorded as residual **R-5 (#1812)** and remains out of scope for this PR.

The header's per-gate debt baseline gains (AC-14) — and the measurement method is part of the entry, because a bare "zero debt" is indistinguishable from a fail-open reading:

> `oversight-gate-security-scan` — zero debt: **0 HIGH findings over 219 tracked `.py` files, measured 2026-09-22 through bandit's `-o` file channel** (not stdout, which is progress-bar contaminated — see DECISIONS.md, #1605). Not promoted to required: #1605 wires, promotion is its own decision (F-1).

`setup_branch_protection.sh` is **not** touched (AC-15). **`dependency_audit.sh` must not appear in `oversight-gates.yml`** at all (AC-11) — that workflow is deterministic, offline-only.

Known inherited residual, not introduced here: a PR whose diff is *entirely deletions* makes every file-scoped job exit 3 (#1759 RISK-1 / D5). The new job inherits it; do not attempt to fix it in this PR.

### AD-10 — The scheduled workflow is **two jobs**, and the split is the trust boundary.

`.github/workflows/dependency-audit.yml`, `name: Dependency audit (scheduled)`.

```
on:
  schedule: [{ cron: "17 6 * * 1" }]   # weekly, Monday 06:17 UTC (I-5; off the :00 congestion peak)
  workflow_dispatch:                    # NO inputs (AD-11)
permissions:
  contents: read                        # top-level floor
concurrency:
  group: hos-dependency-audit
  cancel-in-progress: false             # never interrupt a run mid-write
jobs:
  audit:    # permissions: contents: read      — installs third-party wheels, holds NO write scope
  report:   # permissions: contents: read, issues: write — needs: audit; installs nothing
```

- **`audit`** builds the oversight venv **without** `HOS_SKIP_PROJECT_REQUIREMENTS` (AV-9: a `schedule` run checks out the *default branch*, which is content we do control; and the measurement must equal what a developer's local `dependency_audit.sh` reports, which is a venv with `requirements*.txt` installed). It runs `pip-audit --progress-spinner off --format json` to a file, handling rc explicitly — **rc ∈ {0,1} continue, anything else fail the job** — and uploads the JSON as an artifact.
- **`report`** downloads the artifact and runs the reporting module with `GH_TOKEN: ${{ github.token }}`. It is **stdlib-only plus the preinstalled `gh`**: no `pip install` runs in the job that holds `issues: write`.
- **The artifact is inert data, or the split protects nothing** *(amended 2026-10-14, security design review M-1)*. The artifact is produced by the job that executed third-party wheel code, so it is untrusted input to the job that holds `issues: write`. `report` downloads it to a dedicated directory **outside the checked-out workspace** (never the default `path:`, never the repo root or any directory on `sys.path` / the module's cwd), and reads **exactly one file from it, the pip-audit JSON, by its fixed name**, as data. Nothing in the artifact is executed, sourced, imported or extracted over the tree. A download into the workspace would let the artifact overwrite tracked code or shadow a module that `python -m` then imports: code execution with the write token, i.e. the single-job hazard reinstated through the back door.
- `cancel-in-progress: false` (AC-19): cancelling a run that is mid-write is precisely how a body update lands without its comment.
- *(Note, D-5, 2026-10-20.)* The workflow gains a third job, `outcome`, and the `audit` job also computes the roster verdict. AD-15 and AD-16 govern both. Nothing above changes: the trust split, the artifact rule and the `needs:` edge all stand.

**Why two jobs and not one.** `pull_request_target`'s hazard is not the trigger name; it is *write-scoped token + attacker-influenced code in one job*. A `schedule` trigger avoids the second half only as long as nothing untrusted enters the job — and `pip install -r requirements*.txt` executes third-party build backends from PyPI. One job would put arbitrary wheel code in the same process tree as an `issues: write` token. Splitting confines dependency execution to a read-only-token job and confines the write token to a job that installs nothing — **provided** the artifact crossing between them is handled as inert data (bullet above). It also makes **AC-25 hold for an honest failure without relying on `report`'s own logic**: if `audit` fails for any reason (network, timeout, unparseable output), `report` never runs, so a permanent *honest* failure can never read as "all vulnerabilities fixed" and auto-close the issue. Cost: one artifact round-trip.

**Residual risk, accepted, stated plainly (M-1).** The `needs:` edge is fail-closed only against an `audit` job that fails *honestly*. It is not a defence against a *compromised* `audit` job. Wheel code running in `audit` can write a well-formed pip-audit JSON with zero vulnerabilities, let the job succeed, and `report` will then close the tracking issue as "all fixed". No job topology prevents this, because `audit` is by construction where the measurement happens. It is mitigated, not eliminated, by strict field validation of the artifact in `report` (security review S-4, specified in the TD): a document that does not match the expected schema exactly is unparseable input ⇒ exit non-zero, zero writes (AD-12). A schema-valid empty report still passes. The worst case is a false close of the tracking issue, which is visible in the issue's history and reverses itself on the next honest run. The write token itself is not reachable from `audit`.

### AD-11 — `workflow_dispatch` takes **no inputs**, and the workflow never checks out a non-default ref.

Dispatch is mandatory (AC-17 — a workflow you can only exercise by waiting a week is unreviewable). It is also the only operator-influenced surface on a write-scoped workflow, so it carries zero inputs: no ref, no issue number, no dry-run flag. Nothing in either job may consume `github.event.inputs`, `github.head_ref`, or any fork-controlled value.

### AD-12 — The reporting logic is a **Python module**, not bash in the workflow, and it never touches the network itself.

`scripts/automation/dependency_audit_report.py` — stdlib-only, importable (not subprocess-only), CLI-guarded, invoked as:

```
python3 scripts/automation/dependency_audit_report.py \
    --pip-audit-json <path> --owner <o> --repo <r> [--dry-run]
```

**It takes JSON in; it does not run `pip-audit`.** Acquisition belongs to the `audit` job (AD-10). The module's only outbound calls are GitHub writes.

Required decomposition (this is what makes AC-28 true rather than aspirational):

| Function | Purity | Role |
|---|---|---|
| `normalize(pip_audit_json) -> set[tuple]` | pure | `(name, installed_version, vuln_id, tuple(sorted(fix_versions)))`, order-insensitive (AC-20's comparison unit, fix versions included deliberately) |
| `render_body(findings) -> str` | pure | marker + prose + the state block |
| `parse_state(body) -> set | None` | pure | recovers the previous set; `None` = unreadable |
| `diff(old, new) -> (added, removed)` | pure | AC-22's delta |
| `reconcile(new, issue, writer) -> Plan` | I/O via injected `writer` | decides; every write goes through `writer` |

Tests inject a **recording fake writer** and assert AC-21 as *zero recorded calls* — not "no visible change".

`--dry-run` prints the plan and performs no writes; it exists so a reviewer can exercise the whole path against a fixture.

**Idempotence mechanics (binding):**

- **Marker** `<!-- hos-dependency-audit -->` on the issue body's first line. ~~Identity is the marker, never the title (AC-20).~~ **SUPERSEDED by AD-12a:** identity is the `dependency-audit` **label AND** the first-line marker, both required; the marker alone authenticates nothing. Never the title (AC-20 — unchanged).
- **State block**: a fenced ```json``` block delimited by `<!-- hos-dependency-audit:state -->`, holding the sorted normalized set. Comparison reads the block, never the prose. A **missing or unparseable** block is `None` ⇒ treat as *unknown*, perform a full update and say so in the comment. **Never** treat unknown as empty-and-clean.
- **Lookup** *(amended 2026-10-14 by AD-12a's "Lookup bound" ruling, cross-vendor second review CWE-400)*: ~~`GET /repos/{o}/{r}/issues?state=all&per_page=100`, paginated, **hard cap 50 pages**, entries carrying a `pull_request` key discarded, each entry then tested against AD-12a's two-condition predicate (the listing itself stays **unfiltered** — no `?labels=` — see AD-12a).~~ *(The struck text is the 2026-10-14 AD-12a wording, which had already superseded the original "marker matched in the body".)* `GET /repos/{o}/{r}/issues?state=all&labels=dependency-audit&per_page=100`, paginated, **hard cap 50 pages**, entries carrying a `pull_request` key discarded, and **every returned entry** then tested against AD-12a's two-condition predicate. The server-side label filter **only narrows the candidate set and is never trusted on its own**. The in-code predicate stays the authenticator. **`gh search` is forbidden** — `github.py` excludes Search by design, and search-index lag would let a run miss an existing issue and create a duplicate, permanently breaking AC-20. No `creator=` filter: its semantics for `github-actions[bot]` are not something I am willing to bet AC-20 on. ~~and 18 cheap REST calls a week is not a cost worth that risk.~~ With the label filter, a normal run makes one list call.
- **Fail-closed on ambiguity, in both directions:** cap reached without a match ⇒ **exit non-zero, zero writes** (never create — a create on an uncertain lookup is the duplicate). The cap now bounds the **label-filtered** collection, which only triage-capable actors can grow (AD-12a "Lookup bound"). **More than one match ⇒ exit non-zero, zero writes** (a duplicate already exists; a human resolves it). Per AD-12a, "match" means an issue satisfying **both** conditions; marker-only and label-only issues are not counted.
- **Write ordering** — comment **before** body, state block written **last**, `state` transitions last of all:
  - changed set: comment(delta) → update body(+state) ;
  - zero findings: comment(closing) → update body(empty state) → `state: closed` ;
  - findings return: `state: open` → comment(delta) → update body(+state).
  The invariant: an interrupted run must leave the *state block stale*, never the *notification missing*. A stale block re-fires the same delta next week (one duplicate comment); a missing comment is a permanently lost signal. Duplicate-notification is the safe direction.
- **Title** (cosmetic, never matched): `Dependency vulnerabilities — pip-audit (scheduled report)`. ~~**No labels** (AC-26)~~ **SUPERSEDED by AD-12a/AD-12b:** the issue carries exactly one label, `dependency-audit`, applied on create and verified. Still **no pending-actor label** (AC-26's `needs-ai` concern stands). Body cross-references #1504 (unchanged).
- **Unparseable input** ⇒ exit non-zero, zero writes (defence in depth behind AD-10's job split).
- *(Note, D-5, 2026-10-20.)* The report module is **unchanged by D-5**. The tracking issue still holds the **full** normalized set, exempted advisories included (AC-20..AC-24 unchanged, as pm-agent ruled). Hold decisions use the **partitioned** set (AD-15). The two sets differ on purpose. While any exempted advisory is reported, the issue stays open and the pipeline is not held. That is correct, because black and mcp are still vulnerabilities, tracked in #1961 and #2120. On a `NOT_RUN`, the module makes zero writes, as before (AC-25). Whether it should write a status is Q-D5-2, and AD-15 is built so that either answer fits without a redesign.

### AD-12a — AMENDMENT: the `dependency-audit` label is the **authenticator**. Adoption requires label AND first-line marker.

*Added 2026-10-14, recording a ruling the implementation adopted on 2026-09-22 (branch `worker-1605-gate-split-impl-260922213001-2366083`, reviewed at `f5c1c227f`; current branch tip `b9c342559` is an amended rewrite of that commit — see §5) in response to security-reviewer round 3/4's HIGH (CWE-345 / CWE-863). It **supersedes** AD-12's marker-only identification and REQUIREMENTS AC-26's "no new label" wherever either is stated.*

**What was wrong with AD-12 as written.** The marker is a public constant — it is committed in `dependency_audit_report.py`. Any predicate over the issue **body** (marker anywhere, marker on line 1, the state block, the title) is therefore forgeable at zero cost by anyone who can open an issue in this repo. Tightening the match to "marker on the first line" fixed a reader/writer mismatch but not the exploit: an attacker authoring a fresh issue puts the marker on line 1 for free. Two consequences, both live under AD-12 as originally written:

1. **Repeatable DoS.** One planted decoy next to the real issue ⇒ two matches ⇒ AD-12's fail-closed-on-ambiguity rule exits non-zero every week. The vulnerability report stops, and the only signal is a red Actions run.
2. **Hijack.** Before the first scheduled run, or after a human closes the real issue, a planted decoy becomes the adopted issue; the `issues: write` token then rewrites its body weekly and eventually force-closes it.

AD-12's fail-closed ambiguity rule was correct for *accidental* duplicates and turned into the attack surface for *deliberate* ones. That is the defect.

**The ruling (binding):**

- `find_tracking_issue` adopts an issue only when it carries the **`dependency-audit` label** (exact, case-sensitive name match) **AND** has the marker as the body's **first line** (`splitlines()[0].strip() == MARKER`; tolerates CRLF and trailing whitespace, never leading prose). Both conditions are required; neither alone matches.
- The **label is the authenticator**. Applying a label requires triage/push rights on the repo, and GitHub **silently drops** labels supplied on issue create by a token without push access — so an outside account cannot self-apply it, whether through the UI or the API. The **marker is the round-trip check** that the adopted issue is shaped like one `render_body` wrote; it no longer carries identity on its own.
- **Ambiguity is counted only over doubly-qualified issues.** Unlabelled marker decoys are filtered out before the count, so they can neither raise `AmbiguousTrackingIssue` nor block the first-run create. `AmbiguousTrackingIssue` is now reachable only by two labelled-and-marked issues — that is, by triage-capable actors. It is a human-coordination problem, not an externally reachable DoS. *(Amended 2026-10-14: this held for the **count** of decoys, not their **volume**. Over an unfiltered listing, enough unlabelled issues exhausted the page cap and blocked the first-run create. The "Lookup bound" ruling below closes that.)*
- ~~The label is checked **in the predicate, not pushed into the query.** The lookup stays the unfiltered `state=all` listing of AD-12. A server-side `?labels=` filter buys no security, because the decoy is rejected by the predicate either way, and it would change the HTTP surface whose `[]`-vs-raise semantics let the first-ever run create the issue. The listing is unchanged; only the adoption rule is tighter.~~ **SUPERSEDED 2026-10-14 by "Lookup bound" below.** The label is checked in the predicate **and** pushed into the query. The query narrows the candidates, and the predicate authenticates them.
- An issue with no `labels` key, or with junk entries, **fails closed** (it is not adopted). Both GitHub's `[{"name": …}]` shape and a bare-string list are accepted. One shared helper (`_label_names`) serves both the read path (AD-12a) and the write-verification path (AD-12b), so the two cannot drift.

**Residual risk, accepted, stated plainly.** AD-12a does not stop an actor who **already has triage rights**. Such an actor can plant a labelled, first-line-marked issue, which either causes ambiguity (exit non-zero, a human resolves it) or gets adopted before the first run or after a closure. I accept this residual for this repo and this tier, because it grants no new authority: anyone with triage rights can already edit, relabel or close the real tracking issue directly. Squatting gains them nothing they did not have. The threat set has moved from "anyone with a GitHub account" to "an actor the repo already trusts with triage". Further hardening (author-identity pinning) is **#1812 item 5**. It is not a precondition for merge.

**Residual risk, confused deputy (security design review S-3).** The previous paragraph understates the triage residual: the triage-capable actor need not be malicious. An outside author opens an issue whose first line is the marker. A triager, seeing a natural-sounding `dependency-audit` label that matches the issue's apparent subject, applies it in good faith. The issue now carries both the label and the first-line marker, so it counts toward ambiguity, and every weekly run goes red (exit non-zero, zero writes) until a human removes the label or closes the decoy. Before the first run, or after a closure, the same sequence gets the decoy adopted. The outside author has borrowed the triager's authority without holding it. I accept this as a coordination residual (it is loud, not silent, and it fails with zero writes in the ambiguity case), on one binding condition:

- **No automated or templated path may apply `dependency-audit`.** No issue template, no `labels:` front matter in `.github/ISSUE_TEMPLATE/*`, no issue-form `labels:` key, and no labelling workflow or bot (auto-labeller, triage rule, label-sync by keyword) may apply it. The only legitimate applier is `dependency_audit_report.py`'s create path (AD-12b). An automated path would turn the residual from "a triager made a mistake" into "any outside author can self-apply the authenticator", which is the HIGH that AD-12a closed. The runbook's AD-12b note must also tell triagers that this label is applied only by the workflow and never by hand when triaging. The single exception is AD-12b clean-up step 3, an operator recovery action restricted to a provenance-verified, workflow-created issue.

**Rejected alternatives** (recorded so they are not re-litigated):

| Option | Rejected because |
|---|---|
| Author `user.login` pinning | There is no robust source for the expected identity. On a `schedule` trigger `GITHUB_ACTOR` is the workflow-owning user, not `github-actions[bot]`. `GET /user` is forbidden to `GITHUB_TOKEN`. A hardcoded `github-actions[bot]` breaks every local, `--dry-run` or differently-tokened run **silently**: a mismatch reads as "no tracking issue exists" and creates the duplicate AD-12 exists to prevent. Deferred to #1812 item 5 for a proper design. |
| Store the issue number in a repo variable or a committed file | Both need a broader scope (`administration: write` / `contents: write`) than this job's least-privilege `issues: write`. That is a larger privilege grant than the exposure it removes. |
| Marker-only with first-line anchoring | Zero marginal cost to an attacker authoring a fresh issue (security round 4: still HIGH). |

#### AD-12a "Lookup bound" — AMENDMENT 2026-10-14: the listing is label-filtered server-side; the predicate stays the authenticator.

*Added 2026-10-14 in response to the cross-vendor second review (codex, adversarial lens, MEDIUM, CWE-400; `.claudetmp/second-review/step1605-design-20261014T084518.md`). It supersedes the fourth AD-12a ruling bullet above, the "unfiltered" clause of AD-12's lookup bullet, and the `list_issues` signature in AD-13.*

**What was wrong with the superseded bullet.** It was right about integrity and wrong about availability. The predicate decides **which** entries are adopted. The listing decides **whether the lookup finishes at all**. An unfiltered `state=all` listing returns every issue **and every PR** in the repo, and any GitHub account can add to it. AD-12 caps it at 50 × 100 = 5,000 entries and, correctly, makes **zero writes** when the cap is hit. Together these mean that anyone who can open issues can turn off the weekly vulnerability report by opening about 5,000 of them, none of which carries the label. That is the externally reachable DoS that AD-12a claimed to have closed, reached through volume instead of ambiguity.

No attacker is needed. On 2026-10-14 this repo's issue and PR numbers are at about #2096, so the unfiltered listing already returns roughly 2,100 entries, and that count grows by about 800 a month. The cap would be hit **organically around February 2027**. After that, every run would go red with zero writes, permanently. A raised cap only moves that date.

The superseded bullet's one real concern was the `[]`-vs-raise surface. That concern is valid, but its failure mode is loud, bounded and covered by an existing remedy (see "Unverified until the first live run" below). The unfiltered design's failure is certain and permanent. The filter wins.

**The ruling (binding):**

1. **Query.** The consumer calls `list_issues(owner, repo, state="all", label=LABEL, page_limit=50)`. This issues `GET /repos/{o}/{r}/issues?state=all&labels=dependency-audit&per_page=100&page=N`. `state=all` is kept: AC-20's open-and-closed scope and AC-24's reopen depend on it.
2. **The server filter narrows; it never authenticates.** `find_tracking_issue` is unchanged. It re-tests the exact, case-sensitive label **and** the first-line marker on every returned entry, and counts ambiguity only after the predicate. If the server ignored or loosened the filter, the code would fall back to the old unfiltered behaviour, failing closed at the cap. It would never adopt the wrong issue.
3. **`list_issues` gains exactly one keyword, `label: str | None = None`.** It takes a **single** label name, not a list. Before any request it MUST fullmatch `[A-Za-z0-9][A-Za-z0-9._-]*`, or it raises `ValueError` with zero requests made. This rejects `,` (GitHub's multi-label AND separator) and `&`, `#`, `%`, `?`, `=` and whitespace, any of which would change the query. The value is also percent-encoded with `urllib.parse.quote(label, safe="")`. `None` omits the parameter. It is still one of exactly three helpers (AD-13).
4. **Fail-closed pagination is unchanged.** A `None` page raises, a full final page at the cap raises, and only HTTP 200 `[]` means empty. PR entries (`pull_request` key) are still dropped. PRs can carry labels, but only triage-capable actors can apply one. The cap stays at 50 pages. It now bounds the **label-filtered** collection, which in normal operation holds one entry for the life of the repo, because a closed issue is reopened rather than re-created. Growing that collection to 5,000 requires applying the label 5,000 times, which needs triage rights. That puts it inside AD-12a's existing triage residual, which grants no new authority.
5. **Tests (binding on `unit-test`; TD §7.3).**
   - (a) **Request shape.** The consumer's recorded list argv carries both `state=all` and `labels=dependency-audit`.
   - (b) **Label validation.** `"a,b"`, `"a b"`, `"a&state=open"`, `"a#b"`, `"%41"` and `""` each raise `ValueError` with **zero** subprocess calls.
   - (c) **Volume independence, at CLI level.** Use a fake GitHub that honours `labels=` only when it is present, serving a repo that holds more unlabelled issues and PRs than `page_limit × 100`, including unlabelled first-line-marker decoys. With no labelled issue, the first run creates (exit 0, `labels=[LABEL]`). With one real labelled issue, that issue is found and reconciled. Assert that exactly one list page is requested. The fake must be **discriminating**: a call without `labels=` gets the full unfiltered set, so if the filter is ever dropped this test goes red with `InconclusiveLookup`.
   - (d) **The filter is not trusted.** Use a fake that ignores `labels=` and returns unlabelled marker-first decoys, a labelled-and-marked **PR**, and label-only issues. Nothing is adopted, and the first run still creates.
   - (e) **The cap still binds the filtered set.** `page_limit` full pages of labelled entries raise `InconclusiveLookup`, with zero writes.
   - (f) **Existing tests are retained.** The 404/`None`-raises and 200-`[]`-is-empty helper tests stay, with the label parameter now present in the argv.

   *Honest limit:* (a)–(f) prove the request shape and that the code's outcome does not depend on unlabelled volume. They cannot prove that GitHub honours the filter. That is a server property, listed below.

**Unverified until the first live run** (the same class as AD-12b's two assumptions):

- (i) **A filter naming a not-yet-existing label returns HTTP 200 `[]`, not 404/422.** This is expected, because GitHub matches the label by name and does not check that it exists, but it has not been exercised against live GitHub. If it is wrong, `list_issues` raises on page 1. The first run, and every run after it, goes red with **zero writes and no duplicate**, until the label exists. The remedy is AD-12b clean-up step 1 (create the `dependency-audit` label). This adds no new operator obligation, only a new symptom that triggers an existing step. The TD's §11.2(d) runbook text must name the symptom: `list_issues: no usable response for page 1` on a first run means create the label.
- (ii) **The label filter is a consistent read of the issue record, not a search index.** Search was rejected in AD-12 because of index lag. If GitHub ever served a stale filtered view that missed the real issue, the run would create a second labelled issue. The next run would then see two doubly-qualified matches and go red under the ambiguity rule. The worst case is one duplicate and one red run, never a silent recurrence.

**Residual, accepted.** A triage-capable actor can still exhaust the filtered cap, or cause ambiguity, by mass-labelling. This is the AD-12a triage residual, with no new authority granted.

**Rejected alternatives** (recorded so they are not re-litigated):

| Option | Rejected because |
|---|---|
| Keep the listing unfiltered and raise the cap | Moves the organic exhaustion date and leaves the outsider DoS in place. An attacker's issue count scales; a constant does not. |
| Keep the listing unfiltered and remove the cap | Hands control of an unbounded number of API calls to outsiders. The token's rate limit becomes the cap, and hitting it is just a slower red. |
| Unfiltered, oldest-first, stop at the first match | Proving absence still means reading the whole listing, so the first run and any run after a lost label face the same exhaustion. |
| `creator=` filter | Already rejected in AD-12, because it depends on identity. A creator mismatch reads as "none exists" and creates a duplicate. |
| Search API (`label:` qualifier) | Index lag gives a missed match and a duplicate (AD-12). |

### AD-12b — AMENDMENT: creation applies the label and **verifies it stuck** from the create response. Fail closed.

Because AD-12a makes the label part of identity, a create that loses the label produces an issue this tool can **never adopt again**. Unverified, that failure is silent and recurring: the next run finds no labelled issue, reads that as "none exists", and creates another one **every week**. That is AC-20's duplicate, as a slow leak.

**The ruling (binding):**

- `reconcile`'s create branch calls `writer.create_issue(TITLE, body, ["dependency-audit"])`. The `Writer` protocol's `create_issue` takes `labels` (`RecordingWriter` records it, so the label is test-assertable).
- `GitHubWriter.create_issue` reads the **issue object returned by its own POST** and raises `GitHubError` if any requested label is absent from it. It does not do a second lookup. The response is GitHub's own and cannot be influenced by an attacker, so this guard is not itself a DoS vector.
- The `GitHubError` propagates to `main()` ⇒ **exit 1 ⇒ red workflow, from the first run**. A loud failure is the required failure mode. A quiet recurring duplicate is forbidden. *(Amended 2026-10-14, security design review S-2: this is not a one-off. See "Unverified until the first live run" below.)*
- The verification fires only on create. A reopen re-adopts the existing labelled issue and does not re-create, so the guard runs at most once per issue lifetime.
- `lib.github.create_issue` gains an optional `labels` parameter (AD-13, amended). It is still one of exactly three helpers, and still body-via-`stdin_json`.

**Unverified until the first live run.** AD-12b assumes that the workflow's `GITHUB_TOKEN` with `issues: write` counts as push-capable for label-on-create, and that a `dependency-audit` label that does not yet exist is created by the first create. Neither has been exercised against live GitHub; tests use stubs. AD-12b turns either assumption being wrong into a red run, with the issue created unlabelled and a message naming the missing label. *(Amended 2026-10-14, security design review S-2.)* It is **not** silent, but it is **recurring**: the unlabelled issue is invisible to AD-12a's predicate, so each subsequent run (weekly, and every `workflow_dispatch`) reads "none exists", may create **another** unlabelled issue, and goes red again, until an operator fixes the label. The failure is a loud, recurring red, not a quiet duplicate. The remedy is operational and needs no code change:

1. Fix the cause: create the `dependency-audit` label in the repo if it is missing, or correct the token's permission.
2. Clean up the strays: list issues whose first line is the marker and that lack the label, and **close all of them except at most one**.
3. Adopt (optional): label `dependency-audit` on at most one survivor, and only if its provenance is shown: its issue number is named in a failed run's `GitHubError` message (the run log), and its author is the identity the workflow created it under (`github-actions[bot]` for the scheduled workflow). The first-line marker is necessary but not sufficient, because it is a public constant. If provenance cannot be shown, close it too, and the next run creates a fresh, verified issue. Never label more than one, or AD-12a's ambiguity rule turns the next run red. This is an operator recovery action, the only sanctioned manual application of the label, and it is never a triage action.
4. Re-run with `workflow_dispatch` and confirm it is green.

These steps go in the runbook alongside the "do not remove the label" rule below.

**Operational consequence (§6 item 3).** This change adds a new repo label, `dependency-audit`, contrary to AC-26's "no new label". It also adds a standing rule: **do not hand-remove the label from the tracking issue.** Removing it makes the next run treat the issue as non-existent and create a fresh one. That is a duplicate, not a lost signal, so it fails in the safe direction, but it is still a duplicate. The rule is recorded in `docs/OVERSIGHT-RUNBOOK.md` on the implementation branch. The `docs/LABELS.md` / `KNOWN_LABELS` registry row is a **follow-up (#1812 item 12)**, not in this PR, because the implementation PR is at 14 of 15 files (TD §1.5) and the registry row touches two files (`docs/LABELS.md` and `KNOWN_LABELS` in `scripts/framework/check_agents_static.sh`), which would make 16. Until that row lands, the label exists in the repo but not in the registry. It is a reporting label, not a pending-actor label, so no router consumes it.

### AD-13 — The three GitHub write helpers go in `scripts/automation/lib/github.py`. The module does not roll its own `gh api`.

Add exactly three, no more (non-goal 7 — build what the workflow needs):

```
list_issues(owner, repo, *, state="all", label=None, page_limit=50) -> list[dict]   # excludes PRs; `label` per AD-12a "Lookup bound" (amended 2026-10-14)
create_issue(owner, repo, title, body, labels=None) -> dict             # POST via stdin_json; `labels` per AD-12b
update_issue(owner, repo, number, *, title=None, body=None, state=None) -> dict   # PATCH via stdin_json
```

`post_comment()` already exists and is used as-is. All bodies go through `_run_gh(..., stdin_json=...)`, which is the mechanism already **verified** to transmit file contents rather than an `@path` literal (#752/#1155) — that is AC-27 satisfied by an existing, tested implementation. Rolling `gh api` inside the new module would duplicate retry, backoff, rate-limit handling and the `@path` defence, which is precisely what CLAUDE.md's "use the code, don't roll it yourself" forbids; F-3 is therefore **resolved as: yes, the workflow needs it** — narrowly.

### AD-14 — Registries and docs (AC-29/30/31), with one shed.

| File | Change |
|---|---|
| `docs/specs/SPEC-375-deterministic-gate-invariant.md` | add `dependency_audit.sh` → `dependencies`; `security_scan.sh` → `security` unchanged |
| `docs/OVERSIGHT-RUNBOOK.md` | gate→key table row; the `:301` invocation example gains the dependency gate; one sentence recording AD-2's empty-changeset/network trade |
| `docs/CI-EXECUTION-INVENTORY.md` | **replace** the `security_scan.sh` "CI-portable, deferred" row (AC-30 — the pip-audit rationale is retired, not amended) with two rows: `security_scan.sh` → wired, not required, zero debt measured via `-o`; `dependency_audit.sh` → deliberately not in `oversight-gates.yml`, covered by `dependency-audit.yml` |
| `DECISIONS.md` | one appended, dated entry (AC-31): the split; the fail-open and its **duration** trigger; AV-5's unparsed-file negative; the 0/219 baseline **with its measurement channel**; S-3's deferral; AD-6's ratchet reasoning |
| `SCRIPTS-INDEX.md` | regenerate via `scripts/framework/gen_scripts_index.sh` — **first shed** if the budget binds (S-6 #1) |

---

## 2b. Amendment D-5 (2026-10-20): the scheduled run pauses and alerts. AD-15..AD-23.

**Inputs:** REQUIREMENTS-1605 §2F (AC-32..AC-43), I-7 and Q-D5-1..6 (pm-agent, commit `4d0d2d161`); #2123 and #2125 (both unbuilt, read 2026-10-20).

**Searched first (CLAUDE.md item 1).** I searched `bin`, `scripts` and `bootstrap` for `usage-pause|timeout-breaker|usage_pause`, and read `scripts/automation/lib/github.py`. Findings:

- `bin/lib/usage_pause.py` together with its `bin/hos-cron` gate (`:461`) is the closest pattern. A crash, a timeout or garbled output there means pause.
- `~/.hos/timeout-breaker/<role>-<project>` is a per-project state file.
- The cycle context's "New work directive (#1198)" (`bin/hos-cron` `_build_context`) is the single place where the worker is told whether to start work.
- `github.py` has `list_check_runs_for_ref` but **no** Actions-runs reader. `scripts/framework/rerun_gate_checks.py` reads `actions/runs`, but it runs in CI with its own `_gh_api`, not through `github.py`.
- `scripts/automation/lib/breakers.py` keeps repo-local `.ai-local/` state, which is the wrong family for this.
- `bootstrap/notify_human.sh` does not exist.
- `security_scan_logic.py filter` already has the tri-state this needs: rc **0** clean, **1** kept advisories, **2** unreadable audit, invalid roster, missing `packaging` or a crash.

### AD-15 — Three parties. Actions measures and decides, an install-free job publishes, and the host holds.

| Party | Where | Does | Never |
|---|---|---|---|
| `audit` job | Actions, `contents: read` | pip-audit → JSON. Then **`python scripts/oversight/security_scan_logic.py filter < audit.json`**, the same module on the same checkout of main, never a copy (AC-32). Its rc is the verdict. Exits non-zero, with a cause output set first, on every AC-33 cause. | hold a write token |
| `report` job | Actions, `issues: write` | AD-12, unchanged | install anything |
| **`outcome` job (new)** | Actions, `permissions: {}`, `needs: [audit, report]`, `if: always()` | maps the `needs` results to **one strict record** (AD-16) and emits it as a single annotation | install, check out third-party code, or put `${{ }}` inside `run:` (inputs go through `env:` and are re-validated) |
| host consumer | `scripts/automation/dependency_pause.py`, called from `bin/hos-cron` (AD-18) | reads the record, sets or clears the hold, fires the alert | be the source of truth for findings |

**Why the verdict is computed in `audit` and not in `report`:** `security_scan_logic.py` imports `packaging`. `report` installs nothing (AD-10), and that rule is not relaxed. Computing the verdict in `audit` adds **no new trust**. `audit` is already where the measurement happens, and a compromised `audit` can already fake a clean pip-audit JSON. That is AD-10's accepted M-1 residual, unchanged.

**Outcome mapping (binding):**

| `audit` | verdict | `report` | Outcome | Cause |
|---|---|---|---|---|
| success | 0 | success | `clean` | — |
| success | 1 | any | `finding` | `dependency-advisory` (if `report` failed, `sub=report-failed` is added; the hold is unaffected) |
| success | 0 | not success | `not_run` | `environment-broken`, `sub=report-failed` |
| not success | — | — | `not_run` | `environment-broken`, `sub=<audit cause output if valid, else audit-failed>` |
| verdict rc 2 | — | — | `not_run` | `environment-broken`, `sub=roster-invalid` or `unparseable` |

A clean audit whose issue write failed is `not_run`, not `clean`. The scheduled path did not complete, and D-5 forbids that outcome being silent. **This is a product-visible choice:** it holds build work while dependencies are in fact clean. It is listed in §6 item 5.

### AD-16 — Transport: three REST reads, no artifact download, no issue channel.

The consumer reads the following through **three new narrow read helpers in `lib/github.py`**, which inherit retry, backoff, rate-limit handling and the 30 s timeout:

1. `GET /repos/{o}/{r}/actions/workflows/dependency-audit.yml/runs?branch=main&status=completed&per_page=20`;
2. `GET /actions/runs/{id}/jobs`, to find the `outcome` job's `check_run_url`;
3. `GET /check-runs/{id}/annotations`.

Selection rules:

- A run qualifies only if `head_branch == main` (the default branch), `event ∈ {schedule, workflow_dispatch}` and `path == .github/workflows/dependency-audit.yml`. The newest qualifying completed run by `run_started_at` wins, **whatever its conclusion**. A cancelled or timed-out run, or one with no record, is `not_run`.
- A dispatch on a non-default branch is **ignored, not trusted**. It runs that branch's copy of the workflow, which could emit a forged `clean`.

**Record grammar (binding shape; the TD fixes exact patterns).** Exactly one annotation from the `outcome` job whose message fully matches:

`hos-dependency-audit/1 outcome=<clean|finding|not_run> cause=<-|dependency-advisory|environment-broken> sub=<token|-> first=<advisory-id|-> kept=<int> issue=<int|-> sha=<40 hex>`

- The record is ASCII only, one line of at most 512 bytes, and the advisory id comes from a bounded allowlist.
- No match, more than one match, or a `sha` different from the run's `head_sha` gives `not_run` with `sub=record-invalid`.
- `issue=` is filled when `report` resolved the tracking issue. The `outcome` job never looks the issue up itself, since it holds no token scope.

**Precondition.** The Worker App token needs `actions: read` and `checks: read`. If either is missing, the read fails, which gives `not_run` (`read-failed`) on the first cycle. That is loud, and AC-42's day-one run surfaces it before the hold is enabled. Granting a permission is a human act (§6 item 4).

**Rejected alternatives:**

| Option | Rejected because |
|---|---|
| Download a workflow artifact on the host | It unpacks a zip produced by the wheel-executing job, inside the most privileged environment (the host holds App keys). It also needs a binary download path that `_run_gh` does not have. |
| Use the tracking issue as the channel | A weekly freshness write breaks AC-21's zero-writes rule. A failed `audit` never reaches `report`, so `NOT_RUN` could only show up as staleness, up to 9 days late. |
| Commit statuses | They need a new `statuses: write` scope and are anchored to a SHA that main moves past. |
| Encode the outcome in step names | Static names cannot carry AC-41's advisory id. |

### AD-17 — Staleness and read failure (AC-38, and the architectural half of Q-D5-6).

- **Stale.** Stale means no qualifying completed run started within **216 h** (the 7-day cadence plus 48 h of grace). The result is `not_run` with `sub=stale`. The value comes from `HOS_DEPENDENCY_AUDIT_MAX_AGE_HOURS` and is clamped to **[168, 336]**. An out-of-range value is a config error, which means held. It is never "disabled". The 48 h grace absorbs GitHub's documented scheduled-run delays and drops, so a single dropped fire does not trip the hold. A missed second week does. A workflow that has never run is stale.
- **Read failure.** The consumer reads on every worker cycle. That is 3 calls every 15 minutes, which is negligible against the rate limit. If a read fails, the consumer reuses the last successful reading, kept in the hold directory, **only if that reading is under 6 h old**, and logs `reading_age`. Otherwise the result is `not_run` with `sub=read-failed`. This defines "cannot read". It does not decide Q-D5-6. If the human rejects I-7, the only change is that `read-failed` stops holding.

### AD-18 — Hold state, the #2123 seam, and where the consumer lives.

**The state** is a per-project directory that more than one hold source can share: **`~/.hos/build-hold/<project>/<source>.json`**. Directory mode is 0700, file mode 0600, and writes are atomic (temp file plus rename). This source is `dependency-audit`. The schema is `hos-build-hold/1`, with these fields:

- `source`, `cause`, `sub`;
- `fingerprint`, which is `dependency-audit:<cause>:<first advisory id | sub>`, exactly as AC-41 specifies;
- `since`, `last_evaluated`;
- `issue`, `run_url`, `clear_act`;
- `alert: {status: sent|undelivered|pending, reason, at}`;
- `detail: {}`, which is source-specific.

**The file is derived, not authoritative.** Every worker cycle recomputes the outcome:

- Not clean: the consumer writes or keeps the file. `since` is kept while the fingerprint is unchanged. A new fingerprint updates the file and re-alerts.
- Clean: the consumer deletes the file and emits `dependency-pause-cleared` with the hold's duration.
- **Clean only arrives from a qualifying run** (AC-37, pending Q-D5-3). Deleting the file by hand achieves nothing, because the next cycle rewrites it.
- An unreadable or corrupt file in the directory means **held**, with `sub=state-corrupt`. It is never "absent".

**The #2123 seam.** #2123 adopts this by writing its own `pipeline-blocked.json` into the same directory, using the same schema. It gets the shared reader, the directive (AD-19) and the log line at no cost. Each source exclusively owns its own file. One source never deletes another's. #2123's B4 rule ("could not run" fingerprints the same as "failed") stays #2123's to implement. Both PR bodies disclose this cross-issue requirement.

**The consumer** is `scripts/automation/dependency_pause.py`. Its decision logic is pure and its I/O goes through injected fakes, so it is testable without network (AC-28, AC-43).

- It is invoked from `bin/hos-cron` as `python3 -m scripts.automation.dependency_pause check …`, the same shape as `select_work_candidates`. It runs for the **worker role only**, after the usage-pause gate, under a wall-clock bound.
- If the consumer crashes, times out, or prints a line that does not parse as a verdict, `hos-cron` treats the project as **held**, with `sub=check_error`. That is the usage-pause rule, and hos-cron then calls the notifier itself (AD-20).
- The module gets an **exact-path entry in `protected_surfaces.txt`**. It is the only automated path that releases a hold, so it is control code.

**Scope (binding).** `bin/hos-cron` ships to consumers (`framework_consumer_files.txt`) and `dependency-audit.yml` does not. hos-cron therefore invokes the consumer **only when `.github/workflows/dependency-audit.yml` is tracked in the clone**. When it is not tracked, every cycle prints `[DEPENDENCY-AUDIT] not configured for this project (#1605)`, which is visible. Nothing is held and the consumer is not invoked, so a consumer install neither crashes into `check_error` nor sits in a permanent `stale` hold. Turning the hold off by deleting the workflow takes a merged change to `.github/workflows/**`, which is a protected surface and therefore needs human approval.

### AD-19 — What the hold does (AC-36). Directive-level, stated honestly.

While any hold file is present, hos-cron's **New work directive** renders `NEW WORK: DOCS/DESIGN ONLY` (unless it already says `BLOCKED`). The directive also lists:

- the source, the cause and the issue;
- the carve-out: triage; docs-only and design-only steps; work on the tracking issue, on #1504, or on an exemption or bump that clears the hold.

Every held cycle logs exactly one line (AC-39):

`[HELD-DEPENDENCY] cause=<c> sub=<s> issue=#<n|-> since=<t> alert=<sent|undelivered:<reason>>`

Audit events are emitted only on transitions: `dependency-pause-set`, `dependency-pause-cleared` (with duration) and `alert-undelivered`. They are not emitted on every cycle.

- **The overseer is not held.** D-5 holds the *start* of build work. Reviewing and merging PRs that were already built is out of scope.
- **Residual, accepted and disclosed:** the hold is enforced by a directive that the worker agent obeys. That is the same strength as today's #1198 `BLOCKED`. There is no mechanical backstop in v1. A deterministic "no non-docs PR while held" check in `submit_pr.sh` belongs with #2123, which has the identical carve-out and should build the backstop once for both sources.

### AD-20 — The alert seam (AC-39, AC-40). The hold never waits on the alert.

**Ordering is binding.** The consumer writes the hold file **first**, and only then invokes `bootstrap/notify_human.sh --cause <dependency-advisory|environment-broken> --issue <n> --since <iso> --priority high --body-file <path>` through an injectable runner with a 30 s bound.

- **When it fires:** on a new hold or a fingerprint change. While `alert.status=undelivered`, it retries at most once an hour. There are no reminder pushes; #2125's dedup and #1928's re-ping own those.
- **Undelivered:** the notifier being absent, not executable, exiting non-zero or timing out all mean undelivered with a named reason. The consumer records the reason in the file, emits `alert-undelivered`, and carries the reason in AD-19's log line. Nothing else changes, and the hold stands.
- **No Pushover client of its own.** The credential never enters this code path.
- **Cross-issue requirements on #2125**, disclosed in the PR body:
  - add the two causes to #2125's closed trigger list;
  - accept `--url <run url>` in place of `--issue` when no tracking issue exists yet (for example, a first run that never reached `report`).
- **The fallback channel is Q-D5-5 (human).** If the human picks (a), the consumer calls `bootstrap/escalate_to_human.sh` on the tracking issue when the alert is undelivered. The **host** makes that write, not the workflow, so AC-25 is not touched.

### AD-21 — A partial audit is not a clean run.

`security_scan_logic` reports pip-audit's `skipped` dependencies as `NOT CHECKED` and still returns rc 0. On the scheduled path, any skipped dependency means `not_run` with `sub=partial-audit`. A clean run (§2F Terms) means every advisory was decided, and a dependency that was not audited has had nothing decided. **Precondition for the TD:** measure the current main venv. If it produces any skipped entries, bring that back to the architect. Do not allowlist them.

### AD-22 — BINDING sequencing finding: Part 2 predates #1776 and must carry its roster.

The Part 2 implementation branch (`b9c342559`) forks before `4d5b8cff5` (#1776, merged 2026-10-20). Its `dependency_audit.sh` has **zero** references to `security_scan_logic`, while main's `security_scan.sh` has three. Merged as-is, the extracted local gate would block on black and mcp again. That re-creates the always-red gate #1776 just fixed, and the split would silently undo a human ruling.

**Ruling:**

- Part 2 is re-cut on current main.
- The pip-audit lane moves **as it is on main**: the roster filter, the `GATE FAIL`/exit-2 semantics, and the `GATE PASS … not completed` naming.
- `tests/oversight/test_security_scan_exemptions.py` (`_GATE` points at `security_scan.sh`) is re-pointed to `dependency_audit.sh`. That is **one more file** in Part 2.

**Startup gap:** no. #1776 landed after this ADR was approved. It is a sequencing gap, and the affected sign-offs are listed in §5.

### AD-23 — Ship vehicle (Q-D5-1). **RECOMMENDATION, PENDING THE HUMAN. Not decided.**

**Recommendation:** pm-agent's option. Invoke shed step 3 (§3), and **Part 3** carries the scheduled half together with all of D-5. Reasons:

- (i) No report-only scheduled workflow ever lands. Landing one would ship exactly the behaviour D-5 overruled.
- (ii) AD-22 already forces a re-cut of Part 2, so the "don't disturb reviewed SHAs" argument behind the S-6 waiver no longer holds. Under AD-22, `security_scan.sh` and `dependency_audit.sh` need re-review regardless.
- (iii) Part 2 with files 4, 5, 6 and 8 removed, plus AD-22's test file, is about 11 files, which leaves headroom.

**Corollary for the S-6 waiver.** The 11th commit's security amendments split by half. SEC-M2 and SEC-S1 stay in Part 2. SEC-M1, SEC-S4 and the report-side items go to Part 3. If the re-cut Part 2 is at or under 10 commits, the waiver goes unused. A waiver that goes unused is not a waiver used elsewhere: it does **not** transfer to Part 3.

**Part 3 estimate: 14–15 files, at the ceiling.**

| # | File |
|---|---|
| 1 | `dependency-audit.yml` |
| 2 | `dependency_audit_report.py` |
| 3 | `lib/github.py` (the three AD-13 write helpers and the three AD-16 read helpers) |
| 4 | `test_dependency_audit_report.py` |
| 5 | `dependency_pause.py` |
| 6 | `test_dependency_pause.py` |
| 7 | `bin/hos-cron` |
| 8 | the existing hos-cron directive test |
| 9 | `protected_surfaces.txt` |
| 10 | `CODEOWNERS` (regenerated) |
| 11 | `OVERSIGHT-RUNBOOK.md` |
| 12 | `CI-EXECUTION-INVENTORY.md` |
| 13 | `DECISIONS.md` |
| 14 | `CRON-SETUP.md` (the permission precondition) |
| 15 | `SCRIPTS-INDEX.md` |

**Part 3 shed order:** first, `SCRIPTS-INDEX.md` becomes a follow-up. Second, the `CRON-SETUP.md` note folds into the runbook. **Never shed** AD-19, AD-20 or AC-43's tests. Splitting Part 3 again would land either a report-only workflow or a consumer with nothing to read. If it goes over 15 after the shed, that is a new human waiver question, not an agent-side split.

**If the human prefers one larger Part 2:** the D-5 work makes Part 2 roughly 22 files, and that needs an explicit size waiver. I recommend against it, because one PR would carry `bin/hos-cron`, a new trust read path and the gate split together.

### Q-D5 dispositions

| Q | Kind | Disposition |
|---|---|---|
| Q-D5-1 vehicle | **human** | Open. Recommendation in AD-23 (Part 3). |
| Q-D5-2 `NOT_RUN` written to the issue | **product** | Open. **Recommendation: no.** Keep AC-25's zero writes. The hold file, the log line, the run and the alert are the record. If Q-D5-5 = (a), the host's escalation comment provides the visible issue record without the workflow writing anything. Either answer fits AD-15 without a redesign. |
| Q-D5-3 clearing without a clean run | **product** | Open. **Recommendation: clean run only** (AC-37 as written). A human's fix lands on main, and a `workflow_dispatch` re-evaluates it in minutes. Clearing on an issue comment or label would need an authenticated human-act parser, and bots can write both, which makes a new trust surface. If the human wants an escape hatch for an Actions outage, make it a **host-side, human-run, time-boxed override** (at most 7 days, audited), never an issue act. An override is a loosening, so it needs the human's explicit choice. |
| Q-D5-4 does Q3 count as the AD-12a/b merge clearance | **human** | Open. Not architectural. One note: under AD-23 the label code moves to Part 3, so whichever answer the human gives attaches to **Part 3's** merge, not Part 2's. A one-line link in that PR thread costs nothing and removes the ambiguity. |
| Q-D5-5 fallback when the alert is undelivered | **product** | Open. **Recommendation: (a)**, `escalate_to_human.sh` on the tracking issue, which relaxes AC-26's SHOULD for this case only. (b) is "log only", which contradicts B3's "never silent". (c) is "hold D-5 until #2125 lands", which leaves the hold unbuilt for no gain, because AD-20 already holds independently of the alert. |
| Q-D5-6 read failure means held | **product**, with an architectural half | The definition of "cannot read" is **decided** in AD-17: 6 h of cached-reading tolerance, then `read-failed`. Whether `read-failed` holds is open. **Recommendation: confirm I-7.** A worker that cannot reach GitHub cannot open PRs anyway, so holding costs nothing extra. |

---

## 3. File and commit budget

Design artefacts ship in their **own** PR in this repo (precedent: PRs #1618, #1651, #1656, #1658 — one or two files each), so this ADR and `TECHNICAL-DESIGN-1605` do **not** consume the implementation PR's 15.

**Implementation PR — 15 files, at the ceiling** *(planned budget; **superseded by TD §1.5: the PR as built is 14 files**)*:

1 `scripts/oversight/gates/security_scan.sh` · 2 `scripts/oversight/gates/dependency_audit.sh` · 3 `.github/workflows/oversight-gates.yml` · 4 `.github/workflows/dependency-audit.yml` · 5 `scripts/automation/dependency_audit_report.py` · 6 `scripts/automation/lib/github.py` · 7 `tests/oversight/test_security_scan_split.py` · 8 `tests/automation/test_dependency_audit_report.py` · 9 `tests/automation/test_github.py` · 10 `tests/oversight/test_gate_arg_grammar.py` · 11 `docs/specs/SPEC-375-…` · 12 `docs/OVERSIGHT-RUNBOOK.md` · 13 `docs/CI-EXECUTION-INVENTORY.md` · 14 `SCRIPTS-INDEX.md` · 15 `DECISIONS.md`

> **As built (TD §1.5), 14 files:** the list above minus file 9 `tests/automation/test_github.py`, whose helper tests were folded into file 8 (**shed step 2** below), and minus file 7 `tests/oversight/test_security_scan_split.py`, re-homed into the existing `tests/oversight/test_scan_gates_empty_args.py`, which already owns the #976 no-fail-open contract. That re-homing is a substitution and does not change the count. Net: 15 − 2 + 1 = 14. Shed step 1 (`SCRIPTS-INDEX.md`) and shed step 3 were **not** invoked. Nothing on the "never shed" list moved.

**Shed order if it exceeds 15** — follow it exactly; do not improvise past it (S-6):
1. `SCRIPTS-INDEX.md` regeneration → follow-up issue.
2. Fold the three helpers' tests from `tests/automation/test_github.py` into `tests/automation/test_dependency_audit_report.py` (they exist only for this consumer).
3. Split the **whole scheduled half** (files 4, 5, 6, 8, 9) into its own PR with #1605 **kept open**, and say so explicitly in the PR body.

**Never shed:** the fail-open fix and its tests; AD-5's branch; the gate→key tables; the `DECISIONS.md` entry.

**Commits (9 of 10), in this order:**

1. `fix(#1605): bandit verdict comes from -o, never stdout; fail closed on unparseable or unscannable` — gate + `HOS_BANDIT_BIN` + tests. **The fix lands in place, before the split**, so the reviewer diffs it against the code that had the defect rather than against a new file with no history.
2. `refactor(#1605): extract pip-audit into a repo-scoped dependency_audit gate` — new gate + `HOS_PIP_AUDIT_BIN` + tests; `security_scan.sh` becomes bandit-only; `KIND_FILTER_GATES` row.
3. `ci(#1605): wire oversight-gate-security-scan with its measured debt baseline`.
4. `feat(#1605): narrow issue create/update/list helpers in github.py`.
5. `feat(#1605): dependency_audit_report — marker-identified, zero-write-on-unchanged`. (Historical title; identity is label+marker per AD-12a — the label change landed in a later commit, now `b9c342559`.)
6. `ci(#1605): weekly scheduled dependency audit, split audit/report jobs`.
7. `docs(#1605): gate→key registries and the retired CI-portability rationale`.
8. `chore(#1605): regenerate SCRIPTS-INDEX`.
9. `docs(#1605): DECISIONS entry`.

Commits 1–3 are a coherent shippable unit if shed step 3 fires.

---

## 4. What I considered and rejected

| Option | Rejected because |
|---|---|
| `--skip-pip-audit` flag (the issue's option A) | Auto-discovery is file-based; the local path would still run the fused script, leaving one code path where a network dependency can reach a context that forbids it. (Upholds I-1.) |
| Scrub the progress bar off stdout | Makes correctness depend on matching an undocumented, TTY/width/locale-sensitive rendering. AV-1: the channels are already separate. |
| Make the dependency gate non-blocking locally | Auto-loosening without a suspension record (AD-6). |
| Delete the local pip-audit lane, relying on the scheduled workflow | A larger auto-loosening: it removes a blocking check outright. |
| Comment on #1504 instead of a tracking issue | Hardcodes an issue number that will close (I-4, upheld). |
| `gh search issues` for the marker | Index lag ⇒ missed match ⇒ duplicate issue; `github.py` excludes Search by design. |
| One workflow job | Puts PyPI build-backend code and an `issues: write` token in the same job (AD-10). |
| Rename the bandit half to `bandit_check.sh` | Four registries edited to move a name, and the `security` key — the one with a reviewer-role twin — ends up on the network half (AD-1). |
| Hand-rolled `gh api` inside the reporting module | Duplicates retry/backoff/rate-limit and the #752 `@path` defence (AD-13). |

---

## 5. Startup-gap analysis and affected sign-offs

*Should any of this have been settled earlier?* Partly, and it is already on record:

- **#1759 D4** explicitly deferred `HOS_BANDIT_BIN` and named it as the successor action. AD-7 executes that deferral; it is a closed gap, not an orphaned approval. **No re-review of #1759 is required.**
- **#1759 row 7** specified the `BANDIT_LAST_RC == 2` message split for `security_scan`; it did not land. AD-4 lands it. Its sign-off was for a design item, not for shipped behaviour — nothing built against it needs revisiting.
- **#1759's `STATUS=empty` ⇒ skip-pip-audit ruling** is **superseded** by AD-2. The superseded scope is one comment and one branch inside a lane that is being relocated; no other #1759 decision depends on it, and the changeset grammar it belongs to is untouched. `technical-design` must carry the rationale into `dependency_audit.sh`'s header rather than dropping it. **All other #1759 sign-offs stand.**
- **AV-5** (unparsed file reads as clean) is a *newly discovered* defect, not a previously-decided one. It strengthens pm-agent's **F-2** (repo-wide sweep for the `|| echo 0` fail-open class): the sweep should look for *both* shapes — default-on-parse-failure **and** verdicts derived from a tool's summary rather than from what it demonstrably covered. `technical-design` does not act on F-2; the worker files it (it is a "file regardless of budget" item).

No approved design or code elsewhere in the repo was built against a decision this ADR revises.

**AD-12a/AD-12b (amendment, recorded 2026-10-14).** *Should this have been settled in the initial review?* **Yes. This is a startup-artifact gap.** AD-12 put an `issues: write` token behind an identity check made entirely of attacker-controlled bytes. I reasoned about accidental duplicates (index lag, title edits) and not about deliberate ones, even though AD-10 and AD-11 had already treated this workflow's write scope as a trust boundary. The question "who can make an issue look like ours?" belonged in AD-12 from the start. A second process gap compounds the first: the implementation adopted the fix on 2026-09-22, but the ADR, TD and REQUIREMENTS were not amended in the same cycle, so the docs drifted from the code. This amendment closes the ADR half. **Affected sign-offs:**

- **Stand, for `f5c1c227f`.** code-reviewer (2026-09-23, scoped to the AD-12a/b diff) and security-reviewer round 5 (2026-09-23). Both reviewed the behaviour this amendment records, at `f5c1c227f`. infra round 3 (`3b18361c`) also stands, because the workflow's permissions and topology are unchanged by AD-12a/b (security round 5 re-verified this).
- **Post-approval delta: no sign-off covers it.** The branch tip is now `b9c342559`, an amended rewrite of `f5c1c227f`. `git diff f5c1c227f b9c342559` touches 5 files:
  - `dependency_audit_report.py`: the `_label_names` consolidation (code-reviewer's own SHOULD_FIX), and a `vulns` None-tolerance change in `normalize`;
  - `dependency_audit.sh`;
  - two test files;
  - `DECISIONS.md`.

  The `_label_names` change does not alter AD-12a/b's predicate as specified above, but it touches the authenticator's code path. **code-reviewer and security-reviewer must re-confirm at `b9c342559`** (a `f5c1c227f..b9c342559`-scoped pass is sufficient) before the register can be cited for the tip.
- **Orphaned until re-checked against AD-12a/b.** These are sign-offs given before `f5c1c227f` on surfaces the amendment changed:
  - **reliability** (both 2026-09-22 entries). AD-12b adds a new external-dependency failure mode: a create that succeeds at GitHub but is converted to `GitHubError` / exit 1, leaving an unlabelled issue behind.
  - **unit-test** (2026-09-22T23:40Z). It predates the 11 label tests and the `Writer.create_issue` signature change.
  - **ops** (both 2026-09-22 entries). There is a new red-workflow signal and a new "do not remove the label" runbook obligation.
  - **Earlier code-review / security rounds 1–4.** These are superseded by the `f5c1c227f` entries, but only for `dependency_audit_report.py` / `github.py`.
- **Process (REQUIREMENTS-1605, 2026-09-22T19:45Z).** This sign-off is orphaned for **AC-20 and AC-26 only**. AC-26's "MUST NOT require a label absent from `docs/LABELS.md`" is now false for this change. pm-agent must amend AC-20 and AC-26, or record them as superseded, before the implementation PR can claim AC-26 conformance.
- **TECHNICAL-DESIGN-1605.** Every section stating marker-only identification or "no label" is building against a superseded ruling. technical-design must realign it, and the TD's approval is orphaned for those sections until then.

**AD-12a "Lookup bound" (amendment, recorded 2026-10-14; cross-vendor second review, codex, CWE-400 MEDIUM).** *Should this have been settled in the initial review?* **Yes. This is a startup-artifact gap, and the second one on the same lookup.** AD-12 set a fixed resource ceiling (5,000 entries) over a collection that outsiders can grow, and made reaching that ceiling fail closed with zero writes. It did this without asking how large the collection already was. At the initial review the repo was at about #1605, so a third of the ceiling was already used. When I wrote AD-12a I then explicitly kept the listing unfiltered, reasoning only about integrity ("buys no security"), when the question that mattered was availability. The fail-closed-at-cap rule was correct for an *uncertain* lookup and became the attack surface for a *deliberately* or *organically* exhausted one. That is the same shape as the AD-12a defect. **Affected sign-offs:**

- **Orphaned for the lookup surface only (built against the superseded bullet).** On the implementation branch at `b9c342559`, `lib/github.py`'s `list_issues` takes no label and requests `?state={state}&per_page=100&page=N`, and the consumer's lookup call does not filter. The code-reviewer and security-reviewer `f5c1c227f` entries stand for the predicate and the create-verification path, and are orphaned for `list_issues` and the lookup call. unit-test was already orphaned. reliability, also already orphaned, must additionally cover assumption (i) above, which is a new external-dependency semantic.
- **Where the fix lands.** It goes in the **single** amendment commit already ruled (C1). It touches only manifest file 6 (`github.py`) and file 8 (`test_dependency_audit_report.py`), so the 14-file count is unchanged and so is the commit count. It stays blocked on the human S-6 waiver. The code-reviewer and security-reviewer re-reviews of that commit (TD §14) must cover it explicitly.
- **Design approvals.** The architect's 2026-10-14T08:21:19Z entry endorsed "the unfiltered state=all listing with no ?labels=". **That endorsement is withdrawn.** The 08:44:44Z APPROVED entry stands for everything except the TD sections that mirror the superseded bullet (§7.3 rows, §8, the §9.4 `find_tracking_issue` docstring, §9.6, the §11.2(d) runbook text, the AC-20 trace row, §14 and Human Review). Those are orphaned until technical-design mirrors this ruling. The security-reviewer's design re-review (TD §14) must cover the mirrored text.
- **REQUIREMENTS-1605: unaffected.** AC-20 requires a `state=all` scope and no title matching. Both are kept, so no pm-agent action is needed.
- **Cross-vendor second review.** This amendment answers the codex finding at the design level. The second review must be re-run on the amendment delta so the evaluator has a recorded disposition. The agy lane in the same run failed with `prompt_too_large` (#1718), and its own output says not to narrow the review to get a pass. That is a human restructuring decision and is not resolved by this ruling.

**D-5 (amendment, recorded 2026-10-20).** *Should this have been settled in the initial review?* **No for D-5 itself.** It is a new human scope ruling, not a gap in the original review. **AD-22 is a sequencing gap**, not a startup gap: #1776 merged after approval, and nothing in this ADR could have anticipated it. One process lesson is noted all the same: an ADR whose implementation stays unmerged for four weeks has to be re-checked against main before it is resumed. **Affected sign-offs:**

- **Stand.** The bandit-half design (AD-1, AD-3..AD-9). Every Part 2 design approval except those listed below.
- **Orphaned by D-5 (design).** Every approval of AD-10 and AD-12 as "the scheduled path" is orphaned for the scope of that path. They stand for the job split, artifact handling, identity and idempotence, and are orphaned for what happens on failure and on a finding. technical-design must add AD-15..AD-21 to the TD. The security reviewer must re-review the new read path (AD-16) and the `outcome` job. The reliability reviewer must review AD-17 and AD-20. The ops reviewer must review the new log line and events.
- **Orphaned by AD-22 (code).** Every code sign-off on the Part 2 `security_scan.sh` and `dependency_audit.sh` (through `b9c342559`) was given against a pre-#1776 base. They must be re-reviewed against the re-cut branch. #1776's own sign-offs stand, because AD-22 preserves its behaviour and only relocates it.
- **Moved, if AD-23 is adopted.** The pending re-confirmations on `dependency_audit_report.py` and `github.py` at `b9c342559` move to Part 3 together with the code.

---

## 6. Flagged for the overseer/human in the PR body (items 1–2 not blocking; item 3 merge-gated)

Per the worker's directive, items 1–2 are surfaced, not gated; item 3 is merge-gated. All three carry consequences beyond the technical call, which is why they are named explicitly rather than buried in a diff.

1. **A new standing operational obligation (AD-10).** This repo's first `on: schedule` workflow: weekly Actions minutes; a self-maintaining tracking issue that will exist indefinitely and overlap #1504 (I-4); and a workflow holding `issues: write` — a write scope no gate workflow currently has. The existence of the workflow is the issue's own approved ask; the *grant*, the *cadence* and the *permanent second issue* are the parts a human may wish to adjust. Cadence and cron are one-line reversible.
2. ~~**AD-2's empty-changeset consequence.**~~ **DOWNGRADED by AD-2a (§2a) — no longer a behaviour change.** The dependency gate now skips the runner's explicit empty-changeset no-op run, so `run_gates.sh` on an empty changeset behaves exactly as it does today (exit 0, every record `not-checked`, no network call), and #1759's TC-A2 invariant is preserved rather than narrowed. What remains worth a reader's eye is only the record of the reversal itself: AD-2 originally ruled the gate unconditional, a pre-existing test pinned the opposite, and the invariant was upheld. See §2a and the `DECISIONS.md` entry.

3. **A new repo label and a standing "do not remove it" rule (AD-12a/AD-12b).** This contradicts the requirements' AC-26 ("no new label"), so it needs explicit human clearance in the PR body. It was adopted in code during the 2026-09-22 cycle to close a HIGH security finding, and it is being recorded here after the fact, which is itself a reason to put it in front of a human rather than treat it as settled. Item 1's issue gains one label, `dependency-audit`. Hand-removing it causes a duplicate tracking issue. The `docs/LABELS.md` row is deferred to #1812 item 12. The residual risk (an actor with triage rights can still squat, or can be led into it by an outside author's decoy, S-3) is accepted in AD-12a, on the binding condition that no issue template, `labels:` front matter or labelling workflow ever applies `dependency-audit`. If the human prefers the deferred author-pinning design (#1812 item 5), that is the alternative, not "no label": "no label" reopens the HIGH. *(Added 2026-10-14, AD-12a "Lookup bound".)* The label now also bounds the lookup: the listing is filtered server-side by `dependency-audit`, so outsiders cannot exhaust its 5,000-entry cap, and the repo's own growth cannot either (about 2,100 issues and PRs today, growing about 800 a month). Declining the label therefore also reopens the CWE-400 availability finding. Any fallback design must solve the lookup bound as well as identity. This adds no new obligation to the clearance. It changes what the human is weighing. **Merge gate:** the implementation PR MUST NOT merge until a human clears this item in the PR thread. Design and code proceed against AD-12a/AD-12b meanwhile. If declined, the fallback is #1812 item 5 plus an ADR revision, never a revert to marker-only.

*(Added 2026-10-20, D-5. These are product-boundary items arising from my D-5 decisions. They are in addition to Q-D5-1..6, which are in AD-23's table. The human's D-5 ruling covers the hold itself. It does not cover the following.)*

4. **New App permissions (AD-16).** The Worker App token must be able to read Actions runs and jobs (`actions: read`) and check-run annotations (`checks: read`). These are read-only, but they are a grant on the trust surface. If the App already has them, this item reduces to a recorded check. If it does not, a human grants them before Part 3's day-one run (AC-42).
5. **Holds on a clean audit (AD-15, AD-21).** A `report` failure, or a partial audit, holds build work even when no advisory is outstanding. I chose the never-silent direction, because the scheduled path did not complete. The human may prefer an alert-only treatment for `report-failed`.
6. **The hold is directive-level (AD-19).** It has the same strength as #1198's `BLOCKED`. The mechanical backstop is deferred to #2123.
7. **A dated hold.** #1776's black and mcp exemptions expire on **2027-01-31**. Under D-5, the first scheduled run after that date returns `finding` and **holds build work**. TC-X5 also turns the `tests` check red from 2027-02-01. A renewal decision is therefore needed **before** the end of January, not after.

None of these reverses anything below; each narrows or retunes rather than invalidates.

## Human Review Required

**RISK: MEDIUM — CONFIDENCE: HIGH**
**Change classification: ADDITIVE, with three STRUCTURAL-adjacent items (§6; item 3 per AD-12a/AD-12b).**

The technical core is high-confidence: every premise is re-measured (§0), and the fail-closed design removes an entire class of false green rather than patching one instance of it. The residual risk is operational, not correctness: a first scheduled workflow with a write-scoped token, and a gate that now runs in a situation where it previously did not.

**D-5 amendment (2026-10-20): RISK: HIGH, CONFIDENCE: MEDIUM. Change classification: STRUCTURAL.** D-5 adds a new pipeline state that holds build work, a new host read path from GitHub, a cycle-start step in `bin/hos-cron`, and two cross-issue requirements (on #2123 and #2125). Confidence is MEDIUM, not HIGH, for three reasons:

- AD-16 depends on GitHub behaviour that has not yet been exercised live: annotations as a data channel, and the run-selection fields.
- AD-15 assumes that job outputs survive a failed job; until that is confirmed, the fallback is `sub=audit-failed`.
- AD-21's precondition is unmeasured.

The TD must verify each of these, and AC-42's day-one run must exercise them.
