# TECHNICAL-DESIGN-1605 — Two gates, a file-derived bandit verdict, and a scheduled dependency report

**Status:** BINDING on `coder`, `unit-test`, `system-test` for issue #1605. Everything below is a contract, not a suggestion. Where this document narrows or corrects the ADR it says so explicitly and gives the measurement that forced it (§1.4).

**Date:** 2026-09-22 (realigned 2026-10-14 to AD-12a/b; amended 2026-10-14 by the security design review)
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
| TC-D1..TC-D4 | AC-10, AD-6 | one per pip-audit stub PB-1…PB-4 (§6.2) |
| TC-D5 | AD-6 inertness | seam unset → the gate resolves the venv binary (assert the SKIP line when absent, else that a real run completes). Skip-guarded; marked `slow`/network-tolerant, since it is the one case that may touch the network |
| TC-D6 | AC-9 | tmp git repo + `contract/gate-suspension.md` containing `SUSPENDED: dependencies`, cwd=tmp_path (TV-9): `dependency_audit.sh` prints `GATE SUSPENDED: dependencies` and exits 0, **while `security_scan.sh` in the same tree still scans** a planted HIGH file |
| TC-D7 | AC-9 (converse) | same, with `SUSPENDED: security`: `security_scan.sh` is suspended, `dependency_audit.sh` (stubbed) still reports its findings |
| TC-D8 | AC-7 | `"security" not in AUTO_CHECKABLE_GATES and "dependencies" not in AUTO_CHECKABLE_GATES` (import the map, do not re-implement it) |

All stub-driven cases run with `GATE_TIMEOUT=20`, `GATE_RETRIES=1` (existing `_run` helper) and must not touch the network.

### 7.2 `tests/oversight/test_gate_arg_grammar.py` (modify)

1. `KIND_FILTER_GATES` gains `"security_scan": "Python"` (AD-5). `FILE_LIST_GATES` and `DEFAULTING_STRING_GATES` are **unchanged**.
2. Module docstring: the paragraph explaining that assertions avoid depending on pip-audit's network result for `security_scan.sh` must be rewritten — after #1605 that gate is offline and deterministic; the caveat now applies to nothing in this file. Say so, and say why (the network half moved to `dependency_audit.sh`, which is not in `FILE_LIST_GATES`).
3. **TC-G9 — `dependency_audit.sh` ignores its argv, except `--empty-changeset`** (the TC-G8 `collection_integrity` precedent, and the pin on TD-1 as narrowed by AD-2a). With `HOS_PIP_AUDIT_BIN` pointed at stub PB-2 so the case is offline and deterministic, run in a tmp git repo with one committed `.py`:
   - baseline (no args) vs `--diff HEAD~1` vs `a.py b.py` vs `--nope`: assert **identical stdout and identical rc** across these four. `--nope` producing the same output pins "no argv parsing beyond the one token" (no exit 2).
   - `--empty-changeset`, asserted separately: rc 0; stdout **differs** from the baseline; stdout contains `dependency_audit: NOT CHECKED — empty changeset (nothing was checked; this is not a pass)`; no `GATE PASS`. ~~`--empty-changeset` producing the same output as the baseline is the explicit pin on TD-1.~~ *(Withdrawn by AD-2a. The same-output assertion would now fail, and correctly.)* The no-network half of AD-2a (the stub is never invoked) is pinned in §4.2's two cases, not here. The as-built test at `a979a4605` matches.
4. **TC-G10 — auto-discovery (AC-8).** Run the runner's own discovery expression (`find scripts/oversight/gates -maxdepth 1 -name '*.sh' -not -name 'check_suspension.sh'`) and assert both `security_scan.sh` and `dependency_audit.sh` are in the result. This pins that a new gate file is picked up with no `run_gates.sh` edit. The companion assertion — that `run_gates.sh` has no diff — is a PR-level check (§12), not a unit test.

### 7.3 `tests/automation/test_dependency_audit_report.py` (new)

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

