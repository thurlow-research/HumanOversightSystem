# TECHNICAL DESIGN — ADR-033 dual-lens spec-review gate

**Status:** DRAFT 1 — awaiting `architect` review (ADR-033 rev 6 is binding input).
**Date:** 2026-07-31
**Author:** technical-design
**Consumes:** `docs/v0.6.0/ADR-033-dual-lens-spec-review-gate.md` (rev 6)
**Consumer:** the autonomous `worker`, via a `needs-ai` issue.
**Scope note:** this document is the implementation contract. It describes *what the code must
do*. It contains no application code.

---

## 0. Verification findings — ADR premises that do not match the repo

Every claim below was checked against the files on 2026-07-31, not quoted from the ADR.
**VF-1, VF-2, VF-3, VF-4, VF-6, VF-7, VF-8, VF-9, VF-10 all re-verify as stated.** The findings
below are *new* and change the design. They are numbered TD-VF-n to avoid colliding with the ADR's.

### TD-VF-1 (severity: HIGH) — `pr_readiness.py` does not exist. AD-8's "established pattern" is a fourth instance of the VF-1/VF-2/VF-3 failure mode.

ADR-033 line 913 says *"the natural home is the existing pre-dispatch gate family
(`scripts/automation/lib/pr_readiness.py` is the established pattern: exit 0 = pass, non-zero =
do not proceed, `worker.md:8.9`)"*.

`scripts/automation/lib/pr_readiness.py` **does not exist**. `ls scripts/automation/lib/` returns
`breakers.py budget.py claim.py codeowners.py config_resolver.py correlation.py cycle_log.py
envelope.py gate_compliance.py github.py ledger.py merge_authority.py multi_customer.py
next_candidates.jq observability.py overseer_state.py probe.py self_review_source.py
stale_commit_detector.py triage.py` — no `pr_readiness`. `find . -name "pr_readiness*"` returns
nothing.

It is nevertheless cited as a live executable gate in:
- `worker.md:85` — *"run the self-assessment gate (`python -m scripts.automation.lib.pr_readiness`)"*
- `worker.md:233` — step 8.9, *"**Self-assessment gate (deterministic — blocks PR creation)** — run
  `python -m scripts.automation.lib.pr_readiness --cid <cid> --base-sha <base> --head-sha <HEAD>`.
  Exit 0 = PASS → proceed to step 9. Exit non-zero = FAIL → do NOT open a PR."*
- `METHODOLOGY.md:335` — *"`pr_readiness.py`   →  deterministic self-assessment gate (REQ-W-01..W-14)"*
- `docs/specs/SPEC-317-worker-pre-pr-gate.md` (the full checklist REQ-W-01..W-17)
- `docs/v0.4.0/TECHNICAL-DESIGN-317-pre-pr-gate.md` (a complete design for it)

`overseer.md:228` step 4a further says *"Evaluate bounce conditions using **the existing readiness
checks**"* — those checks are the ones this module was to implement.

**Consequence for this work item.** AD-8 must not model its enforcer on a module that was never
written. The design below places the enforcer at **`scripts/oversight/spec_gate.py`** and models it
on `scripts/oversight/signoff_gate.py`, which *does* exist, *is* executable, has `argparse`, a
`main() -> int`, and documented exit codes (0 clean / 1 findings / 2 usage). That is the real
established pattern.

**This is a `startup-artifact-gap` in its own right** and must be filed separately (§10, ISSUE-4).
Do not fix `pr_readiness.py` in this work item — but do **not** write `run
scripts.automation.lib.pr_readiness` anywhere in the new material either.

### TD-VF-2 (severity: HIGH) — AD-14's trigger change is defeated by a *second* tier gate in the caller, and a *third* in prose. Three copies exist; the ADR names one.

`run_second_review.sh` is not self-dispatching. Its caller short-circuits it:

`scripts/run_review_chain.sh:238-244`
```
RUN_AGY=0
RUN_CODEX=0
[[ "$(rank "$TIER")" -ge 1 ]] && RUN_AGY=1    # MEDIUM+
[[ "$(rank "$TIER")" -ge 2 ]] && RUN_CODEX=1  # HIGH+

if [[ $RUN_AGY -eq 0 ]]; then
  skip "second review: tier=$TIER is below MEDIUM — skipping (validators-only gate)"
```

