# Technical Design — Worker Operational Reliability (v0.4.0)

**Status:** draft — for architect review (iteration 1)
**Source spec:** `docs/specs/SPEC-worker-operational.md` (pm-agent, 2026-06-16)
**Issues:** #54, #157, #309, #311, #312, #316, #325
**Author:** technical-design · 2026-06-16
**Reviewers required before coder handoff:** `architect` (approval), then routes to `coder`

---

## Self-flag (design-authoring, per HOS authoring contract)

This document is an authoring artifact, not application code. Per the technical-design
authoring rules I classify the design changes and emit the HOS self-flag for the
MEDIUM-or-above ones.

**RISK:** MEDIUM
**CONFIDENCE:** MEDIUM-HIGH
**BLAST RADIUS:** Install-time flow (`hos_install.sh` / `scripts/framework/install.sh`),
`.claude/settings.json` hook surface, two new automation scripts, one new gate
sign-off field, `activation.py` (a module on the §312 scope-guard path), and the
operator guide. Touches the **framework-canonical protected surface**
(`bootstrap/**`, `scripts/framework/**`, `scripts/oversight/gates/**`,
`.claude/agents/**`) at several points — every PR built from this design that
modifies those paths routes to HUMAN merge regardless of tier (R9.1.3). The coder
and reviewers must treat all such steps as human-gated.

**Change classification per section:**

| § | Change type | Self-flag tier | Notes |
|---|---|---|---|
| §1 prompt-capture hooking | **structural** | MEDIUM | New install-time decision + persistent hook wiring + new audit event. Structural → escalated to human below. |
| §2 collection-integrity gate | **clarifying** | LOW | Gate already exists; this adds the sign-off field contract only. |
| §3 session-state artifact | **additive** | LOW | New template + read/write contract; no protected surface beyond `worker.md` PROJECT-adjacent CORE (already shipped). |
| §4 triage calibration Phase 1 | **additive** | MEDIUM | New read-only analysis script; no production-path mutation in Phase 1. Depends on a module (`triage.py`) that does not yet exist — see OQ-A. |
| §5 repo scope assertion | **additive** | MEDIUM | Two new pure functions in `activation.py`; behavioral contract already in `worker.md` CORE. |
| §6 dead-man paging | **structural** | MEDIUM | New externally-run notification path with side effects (email, webhook, issue creation); depends on `breakers.py` which does not yet exist — see OQ-B. Structural → escalated to human below. |
| §7 empty-PR guard | **additive** | MEDIUM | New pre-`gh pr create` check in `hos_worker.sh` which does not yet exist — see OQ-C. |

### Human Review Required

Two sections are classified **structural** and are escalated to a human before the
coder writes against them:

- **§1 (prompt-capture auto-hooking)** — it introduces a new persistent control
  surface (`.claude/settings.json` hooks) and a new permanent suspension record
  (`contract/gate-suspension.md`) decided once at install. A wrong default here
  silently suppresses the prompt-capture gate for the life of the install. Human
  must confirm: (a) the prompt default (`[Y/n]` → default **Yes**), and (b) that
  writing a `SUSPENDED:` record from an installer is acceptable given the
  gate-suspension template's "HUMAN ONLY — agents must not create or modify this
  file" invariant (see **OQ-D**, a live conflict the human must resolve).
- **§6 (dead-man paging)** — it adds an outbound notification path (email/webhook/issue)
  that fires on an operational incident. A misconfigured or noisy path is itself an
  operational hazard, and it depends on a not-yet-built module (`breakers.py`).

The remaining sections (§2–§5, §7) are `clarifying`/`additive` and proceed under
normal architect review.

---

## Dependency reality check (read before sequencing)

The spec references several modules and scripts **as if they exist**. They do not
yet exist in the tree as of 2026-06-16. This materially affects build order and is
the single largest open question for the architect.

| Referenced by spec | Exists today? | Consequence |
|---|---|---|
| `scripts/automation/lib/activation.py` | **Yes** (`verify_bot_identity` only) | §5 extends it. |
| `scripts/oversight/gates/collection_integrity.sh` | **Yes** (already implements R2.1–R2.3, R2.5) | §2 reduces to the sign-off-field contract + a CI wiring confirmation. |
| `scripts/capture_session.sh` | **Yes** (at `scripts/`, not `scripts/automation/`) | §1 hook command path differs from spec — see §1.4. |
| `templates/claude-settings.json` | **Yes** (permissions only, no `hooks` key) | §1 adds a `hooks` block. |
| `contract/gate-suspension.template.md` | **Yes** (template) | §1 "No" path writes the rendered `gate-suspension.md`. |
| `scripts/automation/lib/breakers.py` (`dead_man_triggered`) | **NO** | §6 cannot run end-to-end until `breakers.py` ships. **Hard dependency.** |
| `scripts/automation/lib/triage.py` (`triage`) | **NO** | §4 calibration cannot run until `triage.py` ships. **Hard dependency.** |
| `scripts/automation/lib/correlation.py` | **NO** | Not directly needed by this spec but referenced by the worker chain. |
| `scripts/automation/hos_worker.sh` | **NO** | §7 worker-side guard has no host script yet. **Hard dependency.** |
| `scripts/automation/hos_orchestrator.sh` | **NO** (referenced by operator guide + PRD) | §6 cron context. |
| `pr_readiness.py` (step 8.9) | unverified | §3 R3.6 self-assessment integration depends on it. |

