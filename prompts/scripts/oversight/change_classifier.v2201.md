# Prompt Artifact — change_classifier.py (#2201)

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/change_classifier.py` (+ `tests/oversight/test_change_classifier.py`) |
| **Description** | #2201: drop bare `new\s+state\b` prose alternative from new-user-facing-state signature; 2026-11-03 scope addition: path-scoped `choices=` exemption for repo-root `scripts/`, `bootstrap/`, `bin/` (human ruling 2026-10-30) |
| **Date** | 2026-10-30 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | MEDIUM (coder self-declared LOW; validator composite 0.3584 → MEDIUM; module feeds Condition-10 gating) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Prompt from the worker to the `coder` subagent. It is verbatim except that the commit-message block is summarized:

```
Bug: scripts/oversight/change_classifier.py lines 108-112 define the `new-user-facing-state`
structural signal (in ADDED_LINE_SIGNATURES). Its regex ends in the alternative `new\s+state\b`,
which matches ordinary English prose in Markdown design docs — e.g. the added line
"Constants and the new state variables:" in docs/v0.7.0/TECHNICAL-DESIGN-2122-S1-fingerprint-source.md
raised new-user-facing-state and forced a false Condition-10 ESCALATE in the oversight-evaluator.

Fix (decided): remove the bare `new\s+state\b` alternative. Keep every code-shaped alternative
unchanged (choices\s*=, TextChoices, IntegerChoices, models.TextChoices, StateField, FSMField,
@transition, STATUS_[A-Z], _STATES\b, enum\.Enum). Add a short comment above the entry in the
style of the #2031 comment. Do not add file-extension special-casing. Do not touch other signatures.

Tests: (1) the TD-2122-S1 prose line in a .md file, "There is no new state carrier beyond
needs-human" in a .md file, and the same phrase as a Python comment produce NO
new-user-facing-state signal; (2) `class Status(models.TextChoices):` and
`class Phase(enum.Enum):` in app/models.py still produce it. Write the tests first, confirm (1)
fails before the fix. Run the test file and run_tests_inner_loop.sh.

Commit: one commit, the two files only, one contiguous trailer block, no closing keywords.
```

## Constraints Specified

- Narrow only the `new-user-facing-state` signature. Every other compiled rule must stay byte-identical.
- No `.md` scanning-scope change. The issue offered extension-gating as an alternative, but removing the prose-only alternative is the narrower fix and touches no other signal.
- Real code-shaped state (TextChoices, enum.Enum, choices=, FSM transitions) must still be detected, with tests.

## Refinement History

- v1 (4715b3311): removed `|new\s+state\b` from the regex, added a comment and 5 parametrized tests (3 negatives, 2 positives).
- v2 (2026-11-03 scope addition, human ruling 2026-10-30): added `INTERNAL_TOOLING` (`^(scripts|bootstrap|bin)/`) and a shared `_CHOICES_ALT` constant; `choices=` alone no longer raises `new-user-facing-state` in those repo-root paths (other alternatives unchanged; nested paths like `app/scripts/` still flagged). Tests cover exempt/non-exempt paths, other alternatives, and the #2174 replay.

Accepted residual: a code change that introduces new user-facing state only through a construct
none of the remaining code-shaped tokens covers (e.g. a plain string constant) is no longer caught
by an incidental "new state" comment. The prose alternative never reliably detected that case anyway.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare the `new-user-facing-state` entry against `scripts/oversight/change_classifier.py`

---

## Scope addition (2026-11-03, #2201 human ruling 2026-10-30)

1. A `choices\s*=` match is NOT `new-user-facing-state` when the changed file is HOS internal tooling: a repo-root path under `scripts/`, `bootstrap/` or `bin/`. Exclude by PATH, never by guessing intent from the line content (e.g. do NOT special-case `add_argument`).
2. Every other alternative of `new-user-facing-state` (TextChoices, enum.Enum, STATUS_*, _STATES, @transition, FSMField, ...) stays flagged in those paths exactly as today (outside FRAMEWORK_TOOLING, which is unchanged). `choices=` stays flagged everywhere else - application code, e.g. `app/models.py`, a consumer `src/` file, and a NESTED path such as `app/scripts/x.py` or `src/bin/x.py` (anchor at repo root, `^`, not `(^|/)`).
3. Design decision (made by the worker - implement it, do not substitute another list): add a new module-level constant next to `FRAMEWORK_TOOLING`, e.g. `INTERNAL_TOOLING = re.compile(r"^(scripts|bootstrap|bin)/")`, with a short comment citing #2201 and stating why the existing path sets were not reused: `scripts/framework/protected_surfaces.txt` omits `scripts/automation/` (the #2174 case); `scripts/framework/framework_consumer_files.txt` is the consumer ship-set and deliberately omits internal tooling; `FRAMEWORK_TOOLING` is narrower and exempts every signature, not just `choices=`. Keep the comment density of the surrounding code.
4. Implement the exemption so the `choices=` alternative is not duplicated as a second copy that could drift from the signature regex (e.g. split the `choices\s*=` alternative into a named constant used to build the signature, and a per-signature path-scoped exclusion consulted in `detect_structural`). Keep `ADDED_LINE_SIGNATURES` shape (list of (name, regex-string)) compatible: `_auth_signature_regex()` and any other reader must keep working. Within a single line that matches BOTH `choices=` and another alternative (e.g. `status = models.CharField(choices=Status.choices)` alongside `STATUS_X`) in an internal-tooling path, the other alternative must still produce the signal.
5. Do not change tier-floor logic, FRAMEWORK_TOOLING, or any other signature.
