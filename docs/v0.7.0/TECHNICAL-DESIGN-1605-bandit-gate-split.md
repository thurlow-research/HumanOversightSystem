# TECHNICAL-DESIGN-1605 — Two gates, a file-derived bandit verdict, and a scheduled dependency report

**Status:** BINDING on `coder`, `unit-test`, `system-test` for issue #1605. Everything below is a contract, not a suggestion. Where this document narrows or corrects the ADR it says so explicitly and gives the measurement that forced it (§1.4).

**Date:** 2026-09-22 (realigned 2026-10-14 to AD-12a/b; amended 2026-10-14 by the security design review; amended 2026-10-20 for D-5 and AD-22, §15)
**Author:** technical-design
**Issue:** #1605 (v0.7.0, `priority:high`). Parent #1567; per-check job pattern #1571; the vulnerabilities themselves #1504.
**Inputs:**
- issue #1605 body; the worker's brief (`/tmp/claude/brief-1605.md`) and its hard constraints A–E for this cycle;
- `docs/v0.7.0/REQUIREMENTS-1605-bandit-gate-split.md` (pm-agent, 31 ACs + proposed AC-20a) — **binding, accepted in full except AC-20/AC-26, where this TD implements the proposed 2026-10-14 amendments (AC-20, AC-20a, AC-26) per ADR AD-12a/AD-12b; those amendments are pending human clearance and gate the implementation PR's merge ("Human Review Required" item 3, end of this document)**;
- `docs/v0.7.0/ADR-1605-bandit-gate-split.md` (architect, AD-1…AD-14 / AV-1…AV-9) — **binding, adopted except the four items in §1.4**;
- `docs/v0.7.0/TECHNICAL-DESIGN-1759-run-gates-diff-parsing.md` (Ruling H, row 7, gap D4);
- my own re-measurement against this branch (§0).

**Consumers:** `coder` → `unit-test` / `system-test` → the review chain.

> **REALIGNED 2026-10-14 to ADR AD-12a/AD-12b.** The tracking issue's identity is the
> `dependency-audit` **label AND** the first-line marker, both required; ambiguity
> counts only doubly-qualified issues; creation applies the label and
> `GitHubWriter.create_issue` verifies it from the create response, raising
> `GitHubError` if it did not stick. This supersedes every marker-only and
> "no label" statement this document previously made (§2, §7.3, §8, §9, §10.2,
> §11, §12, §13). The amendment record and affected sign-offs are in §14.
> The label behaviour is binding on design and code. The AC-20/AC-20a/AC-26 amendments are pending human clearance (ADR §6 item 3); the implementation PR MUST NOT merge until that clearance is recorded in its PR thread.

> **AMENDED 2026-10-14 by the security design review** (`security-reviewer`, CONDITIONAL,
> MUST_FIX-1/MUST_FIX-2 + SHOULD_FIX S-1/S-4/S-5). The following are binding on the Part 2
> implementation and change existing manifest files only (the 14-file budget holds):
> **SEC-M1** report job reads the artifact from an isolated directory outside the
> workspace (§10.2); **SEC-M2** `--` before bandit's file list and NUL-delimited
> changed-file listing in CI (§3.6, §10.1, TV-10…TV-12); **SEC-S1** the CI job asserts
> the scanner is present (§10.1); **SEC-S4** `normalize` allowlists every rendered field
> and the run is bounded in count and size (§9.2, §9.3, §9.5); **SEC-S5**
> `persist-credentials: false` on both `dependency-audit.yml` checkouts (§10.2). Tests:
> TC-S15…TC-S18 (§7.1), the `normalize`-allowlist, bounds and workflow-static groups
> (§7.3). Amendment record and affected sign-offs: §14.

> **AMENDED 2026-10-20 for D-5 (ADR AD-15..AD-23, REQUIREMENTS §2F AC-32..AC-43) and AD-22.**
> New §15 is binding. It specifies the scheduled run's pause-and-alert path. It also
> re-cuts Part 2 on current main, because Part 2 predates #1776 (AD-22, binding). The
> file lists in §15.11 assume AD-23's recommendation: **Part 2** is the gate split only,
> and **Part 3** is the scheduled workflow, the report and all of D-5. That vehicle is
> pending the human (Q-D5-1). Where §15 contradicts an earlier section, §15 governs, and
> the earlier section carries a pointer. The most important supersessions are these.
> §4.4–§4.5, §6.2 and TC-D1–TC-D5 are replaced: `dependency_audit.sh` now carries main's
> pip-audit lane verbatim (§15.1). §10.2's two-job YAML becomes three jobs (§15.3).
> §12 is replaced by §15.11. Gaps returned to the architect: §15.13.

**Scope note:** S-1 (fail-open fix in scope), S-3 (promotion deferred), I-1 (two scripts), AD-1…AD-14 are not re-litigated here. This document says *how*, at the level of exact function decomposition, exact output strings, exact signatures and exact file edits.

---

## 0. What I re-measured myself (only the facts that decide an implementation detail)

Run on this branch, `scripts/oversight/.venv/bin/bandit` (bandit 1.9.4), `scripts/oversight/.venv/bin/pip-audit`, Python 3.12.3.