`run_second_review.sh` is **never invoked at all** below MEDIUM. Changing only
`second_review_logic.select_reviewers()` would leave AD-14 inert for precisely the case it exists to
close — the LOW-tier `.md` change (AD-11c / VF-10 / #1079), which in this repository *is the
governed product*.

A third copy is prose: `worker.md:230` step 8.4 — *"**Second review** (MEDIUM+ tier only) — run
`bash scripts/run_review_chain.sh --step N --tier <validated>`."* Note also that it passes
`--tier <validated>` — i.e. `risk-assessor`'s **self-reported** `validated_tier`, which AD-14
explicitly forbids as the trigger input.

**Consequence.** AD-14 requires edits at **three** sites, not one. All three are specified in §6.
This is itself a D41 instance ("one invocation site") and §6 collapses the duplication: the union
predicate is computed once, in `second_review_logic.py`, and both shell callers ask it rather than
re-implementing `rank(TIER) >= 1`.

### TD-VF-3 (severity: HIGH) — `run_panel.sh:385` is a **log string**, not a predicate. There is no author-exclusion predicate to correct; there is only an absence.

ADR item 11 / AD-12's table calls `run_panel.sh:385` *"the roster line `Opus authored → excluded`"*
and marks the change *"Behavioral, not cosmetic."* Verified: line 385 is

```
info "roster ($RISK$( ((SAMPLED)) && echo ' +audit' )): ${ROSTER[*]}   (Opus authored → excluded; Copilot runs natively in CI)"
```

— an `info` echo. The actual behaviour is at `:375-383`, where `ROSTER` is a hard-coded list that
simply never contains a Claude entry:

```
  ROSTER=("agy:correctness")
  [[ "$(rank "$RISK")" -ge 2 ]] && ROSTER+=("codex:security")                     # HIGH+
  [[ "$(rank "$RISK")" -ge 2 ]] && ROSTER+=("codex:adversary")                    # HIGH+ : red-team ALWAYS (D18)
```

`call_model()` at `:128-138` *can* dispatch `haiku` and `sonnet`; the roster never asks it to.
So the family-blanket rule is encoded as *nothing at all* — an unstated invariant.

Two further stale statements are genuinely behavioural because they enter a model's prompt:
- `run_panel.sh:427` — the reviewer prompt asserts *"The author was Claude Opus; you are the
  independent check"*. This is **false today** for inner-loop work: `coder.md` pins
  `claude-sonnet-4-6`. A reviewer is being told a factual untruth about its input.
- `run_panel.sh:12` / `:127` header comments repeat the family-blanket rule.

**Consequence.** §7 does not "correct a predicate"; it **creates** one — an evaluable,
unit-testable `reviewer_admissible()` filter over the roster, backed by the rank registry. Today
the filter admits everything currently in the roster (no Claude entries), so the behavioural delta
is nil *by construction*; the value is that the rule now exists as code and a future roster change
cannot silently violate it. The two prompt/log strings are corrected to rank-relative language and
to the truth.

### TD-VF-4 (severity: MEDIUM) — the pm-agent FR1–FR8 requirements document is not in the repository.

ADR-033's **Inputs** line cites *"pm-agent finalized requirements FR1–FR8 (human-approved)"*.
`grep -rln "FR1\b" --include=*.md .` returns exactly one file: the ADR itself. There is no
`docs/v0.6.0/` requirements doc, nothing in `docs/specs/`, nothing in `.claudetmp/`.

This blocks one specific binding: **AD-6** requires that *"FR2's classification test, the operational
citation test, and the two exhaustive exceptions are transcribed **verbatim** from the
requirements"*. A verbatim transcription of an artifact that does not exist is not possible.

**Consequence.** §5 specifies the both-modes rule using (a) the text already in `worker.md:224-228`,
(b) the fragments the ADR itself preserves (FR2 exception 1 — *"defect correction restoring
behavior an approved artifact already requires"*; the non-exemptions *"it's small" / "it's LOW
risk" / "it only tightens governance" / "high confidence"*; the exemption-citation test in AD-5),
and (c) `docs/AGENTS.md:270-272` + `pm-agent.md:41-43`, which already carry the canonical
clarifying/additive/structural definitions. **Routing:** this is a product/requirements question →
escalated to `pm-agent` (§10, ESC-1). The worker may build §5 from the reconstruction; pm-agent
must commit the FR document and confirm the transcription before the step is signed off.

### TD-VF-5 (severity: MEDIUM) — `agy` now has a JSON output mode. The D41 / HOS#113 premise embedded in `run_second_review.sh` is stale.

`run_second_review.sh:590-591` states *"agy has no JSON-output mode and intermittently returns prose
narration instead of the requested JSON (HOS#113)"*, and `DECISIONS.md` D41 records the same.
Verified against the installed CLI (`agy --help`, 2026-07-31):

```
  --json-schema     Optional JSON schema string or path to a schema file to enforce structured output (for stream-json, only applicable to the final result)
  --output-format   Output format for print mode (text, json, stream-json) (default text)
  --sandbox         Run in a sandbox with terminal restrictions enabled
  -p / --print      Run a single prompt non-interactively and print the response
```

**Consequence.** `run_spec_panel.sh` (new code) SHOULD request `--output-format json` and keep the
proven salvage+single-retry fallback beneath it — belt and braces, honest degradation preserved.
**Do not** rewrite `run_second_review.sh`'s agy invocation in this work item (out of scope, and the
`--output-format json` envelope shape is unverified — the flag exists; its payload was not
exercised). File as ISSUE-6 (§10).

Also note the invocation-form drift: `spec-red-team.md:61` uses `agy --print "…"` with no
`--sandbox`, while `run_second_review.sh:595` uses `agy --sandbox -p "$prompt"` with a recorded
reason (*"agy is an AGENTIC CLI — without this it has run pytest and created files mid-review
(HOS#113). A review step must never write to the tree."*). **`run_spec_panel.sh` uses the
`--sandbox` form.** `spec-red-team.md`'s inline bash block becomes non-normative (§4.3).

### TD-VF-6 (severity: MEDIUM) — AD-14's "asymmetry" argument is fully true only at the structural boundary.

AD-14 justifies swapping the trigger on the grounds that *"Change classification has an independent
mechanical re-derivation"*. Verified: `change_classifier.py` emits `structural_signals`,
`domains_touched`, `tier_floor`, and `structural_modifications`. It **does not emit a
classification**. There is no mechanical re-derivation of the `clarifying` ↔ `additive` boundary —
only of `→ structural` (contract §2a). The contract itself already says so at
`contract/OVERSIGHT-CONTRACT.md:169`: *"Agent prompts must not tell authors 'it will always be
caught' — only signature-bearing additions are mechanically guaranteed."*

**Consequence.** An author self-labelling `additive` work as `clarifying` on a `.md` file with no
§2a signature escapes the classification arm of the union. §6 handles this by (a) **fail-closed
defaults** — absent/unrecognised classification is treated as firing; (b) recording
`classification_source` in the header so the escape is *measurable*; (c) leaving the residual
exception documented rather than papered over. **Do not** let any downstream document claim the
classification trigger is fully audited. This is a narrowing of AD-14's claim, not of its rule.

### TD-VF-7 (severity: MEDIUM) — ADR summary row 7 contradicts AD-7 rev 3 and summary row 12 on whether `run_second_review.sh` is in scope.

Summary table row 7 ends: *"Applying the new posture to `run_second_review.sh` is a deliberate
follow-up, **out of scope**."* That is retained rev-2 text. AD-7 §2 consequence 2 (rev 3) says
*"**Rev-3 revision: this moves back IN scope.**"* and summary row 12 says *"AD-7's outage posture
applied in the same change."*

**Resolution taken:** rev-3 text governs (later revision, and the human's brief for this design
confirms it). Row 7's trailing sentence is stale. §6.3 K5 implements the posture in
`run_second_review.sh`. Flagged for the ADR's own errata.

### TD-VF-8 (severity: MEDIUM) — the AD-7 relaxation delta in `run_second_review.sh` is much smaller than the ADR implies.

AD-7 §2 consequence 2 offers *"codex absent at HIGH+ while agy is up no longer needs to block"* as
the valuable relaxation. Verified at `run_second_review.sh:263-274`: the HIGH+ guard **already**
fails only when `! $AGY_AVAILABLE && ! $CODEX_AVAILABLE`. Codex-absent-while-agy-up already
proceeds. The MEDIUM guard at `:254-261` fails when agy is absent and codex does not fire — under
AD-7 that stays a hard fail (no independent participant would remain).

**Consequence.** §6.3 K5's real content is *honesty and expression*, not permission: (a) name the
absent participant in the header instead of losing it, (b) restate the fail condition as
"would proceeding leave peer review alone?" so the rule is legible and testable, (c) make the
runtime-error-is-absence rule symmetric. Implement it; do not advertise it as a coverage change.

### TD-VF-9 (severity: LOW) — `DECISIONS.md` has two entry formats; "D54 is the current tail" is true only of the numbered series.

Numbered entries run `### D1 …` to `### D54 — 2026-06-17: …`. Entries after that switched to
`## YYYY-MM-DD — Title` with no D-number; the file tail is `## 2026-07-30 — RN calculator JS/TS
sibling, provisional calibration (ADR-032 D7, #1064, S8)`. AD-12 says *"D54 is the current tail"* —
true for the D-series, not for the file.

**Consequence.** §9.1 fixes the exact heading so the entry is both chronologically appended
(append-only, `CLAUDE.md`) and greppable as `D55`.

### TD-VF-10 (severity: LOW, but it degrades the AD-16 deliverable) — the primary Fable citation is a gitignored path.

`.gitignore:2` is `.claudetmp/`. The AD-16 citation table's primary artifact is
`.claudetmp/design/fable-consistency-check.md` (verified present locally, 6075 bytes, mtime
2026-07-29 08:56, alongside `research-findings-draft-2.md`, 11086 bytes). A research note whose
principal citation points into an untracked directory cites something no future reader can open.

**Consequence.** §8 requires the note to (a) **quote the load-bearing content inline** — the B1
finding and the finding counts — and (b) label the path explicitly as *a local, uncommitted working
artifact, not a repository citation*. This closes the gap **without extending the fixed citation
set**, which §8 forbids.

### TD-VF-11 (severity: LOW) — `gh` is unauthenticated in this environment; the issue citations could not be independently verified.

`gh auth status` → *"You are not logged into any GitHub hosts."* `gh issue view 1082` → auth error.
The AD-16 fixed citation set (`#1078`, `#1079`, `#1082`, and issues `#972–#1002`) is therefore
carried forward **on the ADR's and the human's authority, unverified by me**. §8 binds the worker
to verify the fixed set at implementation time if `gh` is authenticated, to **escalate rather than
substitute** on any mismatch, and under no circumstances to extend the set by inference.

### TD-VF-12 (severity: LOW) — `check_agents_static.sh` imposes a build-order constraint.

`scripts/framework/check_agents_static.sh` §3 fails on any path referenced in an agent file that
does not exist on disk, and §2 fails on any agent named `### N. \`name\`` in `docs/AGENTS.md`
without a matching `.claude/agents/<name>.md`. Both are blocking (exit 1).

**Consequence.** `scripts/run_spec_panel.sh` must land **before or in the same commit as**
`.claude/agents/spec-completeness-review.md` (which references it), and the `docs/AGENTS.md` §30
section must land with the agent file. Encoded in the build order (§11).

---

## 1. Terminology (binding, per ADR §1a)

Every artifact this design touches uses these terms and no coined substitutes. Positional language
("the deep pass", "the second model", "qualifying voice") must not appear.

| Term | Meaning in HOS |
|---|---|
| **Peer review** | Review by the same model family as any author, at any class. |
| **Independent review** | Review by a different vendor family from every author, or by the human. **Technical independence only.** |
| **Hold point** | A mandatory verification point beyond which work cannot proceed without approval by the designated authority. |
| **Witness point** | The designated party must be notified and may attend; work may proceed if they do not. |
| **Graduated independence** | Independence *coverage* unconditional; independence *intensity* scaled by integrity level. |

**The canonical rule sentence (ADR binding 16b — quote verbatim, do not paraphrase):**

> At a **hold point**, same-model-different-instance does **not** discharge the requirement. The
> completeness lens is same-family peer review and **cannot by itself discharge the spec panel's
> hold point**; it is discharged because agy (cross-vendor) is also present. **A fable-class lens
> running alone at a hold point is NON-COMPLIANT at any rank.**

**The limitation sentence (state wherever HOS's review layer is characterised):**

> HOS achieves **technical independence** of the reviewing model under a common orchestrator. It has
> **no managerial and no financial independence**. No claim of IV&V-grade independence follows.

---

## 2. Component map

| # | Artifact | Kind | Binding |
|---|---|---|---|
| A | `scripts/oversight/model_rank.py` | NEW module + CLI | AD-10 rank registry |
| B | `scripts/oversight/spec_panel_logic.py` | NEW module + CLI | AD-2, AD-3, AD-4, AD-7 |
| C | `scripts/run_spec_panel.sh` | NEW script | AD-2 (the single invocation site) |
| D | `scripts/oversight/spec_gate.py` | NEW module + CLI | AD-8 (the hold-point enforcer) |
| E | `.claude/agents/spec-completeness-review.md` | NEW agent | AD-1 |
| F | `.claude/agents/spec-red-team.md` | EDIT | AD-4 only |
| G | `.claude/agents/pm-agent.md` | EDIT | AD-8 resolver side |
| H | `.claude/agents/worker.md` | EDIT | AD-6, AD-8, AD-14 |
| I | `.claude/agents/overseer.md` | EDIT | AD-5 (FR8) |
| J | `scripts/oversight/second_review_logic.py` | EDIT | AD-14 union |
| K | `scripts/run_second_review.sh` | EDIT | AD-14 + AD-7 + D55 comment |
| L | `scripts/run_review_chain.sh` | EDIT | AD-14 (TD-VF-2) |
| M | `scripts/run_panel.sh` | EDIT | AD-12 rank-relative predicate (TD-VF-3) |
| N | `scripts/framework/validate_agents.sh` | EDIT | AD-12 comment |
| O | `contract/OVERSIGHT-CONTRACT.md` | EDIT | AD-4, AD-13, AD-5, AD-2 |
| P | `bootstrap/validate_setup.sh` | EDIT | AD-11b Copilot precondition |
| Q | `METHODOLOGY.md` / `CLAUDE.md` / `ARCHITECTURE.md` / `docs/AGENTS.md` / `docs/OVERSIGHT-RUNBOOK.md` / `docs/SETUP.md` | EDIT | FR7 |
| R | `research/findings/<slug>.md` | NEW | AD-16 |
| S | `DECISIONS.md` | APPEND | AD-12 (D55) |
| T | `scripts/framework/consumer_agents.txt`, `bootstrap/hos_install.sh`, `.claude/agents/framework-setup-validator.md` | EDIT | AD-1 registration |
| U | `tests/oversight/`, `tests/framework/` | NEW tests | §12 |

**Explicitly NOT built** (ADR out-of-scope): bounce helper functions (VF-3); region-marker migration
for the other twelve agents (VF-7); the #1122 alias sweep across the other 29 agents; any
`reason_category` enum extension; `TIER_FLOOR_*` extension to `.md`; adding a same-family reviewer
to the `run_panel.sh` roster; implementing `pr_readiness.py` (TD-VF-1).

---

## 3. Component A — `scripts/oversight/model_rank.py` (rank registry)

**Purpose.** AD-10 requires "independent", "higher" and "sole" to be evaluable predicates, held in
*one* table so a new model does not require edits in N places. Components B, C, D and M all consume
it.

**Purity.** No subprocess, no network. File reads limited to agent frontmatter when explicitly asked
(`agent_class`). Unit-testable with synthetic inputs. Matches the SPEC-331 purity discipline
recorded in `second_review_logic.py:20-24`.

### 3.1 Data

| Name | Value | Notes |
|---|---|---|
| `CLASS_RANKS` | `{"haiku": 1, "sonnet": 2, "opus": 3, "fable": 4}` | Human-ruled ordering. The **only** place the ordering appears. |
| `FAMILY` | `{"haiku": "claude", "sonnet": "claude", "opus": "claude", "fable": "claude"}` | All four are the Claude family. Cross-vendor CLIs are **not** in the registry. |
| `CROSS_VENDOR_CLIS` | `{"agy", "codex", "copilot"}` | Recognised independent-review participants. Rank-less **by design** — they satisfy rule (2), never rule (1). |
| `DEFAULT_COMPLETENESS_CLASS` | `"fable"` | AD-3: rank 4 binds *as the demonstrated configuration pending better evidence*. **The single point of operator step-down** — changing this constant to `"opus"` is a quality decision requiring no governance change (AD-3 (1)). The docstring must say exactly that. |
| `DEFAULT_ADVERSARIAL_CLI` | `"agy"` | AD-3. |
| `BUNDLE_AUTHOR_AGENTS` | `("pm-agent", "architect", "technical-design")` | VF-9: the agents that author the spec bundle. |

### 3.2 Functions (contracts)

- `rank(class_alias: str) -> int | None`
  Case-insensitive lookup in `CLASS_RANKS`. **Unregistered → `None`, never a default.** AD-10:
  *"An unregistered model has no rank and therefore cannot satisfy any class-differential
  requirement — fail-closed, not 'assume highest'."*

- `class_of(model: str) -> str | None`
  Accepts a class alias (`"opus"`) **or** a resolved/pinned model ID (`"claude-opus-4-8"`). Returns
  the class alias, or `None` if no registered class token appears in the string. Matching is on a
  word/segment boundary against the `CLASS_RANKS` keys — never a bare substring scan, so a future
  ID containing an unrelated occurrence cannot false-match. `None` propagates to rank `None`.

- `is_cross_vendor(participant: str) -> bool`
  True iff `participant` is in `CROSS_VENDOR_CLIS`. **Note the asymmetry and preserve it:** a
  cross-vendor participant is rank-less *and that is correct* — rules (1) and (2) are orthogonal
  (AD-10). Do not "fix" this by giving agy a rank.

- `agent_class(agent_path: Path) -> str | None`
  Reads the first `^model:` line of an agent file's YAML frontmatter and returns `class_of()` of its
  value. Missing frontmatter, missing `model:`, or unregistered value → `None`.

- `highest_author_rank(agent_paths: Iterable[Path]) -> tuple[int | None, list[dict]]`
  Returns `(max_rank_or_None, evidence)` where each evidence row is
  `{"agent": <slug>, "declared": <raw model: value>, "class": <alias|null>, "rank": <int|null>}`.
  **If any author's class is unregistered, the returned rank is `None`** (fail-closed: an unknown
  author rank cannot be shown to be strictly below the lens). The evidence list always names which
  agent caused it.

- `is_class_differential(lens_rank: int | None, author_rank: int | None) -> bool`
  `True` iff both are integers and `lens_rank > author_rank`. Any `None` → `False`.
  **Strictly greater.** Equal rank is same-class self-validation, the prohibited case (AD-10 / D55
  rule (1)).

- `reviewer_admissible(reviewer_class: str | None, reviewer_cli: str, author_rank: int | None) -> tuple[bool, str]`
  The AD-12 / TD-VF-3 exclusion predicate, used by Component M.
  - `is_cross_vendor(reviewer_cli)` → `(True, "cross-vendor")`.
  - Same-family reviewer with `is_class_differential(rank(reviewer_class), author_rank)` →
    `(True, "class-differential peer review")`.
  - Otherwise → `(False, "same-family at or below author rank")`.
  The reason string is written into the panel log so the exclusion is *visible*, not silent.

### 3.3 CLI

`python3 scripts/oversight/model_rank.py <subcommand>`, JSON to stdout, exit 0 always for reporter
subcommands (the caller decides), exit 2 on usage error. Subcommands:

- `rank --class <alias>` → `{"class": "...", "rank": 4|null}`
- `resolve --model <alias-or-id>` → `{"input": "...", "class": "...", "rank": N|null, "family": "claude"|null}`
- `author-rank [--agents-dir .claude/agents] [--agent NAME ...]` → `{"highest_rank": N|null, "highest_class": "...", "evidence": [...]}`; with no `--agent`, defaults to `BUNDLE_AUTHOR_AGENTS`.
- `differential --lens-class <alias> --author-rank <N>` → `{"class_differential": true|false}`
- `defaults` → `{"completeness_class": "fable", "adversarial_cli": "agy"}`

**Header comment must state:** this table is the single source of truth for the class ordering; it
is referenced by `DECISIONS.md` D55; adding a model class requires adding it here and nowhere else;
an unregistered class is fail-closed by design.

---

## 4. Components B + C — the paired gate

### 4.0 Why the logic is a Python module and the shell only launches

Repo policy #314 (recorded in `second_review_logic.py:15`): *"prefer Python for logic, shell for
launch."* AD-2 additionally requires the gate be verifiable from an artifact. Splitting them means
the AD-7 posture, the AD-4 taxonomy validation, the header rendering and the dedup rule are all
unit-testable **without a live model** — which is the only way the fail-closed branches ever get
exercised. `run_spec_panel.sh` owns: argument parsing, env reading, CLI availability probing,
CLI invocation, and exit codes. `spec_panel_logic.py` owns everything else.

### 4.1 Component B — `scripts/oversight/spec_panel_logic.py`

Pure (no subprocess/network); the `__main__` shim does stdin/stdout and file writes only.

**B1 `bundle_digest(paths: list[Path]) -> tuple[str, list[dict]]`**
Returns `(bundle_sha, files)` where `bundle_sha` is the SHA-256 over the concatenation of, for each
path in **sorted order**, the UTF-8 bytes of `f"{relative_path}\n"` followed by the file bytes
followed by `b"\n"`. `files` is `[{"path": ..., "sha256": ..., "bytes": N}]`. Sorted order and the
path prefix make the digest stable and make a rename detectable. A missing path is a hard error
(caller exits 2) — never silently skipped, or the bundle hash would certify a bundle that was not
read.

**B2 `resolve_participants(...) -> ParticipantSet`**
Inputs: `adversarial_cli`, `adversarial_available: bool`, `completeness_model`,
`completeness_available: bool`, `author_rank: int | None`, plus a per-lens runtime status
(`ran | absent | error | unparseable`). Computes and returns:
- `completeness_class`, `completeness_rank` (via Component A)
- `completeness_lens_class_differential` (Component A `is_class_differential`)
- `independent_participants: int` — count of participants that are cross-vendor **and** whose
  status is `ran` or `unparseable`. **Status `error` counts as absent**, per AD-7 (*"Runtime errors
  are treated as absence, not as approval"*) and `contract:544-546`.
- `hold_point_discharged: bool` — `independent_participants >= 1`.
- `fr1_dual_lens_satisfied: bool` — both lenses' status in `{ran, unparseable}`.

**B3 `decide(participants: ParticipantSet) -> Decision`** — the AD-7 posture, in one place.
Returns `(blocked: bool, block_reason: str, owner: str, message: str)`.

| Condition | `block_reason` | Owner | Exit |
|---|---|---|---|
| Env/config violation (see C3) | `CONFIG_REJECTED` | operator | 3 |
| `hold_point_discharged == False` | `RULE2_SOLE_SAME_FAMILY` | architect (rule 2) | 1 |
| `hold_point_discharged == True` but `fr1_dual_lens_satisfied == False` | `FR1_LENS_ABSENT` | pm-agent / human (FR1) | 2 |
| otherwise | `none` | — | 0 |

**The two blocked cases MUST NOT be collapsed into one message.** AD-7 §2 consequence 1: *"The
correct implementation records which rule blocked, because the two have different owners and
different remedies."* The message text names the owner and the remedy:
- `RULE2_SOLE_SAME_FAMILY` → *"Proceeding would leave a sole same-family voice deciding a hold
  point. A fable-class lens running alone at a hold point is NON-COMPLIANT at any rank. Restore the
  cross-vendor adversarial lens, or obtain a human bypass at
  `.claudetmp/oversight/spec-panel-bypass.md`."*
- `FR1_LENS_ABSENT` → *"Independent review is present (agy), so rule (2) holds — but FR1 makes the
  dual lens unconditional and the completeness lens did not run. Only the human may re-scope FR1."*

**B4 `classify_lens_output(raw: str) -> tuple[str, dict | None]`**
Returns `(status, parsed)` with status in `{ran, unparseable, error}`.
- Empty/whitespace raw → `("error", None)` (invocation failure).
- Parseable review object → `("ran", obj)`.
- Non-empty but unparseable → `("unparseable", None)`. **`unparseable` is preserved, never
  promoted to `error` and never demoted to `pass`** — HOS#113, binding at `contract:548`.
JSON extraction **reuses `scripts/oversight/panel_logic.py extract-json`** (one invocation site,
D41). Do not re-implement a brace scanner.

**B5 `validate_findings(findings, lens) -> tuple[list[dict], list[str]]`**
Enforces the AD-4 canonical schema per finding. Errors (not warnings) on: unknown `gap_type`;
`gap_type` not permitted for that lens (`missing-scope` is completeness-only; `contradiction`,
`gaming-vector`, `implicit-assumption`, `missing-edge-case` are adversarial-only; `ambiguity` and
`missing-requirement` are either); `lens` value not exactly one of `adversarial | completeness`;
missing required field. A finding failing validation is **retained and flagged**, never dropped —
dropping a real finding to satisfy a schema is the fail-open shape D41 warns about. Flagged
findings appear in the artifact under `## Schema-invalid findings (human must read)` and force
verdict `unparseable`.

**B6 `dedupe(adversarial: list, completeness: list) -> tuple[list, list]`**
AD-4: *"the same finding independently raised by both lenses is filed once with the first lens
recorded and a `Corroborated-by:` note, so the provenance metric measures disjointness."*
Matching key: normalised (`casefold`, whitespace-collapsed, punctuation-stripped) tuple of
`(gap_type, spec_section, first 12 significant tokens of finding)`. On a match, keep the
**adversarial** record (deterministic tie-break: the adversarial lens runs first) and set
`corroborated_by: completeness`. Returns `(to_file, corroborations)`. **The dedup must never merge
across different `gap_type` values** — that would destroy the disjointness measurement that is the
entire research value of the pair.

**B7 `render_header(...) -> str`** — the machine-readable header (§4.2 exact field list).
**B8 `render_issue_body(finding) -> str`** — the AD-4 issue body (§4.4).
**B9 CLI subcommands:** `bundle-digest`, `classify` (stdin), `validate-findings` (stdin),
`dedupe` (stdin), `decide` (stdin JSON of the participant set), `render-header` (stdin JSON).

### 4.2 Component C — `scripts/run_spec_panel.sh`

**Path:** `scripts/run_spec_panel.sh`. **Structural model:** `scripts/run_second_review.sh` — same
shape for arg parsing, availability pre-check, per-vendor invocation, machine-readable header
first / rewritten last, non-zero exit on fail-closed.

**C1 — Usage**
```
./scripts/run_spec_panel.sh --step <N> [--cid <id>] --bundle <path> [--bundle <path> ...]
                            [--out-dir .claudetmp/spec-panel] [--dry-run] [--no-issues]
```
- `--step` **required** (names the artifact; matches `run_second_review.sh:153-156` behaviour).
- `--bundle` repeatable, **at least one required**. Convention: pm requirements doc, the ADR, the
  technical design. If `SPEC_FILE` is set in `scripts/framework/config.sh` and no `--bundle` is
  given, `SPEC_FILE` is used and a WARN is printed that the bundle is spec-only. Sourcing
  `config.sh` follows the existing pattern at `run_second_review.sh:370`.
- `--dry-run` resolves models, computes ranks and the bundle digest, writes the header with
  `verdict: dry-run`, invokes no model, exits 0. This is the hermetic test entry point.
- `--no-issues` suppresses `gh issue create` (tests, and reruns after issues already exist).

**C2 — Output**
`.claudetmp/spec-panel/step{N}-{ISO-timestamp}.md`, timestamp format `%Y%m%dT%H%M%S` (matching
`run_second_review.sh:277`). `mkdir -p` the directory. Register the location in the contract §1
filesystem protocol (§7.1).

**C3 — Env knobs, one-way only (AD-2 anti-tamper, AD-3)**

Two knobs, read **from the real environment only**. Unlike `run_second_review.sh`, the repo-local
`.env` is **not** consulted at all: `run_second_review.sh:67-77` reads `.env` because thresholds
have a legitimate operator-tuning use; a *lens identity* has none, and `.env` is author-controlled.
Reading it would reintroduce HOS#985 through a wider door. State that reason in the header comment.

| Var | Purpose | Accepted |
|---|---|---|
| `OVERSIGHT_SPEC_ADVERSARIAL_CLI` | retarget the adversarial lens | a value in `CROSS_VENDOR_CLIS` |
| `OVERSIGHT_SPEC_COMPLETENESS_MODEL` | retarget/step-down the completeness lens | a value resolving via `model_rank.resolve` to a **registered class with a rank** |

**Rejections — all exit 3, before any model is invoked, with the offending value echoed:**
1. Empty string, or any of `none`, `off`, `skip`, `disabled`, `0`, `false` — **a lens may not be
   disabled**, only retargeted.
2. Both knobs resolving to the same participant — *"One model running both prompts is not a degraded
   dual-lens; it is a single-lens gate wearing a dual-lens verdict"* (AD-3).
3. `OVERSIGHT_SPEC_COMPLETENESS_MODEL` resolving to rank `None` (unregistered class) — AD-10
   fail-closed.
4. `OVERSIGHT_SPEC_ADVERSARIAL_CLI` resolving to a same-family model — that would zero the
   cross-vendor count, which no knob may do.

**Note the deliberate asymmetry with AD-3's rank rule:** a same-*class* completeness lens (rank 3
over rank-3 authors) is **accepted and run**, with `completeness_lens_class_differential: false`
recorded. AD-3: *"It does not refuse a same-class run, because AD-3's operator step-down must stay
available without a code change — a hard refusal would convert a quality decision back into a
governance one."* An **unregistered** lens is refused; a **same-class** lens is recorded. Do not
conflate these two branches; add a test for each (§12).

**C4 — Availability pre-check**
`command -v agy`, `command -v claude` (mirrors `run_second_review.sh:240-241`). Additionally, the
completeness lens may fail at *invocation* if the runtime rejects the class alias (the `fable` alias
is unverified in this environment — see §5.2 of the ADR's #1122 constraint). Both an unavailable CLI
and a rejected alias produce lens status `absent`/`error`; both flow through B2/B3 identically. The
script must not special-case them.

**C5 — Lens invocation**

*Adversarial lens (agy, cross-vendor, independent):*
- Command form: `agy --sandbox --output-format json -p "$prompt"`, falling back to
  `agy --sandbox -p "$prompt"` if the first form exits non-zero with an unrecognised-flag signature.
  `--sandbox` is **mandatory** (`run_second_review.sh:584-586`: agy has written to the tree
  mid-review — HOS#113). Then salvage + **one** hard JSON-only retry, exactly as
  `run_second_review.sh:594-619`.
- Prompt: built from `.claude/agents/spec-red-team.md`'s probe taxonomy (gaming vectors,
  contradictions, implicit assumptions, missing edge cases, scope-creep). **Bundle is passed
  untruncated** — see C6.

*Completeness lens (same-family, class-differential peer review):*
- Command form: `claude -p --model "$COMPLETENESS_MODEL" "$prompt"` (the dispatch shape at
  `run_panel.sh:131-132`). Salvage + one retry identically.
- Prompt: built from `.claude/agents/spec-completeness-review.md`'s coverage framing (§5.1).
- **Order is fixed: adversarial first, completeness second.** Deterministic, and it makes the B6
  tie-break (`keep the adversarial record`) meaningful.

**C6 — Context regimes differ and must not be unified**
- Adversarial lens: preserves `spec-red-team`'s existing regime. SPEC-379 deliberately excluded
  `spec-red-team` from diff-centric context (`SPEC-379-diff-centric-review-context.md:46,135,141`;
  `TECHNICAL-DESIGN-379:50,85-87,223` — *"MUST NOT modify `spec-red-team`"*).
- Completeness lens: **full untruncated bundle plus surrounding repo context** (FR3 / AD-1 reason 2).
  Concretely: every `--bundle` file in full, plus a listing of `docs/`, `contract/`, and
  `.claude/agents/` filenames so the lens can detect silent contradictions with existing repo docs
  (the #1059 `missing-scope` class). No `head -N` anywhere.
- **The `head -200` / `head -100` truncation at `spec-red-team.md:69,72` must not be reproduced in
  `run_spec_panel.sh` for either lens.** It is the ADR's originally-cited defect.

**C7 — The header (written first with `verdict: pending`, rewritten last)**

Exact field list. Every field is emitted on **every** path including the fail-closed ones — an
absent field is indistinguishable from a false one, which is the failure D41 names.

```
# Spec Panel — Step {N}
Timestamp: {ISO}
verdict: pass | findings | error | unparseable | dry-run
step: {N}
cid: {cid|none}
bundle_sha: {sha256}
bundle_files: {n}
bundle_paths: {comma-separated}
adversarial_cli: {agy|...}
adversarial_model_resolved: {string|unknown}
adversarial_status: ran | absent | error | unparseable
completeness_cli: claude
completeness_model_resolved: {string|unknown}
completeness_class: {alias|unregistered}
completeness_rank: {1..4|none}
completeness_status: ran | absent | error | unparseable
author_agents: pm-agent,architect,technical-design
author_highest_class: {alias|unknown}
author_highest_rank: {int|none}
completeness_lens_class_differential: true | false
independent_participants: {int}
hold_point_discharged: true | false
fr1_dual_lens_satisfied: true | false
block_reason: none | CONFIG_REJECTED | RULE2_SOLE_SAME_FAMILY | FR1_LENS_ABSENT
absent_participants: {comma-separated|none}
findings_count: {int}
findings_adversarial: {int}
findings_completeness: {int}
corroborated_count: {int}
issues_created: {comma-separated issue numbers|none}
completeness_prompt_tokens: {int}
completeness_output_tokens: {int}
completeness_total_tokens: {int}
completeness_tokens_source: actual | estimated
adversarial_prompt_tokens: {int}
adversarial_output_tokens: {int}
adversarial_total_tokens: {int}
adversarial_tokens_source: actual | estimated
bypass_consumed: true | false
```

`completeness_*_tokens` is AD-3 binding (3), *"a binding deliverable, not a nice-to-have"*. In
addition to the header, record it through the existing tracker — no new ledger:
```
python3 scripts/oversight/token_tracker.py record --vendor claude --stage spec-panel-completeness \
    --step "$STEP" --prompt-chars N --output-chars N [--actual-prompt-tokens N --actual-output-tokens N]
```
`--vendor claude` and `--vendor agy` are already in the tracker's `choices` list
(`token_tracker.py:249`) — **no enum extension is needed and none may be made**. Use stages
`spec-panel-completeness` and `spec-panel-adversarial`.

Carry AD-3's qualifier into the script header comment, verbatim in substance:
> The completeness lens runs at rank 4 (`fable`) as **the demonstrated configuration pending better
> evidence**, not as an established requirement — the evidence is n=1 and confounded with running
> last. Stepping down to rank 3 degrades quality only; the panel's independent review (agy) and the
> hold point are unaffected, so it is an operator decision needing no governance change, no ADR
> revision and no human gate. Recommended step-down thresholds (defaults, not gates): sustained
> weekly utilization >50% → consider rank 3; >80% → step down.

**C8 — Verdict and exit codes**

| Verdict | When | Exit |
|---|---|---|
| `pass` | both lenses `ran`, zero findings | 0 |
| `findings` | both lenses `ran`, ≥1 finding filed | 0 |
| `unparseable` | ≥1 lens `unparseable`, none blocked | 0, with a loud *"a human must read this"* notice modelled on `run_second_review.sh:853-865` |
| `error` | blocked | 1 / 2 / 3 per B3 |
| `dry-run` | `--dry-run` | 0 |

`unparseable` is **not** `error` and **not** `pass` (AD-2, `contract:548`). A panel artifact with
`verdict: unparseable` **does** satisfy the AD-8 gate's artifact-exists / non-`error` test, and
raises a conditional item for a human. State that explicitly in both places or the two will drift.

**C9 — Human bypass**
Before deciding, check `.claudetmp/oversight/spec-panel-bypass.md`. If present and it names this
`step`/`cid` and is unexpired, set `bypass_consumed: true`, emit the audit event
`spec-panel-bypass-consumed` (§7.4), and exit 0 with `verdict` unchanged and `block_reason` still
recorded. **Agents may read this file; they may never create or modify it** — same class as
`human-authorization.md` / `human-tier-override.md` (`contract:77-93`). Register it in the contract
artifact table (§7.1) with fields `step`/`cid`, `reason`, `scope`, `expiry`.

### 4.3 Issue creation

Both lenses' findings become `spec-gap` GitHub issues, created by `run_spec_panel.sh` — **not** by
either agent. Title convention (`contract:375-379,392`):
```
[AI: spec-red-team] spec-gap: <topic> — <one-line>          # adversarial lens
[AI: spec-completeness-review] spec-gap: <topic> — <one-line>   # completeness lens
```
Body: the §7.2 canonical block. Footer: the mandatory `contract:381-386` AI footer.
`gh` unavailable/unauthenticated → **do not fail the panel**, but set `issues_created: none` and
append a loud `## [BLOCKING] Findings not filed` section listing every finding verbatim, and print a
non-suppressible warning. The findings still exist in the artifact, and the AD-8 gate (§5.3) will
block the coder anyway because it also fails closed when `gh` is unqueryable. Rationale: losing a
finding is worse than a noisy artifact; passing a gate you could not evaluate is worse than both.

---

## 5. Components D + E + F + G + H — the hold point and its agents

### 5.1 Component E — `.claude/agents/spec-completeness-review.md` (NEW)

A **sibling** of `spec-red-team`, not an extension (AD-1). Ships **with** `HOS:CORE` / `HOS:PROJECT`
region markers (VF-7 constraint on new files), matching the layout of `.claude/agents/pm-agent.md`
(`<!-- HOS:CORE:START -->` … `<!-- HOS:CORE:END -->`, then `## Project Extensions (yours — HOS never
writes here)` and `<!-- HOS:PROJECT:START -->` … `<!-- HOS:PROJECT:END -->`).

**Frontmatter:**
```
name: spec-completeness-review
description: >
  Reviews a spec bundle for entire unaddressed scope areas before coding begins. The
  coverage counterpart to spec-red-team's adversarial lens: spec-red-team checks the
  bundle against itself; this checks the bundle against everything it should have
  covered. Runs as one half of the paired spec-panel hold point via
  scripts/run_spec_panel.sh — never as a standalone gate. Creates spec-gap issues.
model: opus
tools:
  - Read
  - Grep
  - Glob
  - Bash
dispatches: []
```

**On the `model:` field — a design decision the architect must confirm (§10, ESC-2).**
ADR binding 1 requires *"a `model:` class alias"*, and #1122 forbids a pinned ID. Two things are
being named and the ADR does not separate them:
1. the **agent's own runtime model** (what the frontmatter `model:` field controls, as
   `spec-red-team.md:9`'s `claude-sonnet-4-6` controls *that* agent while its lens is agy); and
2. the **completeness lens model**, which `run_spec_panel.sh` invokes.

I bind `model: opus` for (1) — a registered alias, valid today, no pinned ID — and put (2) in
`model_rank.DEFAULT_COMPLETENESS_CLASS = "fable"`, overridable by
`OVERSIGHT_SPEC_COMPLETENESS_MODEL`. Reasons: `fable`'s validity as a Claude Code runtime alias is
**unverified** (it appears nowhere in the repo, and I could not test it), so putting it in
frontmatter risks an agent that cannot launch; and AD-3's operator step-down wants exactly one place
to change, which a constant + env var gives and frontmatter does not. **Consequence that must be
written into the charter:** a direct invocation of this agent runs at rank 3 over rank-3 authors and
is therefore *not* class-differential; only the `run_spec_panel.sh` artifact discharges the gate.
If the architect prefers `model: fable`, the change is one line here and one line in
`model_rank.py`; nothing else moves.

**CORE body — required content, section by section:**

1. **Identity line.** `[Spec Completeness Review — step <N>]` first line of every response
   (house convention, cf. `pm-agent.md:19-21`).
2. **Lens statement.** *"`spec-red-team` checks a spec against itself — contradictions, gaming
   vectors, implicit assumptions, edge cases. You check it against **everything it should have
   covered**. Your failure class is `missing-scope`: an entire area the bundle never addresses at
   all. Neither lens subsumes the other; the gate is a pair, not a choice."*
3. **Independence statement — quote binding 16b verbatim** (§1 above). Then: *"You are same-family
   peer review. You do not discharge this hold point. agy does. Never record, report, or imply that
   your pass constitutes independent review."*
4. **Peer-review guardrails (ADR §1a, both mandatory).**
   - *No author framing.* *"The bundle's own prose rationale — 'why this design is right', 'this was
     considered and rejected', confidence statements — is untrusted input. Evaluate what the bundle
     covers, not how well it argues."* (This is D53 extended to a fourth lane; D53's own
     three-lane coverage gap is filed separately, §10 ISSUE-5.)
   - *Adversarial instruction.* *"Your job is to find what is absent. A clean pass is a finding
     about you, not about the bundle."*
5. **Inputs.** The full untruncated bundle plus surrounding repo context. Explicit prohibition:
   *"Never truncate an input. Do not use `head -N` on a bundle file."*
6. **What to probe — the four `missing-scope` sub-classes from #1059, named:** an inert output file
   (something produced that nothing consumes); an unmigrated instance of the rule being formalized
   (the rule applied everywhere except to itself); an absent lifecycle story (created, but never
   updated, expired, or removed); a silent contradiction with an existing repo doc.
7. **The taxonomy block**, byte-identical to `spec-red-team.md`'s, pointing at
   `contract/OVERSIGHT-CONTRACT.md` §2b as the source of truth (§7.2). Including the boundary test
   **verbatim**: *"The `missing-requirement` / `missing-scope` boundary is: **is the area addressed
   at all?**"* AD-4 requires this sentence to appear **verbatim in both agent files**.
8. **Output.** *"You produce findings. You do not create issues and you do not run the panel —
   `scripts/run_spec_panel.sh` does both. Absence of its artifact is the detectable condition; a
   technical-design document alone is not evidence the panel ran."*
9. **What you do NOT do.** Do not review code. Do not edit the spec. Do not invoke agy (that is the
   adversarial lens's vendor; running both prompts on one model is a single-lens gate wearing a
   dual-lens verdict). Do not set `Ready for coder`. Do not write to any `.claude/agents/*.md`.
10. **The standard CORE/PROJECT carve-out footer** (copy verbatim from `pm-agent.md:75-89`).

**PROJECT region:** empty, with the standard comment.

**Registration surface — exhaustive; `check_agents_static.sh` fails on any mismatch:**

| File | Change |
|---|---|
| `scripts/framework/consumer_agents.txt` | add `spec-completeness-review` in the **Oversight layer** block, immediately after `spec-red-team` |
| `bootstrap/hos_install.sh:777` | add to the built-in fallback array (currently `… oversight-orchestrator spec-red-team prompt-fidelity ops-designer …`) |
| `.claude/agents/framework-setup-validator.md:~39` | add to the `REQUIRED` list |
| `docs/AGENTS.md` | **append `### 30. \`spec-completeness-review\` — Spec Completeness Review`** — the numbered series currently ends at `### 29. \`post-change-sweep\``, so §30 is the next free number and **nothing is renumbered**; also update the agent-list block at `:130-131` (`SPEC REVIEW (before coding starts)`), the escalation map (add `spec-completeness-review └── escalates to: pm-agent (spec gaps)` beside the existing `spec-red-team` entry at `:1019-1020`), and the oversight-agent roster at `:1052` (and its "26 agents" count → 27) |
| `ARCHITECTURE.md:81` | add a table row beside `spec-red-team` |
| `ARCHITECTURE.md:157` | mermaid — `SRT` becomes a paired node (§7.5) |
| `METHODOLOGY.md:174` | mermaid — spec-phase node relabelled (§7.5) |
| `CLAUDE.md` | oversight-layer agent table + the pipeline block's `SPEC PHASE` section |
| `contract/OVERSIGHT-CONTRACT.md:392` | issue-title convention row |
| `docs/OVERSIGHT-RUNBOOK.md:253-263` | PHASE 0 rewritten (§7.5) |
| `docs/SETUP.md:94` | `SPEC_FILE` consumers list — add `spec-completeness-review` |
| `tests/framework/test_consumer_agents_canonical.py:38-39` | add to the `test_core_oversight_agents_present` list |

### 5.2 Component F — `.claude/agents/spec-red-team.md` (EDIT — taxonomy only)

**AD-4 scope discipline: nothing but the taxonomy changes.** Charter, vendor (`agy`), the
`Do not invoke codex` line at `:124`, and the model frontmatter all stay. The `head -200`/`head -100`
truncation at `:69`/`:72` stays *in this file* — it is now non-normative (the panel builds the
prompt), and removing it is a charter change the ADR did not authorise. Add one line above the bash
block instead:

> *"The block below is illustrative. In the pipeline this lens is invoked by
> `scripts/run_spec_panel.sh`, which builds the prompt and passes the bundle untruncated; the
> `head -N` calls here are a manual-invocation convenience, not the pipeline's context regime."*

**Edit 1 — the `gh issue create` body, `:83`.** Anchor:
```
     --body "**Build step:** [N]\n**Type:** [gaming-vector|contradiction|implicit-assumption|missing-edge-case]\n**Finding:** ...
```
Replace `**Type:** [...]` with the canonical `**Gap type:**` field and add `**Lens:** adversarial`.
Also replace the whole `gh issue create` invocation with a pointer: *"You do not create issues in
the pipeline — `scripts/run_spec_panel.sh` does, from your findings, using the canonical schema in
`contract/OVERSIGHT-CONTRACT.md` §2b. The block below is retained only for manual invocation."*

**Edit 2 — the required-fields block, `:103-113`.** Anchor:
```
**Required fields on every spec-gap issue body:**
```
```
**Gap type:** [ambiguity | missing requirement | contradiction | implicit assumption]
```
Replace the entire fenced block with the §7.2 canonical block, including `Lens:` and
`Corroborated-by:` and the verbatim boundary sentence.

**Edit 3 — `:115`.** Anchor: *"pm-agent resolves the issue by: updating the spec, setting
`Ready for coder: YES`, and noting the change classification."* Extend to name the enforcer:
*"…`Ready for coder: YES`… The field is enforced: `scripts/oversight/spec_gate.py` refuses to
dispatch the coder while any open `spec-gap` issue for the step lacks it."*

**Result: exactly one taxonomy in the file, sourced from the contract.**

### 5.3 Component D — `scripts/oversight/spec_gate.py` (the AD-8 enforcer)

**This is the hold point's signature check.** AD-15 / binding 14: *"an ITP hold point the traveller
can walk past is not a hold point."* Prose cannot implement it — VF-1, VF-2, VF-3 and TD-VF-1 are
four independent demonstrations.

**Pattern:** modelled on `scripts/oversight/signoff_gate.py` — `argparse`, `main() -> int`,
documented exit codes, module docstring explaining the workflow. **Not** on
`scripts/automation/lib/pr_readiness.py`, which does not exist (TD-VF-1).

```
python3 scripts/oversight/spec_gate.py --step <N> [--cid <id>] [--repo-root .] [--json]
```

**Checks, in order; evaluation continues after a failure so the operator sees every blocker at
once (the SPEC-317 §3 convention).**

| id | Check | On failure |
|---|---|---|
| `SPEC-PANEL-ARTIFACT-MISSING` | Newest `.claudetmp/spec-panel/step{N}-*.md` exists | FAIL — name the expected glob and the command to run |
| `SPEC-PANEL-VERDICT-ERROR` | That artifact's `verdict:` is not `error` | FAIL — echo `block_reason` and its owner |
| `SPEC-GAP-NOT-READY` | Every open `spec-gap` issue for the step/cid carries `Ready for coder: YES` | FAIL — list the blocking issue numbers |
| `SPEC-GATE-UNQUERYABLE` | `gh` is present and authenticated | **FAIL** — see below |

**`SPEC-GATE-UNQUERYABLE` fails closed, deliberately.** If `gh` cannot list issues, the gate cannot
know whether an unresolved blocker exists. Passing would make the enforcer indistinguishable from
the prose gate it replaces. Distinct message: *"Cannot verify spec-gap resolution — `gh` is
unavailable or unauthenticated. This gate does not pass on an evaluation it could not perform. Run
`source <(bootstrap/get_app_token.sh --app worker)` and retry."*

**Issue matching.** `gh issue list --label spec-gap --state open --json number,title,body --limit 200`,
then match on a `**Build step:** {N}` line or a `**CID:** {cid}` line in the body. An open `spec-gap`
issue that matches *neither* is reported as `SPEC-GAP-UNSCOPED` — a **WARN**, not a FAIL (it may
belong to another step), but it is printed so an unscoped issue is visible rather than silently
ignored.

**Exit codes:** `0` all checks pass; `1` one or more blocking checks failed (do not dispatch coder);
`2` usage error or unreadable repo. `--json` emits
`{"gate":"spec","step":N,"pass":bool,"checks":[{"check_id","status","detail"}]}` for the worker to
quote into a bounce/escalation body.

**`Ready for coder: YES` matching is exact and case-sensitive on the token `YES`.** `Ready for
coder: yes`, `Ready for coder: YES (pending)`, and `Ready for coder: [will be set…]` (the template
placeholder at `spec-red-team.md:112`) all **fail**. A gate whose sentinel matches its own unfilled
template is not a gate.

### 5.4 Component G — `.claude/agents/pm-agent.md` (the resolver side)

`pm-agent.md` currently never mentions the field (VF-2 confirmed). Insert a new section between
`## Spec-update path` (ends `:47`) and `## Test-plan sign-off` (`:49`), inside the CORE region.

Anchor for the edit — insert after this line:
> **Never** rewrite the spec to rationalize already-built code that misses it — that is spec
> falsification. Surface the discrepancy and let the human decide.

New section content (contract, not prose to copy blindly):

- **Heading:** `## Resolving spec-gap issues — the `Ready for coder` signature`
- The spec panel is a **hold point**. `Ready for coder: YES` is its signature and you are the named
  signer. The coder is the traveller; it cannot advance past your signature. Quote the human's
  recorded rationale verbatim: *"Spec panel is hold point. Work could be invalidated, so don't start
  until we know specs good."*
- Set `Ready for coder: YES` on a `spec-gap` issue **only after** the underlying gap is resolved in
  the spec (or explicitly dispositioned as not-a-gap with the reason recorded on the issue). Never
  as a batch action, never to unblock a waiting coder.
- **`structural` changes require a human approval link on the issue before `Ready for coder: YES`.**
  Cite the approving comment/issue URL in the `Human approval:` field.
- **Architect confirmation, both lenses.** Preserve `docs/AGENTS.md:277`'s existing rule and extend
  it: a `spec-gap` issue you judge technical or architectural in scope requires `architect`
  confirmation before you resolve it. *"That rule now covers both lenses; `missing-scope` findings
  will frequently be architectural."* (AD-8.)
- **You may not set the field on your own spec-gap issues without the same discipline** — the field
  is the gate, not a formality.
- **Enforcement is executable.** `scripts/oversight/spec_gate.py` refuses coder dispatch while any
  open `spec-gap` issue for the step lacks `Ready for coder: YES`. It also fails closed when `gh`
  cannot be queried. Do not ask the worker to proceed around it.

Also extend `docs/AGENTS.md:277` in place: after *"a `spec-red-team` issue that pm-agent judges to be
technical or architectural in scope must get `architect` confirmation"*, add *"— the same rule
applies to `spec-completeness-review` issues, where `missing-scope` findings are frequently
architectural."*

### 5.5 Component H — `.claude/agents/worker.md`

**H1 — Hoist the FR2 classification rule to a both-modes section (AD-6, VF-4).**

`worker.md:63-71` (`## Scope guard (both modes)`) is the existing precedent. Insert a **new
both-modes section immediately after it**, before `---` and `## INTERACTIVE mode`:

`## Pipeline discipline — no self-exemption (both modes) (#556)`

Content: move the text currently at `:224-228` **verbatim** (the three-way classification, the
"cannot self-certify" sentence, the "if uncertain, treat as spec/behavioral" rule, and the #556 root
cause note). Add, per AD-6 and TD-VF-4's reconstruction:
- The two exhaustive exceptions: (1) **defect correction** restoring behavior an approved artifact
  already requires; (2) a change that cites a **pre-existing artifact or defect report** which
  predates the branch point and covers the diff's scope.
- The **operational citation test**: a `fix:` or `chore:` framing is not self-validating — it must
  cite the artifact or defect report, and the overseer verifies at merge that the citation exists,
  predates the branch point, and covers the diff's scope (§6.7).
- The explicit non-exemptions, **verbatim**: *"it's small"*, *"it's LOW risk"*, *"it only tightens
  governance"*, *"high confidence"* — *"these name the #556 failure mode by its actual
  rationalizations."*
- The spec-phase consequence: a spec/behavioral change dispatches `pm-agent` + `architect` +
  `technical-design`, **then** `scripts/run_spec_panel.sh`, **then** the `spec_gate.py` hold point,
  **then** coder.

Then **replace** `:224-228` with a one-line reference to the new section, and add the same reference
to the INTERACTIVE routing bullet at `:119` (*"Design or spec a change → dispatch technical-design /
architect"* → *"… and follow **Pipeline discipline (both modes)** — the spec panel and its hold point
apply in interactive mode too"*). **Do not restate the rule twice**; AD-6: *"Restating it twice
guarantees the two copies diverge."*

**`triage.py` is not touched.** It classifies for autonomy/security-report routing (chain step 6),
a different question. Making it the FR2 trigger point would be the new mechanism FR2 forbids.

**H2 — New chain step 8.0, the hold point (AD-8, AD-15).**

Insert between step 8's pipeline-discipline bullet and step 8.4:

> **8.0. Spec-panel hold point (deterministic — blocks coder dispatch).** When the pipeline-discipline
> classification is spec/behavioral, after `pm-agent` + `architect` + `technical-design` have
> produced the bundle: run
> `bash scripts/run_spec_panel.sh --step <N> --cid <cid> --bundle <requirements> --bundle <adr> --bundle <technical-design>`,
> then `python3 scripts/oversight/spec_gate.py --step <N> --cid <cid>`.
> Exit 0 = the hold point is discharged → dispatch coder. Non-zero = **do NOT dispatch coder**;
> resolve the listed `spec-gap` issues via `pm-agent` (with `architect` confirmation where the gap is
> technical or architectural) and re-run the gate. There is no "proceed anyway" path: this is a hold
> point, not a warning. If the gate cannot be made to pass, escalate per §8.2.

**H3 — Update the stale gate note at `:229` (AD-6 binding).** Current text:
> **Pre-coder gate (mechanical).** A mechanical enforcement gate is planned for v0.6.0 via triage
> agents (#558) and does not yet exist. Until it does: the pipeline discipline classification rule
> above is the sole enforcement mechanism.

Replace with: *"**Pre-coder gate (mechanical) — it exists.** `scripts/oversight/spec_gate.py`
(step 8.0) is the mechanical enforcement gate; it exits non-zero and blocks coder dispatch. The
pipeline-discipline classification rule selects *whether* the spec phase runs; the gate enforces
*that it completed*."* Leaving a "no mechanical gate exists" claim next to a mechanical gate is
exactly the silent-doc-contradiction class the completeness lens exists to catch.

**H4 — Step 8.4 trigger and tier source (AD-14, TD-VF-2).** Current text:
> 8.4. **Second review** (MEDIUM+ tier only) — run `bash scripts/run_review_chain.sh --step N --tier <validated>`.

Replace `(MEDIUM+ tier only)` with the union, and stop passing the self-reported tier as the
trigger: *"**Second review** — independent review fires iff the change classification is `additive`
or `structural`, **OR** the deterministic tier floor is MEDIUM+. Run
`bash scripts/run_review_chain.sh --step N --classification <label> --tier <validated>`. The script
re-derives both inputs (`change_classifier.py --structural-only` and `--tier-floor`); the values you
pass are declarations, not the trigger. Fail-closed if no independent reviewer is available."*

**H5 — Worker-sandboxing forward constraint (AD-6).** Add to the section's notes:
> **Forward constraint (tracked, not solved here).** Any future sandboxing of the worker must
> preserve its ability to invoke `scripts/run_spec_panel.sh` and the underlying vendor CLIs.
> Stripping model-invocation capability would silently disable this hold point.

File it as ISSUE-7 (§10).

---

## 6. Components J + K + L + M + N + I — AD-14, AD-7, and FR8

### 6.1 The union predicate, computed once

> **Independent review fires iff** `classification ∈ {additive, structural}` **OR**
> `deterministic tier floor ≥ MEDIUM`.
> **Intensity** scales with the deterministic tier floor: agy whenever it fires; codex additionally
> at HIGH+ (`OVERSIGHT_CODEX_THRESHOLD`, unchanged).
> **Classification and tier are both floors; neither may veto the other.**

### 6.2 Component J — `scripts/oversight/second_review_logic.py`

Extend `select_reviewers` (currently `:54-78`). New signature:

```
select_reviewers(score, tier, agy_threshold, codex_threshold, *,
                 classification=None, tier_floor=None) -> tuple[bool, bool]
```

Backwards-compatible: with both new kwargs `None`, behaviour is **byte-identical** to today (there
are existing tests at `tests/oversight/test_second_review_logic.py`; they must keep passing
unmodified — that is the regression contract).

Rules:
1. `effective_tier_rank = max(rank(tier), rank(tier_floor))`. Both are floors (AD-14); using
   `tier_floor` *instead of* `tier` could lower the trigger where `validated_tier > floor`, which
   would be a loosening.
2. `classification_fires = normalise(classification) in {"additive", "structural"}`.
3. **Fail-closed normalisation:** `None`, empty, or any unrecognised value → treated as `additive`
   (fires). Only the exact tokens `clarifying`, `additive`, `structural` (case-insensitive, stripped)
   are recognised. Reason: an unparseable label must not silently buy an exemption. Document it in
   the docstring.
4. `run_agy = classification_fires or effective_tier_rank >= MEDIUM or score >= agy_threshold`
5. `run_codex = effective_tier_rank >= HIGH or score >= codex_threshold`
   — **classification does not fire codex.** Codex is intensity, and D4/D5's reserve-status
   invariant (`run_second_review.sh:17-21`) stands unamended.
6. **Anti-tamper companion (AD-14 binding).** The `classification_fires` term is evaluated
   *inside this function*, downstream of every threshold. `agy_threshold` and `codex_threshold`
   arrive already clamped by the shell's `min(trusted_baseline, clamp(env,0,1))` rule
   (`run_second_review.sh:78-100`, written for HOS#985). No env value reaches
   `classification_fires`, so **no env value can suppress the classification trigger.** Add an
   explicit unit test (§12) that `select_reviewers(score=0.0, tier="LOW", agy_threshold=9.0,
   codex_threshold=9.0, classification="additive")` returns `run_agy=True`.

Add a companion pure helper so the shell does not re-implement it:

```
effective_classification(declared: str | None, structural_signals: list | None,
                         classifier_available: bool) -> tuple[str, str]
```
Returns `(classification, source)`:
- `classifier_available is False` → `("structural", "fail-closed-classifier-unavailable")`
  (the established convention: `SPEC-83:64`, `oversight-evaluator.md:303`).
- `structural_signals` non-empty → `("structural", "re-derived-2a-override")`
- otherwise → `(normalise(declared), "declared")` with the fail-closed normalisation of rule 3, and
  source `"declared-unrecognised-failclosed"` when the fallback applied.

**Honesty requirement (TD-VF-6).** The docstring must state: *"§2a re-derivation forces `structural`
only. There is no mechanical re-derivation of the `clarifying` ↔ `additive` boundary
(`contract:169`). A `clarifying` self-label on a signature-free change is not independently audited;
`classification_source` records which path was taken so the residual is measurable."*

New CLI subcommand `select-reviewers` gains `--classification` and `--tier-floor`; and a new
subcommand `effective-classification --declared X --signals-json - --classifier-ok true|false`.

### 6.3 Component K — `scripts/run_second_review.sh` (AD-14 + AD-7 + D55)

**K1 — new args.** `--classification <clarifying|additive|structural>` and `--tier-floor <T>`.
Both optional; both default to re-derivation.

**K2 — re-derivation block**, inserted after the score is resolved (`:190`) and before reviewer
selection (`:207`). It runs:
```
python3 "$(dirname "$0")/change_classifier.py" --structural-only --base <BASE> --head <HEAD>
python3 "$(dirname "$0")/change_classifier.py" --tier-floor     --base <BASE> --head <HEAD>
```
using the same `REVIEWED_RANGE` derivation the script already performs — **but note the ordering
problem: `REVIEWED_RANGE` is derived at `:285-349`, after selection at `:207`.** Move the
range-derivation block **above** reviewer selection, or (preferred, smaller diff) extract the
`--step` branch's `get_step_range` call into a lightweight pre-pass. Whichever the coder chooses,
the invariant is: **the classifier is run over the same range the reviewers review** — a classifier
run over a different range would be a fresh instance of the SPEC-219 defect the `reviewed_range`
field exists to prevent. Record the range in the header alongside the classification.
Classifier missing or non-zero exit → `classifier_available=false` → fail-closed `structural`.

**K3 — selection call.** Pass `--classification "$EFFECTIVE_CLASSIFICATION"` and
`--tier-floor "$TIER_FLOOR"` through to `second_review_logic.py select-reviewers`.

**K4 — the skip sentinel (`:221-237`)** gains the new fields and a truthful reason string. Today it
says *"score=$SCORE below both thresholds … and tier=${TIER:-none} below MEDIUM — skip"*. It must
also name the classification arm:
```
verdict: skipped
reason: classification=clarifying (source: declared) AND tier_floor=LOW AND validated_tier=LOW AND score=0.10 below both thresholds
classification_declared: clarifying
classification_effective: clarifying
classification_source: declared
tier_floor: LOW
validated_tier: LOW
```
The existing hermetic test `tests/oversight/test_second_review_env_threshold_clamp.py` parses this
sentinel; keep `agy_threshold:` / `codex_threshold:` / `verdict:` **exactly as they are** so it keeps
passing, and add fields only.

**K5 — AD-7 outage posture (`:243-274`).** Restate the fail condition as the rule, not as threshold
arithmetic:
```
independent_available = (RUN_AGY && AGY_AVAILABLE) || (RUN_CODEX && CODEX_AVAILABLE)
```
- `independent_available` true → **proceed**, and write `absent_participants: agy|codex|none` into
  the header. Absence is logged, never silent.
- `independent_available` false while review was required → **hard fail, exit 1**, message naming
  which vendors were required and which were absent, and pointing at the human-override path.
- **The combined codex fallback at `:244-246,715-729` is RETAINED**, but its honesty is fixed: set
  `agy_status: absent` and `codex_mode: fallback-combined` in the header, and never report the
  correctness lens as independently covered by a targeted review. Rationale for retaining: AD-3's
  rejection of the fallback shape is scoped to the *spec panel* ("one model running both prompts is
  not a degraded dual-lens"); removing it here would *reduce* coverage, which AD-14's own
  union-not-replacement reasoning forbids. Flagged for architect confirmation (§10, ESC-3).
- **Runtime error = absence** (already partly present at `:819-832`): keep the `verdict: error` →
  exit 1 guard and make the header record which reviewer errored.

**K6 — header comment block (`:9-53`) rewritten.** Three changes:
1. `:9` — `VENDOR ROLES (DECISIONS.md D4 — no Claude model as independent check)` →
   `VENDOR ROLES (DECISIONS.md D55, superseding D4:27 / D16:80 — independent review means a
   different vendor family, or the human; a same-family model may be class-differential peer review
   but never the independent check)`.
2. `:11-21` — the pure tier-gating description is replaced by the AD-14 union statement (§6.1
   verbatim), keeping the intensity/threshold prose. AD-14 binding: *"would otherwise describe
   behavior the script no longer has."*
3. Add the AD-7 posture paragraph and the §1 terminology.

### 6.4 Component L — `scripts/run_review_chain.sh` (TD-VF-2, the gap the ADR missed)

Replace `:238-244`:
```
RUN_AGY=0
RUN_CODEX=0
[[ "$(rank "$TIER")" -ge 1 ]] && RUN_AGY=1    # MEDIUM+
[[ "$(rank "$TIER")" -ge 2 ]] && RUN_CODEX=1  # HIGH+

if [[ $RUN_AGY -eq 0 ]]; then
  skip "second review: tier=$TIER is below MEDIUM — skipping (validators-only gate)"
```
with a call to the **same** predicate rather than a second implementation:
```
eval "$(python3 "$SCRIPT_DIR/oversight/second_review_logic.py" select-reviewers \
        --score "$SCORE" --tier "$TIER" --tier-floor "$TIER_FLOOR" \
        --classification "$CLASSIFICATION" \
        --agy-threshold "$AGY_THRESHOLD" --codex-threshold "$CODEX_THRESHOLD")"
```
(`RUN_AGY`/`RUN_CODEX` are the same `true|false` variables the module already prints — see
`run_second_review.sh:207-219`; reuse that contract exactly, including its two fail-closed guards on
empty output and non-zero exit.)

- Add `--classification <label>` to `run_review_chain.sh`'s own arg parser (`:60-90` area) and pass
  it through to `SR_CMD` at `:259` alongside `--tier`.
- `--step` is currently required only at MEDIUM+ (`:254-256`). Since the chain can now fire at LOW,
  make `--step` required **whenever the union fires**, with the same error message.
- Update the section heading at `:236` — `Step 2/3 — second review (tier-gated)` →
  `Step 2/3 — second review (classification ∪ tier-floor)`.
- Update the file header at `:2` and `:6` (`agy at MEDIUM+, codex at HIGH+` → the union statement).
- **Do not duplicate the union logic.** One predicate, two callers. This is the D41 fix, applied.

### 6.5 Component M — `scripts/run_panel.sh` (AD-12, TD-VF-3)

**M1 — create the predicate.** After the roster is built (`:374-383`), filter it:
```
for entry in "${ROSTER[@]}"; do
  cli="${entry%%:*}"
  # class is empty for cross-vendor CLIs; model_rank decides admissibility
  verdict=$(python3 scripts/oversight/model_rank.py admissible \
            --cli "$cli" --class "${CLAIMED_CLASS:-}" --author-rank "$AUTHOR_RANK")
  ...
done
```
- `AUTHOR_RANK` resolution order: `--author-class <alias>` flag → the `coder` agent's frontmatter
  class via `model_rank.py author-rank --agent coder` → fail-closed `None`.
- A `None` author rank makes `is_class_differential` false, so **every same-family reviewer is
  excluded** — fail-closed, which is the correct direction.
- **Behavioural delta today: none.** The roster contains only `agy`, `codex`, `ipcheck`, all
  cross-vendor/local, all admitted. The predicate exists so a future roster addition cannot
  silently violate D55 rule (1). State this in the code comment so a reader does not "simplify" it
  away.

**M2 — fix the log line `:385`.** Current:
```
info "roster ($RISK$( ((SAMPLED)) && echo ' +audit' )): ${ROSTER[*]}   (Opus authored → excluded; Copilot runs natively in CI)"
```
New text: `(author rank: ${AUTHOR_CLASS}(${AUTHOR_RANK}); same-family reviewers admitted only strictly above that rank — D55 rule (1); Copilot runs natively in CI)`, plus one `info` line per excluded entry naming `model_rank`'s reason string.

**M3 — fix the reviewer prompt `:427`.** Current:
```
The author was Claude Opus; you are the independent check — do not assume the author is correct.
```
New: `The author was a Claude-family model; you are the cross-vendor independent check — do not assume the author is correct.` This removes a statement that is factually false for Sonnet-authored inner-loop work (TD-VF-3) and adopts the §1 vocabulary.

**M4 — header comments `:11-12` and `:127`.** `REVIEWERS  cross-vendor fan-out scaled by risk (Opus is the author → never reviews)` and `(subscription CLIs; Opus is the author and is NEVER called here)` → rank-relative phrasing citing D55.

**M5 — `--help` range.** `:100` runs `sed -n '2,49p' "$0"`. If the header grows past line 49, extend
the range in the same edit or the help output silently truncates.

**Out of scope, explicitly:** adding a rank-4 same-family reviewer to the roster. Only the predicate
is created (ADR "Explicitly out of scope").

### 6.6 Component N — `scripts/framework/validate_agents.sh:15`

Anchor:
```
# VENDOR ROLES (mirrors run_second_review.sh DECISIONS.md D4):
```
→ `# VENDOR ROLES (mirrors run_second_review.sh; DECISIONS.md D55, superseding D4):`
Comment only; the script's vendor logic is unchanged by this ADR. **Do not** swap the lens↔vendor
assignment here — see the VF-6 exception (§7.6): the spec phase's assignment (agy = adversarial) is
deliberately the inverse of this file's convention, and D55 records why.

### 6.7 Component I — `.claude/agents/overseer.md`, the FR8 reject-back-to-worker path (AD-5)

**What "reject" means here, stated first because it is the requirement most easily mis-implemented.**
Reject is **not** closing the PR and is **not** escalating to a human. It is the existing **pre-merge
bounce**: the PR stays open (converted to draft), is assigned back to `hos-worker-hos[bot]`, gets the
`needs-ai` label, and a `pr-bounced` audit event is appended. `worker.md:278` is explicit that
**a bounce does NOT count as a task failure** and `worker.md:270-278` already defines re-entry. The
worker remediates, or escalates immediately if it disagrees. That is, line for line, the human's
requirement.

**Mechanism reuse — nothing new is invented.** `contract/OVERSIGHT-CONTRACT.md:429,442,542` and
`overseer.md:228-231,249-284,441,465` already define the whole protocol. FR8 adds **one bounce
condition**, not a mechanism.

**I1 — VF-3 constraint, binding on the wording.** `record_pr_bounce()`,
`check_register_completeness()` and `bounce_count()` are cited in `overseer.md` and the contract but
**do not exist as code** (verified: zero `.py` hits; `merge_authority.py` contains
`decide_merge_authority`, `detect_server_side_gate`, `detect_human_hold_directive`, `open_draft_pr`,
`route_embargo` and no bounce functions). The bounce is an **agent-executed prose protocol.** The new
condition must therefore be written as prose that instructs the overseer to *execute the bounce
protocol*, and **must not introduce any new function-call reference.** Do not add
`call record_pr_bounce(...)`. Do not "fix" the existing citations here — ISSUE-2.

**I2 — the new condition.** Add one bullet to the step-4a bounce-condition list (`overseer.md:228-231`).
Anchor for the insertion — the existing block begins:
```
4a. **Register-completeness check (bounce-back gate)** (`merge_authority.py:check_register_completeness`) — before the matrix, check that the worker's PR is procedurally complete. Evaluate bounce conditions using the existing readiness checks:
```

New condition, `check_id: SPEC-PHASE-MISSING`:

> **Spec-phase artifact missing on a structural change (FR8).**
> **Detect** — do not write detection logic; run the existing classifier over the PR's range:
> `python3 scripts/oversight/change_classifier.py --structural-only --base <base_sha> --head <head_sha>`.
> The condition holds when `structural_signals` is **non-empty** AND no accepted spec-phase artifact
> covers the step.
> **Classifier unavailable or non-zero exit → assume the condition is TRUE and say so in the
> output** (the established fail-closed convention: `SPEC-83:64`, `oversight-evaluator.md:303`).

**I3 — acceptance order for "an accepted spec-phase artifact" (FR8's genuinely new part).**
Contract §7 condition 10 checks for a *human-authorization* artifact; this checks for a *spec-phase*
artifact. They are different objects and must not be conflated.
1. **Sufficient:** `.claudetmp/spec-panel/step{N}-*.md` exists for the step with `verdict:` not
   `error`. This is the only evidence that proves **both lenses ran**.
2. **Grandfathering only:** a technical-design document **plus** open-or-closed `spec-gap` issues for
   the cid, accepted **only** for work whose branch point predates this ADR's ship commit. Mirrors
   the SPEC-267 grandfathering pattern at `contract/OVERSIGHT-CONTRACT.md:534`.
   *Presence of a technical-design doc alone is never sufficient on post-ship work* (AD-2).

**I4 — exemption audit (FR8 part 2).** A PR claiming an FR2 exemption (a `fix:` / `chore:` framing)
must cite an artifact or defect report. The overseer verifies the citation:
(a) **exists**, (b) **predates the branch point**, (c) **covers the diff's scope.**
Scope-overlap uses the **SPEC-267 canonicalization rules verbatim**
(`contract/OVERSIGHT-CONTRACT.md:534`; evaluator steps 1–4): paths relative to the project root,
**exact-match** against `git diff --name-only`, **no prefix, basename, or directory-containment
matching.** Behavior beyond the cited scope invalidates the exemption → bounce.
**Reuse those rules; do not restate them with variations** — a second, subtly different
canonicalization is how the two drift.

**I5 — mislabel telemetry (FR8 part 3) is loggable, non-blocking.** Emit the new `spec-phase-missing`
audit event (§7.4) with payload `pr`, `cid`, `step`, `structural_signals[]`, `artifact_found` (bool),
`claimed_exemption` (string|null), `citation_valid` (bool|null), `disposition`
(`bounced | passed | mislabel-logged`).
**Emit it even when `disposition: passed`.** The passed-vs-bounced ratio *is* the escaped-mislabel
rate — exactly as `structural-override` is emitted when `covered: true`. Without the passing case
there is no denominator and the metric is unusable.

**I6 — enum discipline.** `reason_category: COMPLIANCE_FAILURE` — the **existing** value
(`contract:429`; semantics at `overseer.md:284`: *"a concrete compliance/register check failure (the
specific `check_id`(s) appear in the audit event's `failures` field)"*). The `check_id` already
carries the specificity. **Do not extend the enum.** `SPEC_AMBIGUITY` means something else entirely
and must not be repurposed; an enum extension is a contract schema change with unknown downstream
parsers, unjustified for zero added information.

**I7 — the escalation invariant is preserved through the existing cap, not through a new counter.**
`overseer.md:410` says the overseer *"errs toward escalation, never toward auto-merge."* Write the
reconciliation into `overseer.md` rather than leaving it implicit — three reasons:
(a) the invariant governs the **auto-merge boundary**; a bounce merges nothing, so it never errs
toward auto-merge — it is strictly more conservative than proceeding;
(b) a missing-spec-artifact finding is **deterministic and worker-remediable** (an artifact either
exists or does not), whereas escalation is reserved for **ambiguous risk judgment** only a human can
settle;
(c) the existing per-cid cap is retained **unmodified**: `bounce_count(cid) >= 2` → `HUMAN_REQUIRED`
(`overseer.md:230,266`). A worker that disputes the classification twice reaches the human
automatically, and may escalate immediately at any point if it disagrees.
**That cap is the loop-exit. Do not add a separate counter** — `overseer.md:271` already forbids one
for out-of-scope bounces; the same rule applies here.

**I8 — ordering is halt-on-failure and mirrors the existing protocol** (`overseer.md:256-260,441`):
1. post the bounce comment (carrying the SPEC-378 R1.2 `**Reason category:**` / `**Summary:**` fields);
2. confirm it posted (HTTP success / comment URL returned);
3. append the `pr-bounced` audit event **and** the `spec-phase-missing` event;
4. finalize — assign to `hos-worker-hos[bot]`, apply `needs-ai`, convert to draft.
**Never write an event for a comment that did not post.** If the comment post or the audit append
fails, halt without finalizing.

**I9 — worker re-entry needs no change.** `worker.md:270-278` already handles
`- [<CHECK-ID>] <detail>` lines; `SPEC-PHASE-MISSING` maps to *"run the spec panel and the
`spec_gate.py` hold point (chain step 8.0), then re-submit."* Add that one mapping sentence to
`worker.md`'s re-entry section so the check_id is actionable rather than merely reported.

---

## 7. Component O + Q — contract and documentation

### 7.1 `contract/OVERSIGHT-CONTRACT.md` §1 — filesystem protocol

Add to the `.claudetmp/` block (after the `second-review/` entry at `:110-118`):
```
  spec-panel/
    step{N}-{ts}.md              ← dual-lens spec-panel output (run_spec_panel.sh).
                                    Machine-readable header then per-lens blocks.
                                    Top-level fields include:
                                      verdict: pass|findings|error|unparseable|dry-run
                                      block_reason: none|CONFIG_REJECTED|
                                                    RULE2_SOLE_SAME_FAMILY|FR1_LENS_ABSENT
                                      completeness_lens_class_differential: true|false
                                      hold_point_discharged: true|false
                                    ABSENCE OF THIS FILE is the detectable condition that
                                    the spec panel did not run; a technical-design doc
                                    alone is not sufficient evidence.
```
And to the `oversight/` block, beside `human-tier-override.md` (`:90-93`):
```
    spec-panel-bypass.md         ← HUMAN ONLY. Authorizes proceeding past a blocked
                                    spec panel. Agents may READ it; they must never
                                    create or modify it. Required fields: step (or cid),
                                    reason, scope, expiry (YYYY-MM-DD). Consumption emits
                                    a `spec-panel-bypass-consumed` audit event so bypasses
                                    are countable.
```

### 7.2 `contract/OVERSIGHT-CONTRACT.md` — NEW §2b, the canonical spec-gap schema (AD-4)

Placed immediately after §2a (`:153-169`), before `## 3. Sign-off register schema`. **This is the
single source of truth**; both agent files reference it and neither owns it.

**Canonical `Gap type` values — single token, kebab-case, machine-parseable:**

| Value | Meaning | Permitted lens |
|---|---|---|
| `contradiction` | Two requirements conflict under some condition | adversarial |
| `gaming-vector` | The rules can be exploited without technically being violated | adversarial |
| `implicit-assumption` | Something assumed but never stated | adversarial |
| `missing-edge-case` | A boundary condition inside an addressed area is unhandled | adversarial |
| `ambiguity` | Stated, but admits more than one implementation reading | either |
| `missing-requirement` | A specific requirement absent **within an area the bundle does address** | either |
| `missing-scope` | **An entire area the bundle never addresses at all** — including a silent contradiction of an existing repo doc, an inert output, an unmigrated instance of the rule being formalized, an absent lifecycle story | completeness |

**The boundary test — this sentence appears verbatim in `spec-red-team.md`, in
`spec-completeness-review.md`, and here:**
> The `missing-requirement` / `missing-scope` boundary is: **is the area addressed at all?**

**Required fields on every `spec-gap` issue body:**
```
**Build step:** {N}
**CID:** {cid or "none"}
**Gap type:** {one of the seven values above}
**Lens:** {adversarial | completeness}          ← exactly one, never both
**Corroborated-by:** {other lens | none}
**Spec section:** §N.N (or "no section — implicit")
**Finding:** {what is unclear, missing, or exploitable}
**Impact:** {what could go wrong if coding proceeds without resolving this}
**Resolution required:** {what pm-agent must decide or clarify}
**Change classification:** {clarifying | additive | structural}
**Human approval:** {URL for structural, else "not required"}
**Ready for coder:** {set to YES by pm-agent after resolution — the hold-point signature}
```

**Provenance rule (AD-4).** A finding raised independently by both lenses is filed **once**, with the
first lens recorded in `Lens:` and the other in `Corroborated-by:`. Never two issues. The metric
this preserves is *disjointness between the lenses*, which is the research value of the pair.

**Enforcement.** `Ready for coder:` is enforced by `scripts/oversight/spec_gate.py`, which exits
non-zero and blocks coder dispatch while any open `spec-gap` issue for the step lacks the exact token
`YES`. It fails closed when `gh` cannot be queried.

### 7.3 `contract/OVERSIGHT-CONTRACT.md` — NEW §1b, the enumerated hold points (AD-13)

AD-13: *"An enumerable predicate that is never actually enumerated degrades straight back into a
semantic one."* `technical-design` proposes; `architect` confirms (§10, ESC-4).

> **Hold points (enumerated).** A hold point is a mandatory verification point beyond which work
> cannot proceed without approval by the designated authority. **At every hold point, at least one
> independent reviewer (a different vendor family, or the human) must participate.** Routine work is
> unconstrained beyond the peer-review guardrails (no shared memory / no author framing, plus
> adversarial instruction).
>
> | # | Hold point | Signature | Traveller | Independent participant | Enforcer |
> |---|---|---|---|---|---|
> | HP-1 | **Spec panel** (dual-lens spec review) | `Ready for coder: YES` on every open `spec-gap` issue for the step | `coder` | `agy` (adversarial lens) | `scripts/oversight/spec_gate.py` |
> | HP-2 | **Pre-PR second review** | `verdict:` not `error` in `.claudetmp/second-review/step{N}-*.md` | the PR | `agy`; `codex` at HIGH+ | `run_second_review.sh` exit code + evaluator §7 |
> | HP-3 | **Merge gate** (CRITICAL tier, protected surface, or `human_gate_required`) | `step{N}-human-authorization.md` / human PR approval | the merge | the human | `oversight-evaluator` §7 condition 7; `merge_authority.decide_merge_authority` |
>
> **Class-differential peer review never substitutes for independent review at a hold point.** Rules
> (1) and (2) of D55 are conjunctive and orthogonal: satisfying one never satisfies the other.
> Deterministic checkers (validators, gates, `change_classifier.py`) make no judgment and therefore
> cannot carry rule (2) — they are decisive for *triggering* review, never a substitute for it.

Quote the binding-16b sentence (§1 above) immediately beneath the table.

### 7.4 `contract/OVERSIGHT-CONTRACT.md` §6a — two new audit events (AD-5, AD-7)

Add to the catalog table (`:409-432`), keeping the existing column order:

| Event | Meaning | Emitted by | Key fields |
|---|---|---|---|
| `spec-phase-missing` | The overseer's pre-merge FR8 check evaluated whether a structural change reached the PR without a spec-panel artifact. **Emitted on `passed` as well as `bounced`** — without the passing case there is no denominator and the escaped-mislabel rate is unusable (same rationale as `structural-override`'s `covered: true`). | overseer | `pr`, `cid`, `step`, `structural_signals[]`, `artifact_found` (bool), `claimed_exemption` (string\|null), `citation_valid` (bool\|null), `disposition` (`bounced \| passed \| mislabel-logged`) |
| `spec-panel-bypass-consumed` | A human-authored `.claudetmp/oversight/spec-panel-bypass.md` was consumed to proceed past a blocked spec panel — bypasses are countable, never silent | run_spec_panel.sh | `step`, `cid`, `block_reason`, `scope`, `expiry`, `authorized_by` |

**No `reason_category` enum extension.** AD-5: the FR8 bounce uses the existing
`COMPLIANCE_FAILURE`; the specificity lives in `check_id: SPEC-PHASE-MISSING`, which appears in the
`pr-bounced` event's existing `failures` array (`contract:429,442`). `SPEC_AMBIGUITY` means
something else and must not be repurposed.

### 7.5 FR7 documentation updates

All of the following adopt the §1 vocabulary — *peer review*, *independent review*, *hold point*,
*graduated independence* — replacing coined and positional language, and **state the
technical-independence-only limitation wherever they characterize what HOS's review layer
achieves** (§1's limitation sentence).

| File | Anchor | Change |
|---|---|---|
| `METHODOLOGY.md:174` | `    A([Spec phase\nspec-red-team]) --> B` | → a two-lens node labelled a **hold point**: `A([SPEC PHASE — HOLD POINT<br/>run_spec_panel.sh<br/>spec-red-team · agy (independent)<br/>spec-completeness-review · same-family peer review]) --> A2{Ready for coder: YES?}` with `A2 -- No --> A` and `A2 -- Yes --> B`. The "Yes" edge is the only path into the inner loop. |
| `METHODOLOGY.md` §6 prose | around the pipeline description | New paragraph: the spec phase is a hold point, the two lenses, the rework-avoidance rationale (quote the human verbatim: *"Spec panel is hold point. Work could be invalidated, so don't start until we know specs good."*), and the limitation sentence. |
| `METHODOLOGY.md:335` | `pr_readiness.py   →  deterministic self-assessment gate (REQ-W-01..W-14);` | **Do not silently fix.** Add `spec_gate.py → the spec-panel hold-point enforcer (blocks coder dispatch)` alongside it, and file TD-VF-1 as ISSUE-4. |
| `ARCHITECTURE.md:81` | the `spec-red-team` table row | Add a `spec-completeness-review` row; amend the `spec-red-team` row to say *"one of two lenses at the spec-phase hold point; supplies technical independence (cross-vendor agy)"*. |
| `ARCHITECTURE.md:157` | `PMA[...] --> SRT["spec-red-team\n adversarial spec review\n(agy, per step)"]` and `SRT --> ARCH` | `PMA --> PANEL` where `PANEL` is a subgraph containing both lenses, then `PANEL --> GATE{Ready for coder: YES}` → `ARCH`. Label the subgraph **HOLD POINT**. |
| `CLAUDE.md` | the oversight-layer agent table | Add a `spec-completeness-review` row; amend `spec-red-team`'s. |
| `CLAUDE.md` | the "Pipeline position of each script" block, `SPEC PHASE` section | `spec-red-team agent → spec-gap issues` becomes the paired invocation: `run_spec_panel.sh → spec-red-team (agy, independent) + spec-completeness-review (same-family peer review) → spec-gap issues → spec_gate.py (HOLD POINT — blocks coder)`. |
| `CLAUDE.md` | repo-layout `scripts/` listing | Add `run_spec_panel.sh` and `oversight/{model_rank,spec_panel_logic,spec_gate}.py`. Update the "26 shipped agents" counts to 27 wherever they appear. |
| `docs/OVERSIGHT-RUNBOOK.md:253-263` | `### PHASE 0 — Spec Red-Team (before coding starts)` | Rename to `### PHASE 0 — Spec Panel (HOLD POINT — before coding starts)`. Replace the "invoke the agent in Claude Code" instruction with the actual commands (`run_spec_panel.sh`, then `spec_gate.py`), the artifact path, the exit-code meanings, and the two distinct block reasons with their owners. |
| `docs/OVERSIGHT-RUNBOOK.md:512` | the evaluator re-derivation paragraph | Add the AD-14 union: independent review is triggered by classification ∪ deterministic tier floor, never by a self-assessed tier. |
| `docs/SETUP.md:94` | `SPEC_FILE` row: *"(`spec-red-team`, `ux-designer`)"* | → *"(`spec-red-team`, `spec-completeness-review`, `ux-designer`, `run_spec_panel.sh`)"* |
| `docs/AGENTS.md` | §30, `:130-131`, `:277`, `:1019-1020`, `:1052` | Per §5.1's registration table and §5.4. |
| `README.md:97` | the transition-phase paragraph | Add the union trigger and the terminology; state the limitation sentence once. |

### 7.6 The VF-6 lens↔vendor exception — record it so a sweep cannot undo it

The spec phase deliberately assigns **agy = adversarial** and **same-family = completeness**, which
is the inverse of `DECISIONS.md` D4, `run_second_review.sh:11-21`, and `validate_agents.sh:15-17`.
Record the exception in **three** places so no single "consistency fix" can swap the lenses:
1. `DECISIONS.md` D55 item 5 (§9.1).
2. A note in `contract/OVERSIGHT-CONTRACT.md` §2b: *"The spec phase's lens↔vendor assignment is
   deliberately the inverse of the D4 convention. It reproduces the configuration that produced the
   demonstrated result. Do not 'harmonise' it."*
3. A header comment in `scripts/run_spec_panel.sh`.

### 7.7 Component P — `bootstrap/validate_setup.sh` (AD-11b Copilot precondition)

AD-11b: *"Copilot PR review being enabled on the repository is a **checked precondition** of
rule-(2) compliance at LOW … today it is an assumption stated in a decision log, not a verified
precondition."*

Add a new numbered section `── 5. Independent-review floor (Copilot) ──` after the git-remote check,
with **three** states — the two-state design fails on the first offline run and would be disabled
within a week:

| State | Condition | Action |
|---|---|---|
| VERIFIED | `gh` authenticated **and** the repo reports Copilot code review enabled | `ok "Independent-review floor: Copilot enabled"`; write/refresh `.claudetmp/oversight/copilot-attestation.json` with `{checked_at, repo, enabled: true}` |
| STALE/UNVERIFIABLE | `gh` unavailable/unauthenticated **and** a non-expired attestation exists (≤ 30 days) | WARN naming the attestation date; **do not fail** |
| FAIL | Copilot reported disabled, **or** no attestation and no way to check | `fail "Independent-review floor absent: Copilot PR review is not verified enabled. LOW-tier work would have NO independent review, violating D55 rule (2). Enable Copilot code review on the repository, or run this check where gh is authenticated."` |

`--skip-copilot-check` is accepted **only** with an explicit `HOS_COPILOT_CHECK_ACK=<reason>` and
prints a loud WARN naming the reason — so a skip is attributable, not habitual.

Also add the check to `.claude/agents/framework-setup-validator.md` as a listed precondition, so
both members of the family (per AD-11b) carry it.

**Bounded documented exception (AD-11b, narrowed by AD-14).** Record in the contract §1b table
footnote: *"A LOW-tier `clarifying` change — one that by definition introduces, alters, or removes no
observable behavior — receives no **local** independent review; its independent review is Copilot at
PR time. No merge can occur before that point. Everything `additive` or `structural` now receives
local independent review at every tier (AD-14)."*

---

## 8. Component R — the research note (AD-16)

**Path:** `research/findings/independent-review-is-decomposed-not-binary.md`.
**Style:** follows the existing `research/findings/` convention exactly — an H1 `# Finding: …`, a
`**Role:**` header (per `research/README.md`: use **`oversight-mechanism`**), first-observed/
confirmed dates, then `## The Finding`, `## Why This Matters`, `## Evidence`, `## Implications for
Research`, `## Related findings`.

**Required sections:**

1. **The finding.** HOS's review scheme is an instance of an established practice (IEEE 1012 /
   IV&V), not a coinage. The five terms of §1 and the HOS construct each names.
2. **The citations** — verified 2026-07-31, exactly as listed in ADR §1a: IEEE 1012 itself; US NRC
   Regulatory Guide 1.168 (which endorses it); the IEEE Spectrum integrity-level table; the
   hold/witness-point definitions. Reproduce the URLs from ADR §1a; **do not add sources.**
3. **`## Divergence from the precedent` — MANDATORY, and it must not be softened.**
   - IEEE 1012 decomposes independence into **technical, managerial, and financial**.
   - **HOS satisfies technical only.**
   - Cite the standard *for the two dimensions HOS does not satisfy*.
   - Name the reasons concretely: a single orchestrator (`worker`) dispatches both the author chain
     and the reviewers, selects the work, and decides when review is complete → **no managerial
     independence**; one operator, one set of subscriptions → **no financial independence**.
   - State plainly: **no claim of IV&V-grade independence follows from the borrowed vocabulary.**
   - Include the *why this section exists* argument: a note that cites IEEE 1012 to borrow its
     credibility while omitting two of its three independence dimensions is **selective framing** —
     the same description-vs-substance mismatch the repo's own P9 / `prompt-fidelity` rules exist to
     detect and that AD-5's FR8 part 3 makes a loggable finding for PRs. *A framework that logs
     mislabeling in its subjects and practises it in its own research artifacts has a credibility
     problem larger than any finding in the note.*
   - Note the managerial gap is **load-bearing, not incidental**: an orchestrator that chooses which
     reviewers fire is exactly the actor a managerial-independence requirement exists to constrain,
     which is why AD-14's "never gated on self-assessment" rule matters.
4. **The dual-lens evidence — the fixed citation set. DO NOT EXTEND IT BY INFERENCE.**

| Citation | Verified content | Use |
|---|---|---|
| `.claudetmp/design/fable-consistency-check.md` | Run 2026-07-29; a **design-chain consistency check over one epic** (ADR-032 → epic spec → corrected decomposition → tickets #1060–#1074). Method: given seven already-known defects, asked what that list *misses*. Findings B1 (BLOCKER), M1–M4 (MAJOR), m1–m3 (MINOR). B1 = the Task-4 action table consistently swaps **#1072** (astro pack mega-ticket) and **#1073** (micro-ticket), so verbatim application would close the mega-ticket as folded and split the tiny one three ways. | Primary evidence for the completeness lens's distinct failure class |
| **#1078** | The mechanism this ADR formalizes; the artifact self-describes as *"the first real exercise of the mechanism proposed in #1078, run deliberately out of process"* | Provenance of the dual-lens idea |
| **#1082** | The repo's own contemporaneous comparative record, **including** the confound (*"same vendor as the third reviewer, so vendor diversity predicts it should add little"*) and the caveat (*"a single deep reviewer remains exposed to its own family's blind spots… Fable must not become a substitute for cross-vendor votes"*) | **Cite for the n=1 caveat rather than deriving it** — it is the repository's own record, not this design's inference |
| **#1079** | *"the artifacts that govern code get less review than code"* | The prose-tier-floor gap (VF-10 / AD-11c) |

   **TD-VF-10 handling:** the first row's path is inside `.claudetmp/`, which `.gitignore:2`
   excludes. The note MUST therefore (a) quote the B1 finding and the finding counts **inline**, so
   the evidence survives, and (b) label the path explicitly as *"a local, uncommitted working
   artifact — not a repository citation"*. This closes the durability gap **without adding a
   source.**

5. **The retroactive-remediation batch — verified fact, contested attribution.**
   - **Write:** issues **#972–#1002** — 31 issues, filed **2026-07-14**, all prefixed `[AI: audit]`,
     **30 of 31 now closed**. Substantive findings included CI approval gates self-bypassable,
     `require_tier_ceiling` dead code, multiple fail-opens, and the panel dropping all reviewer
     findings when the arbiter is unavailable. This is **stronger** evidence that retroactive
     remediation occurred than testimony alone — 31 real defects, 30 fixed, closure evidence in the
     tracker.
   - **Write no model name.** Every issue carries a contemporaneous provenance line reading
     *"surfaced by an AI code-audit sweep (Claude, opus-4-8) on 2026-07-14"*, which conflicts with
     the recollection that it was fable. Three live possibilities: opus is correct and fable is a
     misremembering; a separate fable audit exists and has not been located; or the provenance line
     is wrong. **Asked and unanswered.**
   - Where the note must refer to the actor, say **"an AI code-audit sweep (model attribution
     unresolved — see the provenance discrepancy)"** and say so explicitly rather than picking the
     likelier option. **Neither "fable" nor "opus-4-8" may appear as settled fact.**
   - What **is** safe to state under either attribution: it was **same-family peer review** and
     would not have discharged a hold point on its own.
   - The reason under-claiming is the required direction, stated in the note: the defect the
     design-chain pass itself caught was **two swapped issue numbers in an otherwise internally
     coherent document** (B1). A research note that guessed a model attribution wrong while citing
     the finding about referential errors in coherent documents would be self-refuting in exactly
     the same way.
   - **Scope correction — do not enumerate.** The verified Fable artifact is a design-chain
     consistency check over one epic, **not** a comprehensive codebase audit. Remediation did occur;
     no issue enumeration may be attached to *that* artifact. (The #972–#1002 batch is cited on its
     own footing, unattributed.)

6. **`## Related findings`** — link `cross-vendor-review-finds-real-bugs.md`,
   `gate-on-computed-signal-not-self-reported-verdict.md`, `a-guard-that-doesnt-halt-is-not-a-guard.md`,
   `agent-confidence-is-uninformative-for-defect-prediction.md`.

**TD-VF-11 constraint on the worker:** `gh` was unauthenticated when this design was written, so
#1078 / #1079 / #1082 / #972–#1002 are carried on the ADR's and the human's authority. If `gh` is
authenticated at implementation time, verify each. **On any mismatch, escalate — do not substitute a
different issue number.** Under no circumstances extend the citation set.

---

## 9. Component S — `DECISIONS.md` D55

### 9.1 Placement and heading

`CLAUDE.md`: *"`DECISIONS.md` is append-only. New decisions go at the bottom with a date header."*
So: **append at end of file. Never edit D4 or D16 in place.**

Per TD-VF-9, the file has two heading conventions. Use a heading that satisfies both — chronological
append in the current format, and greppable as `D55`:

```
## 2026-07-31 — D55: Reviewer independence revised — class-differential within family, never sole (ADR-033)
```

### 9.2 Required content (all eight items — AD-12)

1. **What is superseded and what survives.** D4's *"Opus authors, so Opus never reviews its own
   output"* and **D16:80** — *"no Claude model can be the independent check… Sonnet stays
   arbiter-only"* — are replaced by two narrower rules:
   **(1) class-differential permitted within family** — a same-family model may validate work
   authored by a strictly lower class; same-class self-validation remains prohibited;
   **(2) never sole** — a same-family voice may participate in a panel but may never constitute it.
   D4's *author-exclusion* principle survives intact and is the special case of rule (1) at equal
   rank. **Name `D16:80` explicitly as superseded** — a reader who greps D16 first must find a
   pointer forward.
2. **The class ordering** `haiku(1) < sonnet(2) < opus(3) < fable(4)` as a **rank registry**, held in
   `scripts/oversight/model_rank.py`, with the fail-closed rule that an unregistered class has **no
   rank** and therefore cannot satisfy any class-differential requirement.
3. **The AD-10 distinction, explicitly, so the entry cannot be read as "depth replaces diversity":**
   class differential buys capability/thoroughness; cross-vendor buys decorrelation; **neither
   substitutes**; a same-family voice may never reduce a gate's cross-vendor count to zero. Cite the
   repo's own finding and its honest limitation (n=1, confounded with running last) — via #1082, per
   §8's fixed citation set.
4. **The direction-of-change disclosure — state it plainly.** Reviewer independence and the
   cross-vendor requirement are a **safety-critical class of rule; this amendment LOOSENS the
   predicate.** Record the compensating tightenings that make the net effect at the gate level
   neutral-to-stricter:
   - **AD-14** — independent review is now triggered by classification ∪ deterministic tier floor,
     so a same-family chain can no longer self-declare its way below the independent review on
     `additive`/`structural` work at any tier.
   - **AD-11b** — independent-voice coverage made unconditional at LOW, where it was previously
     absent from the inner loop, with **Copilot-enabled promoted from an assumption to a checked
     precondition**.
   - **AD-8 / AD-15** — the spec panel becomes an executably-enforced hold point.
   **Note the delta from the ADR's rev-2 text:** AD-12 item 4 names **AD-11a** as a compensating
   tightening. **AD-11a was permanently WITHDRAWN in rev 6.** D55 must therefore **not** cite it,
   and must not claim a class differential on the mandatory review lane. Substituting AD-8/AD-15 (a
   real, shipped tightening) keeps the disclosure honest. *A loosening recorded without its
   compensations is how a ratchet quietly reverses — and a loosening recorded with a compensation
   that was withdrawn is worse.*
5. **The VF-6 lens↔vendor exception** for the spec phase (agy = adversarial / same-family =
   completeness, deliberately the inverse of the D4 convention), so a later consistency sweep cannot
   swap it back.
6. **Scope of the outage-posture change (AD-7)**, applied to `run_second_review.sh` in the same
   change as AD-14 rather than as a follow-up — with the honest note (TD-VF-8) that the script's
   HIGH+ branch already permitted codex-absent-while-agy-up, so the change is mostly one of
   expression and header honesty.
7. **The AD-14 trigger principle as a standing rule**, not merely a change to one script:
   *independence coverage is triggered by phase boundaries and change classification; a self-assessed
   risk tier may scale intensity but may never reduce coverage to zero.* Record the
   **union-not-replacement** correction and its reason: a pure-classification trigger would have
   **removed** independent review from a high-risk bug fix (`clarifying` by FR2's exception 1), which
   today gets agy at MEDIUM+ and codex at HIGH+.
8. **The §1a terminology and the IEEE 1012 / IV&V grounding**, including the explicit statement that
   **HOS has technical independence only — no managerial and no financial independence** — so no
   future document can claim IV&V-grade independence on the strength of this amendment. *This is the
   entry's most important line for anyone reading the framework's claims from outside.*

Plus a short **"Live citations updated in this change"** list: `run_second_review.sh:9`,
`validate_agents.sh:15`, `run_panel.sh:385` (+ `:12`, `:127`, `:427`).

---

## 10. Escalations, issues to file, and the startup-gap analysis

### 10.1 Escalations (technical-design → other roles)

| id | To | Question | Blocks |
|---|---|---|---|
| ESC-1 | **pm-agent** | The FR1–FR8 requirements document does not exist in the repository (TD-VF-4). AD-6 requires FR2's classification test, the operational citation test, and the two exhaustive exceptions to be transcribed **verbatim**. Commit the FR document, or confirm §5's reconstruction as authoritative. | §5 H1's sign-off only; the rest of the build proceeds |
| ESC-2 | **architect** | `spec-completeness-review`'s frontmatter `model:` — `opus` (agent runtime) with the lens class in `model_rank.DEFAULT_COMPLETENESS_CLASS = "fable"`, vs. `model: fable` in frontmatter. Rationale for the split in §5.1. One line either way. | Component E |
| ESC-3 | **architect** | Retaining the codex combined-review fallback in `run_second_review.sh` (§6.3 K5) while AD-3 rejects that shape for the spec panel. Rationale: removing it *reduces* coverage. | Component K |
| ESC-4 | **architect** | Confirm the §7.3 hold-point enumeration (HP-1 spec panel, HP-2 pre-PR second review, HP-3 merge gate). AD-13: *"technical-design proposes the list and I confirm it."* | §7.3 |
| ESC-5 | **architect** | ADR errata: summary row 7 says AD-7-on-`run_second_review.sh` is out of scope; AD-7 rev 3 and row 12 say in scope (TD-VF-7). Proceeding on rev 3. | none |

### 10.2 Issues to file — separately, not folded into this work item

| id | Title | Basis |
|---|---|---|
| ISSUE-1 | `[AI: technical-design] startup-artifact-gap: SPEC PHASE documented as an executing stage with no caller and no enforcer (VF-1 + VF-2)` | ADR §4; cross-reference `audit/2026-06-14-self-3p-eval.md:24` and ADR-033 |
| ISSUE-2 | `[AI: technical-design] bug: overseer.md and OVERSIGHT-CONTRACT.md cite merge_authority.py bounce functions that do not exist (VF-3)` | `record_pr_bounce`, `check_register_completeness`, `bounce_count` — zero `.py` hits |
| ISSUE-3 | `[AI: technical-design] chore: twelve agent files lack HOS:CORE/HOS:PROJECT region markers (VF-7)` | contradicts `CLAUDE.md`'s "every agent file is layered" |
| ISSUE-4 | `[AI: technical-design] startup-artifact-gap: scripts/automation/lib/pr_readiness.py does not exist but is cited as a blocking gate in worker.md:85,233 and METHODOLOGY.md:335 (TD-VF-1)` | **New.** Same failure family as VF-1/VF-2/VF-3 |
| ISSUE-5 | `[AI: technical-design] gap: D53 anti-framing instruction present in only 3 of the reviewer lanes` | ADR §1a peer-review guardrail |
| ISSUE-6 | `[AI: technical-design] chore: agy now supports --output-format json / --json-schema; the HOS#113 "no JSON mode" premise in run_second_review.sh and D41 is stale (TD-VF-5)` | **New.** Verified against the installed CLI |
| ISSUE-7 | `[AI: technical-design] constraint: worker sandboxing must preserve run_spec_panel.sh and vendor-CLI invocation` | AD-6 forward constraint |
| ISSUE-8 | `[AI: technical-design] gap: run_review_chain.sh and worker.md:230 carry duplicate copies of the second-review tier gate (TD-VF-2)` | **New.** File even though §6.4 fixes it, so the D41 pattern is on the record |

**AD-11c is NOT closed and #1079 does not close against this ADR.** The `.md` tier floor remains
wrong for every *other* tier-gated consumer (reviewer-set selection, human-gate firing, suspension
rules); AD-14 only removes its load-bearing role for independence.

### 10.3 Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design, before any code was written
against it?* **Yes — for VF-1, VF-2 and TD-VF-1.** Each is a gate documented as executing with
nothing executing it.

**Affected sign-offs: none are invalidated.** Every prior design/code approval was made against a
pipeline in which the spec phase did not execute. This work item *adds* a gate on a path that was
never built, rather than *revising* a contract already built against. Under the CORE rule — *a
decision for a path never built → prior sign-offs stand* — **all prior sign-offs stand.**

Two boundaries to watch, both already bound:
1. Work merged under an FR2-exempt framing **before this ships** is grandfathered by the AD-5
   acceptance-order rule (§6.7 acceptance path 2) and **must not be retroactively bounced.**
2. Sign-offs written by the same-family, same-class inner-loop chain are **not** invalidated by D55
   rule (1): rule (1) governs whether a same-family check counts *as the independent check*, and for
   every MEDIUM+ step an actual independent review (agy; codex at HIGH+) ran alongside them. The
   exposure is confined to LOW-tier steps merged before a verified-enabled Copilot — bounded,
   enumerable from the audit log, and forward-closed by §7.7 and AD-14.

---

## 11. Build order

Dependencies are real; this order is not a preference.

| # | Slice | Depends on | Why here |
|---|---|---|---|
| S1 | **A** `model_rank.py` + tests | — | Four components consume it |
| S2 | **B** `spec_panel_logic.py` + tests | S1 | Pure logic; testable without a model |
| S3 | **O(a)** contract §2b taxonomy + §1 filesystem + §6a events | — | B/C/D/E/F/I all quote these field names; land the schema before the consumers |
| S4 | **C** `run_spec_panel.sh` + tests | S1, S2, S3 | Must exist **before** any agent file references its path (TD-VF-12) |
| S5 | **E** new agent + full registration surface + `docs/AGENTS.md` §30 | S3, S4 | `check_agents_static.sh` §2 and §3 both gate this |
| S6 | **F** `spec-red-team.md` taxonomy reconciliation | S3 | Boundary sentence must be byte-identical to S5's |
| S7 | **D** `spec_gate.py` + tests | S3, S4 | Reads S4's artifact and S3's schema |
| S8 | **G** `pm-agent.md` resolver + `docs/AGENTS.md:277` | S3, S7 | Names the enforcer |
| S9 | **H** `worker.md` — both-modes hoist, step 8.0, `:229` note, step 8.4 | S4, S7 | Wires the hold point; §8.4 needs S10-S12's flag names |
| S10 | **J** `second_review_logic.py` union + tests | — | Independent; do it before its two callers |
| S11 | **K** `run_second_review.sh` — trigger, AD-7 posture, `:9` comment | S10 | |
| S12 | **L** `run_review_chain.sh` union (TD-VF-2) | S10, S11 | **Without this, S10–S11 are inert below MEDIUM** |
| S13 | **M** `run_panel.sh` predicate + strings + tests | S1 | |
| S14 | **N** `validate_agents.sh:15` comment | — | Trivial; fold into S11's commit if convenient |
| S15 | **I** `overseer.md` FR8 bounce condition | S3, S4 | Detects S4's artifact; uses S3's event |
| S16 | **P** `validate_setup.sh` Copilot precondition | — | Independent |
| S17 | **O(b) + Q** contract §1b hold points + the FR7 doc sweep | S4–S16 | Documents what actually shipped |
| S18 | **R** research note | — | Independent, but land after S17 so the terminology matches |
| S19 | **S** `DECISIONS.md` D55 | **everything above** | It must describe what shipped, including the AD-11a correction (§9.2 item 4) |
| S20 | ISSUE-1..8 filed | — | Any time; before the PR |

**PR-size constraint (`docs/PR-SIZE-POLICY.md`, `worker.md:123,264`):** >15 files or >10 commits
requires a split; 25 files is a hard ceiling. This work item touches well over 25 files. **Split into
at least four PRs** along the seams: (P1) S1–S7 the gate machinery; (P2) S8–S9 the agent wiring;
(P3) S10–S15 the trigger and outage work; (P4) S16–S20 docs, research note, D55. Each PR must be
independently green.

---

## 12. Test plan

Conventions matched: pure logic → `tests/oversight/test_<module>.py` importing directly (root
`tests/conftest.py` puts `scripts/oversight/` and `scripts/oversight/validators/` on `sys.path`);
shell scripts → drive the real script as a subprocess in a `tmp_path` cwd, exercising only paths
that short-circuit before any model call, exactly like
`tests/oversight/test_second_review_env_threshold_clamp.py`; framework/registration invariants →
`tests/framework/`. Nothing may require a live model, network, or authenticated `gh`.

### 12.1 `tests/oversight/test_model_rank.py` (S1)
1. `rank()` returns 1/2/3/4 for the four registered classes, case-insensitively.
2. `rank("gpt-5")`, `rank("")`, `rank(None)` → `None`. **Never a default.**
3. `class_of("claude-opus-4-8")` → `"opus"`; `class_of("opus")` → `"opus"`;
   `class_of("claude-sonnet-4-6")` → `"sonnet"`; `class_of("gemini-3")` → `None`.
4. `class_of` does not false-match on an unrelated substring occurrence (boundary matching).
5. `is_class_differential(4, 3)` True; `(3, 3)` **False** (same-class is the prohibited case);
   `(2, 3)` False; `(None, 3)` False; `(4, None)` False.
6. `highest_author_rank` over the three real bundle-author agent files returns rank 3 / `"opus"`
   (this pins VF-9 — the test **must** read the real `.claude/agents/*.md`, so a future promotion of
   `pm-agent`/`architect`/`technical-design` fails loudly rather than silently flipping the flag).
7. `highest_author_rank` returns `None` when any author's class is unregistered, and the evidence
   row names the offending agent.
8. `reviewer_admissible("opus", "claude", author_rank=3)` → `(False, …)`;
   `("fable", "claude", 3)` → `(True, …)`; `(None, "agy", 3)` → `(True, "cross-vendor")`;
   `("fable", "claude", None)` → `(False, …)` (fail-closed on unknown author rank).
9. CLI: each subcommand emits valid JSON and exits 0; usage error exits 2.

### 12.2 `tests/oversight/test_spec_panel_logic.py` (S2)
1. `bundle_digest` is stable across call order and changes when any byte or any filename changes.
2. `bundle_digest` raises on a missing path (never silently skips).
3. `classify_lens_output`: `""` → `error`; valid JSON → `ran`; prose → `unparseable`.
   **Explicit test that `unparseable` is never mapped to `error` or `pass`.**
4. `decide` truth table — all four rows of §4.1 B3, asserting `block_reason`, owner, and exit code
   for each.
5. `decide` with agy `status="error"` → counted as **absent** → `RULE2_SOLE_SAME_FAMILY` (the
   error-is-not-approval rule).
6. `decide` with the completeness lens absent but agy present → `FR1_LENS_ABSENT`, **not**
   `RULE2_SOLE_SAME_FAMILY`. This is the AD-7 "two owners" requirement; the two must never collapse.
7. `validate_findings`: `missing-scope` from the adversarial lens → invalid;
   `gaming-vector` from the completeness lens → invalid; `ambiguity` from either → valid;
   unknown `gap_type` → invalid; **an invalid finding is retained and flagged, never dropped**.
8. `dedupe`: an identical finding from both lenses files once with `corroborated_by: completeness`;
   two findings with the same text but different `gap_type` are **not** merged.
9. `render_header` emits **every** field of §4.2 C7 on every code path, including the blocked ones
   (parameterised over all four `block_reason` values).

### 12.3 `tests/oversight/test_run_spec_panel.py` (S4) — hermetic, subprocess
1. Missing `--step` → exit non-zero with a usage message (mirrors `run_second_review.sh:153-156`).
2. `--dry-run` writes `.claudetmp/spec-panel/step{N}-*.md` with `verdict: dry-run`, a real
   `bundle_sha`, `author_highest_rank: 3`, and `completeness_lens_class_differential: true`.
3. `OVERSIGHT_SPEC_COMPLETENESS_MODEL=none` → **exit 3**, no artifact-with-a-pass, message names the
   rejected value. Repeat for `off`, `skip`, `0`, `""`.
4. `OVERSIGHT_SPEC_COMPLETENESS_MODEL=gpt-5` (unregistered) → **exit 3** (AD-10 fail-closed).
5. `OVERSIGHT_SPEC_COMPLETENESS_MODEL=opus` (registered, same class as authors) → **exit 0** in
   `--dry-run`, with `completeness_lens_class_differential: false`. **This and #4 are the two
   branches AD-3 deliberately separates; both must be pinned.**
6. `OVERSIGHT_SPEC_ADVERSARIAL_CLI=claude` → exit 3 (a knob may not zero the cross-vendor count).
7. Both knobs set to the same participant → exit 3.
8. A repo-local `.env` containing `OVERSIGHT_SPEC_COMPLETENESS_MODEL=none` has **no effect** — the
   script does not read `.env`. (The `.env`-based attack that HOS#985 closed for thresholds.)
9. A `--bundle` path that does not exist → exit 2, no artifact.
10. Header field-name lock: the set of `key:` lines in the artifact equals the §4.2 C7 list exactly.
    (`spec_gate.py` and the overseer both parse this; a rename must break a test, not a gate.)

### 12.4 `tests/oversight/test_spec_gate.py` (S7)
1. No artifact for the step → exit 1, `SPEC-PANEL-ARTIFACT-MISSING` in output.
2. Artifact with `verdict: error` → exit 1, `SPEC-PANEL-VERDICT-ERROR`, and the `block_reason` is
   echoed.
3. Artifact with `verdict: unparseable` → **passes the artifact checks** (it is not `error`) but
   raises a conditional item in `--json` output.
4. Newest-artifact selection: two artifacts for the same step, the older `pass` and the newer
   `error` → the **newer** governs.
5. `gh` unavailable → exit 1 with `SPEC-GATE-UNQUERYABLE`. **The gate must not pass.** (Simulate by
   running with a `PATH` that omits `gh`.)
6. `Ready for coder:` matching — `YES` passes; `yes`, `Yes`, `YES (pending)`, and the literal
   template `[will be set to YES by pm-agent after resolution]` all **fail**.
7. `--json` output shape is stable and parseable.
8. All checks are evaluated even after the first failure (the output lists every blocker).

### 12.5 `tests/oversight/test_second_review_logic.py` (S10) — extend the existing file
1. **Regression:** every existing test passes unmodified with the new kwargs defaulted to `None`.
2. `classification="additive"`, `tier="LOW"`, `tier_floor="LOW"`, `score=0.0` → `run_agy=True`,
   `run_codex=False`.
3. `classification="structural"` → same.
4. `classification="clarifying"`, `tier_floor="LOW"`, `score=0.0` → `run_agy=False` (the residual
   exception, pinned so a later change to it is deliberate).
5. `classification="clarifying"`, `tier_floor="MEDIUM"` → `run_agy=True` (union: tier arm).
6. `classification="clarifying"`, `tier="HIGH"`, `tier_floor="LOW"` → `run_agy=True`,
   `run_codex=True` (`max(tier, tier_floor)` — the tier arm may not be weakened by the floor).
7. **Anti-tamper:** `agy_threshold=9.0, codex_threshold=9.0, score=0.0, tier="LOW",
   tier_floor="LOW", classification="additive"` → `run_agy=True`. *No env value may suppress the
   classification trigger.*
8. `classification=None` / `""` / `"weird"` → treated as firing (fail-closed).
9. `effective_classification`: classifier unavailable → `("structural", "fail-closed-classifier-unavailable")`;
   non-empty signals → `("structural", "re-derived-2a-override")`; declared `clarifying` with no
   signals → `("clarifying", "declared")`.
10. `effective_classification` never returns `clarifying` when signals are present — the §2a override
    cannot be overridden by a self-label.

### 12.6 `tests/oversight/test_second_review_ad14_trigger.py` (S11) — hermetic, subprocess
1. `--classification additive --score 0 --tier LOW` in an empty git repo → the script does **not**
   write `verdict: skipped`; it proceeds to the availability pre-check. (Assert on stdout/exit, not
   on a model call.)
2. `--classification clarifying --score 0 --tier LOW` → skip sentinel written, and its `reason:`
   names all three arms (classification, tier floor, score).
3. The skip sentinel still carries `agy_threshold:`/`codex_threshold:`/`verdict:` in the existing
   format — i.e. `tests/oversight/test_second_review_env_threshold_clamp.py` still passes untouched.
4. `.env` with `OVERSIGHT_AGY_THRESHOLD=9` **and** `--classification structural` → agy still fires.
   (The HOS#985 attack composed with the new trigger.)
5. `change_classifier.py` unreachable (simulated) → the run proceeds fail-closed as `structural`, and
   `classification_source: fail-closed-classifier-unavailable` appears in the header.

### 12.7 `tests/oversight/test_run_review_chain_trigger.py` (S12)
1. `--tier LOW --classification additive --step 1 --dry-run` → the chain reports it **would** run the
   second review (today it prints `skipping`). This is the TD-VF-2 regression test.
2. `--tier LOW --classification clarifying --step 1 --dry-run` → still skips.
3. The chain passes `--classification` through to `SR_CMD` (assert on the `[dry-run] would run:` line).
4. `--step` is required whenever the union fires, including at LOW.
5. **Single-source assertion:** `run_review_chain.sh` contains no `rank "$TIER"` comparison for
   reviewer selection — it calls `second_review_logic.py select-reviewers`. (A grep-style guard,
   like `tests/framework/test_consumer_agents_canonical.py`'s installer assertions.)

### 12.8 `tests/oversight/test_run_panel_author_exclusion.py` (S13)
1. With the current roster and `--author-class sonnet`, every entry survives the filter (the
   no-behavioural-delta guarantee).
2. With an injected `claude-sonnet:correctness` roster entry and `--author-class sonnet`, the entry
   is excluded and the reason is logged.
3. With an injected `claude-fable:correctness` entry and `--author-class opus`, the entry is admitted.
4. With `--author-class` unresolvable, every same-family entry is excluded (fail-closed).
5. **String assertions:** `run_panel.sh` no longer contains the literal `Opus authored → excluded`
   nor `The author was Claude Opus`. (Pins TD-VF-3's behavioural corrections.)

### 12.9 `tests/framework/test_spec_completeness_review_registration.py` (S5)
1. `.claude/agents/spec-completeness-review.md` exists and its `name:` frontmatter matches the slug.
2. Its `model:` value resolves to a **registered class** via `model_rank.class_of` and is **not** a
   pinned generation ID (assert it does not match `r"-\d+-\d+$"`). This is the #1122 guard.
3. It carries `HOS:CORE:START/END` and `HOS:PROJECT:START/END` markers, in that order (VF-7).
4. It appears in `scripts/framework/consumer_agents.txt`, in the `hos_install.sh` fallback array, and
   in `framework-setup-validator.md`'s `REQUIRED` list.
5. It appears in `docs/AGENTS.md` as `### 30.` and **no existing section number changed** (assert the
   full `### N.` sequence is `1..30` with `18 == spec-red-team` and `29 == post-change-sweep`).
6. **Taxonomy parity:** the seven `Gap type` values and the verbatim boundary sentence
   *"The `missing-requirement` / `missing-scope` boundary is: **is the area addressed at all?**"*
   appear in `contract/OVERSIGHT-CONTRACT.md`, in `spec-red-team.md`, and in
   `spec-completeness-review.md` — and the three renderings are byte-identical after whitespace
   normalisation. *(AD-4: "that test must appear verbatim in both agent files, or the two lenses
   will file the same finding under two types and the provenance data is worthless.")*
7. `spec-red-team.md` contains **exactly one** gap-taxonomy block — assert the old
   `[gaming-vector|contradiction|implicit-assumption|missing-edge-case]` and
   `[ambiguity | missing requirement | contradiction | implicit assumption]` strings are both gone.
8. `spec-red-team.md` still contains `Do not invoke codex` and still declares agy (charter and vendor
   unchanged — AD-4 scope discipline).
9. Extend `tests/framework/test_consumer_agents_canonical.py::test_core_oversight_agents_present`
   with `spec-completeness-review`.

### 12.10 `tests/framework/test_contract_hold_points.py` (S17)
1. `contract/OVERSIGHT-CONTRACT.md` contains a §1b hold-point table with exactly the three rows
   HP-1/HP-2/HP-3, each naming a signature, a traveller, an independent participant, and an enforcer.
2. Every enforcer path named in that table **exists on disk**. (The direct antidote to VF-1/VF-2/
   VF-3/TD-VF-1: a hold point whose enforcer does not exist fails a test.)
3. The binding-16b sentence appears verbatim in the contract, in `spec-completeness-review.md`, and
   in `spec-red-team.md`.

### 12.11 `tests/framework/test_decisions_d55.py` (S19)
1. `DECISIONS.md` contains a heading matching `^## 2026-07-31 — D55:` and it is at the **end of
   file** (nothing appended after it in this change).
2. D4 and D16 line content is **unchanged** (compare against the pre-change blob via
   `git show HEAD~N` in a subprocess, or pin the exact strings).
3. The D55 body contains the literal token `D16:80` (the explicit-supersession requirement).
4. The D55 body contains the word `loosen` (or `loosening`) — the direction-of-change disclosure.
5. The D55 body does **not** cite AD-11a as a compensating tightening (§9.2 item 4's correction).

### 12.12 `tests/framework/test_research_note_ad16.py` (S18)
1. The note exists under `research/findings/`, opens with `# Finding:`, and carries a `**Role:**`
   header.
2. It contains a divergence section naming **technical**, **managerial**, and **financial**
   independence and the sentence that HOS satisfies technical only.
3. **Negative assertions — the attribution guard:** the note does not contain the token `fable` or
   `opus-4-8` within the paragraph describing the #972–#1002 batch. Implement as: the batch paragraph
   contains `attribution unresolved` and contains neither model token.
4. The note contains `#972` and `#1002` and `30 of 31`.
5. The note contains no issue number outside the fixed set `{1060..1074, 1078, 1079, 1082, 972..1002}`
   — a regex sweep for `#\d+` with an allowlist. *This is the anti-fabrication guard; B1 was two
   swapped issue numbers in an otherwise coherent document.*

### 12.13 Manual / operator verification (cannot be automated hermetically)
- One real `run_spec_panel.sh` execution against a real bundle with both CLIs available: confirm the
  artifact, both lenses' status `ran`, `hold_point_discharged: true`, and non-zero token counts.
- One execution with `agy` removed from `PATH`: confirm exit 1 and `RULE2_SOLE_SAME_FAMILY`.
- One execution with an unreachable completeness model: confirm exit 2 and `FR1_LENS_ABSENT`.
- Confirm the `fable` class alias is accepted by the `claude` CLI (**unverified at design time** —
  see ESC-2). If it is not, `DEFAULT_COMPLETENESS_CLASS` must be set to a working alias and the
  discrepancy reported, **not** worked around by disabling the lens.
- `./scripts/framework/check_agents_static.sh` exits 0.
- `./scripts/framework/run_tests.sh` passes including the 80% coverage gate.

---

## 13. Explicit non-goals

- No application code, templates, or migrations are written here.
- No `reason_category` enum extension.
- No new bounce counter (`bounce_count(cid) >= 2 → HUMAN_REQUIRED` is reused unmodified;
  `overseer.md:271` already forbids a separate one for out-of-scope bounces — same rule here).
- No re-implementation of `change_classifier.py` detection.
- No function call to `record_pr_bounce`, `check_register_completeness`, or `bounce_count` anywhere
  in new material — they do not exist (VF-3).
- No reference to `scripts/automation/lib/pr_readiness.py` in new material — it does not exist
  (TD-VF-1).
- No extension of the AD-16 citation set by inference.
- No model attribution for the #972–#1002 batch.
- `code-reviewer` stays rank 2; AD-11a's promotion and its static class-relation check are **not**
  implemented (permanently withdrawn, rev 6).
