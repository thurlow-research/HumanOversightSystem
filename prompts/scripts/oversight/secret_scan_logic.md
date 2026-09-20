# Prompt Artifact — secret_scan_logic.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/secret_scan_logic.py` |
| **Description** | Finding-level suppression for the secret-scan gate: unblock the required validator artifact without a whole-file skip (#1754) |
| **Date** | 2026-09-20 |
| **Model** | claude-opus-5 |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

The task came from issue #1754, which is the operative prompt. It was not
paraphrased into a separate instruction — the issue states the problem, rejects
the obvious fix, and fixes the acceptance criteria. Its binding content:

```
secret_scan rejects the committed validator artifact the overseer requires —
every MEDIUM+ PR fails oversight-gate-secret_scan.

signoffs/validators/step{N}/summary.json must be committed (overseer step 3b
fail-closes to HUMAN_REQUIRED without it, and its head_sha must equal the
artifact commit's parent). Its head_sha is a 40-char git SHA, which
detect-secrets flags as a Hex High Entropy String.

This is an incomplete exemption, not a new class of problem:
secret_scan.sh:59-70 already carries an exemption for validation stamps
(64-hex `hash:` line, #1572). The exemption list simply never grew to cover
validator artifacts when #555 promoted the summary to a committed artifact.

The decision worth making deliberately: the obvious fix — adding
signoffs/validators/*/summary.json to the skip list — stops scanning the whole
file. That is wider than the existing stamp exemption: a stamp is a handful of
short fields, whereas a validator summary is ~1,000 lines containing file paths
and code-evidence snippets, which is somewhere a real secret could plausibly
land.

A tighter alternative is to suppress only the specific finding type on the
specific field — a Hex High Entropy String on the head_sha line of a validator
artifact — and keep scanning that file for every other detector (AWS keys,
JWTs, private keys, base64 high-entropy, …). The gate currently parses
detect-secrets' JSON output and counts results, so filtering by
(path-glob, finding-type) is feasible where a whole-file skip is not required.

Whichever is chosen, the suppression must be visible rather than silent — the
gate should report how many findings it suppressed and why, given that the
whole point of the surrounding work (#1750, #1643) is that gates must not
quietly decline to do their job.

Acceptance criteria:
1. A PR that commits signoffs/validators/step{N}/summary.json passes
   oversight-gate-secret_scan in CI.
2. The same artifact is still scanned for every non-head_sha secret shape — a
   planted AWS key or private key inside it must still fail the gate. Proven by
   a test, not by inspection.
3. Any suppression is reported in the gate's output (count + reason), never
   silent.
4. signoffs/validators/step1/summary.json, already on main, passes.
5. The rationale is recorded next to the existing #1572 exemption comment so
   the two read as one policy rather than two ad-hoc skips.
```

## Constraints Specified

- **Runtime**: Python 3.10+, standard library only. The module runs inside the
  oversight venv under `PYTHONSAFEPATH=1`, invoked by a bash gate.
- **Security constraints**: the suppression must be *narrower* than a whole-file
  skip, and must never suppress a detector other than the one the benign shape
  provokes. An exemption whose own evidence cannot be read must not apply.
- **Repo policy**: decision logic belongs in a named, unit-testable Python
  module, not inline `python3 -c` in the shell (#314); the shell keeps the
  pass/fail decision, taken from the module's exit status.
- **What it must NOT do**: no network, no writes, no reliance on the gate's
  caller passing a particular working directory beyond the paths
  detect-secrets itself reports.

## Refinement History

Beyond the issue's own framing, two things were tightened during the build,
both from running the real gate rather than from the prompt:

- **v1** implemented the issue's suggested `(path-glob, finding-type)` filter.
  Testing it showed that a credential planted as `"api_token": "<40 hex>"`
  inside the artifact would inherit the exemption — same path, same detector.
  **vFinal** adds a third condition: the flagged *line* must itself be a
  `*_sha` field holding a bare 40-hex value. Verified by planting a distinct
  high-entropy 40-hex value under `api_token` in a copy of the real artifact
  and confirming it still fails while `head_sha` is suppressed.
- The field-name pattern was widened from a literal `head_sha` to the `*_sha`
  family, so a future range field (`base_sha`, already written by some
  artifacts) does not silently re-block the pipeline.

One defect was found in the code being replaced and fixed in passing: the
inline count used `|| echo "0"`, so a detect-secrets output that failed to
parse reported **zero** secrets and the gate PASSED. That is the same
report-success-having-checked-nothing shape as #1750/#1759, one layer down. It
is now exit 2 → gate failure.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

Pending. This change touches `scripts/oversight/gates/**`, a protected surface,
so human approval is required before merge regardless of computed risk tier.

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above verbatim
3. Compare key logic paths against `scripts/oversight/secret_scan_logic.py` —
   in particular that all three suppression conditions are present, that an
   unreadable line fails closed, and that an unparseable baseline is a gate
   failure rather than a zero count
4. Note any drift in a new version artifact (`secret_scan_logic.v1.md`)