Delete the existing `| security_scan.sh | CI-portable, deferred | — | Its pip-audit sub-check … |` row entirely — the rationale is retired, not amended — and insert, keeping the table's existing ordering (after `template_refs_check.sh`, before `django_check.sh`):

| Gate | Status | Workflow | Reason |
|---|---|---|---|
| `security_scan.sh` | Wired, advisory | `oversight-gates.yml` (job: `oversight-gate-security-scan`) | Deterministic, file-scoped, no network — bandit `-lll` only; the pip-audit half moved to `dependency_audit.sh` (#1605), which is what had kept this gate out of CI. Zero debt: 0 HIGH findings over 219 tracked `.py` files, measured 2026-09-22 through bandit's `-o` file channel, not stdout (which carries a progress bar past ~1s of scan time and silently fail-opened the old gate — see DECISIONS.md #1605). Not promoted: #1605 wires; promotion is its own decision (F-1). |
| `dependency_audit.sh` | Local-only (by design), plus a scheduled report | `dependency-audit.yml` (jobs: `dependency-audit-scan`, `dependency-audit-report`) — **not** `oversight-gates.yml` | Repo-scoped and network-dependent: it audits the installed dependency set against a live advisory database, which is not a property of a PR's diff. Deliberately absent from `oversight-gates.yml` (deterministic, offline-only). Runs weekly instead and reconciles a single label-authenticated tracking issue (`dependency-audit` label + first-line marker, AD-12a); it can never fail a PR check. The vulnerabilities themselves are #1504. |

### 11.4 `DECISIONS.md` — one appended, dated entry (AC-31)

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

---

## 12. Commit decomposition (planned 9 of 10; as built 10, plus one security-amendment commit = 11, which needs a human-authorized one-commit S-6 waiver)

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

No approved design or code elsewhere in the repo was built against a decision this document revises.

**Residual risks carried, not fixed:**
- **R-1** — a deletions-only PR makes every file-scoped CI job exit 3 (#1759 RISK-1 / D5). The new job inherits it. Out of scope.
- **R-2** — the new tracking issue permanently overlaps #1504 (I-4, resolved later by F-4).
- **R-3** — `run_gates.sh` derives the suspension key it records in `gate-results.json` from the script's basename (TV-5), so that artifact's `suspended` field will read `dependency_audit`/`security_scan` while the gates themselves check `dependencies`/`security`. Pre-existing for `security_scan`; the new gate inherits it. Fixing it means editing `run_gates.sh`, which S-4 forbids. **Worth a follow-up issue**, filed by the worker alongside F-2.
- **R-4 (SEC-M1, accepted).** A *compromised* `audit` job can upload a valid report: an empty one that closes the tracking issue, or a fabricated finding set. `needs: audit` fails closed only against an honest `audit` failure. SEC-S4 bounds what such a report can write (no mentions, no markup, no forged state block, bounded size), but it cannot detect the forgery. The out-of-band check is that #1504 tracks the same vulnerabilities independently, so a false all-clear contradicts it visibly. This is accepted as residual: no in-workflow design can authenticate a report against the job that produced it.
- **R-5 (SEC-M2 follow-up, #1812).** The other six file-scoped jobs in `oversight-gates.yml` still list changed files with quotepath-quoted `git diff --name-only`, so their gates skip a non-ASCII filename as the wrong kind. The fix is repo-wide and out of this PR. The worker appends it to #1812.
- **R-6 (SEC-M2 follow-up, no-touch file).** `scripts/oversight/lib/changeset.sh`'s git-sourced selectors (`--diff`/`--step`/`--staged`) read `git diff --name-only` with the default quotepath. A non-ASCII path then fails `_hcs_apply_rex`'s `-e` existence test and is misclassified as missing. These selectors also never check git-sourced names for a leading `-` (TV-12). §3.6's `--` neutralises the `-` half for `security_scan.sh`, and every other `FILE_LIST_GATES` tool invocation has the same question to answer. `changeset.sh` is on this PR's no-touch list, so this is a follow-up for the worker to file or append to #1812 (or to #1759's successor), not a change here.

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
