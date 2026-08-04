# Prompt Artifact — merge_authority.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/merge_authority.py` |
| **Description** | Derive security_relevant from scripts/framework/security_surfaces.txt instead of trusting an unpassed caller bool (#1253) |
| **Date** | 2026-08-04 |
| **Model** | claude-sonnet-4-6 |
| **Risk level** | MEDIUM |
| **Human review status** | ⬜ Pending |

---

## Prompt

Provenance, not a single freeform prompt: this fix implements a decision already made
and recorded during an interactive human-proxy session
(`research/sessions/2026-08-04-controls-that-never-fire.md`, decisions table):

> **#1253 signal source** — Both, sequenced. `security_surfaces.txt` now, derived
> **inside** `decide_merge_authority()` rather than passed — a control that depends on
> a caller remembering an input is how this broke. Static-analysis trigger deferred
> behind #1266 and #1170.

That session diagnosed the bug (`decide_merge_authority()`'s `security_relevant` bool
had no real caller — see finding 1 in the session log) and drafted the fix
(`_touches_security_surface()`, `scripts/framework/security_surfaces.txt`, matching
tests) but the working tree was left staged, uncommitted, with no branch or PR — the
session's own artifact list (4 PRs, 14 issues) does not include this one. This
autonomous worker cycle discovered the staged diff directly on `main`, verified it
against #1253's acceptance criteria and the recorded decision above, confirmed no
prior branch/PR already carried it (`gh api pulls?state=all` — no match), moved it to
a properly-owned branch (`bootstrap/create_branch.sh --issue 1253`), ran the required
gates (`run_tests_inner_loop.sh`, `run_validators.sh` → composite 0.4839, tier
MEDIUM), and is submitting it as the PR that session did not open.

## Constraints Specified

- Mirror `_touches_protected_surface()` / `protected_surfaces.txt` exactly in
  structure, glob syntax, and fail-closed-on-read-error contract (explicit design
  constraint in the decision above and in `DECISIONS.md`'s 2026-08-04 entry).
- `security_relevant` parameter stays as an explicit override, OR'd with the derived
  result — not removed, so existing callers that do pass it keep working.
- A missing `security_surfaces.txt` is not itself treated as relevant (its own path is
  covered by `protected_surfaces.txt`, so tampering is independently caught there).
- Static-analysis-derived triggers (bandit findings, etc.) explicitly out of scope —
  deferred behind #1266 and #1170.

## Refinement History

Single pass — no iteration needed; the code, decision record, and test suite were
already internally consistent when discovered.

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
3. Compare key logic paths against `scripts/automation/lib/merge_authority.py`
4. Note any drift in a new version artifact (`merge_authority.v3.md`)