| # | Finding | Consequence |
|---|---|---|
| TV-1 | `bandit -f json -lll -o out.json vuln.py bad.md` → **rc 1**; `out.json` carries `errors:[{filename,reason}]`, `metrics:{"./bad.md":…,"./vuln.py":…,"_totals":…}`, `results:[{filename,line_number,test_id,issue_severity,issue_text,…}]`. | Confirms AD-4's extraction shape and AD-5's `errors` branch. `scanned = len(metrics) - 1` is the count of files bandit **attempted** — it includes files that landed in `errors`. Safe only because the `errors > 0` branch fails first (§3.6). |
| TV-2 | `metrics` carries a per-file entry even for the file bandit could not parse. | The OK line's `0 unscannable` claim is only printed on the `errors == 0` path, where attempted == scanned. Binding on §3.6's branch order. |
| TV-3 | **`python3 scripts/automation/<mod>.py` cannot import `scripts.automation.lib.github`** — `ModuleNotFoundError: No module named 'scripts'`. `python3 -m scripts.automation.<mod>` from the repo root resolves it (namespace packages, and the repo-root conftest does the same for tests). | **AD-12's illustrative invocation string is wrong and would fail at runtime.** Corrected in §1.4 D-1. |
| TV-4 | `pip-audit` supports `-o FILE, --output FILE` ("output results to the given file"). | The AD-3 "verdict comes from a file the tool wrote" rule is achievable for the pip-audit lane too, at zero cost. Adopted in §4.5. |
| TV-5 | `run_gates.sh:190` derives the gate name for `gate-results.json` and for its own `_is_suspended` check from **`basename "$script" .sh`**, not from the key the gate itself passes to `is_suspended`. | `security_scan.sh` already has this divergence (`security_scan` vs `security`). `dependency_audit.sh` will have it too (`dependency_audit` vs `dependencies`). **Pre-existing; not fixed here** — the fix is a `run_gates.sh` edit, which S-4 forbids. Recorded as §13 R-3. |
| TV-6 | `tests/automation/test_github.py::test_no_search_attribute` scans public names for the substring `search`; `tests/framework/test_gate_checkout_pinned_base.py::test_actions_write_scoped_to_dispatcher_only` globs **all** workflows for `actions: write`; `tests/framework/test_branch_protection_contexts.py` only checks required-context → producer, never the reverse. | `list_issues`/`create_issue`/`update_issue` and a new `issues: write` workflow break **none** of them. No 15th file is needed for test-registry upkeep. |
| TV-7 | `gen_scripts_index.sh`'s `describe()` takes the **first paragraph** of the header comment (consecutive `#` lines, terminated by a bare `#`), strips a leading `<basename> —`, and groups by directory under `LC_ALL=C` sort. | The two gate headers' line 2 must each be a single self-contained sentence followed by a bare `#` (§3.1, §4.1), or `SCRIPTS-INDEX.md` gains a multi-sentence entry. `dependency_audit.sh` sorts **before** `django_check.sh`. |
| TV-8 | `bash_check.sh` flags `mapfile`/`readarray`/`declare -A` in `.sh` files (Bash-4+). | Both gate scripts must stay Bash 3.2-clean: `while IFS= read -r` loops only. (Workflow YAML `run:` blocks are not scanned and keep the existing `mapfile` shape.) |
| TV-9 | `suspension_manager.py` resolves `SUSPENSION_FILE = "contract/gate-suspension.md"` **relative to cwd**. | AC-9's two-key independence test is feasible offline: a tmp repo + a planted `contract/gate-suspension.md` + `cwd=tmp_path`. |
| TV-10 | *(2026-10-14, security review)* `bandit -f json -lll -o o.json -- --baseline=x.py é.py` → **rc 1, both files scanned and both HIGH findings reported** (`./--baseline=x.py`, `./é.py`). Without `--`, `bandit … --baseline=x.py` → **rc 2** (consumed as the `--baseline` option). | bandit 1.9.4 honours `--`; it is the correct separator (§3.6). Without it, a file named like an option becomes an option. |
| TV-11 | *(2026-10-14)* `git diff --name-only` under the default `core.quotepath=true` prints `é.py` as `"\303\251.py"` (the quotes are part of the output). `-c core.quotepath=false` or `-z` prints `é.py`. | The quoted form ends in `"`, fails the `*.py` kind filter (§3.4), and is silently SKIPped as non-Python. The CI listing must be unquoted (§10.1). |
| TV-12 | *(2026-10-14)* `scripts/oversight/lib/changeset.sh` rejects a `-*` token **only on explicit argv** (`hos_changeset_parse`'s `-*)` arm, exit 2, before any tool runs). Names that come from git through `--diff`/`--step`/`--staged` (`_hcs_resolve_via_diff` → `_hcs_apply_rex`) are **not** checked for a leading `-`, and that path also reads `git diff --name-only` with the default quotepath. | On the explicit-argv path (the CI job, §10.1) an option-like filename fails closed: a red gate, not a bypass. On the git-sourced selectors (local `run_gates.sh --diff/--step/--staged`) it reaches bandit's argv unchecked today, so `--` is **load-bearing there**, not only defence-in-depth. The changeset.sh quotepath and `-*` gaps are in a no-touch file and are recorded as R-6 (§14). |
| TV-13 | *(2026-10-20, D-5; pip-audit 2.10.1, Python 3.14 local venv)* A full `pip-audit --format json -o` run of the oversight venv gives **rc 1**: 116 dependencies, **0 `skip_reason` entries**, and 4 raw advisories (black ×3 raw / 2 distinct, mcp CVE-2026-59951). `security_scan_logic.py filter` on that JSON gives **rc 0**: 3 suppressed, "116 dependencies read". | AD-21's precondition is met locally: there are no skipped entries to bring back to the architect. Day-one is clean on this venv. The CI venv also installs project requirements (AV-9) and is not this venv, so AC-42 still needs its own run (§15.10). |
| TV-14 | *(2026-10-20)* A dependency that does not exist on PyPI (a fake `dist-info` audited via `--path`) gives pip-audit **rc 0** and "No known vulnerabilities found". The entry is `{"name": …, "skip_reason": "Dependency not found on PyPI and could not be audited: …"}`, with **no `version` key**. `filter` on that JSON gives **rc 0**, with `NOT CHECKED` and "1 NOT CHECKED" in the OK line. | AD-21's premise is confirmed: a partial audit reads as a pass through both tools. The scheduled path must count skips itself (§15.2 step 7). |
| TV-15 | *(2026-10-20)* `pip-audit --strict` on the same input gives **rc 1** (the "vulnerabilities found" code) and **writes no output file**. Separately, pip-audit gives **rc 1** with a traceback when it cannot open its `-o` path. | rc 1 does not mean "vulnerabilities found" unless the output file parses. `--strict` is not used. Every scheduled-path attempt requires a parseable output file whatever the rc (§15.2 step 5). |
| TV-16 | *(2026-10-20)* `pip install --dry-run --no-index --quiet -r scripts/oversight/requirements.txt --report <f>` on the venv gives **rc 0** with `install: []`. For an unsatisfied pin (`black==99.0`) it gives **rc 1** and writes no report. `--no-index` makes this offline by construction. | This is AC-33's "venv does not match requirements.txt" check, using pip's own resolver rather than new comparison code (§15.2 step 3). |

---

## 1. The decisions this document adds

### 1.1 TD-1 — `dependency_audit.sh` is repo-scoped and ignores every path argument; it honours only the literal `--empty-changeset` token (AD-2a). ~~takes the **strict** repo-scoped shape. `--empty-changeset` is NOT honoured.~~ (Worker constraint C, settled; conclusion reversed by AD-2a, see the box below.)

> **WITHDRAWN 2026-09-22 by AD-2a (ADR §2a) — this section's conclusion is REVERSED.**
> `dependency_audit.sh` **does** honour the literal `--empty-changeset` token and skips
> (`NOT CHECKED`, exit 0); every other argument, including a path argument, stays
> ignored exactly as reasons 1, 3 and 4 below argue (they are arguments against
> *scoping by file list*, and AD-2a skips on an explicit runner mode signal, not a
> file count, so they still stand). Reason 2 below is withdrawn outright — struck in
> place, not deleted, with AD-2a's reasoning substituted, because a design that still
> argues for the unconditional run is building against a superseded ruling. Read
> AD-2a before implementing this gate.

The worker asked me to settle whether the new gate should honour `--empty-changeset` (skip, preserving today's `STATUS=empty` short-circuit) or take AD-2's strict shape. **I uphold AD-2 strict**, on four grounds, in ascending weight:

1. **The surviving half of the old rationale is a performance claim, not a correctness one.** The INV-SELECTOR comment gives two reasons: "nothing changed, so there is nothing to gate" and "keeps the empty path fast and side-effect-free". The first is *file-scoped* reasoning that dies on relocation — it is the exact premise #1605 exists to delete. The second is real but bounded: the empty path now costs what every non-empty path already costs today (`GATE_TIMEOUT` 120s × up to 3 attempts, worst case, on a total network outage), and I have deliberately **not** given the new gate a different timeout default (§4.4), so no run gets slower than an equivalent run does today.
2. ~~**The newly-red surface is narrower than it looks.** `run_gates.sh` emits `--empty-changeset` only when a *selector was given and resolved to zero scannable files* (an all-deletions step). A bare `run_gates.sh` is `unscoped`, not `empty`. And AV-7 plus today's code mean every **non-empty** local run in this repo already fails on #1504's vulnerabilities. So the behaviour delta is: *all-deletion steps stop being the one shape that hid the dependency posture.*~~ **WITHDRAWN by AD-2a.** This reasoning did not account for a pre-existing pinned invariant (`tests/oversight/test_run_gates_artifact.py::test_empty_changeset_full_run`, TC-A2, #1759): a run that checked nothing must be `exit 0` with every record `not-checked`, on every gate, full stop. The "narrower than it looks" framing measured *how often* the newly-red surface would fire; it did not check whether an *existing test* already forbade it from firing at all. It did, and TC-A2 is not incidental scaffolding — it is the pin for #1759's TD-D8/TD-D9 contract that a checked-nothing run is exit 0 and is explicitly not a pass. Narrowing TC-A2 to exempt repo-scoped gates would have removed that detector for every future repo-scoped gate, not just this one; AD-2a upholds the invariant instead (ADR §2a, grounds 1–2).
3. **"Ignores argv except one token" is a worse contract than "ignores argv".** The new gate is not in `FILE_LIST_GATES`, so the shared grammar suite does not cover it; honouring exactly one flag would need bespoke parsing plus a bespoke test, and would create a third gate category ("repo-scoped, except when the runner says nothing changed") that every future gate author has to choose between. The existing repo-scoped precedents (`django_check.sh`, `astro_check.sh`, `expensive_gates_stub.sh`, `collection_integrity.sh`) all run on `--empty-changeset` today. Joining them is the consistent, testable shape — and TC-G9 (§7.2) pins it as *identical output for every argv*, which is a stronger assertion than any carve-out could be. **Narrowed by AD-2a:** TC-G9 now pins identical output for every argv shape *except* `--empty-changeset`, which is a fixed, testable carve-out of exactly one literal token — not the bespoke multi-flag parsing this reason warned against.
4. **Dispositive: the answer must not depend on an input that is irrelevant to the question.** A gate whose verdict is "the installed environment has N known-vulnerable packages" cannot legitimately answer differently because this particular step happened to delete files. That is the same defect class as S-1 in a milder costume — a result conditioned on something it did not measure. **This reason survives AD-2a unchanged:** honouring `--empty-changeset` does not make the verdict depend on file deletions — it is not a `GATE PASS`, it is `NOT CHECKED`, which manufactures no evidence of dependency safety on any path (AD-2a ground 4).

**Consequences I accept and route, rather than bury** (as amended by AD-2a):
- `dependency_audit.sh`'s header **must** carry the superseded #1759 rationale and say why AD-2 first overrode it and why AD-2a restores the same observable behaviour on a narrower basis, an explicit runner mode signal and not a file count (AD-2 and AD-2a require this; exact substance in §4.1).
- `docs/OVERSIGHT-RUNBOOK.md` gains one sentence recording that the gate is repo-scoped, ignores path arguments, and skips only the runner's explicit empty-changeset no-op run (§11.2(c), ADR §2a "Downstream record-keeping"). ~~the trade and naming the only sanctioned way to stop it — a human suspension of `dependencies`, or fixing #1504~~
- ~~The PR body carries ADR §6 item 2 to the overseer/human unchanged.~~ ADR §6 item 2 is DOWNGRADED by AD-2a. The PR body records only the reversal itself, not a behaviour change.

Also settled, same shape, same reasoning: **`dependency_audit.sh` parses no argv other than one literal-token comparison for `--empty-changeset` (AD-2a), including no `--help`.** One rule ("this gate ignores its arguments") is testable; two rules invite a third. The affordance a human needs is the first stdout line (§4.3), which names the behaviour at the moment of confusion.

### 1.2 TD-2 — Both new/changed gate scripts are Bash 3.2-clean and shellcheck-clean (TV-8). No `mapfile`, no `declare -A`, no `readarray`.

### 1.3 TD-3 — The bandit extraction stays an inline `$OVERSIGHT_PYTHON -c` string; it does **not** become a new `*_logic.py` module.

#314's "logic in Python, shell for launch" is satisfied in substance: the extraction is a pure projection (parse → three integers) with **no policy** in it — every threshold and every branch stays in the shell where the reviewer reads the verdict. Promoting it to `scripts/oversight/bandit_scan_logic.py` would be a 15th implementation file, over the worker's budget (constraint B), for a six-line function whose failure mode is already fail-closed by construction (any exception → non-zero → rc 65 → `GATE FAIL`). If a later change gives this extraction a *decision* to make, that is the moment to extract it.

### 1.4 Departures from the ADR (four; all implementation-level, none reverses a ruling)

| # | ADR text | Departure | Why |
|---|---|---|---|
| **D-1** | AD-12: `python3 scripts/automation/dependency_audit_report.py --pip-audit-json …` | **`python3 -m scripts.automation.dependency_audit_report --pip-audit-json …`**, run with `cwd` = repo root. | Measured (TV-3): the file-path form raises `ModuleNotFoundError: No module named 'scripts'` the instant the module imports `lib.github`, which AD-13 requires it to do. The `-m` form is the repo's existing convention (`bootstrap/worker-cron-prompt.md:130` runs `python3 -m scripts.automation.pre_pr_stale_check`). AD-12's substance — a stdlib-only, importable, CLI-guarded module taking JSON in — is preserved exactly. |
| **D-2** | AD-10: `audit` job checks out; no ref discussed. AD-11: "never checks out a non-default ref". | Both jobs pin `ref: ${{ github.event.repository.default_branch }}` on `actions/checkout`. | Without the pin, a `workflow_dispatch` run checks out whatever branch the operator selected (`github.ref`), which makes AD-11 an aspiration rather than a property — and the `audit` job *pip-installs `requirements*.txt` from the checkout* (AV-9), so the ref choice is a code-execution decision. The pin is a non-fork-controlled literal and makes AD-11 mechanically true. |
| **D-3** | AD-12: state block "a fenced ```json``` block delimited by `<!-- hos-dependency-audit:state -->`". | An explicit **closing** delimiter `<!-- /hos-dependency-audit:state -->` is added. | A single opening delimiter makes the parse "from the marker to… something", which is exactly the ambiguity that turns a body edit by a human into a silently-misparsed state. With both delimiters, `parse_state` is one unambiguous slice, and an edit that damages either end reads as `None` (unknown) — which AD-12 already routes to a full update, never to empty-and-clean. |
| **D-4** | AD-14: `SPEC-375` gains a plain `dependency_audit.sh` → `dependencies` row. | The row is added **plus a one-line footnote** recording that this gate is network-dependent and therefore satisfies §3.1's determinism clause only relative to the advisory database as of the run. | SPEC-375 §3.1 defines a deterministic gate as one that returns "the same result for the same input on any run". `security_scan.sh` is in that table today *while containing pip-audit*, so the table already carries the impurity silently. The split is the one moment where adding the row without the footnote would actively launder a network-dependent gate into a list whose whole purpose is determinism. One additive line; AC-29 satisfied in full. |

**Notified to `architect`** on publication of this document: D-1 (a measured error in a binding invocation string), D-2 and D-4 (both strictly tighten an ADR ruling), D-3 (a refinement inside AD-12's own mechanism). None requires an ADR revision to proceed; if the architect disagrees with any, D-1 is the only one whose reversal would break the build.

### 1.5 Worker-constraint reconciliation (constraint B)

The worker's 14-file list = the ADR's 15 minus `tests/oversight/test_security_scan_split.py` and `tests/automation/test_github.py`, plus `tests/oversight/test_scan_gates_empty_args.py`. That is exactly **ADR shed step 2** (fold the helper tests into the consumer's test file) plus a re-homing of the new gate tests into the file that already owns the #976 no-fail-open contract. Both are sanctioned; neither touches the ADR's "never shed" list. **The budget holds at 14 and the issue ships whole in one PR** (constraint A) — no part of ADR shed step 3 (splitting the scheduled half) is invoked. I found no work that cannot be done within it.

---

## 2. File manifest (14) — what each file must contain

> **Superseded for file counting by §15.11 (D-5, AD-22, AD-23).** The table below remains the per-file content reference. Under AD-23, rows 4, 5, 6 and 8 move to Part 3. Part 2 gains `tests/oversight/test_security_scan_exemptions.py` (AD-22). Row 2's content is replaced by §15.1.

| # | File | Action | Owns |
|---|---|---|---|
| 1 | `scripts/oversight/gates/security_scan.sh` | modify | bandit-only, file-scoped; `-o` acquisition; fail-closed verdict; Python kind filter; `HOS_BANDIT_BIN` |
| 2 | `scripts/oversight/gates/dependency_audit.sh` | new | repo-scoped pip-audit gate; `dependencies` key; guarded extraction; `HOS_PIP_AUDIT_BIN`; NOT-RUN vocabulary |
| 3 | `.github/workflows/oversight-gates.yml` | modify | new `oversight-gate-security-scan` job; header debt-baseline entry; header group lists |
| 4 | `.github/workflows/dependency-audit.yml` | new | weekly + dispatch; two jobs (`audit` read-only, `report` issues:write) |
| 5 | `scripts/automation/dependency_audit_report.py` | new | normalize / render_body / parse_state / diff / reconcile / writers / CLI |
| 6 | `scripts/automation/lib/github.py` | modify | `list_issues`, `create_issue`, `update_issue` — **exactly three**, nothing else |
| 7 | `tests/oversight/test_scan_gates_empty_args.py` | modify | #976 contract (unchanged) **+** the bandit fail-closed/stub suite **+** dependency_audit behaviour **+** AC-9; module docstring updated |
| 8 | `tests/automation/test_dependency_audit_report.py` | new | pure-function tests, recording-writer reconcile tests, **and** the three `github.py` helper tests (folded per ADR shed 2) |
| 9 | `tests/oversight/test_gate_arg_grammar.py` | modify | `KIND_FILTER_GATES` row; TC-G9 argv-ignoring; TC-G10 auto-discovery; docstring |
| 10 | `docs/specs/SPEC-375-deterministic-gate-invariant.md` | modify | gate→key row + determinism footnote (D-4) |
| 11 | `docs/OVERSIGHT-RUNBOOK.md` | modify | gate→key row; auto-re-enable prose; `:301` invocation block; the AD-2 trade sentence |
| 12 | `docs/CI-EXECUTION-INVENTORY.md` | modify | **replace** the `security_scan.sh` row with two rows (AC-30) |
| 13 | `DECISIONS.md` | modify | one appended dated entry (AC-31) |
| 14 | `SCRIPTS-INDEX.md` | regenerate | `scripts/framework/gen_scripts_index.sh` — never hand-edited |

**Files that must NOT be touched** (each is a testable negative): `scripts/oversight/run_gates.sh` (S-4/AC-8), `scripts/framework/setup_branch_protection.sh` (S-3/AC-15), `scripts/oversight/validators/static_analysis.py` and `.github/workflows/oversight-validators.yml` (non-goal 4), `scripts/oversight/suspension_manager.py` (`AUTO_CHECKABLE_GATES` — AC-7, non-goal 8), `docs/LABELS.md` / `KNOWN_LABELS` (the `dependency-audit` registry row is a follow-up, **#1812 item 12** — not in this PR, ADR AD-12b "Operational consequence"), `scripts/oversight/lib/changeset.sh`.

**Protected-surface note (not a file change):** this PR touches `scripts/oversight/gates/**`, `.github/workflows/**` (protected surfaces) and `scripts/automation/lib/**` (a security surface). Human approval is required for merge regardless of computed tier. No registry file needs editing — all three are glob entries.

---

## 3. `scripts/oversight/gates/security_scan.sh` (modify)

> **AD-22 rebase (2026-10-20, binding).** Apply §3 to **current main's** `security_scan.sh`, as modified by #1776 at `4d5b8cff5`. Do not apply it to the file at `b9c342559`. Main differs in four ways, and each is settled here:
> 1. **Temp files** go through main's `_TMP_CLEANUP` array and `trap _cleanup_tmp EXIT` / HUP / INT / TERM block (#2054 S3), created with `mktemp "${TMPDIR:-/tmp}/bandit_json_XXXXXX"` and `…/bandit_log_XXXXXX`. This replaces §3.6's "explicit `rm -f` on every exit path" and its literal `/tmp`. The trap covers the inline `exit 1` of the exhaustion branch.
> 2. **Main's bandit parse-failure line** (`GATE FAIL: bandit output could not be parsed — nothing was decided; …`) is replaced by §3.6's rc-65 message. No test pins main's string; this was grepped across `tests/`.
> 3. **`NOT_PERFORMED` and the whole pip-audit lane are deleted** (lines 135–227 on main), and so is the AUDIT_STATUS tail check (lines 229–232). They move to `dependency_audit.sh` (§15.1). The final tail keeps only `GATE FAIL: $ERRORS security check(s) failed` and `GATE PASS: no blocking security issues`.
> 4. **bandit absent:** §3.5 governs (`SKIP: …`, then `exit 0` directly, with no `GATE PASS`). Main's `NOT_PERFORMED+=("bandit SKIPPED — not installed")` plus `GATE PASS (…)` naming is withdrawn for this gate. Once pip-audit is gone, that would be a pass line for a run that checked nothing. Test `g6` is rewritten accordingly (§15.1.3). This **tightens** #1776's architect A2 ("a pass line must name what did not run"): no pass line is reachable at all. code-reviewer must confirm it (§14 D-5).

### 3.1 Header

Line 2 must be exactly one sentence followed by a bare `#` (TV-7):

```
#!/usr/bin/env bash
# security_scan.sh — bandit HIGH-severity static analysis gate (blocking, file-scoped, offline).
#
# <body>
```

The body must state, in this order: (a) HIGH blocks, MEDIUM flows to `static_analysis.py` as a scored signal only (carried over); (b) **the verdict is derived from the JSON file bandit writes with `-o`; stdout is never read, because bandit decorates stdout with a progress bar once a scan exceeds ~1s — a *duration* trigger, not a file-count one (#1605, pm-agent V-2)**; (c) a file bandit could not parse is a scan failure, not a clean file (#1605, AV-5); (d) dependency vulnerabilities moved to `dependency_audit.sh` (#1605); (e) the existing usage block and the `changeset.sh` grammar reference, unchanged.

### 3.2 Preamble — unchanged from today

Source order, `is_suspended "security"` before `changeset.sh`, `hos_changeset_parse security_scan "$@" || exit $HOS_CHANGESET_EXIT`, `hos_changeset_summary security_scan`. **No change.** (AC-2, AC-3, AC-7.)

### 3.3 Changeset case switch

`PROJECT_WIDE` is set here and read in §3.4 — the `type_check.sh` precedent. INV-SELECTOR still holds: switch on `$HOS_CHANGESET_STATUS`, never on `${#FILES[@]}`.

| STATUS | Behaviour | Exit |
|---|---|---|
| `empty` | `hos_changeset_not_checked security_scan` | 0 |
| `unscoped` | print `security_scan: no files specified — defaulting to --all (full project scan)` **(string unchanged — AC-3/TC-G4 pin it)**, then enumerate; `PROJECT_WIDE=true` | falls through |
| `all` | enumerate; `PROJECT_WIDE=true` | falls through |
| `ok` | `FILES=("${HOS_CHANGESET_FILES[@]}")`; `PROJECT_WIDE=false` | falls through |

Enumeration is unchanged: `find . -name "*.py" -not -path "./.venv/*" -not -path "./scripts/oversight/.venv/*" -not -path "./.git/*"` read through a `while IFS= read -r` loop.

### 3.4 The Python kind filter (AD-5 part 1) — new

After the switch:

- If `PROJECT_WIDE` is true and the enumeration produced zero files → print `security_scan: NOT CHECKED — the project contains no Python file(s); nothing was scanned` and **exit 0**.
  *This replaces today's `no Python files found in project — bandit SKIP` + `GATE PASS: no blocking security issues` pair.* Rationale: with pip-audit gone, that path would end in a `GATE PASS` line having scanned nothing — the #1750/#1759 no-op-pass shape, and the secret_scan precedent (`secret_scan: NOT CHECKED — no scannable file(s) resolved`) already spells the honest form. Exit code unchanged (0); only the vocabulary changes, so nothing downstream moves.
- If `PROJECT_WIDE` is false: filter `FILES` to `*.py` into `PY_FILES` (a plain `case "$f" in *.py)` loop — the `lint_check.sh`/`type_check.sh` shape). If `PY_FILES` is empty → `hos_changeset_skip_kind security_scan "Python" 0` and **exit 0**. Otherwise `FILES=("${PY_FILES[@]}")`.

Without this filter, CI would hand every `.md` in a docs PR to bandit and §3.6's `errors` branch would go red on every documentation change (AD-5).

### 3.5 Binary resolution and the seam (AD-7)

```
BANDIT_BIN=""
if   [[ -n "${HOS_BANDIT_BIN:-}" ]]; then BANDIT_BIN="$HOS_BANDIT_BIN"
elif [[ -x "$VENV_BIN/bandit"    ]]; then BANDIT_BIN="$VENV_BIN/bandit"
fi
[[ -z "$BANDIT_BIN" ]] && { echo "SKIP: bandit not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"; exit 0; }
```

**No PATH fallback** — today's gate is venv-only and adding one would change what runs in the real pipeline (out of scope). The seam's header comment must mirror `secret_scan.sh`'s `HOS_DETECT_SECRETS_BIN` note: *off by default, inert in the real pipeline, present only so the fail-closed branches can be pinned.* Inertness and the absence of a PATH fallback are both test cases (§7.1 TC-S9/TC-S10).

### 3.6 The bandit unit of work and the verdict (AD-3, AD-4, AD-5)

**State:** `BANDIT_JSON=$(mktemp /tmp/bandit_json_XXXXXX)`, `BANDIT_LOG=$(mktemp /tmp/bandit_log_XXXXXX)`, `BANDIT_LAST_RC=0`, `BANDIT_HIGH=`, `BANDIT_ERRS=`, `BANDIT_SCANNED=`. Both temp files are removed on every exit path (explicit `rm -f`, matching the existing style; the exhaustion path removes them before its own `exit 1`).

**Invocation (exact):**

```
with_timeout "$GATE_TIMEOUT" "$BANDIT_BIN" -f json -lll -o "$BANDIT_JSON" -- "${FILES[@]}" >/dev/null 2>"$BANDIT_LOG"
```

Stdout to `/dev/null` — never read, never filtered, never regexed (AD-3). stderr to a log file, not `/dev/null` (AV-2). The string `|| echo "0"`, and any other default-on-parse-failure constant, must not appear anywhere in this file.

**`--` before the file list is binding (SEC-M2, TV-10, TV-12).** Every option must come before the `--`, and only file paths may follow it. This is the **only** bandit invocation in the file that takes paths. The two reporting-only calls in the success branch take `$BANDIT_JSON`, not the file list. How an option-like filename reaches this line differs by path:
- **Explicit argv** (the CI job, a hand-typed list): `hos_changeset_parse` rejects any `-*` token with exit 2 before bandit runs. An option-like name such as `--baseline=x.py` or `--configfile=y.py` turns the gate **red**. It cannot turn it green. Here `--` is defence-in-depth.
- **`--diff` / `--step` / `--staged`**: the names come from `git diff` and are not checked for a leading `-` (TV-12). Without `--`, a committed `--baseline=x.py` would be consumed as a bandit option. Here `--` is **load-bearing**.
- **`--all` / unscoped**: `find .` yields `./`-prefixed paths, which never begin with `-`.

The gate must not add its own `-*` filter or rewrite paths (for example by prefixing `./`) to work around this. `--` is the whole fix, and the changeset grammar stays owned by `changeset.sh`.

**`_run_bandit` (one attempt) — succeeds only if all four hold:**

1. `: > "$BANDIT_JSON"` **first** (AV-3: a timeout-killed attempt N-1 can leave its file behind; reading it as attempt N's result is a fail-open through the back door);
2. run the invocation above; `BANDIT_LAST_RC=$?`; if rc ∉ {0,1} → `return $BANDIT_LAST_RC` (preserves 124 so `run_with_retry` logs `timeout`, and 2 for the usage split);
3. one extraction call (below) succeeds;
4. its three captured values each match `^[0-9]+$`.

Failure of (3) or (4) → `BANDIT_LAST_RC=65; return 65`. Rationale for the guard in (4): `[[ "" -gt 0 ]]` evaluates false, so an empty capture is a silent pass. Rationale for one call rather than three: three pipes are three chances to fail open.

**The extraction (single `-c` string, path as `argv[1]`, `PYTHONSAFEPATH=1`, stderr appended to `$BANDIT_LOG`). Contract — it must print exactly one line, `high=<int> errors=<int> scanned=<int>`, and must raise (any exception) rather than emit a default on any deviation:**

```
import json, sys
d = json.load(open(sys.argv[1]))
r = d["results"]; m = d["metrics"]; e = d["errors"]          # KeyError → fail closed
if not isinstance(r, list) or not isinstance(m, dict) or not isinstance(e, list):
    raise SystemExit(1)
h = len([x for x in r if x.get("issue_severity") == "HIGH"])
print("high=%d errors=%d scanned=%d" % (h, len(e), len(m) - 1))
```

`len(m) - 1` excludes `_totals`; an empty `metrics` yields `scanned=-1`, which fails the `^[0-9]+$` guard and becomes rc 65 — deliberate, not incidental.

The shell parses the line with `${line#*high=}`-style parameter expansion or a `read` over a `high=%s errors=%s scanned=%s` split — **not** `eval`.

**Retry:** `run_with_retry "bandit" "$GATE_RETRIES" "true" _run_bandit`. `required=true`, unchanged. Retrying rc 65 is accepted; do not special-case it (AD-4).

**Exhaustion branch** — prints one of three messages, then `tail -n 5 "$BANDIT_LOG"` prefixed `  bandit stderr:`, then `rm -f` both temps and **`exit 1` directly** (not `ERRORS=$((ERRORS+1))`). Exiting inline is what makes AC-4's "must not print any line asserting absence of findings" structurally true: no OK line and no `GATE PASS` line is reachable after it.

| Condition | Message (exact) |
|---|---|
| `BANDIT_LAST_RC -eq 2` | `GATE FAIL: bandit rejected its arguments (exit 2 — a usage error, not tool flakiness). Nothing was scanned; do not retry.` |
| `BANDIT_LAST_RC -eq 65` | `GATE FAIL: bandit completed but its JSON output could not be parsed — nothing was verified. Zero findings are NOT inferred from a parse failure.` |
| otherwise | `GATE FAIL: bandit did not complete after retries` |

**Success branch — two independent checks, then the guarded OK. Order is binding:**

1. `if [[ "$BANDIT_HIGH" -gt 0 ]]` → `GATE FAIL: $BANDIT_HIGH HIGH severity bandit finding(s)` (substring `HIGH severity bandit finding` is pinned by an existing test), then list each HIGH as `  <filename>:<line_number> [<test_id>] <issue_text>` via a second, reporting-only python call. That call may carry `|| true` **because the verdict is already FAIL** — annotate it with exactly that reason. `ERRORS=$((ERRORS + 1))`.
2. `if [[ "$BANDIT_ERRS" -gt 0 ]]` → `GATE FAIL: bandit could not scan $BANDIT_ERRS file(s) — these were not checked.` then list each as `  <filename>: <reason>` (same reporting-only rule). `ERRORS=$((ERRORS + 1))`.
3. Only if both are zero → `OK: no HIGH severity findings ($BANDIT_SCANNED file(s) scanned, 0 unscannable)`.

Both checks are `if`, not `if/elif` — a run with both a HIGH finding and an unscannable file must report both.

**Tail:** unchanged in shape — `GATE FAIL: $ERRORS security check(s) failed` / exit 1, else `GATE PASS: no blocking security issues` / exit 0.

### 3.7 What §3 does NOT do

No change to the severity threshold (non-goal 3), to the `--all` enumeration, to `FILE_LIST_GATES`/`DEFAULTING_STRING_GATES` membership, to the `security` suspension key, or to retry/timeout defaults. S-1's bound holds: only the JSON acquisition channel, fail-closed handling, and AD-5's one extra branch.

---

## 4. `scripts/oversight/gates/dependency_audit.sh` (new)

> **AD-22 (2026-10-20, binding): §4.1 items 3–5, §4.4 and §4.5 are SUPERSEDED by §15.1.** The pip-audit lane moves **as it is on main**. It keeps the `security_scan_logic.py filter` roster, the `GATE FAIL` / filter-exit-2 semantics, the `NOT CHECKED … GATE PASS (… NOT CHECKED — see above)` naming, the invalid-override `GATE FAIL`, and stdout capture rather than `-o`. §4.2 (preamble, AD-2a skip) and §4.3 (announcement lines) still govern. §4.1 items 1, 2 and 6 still govern.

### 4.1 Header

```
#!/usr/bin/env bash
# dependency_audit.sh — repo-scoped dependency vulnerability gate (pip-audit, blocking on findings).
#
# <body>
```

Body must state, in this order:

1. **Repo-scoped: it takes no file arguments and ignores every path argument** — the `django_check.sh` / `astro_check.sh` / `collection_integrity.sh` precedent. Dependency posture is a property of the installed environment, not of a changeset. The single exception is item 2.
2. **Why `--empty-changeset` IS honoured (AD-2a, reversing AD-2's unconditional run).** ~~Why `--empty-changeset` is not honoured — … The cost is one network call on an otherwise-empty run — the same cost every non-empty run already pays. The sanctioned way to stop it is a human suspension of the `dependencies` key, or fixing the findings (#1504).~~ *(Withdrawn by AD-2a.)* Required substance: *"AD-2 first ruled that the gate must run even on an empty changeset, because dependency posture is a property of the installed environment, not of a diff. That still holds as an argument against scoping by file list, which is why every path argument is ignored. It does not reach the literal `--empty-changeset` token. That token is not a file list. Per TD-D9 it is the runner's explicit declaration that the whole invocation verifies nothing. Honouring a mode signal is not inferring scope from a file count, and it does not bring back the file-scoped INV-SELECTOR skip that AD-2 superseded. The reversal was forced by the pinned invariant TC-A2 (#1759): a run that checked nothing must exit 0. Do not re-add an unconditional run without re-opening AD-2a."* On this token the gate makes **no** network call and prints `NOT CHECKED`, never `GATE PASS`. The as-built header at `a979a4605` satisfies this item.
3. Blocking on findings; **execution failure is non-blocking and reports `GATE NOT RUN`, never `GATE PASS`** (AD-6).
4. Exit codes: 0 = no vulnerabilities, or suspended, or an explicit `--empty-changeset` skip, or the audit could not run; 1 = vulnerabilities found.
5. `HOS_PIP_AUDIT_BIN`: off by default, inert in the real pipeline, present only so the NOT-RUN branch can be pinned without disabling the network.
6. bandit/HIGH-severity static analysis lives in `security_scan.sh` (#1605).

### 4.2 Preamble

```
set -euo pipefail
_GATES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$_GATES_DIR/check_suspension.sh"
is_suspended "dependencies" && { print_suspended "dependencies"; exit 0; }
source "$_GATES_DIR/../ensure_venv.sh"
```

Suspension **before** `ensure_venv.sh` (the `secret_scan.sh` ordering): a suspended gate must not pay for a venv build. `changeset.sh` is **not** sourced and `hos_changeset_parse` is **not** called (AD-2, restated by AD-2a).

**AD-2a skip (binding), placed after the `is_suspended` line and before `ensure_venv.sh`:** scan `"$@"` for the literal token `--empty-changeset`. If it is present, print `dependency_audit: NOT CHECKED — empty changeset (nothing was checked; this is not a pass)` and `exit 0`. Only that token skips. A zero-argument invocation must still **run**, because that is the direct operator call from the runbook. The message mirrors `hos_changeset_not_checked`'s vocabulary without sourcing `changeset.sh`, and a comment must say so. The two AD-2a test cases (ADR §2a: `--empty-changeset` ⇒ rc 0, `NOT CHECKED — empty changeset` present, stub marker file absent, no `GATE PASS`; `some/file.py` ⇒ stub marker file present) live in `tests/oversight/test_scan_gates_empty_args.py`. The ADR names `test_security_scan_split.py`, which §1.5 re-homes into this file, so the 14-file budget is unchanged.

### 4.3 Announcement lines (printed before any work, after the AD-2a skip)

```
=== pip-audit (dependency vulnerabilities) ===
dependency_audit: repo-scoped — dependency posture is a property of the installed environment, not of a changeset; any arguments given (other than --empty-changeset) are ignored.
```

The second line is the affordance that replaces argv parsing (TD-1): a human who types `dependency_audit.sh foo.py` is told what happened at the moment it happens. It is a **fixed sentence**. ~~`all arguments ignored ($# received).`~~ An echo of `$#` would vary with argv and break TC-G9's byte-identical stdout assertion (§7.2). The as-built line at `a979a4605` matches. On `--empty-changeset` neither line prints, because the gate has already exited with `NOT CHECKED` (§4.2).

### 4.4 Binary resolution, timeout, retries

```
PIP_AUDIT_BIN=""
if   [[ -n "${HOS_PIP_AUDIT_BIN:-}" ]]; then PIP_AUDIT_BIN="$HOS_PIP_AUDIT_BIN"
elif [[ -x "$VENV_BIN/pip-audit"    ]]; then PIP_AUDIT_BIN="$VENV_BIN/pip-audit"
fi
[[ -z "$PIP_AUDIT_BIN" ]] && { echo "SKIP: pip-audit not in oversight venv (run: ./scripts/oversight/ensure_venv.sh)"; exit 0; }
GATE_TIMEOUT="${GATE_TIMEOUT:-120}"   # identical to today — the empty path must not cost more than any other path
GATE_RETRIES="${GATE_RETRIES:-2}"
```

No PATH fallback, same reasoning as §3.5.

### 4.5 The pip-audit unit of work

**Invocation (exact) — `-o` for the same reason bandit uses it (TV-4, AD-3's principle applied to the second artefact per S-2):**

```
with_timeout "$GATE_TIMEOUT" "$PIP_AUDIT_BIN" --progress-spinner off --format json \
    -o "$PIP_AUDIT_JSON" >/dev/null 2>"$PIP_AUDIT_LOG"
```

`_run_pip_audit` succeeds only if: `: > "$PIP_AUDIT_JSON"` first; rc ∈ {0,1} (rc 1 = vulnerabilities found = a **successful** scan, #672); the single guarded extraction below succeeds; both captured values match `^[0-9]+$`. Otherwise: preserve 124; map "completed but unparseable/unextractable" to **65**; else return the tool's rc. `PIPAUDIT_LAST_RC` records the last attempt (the `DS_LAST_RC` pattern).

**Extraction contract** — one call, prints exactly `vulns=<int> deps=<int>`:

```
import json, sys
d = json.load(open(sys.argv[1]))
deps = d["dependencies"]                       # KeyError → fail closed
if not isinstance(deps, list):
    raise SystemExit(1)
print("vulns=%d deps=%d" % (sum(len(x.get("vulns", [])) for x in deps), len(deps)))
```

`|| echo "0"` must not appear in this file (S-2 construction requirement).

**Retry:** `run_with_retry "pip-audit" "$GATE_RETRIES" "false" _run_pip_audit` — `required=false`, unchanged from today, so a missing network does not fail an offline developer's inner loop.

**Branches:**

| Case | Output | Exit |
|---|---|---|
| Findings (`vulns > 0`) | `GATE FAIL: $VULNS dependency vulnerability(ies) found` + one line per vuln: `  <name> <version> [<id>] fix: <comma-joined fix_versions or 'none'>` (reporting-only call, `|| true` permitted, annotated) | **1** |
| Clean (`vulns == 0`) | `GATE PASS: no known dependency vulnerabilities ($DEPS package(s) audited)` | 0 |
| Exhausted (`run_with_retry` returns 2) | `GATE NOT RUN: dependency audit did not complete — nothing was checked (this is not a pass)`, then the cause (`timeout`, `exit <rc>`, or `output could not be parsed` for rc 65) and `tail -n 5 "$PIP_AUDIT_LOG"` prefixed `  pip-audit stderr:` | **0** |

The clean line names the package count for the same reason §3.6's OK line names the scanned count: a green must be evidence of coverage, not an assertion. The NOT-RUN line is #1759's TD-D8 vocabulary — same exit code as today's `WARN:` line, honest sentence (AD-6; not a loosening).

Findings remain blocking (AD-6 / the RATCHET PRINCIPLE): converting this to a warning inside a refactor PR would be the system auto-loosening a control on its own authority, with no suspension record, no `review-by` date and no `--census` visibility. Suspension is the only sanctioned loosening path.

---

## 5. Seam contracts (both gates)

| | `HOS_BANDIT_BIN` | `HOS_PIP_AUDIT_BIN` |
|---|---|---|
| Default | unset | unset |
| Precedence | above the venv binary; **no PATH fallback** | above the venv binary; **no PATH fallback** |
| Purpose | pin AD-4/AD-5's fail-closed branches deterministically (V-2: the real defect is duration-triggered and cannot be naturally reproduced) | pin the NOT-RUN branch and the findings branch without a network |
| Inertness | when unset, resolution and behaviour are byte-identical to the venv path — **itself a test case** (TC-S8) | same (TC-D5) |
| Documented | in the script header, `secret_scan.sh`'s `HOS_DETECT_SECRETS_BIN` wording | same |
| Precedent | #1759 Ruling H; closes #1759 gap **D4** by name | this document, by symmetry |

---

## 6. Stub contracts (binding on `unit-test` — a wrong stub proves nothing)

A stub is a short `bash` script written into `tmp_path`, `chmod 0755`, pointed at by the seam env var. **Every bandit stub MUST parse its own argv for `-o <path>` and write there.** A stub that writes only to stdout would make a correct implementation fail and an incorrect one pass (AD-8). Stub argv shape is `-f json -lll -o <path> -- <file>...` (SEC-M2). Stubs must find `-o` by scanning argv, not by position, and must treat everything after the first `--` as a file.

### 6.1 bandit stubs

| ID | Stub behaviour | Required assertions |
|---|---|---|
| **SB-1** (AC-5 — the defect, pinned) | print `Working... ━━━━ 100% 0:00:02` to **stdout**; write fixture JSON with **one HIGH result** (`results:[{filename,line_number:3,test_id:"B602",issue_severity:"HIGH",issue_text:…}]`, `errors:[]`, `metrics:{"<file>":{},"_totals":{}}`) to the `-o` path; exit **1** | rc ≠ 0; `HIGH severity bandit finding` present; `B602` and the filename+line present; no `OK: no HIGH severity findings` |
| **SB-2** (contamination immunity) | write `results:[]`, `errors:[]`, `metrics:{"<file>":{},"_totals":{}}` to the `-o` path; write a **HIGH-finding JSON to stdout**; exit 0 | rc 0; `OK: no HIGH severity findings (1 file(s) scanned, 0 unscannable)` present — proves stdout is never consulted |
| **SB-3** (AC-4 — unparseable) | write `not json` to the `-o` path; exit 0 | rc ≠ 0; the rc-65 message present; `OK: no HIGH severity findings` **absent**; `did not complete after retries` **absent**; `GATE PASS` absent |
| **SB-4** (exit 2) | write nothing; exit 2 | rc ≠ 0; the usage-error message present; `did not complete after retries` absent |
| **SB-5** (AV-5 — unscannable file) | write `results:[]`, `errors:[{"filename":"./x.py","reason":"syntax error while parsing AST from file"}]`, `metrics:{"./x.py":{},"_totals":{}}`; exit 0 | rc ≠ 0; `could not scan 1 file(s)` present; `./x.py` and the reason listed; no OK line |
| **SB-6** (schema deviation) | write `{"results": "nope", "metrics": {}, "errors": []}`; exit 0 | rc ≠ 0; rc-65 message present; no OK line |
| **SB-7** (rc gate precedes the file) | write a **HIGH-finding** JSON to the `-o` path, then exit **2** | rc ≠ 0; the usage-error message present; **the HIGH finding must NOT be reported** — proves a failed attempt's file is never read |
| **SB-8** (truncation, AV-3 — the only case that observes `: > "$BANDIT_JSON"`) | **stateful**, driven by a counter file in `tmp_path`: attempt 1 writes a HIGH-finding JSON to the `-o` path and exits **2**; attempt 2 writes **nothing** and exits **0**. Run with `GATE_RETRIES=1` (two attempts) | rc ≠ 0; the **rc-65** message present; `HIGH severity bandit finding` **absent**. Without the truncation, attempt 2 would parse attempt 1's leftover file and report a finding this attempt never produced — a fail-open through the back door |
| **SB-9** (argv recorder, SEC-M2) | append its full argv, NUL-separated, to a record file in `tmp_path`; then write `results:[]`, `errors:[]`, and a `metrics` object with one entry per post-`--` file plus `_totals`, to the `-o` path; exit 0 | used by TC-S15…TC-S17 (§7.1). Lets a test assert **what bandit was handed** and whether it was invoked at all (an absent record file means it was never run) |

### 6.2 pip-audit stubs

> **SUPERSEDED by AD-22 (§15.1.3).** PB-1…PB-4 assume the `-o` lane and the `GATE NOT RUN` vocabulary, which main does not have. The pip-audit gate stubs are the stdout-JSON stubs (`_stub`, `_counting_stub`) of `tests/oversight/test_security_scan_exemptions.py`, retargeted to `dependency_audit.sh`. The table below is kept for history only.

Argv shape `--progress-spinner off --format json -o <path>`; same `-o`-parsing requirement.

| ID | Stub behaviour | Required assertions |
|---|---|---|
| **PB-1** (findings) | write `{"dependencies":[{"name":"anyio","version":"4.2.0","vulns":[{"id":"GHSA-x","fix_versions":["4.4.0"]}]}]}`; exit 1 | rc 1; `GATE FAIL: 1 dependency vulnerability(ies) found`; `anyio 4.2.0 [GHSA-x] fix: 4.4.0` |
| **PB-2** (clean) | write `{"dependencies":[{"name":"anyio","version":"4.4.0","vulns":[]}]}`; exit 0 | rc 0; `GATE PASS: no known dependency vulnerabilities (1 package(s) audited)` |
| **PB-3** (unparseable) | write `not json`; exit 0 | rc **0**; `GATE NOT RUN` present; `GATE PASS` **absent**; `output could not be parsed` present |
| **PB-4** (execution failure) | write nothing; exit 3 | rc 0; `GATE NOT RUN` present; `GATE PASS` absent |

---

## 7. Test plan

### 7.1 `tests/oversight/test_scan_gates_empty_args.py` (modify)

**Module docstring — must be rewritten** to say the file now owns two contracts: (1) #976 — neither scan gate may fail open on zero file args (existing); (2) **#1605 — `security_scan.sh`'s verdict must come from the file bandit wrote, never from the decorated stream, and must fail closed when that file is unparseable or reports unscannable files; and `dependency_audit.sh` must never report a pass it did not measure.** It must also record *why* the stub is mandatory (V-2: the real contamination trigger is elapsed scan time, so a natural-reproduction test would pass or fail with runner speed).

Existing cases: unchanged, except that `_HIGH_FINDING_PY` must keep the **variable** form `subprocess.Popen(cmd, shell=True)` — the literal-string form is not HIGH at `-lll` (AV-6). It already does; do not "simplify" it. Add a comment saying so.

New cases:

| ID | AC | Case |
|---|---|---|
| TC-S1…TC-S8 | AC-4, AC-5 | one per bandit stub SB-1…SB-8 (§6.1), in order |
| TC-S9 | AD-7 inertness | seam unset + planted HIGH `.py` → real venv bandit detects it (skip-guarded on bandit's presence). *This is the existing `test_security_scan_no_args_detects_high_finding`; assert explicitly that `HOS_BANDIT_BIN` is absent from the env.* |
| TC-S10 | AD-7 no-PATH-fallback | a stub named `bandit` planted in `tmp_path` and prepended to `PATH`, seam unset, planted HIGH file → the **real** finding is still reported (the stub was not used) |
| TC-S11 | AC-1 | `security_scan.sh` on a planted `.py`: stdout contains **no** `pip-audit` substring and no dependency section |
| TC-S12 | AC-6 | **`@pytest.mark.slow`** — generate ~200 trivial `.py` files plus one carrying `subprocess.Popen(cmd, shell=True)`; run the gate with no seam; assert `GATE FAIL` and the finding is named. Must not gate CI on timing; AC-5 (TC-S1) is the enforcing test, this is corroboration |
| TC-S13 | AD-5 | `security_scan.sh only.md` → `SKIP — 0 of 1 changeset file(s) are Python`, rc 0 (also covered by TC-G5; kept here because it is the branch that stops AD-5 part 2 reddening every docs PR) |
| TC-S14 | §3.4 | `security_scan.sh --all` in an empty dir → `NOT CHECKED — the project contains no Python file(s)`, rc 0, **no `GATE PASS`** |
| TC-S15 | SEC-M2 (explicit argv fails closed) | stub SB-9; tmp git repo with a committed file named `--baseline=x.py`; run `security_scan.sh --baseline=x.py` → rc **2**; stderr names the refused option (`refusing to treat it as a filename`); **the SB-9 record file does not exist** (bandit never ran); no `OK:` and no `GATE PASS` line |
| TC-S16 | SEC-M2 (git-sourced selector, `--` is load-bearing) | stub SB-9; tmp git repo, commit 1 = a `.py` file, commit 2 adds `--baseline=x.py`; run `security_scan.sh --diff HEAD~1` → the recorded argv contains `--`, every option appears **before** it, and `--baseline=x.py` appears **after** it as a file (never as an option token before `--`); rc 0 with `OK: … (1 file(s) scanned, 0 unscannable)` |
| TC-S17 | SEC-M2 (non-ASCII Python name is Python) | stub SB-9; explicit argv `é.py` (raw UTF-8, file present) → the recorded argv after `--` contains `é.py`; **no** `SKIP — 0 of 1 changeset file(s) are Python` line. Companion negative: the quoted form `"\303\251.py"` (TV-11's literal output) is what the kind filter would skip, which is why §10.1 must never produce it |
| TC-S18 | SEC-M2, SEC-S1 (workflow static) | parse `.github/workflows/oversight-gates.yml` with PyYAML from the oversight venv (the `test_gate_checkout_pinned_base.py` precedent) and inspect the `oversight-gate-security-scan` job: the job's file listing uses `git diff -z --name-only` and `mapfile -t -d ''`; a step runs `test -x scripts/oversight/.venv/bin/bandit` **after** the venv build and **before** `security_scan.sh`; the string `HOS_BANDIT_BIN` does not appear anywhere in the workflow file |
| ~~TC-D1..TC-D4~~ | AC-10, AD-6 | **Superseded by AD-22.** Covered by the retargeted `g1`–`g4h` cases in `test_security_scan_exemptions.py` (§15.1.3). Do not add PB-based duplicates. |
| ~~TC-D5~~ *(superseded: covered by the retargeted `g4b`, which names the override in the pass line; the unset-seam inertness is main's existing behaviour)* | AD-6 inertness | seam unset → the gate resolves the venv binary (assert the SKIP line when absent, else that a real run completes). Skip-guarded; marked `slow`/network-tolerant, since it is the one case that may touch the network |
| TC-D6 | AC-9 | tmp git repo + `contract/gate-suspension.md` containing `SUSPENDED: dependencies`, cwd=tmp_path (TV-9): `dependency_audit.sh` prints `GATE SUSPENDED: dependencies` and exits 0, **while `security_scan.sh` in the same tree still scans** a planted HIGH file |
| TC-D7 | AC-9 (converse) | same, with `SUSPENDED: security`: `security_scan.sh` is suspended, `dependency_audit.sh` (stubbed) still reports its findings |
| TC-D8 | AC-7 | `"security" not in AUTO_CHECKABLE_GATES and "dependencies" not in AUTO_CHECKABLE_GATES` (import the map, do not re-implement it) |

All stub-driven cases run with `GATE_TIMEOUT=20`, `GATE_RETRIES=1` (existing `_run` helper) and must not touch the network.

*(AD-22.)* TC-D6 and TC-D7 keep their assertions, but their pip-audit stub is a stdout-JSON stub in the `test_security_scan_exemptions.py::_stub` shape (`cat <payload>; exit <rc>`), not PB-1. Under main's lane, TC-D7's "still reports its findings" means rc 1 and the advisory line `  <pkg> <ver> [<id>] fix: …` from `filter`.

### 7.2 `tests/oversight/test_gate_arg_grammar.py` (modify)

1. `KIND_FILTER_GATES` gains `"security_scan": "Python"` (AD-5). `FILE_LIST_GATES` and `DEFAULTING_STRING_GATES` are **unchanged**.
2. Module docstring: the paragraph explaining that assertions avoid depending on pip-audit's network result for `security_scan.sh` must be rewritten — after #1605 that gate is offline and deterministic; the caveat now applies to nothing in this file. Say so, and say why (the network half moved to `dependency_audit.sh`, which is not in `FILE_LIST_GATES`).
3. **TC-G9 — `dependency_audit.sh` ignores its argv, except `--empty-changeset`** (the TC-G8 `collection_integrity` precedent, and the pin on TD-1 as narrowed by AD-2a). With `HOS_PIP_AUDIT_BIN` pointed at ~~stub PB-2~~ *(AD-22)* a stdout-JSON stub that prints `{"dependencies":[{"name":"anyio","version":"4.4.0","vulns":[]}]}` and exits 0, so the case is offline and deterministic. The roster lines that `filter` prints are date-dependent but identical within one test run. Run in a tmp git repo with one committed `.py`:
   - baseline (no args) vs `--diff HEAD~1` vs `a.py b.py` vs `--nope`: assert **identical stdout and identical rc** across these four. `--nope` producing the same output pins "no argv parsing beyond the one token" (no exit 2).
   - `--empty-changeset`, asserted separately: rc 0; stdout **differs** from the baseline; stdout contains `dependency_audit: NOT CHECKED — empty changeset (nothing was checked; this is not a pass)`; no `GATE PASS`. ~~`--empty-changeset` producing the same output as the baseline is the explicit pin on TD-1.~~ *(Withdrawn by AD-2a. The same-output assertion would now fail, and correctly.)* The no-network half of AD-2a (the stub is never invoked) is pinned in §4.2's two cases, not here. The as-built test at `a979a4605` matches.
4. **TC-G10 — auto-discovery (AC-8).** Run the runner's own discovery expression (`find scripts/oversight/gates -maxdepth 1 -name '*.sh' -not -name 'check_suspension.sh'`) and assert both `security_scan.sh` and `dependency_audit.sh` are in the result. This pins that a new gate file is picked up with no `run_gates.sh` edit. The companion assertion — that `run_gates.sh` has no diff — is a PR-level check (§12), not a unit test.

### 7.3 `tests/automation/test_dependency_audit_report.py` (new)

> *(D-5/AD-23: Part 3.)* The "workflow static" row below is extended by §15.9's three-job assertions. The new `github.py` read helpers are tested in `test_dependency_pause.py` (§15.9), not here.

Imports `from scripts.automation.dependency_audit_report import (...)` (repo-root conftest makes this work). **No network, no `gh`, no live GitHub anywhere in this file** (AC-28).

| Group | Cases |
|---|---|
| `normalize` | well-formed fixture → exact expected set; order-insensitivity (two shuffled inputs → equal sets); `fix_versions` sorted into the key; `fix: none` vs `fix: 1.2.3` produce **different** tuples (AC-20's deliberate choice); missing `dependencies` key / wrong types → raises `MalformedAuditJSON` (never returns an empty set). Fixtures use realistic ids (`GHSA-xxxx-xxxx-xxxx`, `CVE-2024-12345`, `PYSEC-2024-1`). Placeholders like `GHSA-x` fail the S-4 allowlist and belong only in the rejection rows below |
| `normalize` allowlist (SEC-S4) | **accepted:** `jinja2`/`Jinja2`/`zope.interface`/`typing_extensions` names; versions `4.2.0`, `1!2.0`, `1.0rc1`, `1.0.post1`, `2.0+local.1`; ids `GHSA-abcd-2345-wxyz`, `CVE-2024-123456`, `PYSEC-2024-17`, `OSV-2024-1`, `GO-2024-1234`. **Each rejected with `MalformedAuditJSON`, one case per field** (name, version, id, a single `fix_versions` entry): `@octocat`, `a b`, `<img src=x>`, `` `x` ``, `[x](http://e)`, `x\|y` (pipe), `x\ny`, `""`, an over-length value (`"a"*101` for names, `"1"*65` for versions/ids), and a non-string (`1`, `None`). A rejection anywhere fails the **whole** input, never just one finding. Entries with empty `vulns` are not pattern-checked and contribute nothing (pip-audit skip entries carry no `version`) |
| bounds (SEC-S4) | `MAX_FINDINGS` findings → accepted; `MAX_FINDINGS + 1` → `MalformedAuditJSON`. `fix_versions` of length `MAX_FIX_VERSIONS + 1` → `MalformedAuditJSON`. An input file larger than `MAX_INPUT_BYTES` → CLI exit 2 **without the file being parsed** (assert via a sparse/oversized tmp file). A `reconcile` whose rendered body or comment would exceed `MAX_BODY_CHARS` (monkeypatched to a small value) → raises `MalformedAuditJSON` with **`writer.calls == []`**, on the create, update and close rows alike. The size check runs before the first write, so it can never leave a comment posted without its body. **Every bound case above raises `OversizedAuditJSON`** (assert the subclass, not just the base), and at the CLI the `MAX_INPUT_BYTES` and `MAX_FINDINGS` cases exit 2 with stderr containing `oversized` and **not** `malformed` (§9.7). A pattern-failure case from the allowlist row keeps the `malformed` wording |
| workflow static (SEC-M1, SEC-S5) | parse `.github/workflows/dependency-audit.yml` with PyYAML (oversight venv): **both** `actions/checkout` steps set `persist-credentials: false`; the `report` job's `actions/download-artifact` step sets `path:` to a value beginning `${{ runner.temp }}`, and **no** download step lacks `path:`; the reconcile step's `env.AUDIT_JSON` begins `${{ runner.temp }}/audit-in/`, its `run` passes `--pip-audit-json "$AUDIT_JSON"`, and the `report` job's text contains **no** bare relative `pip-audit.json` argument; the reconcile `run` performs the regular-file/not-symlink check before the `python3 -m` line; the reconcile command does not contain ` -I ` (§10.2); `report` has no `if:` key (AC-25) |
| `render_body` / `parse_state` | round-trip: `parse_state(render_body(s)) == s` for empty, single, and multi-finding sets; body's **first line** is the marker; body contains `#1504`; body **text** carries no label directive (no `/label`, no `needs-ai` — this is about the body, not the issue's `labels` metadata, which carries `LABEL` per AD-12a); `parse_state` returns `None` for: missing open marker, missing close marker, non-JSON fence content, JSON that is not a list of 4-element entries, and an empty body — and **never** an empty set for any of them |
| `diff` | added-only, removed-only, both, neither |
| `reconcile` (recording writer) | one case per row of §9.5's decision table. **AC-21 asserts `writer.calls == []`** — zero recorded calls, not "no visible change". AC-22 asserts exactly one `post_comment` and exactly one `update_issue(body=…)`, in that order. AC-23 asserts comment → body → `state="closed"`, and **zero** calls when no issue exists or it is already closed. AC-24 asserts `state="open"` **first**, then comment, then body. The create row asserts the recorded `labels == [LABEL]` (AD-12b), and a create → `find_tracking_issue` round trip adopts what `reconcile` created (both conditions at once) |
| identity (AD-12a) | adopted only with **both** `LABEL` and the first-line marker — label-only and marker-only each → `None`; an unlabelled `render_body` issue (no `labels` key, or `labels: []`) → `None`; marker mid-body or after leading prose on line 1 → `None`; CRLF / trailing whitespace on line 1 tolerated; **near-miss label names rejected** (`dependency-audits`, `Dependency-Audit`, `dependency_audit`, `""` — exact, case-sensitive); bare-string label entries accepted and junk entries (`None`, ints, `{}`) ignored, never admitted |
| ambiguity | two **labelled-and-marked** issues → raises/exits non-zero with **zero** recorded writes; **unlabelled marker decoys never count**: one real labelled issue plus several unlabelled `render_body` decoys resolves to the real one (no raise), and at the CLI, unlabelled decoys with no real issue still let the first run create (exit 0, `labels=[LABEL]`); ~~page-cap-without-match → raises/exits non-zero with zero writes~~ *(amended 2026-10-14, ADR AD-12a "Lookup bound")* page-cap-without-match **over the label-filtered collection** → raises/exits non-zero with zero writes (the cap no longer counts unlabelled issues or PRs; see the Lookup-bound (e) row); `pull_request`-keyed entries are excluded before matching |
| Lookup bound (a): request shape (ADR AD-12a "Lookup bound" test (a)) | at the CLI, with the fake GitHub below, the consumer's recorded list-request argv carries **both** `state=all` **and** `labels=dependency-audit` (and `per_page=100`) in the endpoint path |
| Lookup bound (b): label validation (test (b)) | `list_issues(..., label=v)` for each of `"a,b"`, `"a b"`, `"a&state=open"`, `"a#b"`, `"%41"` and `""` raises `ValueError` with **zero** recorded `subprocess.run` calls |
| Lookup bound (c): volume independence, CLI level (test (c)) | a **discriminating** fake GitHub (below) serving a repo with more unlabelled issues **and** PRs than `page_limit × 100`, including unlabelled first-line-marker decoys. (i) No labelled issue, non-empty findings → the first run creates: exit 0, recorded create carries `labels=[LABEL]`, **exactly one** list page requested. (ii) One real labelled-and-marked issue → that issue is found and reconciled (its number is the one written to), **exactly one** list page requested. Because the fake returns the complete set, labelled or not, to any list request lacking `labels=`, dropping the filter turns this test red with `InconclusiveLookup` (exit non-zero, zero writes) |
| Lookup bound (d): the filter is not trusted (test (d)) | a fake that **ignores** `labels=` and returns unlabelled marker-first decoys, a labelled-and-marked entry carrying a `pull_request` key, and label-only (unmarked) issues → nothing is adopted (`find_tracking_issue` → `None`), and at the CLI the first run still creates (exit 0, `labels=[LABEL]`) |
| Lookup bound (e): the cap still binds the filtered set (test (e)) | `page_limit` full pages (100 each) of **labelled** entries with no doubly-qualified match → `GitHubError` from `list_issues`, surfaced as `InconclusiveLookup`, exit non-zero, **zero** writes |
| `GitHubWriter` label verification (AD-12b) | `lib.github.create_issue` patched to return `{"labels": []}` → `GitHubWriter.create_issue` raises `GitHubError` naming the missing label; returns accepted for `[{"name": LABEL}]`, `[LABEL]`, and `LABEL` among other labels |
| CLI | `main()` with `--dry-run` performs zero writes and exits 0; a malformed `--pip-audit-json` exits non-zero with zero writes; missing required args exits 2 |
| `github.py` helpers (folded per ADR shed 2) | `list_issues` paginates and stops at `page_limit`, drops `pull_request` entries, **raises `GitHubError` when a page yields no usable response (404 / empty body) and returns `[]` only for a genuine HTTP 200 `[]`** — these retained cases now run with `label="dependency-audit"`, and the recorded argv carries `labels=dependency-audit` (ADR AD-12a "Lookup bound" test (f); the 404→raise ruling is unchanged); with `label=None` the recorded endpoint path contains **no** `labels` parameter at all; a valid name such as `"a.b_c-1"` appears in the path as exactly `urllib.parse.quote("a.b_c-1", safe="")`. (Every name the allowlist admits is unreserved, so the encoding is an identity on accepted input. It is defence in depth behind the validation, and no test can, or needs to, show a changed byte.) Each invalid name from Lookup-bound (b) raises `ValueError` with zero subprocess calls; `create_issue` and `update_issue` both call `_run_gh` with `stdin_json=` and **never** a `--field`/`-f` argument (AC-27 — assert on the recorded argv); `create_issue` passes `labels` through into the `stdin_json` payload when non-empty and **omits the key** when `labels` is `None`/`[]`; `update_issue` omits keys whose value is `None` |

Mock at `subprocess.run` for the helper tests (the existing `test_github.py::_make_result` shape); everything else is pure.

**The Lookup-bound fake GitHub (rows (a), (c), (d), (e)).** It also sits at `subprocess.run`, so it exercises the real `list_issues`, `create_issue` and `GitHubWriter` code and still makes no network call (AC-28). It records every request argv and answers by endpoint path. **List requests** (`GET /repos/{o}/{r}/issues?...`): the discriminating variant used by (a) and (c) returns only entries whose `labels` contain the requested name when the path carries `labels=`, and returns the **complete set, labelled or not**, paged at 100, when it does not. The ignoring variant used by (d) returns its fixed set whatever the query says. **Create** (`POST`) returns an issue object that echoes the requested `labels` as `[{"name": …}]`. **Comment and update** calls return a minimal issue or comment object. Tests count list pages by counting recorded list-request argvs.

---

## 8. `scripts/automation/lib/github.py` (modify) — exactly three additions

> *(D-5, AD-16; Part 3.)* "Exactly three" now means three **write** helpers. Part 3 also adds the three narrow **read** helpers in §15.5. The file then has six #1605 additions in total and no others.

Placed after `get_commit` and before `post_comment`, under a new section comment `# --- REST-by-id issue writes (added for #1605's scheduled dependency audit) ---`. ~~No other line of the file changes.~~ *(Amended 2026-10-14, ADR AD-12a "Lookup bound": the label validation and encoding need two stdlib imports the file does not have today, which were re-measured on this branch as `json`, `subprocess`, `time` and `typing` only.)* The only other change is the addition of `import re` and `import urllib.parse` to the existing import block. No other line of the file changes. Each docstring must name #1605 as the single consumer and say that Search remains excluded by design.

```python
def list_issues(
    owner: str,
    repo: str,
    *,
    state: str = "all",
    label: str | None = None,
    page_limit: int = 50,
) -> list[dict[str, Any]]:
    """GET /repos/{owner}/{repo}/issues?state={state}[&labels={label}]&per_page=100
    (paginated).

    Returns issue objects with pull requests EXCLUDED (entries carrying a
    'pull_request' key are dropped — the REST issues endpoint returns both).
    Stops after `page_limit` pages; the caller MUST treat a full-cap result
    as an inconclusive lookup, never as 'not found' (#1605 AD-12).

    `label` is a SINGLE label name, not a list. Before any request it must
    fullmatch [A-Za-z0-9][A-Za-z0-9._-]*, otherwise ValueError is raised and
    no request is made. This rejects ',' (GitHub's multi-label AND separator)
    and '&', '#', '%', '?', '=' and whitespace, any of which would change the
    query. The value is then sent as urllib.parse.quote(label, safe="").
    `label=None` omits the parameter entirely. The server-side filter only
    NARROWS the result. It is not authoritative, and a caller that depends on
    the label for identity must re-check it on every returned entry (#1605
    ADR AD-12a "Lookup bound").

    Raises GitHubError when any page yields no usable response — `_run_gh`
    returns None for HTTP 404, a 404-shaped `gh` failure, and an empty body,
    and for a COLLECTION endpoint none of those means 'the collection is
    empty' (an existing repo answers 200 `[]` for that). An empty page is
    still an empty page: HTTP 200 with `[]` terminates pagination normally.
    Never uses Search.
    """
```

- Validation runs **first**, before the loop and before any `_run_gh` call: `label is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", label)` ⇒ `raise ValueError(...)`. The empty string fails the fullmatch.
- Each page's endpoint is `/repos/{owner}/{repo}/issues?state={state}` + (`&labels={quote(label, safe="")}` only when `label is not None`) + `&per_page=100&page={N}`, as one argv element, matching `list_issue_comments`. *(Amended 2026-10-14, ADR AD-12a "Lookup bound".)*
- Pagination follows `list_issue_comments`' shape — `while True`, `per_page=100&page=N`, break on `len(batch) < 100`, cap at `page_limit` — with one deliberate divergence: `list_issue_comments` treats a `None` from `_run_gh` as a terminating empty batch, and `list_issues` must **not**. A `None` (404, 404-shaped `gh` failure, empty body) is "could not determine"; only HTTP 200 `[]` is "empty". The two are checked separately: `if batch is None: raise GitHubError(...)` precedes `if not batch: break`.
- **PR exclusion happens here**, client-side, so no caller can forget it. *(Clarified 2026-10-14: this bullet refers to dropping `pull_request`-keyed entries. That stays client-side even when `label` is given, because PRs can carry labels. The server-side `labels=` filter is a separate narrowing step and is never a substitute for the caller's own label check.)*
- It must be possible for the caller to distinguish "exhausted naturally" from **every** way the loop can stop without having exhausted the result set. There are two such ways, and both raise `GitHubError` — the fail-closed direction, which the caller (§9.5) converts to exit-non-zero-with-zero-writes: (i) the page cap is reached with a full final page (`"list_issues: page limit N reached …"`); (ii) any page returns no usable response (`"list_issues: no usable response for page N …"`). Returning `[]` for either would let a lookup that never ran be read as authoritative absence — the single inference AD-12 exists to forbid, because it is what produces the duplicate tracking issue.

```python
def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: Optional[list[str]] = None,
) -> dict[str, Any]:
    """POST /repos/{owner}/{repo}/issues — body via stdin_json (#752/#1155).

    Returns the created issue object (at least 'number' and 'html_url').
    Raises GitHubError if GitHub returns no response.

    `labels` is sent only when non-empty. GitHub silently DROPS labels on
    create for a token without push access, so a caller that relies on the
    label for identification MUST read the returned 'labels' back and fail
    if its own label is absent (#1605 AD-12b — GitHubWriter.create_issue).
    """
    fields = {"title": title, "body": body}
    if labels:
        fields["labels"] = list(labels)
    result = _run_gh([f"/repos/{owner}/{repo}/issues", "--method", "POST"],
                     stdin_json=fields)
```

The `stdin_json` payload gains a `labels` key **only** when `labels` is non-empty; an omitted or empty `labels` sends `{"title", "body"}` exactly as before (an empty list must not be sent — it would read as "clear the labels"). The helper does **not** verify the label itself: verification belongs to the one caller that depends on it (§9.4), so the helper stays a thin transport.

```python
def update_issue(
    owner: str,
    repo: str,
    number: int,
    *,
    title: Optional[str] = None,
    body: Optional[str] = None,
    state: Optional[str] = None,
) -> dict[str, Any]:
    """PATCH /repos/{owner}/{repo}/issues/{number} — fields via stdin_json.

    Only the non-None keyword arguments are sent; a call with all three None
    is a programming error and raises ValueError rather than issuing an empty
    PATCH (an empty write is still a write — see AC-21).
    Returns the updated issue object. Raises GitHubError on no response.
    """
```

**Boundaries:** label handling is limited to `create_issue`'s optional `labels` pass-through (AD-12b) ~~— no label parameter on `update_issue` or `list_issues` (the lookup stays unfiltered, no `?labels=`, AD-12a)~~ *(superseded 2026-10-14, ADR AD-12a "Lookup bound")* and `list_issues`' one keyword. There is no label parameter on `update_issue`, and `list_issues` gains exactly one single-name `label` keyword (ADR AD-12a "Lookup bound"). There are no label-management helpers; no assignee/milestone parameters, no `close_issue()` convenience wrapper (`update_issue(state="closed")` is the one path), no Search, no `@path`-style body passing anywhere. Non-goal 7 is satisfied by building exactly what §9 calls.

---

## 9. `scripts/automation/dependency_audit_report.py` (new)

### 9.1 Module contract

- Module docstring's **first paragraph must be a single sentence** (TV-7) — e.g. `"""dependency_audit_report.py — reconcile a pip-audit JSON report against a single label-authenticated GitHub tracking issue (#1605)."""` — followed by a blank line and the detail.
- **stdlib only**, plus `scripts.automation.lib.github`. No `requests`, no third-party anything: the job that runs it holds `issues: write` and installs nothing (AD-10).
- **It never runs `pip-audit`** and never reads the network except through `lib.github`. Acquisition belongs to the `audit` job.
- Importable and CLI-guarded (`if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`).
- Invoked as `python3 -m scripts.automation.dependency_audit_report` (D-1).

### 9.2 Constants

```python
MARKER       = "<!-- hos-dependency-audit -->"
LABEL        = "dependency-audit"   # the authenticator (AD-12a)
STATE_OPEN   = "<!-- hos-dependency-audit:state -->"
STATE_CLOSE  = "<!-- /hos-dependency-audit:state -->"
TITLE        = "Dependency vulnerabilities — pip-audit (scheduled report)"
CROSS_REF    = 1504        # rendered as "#1504" in the body
```

`TITLE` is cosmetic and **never matched on** (AC-20). `MARKER` is a public constant and therefore authenticates nothing on its own; `LABEL` is the authenticator (AD-12a).

**Input allowlist and bounds (SEC-S4, binding).** Every value that enters a `Finding`, and so gets rendered into a body, comment, or state block, must full-match its pattern with `re.fullmatch`, never `re.match`. Each pattern is compiled once at module level:

```python
NAME_RE    = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?"     # PEP 508 name, ≤100 chars
VERSION_RE = r"[A-Za-z0-9](?:[A-Za-z0-9.!+_-]{0,62}[A-Za-z0-9])?"   # PEP 440-ish (epoch !, local +), ≤64
VULN_ID_RE = (r"GHSA(?:-[0-9a-z]{4}){3}"                          # GitHub advisory
              r"|CVE-\d{4}-\d{4,7}"                               # CVE
              r"|PYSEC-\d{4}-\d{1,7}"                             # PyPA advisory DB
              r"|[A-Z][A-Z0-9]{1,15}-[A-Za-z0-9-]{1,48}")         # OSV-style PREFIX-ID (OSV-, GO-, RUSTSEC-, …)
MAX_FINDINGS     = 500
MAX_FIX_VERSIONS = 32          # per finding; each entry must match VERSION_RE
MAX_INPUT_BYTES  = 8 * 1024 * 1024
MAX_BODY_CHARS   = 60_000      # under GitHub's 65,536-char body/comment limit
```

The patterns exclude whitespace, `@`, `<`, `>`, `[`, `]`, `(`, `)`, `|`, backticks, and newlines **by construction**. An allowlisted value therefore cannot carry a mention, an HTML comment that forges `STATE_OPEN`/`STATE_CLOSE` or `MARKER`, a markdown link, or a table-cell break. This is the minimum bar. It is **not** general output escaping, which stays with #1812. The patterns are deliberately looser than the PEP grammars, because a real advisory must never be rejected as malformed. They are tight only on the characters that matter for rendering. Changing a pattern is a design change, not a code fixup.

### 9.3 Types and pure functions

```python
Finding = tuple[str, str, str, tuple[str, ...]]     # (name, installed_version, vuln_id, sorted fix_versions)

class MalformedAuditJSON(Exception): ...
class OversizedAuditJSON(MalformedAuditJSON): ...   # a SEC-S4 *bound* was exceeded (MAX_INPUT_BYTES, MAX_FINDINGS,
                                                    # MAX_FIX_VERSIONS, MAX_BODY_CHARS) by otherwise well-formed input; §9.7
class AmbiguousTrackingIssue(Exception): ...        # >1 issue carrying BOTH LABEL and the first-line marker
class InconclusiveLookup(Exception): ...            # lookup not shown to be exhaustive: page cap, or a page with no usable response

def normalize(pip_audit_json: dict) -> set[Finding]:
    """AC-20's comparison unit. Order-insensitive by construction.

    Raises MalformedAuditJSON on any shape deviation — NEVER returns an empty
    set for unreadable input, which would read as 'all vulnerabilities fixed'
    (AC-25 in depth, behind AD-10's job split).

    SEC-S4: also raises MalformedAuditJSON if any name / installed version /
    vuln id / fix_versions entry of a finding-bearing dependency fails its
    §9.2 pattern, if a finding has more than MAX_FIX_VERSIONS fix versions, or
    if the result would hold more than MAX_FINDINGS findings. The two count
    bounds raise the OversizedAuditJSON subclass; a pattern failure (including
    an over-length single value, which fails the pattern) raises plain
    MalformedAuditJSON. One bad value
    rejects the whole input; values are never dropped, truncated or rewritten.
    Fields pip-audit emits that are not part of a Finding (aliases,
    description, skip_reason) are never read and never rendered.
    """

def render_body(findings: set[Finding]) -> str:
    """MARKER on line 1; prose; a markdown table of findings; the #1504
    cross-reference; then the state block (STATE_OPEN, a ```json fence holding
    json.dumps(sorted(findings)) with tuples as arrays, STATE_CLOSE).
    Deterministic: the same set always renders byte-identically.
    """

def parse_state(body: str) -> set[Finding] | None:
    """Recover the previous set from the state block. Returns None — meaning
    UNKNOWN, never empty-and-clean — if the body is missing either delimiter,
    the fence is absent, the JSON does not parse, or any entry is not
    [str, str, str, [str, ...]]. Reads the block only; never the prose.
    """

def diff(old: set[Finding], new: set[Finding]) -> tuple[set[Finding], set[Finding]]:
    """(added, removed)."""

def _label_names(entries) -> set[str]:
    """Label names from GitHub's [{"name": ...}] list, also accepting bare
    strings. Non-string names and entries of any other type are DROPPED,
    never admitted as None. Shared by the read path (_carries_label) and the
    write-verification path (GitHubWriter.create_issue) so they cannot drift
    (AD-12a)."""

def _carries_label(issue: dict) -> bool:
    """LABEL in _label_names(issue.get("labels")) — exact, case-sensitive.
    No 'labels' key fails closed (False). The authenticator (AD-12a)."""

def _carries_marker(issue: dict) -> bool:
    """body.splitlines()[0].strip() == MARKER — first line only; tolerates
    CRLF and trailing whitespace, never leading prose; empty body is False.
    The round-trip check, not an authenticator (AD-12a)."""

def find_tracking_issue(issues: list[dict]) -> dict | None:
    """Adopt an issue only when _carries_label AND _carries_marker. Issues
    failing either are filtered out BEFORE counting, so unlabelled marker
    decoys can neither raise AmbiguousTrackingIssue nor block the first-run
    create, whatever their NUMBER: the predicate covers their count, and the
    label-filtered list_issues query keeps their VOLUME out of the page cap
    (ADR AD-12a "Lookup bound"). Raises AmbiguousTrackingIssue on >1
    doubly-qualified match. The label is re-checked here on every entry even
    though list_issues is label-filtered server-side; the server filter
    narrows, it never authenticates (ADR AD-12a "Lookup bound"). Never
    matches on title (AC-20).
    """

def render_delta_comment(added, removed, previous_unknown: bool) -> str:
    """ONE comment describing the whole delta — never one per finding (AC-22).
    When previous_unknown, the comment says so explicitly and presents the
    current set as a full update.
    """

def render_closing_comment(previous: set[Finding]) -> str:
    """The zero-findings comment (AC-23)."""
```

### 9.4 The writer seam (what makes AC-21/AC-28 true rather than aspirational)

```python
class Writer(Protocol):
    def create_issue(self, title: str, body: str, labels: list[str]) -> dict: ...
    def post_comment(self, number: int, body: str) -> dict: ...
    def update_issue(self, number: int, *, body: str | None = None,
                     state: str | None = None) -> dict: ...

class GitHubWriter:      # owner/repo bound at construction; delegates to lib.github
class RecordingWriter:   # records ("create_issue"|"post_comment"|"update_issue", kwargs) tuples; performs nothing
                         # create_issue's kwargs include "labels"; its fake return carries them as [{"name": …}]
```

**`GitHubWriter.create_issue` verifies the label stuck (AD-12b).** It calls `lib.github.create_issue(owner, repo, title, body, labels=labels)`, reads `labels` from the **issue object returned by that POST** via `_label_names`, and raises `GitHubError` naming the issue number and every requested label that is absent. No second lookup. The error propagates out of `reconcile` to `main()` ⇒ exit 1 (§9.7). ~~— a loud red first run, never a silent weekly duplicate.~~ *(Superseded by ADR AD-12b as amended 2026-10-14, security design review S-2.)* The failure is **loud and recurring, never silent**. The issue just created is unlabelled and so invisible to `find_tracking_issue`'s predicate (AD-12a). Every later run (weekly, and every `workflow_dispatch`) reads "none exists", may create **another** unlabelled issue, and goes red again with the same message, until an operator fixes the cause and runs the §11.2(d) clean-up. That is the intended failure mode. A quiet duplicate is forbidden. A loud recurring red is required. No code change is specified for it: the remedy is operational (§11.2(d) part 3). The `GitHubError` message must name the issue number and the missing label, so the operator can find the stray. The check fires only on create; reopen re-adopts the existing issue and never re-creates.

`--dry-run` binds a `RecordingWriter` and prints the recorded calls. Tests bind the same class and assert on `writer.calls`. **Every** write in the module goes through the injected writer; no function may call `lib.github` directly.

### 9.5 `reconcile(new, issue, writer) -> Plan`

`Plan` is a small dataclass: `action: str` (one of `create`, `update`, `reopen`, `close`, `noop`) and `writes: list[tuple[str, dict]]` mirroring what was sent to the writer. Decision table — binding, and the row order is the test order:

| new set | issue state | previous (`parse_state`) | action | writes, **in this order** |
|---|---|---|---|---|
| non-empty | no issue | — | `create` | `create_issue(TITLE, render_body(new), labels=[LABEL])` (AD-12b) |
| non-empty | open | `== new` | `noop` | **none** (AC-21) |
| non-empty | open | `!= new` | `update` | `post_comment(delta)` → `update_issue(body=render_body(new))` |
| non-empty | open | `None` (unknown) | `update` | `post_comment(delta, previous_unknown=True)` → `update_issue(body=render_body(new))` |
| non-empty | closed | any | `reopen` | `update_issue(state="open")` → `post_comment(delta)` → `update_issue(body=render_body(new))` |
| empty | no issue | — | `noop` | **none** — never create an issue asserting zero findings (AC-23) |
| empty | closed | any | `noop` | **none** |
| empty | open | any | `close` | `post_comment(closing)` → `update_issue(body=render_body(set()))` → `update_issue(state="closed")` |

A closed issue with a non-empty set **always** reopens, even when `previous == new`: the notification state, not just the finding set, is what is wrong.

**Render before the first write (SEC-S4).** For every row that writes, `reconcile` renders **all** of that row's texts before its first writer call: the body, and the delta or closing comment. If any rendered text exceeds `MAX_BODY_CHARS`, it raises `OversizedAuditJSON` (a `MalformedAuditJSON` subclass, §9.3) with **zero** writes. A size failure that surfaced only after the comment was posted would leave a notification with no matching state block, which is the inverse of the invariant below.

**Write-ordering invariant (AD-12), which the table encodes:** the comment is always written before the body, the state block always last, and `state` transitions last of all — except the reopen, where `state="open"` must precede the comment so the comment lands on an open issue. An interrupted run must leave the **state block stale**, never the **notification missing**: a stale block re-fires the same delta next week (one duplicate comment); a missing comment is a permanently lost signal.

### 9.6 Lookup and fail-closed behaviour

```
issues = github.list_issues(owner, repo, state="all", label=LABEL, page_limit=50)   # AD-12, AD-12a "Lookup bound"
issue  = find_tracking_issue(issues)
```

*(Amended 2026-10-14, ADR AD-12a "Lookup bound": the call now passes `label=LABEL`. The previous call carried no label.)*

- `state="all"` — open **and** closed, so AC-24's reopen can find its own issue.
- `gh search` is forbidden (index lag ⇒ missed match ⇒ duplicate issue, permanently breaking AC-20). `lib.github` excludes Search by design.
- No `creator=` filter~~, and **no `?labels=` filter** — the listing stays unfiltered and the label is tested in `find_tracking_issue`'s predicate (AD-12a), so `list_issues`' `[]`-vs-raise semantics (§8) are untouched~~. *(Struck 2026-10-14, superseded by ADR AD-12a "Lookup bound".)*
- **The listing is label-filtered server-side; the predicate stays the authenticator (ADR AD-12a "Lookup bound").** The request is `?state=all&labels=dependency-audit&per_page=100`. The filter only narrows the candidate set, so unlabelled issues and PRs, whether an outsider's or the repo's organic growth (about 2,100 today, growing about 800 a month), never count toward the page cap. `find_tracking_issue` still re-tests the exact label **and** the first-line marker on every returned entry. If GitHub ignored or loosened the filter, the outcome would degrade to the pre-amendment behaviour (every issue and PR listed), failing closed at the cap. It would never adopt the wrong issue. `list_issues`' `[]`-vs-raise semantics (§8) are unchanged: a `None` page raises, a full page at the cap raises, and only HTTP 200 `[]` means empty. A normal run makes one list call. **Two assumptions stay unverified until the first live run** (the same class as AD-12b's): (i) a filter naming a not-yet-existing label returns HTTP 200 `[]`, not 404/422. If that is wrong, `list_issues` raises on page 1 and every run goes red with **zero writes and no duplicate** until the label exists. The remedy is §11.2(d) clean-up step 1 (create the label). (ii) The label filter is a consistent read of the issue record, not a lagging search index. If a stale filtered view missed the real issue, one run would create a second labelled issue, and the next run would go red on `AmbiguousTrackingIssue`. The worst case is one duplicate and one red run, never a silent recurrence.
- **Ambiguity fails closed in both directions, with zero writes:** `AmbiguousTrackingIssue` (two or more labelled-and-marked issues — a duplicate already exists, a human resolves it; unlabelled decoys never reach this) and `InconclusiveLookup` (cap reached **over the label-filtered collection**, which only triage-capable actors can grow, inside AD-12a's existing triage residual; or a page returned no usable response — a create on an uncertain lookup *is* the duplicate).
- **Two recurring-red residuals, both loud, both accepted in the ADR.** (i) AD-12b's label-did-not-stick failure (§9.4) repeats on every run until an operator fixes it. (ii) AD-12a's confused-deputy residual (S-3): a triager who labels an outside author's marker-first decoy in good faith makes it a second match, so every run raises `AmbiguousTrackingIssue` with zero writes until a human removes the label or closes the decoy. Before the first run, or after a closure, the decoy is adopted instead. Neither residual is closed in code. Both are mitigated by the §11.2(d) runbook text and by the binding ADR condition that **no issue template, issue-form `labels:` key, or labelling workflow or bot may apply `dependency-audit`**. The only legitimate applier is the create path here. This PR adds no such template or workflow, and any later change that does reverses AD-12a.

### 9.7 CLI and exit codes

```
python3 -m scripts.automation.dependency_audit_report \
    --pip-audit-json <path> --owner <o> --repo <r> [--dry-run]
```

| Exit | Meaning |
|---|---|
| 0 | reconciled (including `noop`), or `--dry-run` completed |
| 1 | inconclusive/ambiguous lookup, or a GitHub write failed (including AD-12b's label-did-not-stick `GitHubError`, which leaves one unlabelled issue behind) — **zero or partial writes; the run is visibly red** |
| 2 | usage error, or `--pip-audit-json` missing/unparseable/malformed (`MalformedAuditJSON`, including every SEC-S4 allowlist violation, and every bound violation as its `OversizedAuditJSON` subclass: the file is read with a bound of `MAX_INPUT_BYTES + 1` bytes, and if more than `MAX_INPUT_BYTES` came back it is refused **before** `json.loads`, so the bound does not depend on a separate size check that could race the read) — **zero writes** |

Every non-zero path must print the cause to stderr and must not be reachable after a `close` write.

**Tracking-issue line (D-5, AD-16; Part 3).** On exit 0 only, and excluding `--dry-run`, `main()` prints exactly one final stdout line: `dependency_audit_report: tracking_issue=<N|none>`. `N` is the number of the issue that `reconcile` created or wrote to, or that the lookup adopted on a `noop`. `none` means no issue exists (the empty-set `noop`). The `report` job turns this line into its `issue` output (§15.3). The `outcome` job cannot look the issue up itself, because it holds no token scope. Test: one CLI case per decision-table row asserts the line, and `--dry-run` prints no such line.

**Oversized is not malformed (stderr wording, for ops).** `main()` catches `OversizedAuditJSON` **before** `MalformedAuditJSON` and prints `dependency_audit_report: oversized pip-audit input: <which bound> exceeded (limit <N>)`, naming the bound constant (`MAX_INPUT_BYTES`, `MAX_FINDINGS`, `MAX_FIX_VERSIONS` or `MAX_BODY_CHARS`). That line must **not** contain the word "malformed". An operator reading a red run must be able to tell "the advisory set grew past a bound" (raise the bound, a design change per §9.2) from "the input is broken or hostile" (investigate the `audit` job). The exit code (2) and the zero-write guarantee are unchanged, and every other `MalformedAuditJSON` keeps today's `malformed pip-audit JSON:` prefix. The `MAX_INPUT_BYTES` refusal happens before `json.loads`, so it raises `OversizedAuditJSON` directly from the bounded read.

---

## 10. Workflows

### 10.1 `.github/workflows/oversight-gates.yml` (modify) — three edits

**Edit 1 — header, per-gate debt baseline block.** Append after the `oversight-gate-lint` entry, matching the block's indentation:

```
#   oversight-gate-security-scan — zero debt: 0 HIGH findings over 219 tracked
#                                  .py files, measured 2026-09-22 through
#                                  bandit's `-o` file channel (NOT stdout,
#                                  which carries a progress bar once a scan
#                                  exceeds ~1s — see DECISIONS.md, #1605).
#                                  The measurement method is part of this
#                                  entry: a bare "zero debt" would be
#                                  indistinguishable from a fail-open reading.
#                                  Not promoted to required — #1605 wires,
#                                  promotion is its own decision (F-1).
```

**Edit 2 — header, file-scoped group list.** `(secret-scan, lint, type-check, bash-check, portability, template-refs)` → `(secret-scan, security-scan, lint, type-check, bash-check, portability, template-refs)`.

**Edit 3 — header, the deliberately-not-wired paragraph.** Replace the `security_scan (pip-audit against the CI venv's …) and collection_integrity …` sentence with:

> `dependency_audit` (pip-audit against the CI venv's installed dependency versions, not the PR's changed files — network-dependent, and dependency posture is not a property of a diff) and `collection_integrity` (duplicates `tests.yml`'s own pytest collection) are deliberately not wired in here. `dependency_audit` runs weekly in `dependency-audit.yml` instead (#1605); see DECISIONS.md's 2026-09-10/11 #1216 entries for the original classification.
>
> *(AD-23, Part 2.)* Until Part 3 lands, `dependency-audit.yml` does not exist. Part 2 writes the sentence as `… runs on a schedule in a separate workflow instead (#1605, Part 3) …`. It must not name a file that is not on main. Part 3 does not edit this header again, because the sentence is still true.

**Edit 4 — the new job**, inserted **after `oversight-gate-template-refs` and before `oversight-gate-repo-scoped`** so the diff is one contiguous insertion and no existing job moves. It follows the other file-scoped jobs' #1571 step shape (AC-12) and differs only in the two names, the final command, and the two security-review amendments listed beneath the block: the scanner-presence step (SEC-S1) and the `-z` listing (SEC-M2).

```yaml
  oversight-gate-security-scan:
    name: oversight-gate-security-scan
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Checkout PR head
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build oversight venv
        env:
          HOS_SKIP_PROJECT_REQUIREMENTS: "1"
        run: bash scripts/oversight/ensure_venv.sh
      - name: Assert the scanner is present
        run: |
          test -x scripts/oversight/.venv/bin/bandit \
            || { echo "bandit missing from the oversight venv — the scan cannot run; failing rather than reporting SKIP." >&2; exit 1; }
      - name: Run security_scan
        env:
          GITHUB_BASE_REF: ${{ github.base_ref }}
        run: |
          set -euo pipefail
          git fetch origin "$GITHUB_BASE_REF" --depth=1
          mapfile -t -d '' FILES < <(git diff -z --name-only "origin/$GITHUB_BASE_REF...HEAD")
          if [[ ${#FILES[@]} -eq 0 ]]; then
            echo "No changed files against origin/$GITHUB_BASE_REF — skipping."
            exit 0
          fi
          bash scripts/oversight/gates/security_scan.sh "${FILES[@]}"
```

Binding details: `HOS_SKIP_PROJECT_REQUIREMENTS: "1"` (#1380 — the PR head is content we do not control, AV-9); changed files, never `--all` (AC-13); no job-level `permissions` block (`contents: read` is inherited); `dependency_audit.sh` must not appear anywhere in this file (AC-11 — grep-testable); `setup_branch_protection.sh` untouched (AC-15).

**Security-review amendments to this job (2026-10-14). Each is a deliberate divergence from AC-12's "step-for-step identical", and the security-scan job is the only one that diverges:**
- **SEC-S1, scanner presence.** The `Assert the scanner is present` step is mandatory. A failed or partial venv build would otherwise reach §3.5's `SKIP: bandit not in oversight venv`, exit 0, and give a **green job that scanned nothing**. The local `SKIP` stays unchanged: it is honest on a developer machine, but the CI job must not inherit it. `HOS_BANDIT_BIN` must never be set anywhere in this workflow, since the seam is test-only (§5). TC-S18 pins both.
- **SEC-M2, NUL-delimited listing.** `git diff -z --name-only` with `mapfile -t -d ''` is binding. Under the default `core.quotepath=true`, a non-ASCII Python file prints as `"\303\251.py"`, fails `security_scan.sh`'s `*.py` filter, and is **silently skipped as non-Python** (TV-11). `-z` disables quoting and also keeps a newline inside a filename from splitting one path into two. (`git -c core.quotepath=false diff --name-only` fixes the quoting but not the newline case, so it is not the chosen form.) The workflow `run:` block is bash 5 on `ubuntu-latest` and is not scanned by `bash_check.sh` (TV-8), so `mapfile -d` is permitted here.
- **Option-like filenames.** These reach the gate as explicit argv, so `hos_changeset_parse` rejects them with exit 2 (TV-12). A PR that adds `-x.py` therefore gets a **red** job, not a bypass. That false red is accepted, and the job must not rewrite paths to avoid it (§3.6).
- **Not changed here:** the other six file-scoped jobs in this file still use `mapfile -t FILES < <(git diff --name-only …)` and share the quotepath defect. Converting them is a repo-wide follow-up (**#1812**), not this PR. This job's divergence from them is the intended temporary state.

Known inherited residual, **not** introduced here and **not** to be fixed in this PR: a PR whose diff is entirely deletions makes every file-scoped job exit 3 (#1759 RISK-1 / D5). The new job inherits it.

### 10.2 `.github/workflows/dependency-audit.yml` (new)

> **AMENDED by D-5 (§15.3); Part 3.** The `audit` job's `Run pip-audit` step below is replaced by §15.3's `venv` and `measure` steps, and the job gains `outputs:`. `report` gains an `id`'d step and an `issue` output. A third job, `outcome`, is added. Every binding property below **still holds**: the trust split, SEC-M1 isolation, SEC-S5, the D-2 pin, `needs: audit` with no `if:` on `report`, no App token, and no PR trigger. §15.3 adds properties and removes none.

```yaml
name: Dependency audit (scheduled)

# <header comment — see below>

on:
  schedule:
    - cron: "17 6 * * 1"        # weekly, Monday 06:17 UTC (I-5; off the :00 peak)
  workflow_dispatch:            # NO inputs (AD-11)

permissions:
  contents: read                # top-level floor

concurrency:
  group: hos-dependency-audit
  cancel-in-progress: false     # AC-19 — never interrupt a run mid-write

jobs:
  audit:
    name: dependency-audit-scan
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: read            # installs third-party wheels; holds NO write scope
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}   # D-2
          fetch-depth: 1
          persist-credentials: false                          # SEC-S5
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build oversight venv (with project requirements — AV-9)
        run: bash scripts/oversight/ensure_venv.sh
      - name: Run pip-audit
        run: |
          set -uo pipefail
          RC=0
          scripts/oversight/.venv/bin/pip-audit --progress-spinner off \
            --format json -o pip-audit.json || RC=$?
          if [[ "$RC" -ne 0 && "$RC" -ne 1 ]]; then
            echo "pip-audit failed to complete (exit $RC) — failing the job." >&2
            exit 1
          fi
          python3 -c 'import json,sys; json.load(open("pip-audit.json"))' \
            || { echo "pip-audit output is not parseable JSON — failing the job." >&2; exit 1; }
      - uses: actions/upload-artifact@v4
        with:
          name: pip-audit-json
          path: pip-audit.json
          if-no-files-found: error
          retention-days: 7

  report:
    name: dependency-audit-report
    needs: audit
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      issues: write             # the ONLY write scope in this repo's gate/report workflows
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}   # D-2
          fetch-depth: 1
          persist-credentials: false                          # SEC-S5
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/download-artifact@v4
        with:
          name: pip-audit-json
          path: ${{ runner.temp }}/audit-in                   # SEC-M1 — never the workspace
      - name: Reconcile the tracking issue
        env:
          GH_TOKEN: ${{ github.token }}
          AUDIT_JSON: ${{ runner.temp }}/audit-in/pip-audit.json
        run: |
          set -euo pipefail
          if [[ ! -f "$AUDIT_JSON" || -L "$AUDIT_JSON" ]]; then
            echo "artifact did not deliver a regular pip-audit.json — refusing to reconcile." >&2
            exit 2
          fi
          python3 -m scripts.automation.dependency_audit_report \
            --pip-audit-json "$AUDIT_JSON" \
            --owner "${{ github.repository_owner }}" \
            --repo "${{ github.event.repository.name }}"
```

**Binding properties (each independently checkable by inspection or grep):**

- **Two jobs, and the split is the trust boundary (AD-10).** `pip install -r requirements*.txt` executes third-party build backends from PyPI; one job would put that code in the same process tree as an `issues: write` token. `audit` executes untrusted wheels with a read-only token; `report` holds the write token and installs nothing (**no `ensure_venv.sh` in `report`** — system Python plus the preinstalled `gh` is all `lib.github` needs).
- **AC-25 is structural, not behavioural.** `needs: audit` with **no `if:` override** means a failed `audit` skips `report` entirely, so a permanent network failure can never read as "all vulnerabilities fixed" and auto-close the issue. Adding `if: always()` to `report` is forbidden.
- **No `pull_request` / `pull_request_target` trigger; the workflow can never fail a PR check** (AC-18).
- **No App-token minting** — `${{ github.token }}` only (the `label-swap.yml` precedent).
- Nothing in either job may read `github.event.inputs`, `github.head_ref`, or any fork-controlled value (AD-11). `github.repository_owner` and `github.event.repository.name` are GitHub-set and permitted.
- No workflow step applies a label. The one label, `dependency-audit`, is applied by `dependency_audit_report` on create through `report`'s `issues: write` token and verified from the create response (AD-12b); `issues: write` is therefore load-bearing for identification, not only for writing. No pending-actor label (`needs-ai` etc.) is ever applied.
- **SEC-M1: the artifact is data, never code, and never lands in the workspace.** `actions/download-artifact` with only `name:` extracts into `$GITHUB_WORKSPACE`, over the checked-out tree. `python3 -m scripts.automation.dependency_audit_report` then runs from that tree, with `issues: write`. A compromised `audit` job could ship files that overwrite tracked modules such as `scripts/automation/lib/github.py`, or shadow them, and turn the artifact channel into code execution under the write token (CWE-829/CWE-94). This is AD-10's own threat (third-party build backends run in `audit`), arriving through the one channel the split leaves open. **Binding, checkable properties:** (i) every `actions/download-artifact` step in this workflow sets `path:` under `${{ runner.temp }}`, so nothing from the artifact is extracted under `$GITHUB_WORKSPACE`; (ii) the `report` job reads **exactly one** file from the artifact: `$RUNNER_TEMP/audit-in/pip-audit.json`, which must be a regular file and not a symlink. It is passed by absolute path to `--pip-audit-json`, and no other path under `audit-in/` is read, sourced, executed, or put on `PYTHONPATH`; (iii) the checkout precedes the download, and nothing after the download writes into the workspace. Pinned by §7.3's workflow-static group.
- **Do NOT use `python3 -I -m`.** `-I` implies safe-path, which drops cwd from `sys.path`, so `-m scripts.automation.…` stops resolving from the checkout (TV-3). Isolation comes from (i)–(iii), not from interpreter flags. The same applies to `PYTHONSAFEPATH`, which must not be set on this step.
- **SEC-S5: `persist-credentials: false` on both checkouts.** In `audit`, the persisted token in `.git/config` would be readable by the third-party build backends that `ensure_venv.sh` executes. It is read-only, but a credential is still a credential. In `report`, nothing uses git auth after checkout: `lib.github` authenticates through `GH_TOKEN`. Neither job pushes, so neither needs persisted credentials.
- **Residual, accepted (R-4, §14). Fail-closed is structural only against an *honest* `audit` failure.** `needs: audit` with no `if:` stops a crashed, timed-out, or network-failed `audit` from ever reaching `report` (AC-25). It does **not** stop a *compromised* `audit`, which can upload a well-formed, empty `dependencies` list and let `report` close the tracking issue as "all fixed", or upload a fabricated finding set. No design inside this workflow can tell a forged-but-valid report from a real one: the trust is in the job that produced it. SEC-S4 (§9.2) **bounds the damage**: a forged report can carry no mention, no markup, and no oversized body, and it cannot forge the state block. It cannot prevent a false close or a false finding. The mitigation for that is out-of-band. The close is a visible comment on a labelled issue, and #1504 independently tracks the same vulnerabilities, so a false all-clear contradicts a still-open #1504.

**Header comment must record:** that this is the repo's first `on: schedule` workflow; the two-job trust-boundary rationale; why the checkout ref is pinned (D-2); that `report` never runs if `audit` fails, and that this is the mechanism for AC-25; the weekly cadence rationale (I-5) and that cron + cadence are one-line reversible; that the tracking issue deliberately overlaps #1504 (I-4, resolved later by F-4); and that the issue is authenticated by the `dependency-audit` label (AD-12a), which must not be hand-removed, with the accepted triage-insider residual (#1812 item 5); **and (SEC-M1/SEC-S5)** that the artifact is downloaded outside the workspace and read as one JSON file only, why `-I` is not used, why both checkouts drop persisted credentials, and the R-4 residual that a compromised `audit` can still forge a valid report.

---

## 11. Documentation edits

### 11.1 `docs/specs/SPEC-375-deterministic-gate-invariant.md`

In §3.1's **Gates** table, insert immediately after the `security_scan.sh` row:

```
| `dependency_audit.sh` | `dependencies` [†] |
```

and add, directly beneath the table's existing `check_suspension.sh` note:

> [†] `dependency_audit.sh` queries a live advisory database, so it satisfies §3.1's "same result for the same input" clause only relative to that database as of the run. It is listed here because it is a gate under the invariant (a non-suspended non-zero exit is a deterministic failure for REQ-GATE-NN purposes); it is deliberately **not** wired into `.github/workflows/oversight-gates.yml`, which is offline-only (#1605).

No other line of the spec changes. (The table's pre-existing omission of `bash_check.sh` and `astro_check.sh` is out of scope — do not "fix" it here.)

### 11.2 `docs/OVERSIGHT-RUNBOOK.md` — four edits

> *(AD-23 split.)* Edits (a), (b) and (c) are **Part 2**. Edit (d), on the label and tracking issue, is **Part 3**, together with the new edit (e) in §15.10.

**(a) Gate name reference table (~:149).** Insert after the `security_scan.sh` row:

```
| `dependency_audit.sh` | `dependencies` | — |
```

**(b) The auto-re-enable note (~:169).** The sentence currently reads "…pure script gates (lint, types, secrets, template-refs, portability, django) are auto-re-enabled after consecutive clean passes; reviewer-role suspensions — and `security`, which has a reviewer counterpart a passing scan can't satisfy — are removed only by a human." Extend the human-only clause to name `dependencies`, with its own reason: *"…and `dependencies`, whose pass depends on a live advisory database and is therefore not reproducible on demand"*. This keeps the prose consistent with AC-7 / AD-1 (neither key is in `AUTO_CHECKABLE_GATES`).

**(c) The invocation block (~:301).** After the existing security-scan lines, add:

```bash
# Security scan (bandit, HIGH severity = blocking; file-scoped, offline)
bash scripts/oversight/gates/security_scan.sh [changed files...]

# Dependency audit (pip-audit; repo-scoped and network-dependent — takes no
# file arguments and ignores any it is given)
bash scripts/oversight/gates/dependency_audit.sh
```

and, immediately after the block's "All must exit 0 before proceeding" line, one short paragraph recording AD-2 as amended by AD-2a (ADR §2a "Downstream record-keeping"):

> ~~Since #1605 the dependency audit is repo-scoped: `run_gates.sh` runs it even when the changeset resolves to zero files, where the old bundled gate short-circuited. That is deliberate — dependency posture is a property of the installed environment, not of a diff — but it means an empty-changeset run now makes a network call and can report `GATE FAIL` on pre-existing findings (#1504). The only sanctioned ways to stop it are a human suspension of the `dependencies` key or fixing the findings.~~ *(Withdrawn by AD-2a.)*
>
> Required substance: since #1605 the dependency audit is repo-scoped. It ignores every path argument `run_gates.sh` forwards, because dependency posture is a property of the installed environment, not of a diff. It skips only the runner's explicit `--empty-changeset` no-op run (AD-2a), reporting `NOT CHECKED` with no network call. Any other invocation, including a bare direct run, still checks. The only sanctioned ways to stop a checked run from reporting `GATE FAIL` are a human suspension of the `dependencies` key or fixing the findings (#1504).

The as-built runbook paragraph at `a979a4605` satisfies this. This is the "prose beyond the gate→key table row" that S-6 lists as shed #2. It is **not** shed: it is the record AD-2/AD-2a require, and it is a few sentences.

**(d) The label rule, the triager note, and the stray clean-up (AD-12a S-3 condition; AD-12b "Unverified until the first live run" and "Operational consequence"; AD-12a "Lookup bound" assumption (i)).** Directly after (c)'s paragraph, one subsection with three parts, in this order. This is ADR-bound runbook content. The runbook is manifest file 11, so the 14-file count is unchanged.

1. **The label rule (bolded):** **do not hand-remove the `dependency-audit` label from the scheduled report's tracking issue.** The label is what authenticates it (AD-12a). Removing it makes the next run treat the issue as non-existent and create a fresh one, leaving the old one for a human to close.
2. **The triager note (AD-12a, S-3 binding condition):** the `dependency-audit` label is applied **only by the scheduled workflow** (`dependency_audit_report.py`'s create path). It is **never applied by hand when triaging**, and never by an issue template or issue-form `labels:` key, or by a labelling workflow or bot. A triager who sees an issue that looks like it belongs under this label must **not** apply it: an outside author can open a decoy whose first line is the marker, and a good-faith label turns it into a match, so every weekly run goes red on ambiguity (or the decoy is adopted). The single exception is clean-up step 3 below (ADR AD-12b): an operator recovery action, restricted to a provenance-verified, workflow-created issue, and never a triage action. *(Revised 2026-10-14, architect C5(b)/(c).)*
3. **Recovery when label-on-create fails (AD-12b, four steps verbatim in substance).** State the symptom first. The run goes red with a message naming the missing label, and the issue it created is unlabelled. The failure is **loud and recurring, not one-off**: each later run (weekly, and every `workflow_dispatch`) reads "none exists", may create **another** unlabelled issue, and goes red again until an operator fixes the cause. **A second first-run symptom leads to the same step 1** *(added 2026-10-14, ADR AD-12a "Lookup bound", unverified assumption (i))*: if a run, typically the first, fails with `list_issues: no usable response for page 1`, the label-filtered lookup may have been refused because the `dependency-audit` label does not exist yet. That run made **zero writes and created no issue**, so there are no strays. Do step 1 (create the label), skip steps 2 and 3, and do step 4. If the label already exists, this is an ordinary API failure, not this case. Then the procedure:
   1. Fix the cause: create the `dependency-audit` label in the repo if it is missing, or correct the token's permission.
   2. Clean up the strays: list issues whose first line is the marker `<!-- hos-dependency-audit -->` and that lack the label, and **close all of them except at most one**.
   3. ~~Adopt (optional): label the one survivor `dependency-audit`, after checking that its first line is the marker, so the next run adopts it. Otherwise close it too, and the next run creates a fresh, verified issue. **Never label more than one**, or AD-12a's ambiguity rule turns the next run red.~~ *(Superseded 2026-10-14, architect C5(a)/(c): a first-line check authenticates nothing, because the marker is a public constant, so step 3 as written let an operator adopt an outside author's decoy.)* Adopt (optional): label `dependency-audit` on **at most one** survivor, and **only if its provenance is shown**. (i) **Primary check:** its issue number is named in a failed run's `GitHubError` message (the run log). (ii) **Supporting check:** its author is the identity the workflow created it under (`github-actions[bot]` for the scheduled workflow). The author check is corroboration only, never sufficient alone, because a non-dry-run local invocation creates under its own token. The first-line marker is **necessary but not sufficient**, because it is a public constant. If provenance cannot be shown, close it too, and the next run creates a fresh, verified issue. **Never label more than one**, or AD-12a's ambiguity rule turns the next run red. This is an operator recovery action, **the only sanctioned manual application of the label**, and it is never a triage action.
   4. Re-run with `workflow_dispatch` and confirm it is green.

No code change is needed for any of this.

### 11.3 `docs/CI-EXECUTION-INVENTORY.md` — replace one row with two (AC-30)

> *(AD-23 split.)* **Part 2** replaces the row with two rows, as below, but writes the `dependency_audit.sh` row as: Status `Local-only (by design)`; Workflow `— (not oversight-gates.yml)`; Reason: the first two sentences of the row below, then *"A scheduled run that pauses and alerts is #1605 Part 3 and is not yet on main."* **Part 3** rewrites that one row to the text below, and appends: *"A new uncovered advisory, or a run that could not complete, holds new build work and alerts a human (D-5, ADR-1605 AD-15..AD-21)."* AC-30 is satisfied by Part 2.

Delete the existing `| security_scan.sh | CI-portable, deferred | — | Its pip-audit sub-check … |` row entirely — the rationale is retired, not amended — and insert, keeping the table's existing ordering (after `template_refs_check.sh`, before `django_check.sh`):

| Gate | Status | Workflow | Reason |
|---|---|---|---|
| `security_scan.sh` | Wired, advisory | `oversight-gates.yml` (job: `oversight-gate-security-scan`) | Deterministic, file-scoped, no network — bandit `-lll` only; the pip-audit half moved to `dependency_audit.sh` (#1605), which is what had kept this gate out of CI. Zero debt: 0 HIGH findings over 219 tracked `.py` files, measured 2026-09-22 through bandit's `-o` file channel, not stdout (which carries a progress bar past ~1s of scan time and silently fail-opened the old gate — see DECISIONS.md #1605). Not promoted: #1605 wires; promotion is its own decision (F-1). |
| `dependency_audit.sh` | Local-only (by design), plus a scheduled report | `dependency-audit.yml` (jobs: `dependency-audit-scan`, `dependency-audit-report`) — **not** `oversight-gates.yml` | Repo-scoped and network-dependent: it audits the installed dependency set against a live advisory database, which is not a property of a PR's diff. Deliberately absent from `oversight-gates.yml` (deterministic, offline-only). Runs weekly instead and reconciles a single label-authenticated tracking issue (`dependency-audit` label + first-line marker, AD-12a); it can never fail a PR check. The vulnerabilities themselves are #1504. |

### 11.4 `DECISIONS.md` — one appended, dated entry (AC-31)

> *(D-5/AD-23.)* The entry ships in **Part 2**, dated on the day it is written. The D-5 scope refinement that AC-31 now also requires is the 2026-10-20 DECISIONS.md entry added by the ADR amendment on this design branch (commit `bef59f92d`). Part 2 is cut on main after this design PR merges, so that entry is on main by then. *(Corrected 2026-10-20: it is not on main today.)* So this entry cross-references it and must not restate it. Item 6 is reworded to main's lane semantics (§15.1): execution failure gives `NOT CHECKED` named in the `GATE PASS` line, and an unparseable completed scan or an undecidable roster gives `GATE FAIL`. It no longer says `GATE NOT RUN`. Item 8 (AD-12a/AD-12b) is recorded **prospectively**: the human approved the label on 2026-10-20 (Q3), and the code that applies it ships in Part 3. This is what removes `DECISIONS.md` from Part 3's file list (§15.11).

Appended at the bottom, `## 2026-09-22 — <title> (#1605)`, following the existing entry shape (bold lead-ins, a closing **Scope.** paragraph). It must record, at minimum:

1. **The split** — two gates, not a flag, and why (auto-discovery is file-based, so a flag leaves one code path where the halves stay fused).
2. **The fail-open defect and its trigger** — the old gate parsed **stdout**, which bandit decorates with a progress bar once a scan exceeds ~1s. The trigger is **duration, not file count** (V-2), so the same PR could pass on a fast runner and fail open on a slow or loaded one — and a shared CI runner is the slow, loaded case. The fix is `-o`; scrubbing stdout is forbidden because it would make correctness depend on an undocumented, TTY/width/locale-sensitive rendering.
3. **AV-5's second silent negative** — a file bandit could not parse was counted as scanned-and-clean. Now: changeset filtered to Python first, then non-empty `errors` ⇒ `GATE FAIL`, and the green line names the count of files bandit actually scanned.
4. **The V-6 baseline with its measurement channel** — 0 HIGH over 219 tracked `.py` files, 2026-09-22, measured through `-o`, not stdout. Stating the channel is load-bearing: a bare "zero debt" would be indistinguishable from a fail-open reading.
5. **S-3's deferral** — wired, not promoted; promotion is a control change deserving its own visible human decision (F-1).
6. **AD-6's ratchet reasoning** — the dependency gate stays blocking on findings locally; suspension is the only sanctioned loosening path. Execution failure is non-blocking but now says `GATE NOT RUN`, not `GATE PASS`.
7. **TD-1 as reversed by AD-2a.** ~~`--empty-changeset` is not honoured; the #1759 `STATUS=empty` skip is superseded, with the consequence and its remedy named.~~ The entry must record the reversal explicitly (ADR §2a "Downstream record-keeping"). AD-2 first ruled the gate unconditional. The pinned invariant TC-A2 (#1759) required the opposite. The invariant was upheld, not narrowed: the gate now honours only the literal `--empty-changeset` token (`NOT CHECKED`, exit 0, no network call) and still ignores every path argument. The near-miss is the instructive part. The as-built DECISIONS entry at `a979a4605` carries this.
8. **AD-12a/AD-12b** — the tracking issue is authenticated by the `dependency-audit` label plus the first-line marker (the marker alone is a public constant and forgeable); creation verifies the label stuck and fails red otherwise; one new repo label and the "do not hand-remove it" rule; registry row deferred to #1812 item 12, author pinning to #1812 item 5.
9. **Scope.** — the 14 files, the protected/security surfaces touched, and the explicit non-changes (`run_gates.sh`, `setup_branch_protection.sh`, `static_analysis.py`, `AUTO_CHECKABLE_GATES`, `docs/LABELS.md` / `KNOWN_LABELS` — #1812 item 12).

### 11.5 `SCRIPTS-INDEX.md`

Regenerate only: `bash scripts/framework/gen_scripts_index.sh`. Never hand-edit. Expected delta: one new line for `scripts/oversight/gates/dependency_audit.sh` (sorting **before** `django_check.sh` under `LC_ALL=C`), one new line for `scripts/automation/dependency_audit_report.py`, and a changed description for `scripts/oversight/gates/security_scan.sh`. Pinned by `tests/framework/test_scripts_index.py::test_index_matches_generator_output`, so this is **not** sheddable despite S-6 listing it first — the worker's constraint B governs.

*(AD-23 split.)* In Part 2 the delta is the two gate lines only. In Part 3 it is `scripts/automation/dependency_audit_report.py` plus `scripts/automation/dependency_pause.py`. `gen_scripts_index.sh` indexes `scripts/**`, so both parts must regenerate. This is why AD-23's Part 3 shed step 1 ("SCRIPTS-INDEX becomes a follow-up") cannot be applied (§15.13 G-1).

---

## 12. Commit decomposition (planned 9 of 10; as built 10, plus one security-amendment commit = 11, which needs a human-authorized one-commit S-6 waiver)

> **SUPERSEDED by AD-22 and §15.11 (2026-10-20).** Part 2 is re-cut on current main, so the ten commits through `b9c342559` are not preserved. The "do not squash or rewrite" rule below existed to protect re-confirmations pinned to `b9c342559`. AD-22 orphans those re-confirmations anyway (ADR §5 D-5). The security amendments now land **inside** the re-cut commits rather than as an 11th commit: SEC-M2 and SEC-S1 in Part 2; SEC-M1, SEC-S4, SEC-S5 and the lookup bound in Part 3. If the re-cut Part 2 is at or under 10 commits, the S-6 waiver goes unused, and it does not transfer to Part 3 (AD-23 corollary). The text below is history.

| # | Message | Files | ACs |
|---|---|---|---|
| 1 | `fix(#1605): bandit's verdict comes from the file it wrote, never the stream it decorated` | `gates/security_scan.sh` (bandit lane, kind filter, seam — pip-audit lane untouched), `tests/oversight/test_scan_gates_empty_args.py` (TC-S1…S10, S12…S14 + docstring), `tests/oversight/test_gate_arg_grammar.py` (`KIND_FILTER_GATES` row + docstring) | AC-2, AC-3, AC-4, AC-5, AC-6, AC-7 |
| 2 | `refactor(#1605): extract pip-audit into a repo-scoped dependency_audit gate` | `gates/dependency_audit.sh` (new), `gates/security_scan.sh` (pip-audit lane removed, header), `tests/oversight/test_scan_gates_empty_args.py` (TC-S11, TC-D1…D8), `tests/oversight/test_gate_arg_grammar.py` (TC-G9, TC-G10) | AC-1, AC-8, AC-9, AC-10 |
| 3 | `ci(#1605): wire oversight-gate-security-scan with its measured debt baseline` | `.github/workflows/oversight-gates.yml` | AC-11, AC-12, AC-13, AC-14, AC-15, AC-16 |
| 4 | `feat(#1605): narrow issue list/create/update helpers in github.py` | `scripts/automation/lib/github.py` | AC-27 (partly), AC-28 (enabling) |
| 5 | `feat(#1605): dependency_audit_report — marker-identified, zero-write-on-unchanged` (historical title; identity is label + marker per AD-12a, landed in a later commit — ADR §3) | `scripts/automation/dependency_audit_report.py`, `tests/automation/test_dependency_audit_report.py` | AC-20…AC-24, AC-26, AC-27, AC-28 |
| 6 | `ci(#1605): weekly scheduled dependency audit, split audit/report jobs` | `.github/workflows/dependency-audit.yml` | AC-17, AC-18, AC-19, AC-25 |
| 7 | `docs(#1605): gate→key registries and the retired CI-portability rationale` | `docs/specs/SPEC-375-…`, `docs/OVERSIGHT-RUNBOOK.md`, `docs/CI-EXECUTION-INVENTORY.md` | AC-29, AC-30 |
| 8 | `chore(#1605): regenerate SCRIPTS-INDEX` | `SCRIPTS-INDEX.md` | AC-29 |
| 9 | `docs(#1605): DECISIONS entry` | `DECISIONS.md` | AC-31 |

Commit 1 lands the fix **in place, before the split**, so the reviewer diffs it against the code that had the defect rather than against a new file with no history (AD's ordering, preserved). Commits 1–3 are a coherent shippable unit. One commit of headroom was left for review fixups. It has since been used (see below).

**Pre-PR mechanical checks** (not commits): `git diff --stat origin/main...HEAD` must show `scripts/oversight/run_gates.sh` and `scripts/framework/setup_branch_protection.sh` with **zero** changed lines (AC-8, AC-15); `grep -c dependency_audit .github/workflows/oversight-gates.yml` must be 1 (the header sentence) with no job or invocation (AC-11); `grep -n 'echo "0"' scripts/oversight/gates/security_scan.sh scripts/oversight/gates/dependency_audit.sh` must return nothing (AD-3/S-2).

**As built, the commit count is already 10 of 10.** The local implementation branch `worker-1605-gate-split-impl-260922213001-2366083` has **10 commits** over `origin/main` (`6810c2a5c..b9c342559`). Seven commits carry planned commits 1–9, because planned 7, 8 and 9 (docs, SCRIPTS-INDEX, DECISIONS) landed together as `4f5258c72`. Three more are beyond the plan: `a979a4605` (AD-2a), `e2017fa3e` (mutation hardening) and `b9c342559` (seven re-review fixes). The headroom commit above was used up before the security review. ~~(§12 now has 10 of 10)~~ was false when written.

**Security-review amendments (2026-10-14) in the Part 2 implementation PR: exactly ONE commit, the 11th.** The implementation was built before these amendments, so they land on that PR as **exactly one** additional commit: `fix(#1605): security design review — isolated artifact, bandit --, NUL listing, scanner presence, normalize allowlist`. ~~More than one is also fine.~~ *(Withdrawn, architect C1, 2026-10-14T08:35:54Z.)* The commit budget for this PR is therefore **11**. That exceeds REQUIREMENTS S-6's limit of 10. It is valid **only** under an explicit **human** authorization of a one-commit waiver. pm-agent declined to grant the waiver itself, because `docs/PR-SIZE-POLICY.md` reserves going past 10 commits for a human. It escalated the request with a recommendation to authorize (REQUIREMENTS-1605 §1, "Commit-budget waiver request, 2026-10-14"). The authorization terms are: exactly one extra commit containing only the security design amendments and their tests; file count ≤15; the PR body discloses the 11-commit count and links the authorization. **Until a human authorizes it, the amendment commit must not be made.** **Sequencing (architect C6(b), 2026-10-14):** the authorization must be obtained and recorded **before** the amendment commit is made, either on the `needs-human` issue that `docs/PR-SIZE-POLICY.md` prescribes for going past 10 commits, or in the **design PR's** thread, where the PR body surfaces the waiver request as an explicit human decision item. It must **not** be deferred to the AD-12a/AD-12b clearance in the Part 2 implementation PR's thread: that clearance happens after the PR is opened, and the commit it would authorize must already exist by then, so waiting for it is a sequencing deadlock. The worker escalates instead of improvising, for example by squashing or by splitting the amendments out. **Do not squash, reorder or rewrite the ten existing commits to make room.** Pending code-reviewer and security-reviewer re-confirmations are pinned to `b9c342559` (ADR §5), and rewriting history would orphan them. The 11th commit sits on top of `b9c342559`, so a `b9c342559..HEAD`-scoped re-review covers it exactly. If review of the amendment commit needs fixups, they are folded into that one commit before the PR is opened, never added as a 12th, ~~unless pm-agent grants a further waiver~~ unless a human authorizes a further waiver *(architect C6(a), 2026-10-14: going past 10 commits is human-gated, so pm-agent cannot grant it)*.

Files touched by the amendment commit: `gates/security_scan.sh` (§3.6 `--`), `.github/workflows/oversight-gates.yml` (§10.1), `.github/workflows/dependency-audit.yml` (§10.2), `scripts/automation/dependency_audit_report.py` (§9.2/§9.3/§9.5/§9.7, including the `OversizedAuditJSON` stderr wording), `tests/oversight/test_scan_gates_empty_args.py` (SB-9, TC-S15…TC-S18), `tests/automation/test_dependency_audit_report.py` (allowlist, bounds incl. the `oversized` wording, and workflow-static groups), and `docs/OVERSIGHT-RUNBOOK.md` (§11.2(d) parts 2 and 3: the triager note and the four-step clean-up; part 1, the label rule, is already on the branch). All seven are already in the §2 manifest, so **the budget stays at 14 files**. *(Added 2026-10-14, ADR AD-12a "Lookup bound" and ADR §5 "Where the fix lands".)* The same single commit also carries the lookup-bound fix. That adds `scripts/automation/lib/github.py` (manifest file 6: §8's `label` keyword, validation, encoding and the two imports) to the list. It also extends `scripts/automation/dependency_audit_report.py` (§9.6 call) and `tests/automation/test_dependency_audit_report.py` (§7.3 Lookup-bound rows (a)–(e) and the helper label cases (f)), both already on the list. That makes eight files, all in the manifest, so the file and commit counts are unchanged. The amendment is no longer *only* the security design amendments, so the waiver terms quoted above need the same scope note (see Human Review item 9). Added pre-PR greps: `grep -c -- '-o "$BANDIT_JSON" -- "${FILES\[@\]}"' scripts/oversight/gates/security_scan.sh` = 1; `grep -c 'persist-credentials: false' .github/workflows/dependency-audit.yml` = 2; `grep -n 'python3 -I' .github/workflows/dependency-audit.yml` returns nothing.

---

## 13. Traceability — every AC to a design element (constraint E)

| AC | Where satisfied | Test |
|---|---|---|
| AC-1 standalone, no network, no pip-audit | §3 (pip-audit lane deleted from `security_scan.sh`) | TC-S11 |
| AC-2 file-list argv grammar preserved | §3.2 (preamble unchanged; still in `FILE_LIST_GATES`) | existing TC-G1…G8 |
| AC-3 #976 contract survives | §3.3 (`unscoped` string unchanged), §7.1 | existing #976 cases + TC-G4 |
| AC-4 unparseable ⇒ fail closed | §3.6 rc-65 branch + inline `exit 1` | TC-S3, TC-S6 |
| AC-5 contaminated output parsed correctly | §3.6 `-o` acquisition, stdout to `/dev/null`; §6.1 SB-1/SB-2 | TC-S1, TC-S2 |
| AC-6 e2e positive control | §7.1 TC-S12 (real bandit, ~200 files, variable-command B602 per AV-6) | TC-S12 (`slow`) |
| AC-7 suspension scoped; not auto-checkable | §3.2 (`security` key unchanged); §4.2 (`dependencies`); no `AUTO_CHECKABLE_GATES` edit | TC-D6, TC-D7, TC-D8 |
| AC-8 both halves locally, `run_gates.sh` unmodified | §2 (no-touch list), auto-discovery is file-based (AV-8) | TC-G10 + the §12 diff check |
| AC-9 two keys, independently effective | §3.2 / §4.2 | TC-D6, TC-D7 |
| AC-10 dependency half repo-scoped | §4.2/§4.3, TD-1 | TC-G9 |
| AC-11 dependency half absent from `oversight-gates.yml` | §10.1 (no job; one header mention) | §12 grep check |
| AC-12 own job, #1571 step shape | §10.1 Edit 4 (plus the SEC-S1 presence step and the SEC-M2 `-z` listing — deliberate, documented divergences) | CI run + inspection + TC-S18 |
| AC-13 file-scoped, not `--all` | §10.1 Edit 4 (`git diff -z --name-only` list, SEC-M2) | inspection + TC-S18 |
| AC-14 debt baseline with method | §10.1 Edit 1 | inspection |
| AC-15 not promoted | §2 no-touch list | §12 diff check |
| AC-16 HIGH in changed files fails the check | §3.6 branch 1; the job command shape is the gate's own; §10.1 SEC-S1/SEC-M2 (no green-on-missing-scanner, no silently skipped non-ASCII `.py`) | TC-S1 (gate-level), TC-S12 (real-tool), TC-S17, TC-S18 |
| AC-17 own workflow, schedule + dispatch | §10.2 | inspection |
| AC-18 CI-native auth, no App token, cannot fail a PR | §10.2 (`github.token`, no PR trigger) | inspection |
| AC-19 concurrency group | §10.2 (`cancel-in-progress: false`) | inspection |
| AC-20 exactly one issue, `state=all` (identity = `dependency-audit` label **AND** first-line marker per AD-12a, superseding marker-only) | §8 (`list_issues` single-name `label` keyword, validated and encoded), §9.2, §9.3, §9.4 (create applies and verifies the label), §9.6 (`state=all` lookup, label-filtered server-side per ADR AD-12a "Lookup bound", with the label and marker re-checked in the predicate; `find_tracking_issue` never matches title) | identity + ambiguity cases, Lookup-bound (a)–(e), helper label cases (f), create round trip, `GitHubWriter` label verification |
| AC-20a create applies the label and fails closed if it did not stick (proposed, pending human clearance) | §9.4 (GitHubWriter create-response check), §9.5 create row, §9.7 exit 1 | GitHubWriter label verification; create row asserts labels == [LABEL] |
| AC-21 unchanged ⇒ zero writes | §9.5 row 2 | recording-writer: `writer.calls == []` |
| AC-22 changed ⇒ one body update + exactly one comment | §9.5 rows 3/4 + `render_delta_comment` | reconcile cases |
| AC-23 zero findings ⇒ close only if open; never create | §9.5 rows 6/7/8 | reconcile cases |
| AC-24 findings return ⇒ reopen the same issue | §9.5 row 5 | reconcile case |
| AC-25 execution failure ≠ zero findings | §10.2 (`needs: audit`, no `if: always()`); §9.3 `MalformedAuditJSON` in depth (now including SEC-S4's allowlist/bounds). Holds against an *honest* `audit` failure only — a compromised `audit` is residual R-4 | CLI exit-2 case + workflow-static group + inspection |
| AC-26 cross-references #1504; no pending-actor label. **"No new label" SUPERSEDED by AD-12a/AD-12b** — exactly one label, `dependency-audit`; pm-agent amendment proposed 2026-10-14 (REQUIREMENTS AC-26), pending human clearance (ADR §6 item 3) | §9.2/§9.3 (`render_body`), §9.5 create row (`labels=[LABEL]`), §10.2 (no workflow label step) | `render_body` cases (#1504; no `needs-ai`/`/label` in body text); create applies the label |
| AC-27 no `@path` expansion | §8 (all bodies via `_run_gh(stdin_json=…)`) | helper tests assert argv carries no `--field`/`-f` |
| AC-28 idempotency logic unit-testable offline | §9.3/§9.4 (pure functions + injected writer) | the whole of §7.3 |
| AC-29 every gate→key table updated | §11.1, §11.2, §11.3, §11.5 | `test_scripts_index.py` + review |
| AC-30 retired rationale explicitly retired | §11.3 (row **replaced**, not amended) | review |
| AC-31 DECISIONS entry | §11.4 | review |
| AC-25 *(amended D-5)* execution failure = `NOT_RUN`, plus hold and alert | §15.2 (`measure` exits 1 on every cause), §15.3 (`report` is skipped when `audit` fails; `outcome` maps the result to `not_run`), §15.6 | TC-P1…TC-P9, TC-O* |
| AC-32 same roster and partition, not a copy | §15.2 steps 6–8 (`filter` subprocess rc is the verdict; the projection imports `security_scan_logic`) | TC-P10, TC-P11, TC-P12 |
| AC-33 cannot run = `NOT_RUN` + hold + alert; no skip path | §15.2 (cause table), §15.3, §15.6, §15.7 | **TC-H1 (mandatory human item)**, TC-P1…TC-P9 |
| AC-34 finding = issue + hold + `dependency-advisory` alert | §15.3 (`report` runs on verdict 1), §15.6 | TC-H2 |
| AC-35 the hold is host state, read every cycle | §15.6 (state file), §15.8 (hos-cron call site) | TC-C*, TC-K1…TC-K6 |
| AC-36 build work only | §15.8 directive `NEW WORK: DOCS/DESIGN ONLY` + the prompt bullet | TC-K2 (directive-level only; AD-19 residual) |
| AC-37 clears only on a clean run; `dependency-pause-cleared` with duration | §15.6 decide/apply | TC-C5 |
| AC-38 stale = `NOT_RUN`; grace stated (216 h, configurable in [168, 336]) | §15.5 rule 2 (staleness) | TC-C7…TC-C9 |
| AC-39 never silent; the alert never gates the hold | §15.7 ordering and undelivered; §15.8 log line | TC-A1…TC-A5, TC-K3 |
| AC-40 one `notify_human.sh` call, #2125's interface | §15.7 argv | TC-A1 |
| AC-41 fingerprint `dependency-audit:<cause>:<id\|sub>` | §15.6 schema | TC-C2, TC-C3 |
| AC-42 day-one run disclosed | §15.10 procedure + PR body | PR-body review |
| AC-43 tests without network | §15.9 | all of §15.9 |

**Security design review amendments (2026-10-14) — not ACs, binding on the Part 2 implementation:**

| ID | Finding | Where satisfied | Test |
|---|---|---|---|
| SEC-M1 (MUST_FIX, CWE-829/94) | artifact extracted over the workspace, then `python3 -m` from it with `issues: write` | §10.2 YAML (`path: ${{ runner.temp }}/audit-in`, `AUDIT_JSON`, regular-file check) + binding properties (i)–(iii); no `-I` | §7.3 workflow-static group |
| SEC-M2 (MUST_FIX) | option-like filenames reach bandit argv; quoted non-ASCII names skipped as non-Python | §3.6 `--` (TV-10, TV-12); §10.1 `git diff -z` + `mapfile -d ''` (TV-11); stubs §6 (SB-9) | TC-S15, TC-S16, TC-S17, TC-S18 |
| SEC-S1 | missing bandit ⇒ `SKIP` exit 0 ⇒ green CI job | §10.1 `Assert the scanner is present` step; local `SKIP` unchanged | TC-S18 |
| SEC-S4 (minimum bar) | artifact-sourced strings rendered unescaped into issue body/comments | §9.2 patterns + bounds; §9.3 `normalize`; §9.5 render-before-write; §9.7 exit 2 | §7.3 `normalize` allowlist + bounds groups |
| SEC-S5 | persisted checkout credentials | §10.2 both checkouts `persist-credentials: false` | §7.3 workflow-static group + §12 grep |

**Deferred, with reason (none are ACs):** F-1 (promotion — S-3, deferred by pm-agent), F-2 (repo-wide fail-open sweep — filed by the worker regardless of budget, not done here), F-4 (retiring the tracking issue vs #1504 — lifecycle question for later). F-3 is **resolved**, narrowly, by §8.

---

## 14. Startup-gap analysis and affected sign-offs

*Should any of this have been settled in an initial technical design, before code was written against it?*

- **#1759 D4** explicitly deferred `HOS_BANDIT_BIN` and named it as the successor action. §3.5 executes that deferral: a closed gap, not an orphaned approval. **No re-review of #1759 required.**
- **#1759 row 7** specified the `BANDIT_LAST_RC == 2` message split and it never landed. §3.6 lands it. Its sign-off covered a design item, not shipped behaviour; nothing built against it needs revisiting.
- **#1759's `STATUS=empty` ⇒ skip-pip-audit ruling** is **superseded** by AD-2 / TD-1. The superseded scope is one comment and one branch inside a lane being relocated; the changeset grammar it belongs to is untouched, and no other #1759 decision depends on it. The rationale is carried into `dependency_audit.sh`'s header (§4.1) rather than dropped. **Amended by AD-2a:** the file-count basis stays superseded, but the observable behaviour is restored on a different basis (the runner's explicit `--empty-changeset` mode signal), and #1759's TC-A2 invariant is upheld, not narrowed. **All other #1759 sign-offs stand.**
- **AV-5** (an unparsed file reads as clean) is newly discovered, not previously decided — it strengthens F-2 rather than invalidating anything. The sweep should look for **both** shapes: default-on-parse-failure, *and* a verdict derived from a tool's summary rather than from what it demonstrably covered.
- **TV-3** (the `-m` invocation, D-1) is an error in a binding ADR string discovered before any code was written against it. Corrected here; the architect is notified. No sign-off is affected.
- **AD-12a/AD-12b realignment (2026-10-14).** *Should this have been settled in the initial TD?* **Yes — a `startup-artifact-gap`.** This TD specified a marker-only identity check for an `issues: write` token without asking who else can make an issue look like ours; the code adopted label authentication on 2026-09-22 but this document was not amended in that cycle. The ADR's §5 is the authoritative affected-sign-offs analysis and this realignment adopts it unchanged: code-reviewer and security-reviewer round 5 stand for `f5c1c227f` and must re-confirm at `b9c342559`; **reliability, unit-test and ops** sign-offs (2026-09-22) are orphaned until re-checked against AD-12a/b; REQUIREMENTS-1605's sign-off is orphaned for AC-20/AC-26 only. This TD's own approval was orphaned for §2, §7.3, §8, §9.1–§9.7, §10.2, §11.3, §11.4, §12 and §13 (AC-20/AC-26) and is restored only on architect re-review of this revision. Classification: **clarifying** for the code (the TD now describes what was built and reviewed; no new behaviour), **additive** for the §11.2(d) runbook rule and §11.4 item 8.

- **Security design review amendments (2026-10-14): SEC-M1, SEC-M2, SEC-S1, SEC-S4, SEC-S5.** Source: `security-reviewer`'s design review of the three #1605 documents at `6b30a1b5f`, verdict **CONDITIONAL** ("do not approve until MUST_FIX amended in design"). These are **design amendments that the Part 2 implementation PR must pick up** before it can merge. The amended sections are §0 (TV-10…TV-12), §3.6, §6 (stub argv shape, SB-9), §7.1 (TC-S15…TC-S18), §7.3 (three new groups), §9.2, §9.3, §9.5, §9.7, §10.1, §10.2, §12 and §13.
  - *Should this have been settled in the initial TD?* **Yes, for SEC-M1 and SEC-M2. Both are `startup-artifact-gap`s.** The TD drew the AD-10 trust boundary between jobs but did not follow the one channel that crosses it, the artifact, to where it lands. It also specified the bandit argv without asking what a filename can be. SEC-S1, SEC-S4 and SEC-S5 are hardening that the initial TD could reasonably have included but did not need for correctness of the stated ACs. **Classification: additive.** No interface between components changes, no file is added, and every amendment narrows what the code may do. Nothing is loosened.
  - **Affected sign-offs.** Code for all six touched files was built and reviewed against the *old* contract, so the approvals below are **orphaned until re-checked against this revision**. The re-check is confined to the amendment diff:
    - **security-reviewer.** Its design verdict is CONDITIONAL. It re-reviews this revision (design), then the Part 2 amendment commits (code).
    - **code-reviewer.** Re-reviews the amendment commits on `security_scan.sh`, both workflows, and `dependency_audit_report.py`.
    - **unit-test.** Re-signs: new SB-9 and TC-S15…TC-S18, plus the allowlist, bounds and workflow-static groups. Existing `normalize` fixtures using placeholder ids such as `GHSA-x` must be updated to valid ids (§7.3).
    - **reliability-reviewer.** Re-checks §9.5 render-before-write and the new exit-2 paths, and confirms the allowlist cannot reject a real advisory id format that pip-audit emits today. A false `MalformedAuditJSON` is a red weekly run, not a silent one.
    - **ops-reviewer.** Re-checks the new stderr lines (scanner-missing, artifact-missing) against `TELEMETRY-SPEC.md`.
    - **architect.** Re-reviews this TD revision. SEC-M1 refines AD-10's boundary and adds residual R-4, but changes no ADR ruling.
    - **pm-agent.** Notified. The §10.1 job now diverges from AC-12's "#1571 step shape" by one step (SEC-S1) and the `-z` listing. That is a tightening, but AC-12's wording may want a note.
    - **Sign-offs that stand:** REQUIREMENTS-1605 (no AC changes), the gate-arg grammar tests, and everything about AD-12a/AD-12b identity.

- **Architect conditions C1–C3 (register entry 2026-10-14T08:35:54Z), plus non-blocking item 2.**
  - **C1, the commit budget (§12).** "10 of 10" was false: the branch already had 10 commits. The amendment is exactly one 11th commit. The ten existing commits must not be squashed. *Startup gap?* No. This is bookkeeping drift between the plan and the branch, not a missing design decision. *Classification:* **clarifying.** *Sign-offs:* none change. The commit needs a one-commit S-6 waiver, which pm-agent escalated to a human under `docs/PR-SIZE-POLICY.md`, recommending authorization (REQUIREMENTS-1605 §1). Without that authorization the amendment commit is blocked.
  - **C2, AD-2a propagation (§1.1 heading and consequences, §4.1 items 1/2/4, §4.2, §4.3, §7.2 TC-G9, §11.2(c), §11.4 item 7, §14 #1759 bullet, Human Review preamble).** *Startup gap?* Yes, but already recorded: AD-2a is the ADR's own record of the gap (TC-A2 not checked at design time). This revision only finishes propagating it into the TD, where it should have landed in the 2026-09-22 cycle. *Classification:* **clarifying.** Code, tests, runbook and DECISIONS at `a979a4605` already implement AD-2a, and every C2 edit makes the TD describe what was built. That includes §4.3's fixed announcement sentence, which replaced `($# received)` so TC-G9's byte-identity holds. *Sign-offs:* the sign-offs given on `a979a4605` and later stand. No code needs re-review for C2 alone.
  - **C3, ADR S-2/S-3 carried in (§9.4, §9.6, §11.2(d), Human Review item 3).** *Startup gap?* Yes, already recorded in the ADR as the security design review's S-2/S-3. *Classification:* **additive.** It adds runbook text (§11.2(d) parts 2 and 3) that is **not** on the branch, so it lands in the single amendment commit (§12). It makes no change to code behaviour: the recurring red is what the code already does, and only the description was wrong. *Sign-offs:* ops-reviewer (runbook wording) and code-reviewer review the runbook hunk as part of the amendment-commit re-review already required above. No standing code sign-off is invalidated.
  - **Non-blocking item 2, `oversized` wording (§9.3, §9.5, §9.7, §7.3 bounds row).** *Startup gap?* No. It refines a SEC-S4 amendment that is not yet built. *Classification:* **additive.** It adds one exception subclass `OversizedAuditJSON(MalformedAuditJSON)` and one stderr branch. Exit code and zero-write behaviour are unchanged, and every existing `except MalformedAuditJSON` still catches it. *Sign-offs:* this rides in the same amendment commit as SEC-S4, which unit-test, reliability-reviewer and ops-reviewer already have to re-check (above). ops-reviewer should confirm the new stderr line against `TELEMETRY-SPEC.md`.

- **Architect conditions C5(c) and C6 (register entry 2026-10-14T08:42:28Z).**
  - **C5(c), provenance check in clean-up step 3 (§11.2(d) parts 2 and 3).** Step 3's only check was "its first line is the marker", which is a public constant, so it authenticated nothing. An operator following it could adopt an outside author's decoy, which moved the S-3 confused-deputy residual from the triager to the operator. Step 3 now mirrors ADR AD-12b step 3 as revised by C5(a): at most one survivor, labelled only if a failed run's `GitHubError` names its number (primary check), with author `github-actions[bot]` as corroboration only. If provenance cannot be shown, the survivor is closed. Part 2 now says "never by hand when triaging" and names that single exception, matching C5(b). *Startup gap?* Yes. The provenance requirement belonged in the original §11.2(d) text, which was added in this design cycle and has not been built yet. *Classification:* **clarifying** (it tightens unbuilt runbook text). *Sign-offs:* no built code changes. The runbook hunk is not yet on the branch and lands in the single amendment commit (§12), which ops-reviewer and code-reviewer already re-review. No standing sign-off is invalidated.
  - **C6(a), §12 further-waiver clause.** "unless pm-agent grants a further waiver" contradicted the human gate the same paragraph set. It now reads "unless a human authorizes a further waiver". *Startup gap?* No, this was drafting drift in this cycle. *Classification:* **clarifying.** *Sign-offs:* none change.
  - **C6(b), waiver sequencing (§12, Human Review item 7).** The TD now says the S-6 waiver must be authorized **before** the amendment commit is made, on the PR-SIZE-POLICY `needs-human` issue or in the design PR's thread, and never deferred to the Part 2 PR's AD-12a/AD-12b clearance. *Startup gap?* No. *Classification:* **clarifying.** *Sign-offs:* none change. REQUIREMENTS:60 carries the matching wording, which belongs to pm-agent.

- **ADR AD-12a "Lookup bound" (architect register entry 2026-10-14T08:49:46Z, conditions T1–T12; cross-vendor second review, codex, CWE-400 MEDIUM).** The tracking-issue lookup is now label-filtered server-side (`?state=all&labels=dependency-audit&per_page=100`), and the label-and-marker predicate stays the authenticator. Mirrored into §7.3 (identity/ambiguity row; new Lookup-bound rows (a)–(e) and the discriminating fake GitHub; helper row (f)), §8 (signature, docstring, validation and encoding bullets, PR-exclusion clarification, Boundaries, the two imports), §9.4 (`find_tracking_issue` docstring), §9.6 (call, the label-filtered ruling and its two live-run assumptions, cap scope), §11.2(d) (the `list_issues: no usable response for page 1` symptom leads to clean-up step 1), §12 (amendment-commit file list), §13 (AC-20 row) and Human Review item 9.
  - *Should this have been settled in the initial TD?* **Yes. This is a `startup-artifact-gap`, the second on this lookup** (ADR §5). The TD carried a fixed 5,000-entry fail-closed cap over a collection that outsiders and organic growth can fill (about 2,100 entries today). In the AD-12a realignment it then repeated the ADR's ruling against a server-side label filter without asking about availability. Per the architect's register entry, the worker opens or annotates the `startup-artifact-gap` issue. I file nothing.
  - *Classification:* **additive** for the interface: `list_issues` gains one keyword, and the default `None` preserves every existing call. **Clarifying** for behaviour: no new user-visible behaviour, cost or operator obligation, and the change restores the intended weekly report. **Not structural:** no component boundary moves and no file is added. The ADR ruling already made that call, and this TD only mirrors it.
  - **Affected sign-offs (adopting ADR §5 unchanged):**
    - **Code at `b9c342559` is orphaned for the lookup surface.** `list_issues` there has no `label`, and the consumer call passes no label.
    - **code-reviewer and security-reviewer** (`f5c1c227f` entries) stand for the predicate and the create-verification path only. Their re-reviews of the single amendment commit must cover `list_issues` and the §9.6 call explicitly.
    - **unit-test** (already orphaned) re-signs, now including Lookup-bound (a)–(f).
    - **reliability-reviewer** (already orphaned) must also cover assumption (i), a new external-dependency semantic: a filter on a not-yet-existing label is assumed to return 200 `[]`, not 404/422.
    - **ops-reviewer** (already orphaned) re-checks the §11.2(d) symptom text.
    - **architect.** The 08:21:19Z endorsement of the label-less listing is withdrawn by the architect. The 08:44:44Z approval of this TD is orphaned for the sections listed above until the architect re-reviews this revision.
    - **security-reviewer design re-review** must cover the mirrored text.
    - **REQUIREMENTS-1605 is unaffected:** AC-20's `state=all` scope and no-title-matching rule are kept.
  - **404→raise is preserved.** §8's `[]`-vs-raise contract is untouched. Only a genuine HTTP 200 `[]` is empty.
  - **Not restored or replaced by this revision.** It does not restore the orphaned reliability, unit-test or ops sign-offs. It does not replace the security-reviewer design re-review or the code re-reviews of the amendment commit. It does not clear the AD-12a/AD-12b human merge gate or the S-6 waiver. The cross-vendor second review must be re-run on this delta for a recorded disposition. The agy lane's `prompt_too_large` failure (#1718) is a human restructuring decision and is not resolved here.

- **D-5 and AD-22 amendment (2026-10-20), §15.**
  - *Should this have been settled in the initial TD?* **No for D-5.** It is a new human scope ruling. **No for AD-22** either. It is a sequencing gap: #1776 merged after this TD was approved. **Partly yes for three implementation facts this revision corrects in the ADR** (§15.13 G-1, G-2, G-3). The ADR's Part 3 list is missing the worker prompt, which actually reads the directive, and `AGENT-IDENTITY.md` §9. Its shed step 1 also cannot run, because SCRIPTS-INDEX is test-pinned. Those are planning omissions of the D-5 ADR revision, found in this cycle before any code was written. No `startup-artifact-gap` is opened for them: nothing was built against them. The worker decides whether to annotate one.
  - *Classification:* **structural** for D-5 (a new pipeline state, a host read path, a cycle-start step in `bin/hos-cron`). The human issued D-5 and pm-agent and architect have already escalated it (REQUIREMENTS §5; ADR Human Review). This TD **adds no structural change of its own** beyond that ruling. The departures in §15.12 are clarifying or additive. AD-22 is **clarifying** for the code: it restores main's behaviour.
  - **Affected sign-offs (adopting ADR §5 "D-5", plus these):**
    - **Orphaned (code).** Every code sign-off on `security_scan.sh`, `dependency_audit.sh`, `test_scan_gates_empty_args.py` and `test_gate_arg_grammar.py` at `b9c342559` is orphaned and re-reviewed against the re-cut branch. code-reviewer must also confirm §3's rebase item 4: the `g6` rewrite, where bandit absent prints no pass line.
    - **Orphaned (design), this TD.** The architect's approval is orphaned for §2, §3, §4, §6.2, §7.1, §7.2, §10.1 Edit 3, §10.2, §11, §12 and §13 until it re-reviews §15.
    - **New reviews.** security-reviewer: §15.3 `outcome` job, §15.4 record grammar and §15.5 read path. reliability-reviewer: §15.5 staleness and cache, §15.6 state, and §15.7 alert. ops-reviewer: §15.8 log lines and the events in §15.6/§15.7. There is no `TELEMETRY-SPEC.md` in this repo; the runbook (§15.10) is the operator record.
    - **Moved to Part 3 (AD-23).** The pending re-confirmations on `dependency_audit_report.py`, `github.py` and the two workflows.
    - **Stand.** #1776's sign-offs: AD-22 relocates its lane verbatim, and its roster and module are untouched. The bandit-half design: §3 content, apart from the rebase. REQUIREMENTS-1605 as amended.

No approved design or code elsewhere in the repo was built against a decision this document revises.

**Residual risks carried, not fixed:**
- **R-1** — a deletions-only PR makes every file-scoped CI job exit 3 (#1759 RISK-1 / D5). The new job inherits it. Out of scope.
- **R-2** — the new tracking issue permanently overlaps #1504 (I-4, resolved later by F-4).
- **R-3** — `run_gates.sh` derives the suspension key it records in `gate-results.json` from the script's basename (TV-5), so that artifact's `suspended` field will read `dependency_audit`/`security_scan` while the gates themselves check `dependencies`/`security`. Pre-existing for `security_scan`; the new gate inherits it. Fixing it means editing `run_gates.sh`, which S-4 forbids. **Worth a follow-up issue**, filed by the worker alongside F-2.
- **R-4 (SEC-M1, accepted).** A *compromised* `audit` job can upload a valid report: an empty one that closes the tracking issue, or a fabricated finding set. `needs: audit` fails closed only against an honest `audit` failure. SEC-S4 bounds what such a report can write (no mentions, no markup, no forged state block, bounded size), but it cannot detect the forgery. The out-of-band check is that #1504 tracks the same vulnerabilities independently, so a false all-clear contradicts it visibly. This is accepted as residual: no in-workflow design can authenticate a report against the job that produced it.
- **R-5 (SEC-M2 follow-up, #1812).** The other six file-scoped jobs in `oversight-gates.yml` still list changed files with quotepath-quoted `git diff --name-only`, so their gates skip a non-ASCII filename as the wrong kind. The fix is repo-wide and out of this PR. The worker appends it to #1812.
- **R-6 (SEC-M2 follow-up, no-touch file).** `scripts/oversight/lib/changeset.sh`'s git-sourced selectors (`--diff`/`--step`/`--staged`) read `git diff --name-only` with the default quotepath. A non-ASCII path then fails `_hcs_apply_rex`'s `-e` existence test and is misclassified as missing. These selectors also never check git-sourced names for a leading `-` (TV-12). §3.6's `--` neutralises the `-` half for `security_scan.sh`, and every other `FILE_LIST_GATES` tool invocation has the same question to answer. `changeset.sh` is on this PR's no-touch list, so this is a follow-up for the worker to file or append to #1812 (or to #1759's successor), not a change here.
- **R-7 (AD-19, accepted).** The hold is enforced by a directive that the worker agent obeys. Nothing mechanically stops a non-docs PR while held. The backstop belongs with #2123.
- **R-8 (AD-15 / M-1, accepted).** A compromised `audit` job can emit a forged `MEASURE … verdict=0` and so a forged `clean`. This is AD-10's M-1 residual extended to the verdict. The compromised job can already forge the pip-audit JSON.
- **R-9 (D-2 pin).** The record's `sha=` is `github.sha`, but `audit` checks out the default branch when the job starts. If main moves in between, the measured tree is newer than `sha`. The consumer checks only `sha == head_sha`, which still holds. The next run corrects any difference. Accepted.
- **R-11 (G-4 overflow, accepted).** With more than 100 distinct kept advisories, the record carries only the first 100 sorted ids, so a swap wholly beyond them does not re-alert (§15.6). The tracking issue's delta comment still shows it.
- **R-12 (H-1 remainder, accepted).** `notify_human.sh` and `escalate_to_human.sh` run from the working tree. An unmerged edit to them can affect alert delivery, never the hold (§15.8).
- **R-10 (day one, by design).** Once Part 3 merges, the hold is configured (§15.8 predicate) before any run exists, so the first worker cycles read `sub=stale` and are **held** until someone dispatches the workflow. This is AC-38 working as specified, not a defect. The runbook (§15.10) and the PR body tell the operator to dispatch immediately after merge.

---

## 15. D-5 pause-and-alert, and the AD-22 re-cut (amendment 2026-10-20) — BINDING

**Inputs:** REQUIREMENTS-1605 §2F (AC-32..AC-43), I-7, Q-D5-1..6 (commit `4d0d2d161`); ADR-1605 §2b, AD-15..AD-23 (commit `bef59f92d`); TV-13..TV-16 (§0). AD-1..AD-23 are not re-litigated here. Where §15 and an earlier section disagree, §15 governs.

**Main facts re-verified for this section (2026-10-20, `origin/main` = `4d5b8cff5`):**

- `scripts/oversight/gates/security_scan.sh`: the temp-file trap block is at `:24–30` (`_TMP_CLEANUP`, `trap _cleanup_tmp EXIT`, HUP/INT/TERM). `NOT_PERFORMED=()` is at `:81`. The bandit-absent branch appends `NOT_PERFORMED+=("bandit SKIPPED — not installed")` at `:132`. The pip-audit lane runs from `:135` to `:227`, the `AUDIT_STATUS` tail check is at `:229–232`, and the `GATE FAIL`/`GATE PASS` tail is at `:233–247`.
- `scripts/oversight/security_scan_logic.py`: the CLI is `filter` only, reading stdin. Exit **0** means clean, **1** means kept advisories, and **2** means the audit could not be read, the roster is invalid, `packaging` is missing or the module crashed. Public pure functions used here: `parse_audit(document) -> AuditDoc` (with `.advisories`, `.skipped`, `.dependency_count`), `partition(advisories, rules, today) -> Decision` (with `.kept: list[Kept]` and `Kept.advisory`), `roster_mode(root) -> RosterMode` (with `.active`), and `SUPPRESSIONS`. `scripts/oversight/` has **no** `__init__.py`, so the module is loaded by path.
- `bin/hos-cron`: the usage-pause gate is at `:432–487`, with the bound array `_UP_BOUND`, the `if X="$(…)"; then rc=0; else rc=$?` capture and a strict verdict regex. `_REPO_SLUG` is set at `:943`, and the App token is minted at `:957`. The #1395 actionable-work gate starts at `:1126`. `_build_context` is at `:2030`, and its New work directive is at `:2068–2091`, printing only `NEW WORK: BLOCKED` or `NEW WORK: ALLOWED`. `_audit` is at `:368`. `_HOS_DIR="${HOS_STATE_DIR:-${HOME}/.hos}"` is at `:253`. `bin/**` is already a protected surface.
- `bootstrap/notify_human.sh` **does not exist** on main. #2125 has not landed. This section designs against the interface that AC-40 quotes from #2125 and that ADR AD-20 extends with `--url`. Until #2125 lands, every alert resolves to `undelivered:absent` (AC-39).
- `bootstrap/escalate_to_human.sh` exists, with usage `--number <N> --body-file <path> --reason <token> --app <role>`. It is idempotent per (issue, reason, body).
- The directive values are read by `bootstrap/worker-cron-prompt.md` (`:73–76`) **and** `.claude/agents/worker.md` (`:321–346`). See G-2.
- `docs/AGENT-IDENTITY.md` §9 mirrors `protected_surfaces.txt`'s exact-path entries (`:180`, `security_scan_logic.py`). `tests/oversight/test_security_scan_exemptions.py::test_t3` pins that mirror for #1776's module. See G-3.
- HOS has no root `requirements*.txt` or `requirements/*.txt`, so in this repo `ensure_venv.sh`'s project-requirements install adds nothing.
- No local `python3.12` exists on this host (`python3` is 3.14.4). This matters for AC-42 (§15.10).

### 15.1 `scripts/oversight/gates/dependency_audit.sh` carries main's pip-audit lane verbatim (Part 2; replaces §4.4, §4.5 and §4.1 items 3–5)

**15.1.1 File layout (binding, in this order):**

1. Header: §4.1 items 1, 2 and 6, plus these replacement items. 3′: *"Blocking on findings. The verdict comes from `security_scan_logic.py filter` and its time-boxed exemption roster (#1776). A scan whose output cannot be read, or a roster that cannot be decided, is `GATE FAIL`. An execution failure (timeout or network) after retries is `NOT CHECKED`, named in the `GATE PASS` line, and is non-blocking locally."* 4′: exit codes. 0 means clean, suspended, `--empty-changeset`, pip-audit not installed (`SKIP`) or `NOT CHECKED`. 1 means a kept advisory, unparseable output, an undecidable roster, or an invalid override. 5′: `HOS_PIP_AUDIT_BIN` is main's seam text, verbatim.
2. Preamble: §4.2, unchanged, including the AD-2a skip. Then main's trap block (`security_scan.sh:24–30`) **verbatim**. Then `ERRORS=0` and `NOT_PERFORMED=()`.
3. Announcement lines: §4.3, unchanged.
4. **The lane:** main's `security_scan.sh:141–227`, **byte-for-byte**. That runs from `AUDIT_STATE="not-run"` to the `case "$AUDIT_STATE"` block. The `echo "=== pip-audit (dependency vulnerabilities) ==="` and blank-line echoes at `:139–140` are not copied, because §4.3 prints the header. The lane's comment block at `:135–138` is copied too. Only three kinds of edit are permitted:
   - (a) `$GATES_DIR` becomes `$_GATES_DIR`, the variable §4.2 defines. The `security_scan_logic.py` path stays `"$_GATES_DIR/../security_scan_logic.py"`.
   - (b) Variables the lane reads must be defined identically before it: `VENV_BIN`, `OVERSIGHT_PYTHON`, `GATE_TIMEOUT` (default 120), `GATE_RETRIES` (default 2), plus `with_timeout` and `run_with_retry`. They come from `ensure_venv.sh` and whatever main's `security_scan.sh` sources for them. The coder copies the **same** `source` lines main uses, and adds no new ones.
   - (c) Nothing else. No rewording, no `-o`, no `GATE NOT RUN`.
5. The `AUDIT_STATUS` tail check, main's `:229–232`, verbatim.
6. **The tail (new wording, binding):**
   - `ERRORS > 0` → `GATE FAIL: dependency audit failed` and exit 1.
   - Otherwise, with `NOT_PERFORMED` non-empty → `GATE PASS: no blocking dependency vulnerabilities (<entries joined by "; ">)` and exit 0.
   - Otherwise → `GATE PASS: no blocking dependency vulnerabilities` and exit 0.
   - The join loop is main's `:237–241`. The nouns change from main's because `security_scan.sh` keeps `GATE PASS: no blocking security issues`. In `run_gates.sh` output, two different gates must not print the same pass line.

`|| echo "0"` must not appear (S-2). Bash 3.2 and shellcheck rules are unchanged (TD-2).

**15.1.2 `security_scan.sh` after the move.** This is §3's rebase item 3. The file contains no `pip-audit`, `PIP_AUDIT`, `AUDIT_STATE`, `AUDIT_STATUS`, `NOT_PERFORMED` or `security_scan_logic` token, and that is a static test (TC-S19). Its header line 4 loses "and pip-audit for dependency vulnerabilities" (§3.1 governs the exact header).

**15.1.3 `tests/oversight/test_security_scan_exemptions.py` (modify, Part 2): retarget, don't duplicate.**

| Item | Change |
|---|---|
| `_GATE` | → `_REPO / "scripts" / "oversight" / "gates" / "dependency_audit.sh"` |
| new `_BANDIT_GATE` | → `…/security_scan.sh`, used only by `g6` and `g7` |
| `_needs_gate` | Drop the `bandit` requirement. It becomes bash plus `_VENV_BIN / "python3"`, because `dependency_audit.sh` never runs bandit. Reason string: `"oversight venv python3 or bash unavailable"`. |
| `g1`, `g3`, `g4c`–`g4h`, `g5` | Unchanged except through `_GATE`. They still pass a `.py` argument, which `dependency_audit.sh` ignores (TD-1). That makes the arg-ignoring a side effect of these tests, which is intended. |
| `g2` | Expected line → `GATE PASS: no blocking dependency vulnerabilities (pip-audit binary overridden)` |
| `g4` | Expected last line → `GATE PASS: no blocking dependency vulnerabilities (pip-audit binary overridden; pip-audit NOT CHECKED — see above)` |
| `g4b` | Unchanged (it asserts a substring) |
| `g6` | **Rewritten**, renamed `test_g6_bandit_absent_prints_no_pass_line_statically`. On `_BANDIT_GATE`'s text: (i) the index of `echo "SKIP: bandit not in oversight venv` is followed within 120 characters by `exit 0`; (ii) `NOT_PERFORMED` does not occur in the file; (iii) the string `GATE PASS: no blocking security issues (` does not occur. This pins §3 rebase item 4 and the §3.5 shape. |
| new `g7` | `test_g7_security_scan_has_no_pip_audit_lane`: TC-S19's token list, asserted on `_BANDIT_GATE`. It lives here, not in `test_scan_gates_empty_args.py`, so the #1776 file owns the "lane moved, not lost" pair (g7 here, g1–g5 on the new gate). |
| `t1` | Unchanged (through `_GATE`) |
| `t2`, `t3`, `t4`, `r*`, `s*`, `x*`, `f*`, `p*`, `m*`, `pr*` | Unchanged. They test the module, not a gate. |
| module docstring | One sentence: the gate half moved to `dependency_audit.sh` in #1605 (AD-22), and the module and roster are untouched. |

TC-S19 is listed in §7.1 numbering for traceability, but it is **implemented as g7** above. It is not added a second time.

### 15.2 The scheduled measurement procedure (Part 3)

**Location (TD-D5-3).** The procedure lives in `scripts/automation/dependency_audit_report.py`, as two argv modes that dispatch **only** when `argv[0]` is the literal `measure` or `project`. Every other argv goes to the existing §9.7 parser, unchanged. No new file is created (Part 3 is at 15, §15.11). `measure` is stdlib-only and runs under the job's `python3`, which setup-python provides as 3.12. `project` runs under the **venv** interpreter, as a child of `measure`, because it imports `packaging` through `security_scan_logic`.

```
python3 -m scripts.automation.dependency_audit_report measure \
    --venv-bin <dir> --python-version <M.m> --requirements <file> [--requirements <file> ...] \
    --venv-build-outcome <success|failure|cancelled|skipped> \
    --out-json <path> --github-output <path> \
    [--attempt-timeout-seconds <n, default 300>] [--retry-sleep-seconds <n, default 30>] \
    [--logic-path <path, default scripts/oversight/security_scan_logic.py>]
<venv-bin>/python -m scripts.automation.dependency_audit_report project \
    --raw <path> --out <path> [--logic-path <path>]
```

`--logic-path`, `--attempt-timeout-seconds` and `--retry-sleep-seconds` exist **for tests only**. The workflow must not pass any of them (workflow-static test TC-W4). `--logic-path` never makes the production path use a copy: the default is the checked-out module (AC-32).

**Steps (binding order; each failure sets `cause` and stops):**

| Step | Action | Pass condition | Failure → `cause` (`sub`) |
|---|---|---|---|
| 1 | Check `--venv-build-outcome` | `== success` | `venv-build-failed` |
| 2 | Run `<venv-bin>/python -c "import json,sys; print(json.dumps([sys.version_info[0], sys.version_info[1], sys.prefix != sys.base_prefix]))"` with a 30 s timeout | rc 0, and stdout parses to exactly `[M, m, true]` from `--python-version` | `interpreter-wrong` (this includes a missing python, rc≠0, a timeout and a mismatch) |
| 3 | **pip-audit present** *(moved ahead of the venv-match step, architect R-A 2026-10-20: `pip-audit` is in `scripts/oversight/requirements.txt`, so a real absence would otherwise surface as `venv-mismatch`)* | `<venv-bin>/pip-audit` is a regular file and executable | `pip-audit-absent` |
| 4 | **Venv matches requirements (TV-16).** Run `<venv-bin>/pip install --dry-run --no-index --quiet` then `-r <f>` for each `--requirements`, then `--report <tmp>/pip-report.json`, with a 120 s timeout | rc 0, the report parses, and `report["install"] == []` | `venv-mismatch` (this includes pip being absent) |
| 5 | **Run pip-audit, and accept output whatever the rc (TV-15).** Up to 3 attempts, sleeping `--retry-sleep-seconds` between them. Each attempt deletes `<tmp>/raw.json`, then runs `<venv-bin>/pip-audit --progress-spinner off --format json -o <tmp>/raw.json` with the attempt timeout. stderr is captured and only its last 20 lines are kept. An attempt is **accepted** only if rc ∈ {0,1} **and** `raw.json` is a regular non-symlink file of at most `MAX_INPUT_BYTES` **and** `json.loads` of it gives a dict. | an attempt is accepted | After exhaustion, these are checked in order. A file over `MAX_INPUT_BYTES` on any attempt gives `oversized`. Otherwise, any attempt with rc ∈ {0,1} and no acceptable file gives `unparseable`, and this is sticky across later timeouts (main's CWE-636 rule). Otherwise, all attempts timing out gives `timeout`. Otherwise `pip-audit-failed`. |
| 6 | **Verdict = filter rc (AC-32).** Run `PYTHONSAFEPATH=1 <venv-bin>/python <logic-path> filter < raw.json` with a 60 s timeout, capturing stdout and stderr (each capped at 64 KiB) | rc ∈ {0,1} | rc 2 with stderr starting `GATE FAIL: exemption roster invalid` gives `roster-invalid`. rc 2 with stderr starting `GATE FAIL: could not parse pip-audit output` gives `unparseable`. Any other rc 2, any other rc, or a timeout gives `filter-error`. |
| 7 | **Skip count (TV-14, AD-21).** Done inside `project` (step 8) as `len(parse_audit(doc).skipped)`, using the module's own parser, never a re-implementation | — | see step 9 |
| 8 | **Projection.** Run `<venv-bin>/python -m scripts.automation.dependency_audit_report project --raw raw.json --out <out-json> --summary <tmp>/summary.json` with a 60 s timeout | rc 0; exactly one stdout line that `re.fullmatch`es `PROJECT kept=(0\|[1-9][0-9]{0,5}) skipped=(0\|[1-9][0-9]{0,5}) first=(-\|unattributable\|<VULN_ID_RE>) deps=([0-9]{1,6})`; and `summary.json` parses to exactly `{"kept": int, "skipped": int, "first": str, "deps": int, "kept_ids": [str, ...]}` with the same four scalars as the line and `len(kept_ids) == kept` *(security round 1, L-2/L-3)* | `filter-error` |
| 9 | **Consistency and partial audit.** If verdict is 0, then `kept` must be 0, and the filter's stdout must contain no `GATE FAIL:` line. If verdict is 1: *(security round 1, L-2; two-sided)* the filter's stdout must contain exactly one header line that `re.fullmatch`es `GATE FAIL: ([1-9][0-9]{0,5}) dependency advisory\(ies\) not covered by an exemption:`; the lines after it, up to the next line not starting with two spaces, contain the per-advisory **kept lines** (`render` prints them as two spaces, then `<package> <version> [<id>] fix: …`; a note line starts with four spaces and is skipped); a kept line `re.fullmatch`es `  (\S+) (\S+) \[([^\]\x00-\x1f\x7f]{1,200})\] fix: .*`. The header's N, the number of kept lines, and the projection's `kept` must all be equal, and the **multiset** of kept-line ids must equal the multiset `summary.kept_ids`. | consistent | `projection-mismatch`. If it is consistent, verdict is 0 and `skipped > 0`, the result is `partial-audit` (AD-21). If verdict is 1 and `skipped > 0`, the result is a **finding** with `partial=1` (TD-D5-2). |

**`project` mode (pure core plus thin I/O):**

- It loads `security_scan_logic` from `--logic-path` with `importlib.util.spec_from_file_location`, under a fixed module name, `hos_security_scan_logic_1605`.
- It computes `mode = roster_mode(<repo root>)`, `rules = SUPPRESSIONS if mode.active else ()` and `today = datetime.now(timezone.utc).date()`. These are the exact three expressions in `security_scan_logic.main()`. A comment must say so, and must say that step 9's consistency check is what detects any drift.
- It then computes `doc = parse_audit(json.loads(raw))` and `decision = partition(doc.advisories, rules, today)`.
- The pure function is `project_audit(document, rules, active, today, logic) -> tuple[dict, ProjectionSummary]`.
- **Output document:** `{"dependencies": [...]}`. For each dependency entry of the raw document that has **no** `skip_reason` key, it emits `{"name", "version", "vulns": [the raw vuln dicts whose (canonical package, version, id) is in the kept set]}`. Dependencies with no kept vuln are emitted with `"vulns": []`. Skip entries are dropped, because a skip entry has no `version` (TV-14) and `normalize` would reject it. Raw vuln dicts are copied verbatim, so `normalize` (§9.3) still applies SEC-S4 to every value. A kept **malformed** advisory has no raw dict that matches cleanly. It is emitted as its raw dict when one can be identified by position, and otherwise it is counted but not emitted. `normalize` may then reject the document, which gives a `report-failed` finding (§15.3). The hold stands, so this fails closed.
- `first`: the kept advisories are sorted by `(advisory.key, advisory.advisory_id)`. `first` is the first `advisory_id` that full-matches `VULN_ID_RE`. If no kept id matches, `first` is `unattributable`. With no kept advisories, `first` is `-`.
- `kept_ids` *(security round 1, L-2)*: the `advisory_id` of every `decision.kept` item, in `decision.kept` order, duplicates kept, no validation (step 9 compares them to the filter's lines byte for byte).
- It writes `--out` and `--summary` atomically (temp file plus `os.replace`), mode 0644, then prints the one `PROJECT` line and exits 0. Any exception means exit 2, with the cause on stderr.

**Why the artifact is the projection (TD-D5-7, D-5 item 3).** `report` installs nothing and so cannot import `security_scan_logic`. If it were handed the raw document, the tracking issue would list black and mcp, which the human has exempted. Then a clean run (verdict 0) would sit next to an open issue full of "findings". The projection makes the issue's finding set equal the roster-filtered kept set. On a clean run it is empty, so `report` closes the issue (§9.5). This is a change to *what* `report` reads. `report`'s code, allowlists, bounds and decision table are unchanged.

**Output of `measure` (binding).**

- **Log lines.** It prints the filter's stdout lines to its own stdout **only when** the result is clean or a finding. On every `NOT_RUN` cause it prints `dependency audit: filter output withheld — this run is NOT_RUN (<cause>); nothing here is a pass`. This is because the filter prints an `OK:` line on a partial audit (TV-14), and AC-33 forbids an `OK` line on a non-clean outcome. pip-audit's captured stderr tail is printed prefixed `  pip-audit stderr: `.
- **Workflow-command neutralisation** *(security round 1, L-3(c), binding)*. Every line `measure` echoes that came from a subprocess (filter stdout, filter stderr, pip stderr, pip-audit stderr) goes through one function, `_echo_untrusted(lines)`. That function (i) prints `::stop-commands::<token>` first, where `<token>` is `secrets.token_hex(16)` generated per call; (ii) prints each line with C0 controls and DEL replaced by `?`, prefixed with two spaces; (iii) prints `::<token>::` last. No other code path prints subprocess text. The `MEASURE` line is printed after the region is closed. The `report` step's `cat "$RUNNER_TEMP/report.out"` is replaced by the same pattern in bash: `T="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"`, `echo "::stop-commands::$T"`, `sed 's/^/  /' "$RUNNER_TEMP/report.out"`, `echo "::$T::"`.
- **Final stdout line**, always: `MEASURE verdict=<0|1|-> cause=<-|sub token> kept=<n> first=<id|unattributable|-> skipped=<n|-> partial=<0|1> ids=<n_ids> more=<0|1>`.
- **`--github-output`**: it appends exactly seven lines: `verdict=<0|1|->`, `cause=<…>`, `kept=<n>`, `first=<…>`, `partial=<0|1>`, `ids=<-|comma list>`, `more=<0|1>`. They are written **before** exit on every path, including failures. If writing them fails, the exit is 1 and the outcome becomes `audit-failed`.
  - *(Security round 1, L-3(b), binding.)* Each value is written only after `re.fullmatch` against that key's pattern: `verdict` `[01-]`; `cause` `-\|[a-z][a-z0-9_-]{0,31}`; `kept` `0\|[1-9][0-9]{0,5}`; `first` `-\|unattributable\|<VULN_ID_RE>`; `partial` `[01]`; `ids` §15.4's `IDS` group; `more` `[01]`. On any mismatch, all seven are written as the safe defaults `verdict=-`, `cause=audit-output-invalid`, `kept=0`, `first=-`, `partial=0`, `ids=-`, `more=0`, and `measure` exits 1. No free text is ever written there.
  - *(G-4.)* `ids` is the **sorted, de-duplicated** (bytewise) set of kept ids that full-match `VULN_ID_RE`, plus the token `unattributable` once if any kept id does not, truncated to the first 100 entries; `more=1` iff the set had more than 100 entries. On every non-finding path `ids=-` and `more=0`.
- **Exit:** 0 for a clean result or a finding (verdict 0 or 1, consistent). 1 for every `NOT_RUN` cause. 2 for a usage error. No path prints `SKIP`, `GATE PASS`, `PASS` or a leading `OK:` unless the result is clean (TC-H1, TC-P*).

**Cause table (AC-33 → sub tokens; every row is `outcome=not_run cause=environment-broken`):**

| AC-33 condition | `sub` |
|---|---|
| pip-audit absent from the venv | `pip-audit-absent` |
| venv does not match `requirements.txt` | `venv-mismatch`; `venv-build-failed` if `ensure_venv.sh` itself failed |
| wrong interpreter | `interpreter-wrong` |
| retries exhausted, on timeout or network | `timeout`, `pip-audit-failed` |
| output unparseable, or failing the allowlist (AC-25) | `unparseable`, `oversized`; an allowlist failure in `report` is `report-failed` (§15.3) |
| roster invalid (`run_filter` exit 2) | `roster-invalid`; other exit-2 cases are `filter-error` |
| partial audit (AD-21) | `partial-audit` |
| internal inconsistency | `projection-mismatch` |

### 15.3 `.github/workflows/dependency-audit.yml`: three jobs (Part 3; amends §10.2)

Everything in §10.2's binding list still holds. These are the deltas (exact YAML is the coder's, and the properties are binding and test-pinned by TC-W*):

**`audit` job.**

- It gains `outputs:` `verdict`, `cause`, `kept`, `first` and `partial`, each `${{ steps.measure.outputs.<name> }}`.
- Step `Build oversight venv` gets `id: venv` and `continue-on-error: true`. It still runs `bash scripts/oversight/ensure_venv.sh`.
- Step `Measure` gets `id: measure` and `if: always()`. Its `env:` is `VENV_OUTCOME: ${{ steps.venv.outcome }}` and nothing else. Its `run:` is:
  ```
  set -uo pipefail
  python3 -m scripts.automation.dependency_audit_report measure \
    --venv-bin scripts/oversight/.venv/bin --python-version 3.12 \
    --requirements scripts/oversight/requirements.txt \
    --venv-build-outcome "$VENV_OUTCOME" \
    --out-json "$RUNNER_TEMP/pip-audit.json" --github-output "$GITHUB_OUTPUT"
  ```
  - `--python-version` must equal the `setup-python` `python-version` in the same job (TC-W2).
  - The `--requirements` list is the file set `ensure_venv.sh` installs. For HOS that is the one oversight file. A comment must say that a project with root `requirements*.txt` adds each one here.
- Step `Run pip-audit` (§10.2) is **deleted**.
- `upload-artifact` gets `if: steps.measure.outcome == 'success'` and `path: ${{ runner.temp }}/pip-audit.json`. Name, `if-no-files-found: error` and retention are unchanged.
- The job fails whenever `measure` exits non-zero, so `report` is skipped. AC-25's structure is unchanged.

**`report` job.** `needs: audit`, with no `if:` (unchanged).

- It gains `outputs: issue: ${{ steps.reconcile.outputs.issue }}`.
- The reconcile step gets `id: reconcile`. After the existing guard, it runs the module with stdout redirected to `"$RUNNER_TEMP/report.out"`, then `cat`s that file. It then extracts the **last** line, which must full-match `^dependency_audit_report: tracking_issue=([1-9][0-9]{0,8}|none)$`. It writes `issue=<N>`, or `issue=-` for `none`, to `$GITHUB_OUTPUT`. If there is no matching last line, it exits 1. Under `set -euo pipefail`, a module exit≠0 fails the step before extraction.

**`outcome` job (new).**

```
outcome:
  name: dependency-audit-outcome        # the consumer selects the job by this exact name (§15.5)
  needs: [audit, report]
  if: always()
  runs-on: ubuntu-latest
  timeout-minutes: 5
  permissions: {}
  steps:
    - name: Publish the outcome record
      env: { AUDIT_RESULT: ${{ needs.audit.result }}, REPORT_RESULT: ${{ needs.report.result }},
             VERDICT: ${{ needs.audit.outputs.verdict }}, CAUSE: ${{ needs.audit.outputs.cause }},
             KEPT: ${{ needs.audit.outputs.kept }}, FIRST: ${{ needs.audit.outputs.first }},
             PARTIAL: ${{ needs.audit.outputs.partial }}, ISSUE: ${{ needs.report.outputs.issue }},
             IDS: ${{ needs.audit.outputs.ids }}, MORE: ${{ needs.audit.outputs.more }},
             SHA: ${{ github.sha }} }
      run: <the mapping script below; no ${{ }} inside it>
```

The job has no `uses:`, no checkout and no setup-python. Its single `run:` is a bash script with `set -euo pipefail` and `LC_ALL=C`. That script:

1. **Validates every input** with `[[ =~ ]]` full-match patterns:
   - `AUDIT_RESULT` and `REPORT_RESULT` ∈ {success, failure, cancelled, skipped};
   - `VERDICT` ∈ {0, 1, -, empty};
   - `CAUSE` must be empty, `-` or `^[a-z][a-z0-9_-]{0,31}$`;
   - `KEPT` must be empty or `^(0|[1-9][0-9]{0,5})$`;
   - `FIRST` must be empty, `-`, `unattributable` or the record's id pattern (§15.4);
   - `PARTIAL` ∈ {0, 1, empty};
   - `ISSUE` must be empty, `-` or `^[1-9][0-9]{0,8}$`;
   - `SHA` must match `^[0-9a-f]{40}$`;
   - *(G-4)* `IDS` must be empty, `-` or §15.4's `IDS` group; `MORE` ∈ {0, 1, empty};
   - *(security round 1, L-3(a))* before any pattern test, every input containing a newline, carriage return or other C0/DEL character is invalid (`[[ $v == *[[:cntrl:]]* ]]`).

   An invalid `SHA` exits 1 with no record, which the consumer reads as `record-invalid`. Any other invalid input gives `outcome=not_run`, `sub=audit-output-invalid`.
2. **Maps the inputs, first matching row wins:**

   | Condition | outcome | cause | sub | first | kept | issue |
   |---|---|---|---|---|---|---|
   | `AUDIT_RESULT != success` | not_run | environment-broken | `CAUSE` if valid and not `-`/empty, else `audit-failed` | - | 0 | - |
   | `VERDICT=1` and `KEPT≥1` and `FIRST∉{-,empty}` and `IDS∉{-,empty}` | finding | dependency-advisory | `report-failed` if `REPORT_RESULT != success`; else `partial-audit` if `PARTIAL=1`; else `-` | `FIRST` | `KEPT` | `ISSUE` if numeric, else - |
   | `VERDICT=0` and `KEPT=0` and `REPORT_RESULT=success` | clean | - | - | - | 0 | `ISSUE` if numeric, else - |
   | `VERDICT=0` and `KEPT=0` and `REPORT_RESULT != success` | not_run | environment-broken | report-failed | - | 0 | - |
   | anything else | not_run | environment-broken | audit-output-invalid | - | 0 | - |
3. Builds the record (§15.4; `ids=`/`more=` are `IDS`/`MORE` for a finding and `-`/`0` otherwise) and prints it exactly once as `echo "::notice::${RECORD}"`. No other `::notice`, `::warning` or `::error` command is printed.
4. Exits 0 if the outcome is `clean`, and 1 otherwise, so a finding or a `NOT_RUN` shows as a red run (TD-D5-9). The consumer reads the record whatever the run's conclusion (§15.5).

### 15.4 Record grammar (binding; ADR AD-16)

One line, ASCII only, no control characters, at most **8192** bytes *(raised from 512 for G-4; ADR AD-16 text change listed in the round-1 report)*, matched with Python `re.fullmatch` on the exact string *(security round 1, L-3(a); the `^…$` below is notation, and `$` is never relied on)*:

```
hos-dependency-audit/1 outcome=(clean|finding|not_run) cause=(-|dependency-advisory|environment-broken) sub=(-|[a-z][a-z0-9_-]{0,31}) first=(-|unattributable|ID) kept=(0|[1-9][0-9]{0,5}) issue=(-|[1-9][0-9]{0,8}) ids=(IDS) more=(0|1) sha=([0-9a-f]{40})
IDS = -|IDTOK(,IDTOK){0,99}      IDTOK = unattributable|ID
```

Here `ID` is §9.2's `VULN_ID_RE`, verbatim. It is defined once, in `dependency_audit_report.py`, and `dependency_pause.py` imports that constant. The bash in `outcome` cannot import it, so it carries a literal copy, and TC-W6 asserts the two are equal.

**Semantic rules** (the consumer checks them after the regex; any violation is `record-invalid`):

- `clean` ⇒ `cause=- sub=- first=- kept=0`;
- `finding` ⇒ `cause=dependency-advisory`, `first≠-`, `kept≥1`, `ids≠-`, the `ids` list strictly increasing bytewise (sorted, no duplicates), its length ≤ `kept`, and, when `more=0`, `first` ∈ `ids` *(G-4)*;
- `clean` and `not_run` ⇒ `ids=- more=0` *(G-4)*;
- `not_run` ⇒ `cause=environment-broken`, `sub≠-`, `first=-` and `kept=0`.

### 15.5 The read path: three `github.py` read helpers, plus selection (Part 3; ADR AD-16)

Placed directly after §8's three write helpers, under the section comment `# --- Actions-run reads (added for #1605's dependency hold; single consumer: scripts/automation/dependency_pause.py) ---`. Each docstring names #1605 and the single consumer.

```python
def list_workflow_runs(owner, repo, workflow_file, *, branch, status="completed", per_page=20, retries=3) -> list[dict]
    # GET /repos/{o}/{r}/actions/workflows/{workflow_file}/runs?branch={branch}&status={status}&per_page={per_page}
    # returns payload["workflow_runs"]; ONE page, never paginated.
def list_run_jobs(owner, repo, run_id, *, per_page=50, retries=3) -> list[dict]
    # GET /repos/{o}/{r}/actions/runs/{run_id}/jobs?filter=latest&per_page={per_page}; returns payload["jobs"].
def list_check_run_annotations(owner, repo, check_run_id, *, per_page=50, retries=3) -> list[dict]
    # GET /repos/{o}/{r}/check-runs/{check_run_id}/annotations?per_page={per_page}; returns the list.
```

**Contract:**

- **Inputs are validated before any call, with `ValueError` on failure:**
  - `workflow_file` full-matches `[A-Za-z0-9._-]{1,100}\.ya?ml`;
  - `branch` full-matches `[A-Za-z0-9._/-]{1,100}` and is URL-encoded with `urllib.parse.quote(branch, safe="")`;
  - `status` ∈ {completed};
  - the ids are `int` (not `bool`) and > 0;
  - `per_page` is in 1..100.
- **Calls** all go through `_run_gh([...], retries=retries)`.
- **Response shape:**
  - The payload must be a dict holding the named list, or for annotations a list. Otherwise the helper raises `GitHubError("<helper>: unexpected response shape")`.
  - A genuine 200 with an empty list returns `[]`.
  - §8's 404→raise is preserved.

**Selection rules** live in `dependency_pause.py` as pure functions over the helper results:

1. **Runs.** A run qualifies if `head_branch == "main"` (`DEFAULT_BRANCH`, a module constant, TD-D5-10), `event ∈ {"schedule", "workflow_dispatch"}`, `path == ".github/workflows/dependency-audit.yml"` and `status == "completed"`.
   - The newest qualifying run wins, by `run_started_at` (ISO-8601 Z, parsed strictly), ties broken by the larger `id`. Its `conclusion` does not matter here.
   - No qualifying run gives `stale`.
   - A qualifying run with `conclusion ∉ {success, failure}` (cancelled, timed_out, startup_failure, skipped, neutral, action_required, or null) gives `not_run`, `sub=run-incomplete`.
   - An unqualified run is ignored, and is **never** trusted (AD-16).
   - *(Security round 1, L-3(d).)* If the selected run's `run_started_at` is later than `now + 300 s`, the result is `not_run`, `sub=run-invalid`. A future start is never read as "age negative, so fresh".
2. **Staleness** (AD-17) is checked **before** the record is read:
   - `now - run_started_at > max_age` gives `stale`. Equal to `max_age` is not stale.
   - `max_age` comes from `HOS_DEPENDENCY_AUDIT_MAX_AGE_HOURS`: unset means 216, and a value full-matching `[0-9]{1,4}` within [168, 336] is used as is.
   - Any other value gives held, `sub=config-invalid`, before any read.
3. **Jobs.** Exactly one job must have `name == "dependency-audit-outcome"`, `status == "completed"` and a `check_run_url` full-matching `https://api\.github\.com/repos/<owner>/<repo>/check-runs/([1-9][0-9]{0,15})`, with `<owner>/<repo>` compared case-insensitively to `--repo-slug`. Otherwise the result is `record-invalid`.
4. **Annotations.** The candidates are annotations whose `annotation_level == "notice"`, whose `message` is a `str` of at most 8192 bytes once encoded as UTF-8, ASCII only, free of control characters, and which `re.fullmatch` §15.4.
   - Exactly one candidate is required, and its `sha` must equal the run's `head_sha`. Otherwise the result is `record-invalid`.
   - Then the §15.4 semantic rules apply.
5. **Retries.** The consumer calls every helper with `retries=1` (TD-D5-6). That keeps the worst case at 3 × (30 s + 2 s + 30 s), which is under hos-cron's 240 s bound (§15.8).

**Read failure and the cache (AD-17).**

- Any `GitHubError`, `RateLimitError`, `ValueError` from shape validation, or `subprocess.TimeoutExpired` from any of the three reads is a read failure.
- A **complete** read, meaning one where selection reached a decision (including `stale`, `run-incomplete` and `record-invalid`), is cached at `<hold-dir>/dependency-audit.reading`. The file has no `.json` suffix so the hold reader (§15.6) never parses it.
  - Cache format: JSON `{"schema": "hos-dependency-audit-reading/1", "read_at": <iso>, "run": {"id", "run_started_at", "html_url", "conclusion", "head_sha"} | null, "record": <str|null>, "selection_sub": <token|null>, "last_issue": <int|null>}`.
  - `last_issue` *(architect R-B, 2026-10-20)* is the most recent numeric `issue=` from any valid record this consumer has read. It is carried forward from the previous cache when the current record has `issue=-`, and it is never cleared by a clean run. It feeds only the §15.7 fallback target. It never affects the outcome, the fingerprint or the hold.
  - It is written 0600 and atomically, through the §15.6 `dir_fd` + `O_NOFOLLOW` path.
  - *(Security round 1, M-3(a), binding.)* On every read, the cache gets the same file checks as a hold file (§15.6) and a strict schema: the key set is exactly the eight above; `schema` equals the constant; `read_at` is ISO-8601 `Z` and not later than `now + 300 s`; `run` is null or has exactly its five keys with `id` an int > 0, `run_started_at` ISO `Z`, `html_url` full-matching `https://github\.com/<owner>/<repo>/actions/runs/<id>`, `conclusion` null or `[a-z_]{1,32}`, `head_sha` 40 hex; `record` is null or is **re-validated through §15.4** on use; `selection_sub` null or a sub token; `last_issue` null or an int in 1..999999999. Any violation means held, `sub=state-corrupt` (never "no cache").
- On a read failure, the cache is used **only if** it parses and `now - read_at ≤ 6 h` (21,600 s). The cached reading is then **re-evaluated** at `now`, so staleness keeps advancing.
- Otherwise the result is `not_run`, `sub=read-failed`.
- The summary line reports `reading=fresh`, `reading=cached:<age_s>` or `reading=none` (§15.6). If the human rejects I-7 (Q-D5-6), the only change is `READ_FAILED_HOLDS = False`, a module constant that maps `read-failed` to `run` and logs it.

### 15.6 `scripts/automation/dependency_pause.py`: state, decide and apply (Part 3; ADR AD-18)

**Module shape.** The module is a pure core (`select_run`, `parse_record`, `evaluate`, `fingerprint`, `plan_transition`) plus an I/O shell (`read_holds`, `write_hold`, `delete_hold`, `send_alert`, `main`). All I/O is injected through a `Deps` dataclass: `now()`, the three read callables, `run_notifier(argv, timeout)`, `run_escalation(argv, timeout)`, `env` and `state_root`. No test touches the network or `~` (AC-28, AC-43).

**CLI:**

```
python3 -m scripts.automation.dependency_pause check \
    --project <name> --repo-slug <owner/repo> --state-dir <dir> --repo-root <dir>
```

- `--project` full-matches `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`.
- `--repo-slug` full-matches `[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}`.
- Anything else is exit 2 (usage), with no state write. hos-cron reads that as `check_error`.
- The notifier path is `<repo-root>/bootstrap/notify_human.sh`, and the fallback path is `<repo-root>/bootstrap/escalate_to_human.sh`. Neither is an argument, so there is no seam that redirects the alert.

**State (binding schema `hos-build-hold/1`).**

- **Directory:** `<state-dir>/build-hold/<project>/`.
  - *(Security round 1, M-3(a), binding.)* Every component from `<state-dir>` down (`<state-dir>`, `build-hold`, `<project>`) is checked with `os.lstat`: it must not be a symlink, must be a directory, must have `st_uid == os.geteuid()`, and must have `st_mode & 0o022 == 0`. A missing `build-hold` or `<project>` component is created with `os.mkdir(name, 0o700, dir_fd=<parent fd>)`. Each component is then opened with `os.open(name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW, dir_fd=<parent fd>)` and re-checked with `os.fstat` (same four rules), so a swap between check and open is caught. All later file access uses the final directory fd. Any violation means held, `sub=state-corrupt`, and nothing is written.
  - Every file (hold files, the cache) is opened with `os.open(name, O_RDONLY | O_NOFOLLOW, dir_fd=dfd)` and must `fstat` as a regular file with `st_uid == euid` and `st_mode & 0o077 == 0`. Otherwise it is corrupt.
- **Own file:** `<dir>/dependency-audit.json`, mode 0600. The write sequence is `os.open(".dependency-audit.json.tmp-<pid>", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600, dir_fd=dfd)`, then write, `fsync`, and `os.replace(tmp, final, src_dir_fd=dfd, dst_dir_fd=dfd)`. Deletion is `os.unlink(name, dir_fd=dfd)`.
- **Fields** (all required, `null` where shown):

```json
{"schema":"hos-build-hold/1","source":"dependency-audit",
 "cause":"dependency-advisory|environment-broken","sub":"<token>|null",
 "fingerprint":"dependency-audit:<cause>:<first|sub>",
 "since":"<iso Z>","last_evaluated":"<iso Z>",
 "issue":<int>|null,"run_url":"<https url>"|null,
 "clear_act":"<fixed sentence below>",
 "alert":{"status":"sent|undelivered|pending","reason":"<token>|null","at":"<iso Z>|null",
          "fallback":"posted|failed|not-applicable|disabled"},
 "detail":{"held_since":"<iso Z>","first":"<id>|null","kept":<int>,"reading":"fresh|cached|none",
           "alerted_ids":["<IDTOK>", ...],"alerted_more":0|1,"kept_at_alert":<int>}}
```

- **Fingerprint (AC-41):**
  - a finding is `dependency-audit:dependency-advisory:<first>`;
  - a `not_run` is `dependency-audit:environment-broken:<sub>`.
  - The fingerprint identifies the **hold only**. It is not the alert trigger (AC-41 as amended by pm-agent's G-4 ruling, commit `ebadd5397`). Re-alerting is decided by `alerted_ids` (below).
- **`detail.alerted_ids` / `detail.alerted_more` (G-4, binding).** `alerted_ids` is the record's `ids` set at the moment the most recent `dependency-advisory` alert was **attempted** (sent or undelivered): a JSON list of at most 100 `IDTOK` strings, strictly increasing bytewise, each validated by `re.fullmatch`. `alerted_more` is that record's `more`. For an `environment-broken` hold both are `[]` and `0`. A list that is not a list, is longer than 100, is unsorted, has duplicates, or has an invalid token makes the file corrupt (state-corrupt).
- **`clear_act`** is exactly: `Record a time-boxed exemption in the #1776 roster (scripts/oversight/security_scan_logic.py) or land a dependency bump, then run "Dependency audit (scheduled)" on main via workflow_dispatch. The hold clears only on the next clean run.` (AC-37; Q-D5-3 pending, recommendation clean-run only.)

**Shared reader `read_holds(dir)`.**

- It reads every entry whose name full-matches `[a-z][a-z0-9-]{0,31}\.json`, and ignores all others. That ignores the cache file and temp files. (The `check_error` throttle marker is not in this directory at all, §15.8.)
- A file that cannot be read, is over 64 KiB, is not JSON, or lacks `schema == "hos-build-hold/1"` and `source == <stem>` gives `Hold(source=<stem>, cause="environment-broken", sub="state-corrupt", corrupt=True)`. It is never "absent".
- *(Security round 1, M-1(a), binding.)* `read_holds` validates **every field it uses, of every file, own or other**, with `re.fullmatch` after rejecting control characters: `source` = the stem; `cause` and `sub` `[a-z][a-z0-9_-]{0,31}` (`sub` may be null); `issue` null or an `int` (not `bool`) in 1..999999999; `since` ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`; `alert.status` ∈ {sent, pending, undelivered}; `alert.reason` null or `[a-z0-9-]{1,32}`; `alert.fallback` ∈ {posted, failed, not-applicable, disabled}. For the own file, every other schema field is validated too (types, ISO times, `run_url` full-matching `https://github\.com/<owner>/<repo>/actions/runs/[1-9][0-9]{0,15}`, `fingerprint` per AC-41, the G-4 fields). Any failure makes that file corrupt. The `[HELD-*]` lines are **re-rendered** from the validated fields by one formatter. File text is never echoed, and `clear_act` is never read by anyone but a human (hos-cron uses its own constant, §15.8).
- **Other sources' files are read-only to this module.** They are never written or deleted, even on a clean dependency run. That is the #2123 seam.

**`evaluate(reading, now, max_age) -> Evaluation(outcome, cause, sub, first, kept, issue, run_url)`.** Pure. It applies §15.5 rules 1–4. A `finding` keeps the record's `sub` (`report-failed` or `partial-audit` or `-`).

**`plan_transition(own_state, evaluation, now) -> Plan`** (pure; this is decide/apply):

| Own file | Evaluation | Plan |
|---|---|---|
| absent | clean | nothing; no event |
| absent | not clean | write a new file: `since = held_since = now`, `alert.status = "pending"`, and (finding) `alerted_ids`/`alerted_more`/`kept_at_alert` from this record. Event `dependency-pause-set`. Alert. |
| valid, same fingerprint | not clean | keep `since`, `held_since` and `alert`. Update `last_evaluated`, `issue`, `run_url` and `detail.reading`. No event. **G-4 re-alert:** if the evaluation is a `finding` and `new = set(record.ids) − set(detail.alerted_ids)` is non-empty, **or** `record.more == 1` and `record.kept > detail.kept_at_alert` (see below), then: event `dependency-advisory-realert`, `alert.status = "pending"`, alert, and set `alerted_ids`/`alerted_more`/`kept_at_alert` from this record. An unchanged or shrinking set (`new` empty) does **not** re-alert. Otherwise, re-send only if `alert.status == "undelivered"` and `now - alert.at ≥ 3600 s`. |
| valid, different fingerprint | not clean | `since = now`, keep `detail.held_since`, `alert.status = "pending"`, and reset `alerted_ids`/`alerted_more`/`kept_at_alert` from this record (`[]`/0/0 for `environment-broken`). Event `dependency-pause-set` with `previous_fingerprint`. Alert. (TD-D5-4) |
| valid | clean | delete the file. Event `dependency-pause-cleared` with `duration_s = now - detail.held_since` (whole seconds), plus `fingerprint` and `run_url`. |
| corrupt | any | held this cycle, `sub=state-corrupt`, fingerprint `dependency-audit:environment-broken:state-corrupt`. Overwrite the file with that hold (`since = held_since = now`). Event `dependency-pause-set`. Alert. The next cycle re-derives normally (TD-D5-5). |

Deleting the file by hand achieves nothing: the next not-clean evaluation rewrites it (AD-18).

**G-4 resolution (pm-agent ruling, REQUIREMENTS AC-34/AC-41/AC-43 at `ebadd5397`; binding).** The comparison is **set-based, not count-based**: the swap case (one advisory clears, another arrives, `kept` unchanged) gives a non-empty `new` and re-alerts. `detail` gains `kept_at_alert` (int, 0..999999). It is used only in the overflow case (`more=1`, more than 100 distinct kept ids): there the record lists only the first 100 sorted ids, so an id beyond them is invisible; the rule then also re-alerts when `kept` grows past `kept_at_alert`. **Residual R-11:** with more than 100 distinct kept advisories, a swap entirely beyond the first 100 ids is not detected. It is disclosed in the Part 3 PR body. A `not_run` evaluation never changes `alerted_ids`, because it carries no id information. A re-alert under an unchanged fingerprint does not reset `since`.

**stdout contract** (exit 0 whenever the final line is printed):

- `EVENT dependency-pause-set fingerprint=<fp> cause=<c> sub=<s|-> issue=<n|-> run_url=<url|-> [previous_fingerprint=<fp>]`
- `EVENT dependency-pause-cleared fingerprint=<fp> duration_s=<n> run_url=<url|->`
- `EVENT alert-undelivered cause=<c> reason=<r> fingerprint=<fp>`
- `EVENT dependency-advisory-realert fingerprint=<fp> cause=dependency-advisory issue=<n|->` *(G-4)*
- `[HELD-DEPENDENCY] cause=<c> sub=<s|-> issue=<#n|-> since=<iso> alert=<sent|pending|undelivered:<reason>>[ fallback=<f>]`, one line if the own source is held
- `[HELD-BUILD] source=<s> cause=<c> sub=<s|-> issue=<#n|-> since=<iso|-> alert=<…|->`, one line per other held source, sorted by source
- `DEPENDENCY-PAUSE decision=<run|hold> holds=<n> reading=<fresh|cached:<age_s>|none>`, last, exactly once

Every value is a token without spaces, and URLs are validated `https://github.com/…` strings. *(Security round 1, L-1, binding.)* EVENT keys are restricted to exactly {`fingerprint`, `cause`, `sub`, `issue`, `run_url`, `previous_fingerprint`, `duration_s`, `reason`}; the module never prints another key. Values per key: `fingerprint`/`previous_fingerprint` `dependency-audit:(dependency-advisory|environment-broken):(unattributable|<VULN_ID_RE>|[a-z][a-z0-9_-]{0,31})`; `cause` the two causes; `sub` `-` or a sub token; `issue` `-` or `[1-9][0-9]{0,8}`; `run_url` `-` or the validated run URL; `duration_s` `[0-9]{1,10}`; `reason` `[a-z0-9-]{1,32}`. EVENT lines are printed only on transitions (AD-19). An unhandled exception gives exit 1, and hos-cron reads that as `check_error`.

### 15.7 The alert (Part 3; ADR AD-20, AC-39, AC-40)

**Ordering (binding).** `write_hold` completes, including `os.replace`, **before** `send_alert` is called. TC-A2 asserts that the hold file exists when the fake runner is invoked.

**Argv (AC-40), exactly:**

```
<repo-root>/bootstrap/notify_human.sh --cause <dependency-advisory|environment-broken> --issue <n> \
    --since <since> --priority high --body-file <path>
```

When `issue` is null, `--issue <n>` is replaced by `--url <run_url>`. When `run_url` is also null (as for `stale`, `read-failed`, `config-invalid` and `state-corrupt`), the URL is `https://github.com/<repo-slug>/actions/workflows/dependency-audit.yml`. Whether #2125 accepts `--url` is a cross-issue requirement on #2125 and must be disclosed in the PR body (AD-20).

**Body file.** The body is written 0600 into `tempfile.mkdtemp()` (which honours `$TMPDIR`) and removed afterwards. It contains the cause, sub, fingerprint, tracking issue or URL, `since`, and the `clear_act` sentence. It is plain ASCII with no `@`, and the token values have already been validated.

**Invocation.** It runs through `Deps.run_notifier(argv, timeout=30)`: `subprocess.run`, `stdin=DEVNULL`, output captured and discarded except a 2 KiB tail kept for the log.

**Subprocess environment** *(security round 1, L-4, binding)*. Neither runner inherits the consumer's environment. Both pass `env=` built from an allowlist: `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, and every `HOS_*` name **except** any whose name contains `TOKEN`, `SECRET`, `KEY` or `PASSWORD`; plus, when #2125 lands, the variables its header documents, added by name (none today). `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN` and `GITHUB_ENTERPRISE_TOKEN` are never passed to `notify_human.sh`. `run_escalation` gets the same allowlist **plus** `GH_TOKEN`, because `escalate_to_human.sh` writes to GitHub. hos-cron's own `check_error` notifier call (§15.8) uses `env -i` with the same allowlist.

**Results:**

| Result | `alert.status` / reason |
|---|---|
| rc 0 | `sent` |
| path missing | `undelivered` / `absent` |
| exists, but not a regular file or not `os.access(X_OK)` | `undelivered` / `not-executable` |
| rc ≠ 0 | `undelivered` / `exit-<rc>` |
| `TimeoutExpired` | `undelivered` / `timeout` |
| `OSError` on spawn | `undelivered` / `spawn-error` |

After any `undelivered`, the module re-writes the hold file with `alert.status`, `reason` and `at`, and prints `EVENT alert-undelivered`. Nothing else changes: the hold stands (AC-39).

**Fallback (Q-D5-5, PENDING THE HUMAN; designed for recommendation (a)).**

- **Fallback target (architect R-B, 2026-10-20):** the record's numeric `issue` if there is one, else the cache's `last_issue` (§15.5), else none.
- On `undelivered` with a fallback target, the module calls `Deps.run_escalation([<repo-root>/bootstrap/escalate_to_human.sh, --number, <target>, --body-file, <path>, --reason, dependency-audit-alert-undelivered, --app, worker], timeout=60)` **once per fingerprint**. That happens when `alert.fallback` is not already `posted`.
- The body is stable for the fingerprint: it contains no `at` or `last_evaluated`. The script's own idempotency key therefore also dedups.
- The results are rc 0 = `posted` and anything else = `failed`. A failed fallback is retried with the hourly alert retry. With no fallback target, the fallback is `not-applicable`, and the held line shows it: `alert=undelivered:<reason>` is followed by ` fallback=not-applicable` (the §15.8 `[HELD-DEPENDENCY]` regex already admits it). This residual is ADR §6 item 8 (H-D5-7) and must be disclosed in the Part 3 PR body.
- **If the human answers (b)**, the coder sets the module constant `FALLBACK_ENABLED = False` (status `disabled`). **If the human answers (c)**, Part 3 does not start until #2125 lands. **Part 3 coding must not start before Q-D5-5 is answered.**

**No Pushover client and no credential in this path** (AD-20).

### 15.8 `bin/hos-cron`: call site, predicate, directive and log line (Part 3; ADR AD-18, AD-19)

**Call site.** A new block, `# ── Build-hold gate (#1605 D-5) ──`, goes **after** the App-token mint (`:957` and its success check) and **before** the #1395 actionable-work gate (`:1126`). It runs for `ROLE == worker` only. The overseer is never held, and the overseer's cycle never invokes the consumer (TC-K6). Placing it before #1395 means every worker cycle that passes the usage gate logs its hold line, including cycles #1395 later skips as idle. A usage-paused cycle exits at `:484` first and logs `[PAUSED-USAGE]` instead.

**Predicate (scope, AD-18).**

~~`git ls-files --error-unmatch` on the checked-out tree~~ *(replaced, security round 1, M-2: it failed open on any git error and could be disabled by a branch that deletes the workflow)*. Binding, under `LC_ALL=C`:

1. ~~`git -C "$REPO_ROOT" rev-parse --verify --quiet 'origin/main^{commit}'` must exit 0. Otherwise **`check_error`**.~~ *(Architect ruling 2026-10-20, ADR AD-18 "missing-ref case": as written, this held every consumer whose default branch is not `main`.)* `git -C "$REPO_ROOT" show-ref --verify --quiet refs/remotes/origin/main`. rc 0 continues to step 2. **rc 1** means not configured: the same `not configured` line and `_BUILD_HOLD=0` as below. Any other rc is **`check_error`**. Residual R-13 (deleting the local ref turns the hold off until the next sync) is disclosed. Test: TC-K1c (no `origin/main` ref → not configured, the fake consumer is not invoked).
2. `git -C "$REPO_ROOT" cat-file -e 'origin/main:.github/workflows/dependency-audit.yml'`, with stderr captured:
   - rc 0 → configured; invoke the consumer.
   - rc 128 **and** stderr is exactly one line equal to `fatal: path '.github/workflows/dependency-audit.yml' does not exist in 'origin/main'` (measured 2026-10-20 on git 2.x) → not configured: `echo "$LOG_PREFIX [DEPENDENCY-AUDIT] not configured for this project (#1605)"`, `_BUILD_HOLD=0`, directive unchanged.
   - Anything else → **`check_error`** (held).

The checked-out branch never decides whether the hold applies.

**Invocation.**

- *(Security round 1, M-3(b).)* **First**, before any path is built from it, hos-cron checks `[[ "$PROJECT" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]`. On mismatch: `check_error`, the consumer is not invoked, no marker file is used, and the notifier is called (at most once per cycle).
- A bound array `_BH_BOUND` is built exactly as `_UP_BOUND` is: `timeout --kill-after=10 240`, or `gtimeout`, or empty if neither exists.
- *(Security round 1, H-1, binding; stricter than the finding's conditional form.)* **The consumer never runs from the working tree.** hos-cron always runs it from main's code:
  1. `_BH_CODE="$(mktemp -d)"` (under `$TMPDIR`, on disk), removed on every exit path of the block.
  2. `git -C "$REPO_ROOT" archive --format=tar origin/main -- "${_BH_CODE_PATHS[@]}" | tar -x -C "$_BH_CODE"` with `set -o pipefail`, where `_BH_CODE_PATHS=(scripts/__init__.py scripts/automation/__init__.py scripts/automation/lib scripts/automation/dependency_pause.py scripts/automation/dependency_audit_report.py)` is a constant. This extracts exactly main's committed bytes for the consumer and everything it imports. Uncommitted edits, untracked files and the checked-out branch cannot reach it. Because the extraction directory contains nothing else, a branch-added root module (for example a `json.py`) cannot shadow the stdlib either.
  3. Failure of `mktemp`, `archive` or `tar` (for example `origin/main` lacks the module) → **`check_error`**. The working-tree copy is never used as a fallback.
  4. The call is `_BH_OUT="$( (cd "$_BH_CODE" && ${_BH_BOUND[@]+"${_BH_BOUND[@]}"} python3 -E -s -m scripts.automation.dependency_pause check --project "$PROJECT" --repo-slug "$_REPO_SLUG" --state-dir "$_HOS_DIR" --repo-root "$REPO_ROOT") )"`, wrapped in the usage-pause `if …; then _BH_RC=0; else _BH_RC=$?; fi` shape. `-E` ignores `PYTHON*` variables and `-s` drops user site-packages. `-I` is still not used, because `-m` must resolve from the cwd (TV-3).
  - `--repo-root "$REPO_ROOT"` still locates `bootstrap/notify_human.sh` and `bootstrap/escalate_to_human.sh`. Those run from the working tree. **Residual R-12:** an unmerged branch's edit to those two scripts runs, but it cannot release a hold: the hold file is written before either runs (§15.7 ordering), and release only follows a qualifying clean run read by main's code.
  - A static test (TC-C18) asserts that every `scripts.` import reachable from `dependency_pause` resolves inside `_BH_CODE_PATHS`, so a new import cannot silently fall outside the extracted set.

**Parse (strict, `LC_ALL=C`).**

1. The last line must full-match `^DEPENDENCY-PAUSE decision=(run|hold) holds=([0-9]{1,2}) reading=(fresh|cached:[0-9]{1,6}|none)$`.
2. Every other line must full-match one of:
   - `^EVENT (dependency-pause-set|dependency-pause-cleared|alert-undelivered|dependency-advisory-realert)( (fingerprint|cause|sub|issue|run_url|previous_fingerprint|duration_s|reason)=[!-~]{1,300}){1,7}$` *(security round 1, L-1: the key alternation is the allowlist; any other key, including `event`, `role`, `project`, `cycle_id` or `timestamp`, fails the parse and is `check_error`; a key repeated in one line is also `check_error`)*
   - *(Security round 1, M-1(b): exact grammars replace `[ -~]{1,400}`.)* `^\[HELD-DEPENDENCY\] cause=(dependency-advisory|environment-broken) sub=(-|[a-z][a-z0-9_-]{0,31}) issue=(#[1-9][0-9]{0,8}|-) since=[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z alert=(sent|pending|undelivered:[a-z0-9-]{1,32})( fallback=(posted|failed|not-applicable|disabled))?$`
   - `^\[HELD-BUILD\] source=[a-z][a-z0-9-]{0,31} cause=[a-z][a-z0-9_-]{0,31} sub=(-|[a-z][a-z0-9_-]{0,31}) issue=(#[1-9][0-9]{0,8}|-) since=([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z|-) alert=(sent|pending|undelivered:[a-z0-9-]{1,32}|-)( fallback=(posted|failed|not-applicable|disabled))?$`
   - Bash `=~` is ERE without `REG_NEWLINE`, so `$` anchors the end of the string. Lines are split on `\n` first, and any line still containing `\r` or another control character fails.
3. The number of `[HELD-*]` lines must equal `holds`, and `decision=hold` ⇔ `holds ≥ 1`.

If `_BH_RC ≠ 0`, or any check fails, the result is **`check_error`**. Then:

- `_BUILD_HOLD=1`, `_BUILD_HOLD_LINES="[HELD-DEPENDENCY] cause=environment-broken sub=check_error issue=- since=<cycle start iso> alert=<…>"`.
- The cron notifier runs in-line: `"$REPO_ROOT/bootstrap/notify_human.sh" --cause environment-broken --url "https://github.com/$_REPO_SLUG/actions/workflows/dependency-audit.yml" --since <iso> --priority high --body-file <mktemp file>`. *(Security round 1, M-3(b), binding.)* The throttle marker is `$_HOS_DIR/build-hold-alert/$PROJECT.alerted` (only after `$PROJECT` validated). hos-cron creates `$_HOS_DIR/build-hold-alert` itself with `mkdir -p` then `chmod 0700`, and uses it only if `[[ -d $d && ! -L $d && -O $d ]]`. The notifier runs **only if** the marker is absent or older than 3600 s, and the marker is touched after the call. If the directory cannot be created or fails the check, the notifier is called without the throttle, at most once per cycle, and `$LOG_PREFIX WARN: build-hold alert throttle unavailable` is logged. With an invalid `$PROJECT`, no marker is used at all. Its result is mapped to `sent` or `undelivered:<absent|not-executable|exit-N|timeout>` with the §15.7 rules.
- The marker is removed on the next valid verdict.
- `_audit cycle-build-hold-check-error "role=$ROLE" "project=$PROJECT" "cycle_id=$HOS_CYCLE_ID" "rc=$_BH_RC"`.

**On a valid verdict:**

- each `EVENT <name> k=v…` line becomes `_audit <name> "role=$ROLE" "project=$PROJECT" "cycle_id=$HOS_CYCLE_ID" <k=v…>`, each pair one argument;
- each `[HELD-*]` line is echoed as `"$LOG_PREFIX <line>"` (AC-39: every held cycle);
- the summary is echoed as `"$LOG_PREFIX [DEPENDENCY-AUDIT] decision=… holds=… reading=…"`;
- `_BUILD_HOLD=1` iff `decision=hold`, and `_BUILD_HOLD_LINES` holds the `[HELD-*]` lines.

The cycle **continues** either way. The hold changes the directive. It does not exit the cycle, because triage and docs work proceed (AC-36).

**Directive (in `_build_context`, worker branch).**

- If `_OPEN_PR_NUMS` is non-empty, the existing `NEW WORK: BLOCKED` text is printed unchanged. When `_BUILD_HOLD=1`, one more line follows: `Build hold also active: <each [HELD-*] line, joined by "; ">`.
- Else if `_BUILD_HOLD=1`, it prints exactly:

```
NEW WORK: DOCS/DESIGN ONLY
Reason: build hold — <each [HELD-*] line, joined by "; ">.
Allowed this cycle: Step 0 triage; a docs-only or design-only step (changes only under docs/ and to DECISIONS.md; agent definitions, prompts and every other path are never docs-only); any step on the tracking issue named above, on #1504, or that records a dependency exemption or lands a dependency bump that clears the hold.
Not allowed: starting any other build (code) step. Clear act: <constant from _BH_CLEAR_ACT, by source>.
```

*(Security round 1, L-5 and M-1(c), binding.)* "Docs-only" means paths under `docs/` plus `DECISIONS.md`, and nothing else. `.claude/agents/*.md`, `AGENTS.md`, `bootstrap/*.md` and any other `*.md` are not docs-only. The clear-act sentence is a **constant table in hos-cron**, `_bh_clear_act()`, a `case` on the validated `source`: `dependency-audit` → the §15.6 `clear_act` sentence, verbatim; anything else → `See the tracking issue for this hold; hos-cron has no clear act for source <source> yet.` It is never read from a hold file or from the consumer's output. TC-K9 pins this.

- Else the existing `NEW WORK: ALLOWED` is printed.

**Prompt (Part 3, G-2).** `bootstrap/worker-cron-prompt.md` gains one bullet after `:73`: *"`NEW WORK: DOCS/DESIGN ONLY` → a build hold is active (#1605 D-5). Step 0 triage runs. Proceed to Step 2 only for an issue whose next step is docs-only or design-only (changes only under `docs/` and to `DECISIONS.md`), or one the directive's `Allowed this cycle` line names. Never start a code step. If no such issue exists, STOP. Do not try to clear the hold yourself, except through an issue the directive names. Any `NEW WORK:` value other than `ALLOWED` means: do not start a code step."* (The last sentence is architect G-2 condition (ii).) The directive is also self-describing, which covers the agent-definition parity gap (G-2) for this release.

**Residual (R-7, AD-19).** The hold is directive-level. Nothing in `submit_pr.sh` blocks a code PR while held. #2123 owns the backstop.

### 15.9 Test plan for D-5 (Part 3, except where marked Part 2; AC-43)

All tests are offline. No `~/.hos` access (`tmp_path` state dirs), no `gh`, no network.

**`tests/automation/test_dependency_audit_report.py`, measure and project.** `measure` is driven with a fake `--venv-bin` in `tmp_path`: `python` is a symlink to the oversight venv interpreter (skip-guarded like `_needs_gate`), and stub `pip` and `pip-audit` scripts print payloads, write files and record calls. `--attempt-timeout-seconds 2 --retry-sleep-seconds 0`.

| ID | Case | Asserts |
|---|---|---|
| TC-P1 | stub `python` prints `[3, 11, true]` | rc 1; `cause=interpreter-wrong`; the seven GITHUB_OUTPUT lines are present |
| TC-P2 | no `pip-audit` in venv-bin, and a stub `pip` that would report `install` non-empty (the realistic state, since pip-audit is a listed requirement) | rc 1; `cause=pip-audit-absent`; `pip` is never invoked; no stdout or stderr line matches `(?i)\b(GATE PASS\|PASS\|SKIP)\b\|^OK:` |
| TC-P3 | (pip-audit stub present in every sub-case, since step 3 now precedes the venv-match step) (a) `pip` exits 1; (b) `pip` rc 0 with a report where `install` is non-empty; (c) `pip` absent | `venv-mismatch` ×3 |
| TC-P4 | `--venv-build-outcome failure` | `venv-build-failed`; `pip-audit` is never invoked |
| TC-P5 | `pip-audit` sleeps 5 s on every attempt | `timeout`; 3 invocations recorded |
| TC-P6 | (a) rc 1 and no `-o` file (TV-15); (b) rc 0 with a garbage file; (c) unparseable, then a timeout | `unparseable` ×3 |
| TC-P7 | (a) rc 3; (b) a file over `MAX_INPUT_BYTES` | `pip-audit-failed`; `oversized` |
| TC-P8 | `--logic-path` stub exits 2 with stderr `GATE FAIL: exemption roster invalid — x` | `roster-invalid` |
| TC-P9 | stub exits 2 with another stderr; stub sleeps past 60 s (monkeypatched timeout) | `filter-error` ×2 |
| TC-P10 | **AC-32, roster only:** black ×2 + mcp CVE-2026-59951 at the roster versions, real logic | rc 0; `verdict=0 kept=0`; the artifact has no vulns; the filter's `OK:` line is echoed |
| TC-P11 | **AC-32, expired:** `project_audit` in-process, same fixture, `today = expiry + 1 day` | kept ≥ 1 (black); `first` is a black id |
| TC-P12 | **new advisory:** `requests 2.0.0 CVE-2099-0001` plus the roster fixture, real logic | rc 0; `verdict=1 kept=1 first=CVE-2099-0001`; the artifact contains only `CVE-2099-0001` |
| TC-P13 | TV-14 skip entry plus a clean audit | rc 1; `partial-audit`; the filter output is withheld; no `OK:` line |
| TC-P14 | skip entry plus a new advisory | rc 0; `verdict=1 partial=1` |
| TC-P15 | stub logic exits 0 while the projection keeps 1 | `projection-mismatch` |
| TC-P17 | *(L-2)* verdict 1: (a) stub filter prints the header `GATE FAIL: 2 …` and two kept lines while the projection keeps one; (b) same counts but a different id; (c) header N ≠ kept-line count; (d) no header | `projection-mismatch` ×4 |
| TC-P18 | *(L-3(b))* a projection `first` of `x\ny` (stub `project` writing a crafted summary) | all seven GITHUB_OUTPUT values are the safe defaults; rc 1 |
| TC-P19 | *(L-3(c))* stub filter stdout contains `::error::forged` and `##[group]x` | those texts appear only between one `::stop-commands::<t>` line and `::<t>::`, each prefixed with two spaces; `<t>` is 32 hex and differs between two runs |
| TC-W7 | *(architect 2026-10-20, AD-16 transport bound)* the worst-case record (every field at maximum; 100 ids of 65 bytes each, matching `VULN_ID_RE`; `more=1`) built by the extracted `outcome` script is at most 8192 bytes and is accepted by `parse_record` | — |
| TC-P20 | *(G-4)* 101 distinct kept ids | `ids` has 100 sorted entries and `more=1`; 3 kept ids incl. one malformed → `ids=<a>,<b>,unattributable` sorted |
| TC-P16 | argv dispatch: `measure`/`project` vs the §9.7 argv | the existing CLI cases still pass; `--pip-audit-json` alone is never treated as `measure` |

**Workflow static (extends §7.3; PyYAML).**

| ID | Asserts |
|---|---|
| TC-W1 | three jobs exist (`audit`, `report`, `outcome`); `report.needs == "audit"` and `report` has no `if` |
| TC-W2 | the `audit` step with `id: venv` has `continue-on-error: true`; `measure` has `if: always()`; the `measure` `run` contains `--python-version` equal to setup-python's version; the upload step's `if` is `steps.measure.outcome == 'success'` |
| TC-W3 | the `audit` outputs are the seven names; `report.outputs.issue` references `steps.reconcile.outputs.issue` |
| TC-W4 | the workflow text contains none of `--logic-path`, `--attempt-timeout-seconds`, `--retry-sleep-seconds`, `HOS_PIP_AUDIT_BIN` |
| TC-W5 | `outcome`: `permissions == {}`, `needs == ["audit", "report"]`, `if == "always()"`, no step has `uses`, the single `run` has no `${{`, and exactly one `::notice::` occurs in it |
| TC-W6 | the `ID` alternation in `outcome`'s script equals `dependency_audit_report.VULN_ID_RE` |

**Outcome mapping (TC-O\*, in the same file).** The `outcome` job's `run` script is extracted with PyYAML and executed with `bash` and an explicit `env`, with no network.

| ID | Asserts |
|---|---|
| TC-O1..TC-O5 | one per §15.3 mapping row. Asserts the exact record line printed after `::notice::` and the exit code (0 only for clean). |
| TC-O6 | invalid `FIRST` (`x y`), invalid `KEPT` (`-1`) → `sub=audit-output-invalid` |
| TC-O7 | invalid `SHA` → exit 1 with no `::notice::` |
| TC-O9 | *(L-3(a), G-4)* `FIRST` containing a newline; `IDS` with a space or an unsorted list is passed through only if it matches the `IDS` pattern (sortedness is the consumer's check) | control char → `audit-output-invalid`; the record carries `ids=`/`more=` for a finding and `-`/`0` otherwise |
| TC-O8 | `AUDIT_RESULT=failure CAUSE=pip-audit-absent` → `sub=pip-audit-absent`; `AUDIT_RESULT=cancelled` with empty `CAUSE` → `sub=audit-failed` |

**`tests/automation/test_dependency_pause.py` (new).** All cases use fake `Deps`.

Read helpers (TC-R\*), with `_run_gh` mocked as in `test_github.py`:

| ID | Asserts |
|---|---|
| TC-R1 | each helper's exact endpoint string and the `retries=` it is passed |
| TC-R2 | a 200 empty list returns `[]`; a wrong shape raises `GitHubError` |
| TC-R3 | bad inputs (a `bool` id, 0, a branch with a space, `x.txt`) raise `ValueError` with **no** `_run_gh` call |

Consumer (TC-C\*):

| ID | Asserts |
|---|---|
| TC-C1 | finding record, no file → file 0600 in a 0700 dir, every schema field present, `EVENT dependency-pause-set`, decision hold |
| TC-C2 | finding fingerprint `dependency-audit:dependency-advisory:CVE-2099-0001` |
| TC-C3 | not_run fingerprint `dependency-audit:environment-broken:pip-audit-absent` |
| TC-C4 | same fingerprint on the next cycle → `since` unchanged, no EVENT, no notifier call |
| TC-C5 | clean record → file deleted, `EVENT dependency-pause-cleared duration_s=<now − held_since>`, decision run |
| TC-C6 | file deleted by hand, record still a finding → rewritten, with a new `since` |
| TC-C7 | newest qualifying run started 216 h + 1 s ago → `stale`; at exactly 216 h → not stale |
| TC-C8 | no runs, and only non-qualifying runs → `stale` |
| TC-C9 | `HOS_DEPENDENCY_AUDIT_MAX_AGE_HOURS` ∈ {167, 337, abc, "", 0168x} → `config-invalid` and no reads; 168 and 336 are accepted |
| TC-C10 | a newer `workflow_dispatch` run on a non-main branch carrying a forged `clean` is ignored; `push` events are ignored; a path mismatch is ignored |
| TC-C11 | `record-invalid` for: zero matching annotations; two; `sha ≠ head_sha`; non-ASCII; 8193 bytes; a valid record cut short anywhere (→ `sub=record-truncated`, held; architect 2026-10-20); `clean kept=1`; `finding first=-`; level `warning`; zero or two outcome jobs; a foreign `check_run_url` host |
| TC-C12 | conclusion `cancelled`, `timed_out` or `null` → `run-incomplete` |
| TC-C13 | read failure with a 5 h 59 m cache → cached reading used (`reading=cached:<age>`); with a 6 h 1 s cache, or no cache → `read-failed`; `READ_FAILED_HOLDS=False` → run |
| TC-C14 | corrupt own file → `state-corrupt` hold and file rewritten; a corrupt `pipeline-blocked.json` → `[HELD-BUILD] … state-corrupt` and the file untouched; a valid `pipeline-blocked.json` plus a clean dependency run → decision hold, that file untouched |
| TC-C15 | fingerprint change → new `since`, `held_since` kept, `previous_fingerprint` in the EVENT, notifier called again |
| TC-C16 | hold dir is a symlink, or owned by another uid (monkeypatched `geteuid`) → `state-corrupt`, with no write |
| TC-C18 | *(H-1)* static: every `scripts.` import reachable from `dependency_pause` (AST walk) resolves to a file inside hos-cron's `_BH_CODE_PATHS` | — |
| TC-C19 | *(G-4, re-alert while held)* held on `first=CVE-A`, `alerted_ids=[CVE-A]`; next record `ids=CVE-A,CVE-B` (same fingerprint) | `EVENT dependency-advisory-realert`; one notifier call `--cause dependency-advisory`; `since` unchanged; `alerted_ids=[CVE-A,CVE-B]` |
| TC-C20 | *(G-4, swap)* `alerted_ids=[CVE-A,CVE-B]`, kept 2; next record `ids=CVE-A,CVE-C`, kept 2 | re-alert (count unchanged, set changed); then a record `ids=CVE-A` (shrink) and a repeat of `CVE-A,CVE-C` → no notifier call; overflow `more=1` with `kept` growing past `kept_at_alert` → re-alert |
| TC-C21 | *(M-3(a))* each of `<state-dir>`, `build-hold`, `<project>` in turn: a symlink; group-writable (0o775); owned by another uid (monkeypatched); the own file a symlink to a valid hold; the cache a FIFO or group-readable; a cache with an extra key, a future `read_at`, or a `record` failing §15.4 | `state-corrupt` in every case; nothing written through the bad component; a missing `build-hold` is created 0700 |
| TC-C22 | *(M-1(a))* a `pipeline-blocked.json` with `cause` = `x; rm -rf /`, `issue` = `"12"` (string) or `true`, `since` with a newline, or `alert.reason` 33 chars | `[HELD-BUILD] source=pipeline-blocked cause=environment-broken sub=state-corrupt …` re-rendered; no byte of the bad value in stdout |
| TC-C23 | *(L-3(d))* selected run `run_started_at` = now + 301 s; and = now + 299 s | `run-invalid`; second is read normally |
| TC-C24 | *(L-1)* the stdout of every TC-C case | every EVENT key is in the allowlist; no key repeats |
| TC-A6 | *(L-4)* consumer env holds `GH_TOKEN`, `GITHUB_TOKEN`, `HOS_APP_KEY`, `HOS_PROJECT` | the notifier's `env` has none of the first three and has `HOS_PROJECT`, `PATH`, `HOME`; the escalation's `env` has `GH_TOKEN` and not `GITHUB_TOKEN` |
| TC-C17 | stdout contract: every line matches §15.8's parse regexes; the last line is the summary |

Alert (TC-A\*):

| ID | Asserts |
|---|---|
| TC-A1 | argv exactly AC-40 with `--issue 77`; with no issue, `--url <run_url>`; with no run either, the workflow URL |
| TC-A2 | **notifier absent (AC-39):** the hold file exists when the fake runner is checked; `alert=undelivered:absent` appears in the file and in the `[HELD-DEPENDENCY]` line; `EVENT alert-undelivered` |
| TC-A3 | not executable; `exit-3`; `timeout`; `spawn-error` → those reasons |
| TC-A4 | undelivered at T; a cycle at T+59 m → no call; T+60 m → exactly one call |
| TC-A5 | fallback (Q-D5-5 = a): undelivered with issue 77 → `escalate_to_human.sh` argv exact, once per fingerprint; (R-B) a `not_run` record with `issue=-` and a cache `last_issue=77` → escalation on 77; no issue and no `last_issue` → `fallback=not-applicable` in the file and the held line, no call; a second cycle makes no call; a failed fallback leaves the hold unchanged; `FALLBACK_ENABLED=False` → `disabled`, no call |

**`tests/automation/test_hos_cron.py` (modify; TC-K\*).** These cases use the file's existing harness. The fake consumer is a `scripts/automation/dependency_pause.py` **committed** in the test's fake `REPO_ROOT` git repo and pointed to by `refs/remotes/origin/main` (`git update-ref`), together with the workflow file where the case needs it, because hos-cron extracts the consumer from `origin/main` (H-1). It is a real module path, not an env seam. It prints a scripted stdout and exit code.

| ID | Asserts |
|---|---|
| TC-K1 | workflow not tracked → the fake is never invoked; `[DEPENDENCY-AUDIT] not configured for this project (#1605)`; directive `NEW WORK: ALLOWED` |
| TC-K2 | **AC-36:** fake prints a hold → context contains `NEW WORK: DOCS/DESIGN ONLY`, the `Allowed this cycle:` line naming docs-only/design-only steps, and `Not allowed: starting any other build (code) step`; the log has the `[HELD-DEPENDENCY]` line. This is directive-level only (R-7). |
| TC-K3 | the fake exits 1, prints garbage, or prints no summary; and (separately) the bound kills it → `sub=check_error` in the log, `DOCS/DESIGN ONLY`, `_audit cycle-build-hold-check-error`, `alert=undelivered:absent` with the notifier absent; a second run inside an hour makes no notifier call |
| TC-K4 | fake prints `decision=run` → `NEW WORK: ALLOWED` and `[DEPENDENCY-AUDIT] decision=run` |
| TC-K5 | open PR plus hold → `NEW WORK: BLOCKED` text unchanged, plus `Build hold also active:` |
| TC-K6 | `ROLE=overseer` → the fake is never invoked; no `NEW WORK:` line (the existing assertion holds) |
| TC-K1b | *(M-2)* (a) `origin/main` ref missing; (b) `.git/index.lock` held and a corrupt object for the workflow blob; (c) the workflow present on `origin/main` but deleted on the checked-out branch | (a), (b) → `sub=check_error`, `DOCS/DESIGN ONLY`, fake not invoked; (c) → configured, fake invoked |
| TC-K8 | *(H-1)* checked-out branch whose working-tree `dependency_pause.py` (modified, uncommitted; and separately committed on the branch) prints `decision=run` and touches a marker, while `origin/main`'s prints a hold | the branch copy is **never** invoked (marker absent); the `origin/main` copy's hold is used. Variant: `origin/main` lacks the module → fake not invoked, `sub=check_error`. Variant: a branch-added root `json.py` that touches a marker → marker absent |
| TC-K9 | *(M-1(c), L-5)* fake prints a `[HELD-BUILD] source=pipeline-blocked …` line | directive's `Clear act:` is the constant for unknown sources, not any text from the fake; the `Allowed this cycle` line says changes only under `docs/` and to `DECISIONS.md` |
| TC-K10 | *(M-1(b), L-1, M-3(b))* fake prints a `[HELD-DEPENDENCY]` line with an extra field, a `[HELD-BUILD]` line with `cause=Bad`, an EVENT with key `role=x`, or `\r`; separately `PROJECT=../x` | `check_error` each time; for `../x` no path under `$_HOS_DIR` containing `..` is created and the notifier is called once |
| TC-K7 | EVENT lines become `_audit` records with those names |

**Human acceptance tests (mandatory; AC-33, AC-43).**

- **TC-H1: pip-audit absent ⇒ NOT_RUN, pause set, alert fired, no pass line.** One test function chains the three real components offline:
  1. `measure` with a venv-bin lacking `pip-audit` → rc 1, `MEASURE verdict=- cause=pip-audit-absent …`, GITHUB_OUTPUT `cause=pip-audit-absent`.
  2. The extracted `outcome` script with `AUDIT_RESULT=failure` and those outputs → the record `hos-dependency-audit/1 outcome=not_run cause=environment-broken sub=pip-audit-absent first=- kept=0 issue=- ids=- more=0 sha=<40 hex>`, exit 1.
  3. `dependency_pause.main` with fake reads returning one qualifying run (head_sha = that sha), one outcome job, and that record as a notice annotation, plus a recording notifier → the hold file is written with fingerprint `dependency-audit:environment-broken:pip-audit-absent`; the notifier is invoked once with `--cause environment-broken … --priority high`; stdout has `[HELD-DEPENDENCY] cause=environment-broken sub=pip-audit-absent` and `decision=hold`.
  4. Across all captured stdout and stderr of steps 1–3: **no** line matches `(?i)\bGATE PASS\b|\bPASS\b|\bSKIP\b|^OK:`.

  Variant **TC-H1b**: the same chain with the notifier absent → `alert=undelivered:absent`, `EVENT alert-undelivered`, and the hold is still set.
- **TC-H2: new advisory ⇒ issue + pause + `dependency-advisory` alert.**
  1. TC-P12's measure.
  2. The artifact is fed to `dependency_audit_report` CLI `--dry-run` with the recording writer → the planned issue body lists `CVE-2099-0001` and **not** black or mcp.
  3. `outcome` with `REPORT_RESULT=success ISSUE=77` → `finding … first=CVE-2099-0001 kept=1 issue=77 ids=CVE-2099-0001 more=0`.
  4. Consumer → hold; notifier `--cause dependency-advisory --issue 77`.

**AC-43 coverage:**

| AC-43 item | Test |
|---|---|
| absent pip-audit | TC-H1 |
| new advisory | TC-H2 |
| roster only, no pause | TC-P10 + TC-O3 + TC-C5 (clean record) |
| expired, pause | TC-P11 + TC-C2 |
| clean clears | TC-C5 |
| notifier absent | TC-A2, TC-H1b |
| stale | TC-C7, TC-C8 |
| docs-only proceeds while paused | TC-K2 |

**Part 2 test deltas:** §15.1.3 (g2, g4, g6 rewrite, g7), and §7.1/§7.2 as annotated.

### 15.10 Runbook and the AC-42 day-one check (Part 3)

**`docs/OVERSIGHT-RUNBOOK.md` edit (e)** is a new subsection, "Build hold from the scheduled dependency audit (#1605 D-5)". It states:

- (i) what holds, and where the state lives (`~/.hos/build-hold/<project>/dependency-audit.json`);
- (ii) that deleting the file does nothing;
- (iii) the clear act (§15.6);
- (iv) the sub-token table from §15.2 and §15.5, each with its operator action;
- (v) the 216 h staleness rule and the env override range;
- (vi) **the token precondition** (folded in from `CRON-SETUP.md`, AD-23 shed step 2): the Worker App needs `actions: read` and `checks: read`, and without them every cycle holds with `read-failed`. Granting them is a human act;
- (vii) **"dispatch immediately after merge"** (R-10);
- (viii) that the overseer is never held;
- (ix) that until #2125 lands, alerts show `undelivered:absent`, and the Q-D5-5 fallback is the visible channel.

**AC-42 day-one procedure (binding on the worker before the Part 3 PR is marked ready).** The workflow cannot be dispatched before it is on main (AD-11: no non-default ref). Day one is therefore measured locally, through the **same** code path:

1. Search first: `bootstrap/`, `scripts/` and `bin/` for an existing way to provision Python 3.12 (for example `uv`). If one exists, create a **fresh** venv with Python 3.12 under `mktemp -d`. Install `scripts/oversight/requirements.txt` with `pip install -r`, which needs network. Then run `python3 -m scripts.automation.dependency_audit_report measure --venv-bin <fresh>/bin --python-version 3.12 --requirements scripts/oversight/requirements.txt --venv-build-outcome success --out-json <tmp>/a.json --github-output <tmp>/o.txt`.
2. If no Python 3.12 is available (this host has only 3.14.4), run step 1 with the newest available interpreter and its `--python-version`. **Disclose** in the PR body that CI resolves under 3.12 and that resolution can differ by interpreter markers.
3. Paste into the PR body: the `MEASURE` line, the filter's roster lines, and either "clean: no hold on merge except R-10's `stale` until the first dispatch" or the exact kept advisories that would hold the pipeline on merge.
4. After merge: the operator dispatches the workflow, and the PR thread records the first worker cycle's `[DEPENDENCY-AUDIT]` line. A `read-failed` there means the token precondition, item (vi).

TV-13 (this venv, 3.14, 116 dependencies, 0 skipped, clean through `filter`) is the evidence that the roster covers today's advisories. It is not a substitute for step 3.

### 15.11 Part 2 and Part 3: file lists and commit plans (AD-22, AD-23; replaces §12)

**The vehicle is pending the human (Q-D5-1).** These lists implement AD-23's recommendation. If the human instead picks one larger Part 2, these lists merge into one, roughly 26 files, which needs an explicit size waiver. That is not designed further here.

**Part 2: the gate split, re-cut on current main. 11 files (≤15).**

| # | File | Section |
|---|---|---|
| 1 | `scripts/oversight/gates/security_scan.sh` | §3 + rebase box, §15.1.2 |
| 2 | `scripts/oversight/gates/dependency_audit.sh` (new) | §4.1–§4.3, §15.1.1 |
| 3 | `.github/workflows/oversight-gates.yml` | §10.1 (Edit 3 per AD-23 note) |
| 4 | `tests/oversight/test_scan_gates_empty_args.py` | §7.1 (TC-D1–D5 superseded) |
| 5 | `tests/oversight/test_gate_arg_grammar.py` | §7.2 |
| 6 | `tests/oversight/test_security_scan_exemptions.py` | §15.1.3 |
| 7 | `docs/specs/SPEC-375-deterministic-gate-invariant.md` | §11.1 |
| 8 | `docs/OVERSIGHT-RUNBOOK.md` | §11.2 (a)–(c) |
| 9 | `docs/CI-EXECUTION-INVENTORY.md` | §11.3 (Part 2 wording) |
| 10 | `DECISIONS.md` | §11.4 (with the D-5/AD-23 note) |
| 11 | `SCRIPTS-INDEX.md` (regenerated) | §11.5 (two gate lines) |

Part 2 commits (≤10; planned 6). Each commit leaves `run_tests_inner_loop.sh` green.

1. `fix(#1605): bandit's verdict comes from the file it wrote, never the stream it decorated`. Covers `security_scan.sh`: the bandit lane, kind filter, seam and `--`, plus rebase items 1, 2 and 4. The pip-audit lane is still present. Also `test_scan_gates_empty_args.py` (TC-S1–S17 bandit cases), `test_gate_arg_grammar.py` (the `KIND_FILTER_GATES` row) and `test_security_scan_exemptions.py` (the g6 rewrite).
2. `feat(#1605): dependency_audit.sh carries main's pip-audit lane, with the #1776 roster, verbatim`. Covers the new gate, the lane removed from `security_scan.sh` (rebase item 3), the `test_security_scan_exemptions.py` retarget and g7, `test_scan_gates_empty_args.py` (AD-2a cases, TC-D6–D8) and `test_gate_arg_grammar.py` (TC-G9, TC-G10, docstring).
3. `ci(#1605): oversight-gate-security-scan job (file-scoped, wired, not required)`. Covers `oversight-gates.yml` (Edits 1–4, SEC-M2, SEC-S1) and the TC-S18 static test in `test_scan_gates_empty_args.py`.
4. `docs(#1605): gate→key registries for the split`. Covers SPEC-375, the runbook (a)–(c) and the CI inventory.
5. `docs(#1605): DECISIONS entry for the gate split`.
6. `chore(#1605): regenerate SCRIPTS-INDEX`.

The S-6 waiver goes unused, and it does not transfer (AD-23 corollary).

**Part 3: scheduled audit plus D-5. 15 files (= the ceiling; no shed possible, G-1).**

| # | File | Section |
|---|---|---|
| 1 | `.github/workflows/dependency-audit.yml` (new) | §10.2 + §15.3 |
| 2 | `scripts/automation/dependency_audit_report.py` (new) | §9 + §9.7 tracking line + §15.2 |
| 3 | `scripts/automation/lib/github.py` | §8 + §15.5 |
| 4 | `tests/automation/test_dependency_audit_report.py` (new) | §7.3 + TC-P\*, TC-W\*, TC-O\*, TC-H2 |
| 5 | `scripts/automation/dependency_pause.py` (new) | §15.5–§15.7 |
| 6 | `tests/automation/test_dependency_pause.py` (new) | TC-R\*, TC-C\*, TC-A\*, TC-H1 |
| 7 | `bin/hos-cron` | §15.8 |
| 8 | `tests/automation/test_hos_cron.py` | TC-K\* |
| 9 | `bootstrap/worker-cron-prompt.md` | §15.8 prompt bullet (G-2) |
| 10 | `scripts/framework/protected_surfaces.txt` | exact-path `scripts/automation/dependency_pause.py` (AD-18) |
| 11 | `.github/CODEOWNERS` (regenerated by `gen_codeowners.sh`) | — |
| 12 | `docs/AGENT-IDENTITY.md` | §9 list gains `scripts/automation/dependency_pause.py  (build-hold release path, #1605)` (G-3) |
| 13 | `docs/OVERSIGHT-RUNBOOK.md` | §11.2 (d) + §15.10 (e) |
| 14 | `docs/CI-EXECUTION-INVENTORY.md` | §11.3 Part 3 row rewrite |
| 15 | `SCRIPTS-INDEX.md` (regenerated) | §11.5 (two automation lines) |

Not in Part 3: `DECISIONS.md` (prospective in Part 2, §11.4) and `docs/CRON-SETUP.md` (folded into the runbook (vi), AD-23 shed step 2). TC-H1 sits in file 6 and carries its own few-line PyYAML extractor for the `outcome` script. Test files do not import each other, and no conftest is added. **If the inner-loop suite shows that any further file must change** (for example a workflow registry test), that is a 16th file. The worker stops and escalates to the human as a waiver question (AD-23). It does not split Part 3.

Part 3 commits (≤10; planned 7):

1. `feat(#1605): github.py REST-by-id issue writes and Actions-run reads`. Covers `github.py` and the write-helper tests in `test_dependency_audit_report.py`.
2. `feat(#1605): dependency_audit_report — reconcile, measure and project`. Covers the module and its tests (§7.3, TC-P\*).
3. `ci(#1605): scheduled dependency audit — audit, report, outcome`. Covers the workflow and TC-W\*/TC-O\*/TC-H2.
4. `feat(#1605): dependency_pause — host build hold, derived from the scheduled outcome`. Covers the module, `test_dependency_pause.py` (TC-R\*, TC-C\*, TC-A\*, TC-H1), `protected_surfaces.txt`, CODEOWNERS and AGENT-IDENTITY.
5. `feat(#1605): hos-cron honours the build hold (DOCS/DESIGN ONLY)`. Covers `bin/hos-cron`, `test_hos_cron.py` and `worker-cron-prompt.md`.
6. `docs(#1605): runbook and CI inventory for the scheduled audit and hold`.
7. `chore(#1605): regenerate SCRIPTS-INDEX`.

Both PRs touch protected surfaces, so both need human approval for merge regardless of tier. Part 3's merge also carries the Q-D5-4 clearance question (ADR Q-D5 dispositions).

### 15.12 Traceability (AC-32..AC-43) and the departures this section makes

| AC | Design element | Tests |
|---|---|---|
| AC-32 | §15.2 steps 6–9 (filter rc is the verdict; `project` loads the module by path; consistency check) | TC-P10, TC-P11, TC-P12, TC-P15 |
| AC-33 | §15.2 cause table; §15.3 mapping; §15.6; §15.7 | TC-H1, TC-H1b, TC-P1–TC-P9, TC-O8 |
| AC-34 | §15.3 (`report` runs on verdict 1; `finding` record); §15.6 incl. "G-4 resolution" (set-based re-alert); §15.7 | TC-H2, TC-C1, TC-C2, TC-C19, TC-C20 |
| AC-35 | §15.6 host state under `~/.hos/build-hold/`; §15.8 call site every worker cycle | TC-C\*, TC-K1–TC-K7 |
| AC-36 | §15.8 directive + prompt bullet | TC-K2 (directive-level; R-7) |
| AC-37 | §15.6 `plan_transition` clean row; `clear_act` | TC-C5, TC-C6 |
| AC-38 | §15.5 rule 2 (216 h; [168, 336]; `config-invalid`) | TC-C7, TC-C8, TC-C9 |
| AC-39 | §15.7 ordering and undelivered; §15.8 log line and `check_error` alert | TC-A2–TC-A5, TC-K3, TC-H1b |
| AC-40 | §15.7 argv | TC-A1 |
| AC-41 | §15.6 fingerprint; the shared reader for #2123 | TC-C2, TC-C3, TC-C14 |
| AC-42 | §15.10 procedure + PR body | PR-body review |
| AC-43 | §15.9 coverage table | all of §15.9 |
| AC-25 (amended) | §15.2 (`measure` exits 1 on every cause); §15.3 | TC-P\*, TC-O\* |

**Departures** (all additive or clarifying; none reverses AD-15..AD-23):

| ID | Kind | Departure | Reason |
|---|---|---|---|
| TD-D5-1 | additive | sub tokens beyond the ADR's list: `venv-build-failed`, `interpreter-wrong`, `pip-audit-absent`, `venv-mismatch`, `timeout`, `pip-audit-failed`, `oversized`, `filter-error`, `projection-mismatch`, `run-incomplete`, `config-invalid`, `audit-output-invalid`, `state-corrupt` | each AC-33 condition needs a named cause |
| TD-D5-2 | clarifying | a finding with skipped dependencies stays a `finding` (with `partial-audit`), not a `not_run` | downgrading it would skip `report` and hide a real advisory's issue write. The hold is set either way, so AD-21 still holds: a partial audit is never `clean`. |
| TD-D5-3 | additive | the measurement is `measure`/`project` modes of `dependency_audit_report.py`, not a new file | budget (§15.11); a copy of the logic is still forbidden |
| TD-D5-4 | clarifying | `since` resets on a fingerprint change, and `detail.held_since` keeps the hold start | AD-18 says `since` is kept "while the fingerprint is unchanged". The cleared duration must cover the whole hold (AC-37). |
| TD-D5-5 | additive | a corrupt own file holds for one cycle, then is re-derived | AD-18's "corrupt means held", made finite for a file this module owns |
| TD-D5-6 | clarifying | the consumer calls the read helpers with `retries=1` | keeps the 240 s hos-cron bound |
| TD-D5-7 | additive | the artifact is the roster-filtered projection | D-5 item 3; otherwise a clean run sits next to an issue listing exempted advisories |
| TD-D5-8 | clarifying | `.claude/agents/worker.md` parity is not in Part 3 | G-2 |
| TD-D5-9 | additive | the `outcome` job exits 1 on non-clean | a visible red run; the consumer ignores the conclusion for record selection |
| TD-D5-10 | clarifying | `DEFAULT_BRANCH = "main"` is a constant, not a 4th read | only HOS tracks the workflow (AD-18 scope); any other default branch reads `stale`, which is loud |

### 15.13 Gaps returned to the architect

> **Ruled 2026-10-20 (ADR §2b, "Architect rulings on TD §15.13").** G-1: decided, no shed exists, and a 16th file is a human waiver. G-2: deferral accepted, on two conditions: a follow-up issue linked in the Part 3 PR body, and the prompt bullet's fail-closed sentence (§15.8). G-3: both removals confirmed. G-4: ~~a human/product question (ADR §6 item 9). §15.6 implements AC-41 as written until it is answered.~~ **Resolved by pm-agent's ruling (REQUIREMENTS AC-34/AC-41/AC-43, commit `ebadd5397`) and implemented in §15.6 "G-4 resolution" (set-based `alerted_ids`; TC-C19, TC-C20).** G-5: aligned, no change. The review also produced two findings, both edited into this TD. R-A: the presence check now runs ahead of the venv-match step (§15.2). R-B: the fallback falls back to `last_issue` (§15.5, §15.7), with the residual in ADR §6 item 8.

- **G-1 (ADR AD-23 shed step 1 cannot apply).** `SCRIPTS-INDEX.md` is pinned by `tests/framework/test_scripts_index.py`. Both Part 3 automation modules are under `scripts/**`, so it must be regenerated in Part 3 and cannot become a follow-up. Part 3 is therefore at exactly 15 with **no** shed headroom. Request: amend AD-23's shed order to name the real first shed, if any, or record that the next file over is a human waiver question. §15.11 already states the latter.
- **G-2 (the directive's readers).** AD-23's Part 3 list omits `bootstrap/worker-cron-prompt.md`, which enumerates the directive values (`:73–76`). Without it, a third value is undefined behaviour for the agent. It is added as file 9. `.claude/agents/worker.md` (`:321–346`) also enumerates them. It is an agent definition, and CLAUDE.md says those edits are authored by the top-level session, not `coder`. Adding it would also make 16 files. The design makes the directive self-describing (§15.8) and defers `worker.md` parity to a follow-up. Request: the architect confirms the deferral, or rules that `worker.md` must ship with Part 3. The second option is a human waiver (16 files).
- **G-3 (protected-surface mirror).** AD-18 adds an exact-path protected surface. The #1776 precedent (`test_t3`) shows `docs/AGENT-IDENTITY.md` §9 mirrors exact-path entries, so it is added as file 12. `DECISIONS.md` (prospective in Part 2) and `CRON-SETUP.md` (folded into the runbook) leave Part 3 to keep the count at 15. Request: confirm both removals.
- **G-4 (fingerprint granularity, product-adjacent). RESOLVED — see the ruling box above and §15.6 "G-4 resolution".** AC-41 fixes the fingerprint to the **first** kept advisory id. A second new advisory that arrives while held, sorting after the first, does not change the fingerprint, so it does not re-alert. The tracking issue still gets `report`'s delta comment (AC-22), so it is visible but not pushed. Request: confirm this is acceptable, or route to pm-agent to widen AC-41. Changing it is a one-function change (`fingerprint`).
- **G-5 (I-7 cache window).** AD-17's 6 h cache means a GitHub outage longer than 6 h holds build work (Q-D5-6). Nothing to change unless the human rejects I-7. This is noted so the architect's Q-D5-6 disposition and §15.5's `READ_FAILED_HOLDS` constant stay aligned.


### 15.14 Security review round 1 (2026-10-20) and G-4: disposition record

Source: `security-reviewer`, ADR §2b + TD §15 @ `0a94eb9c6` (CHANGES_REQUESTED, iteration 1); pm-agent G-4 ruling @ `ebadd5397`. Every finding's required text is applied verbatim or stricter, in place, marked *(security round 1, <id>)*.

| Finding | Applied in | Stricter than required? | Tests added |
|---|---|---|---|
| H-1 | §15.8 Invocation | Yes: the consumer **always** runs from a `git archive` extraction of `origin/main` (a superset of the "throwaway worktree" path), never from the working tree; extraction failure is `check_error`; `python3 -E -s` | TC-K8, TC-C18 |
| M-1 | §15.6 shared reader (validate every field, re-render); §15.8 parse (exact grammars); §15.8 directive (`_bh_clear_act()` constant table) | — | TC-C22, TC-K9, TC-K10 |
| M-2 | §15.8 Predicate (`rev-parse` + `cat-file -e` on `origin/main`; only the exact no-such-path stderr is "not configured") | — | TC-K1b |
| M-3 | §15.6 Directory (lstat + fstat every component, `dir_fd`, `O_NOFOLLOW`, 0700 on create, file mode `& 0o077 == 0`); §15.5 cache strict schema; §15.8 `$PROJECT` validated first, throttle marker in hos-cron-created `build-hold-alert/` | Files also must have no group/other bits | TC-C21, TC-K10 |
| L-1 | §15.6 stdout contract (key allowlist + per-key value patterns); §15.8 parse (key alternation; repeated key rejected) | — | TC-C24, TC-K10 |
| L-2 | §15.2 step 8 (`--summary` with `kept_ids`), step 9 (two-sided: header N = kept-line count = projection kept; id multisets equal). The filter **does** print per-advisory kept lines (`render`, two-space indent), so the line comparison applies. | — | TC-P17 |
| L-3 | (a) §15.4, §15.5 rule 4, §15.8 parse, §15.3 outcome validation: `re.fullmatch`, control characters rejected; (b) §15.2 `--github-output` per-key validation with safe defaults; (c) §15.2 `_echo_untrusted` stop-commands region + report step; (d) §15.5 rule 1 `run-invalid` | (c) uses both the stop-commands token **and** the two-space prefix plus control-char replacement | TC-P18, TC-P19, TC-O9, TC-C23 |
| L-4 | §15.7 Subprocess environment; §15.8 `env -i` for hos-cron's call | Also drops any `HOS_*` name containing TOKEN/SECRET/KEY/PASSWORD | TC-A6 |
| L-5 | §15.8 directive + prompt bullet: docs-only = `docs/` + `DECISIONS.md` | — | TC-K9 |
| G-4 | §15.2 (`ids`, `more` outputs), §15.3 (outcome carries them), §15.4 (record `ids=`/`more=`, 8192-byte bound), §15.6 (`alerted_ids`, `alerted_more`, `kept_at_alert`, set-based re-alert, `dependency-advisory-realert` event), §15.13 ruling box, Human Review item 21 | Overflow case also re-alerts on count growth; residual R-11 disclosed | TC-C19, TC-C20, TC-P20 |

New sub tokens (extends TD-D5-1): `run-invalid`; *(architect 2026-10-20)* `record-truncated`, which is §15.5 rule 4 with exactly one `notice` annotation whose message starts with `hos-dependency-audit/1 ` but fails the full match. It holds exactly as `record-invalid` does, and the runbook's sub-token table (§15.10 (iv)) names its remedy: lower the `ids` cap. New residuals: R-11, R-12 (§14).

**ADR text changes this needs (not made here; for the architect):** (1) AD-16's record grammar gains `ids=<…> more=<0|1>`, and its "at most 512 bytes" becomes 8192 (G-4). (2) AD-18 "where the consumer lives": the consumer runs from an `origin/main` extraction, not the checkout, and the scope predicate reads `origin/main` (H-1, M-2). (3) AD-18 state: the `check_error` throttle marker lives in `~/.hos/build-hold-alert/`, not in the hold directory (M-3). (4) AD-20: the notifier gets an allowlisted environment without `GH_TOKEN` (L-4). (5) AD-19: "docs-only" is `docs/` + `DECISIONS.md` (L-5).

**Startup-gap check.** H-1, M-1..M-3 and L-1..L-5 should have been in the initial §15. They were caught by design review before any code was written against §15, so no sign-off is orphaned beyond those already listed in §14 "D-5": the architect's §15 approval and the security-reviewer's review are re-run on this revision. No `startup-artifact-gap` issue is needed, since nothing was built.

---

## Human Review Required

**RISK: MEDIUM — CONFIDENCE: HIGH**
**Change classification: ADDITIVE, with one CLARIFYING departure that would break the build if reversed (D-1).**

This document adds implementation detail to two already-approved documents. It reverses no ADR ruling, though AD-2a has since reversed one of mine (TD-1, below). Confidence is high because every premise that moves an implementation choice was re-measured on this branch (§0). The decisions I owned are TD-1 and the four §1.4 departures. ~~— TD-1 (strict repo-scoped) and the four §1.4 departures — each tighten rather than loosen the ADR.~~ TD-1's strict repo-scoped conclusion is **withdrawn by AD-2a**: the gate now honours the literal `--empty-changeset` token, so an all-deletions step reports `NOT CHECKED` with no network call (§1.1, §4.1, §4.2). The four §1.4 departures still each tighten rather than loosen the ADR.

**What a human may want to look at:**

1. ~~**TD-1** — I upheld the architect's strict repo-scoped ruling against the worker's invitation to preserve today's empty-changeset skip. The consequence is real and already flagged in the ADR's §6: a local `run_gates.sh` on an all-deletions step now makes a network call and can report `GATE FAIL` on #1504's live findings where it previously exited 0. Reversible in one line if a human disagrees; the sanctioned stop is a human suspension of `dependencies`.~~ **WITHDRAWN by AD-2a (ADR §2a; ADR §6 item 2, DOWNGRADED).** `dependency_audit.sh` honours the literal `--empty-changeset` token and reports `NOT CHECKED`, exit 0, so an all-deletions step makes **no** network call and cannot report `GATE FAIL`; behaviour is unchanged from today and #1759's TC-A2 invariant is preserved. There is no newly reachable red to surface. *(Struck 2026-10-14 by architect re-review.)*
2. **The ~~two~~ operational item~~s~~ the ADR flagged** (§6 of the ADR, item 1) stand~~s~~ unchanged and belong~~s~~ in the PR body: the repo's first `on: schedule` workflow with an `issues: write` grant and a permanent second tracking issue~~; and TD-1's newly reachable red~~. *(The second item, TD-1's newly reachable red, is withdrawn by AD-2a. See item 1 and ADR §6 item 2.)*
3. **ADR §6 item 3 (AD-12a/AD-12b, realigned here 2026-10-14):** a new repo label, `dependency-audit`, contrary to AC-26's "no new label", plus a standing "do not hand-remove it" rule. Needs explicit human clearance in the PR body. AD-12b's two live-GitHub assumptions (label-on-create works with `GITHUB_TOKEN` + `issues: write`; a missing label is auto-created) are untested against live GitHub. ~~— either failing yields a red first run with one unlabelled issue, never a silent weekly duplicate.~~ *(Superseded by ADR AD-12b as amended, S-2.)* Either failing yields a **loud, recurring red**, not a one-off. The first run creates one unlabelled issue and fails. Every later run (weekly, and every `workflow_dispatch`) may create **another** unlabelled issue and fails again, until an operator fixes the label or token and follows the four-step clean-up in §11.2(d). It is never silent. The PR body should tell the human to watch the first scheduled run. The S-3 confused-deputy residual (a triager labelling an outside author's decoy, which turns every run red on ambiguity) is likewise loud and accepted, on the binding condition that no template or labelling automation ever applies `dependency-audit` (§9.6, §11.2(d)). *(Added 2026-10-14, ADR §6 item 3 addendum, AD-12a "Lookup bound".)* The label now also bounds the lookup. The listing is filtered server-side by `dependency-audit`, so neither outsiders nor the repo's own growth (about 2,100 issues and PRs today, growing about 800 a month, which would reach the 5,000-entry cap around February 2027) can exhaust its cap. **Declining the label therefore also reopens the CWE-400 availability finding**, and any fallback design must solve the lookup bound as well as identity. This adds no new obligation to the clearance. It changes what the human is weighing.

Nothing here required a human before `coder` built the original ten commits. Item 3 requires a human before the implementation PR **merges**. Item 7, added below, requires a human before the security-amendment commit is **made**. Item 9 adds no new gate. Its waiver-scope note rides item 7's existing gate.

**2026-10-14 security-review amendment: RISK: MEDIUM, CONFIDENCE: HIGH. Classification: ADDITIVE** (§14). It tightens an `issues: write` workflow, a blocking gate's argv, and the CI job. No interface, file count, or ruling changes. The three load-bearing facts were re-measured on this branch: bandit honours `--`, quotepath quoting defeats the `*.py` filter, and `changeset.sh` rejects `-*` only on explicit argv (TV-10…TV-12). A human may want to look at:

4. **R-4.** The fail-closed property of the scheduled report holds only against an honest `audit` failure. A compromised `audit` can close the tracking issue with a forged empty report. This is accepted as residual, not fixed.
5. **The SEC-S4 allowlist** is a minimum bar, not output escaping (#1812). An over-strict pattern would turn a real advisory into a red weekly run, never a silent one. That is the intended failure direction.
6. **R-6.** `changeset.sh`'s git-sourced selectors pass `-`-prefixed and quotepath-quoted names unchecked. This affects every file-list gate, not only `security_scan.sh`, and is left to a follow-up because the file is on this PR's no-touch list.

**2026-10-14 architect-conditions revision (C1-C3, non-blocking item 2): RISK: MEDIUM, CONFIDENCE: HIGH. Classification: CLARIFYING (C1, C2) plus ADDITIVE (C3 runbook text; the `OversizedAuditJSON` subclass). Nothing is STRUCTURAL.** No interface between components changes and no file is added. Every C2 statement was checked against the as-built code at `a979a4605`. A human may want to look at:

7. **The commit budget is 11, not 10 (§12). This needs a human decision.** `docs/PR-SIZE-POLICY.md` requires explicit human authorization to go past 10 commits. pm-agent escalated the one-commit waiver with a recommendation to grant it (REQUIREMENTS-1605 §1). Until a human authorizes it, the security-amendment commit must not be made. The ten reviewed commits stay as they are. The authorization must be given **before** that commit, on the `needs-human` issue PR-SIZE-POLICY prescribes or in this design PR's thread. It cannot wait for the Part 2 PR's AD-12a/AD-12b clearance, because the commit must already exist by then (architect C6(b)). Any further fixup commit (a 12th) also needs a human, not pm-agent (C6(a)).
8. **The AD-12b failure repeats on every run until fixed (§9.4, §11.2(d)).** If label-on-create does not work against live GitHub, every run goes red and may leave another unlabelled issue, until an operator follows the four-step clean-up. Watch the first scheduled run. In clean-up step 3 the operator may label at most one survivor, and only one whose issue number appears in a failed run's `GitHubError` message (author `github-actions[bot]` as corroboration). Otherwise it is closed and the next run creates a fresh issue (architect C5).

**2026-10-14 ADR AD-12a "Lookup bound" mirror (architect T1–T12): RISK: MEDIUM, CONFIDENCE: HIGH. Classification: ADDITIVE (one keyword on `list_issues`, with a backward-compatible default) plus CLARIFYING. Nothing is STRUCTURAL** (§14). It changes the HTTP request of a workflow holding `issues: write`, but never what is adopted: the in-code label-and-marker predicate is unchanged and still decides identity. Confidence is high because the failure directions were checked. If the filter is ignored, the lookup falls back to the old fail-closed-at-cap behaviour. If the filter is refused for a missing label, the run goes red with zero writes. If the filtered view is stale, the worst case is one duplicate and one red run. None of these is silent. A human may want to look at:

9. **The lookup is now label-filtered, and two of its properties are unverified until the first live run (§9.6, §11.2(d)).** (i) If GitHub answers 404/422 to a filter on a label that does not exist yet, the first run goes red with `list_issues: no usable response for page 1`, zero writes and no issue. The fix is to create the label (clean-up step 1). (ii) If the filtered view were ever stale, one duplicate would be created and the next run would go red on ambiguity. Watch the first scheduled run for either. **The S-6 waiver's scope** (§12): the single amendment commit now also carries this lookup-bound fix in `github.py` and the consumer test file. The file and commit counts are unchanged, but the waiver terms pm-agent escalated say "only the security design amendments and their tests". The human authorizing the waiver should be told it covers this fix too. pm-agent owns the REQUIREMENTS-1605 §1 wording, and I have not edited it.

**2026-10-20 D-5 / AD-22 amendment (§15): RISK: HIGH, CONFIDENCE: MEDIUM. Classification: STRUCTURAL, human-issued.** D-5 is the human's ruling: a new pipeline state, a host read path, and a cycle-start step in `bin/hos-cron`. pm-agent and the architect have already escalated it. This TD adds no structural change of its own. Its departures (§15.12, TD-D5-1..10) are additive or clarifying, and AD-22 is clarifying, since it restores main's behaviour. Confidence is medium, not high, for three reasons. #2125's notifier does not exist, so the alert is designed against a quoted interface. The Actions-API record path (§15.5) has not been run against live GitHub. The day-one run cannot use CI's Python 3.12 on this host (§15.10). Each of these fails toward a hold that someone can see, never toward a silent pass.

**Open questions for the human. Each one gates the step named in it:**

10. **Q-D5-1, vehicle.** §15.11 implements AD-23's recommendation: Part 2 is the gate split (11 files), and Part 3 is the scheduled audit plus D-5 (15 files, at the ceiling with no shed left, G-1). The alternative is one PR of about 26 files, which needs a size waiver. **This gates Part 2's re-cut.**
11. **Q-D5-2, writing `NOT_RUN` to the tracking issue.** The design follows the recommendation: no. AC-25's zero-writes rule stands, and the hold file, the log line, the run and the alert are the record. A "yes" would add a write path to `report`, which `report` never reaches on an `audit` failure. It would have to be redesigned on the host side.
12. **Q-D5-3, clearing without a clean run.** The design follows the recommendation: clean run only (§15.6 `clear_act`). An escape hatch, if wanted, is a host-side, human-run, time-boxed override. That is a loosening, and it needs your explicit choice.
13. **Q-D5-4, does Q3 count as the AD-12a/b merge clearance?** Under AD-23 the label code ships in Part 3, so the answer attaches to **Part 3's merge**.
14. **Q-D5-5, fallback when the alert is undelivered.** §15.7 is designed for (a): `escalate_to_human.sh` on the tracking issue, once per fingerprint. (b) means setting one constant. (c) means waiting for #2125. **Part 3 coding must not start before this is answered.**
15. **Q-D5-6, does a read failure hold?** The design follows the recommendation and I-7: yes, after 6 h of cached-reading tolerance. A "no" is one constant (`READ_FAILED_HOLDS`).

**Also for the human (not questions):**

16. **The token permission precondition.** The Worker App needs `actions: read` and `checks: read`. Without them, every worker cycle after Part 3 merges holds with `read-failed`. Granting them is a human act (ADR §6 item 4; runbook §15.10 (vi)).
17. **Day one holds by design (R-10).** After Part 3 merges, the worker holds with `stale` until someone dispatches the workflow on main. Dispatch it immediately.
18. **Cross-issue requirements, to be disclosed in the Part 3 PR body.** #2125: add the two causes and accept `--url`. #2123: B4 fingerprinting and adopting the shared hold directory. Neither is implemented here.
19. **`.claude/agents/worker.md` parity is deferred (G-2).** Only the cron prompt learns the third directive value in Part 3. The directive describes itself. A follow-up, authored by the top-level session, brings `worker.md` in line.
20. **H-D5-7 (ADR §6 item 8): until #2125 lands, a hold with no tracking issue ever seen pushes no alert, and a fallback on a closed tracking issue may not surface.** Accept and disclose (recommended), or choose Q-D5-5 (c), or authorise an anchor issue.
21. ~~**G-4 (ADR §6 item 9): does a second new advisory while held need a pushed alert?** Recommendation: re-alert when `kept` increases under the same fingerprint.~~ **Resolved by pm-agent (AC-34/AC-41, `ebadd5397`): yes, per new advisory, set-based (§15.6).** The count-based recommendation was insufficient (swap case). Residual R-11 (more than 100 distinct kept advisories) is disclosed.
