# Prompt Artifact — scripts/oversight/suspension_manager.py (#2392 SHA-pinned manifest human gate)

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/suspension_manager.py`, `scripts/automation/lib/pr_readiness.py`, `tests/oversight/test_suspension_timebox.py`, pr_readiness REQ-W-18 tests |
| **Description** | Read the step-manifest human gate (TD-2214 D-17) at pinned SHAs — default-branch flag OR head flag — and fail closed when the working-tree manifest differs from the head blob (#2392, TD-2214 AM-4) |
| **Date** | 2026-11-20 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (gate-resolution path; D-7 human-gate input) |
| **Human review status** | Pending |

---

## Prompt

The worker (top-level session) dispatched the `coder` subagent with the brief below. The design
is TD-2214 amendment AM-4 (`docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md`,
header lines AM-4 / ARCH-AM4, D-17, D-22, §5.2, §5.2.2, §5.4, §9 rows 1–3, §10 group (i)),
approved by the architect with AR-AM4-1 and AR-AM4-2 applied.

```
Implement TD-2214 amendment AM-4 (#2392) on the current branch. Do NOT switch branches,
stash, checkout, reset or rebase. Run single Bash commands only (no && chains, no pipes
into tail); redirect long output to .claudetmp/ and Read it.

Design: docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md — read the AM-4 and
ARCH-AM4 header lines, D-17, D-22, §5.2 (the [AM-4] paragraphs), §5.2.2 in full, §5.4
[AM-4], §8 R-5 [AM-4]/[ARCH-AM4], §9 rows 1-3, §10 group (i) T-G1..T-G13, and the
[ARCH-AM4] review at the end of §12. Implement exactly that:

1. suspension_manager.py: move the manifest line-scan into _manifest_gate_scan(text, step)
   per §5.2.2 item 1 as amended by AR-AM4-1 (None only when a steps: block exists and the
   step is not in it); manifest_human_gate_required(path, step) becomes a wrapper with
   unchanged behaviour (existing test_manifest_* tests must pass unchanged).
2. read_manifest_gate_at(sha, step, repo_root, *, unlisted_step) per §5.2.2, reusing the
   _git ls-tree regular-file + git show pattern of read_default_branch_suspension, with the
   AR-AM4-2 canonical-text rule on the default read.
3. effective_manifest_human_gate(step, head_sha, default_read, repo_root) with checks
   G1..G6 and error texts E-G1..E-G4 exactly as §5.2.2 states.
4. check_suspended_resolutions: required keyword-only human_gate_error; S3 substitution.
5. cmd_check_suspended_resolutions: pinned read only inside the suspension_applies branch;
   --human-gate-required stays a required floor.
6. pr_readiness._check_dep_mapper_suspension: drop manifest_path; use
   effective_manifest_human_gate; update the assess_pr_readiness call site.
7. Tests: T-G1..T-G13 (tests/oversight/test_suspension_timebox.py and the existing REQ-W-18
   tests in tests/ — grep for _check_dep_mapper_suspension / REQ-W-18); convert
   test_b11_cli_manifest_flag_cannot_be_lowered and test_req_w18_manifest_flag_and_tier_floor
   to the committed-manifest form as §10 says. Use real temp git repos under tmp_path.
8. Update the module docstring if the CLI mode description mentions the manifest read.

Commit with this exact trailer block (one contiguous block, no blank line inside):
  Prompt-Artifact: prompts/scripts/oversight/suspension_manager.v2392.md
  AI-Model: claude-opus-5-5
  AI-Risk: HIGH
  Supervised-by: ScottThurlow
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Run the touched test files with scripts/oversight/.venv/bin/python -m pytest <files> -q
(redirect output to .claudetmp/test-2392.log) and black --check on touched .py files before
committing. Self-flag per AGENTS.md (RISK/CONFIDENCE/BLAST RADIUS) in your report.
```

## Round SR (2026-11-23)

Brief to the coder (implementation of TD-2214 AM-4 SR-1 to SR-6, risk HIGH, gates the D-7 human gate):
implement exactly the "[AM-4 SR]" block in section 5.2.2 of
docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md (SR-1 to SR-6, the round-2 fold,
[ARCH-AM4-SR] and [ARCH-AM4-SR round 2], both APPROVED) and tests T-G14 to T-G20 in section 10(i).
Code: _manifest_scan, manifest_human_gate_required (docstring), and effective_manifest_human_gate
(SR-4 git toplevel, E-G5) in scripts/oversight/suspension_manager.py. Tests are appended to
tests/oversight/test_suspension_timebox.py, reusing the existing helpers. Every SR rule fails
closed: the scanner is never looser than a YAML parser. The T-G19 oracle imports PyYAML
unconditionally and skips steps items that are not dicts. All existing tests pass unchanged.

## Round SR-AL (2026-11-23)

Brief to the coder (risk HIGH, gates the D-7 human gate): implement the "[AM-4 SR-AL]" block (AL-0
to AL-6) of docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md, the round-4 fold
(which wins over AL-0, AL-5 and SR-6), the architect notes [ARCH-AM4-SR round 3] and
[ARCH-AM4-SR round 4] (both APPROVED), and tests T-G21 to T-G25b plus the T-G18, T-G19 and T-G24
revisions. The trigger was the security review of 784c270f0: Unicode-whitespace padding and
plain-scalar continuation lines. Inside the `steps:` block the scanner now accepts a line only if
it matches the canonical-line allowlist (`_classify_steps_line`); anything else gates the whole
scan. Blank and comment lines never end the block; SR-3 (a)-(d) stay mandatory outside it. E-G5
wording follows AL-6. Per AR-AL-3, one comment line is added above `steps:` in
contract/step-manifest.template.yaml. Files: scripts/oversight/suspension_manager.py,
tests/oversight/test_suspension_timebox.py, contract/step-manifest.template.yaml. The repro
probes .claudetmp/probe2392sr.py and .claudetmp/fuzz2392sr.py must show zero looser-than-PyYAML
cases; each new or changed function needs a mutation score of at least 75%.

## Round AL-WD (2026-11-25)

Brief to the coder (risk HIGH, gates the D-7 human gate): implement the "[AM-4 AL-WD]" block
(AL-WD-0 to AL-WD-11) of docs/v0.7.0/TECHNICAL-DESIGN-2214-dep-mapper-low-suspension.md as
approved in [ARCH-AM4-WD] with AR-WD-1 (G4 lstats each cumulative prefix of contract/, outermost
first, first failing prefix decides) and AR-WD-2 (security's fuzz obligation, not the coder's).
This records human ruling A on #2392: extend the canonical-line allowlist to the whole document,
and gate any indented first line or BOM. The trigger was the FINAL second review: an indented
document (F1) and a BOM-prefixed document (F2) each hid a decoy column-0 steps block in a
multi-line value that the denylist missed. Outside the steps block the scanner now accepts only
blank and comment lines, the one leading marker, the canonical steps line, KEY:, KEY: VALUE at
column 0, and a one-level nested mapping under an empty-valued key; U+FEFF anywhere is True in the
pre-scan. Also folded in: agy L1 (every intermediate path component of the manifest must be a real
directory) and agy L2 (the real-manifest test takes step ids from the PyYAML oracle). Files:
scripts/oversight/suspension_manager.py and tests/oversight/test_suspension_timebox.py (T-G27 to
T-G34). The template is not edited. The outside-line classification is inlined in _manifest_scan,
so T-G31 is not required.
