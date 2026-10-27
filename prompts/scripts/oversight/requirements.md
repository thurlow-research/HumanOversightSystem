# Prompt Artifact — requirements.txt

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/requirements.txt` |
| **Description** | filelock>=4.2.1 floor + venv re-sync note (#2164) |
| **Date** | 2026-10-25 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Worker → `coder` subagent brief (verbatim, trailer block and cwd/branch lines elided):

```
Issue #2164 (HOS repo). LOW-risk dependency-hygiene fix. Do NOT edit any .claude/agents files.

Investigation already done (verified):
- pip-audit 2.10.1 requires CacheControl[filecache]; CacheControl declares
  `filelock>=3.8.0 ; extra == 'filecache'`. So filelock is NOT orphaned — `pip show`
  "Required-by" just ignores extras-only edges.
- A fresh `pip install --dry-run -r scripts/oversight/requirements.txt` resolves
  filelock 4.2.4 (fixed; CVE-2026-112940/-112913/-112907 are fixed in 4.2.1).
- The Worker clone's existing venv sits on filelock 4.0.8 because
  scripts/oversight/ensure_venv.sh builds the venv once and never re-syncs an existing
  healthy venv against requirements.txt (intentional — tests/automation/test_ensure_venv.py
  pins "healthy existing venv does not reinstall"). And re-running
  `pip install -r requirements.txt` on that venv would NOT upgrade filelock, since 4.0.8
  still satisfies `>=3.8.0`. A declared floor is what makes a re-sync upgrade it.

Make these changes:
1. scripts/oversight/requirements.txt: add `filelock>=4.2.1`, with a comment block
   matching the existing pyjwt floor's style (just after the pyjwt block): not imported by
   HOS; arrives via pip-audit → CacheControl[filecache] (an extras-only edge, so
   `pip show filelock` reports Required-by: (none) and it looks orphaned); floor exists so
   a stale venv re-synced with `pip install -r` drops 4.0.8's three advisories (#2164);
   >=4.2.1 clears all three.
2. scripts/oversight/ensure_venv.sh header comment: add a short note that an existing
   venv is NOT re-synced when requirements.txt changes (floors such as pyjwt/filelock
   reach it only on rebuild), and the remediation is
   `scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt`
   (or delete .venv to rebuild). Comment only — no behaviour change.
3. Check tests/oversight/test_security_scan_exemptions.py for how the pyjwt floor is
   asserted. If there is a natural analogous test, add one for filelock asserting
   requirements.txt declares a filelock floor >= 4.2.1 (parse with packaging). Keep it small.

Then run the two test files; commit once. Do not push, open PRs, file issues, or edit labels.
```

## Constraints Specified

- No behaviour change to `ensure_venv.sh` (comment only); the no-reinstall-on-healthy-venv contract stays.
- Floor follows the existing pyjwt/certifi transitive-floor convention in `requirements.txt`.
- Out of scope: black CVE-2026-114134 and opentelemetry-api CVE-2026-114603 (tracked in #2147).
- Must NOT edit `.claude/agents/**`.

## Refinement History

First attempt worked. Risk tier raised LOW → MEDIUM by risk-assessor (composite 0.3287); trailers amended accordingly.

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
3. Compare key logic paths against `scripts/oversight/requirements.txt`
4. Note any drift in a new version artifact (`requirements.v1.md`)