**OQ-A / OQ-B / OQ-C (architect):** §4, §6, and §7 each depend on a module/script
that the unattended-worker build (#254) has not yet landed. The design below specifies
the **contract** each of these sections requires from the missing module so the work
can proceed, but the architect must decide build sequencing: either (1) gate these
three sections behind the #254 module landings, or (2) have this work define thin
stubs/interfaces it can build against. My recommendation is **(1)** — define the
interface contract here (done below), but do not merge §4/§6/§7 implementation until
the host module exists, to avoid orphaned code calling a missing symbol. §1/§2/§3/§5
have no such dependency and can proceed immediately.

---

## Component map

```
INSTALL TIME (§1)
  scripts/framework/install.sh
    └─ new Step 5b: prompt-capture decision
         ├─ Y → write hooks block into .claude/settings.json   (merge)
         │       + write config.sh: PROMPT_CAPTURE="active"
         └─ N → render contract/gate-suspension.md (SUSPENDED: prompt-capture)
                 + write config.sh: PROMPT_CAPTURE="suspended"
  templates/claude-settings.json
    └─ new "hooks" block (PostToolUse on Edit|Write, Stop)
  scripts/automation/capture_session.sh   (NEW — thin wrapper / relocation shim)
  scripts/automation/check_prompt_capture.sh (NEW — Stop-hook reminder)

PIPELINE RUN (§1 audit, §2 gate)
  scripts/oversight/gates/prompt_capture_status.sh (NEW — emits one audit event)
  scripts/oversight/gates/collection_integrity.sh  (EXISTS — §2)
    └─ unit-test sign-off entry gains: collection_errors: 0

WORKER RUNTIME (§3, §5, §7)
  .claude/agents/worker.md (CORE already has the behavioral spec; confirm only)
  templates/session-state.template.md (NEW — §3)
  scripts/automation/lib/activation.py (§5: +derive_repo_id_from_path, +is_in_scope)
  scripts/automation/hos_worker.sh (§7 empty-PR guard — DEPENDS on host script)

CALIBRATION / MONITORING (§4, §6)
  scripts/automation/run_triage_calibration.sh (NEW — §4, DEPENDS on triage.py)
  scripts/automation/check_dead_man.sh (NEW — §6, DEPENDS on breakers.py)
  docs/specs/UNATTENDED-WORKER-OPERATOR-GUIDE.md (§6 placeholder removal)
  scripts/framework/machine-accounts.env (§6 ONCALL_* keys documented)
```

---

## §1 — Prompt-capture auto-hooking (#54)

### 1.1 Contract: install-time decision

**Host:** `scripts/framework/install.sh`, new **Step 5b**, placed *after* the
config.sh write (current Step 5, line ~316) and *before* "Step 6: Make scripts
executable". It runs only in interactive mode; in non-interactive (CI) mode it
honors a `PROMPT_CAPTURE` env var and defaults to `active` if unset and hooks are
not already present.

**Prompt text (exact):**

```
── Step 5b: Prompt-capture automation

Enable prompt artifact capture for MEDIUM+ changes?
This installs Claude Code hooks that log session turns automatically and remind
you to run capture_prompt.sh before committing MEDIUM+ changes. Choosing No
records a permanent, auditable suspension of the prompt-capture gate.
[Y/n]:
```

Default (empty input) = **Y**. Input matched case-insensitively: `y`/`yes`/empty → Yes path; `n`/`no` → No path; anything else → re-prompt once, then treat as Yes.

### 1.2 Contract: "Yes" path — hook wiring

`install.sh` merges the following into `.claude/settings.json` (the file already
exists with a `permissions` key; the merge adds a sibling `hooks` key, never
overwriting `permissions`). The canonical block, also shipped in
`templates/claude-settings.json`:

```json
"hooks": {
  "PostToolUse": [
    {
      "matcher": { "tool_name": { "regex": "^(Edit|Write)$" } },
      "hooks": [
        {
          "type": "command",
          "command": "bash scripts/automation/capture_session.sh --file {file} --description '{description}'"
        }
      ]
    }
  ],
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "bash scripts/automation/check_prompt_capture.sh"
        }
      ]
    }
  ]
}
```

The command paths point at `scripts/automation/` per the issue brief. **Note the
existing `capture_session.sh` lives at `scripts/capture_session.sh` and uses a
different CLI (`--log FILE MSG`), not `--file/--description`.** Resolution in §1.4.

`install.sh` also writes to `config.sh`: `PROMPT_CAPTURE="active"`.

**Merge rule:** if `.claude/settings.json` already has a `hooks` key, do not
duplicate — replace the `PostToolUse` Edit|Write matcher and the `Stop`
prompt-capture entry idempotently (key on the `command` substring
`capture_session.sh` / `check_prompt_capture.sh`). The merge is performed with the
same jq/python merge helper `install.sh` already uses for `permissions` (line ~1020
of `bootstrap/hos_install.sh`); reuse that helper, do not hand-roll JSON string
surgery.

### 1.3 Contract: "No" path — explicit suspension

`install.sh` renders `contract/gate-suspension.md` from
`contract/gate-suspension.template.md` (if the rendered file does not already
exist) and appends a `## SUSPENDED: prompt-capture` block:

```markdown
## SUSPENDED: prompt-capture
Authorized at: {ISO-8601 install timestamp, UTC Z}
Authorizing operator: {git config user.email, else $USER}
Reason: opted out at install time
Re-enable: re-run install.sh and select Y, then run capture_prompt.sh --re-enable
```

`install.sh` also writes `config.sh`: `PROMPT_CAPTURE="suspended"`.

The brownfield re-enable invariant (template line 19) holds: once suspended, the
record stays in git history even after re-enabling.

**⚠️ OQ-D (architect + human, blocking §1 No-path):** `gate-suspension.template.md`
declares at its top: *"HUMAN ONLY. Agents must not create or modify this file.
Creating this file without human authorization is a protocol violation."* The spec
(R1.3) directs `install.sh` to write this file. `install.sh` run interactively by a
human, with the human selecting "No", arguably *is* the human authorization — but an
installer is a script, and the invariant is categorical. The architect must decide
whether the installer is a sanctioned writer of this file, and if so, the template
comment must be amended to carve out "the installer's one-time install-time
suspension record, written under interactive human authorization." Until resolved,
the No-path implementation is **blocked**. This is a structural change to a
protected-surface (`contract/**`) file — human-gated regardless of outcome.

### 1.4 Contract: the two new scripts

#### `scripts/automation/capture_session.sh` (NEW)

A thin wrapper that accepts the hook's `--file`/`--description` flags and delegates
to the existing logging behavior. It must NOT fail the tool call — a hook that errors
disrupts the editing session. Contract:

- **Args:** `--file <path>` (the edited file; the literal string `session` allowed
  for meta-turns), `--description <text>` (one-line description).
- **Behavior:** append one turn record to the session log
  `prompts/sessions/{session-id}.log` in the format the existing
  `scripts/capture_session.sh` uses (`{ISO-8601} | {file} | {description}`),
  deriving `{session-id}` as `{date}-{branch-slug}` exactly as the existing script.
- **Exit:** always exit 0. On any internal error, write a one-line warning to stderr
  and exit 0 anyway (a logging hook must never break the editor).
- **Relocation decision (resolves the path mismatch):** rather than duplicate logic,
  this new script is a **flag-translation shim** that calls the existing
  `scripts/capture_session.sh --log "<file>" "<description>"`. If the architect
  prefers, the canonical script is *moved* to `scripts/automation/capture_session.sh`
  and the old path becomes a deprecation shim. **Recommendation: move the canonical
  script to `scripts/automation/` and add `--file`/`--description` as aliases for
  the positional `--log` form**, so the spec's command path and flag names are the
  real interface and there is one implementation. Flagged as **OQ-E** for architect:
  move vs. shim.

#### `scripts/automation/check_prompt_capture.sh` (NEW — Stop hook)

Runs at session Stop. Advisory only — never blocks (R1.2: "advisory only — does not
block the session").

- **Args:** none.
- **Behavior:**
  1. If `config.sh` `PROMPT_CAPTURE` is `suspended` → exit 0 silently.
  2. Determine whether any MEDIUM+ file was touched this session. **OQ1.1 resolution
     (from the spec, escalated to technical-design): use the static
     file-extension/path heuristic, not risk-assessor cached output.** Rationale:
     the Stop hook fires with no guaranteed risk-assessor artifact present, must be
     cheap, and must not introduce a dependency on a possibly-absent file. The
     heuristic: a file is "MEDIUM+ candidate" if it matches the protected-surface
     globs (R9.1.3 set) **or** is a non-test source file (`.py`, `.ts`, `.tsx`,
     `.js`, `.sh`, migrations) outside `tests/`. The session's touched-file set is
     read from the session log written by `capture_session.sh`.
  3. If any MEDIUM+ candidate was touched and no prompt artifact exists for this
     session (check `prompts/sessions/{session-id}-summary.md` or the capture
     watermark), print the reminder to stderr:
     `One or more MEDIUM+ files were changed this session. Run capture_prompt.sh before your next commit.`
  4. Always exit 0.

### 1.5 Contract: per-run audit event

**Host:** a small gate script `scripts/oversight/gates/prompt_capture_status.sh`
(NEW), invoked once per pipeline run by `run_validators.sh` / the transition gate
chain. It appends **exactly one** line to `audit/oversight-log.jsonl`.

The audit log is **flat one-JSON-object-per-line** (confirmed from existing log).
The three event shapes (matching the issue brief verbatim, with a `ts` field added
to match the existing log convention which uses `timestamp`/`ts`):

```json
{"event": "gate-na",        "gate": "prompt-capture", "ts": "<ISO-8601 UTC Z>"}
{"event": "gate-suspended", "gate": "prompt-capture", "ts": "<ISO-8601 UTC Z>"}
{"event": "gate-active",    "gate": "prompt-capture", "artifact": "<path>", "ts": "<ISO-8601 UTC Z>"}
```

**Selection logic:**

- Step risk tier is LOW → `gate-na`.
- `config.sh PROMPT_CAPTURE == "suspended"` (or a `SUSPENDED: prompt-capture` line
  exists in `contract/gate-suspension.md`) → `gate-suspended`.
- Otherwise (active, MEDIUM+ tier) → require an artifact path. If present →
  `gate-active` with `artifact`. **If absent → the gate fails (exit non-zero, R1.5)**
  with the message: `Prompt artifact required for MEDIUM+ step — run capture_prompt.sh or check hook wiring.` and emits NO audit line (the failure is the signal; the
  next successful run emits `gate-active`). The architect should confirm whether a
  failed run should also emit a distinct `gate-failed` event for forensics — I
  recommend yes, but the issue brief lists only three shapes, so I leave it as
  **OQ-F**.

**Field-name note:** the issue brief shows the bare three-key objects without a
timestamp. Every existing line in `audit/oversight-log.jsonl` carries a time field
(`timestamp` or `ts`). I add `ts` for forensic consistency; if the architect wants
the literal brief shape with no timestamp, that is a one-line change. Flagged
**OQ-F**.

### 1.6 Boundaries

- The hooks never block editing or the Stop event (advisory only).
- `prompt_capture_status.sh` is the *only* writer of `prompt-capture` audit events;
  no other script emits them.
- The installer is the *only* writer of the `SUSPENDED: prompt-capture` record
  (pending OQ-D).

---

## §2 — Collection-integrity gate (#157)

### 2.1 Reality: the gate already exists and satisfies most requirements

`scripts/oversight/gates/collection_integrity.sh` already implements R2.1
(collect-only, fail on import errors), R2.3 (transition-gate position via the gate
chain), and R2.5 (prints the error lines). It additionally handles N/A cases
(no pytest, no tests) gracefully and honors suspension via `check_suspension.sh`.

The existing gate runs `pytest --collect-only -q` and greps for errors — equivalent
to the issue brief's `grep -E "ERROR|ImportError|ModuleNotFoundError"`. **No new gate
script is required.** The design for §2 reduces to two contract additions:

### 2.2 Contract: trigger condition (R2.2 — confirm)

The gate runs on any diff touching ≥1 `*.py` file; it does not run on non-Python-only
diffs. The existing script is content-agnostic (it always collects). The
**trigger** belongs to the gate-chain caller (`run_validators.sh` / transition
chain), which must invoke `collection_integrity.sh` only when
`git diff --name-only` contains a `*.py` path. **Coder task:** add that guard in the
gate-chain caller, not in the gate script (keeps the gate reusable for manual runs).

### 2.3 Contract: the `unit-test` sign-off field (R2.4)

The `unit-test` agent's sign-off register entry, for any build step touching Python
files, MUST include the field:

```
collection_errors: 0
```

- Type: integer. Required when the step diff touches `*.py`; omittable otherwise.
- A value other than `0`, or an omission on a Python-touching step, is an
  **oversight-evaluator Phase 1 compliance failure**.
- This is a new required field in the sign-off schema. **It must be added to
  `contract/OVERSIGHT-CONTRACT.md` §3 (sign-off schema) and to the base-agent
  register examples** (`templates/base-agent-register-examples.md`, the `test-unit`
  role example). The `unit-test` agent CORE definition must instruct the agent to
  run the collection-integrity gate and record the count.

### 2.4 Boundaries

- The gate measures the **full** suite, not changed files only — this is the whole
  point (an orphaned import in an *untouched* test file is the failure mode).
- The sign-off field asserts the gate's result; it does not replace the gate. Both
  exist: the gate blocks, the field records.

---

## §3 — Session-state artifact (#309)

### 3.1 Contract: the template file (R3.5)

New file `templates/session-state.template.md`, the canonical format. It governs if
it ever conflicts with the `worker.md` CORE prose (R3.5). Exact content:

```markdown
# Session State — {ISO-8601 date}

## Active work
- Branch: {branch name}
- Build step: {step label, e.g. "B11 (hos_orchestrator.sh)"}
- PR: {PR number, e.g. "#42", or "none yet"}

## Done this session
- {one line per item}

## Next
- {one line per item}

## Open blockers
- {issue number + one-line description, or "none"}
```

This matches the format already in `worker.md` CORE (lines 116–132). The five
sections (`Active work`, `Done this session`, `Next`, `Open blockers`, plus the
title) are required; extra sections are permitted but must not replace these.

### 3.2 Contract: write logic (R3.1, R3.3) — full replace, not append

- **Location:** `.claudetmp/session-state.md` (gitignored).
- **Write mode:** **full overwrite** of the file every time, never append. The file
  is a *current-state snapshot*, not a log. (`worker.md` already says "write or
  update".) The coder must implement this as a `Write` of the whole file, not an
  `Edit`/append.
- **Significant-progress trigger:** the write fires at the end of any turn that meets
  *any* of these (the operational definition of "significant progress"):
  1. A tool call **modified a file** (`Edit` or `Write` succeeded on a non-temp path), or
  2. A tool call **ran tests** (`run_tests_inner_loop.sh` or `pytest` invoked), or
  3. A **commit landed**, or
  4. The **active branch changed**, or
  5. A **blocker was identified or resolved**, or
  6. The **PR transitioned** (none → opened).

  This is the spec's R3.1 list, made detectable. The minimal machine-checkable
  predicate the worker uses: *"did this turn invoke `Edit`/`Write` on a real file,
  or run the test runner, or run `git commit`/`git checkout -b`/`gh pr create`?"* If
  yes → rewrite the session-state file before ending the turn.
- **Immediacy (R3.3):** the write happens at the end of the *triggering* turn, not
  deferred to session end, so a crash does not lose state.

### 3.3 Contract: the `PR: (none yet)` → `PR: #N` transition

When `gh pr create` succeeds and returns a PR number/URL, the worker's next
session-state write sets the `PR:` line to `#N` (extract the number from the `gh pr
create` stdout URL, e.g. `.../pull/42` → `#42`). Before any PR exists the line reads
exactly `PR: none yet`. This is a field update within the full-overwrite write — not
a separate append.

### 3.4 Contract: read logic at session start (R3.4)

On session start the interactive-mode worker:

1. `Read .claudetmp/session-state.md`. If absent → orient from git
   (`git branch --show-current`, `git log --oneline -5`) instead; do not error.
2. If present, extract: the active **branch**, the **build step**, and the **open
   blockers** lines.
3. Produce a **2–3 sentence** orientation summary as the first response, e.g.:
   *"Resuming on branch `forward-port/v0.4.0-specs-to-main` at build step B11
   (hos_orchestrator.sh). Last session opened PR #42 and left one open blocker:
   #316 dead-man paging path. Ready to continue — what's next?"*
4. The summary MUST NOT exceed 3 sentences. Then the worker asks what's next.

This contract is already described in `worker.md` CORE (line 83). §3's job is to
make it precise: the three extracted fields and the ≤3-sentence cap.

### 3.5 Contract: self-assessment gate integration (R3.6)

The self-assessment gate (`pr_readiness.py`, step 8.9) writes its result into the
session-state file:

- On **PASS** → add a line under `## Done this session`:
  `- Self-assessment gate PASSED ({ISO-8601})`.
- On **FAIL** → add a line under `## Open blockers`:
  `- Self-assessment gate FAILED: {first failing check id} ({ISO-8601})`.

This is a session-state update (full-overwrite write), not a replacement of the
gate's own output file. **Depends on `pr_readiness.py` existing** — if it does not,
this sub-requirement is gated behind that module (it is referenced by `worker.md`
step 8.9 but not verified in-tree). Flagged **OQ-G**.

### 3.6 Boundaries

- The file is gitignored — never committed (confirm `.claudetmp/` is in
  `.gitignore`; CLAUDE.md says do not commit `.claudetmp/`).
- Full overwrite always — no reader may assume historical turns are present.
- The summary is bounded at 3 sentences to keep session-start cost near-zero (the
  whole point of #309).

---

## §4 — Triage calibration, Phase 1 only (#311)

### 4.1 Hard dependency

`scripts/automation/lib/triage.py` (with a `triage()` entry point) **does not exist
yet**. Phase 1 calibration cannot run until it lands (#254 work). The design below
specifies the **contract** the calibration script needs from `triage.py`, so the
calibration script can be written and tested against a stub, but it must not be
wired into a real run until `triage.py` ships. **OQ-A (architect): sequence §4
behind the `triage.py` landing.**

### 4.2 Contract: `triage.py` interface required by calibration

The calibration script invokes triage as a batch via
`python -m scripts.automation.lib.triage`. The required interface:

- A callable `triage(issue: dict) -> TriageResult` where `issue` has at least
  `{number, title, body, labels}`.
- `TriageResult` exposes: `.classification` (one of `bug | feature | communication
  | security-report | spec-gap | governance | config | duplicate | invalid`),
  `.confidence` (float 0.0–1.0), `.reached_floor` (bool, confidence ≥ floor).
- The module exposes the active `triage_confidence_floor` (default 0.75) it used.

If `triage.py` lands with a different signature, this script adapts; the contract
above is the minimum it needs.

### 4.3 Contract: `scripts/automation/run_triage_calibration.sh` (NEW)

- **Args:** optional `--repo <owner/repo>` (default `thurlow-research/CondoParkShare`),
  optional `--limit <N>` (default 50), optional `--date <YYYY-MM-DD>` (default today).
- **Step 1 — fetch sample (R4.1):**

  ```bash
  gh issue list --repo thurlow-research/CondoParkShare \
    --label hos-coordination --state all --limit 50 \
    --json number,title,body,labels
  ```

  Sample = the 50 most recent `hos-coordination`-labeled issues (all states),
  created-date descending (the default `gh issue list` ordering). Capture the raw
  JSON to the artifact's appendix for reproducibility.
- **Step 2 — classify batch:** pipe each issue through
  `python -m scripts.automation.lib.triage` (one batch invocation reading the JSON
  array on stdin; the module emits one result object per issue). For each issue
  record: `number, title, classified-as, confidence, reached_floor`.
- **Step 3 — aggregate (R4.3):** compute
  - fraction reaching the 0.75 floor, **per class** and **overall**;
  - security-class false-positive rate — **this requires a human confirmation column**
    (R4.2 bullet 4). The script CANNOT compute false-positive rate autonomously; it
    emits the security-classified rows with an empty `human_confirmed_security`
    column for a human to fill in. The aggregate FP-rate is computed in a second pass
    (a `--score` mode) after the human fills the column, or left as "pending human
    review" in the first pass. **OQ-H (architect):** confirm the two-pass shape
    (machine pass produces the table with a blank column; human fills it; optional
    `--score` re-run computes the FP rate). I recommend two-pass; fully-autonomous FP
    scoring is impossible by R4.2's own definition.
- **Step 4 — write artifact (R4.5):** write
  `audit/automation/triage-calibration-{date}.md`. **Path note:** the issue brief
  says `audit/automation/...`; the spec R4.5 says `audit/triage-calibration-{date}.md`.
  These disagree. **OQ-I (architect/pm):** pick one path. I recommend the issue
  brief's `audit/automation/` subdir (keeps automation artifacts namespaced); flag
  for pm if the spec path is load-bearing for a downstream reader.

### 4.4 Contract: output artifact format

```markdown
# Triage Calibration — {date}

Sample: {N} most recent hos-coordination issues from {repo} (all states).
Triage floor in effect: {floor}

## Per-issue results

| # | Title | Classified as | Confidence | Reached floor | Human-confirmed security (FP?) |
|---|-------|---------------|-----------|---------------|--------------------------------|
| 312 | ... | bug | 0.81 | yes | — |
| 305 | ... | security-report | 0.62 | no | (blank for human) |
...

## Aggregate

- Reached 0.75 floor: overall {x}% ; by class: bug {a}%, communication {b}%, ...
- Security false-positive rate: {pending human review | computed value}
- Misclassification rate (overall, if determinable): {value}

## Decision gate (R4.4) — NOT applied by this script

This artifact is the INPUT to the R4.4 decision gate and Phase 2. The decision and
its rationale are recorded in DECISIONS.md by a human before any triage.py change.

## Appendix: raw gh issue list JSON
{fenced JSON}
```

### 4.5 Boundaries

- Phase 1 is **read-only**: it classifies and reports. It MUST NOT modify
  `triage.py`, `hos-coordination.defaults.yaml`, or the floor. R4.4's decision and
  any change are Phase 2, human-gated, recorded in `DECISIONS.md` first.
- The script does not apply the decision gate — it produces the data the human
  applies it to.
- OQ4.1 (spec): the worker/runner account needs read access to the CPS
  `hos-coordination` issue list. This is an operator prerequisite, surfaced to the
  human (not solvable in code).

---

## §5 — Repo scope assertion (#312)

### 5.1 Reality: behavioral contract already in `worker.md` CORE

`worker.md` CORE "Scope guard (both modes)" (lines 63–72) already specifies R5.1–R5.4
behaviorally: establish session scope from `git remote get-url origin`, one firm
pushback on a cross-repo target, no override path. **§5's job is the implementation
in `activation.py` that the worker calls** — the spec's R5.5 asks technical-design to
confirm the existing section satisfies R5.1–R5.4. **It does** (the pushback message,
the once-only emission, and the no-override rule are all present). No `worker.md`
CORE edit is required; the two new functions give the worker a deterministic
primitive instead of ad-hoc slug parsing.

### 5.2 Contract: `derive_repo_id_from_path(path: str) -> Optional[str]`

New function in `scripts/automation/lib/activation.py`.

```python
def derive_repo_id_from_path(path: str) -> Optional[str]:
    """
    Derive the canonical <owner>/<repo> repo-id slug from a file path OR a
    GitHub URL/reference, using the SAME normalization as the cid/slug
    derivation (R6.1, R13.4): lowercase owner/repo, no trailing slash.

    Resolution order:
      1. If `path` is a github.com URL or an `<owner>/<repo>#<n>` reference,
         extract owner/repo directly and normalize to lowercase.
      2. If `path` is a filesystem path, resolve to absolute, walk up to the
         nearest enclosing git work-tree, read `git -C <root> remote get-url
         origin`, and derive the slug from that remote.
      3. If neither yields a repo, return None.

    Returns the lowercased `<owner>/<repo>` slug, or None when the repo cannot
    be determined.
    """
```

- **Normalization invariant:** MUST use the one canonical owner/repo extraction
  shared with the cid/slug derivation (PRD R6.1 / R13.4 — "exactly one owner/repo
  normalization in this protocol"). When that shared helper lands in `triage.py`/
  `correlation.py`, this function calls it rather than re-implementing. Until then it
  implements the same rule: strip `.git`, lowercase owner and repo, no trailing slash.
- **Returns `None`** (not an exception) when it cannot determine the repo — the
  caller (worker) treats `None` as "cannot prove out-of-scope → do not block on a
  guess" vs "cannot prove in-scope". See the `is_in_scope` boundary below.

### 5.3 Contract: `is_in_scope(target: str, session_repo_id: str) -> bool`

```python
def is_in_scope(target: str, session_repo_id: str) -> bool:
    """
    Return False if `target` resolves to a DIFFERENT repo-id than
    `session_repo_id`; True otherwise.

    target: a file path, a github.com URL, or an `<owner>/<repo>#<n>` reference.
    session_repo_id: the session scope slug (lowercased <owner>/<repo>),
                     derived once at session start from
                     git remote get-url origin.

    Semantics (fail-toward-pushback only when scope is PROVABLY different):
      - derive_repo_id_from_path(target) == session_repo_id  -> True (in scope)
      - derive returns a DIFFERENT, non-None slug             -> False (cross-repo)
      - derive returns None (indeterminate)                    -> True
        (cannot prove a crossing; do not block on a guess — a bare relative path
        inside the current tree is the common case and must not trip the guard)
    """
```

- **Boundary — why `None` → True:** the guard must not false-positive on ordinary
  relative paths (`src/foo.py`) that belong to the current repo. The guard fires only
  on a *provable* crossing (a different non-None slug). This matches `worker.md`'s
  "if asked to act on a file/PR/issue that resolves to a different repository" —
  *resolves to*, i.e. provably different.

### 5.4 Contract: worker call sites

The worker (both modes) calls, before any file edit, PR action, or issue action on a
target it did not itself create this session:

```
if not is_in_scope(target, derive_repo_id()):
    <emit the worker.md scope-crossing pushback, once; do not proceed>
```

`derive_repo_id()` (the session scope, already used by `worker.md`) is the
existing slug from `git remote get-url origin`. The once-only and no-override
behavior (R5.3, R5.4) is governed by `worker.md` CORE prose; these functions are the
pure predicate it consults.

### 5.5 R5.6 research finding (deferred)

After the guard is verified working, a research finding at
`audit/findings/agent-scope-assertion-prevents-cross-repo-drift.md` documents the
incident, fix, and test result. This is a post-verification doc task, not coder work
for this step — note it in the build step's doc-currency checklist.

### 5.6 Boundaries

- The functions are **pure** (no GitHub mutation) except the local `git -C ... remote
  get-url`/work-tree resolution reads. They never act — they only classify.
- They must not raise on malformed input; they return `None`/`True` per the contract.
- They reuse the single canonical owner/repo normalization; they must not introduce a
  second, divergent slug algorithm (that would re-open the M1 duplicate-work hazard
  by analogy).

---

## §6 — Dead-man switch paging (#316)

### 6.1 Hard dependency

`scripts/automation/lib/breakers.py` with `dead_man_triggered(customer) -> bool`
**does not exist yet**. The checker script can be written and unit-tested against a
stub, but a live run requires `breakers.py`. **OQ-B (architect): sequence §6 behind
the `breakers.py` landing.** The required contract from `breakers.py`:

- `dead_man_triggered(customer: str) -> bool` — True iff no probe-completion event
  (a `type: heartbeat` envelope on the designated watchdog issue, per R11.5) landed
  in GitHub for `customer` in the last 6h.
- Ideally also `last_probe_event(customer: str) -> Optional[str]` returning the last
  known probe timestamp, for the issue body's "Last known probe event" line. If
  absent, the body records "unknown".

### 6.2 Contract: `scripts/automation/check_dead_man.sh` (NEW)

Standalone, runs under an **independent cron** distinct from the worker/overseer
(R6.1 — "a dead loop cannot report its own death"). Contract:

- **Args:** `--customer <name>` (required) and `--repo <owner/repo>` (required —
  where the alert issue is created). May also read `CUSTOMER`/`REPO` from env.
- **Step 0 — source config:** `source scripts/framework/machine-accounts.env` to pick
  up `ONCALL_EMAIL`, `ONCALL_WEBHOOK_URL` (both optional, added per §6.5).
- **Step 1 — evaluate condition (R6.2):**

  ```bash
  python3 -c "
  from scripts.automation.lib.breakers import dead_man_triggered
  import sys
  sys.exit(0 if not dead_man_triggered(sys.argv[1]) else 1)
  " "$CUSTOMER"
  ```

  Exit 0 → alive → exit 0 silently. Exit 1 → triggered → run the notification path.
  **Fail-closed:** if the python call errors (non-0/1 exit, e.g. import failure),
  treat as **triggered** and notify — a checker that cannot evaluate the condition
  must not silently assume "alive."
- **Step 2 — notification path, all configured paths fire (R6.5), in order:**
  1. `ONCALL_WEBHOOK_URL` if set:
     ```bash
     curl -sX POST "$ONCALL_WEBHOOK_URL" -H "Content-Type: application/json" \
       -d "{\"event\":\"dead_man_triggered\",\"customer\":\"$CUSTOMER\",\"triggered_at\":\"$TS\"}"
     ```
  2. `ONCALL_EMAIL` if set:
     ```bash
     echo "HOS dead-man switch triggered for $CUSTOMER (no probe in 6h)" \
       | mail -s "HOS ALERT: dead-man switch ($CUSTOMER)" "$ONCALL_EMAIL"
     ```
  3. **GitHub issue — always (R6.4):**
     ```bash
     gh issue create --repo "$REPO" \
       --title "HOS ALERT: dead-man switch triggered — no probe in 6h for $CUSTOMER" \
       --label "needs-human" \
       --body "<body below>"
     ```
  A failure in one path must not suppress the others (R6.5): each is wrapped so a
  non-zero exit logs and continues. The GitHub issue is the always-available floor.

  **Issue body (R6.4, must contain customer, triggered-at, last-known-probe — AC6.3):**
  ```
  The dead-man checker (R11.5) detected no probe-completion event for customer
  <CUSTOMER> in the last 6 hours. The worker may be stopped, hung, or unable to
  post to GitHub.

  Checker triggered at: <ISO-8601 UTC Z>
  Last known probe event: <timestamp from breakers.last_probe_event(), or "unknown">

  Action required: check crontab, orchestrator log, and machine connectivity.
  ```

- **Identity note:** the issue is created under the worker machine-account
  credentials configured for that repo. The checker runs detached from a session,
  so it relies on the cron environment's `GH_TOKEN`/direnv being set to the bot
  account — document this in the operator guide (§6.4).
- **Idempotency (design addition, recommend):** to avoid a new `needs-human` issue
  every checker run while the loop stays dead, the checker should first search for an
  open `needs-human` dead-man issue created in the last 6h and, if found, **comment
  on it** rather than open a duplicate. The issue brief does not require this, but a
  paging path that files an issue every cron tick is itself an incident.
  **OQ-J (architect):** include the de-dup, or accept duplicate alert issues? I
  recommend de-dup (search-by-title-prefix, comment if recent open issue exists).

### 6.3 Contract: machine-accounts.env keys (R6.8)

Add to `scripts/framework/machine-accounts.env` (documented, commented, both
optional, both empty by default):

```bash
# ── Dead-man switch paging (R6.3, #316) — both OPTIONAL ───────────────────────
# If set, check_dead_man.sh emails this address on a dead-man trigger.
ONCALL_EMAIL=""
# If set, check_dead_man.sh POSTs a JSON alert to this webhook on a trigger.
# Payload: {"event":"dead_man_triggered","customer":"<name>","triggered_at":"<ISO>"}
ONCALL_WEBHOOK_URL=""
```

### 6.4 Contract: operator guide update (R6.7)

In `docs/specs/UNATTENDED-WORKER-OPERATOR-GUIDE.md`, replace the
"Not yet implemented" placeholder (lines 59–61) and the troubleshooting-table line
("paging not yet implemented (see issue #316)", line 82) with:

- A description of `check_dead_man.sh` (what it does, that it runs under an
  independent cron).
- The `ONCALL_EMAIL` / `ONCALL_WEBHOOK_URL` config keys and their effect.
- An example cron entry, offset from the worker (R6.6):

  ```cron
  # Dead-man checker — independent cron, offset from worker (R6.6).
  # Worker runs */15; checker runs at minute 7,22,37,52 so it fires even when the
  # worker's scheduled minute is missed.
  7,22,37,52 * * * *  cd /path/to/repo && bash scripts/automation/check_dead_man.sh --customer <name> --repo <owner/repo> >> /tmp/hos-deadman.log 2>&1
  ```

### 6.5 Boundaries

- The checker is **external** to the orchestrator loop — it must not import or call
  the loop, only `breakers.py`'s pure read predicate.
- Fail-closed: an unevaluatable condition pages, it never assumes alive.
- All configured paths fire independently; one failure does not gate the others; the
  GitHub issue is the always-on floor.

---

## §7 — Empty-PR guard, worker side (#325)

### 7.1 Hard dependency

`scripts/automation/hos_worker.sh` (the host for the `gh pr create` call)
**does not exist yet** (it is the per-task worker spawned by the orchestrator,
ADR-3). The guard logic is specified here as a contract for wherever the worker's
`gh pr create` lives — in the interim it also applies to the interactive worker's
PR-open path. **OQ-C (architect): sequence §7 behind the `hos_worker.sh` landing,
and confirm whether the interactive worker's `gh pr create` path needs the same guard
now (I believe yes — R7.1 is mode-agnostic in spirit even though the spec scopes §7
to the worker side).**

### 7.2 Contract: pre-`gh pr create` check (R7.1)

Immediately before `gh pr create`, the worker runs:

```bash
AHEAD=$(git log "origin/${BASE}..HEAD" --oneline | wc -l | tr -d ' ')
```

If `AHEAD -eq 0` → **do NOT open the PR.** Instead:

1. **Log:** `Branch ${BRANCH} has 0 commits ahead of ${BASE} — likely empty after rebase. Not opening PR. Investigating.`
2. **Comment on the originating issue** (if a cid/issue number is known):
   `Branch ${BRANCH} has 0 commits ahead of ${BASE} — likely empty after rebase. Investigating.`
   (Exact text per the issue brief.)
3. **Create a `needs-human` issue** carrying the §8.2 escalation contract
   (problem+risk+background / options / recommendation): the branch is empty ahead of
   base, the likely cause is a rebase that found the fix already upstream, options
   are "confirm upstream and close originating issue as `already-upstream`" vs
   "investigate why the branch reset", recommendation is human confirmation before
   any close. **Per the spec R7.1, the worker does NOT self-close the originating
   issue** — it surfaces and waits. (The spec's R7.1 list mentions closing with
   `already-upstream` "if the fix is confirmed upstream"; confirmation is a human
   step, so the worker proposes the close, does not perform it autonomously. I am
   making the conservative reading explicit; **OQ-K (architect/pm):** confirm the
   worker must NOT auto-close even when `git` strongly suggests upstream.)
4. **Write a `## Open blockers` entry** in `.claudetmp/session-state.md` (via the §3
   full-overwrite write):
   `Branch ${BRANCH} has 0 commits ahead of ${BASE} — investigate before opening PR.`

### 7.3 Contract: post-rebase guard (R7.3)

After any `git rebase` in either mode, run the same `git log origin/${BASE}..HEAD
--oneline` check. If empty:

- Do **not** push the branch.
- Interactive → surface the result to the human.
- Autonomous → create a `needs-human` issue:
  `Rebase dropped all commits — branch is identical to ${BASE}. Verify the fix is upstream before closing the originating issue.`

### 7.4 Out of scope here

R7.2 (overseer pre-review check) is **explicitly the overseer side** and belongs to
`SPEC-overseer-merge-authority.md` per R7.4 — not this design. This design is
authoritative for the **worker-side** guard (R7.1, R7.3) only; the cross-reference
(R7.4) is satisfied by the overseer spec pointing back to R7.1/R7.2.

### 7.5 Boundaries

- The worker never self-merges, never force-pushes, never closes the originating
  issue autonomously on an empty branch — it surfaces state and waits (R7.1 final
  sentence).
- The check uses `origin/${BASE}..HEAD` (local HEAD vs remote base) for the
  pre-open/post-rebase case; the overseer's variant (`origin/${BASE}..origin/${HEAD}`)
  is the overseer spec's concern.

---

## Build-order recommendation (for the architect to confirm)

Independent sections with no missing-module dependency, do first:

1. **§3 session-state** (template + worker read/write contract) — no dependency.
2. **§2 collection-integrity** (sign-off field + caller trigger guard + contract doc
   update) — gate already exists.
3. **§5 scope functions** in `activation.py` — no dependency; `worker.md` already
   has the prose.
4. **§1 prompt-capture hooking** — independent of the missing modules, BUT blocked on
   **OQ-D** (gate-suspension writer authorization) and is structural/human-gated.

Sections blocked on #254 modules, sequence behind their host landing:

5. **§4 triage calibration** — behind `triage.py`.
6. **§7 empty-PR guard** — behind `hos_worker.sh` (interactive variant can land
   earlier if OQ-C says so).
7. **§6 dead-man paging** — behind `breakers.py`; structural/human-gated.

---

## Consolidated open questions for the architect

| ID | Section | Question | My recommendation |
|----|---------|----------|-------------------|
| OQ-A | §4 | `triage.py` does not exist; sequence calibration behind it? | Yes — define contract now, do not wire until it lands. |
| OQ-B | §6 | `breakers.py` does not exist; sequence checker behind it? | Yes — same. |
| OQ-C | §7 | `hos_worker.sh` does not exist; sequence guard behind it; does interactive PR path need the guard now? | Sequence behind it; apply to interactive PR path now too. |
| OQ-D | §1 | Is the installer a sanctioned writer of `gate-suspension.md` despite the "HUMAN ONLY — agents must not modify" invariant? Needs human + template amendment. | Installer-under-interactive-human is sanctioned; amend the template comment to carve it out. **Human-gated.** |
| OQ-E | §1 | New `capture_session.sh` shim vs. move the canonical script to `scripts/automation/` with `--file/--description` aliases. | Move canonical + add flag aliases (one implementation). |
| OQ-F | §1 | Add a `ts` field (and a `gate-failed` event) to the prompt-capture audit lines, vs. literal 3-key brief shape? | Add `ts` for log consistency; add `gate-failed` for forensics. |
| OQ-G | §3 | `pr_readiness.py` existence for R3.6 self-assessment integration. | Gate R3.6 behind that module; rest of §3 proceeds. |
| OQ-H | §4 | Security FP-rate cannot be computed autonomously (R4.2 needs human confirmation). Two-pass (machine table → human fills → `--score`)? | Two-pass. |
| OQ-I | §4 | Artifact path conflict: brief `audit/automation/...` vs spec R4.5 `audit/...`. | `audit/automation/`; confirm with pm if spec path is load-bearing. |
| OQ-J | §6 | De-dup the dead-man `needs-human` issue across checker runs? | Yes — comment on a recent open dead-man issue instead of re-filing. |
| OQ-K | §7 | Must the worker NOT auto-close the originating issue even when git suggests upstream? | Yes — surface and wait; human confirms the close. |

OQ-D is the only one that is **human-gated** (not architect-resolvable) because it
touches a protected-surface invariant; the rest are architecture/sequencing calls.

---

## Status

**Status: DRAFT — awaiting architect review (iteration 1).** Not handed to the coder.
Per the technical-design loop, I request architect review of: the dependency-sequencing
calls (OQ-A/B/C), the structural-change escalations (§1, §6), and the protected-surface
writer conflict (OQ-D, which also needs a human). I will not declare this design
complete or route to `coder` until the architect approves and OQ-D is resolved by a
human.
