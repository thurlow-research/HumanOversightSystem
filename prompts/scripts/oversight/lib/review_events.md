# Prompt Artifact — review_events.py

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/lib/review_events.py` (also `scripts/oversight/write_pr_review_event.sh`, `scripts/oversight/check_pr_reviewed.sh`, `tests/oversight/test_check_pr_reviewed.py`) |
| **Description** | PR-review audit event vocabulary + canonical writer (#1699) |
| **Date** | 2026-10-13 |
| **Model** | claude-opus-5-5 |
| **Risk level** | HIGH (coder declared MEDIUM; risk-assessor raised: audit-log writer + protected `overseer.md`) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Dispatched by the autonomous worker to the `coder` agent (single turn):

```
You are implementing issue #1699 ... on branch worker-1699-pr-review-event-vocabulary-261013063501-619689
(already checked out — do NOT create/switch branches, do NOT commit, do NOT push, do NOT file issues
or touch labels). Do not edit anything under .claude/agents/ or bootstrap/ — the orchestrator handles
governance text.

## Problem (bug fix, no separate TD — this message is the design)
scripts/oversight/check_pr_reviewed.sh (the #1524 PR-review idempotency precheck) matches audit
records against an inline closed set REVIEWED_EVENTS = {"pr-review", "human-required",
"idempotent-skip"}. There is no canonical writer: overseer cycles hand-compose
audit_write_event '{"event":...}' JSON, so the event name is free text. The audit log contains
drifted names the reader never matches: pr-reviewed (should be pr-review) and
pr-review-skipped-idempotent (should be idempotent-skip). Result: a review record exists but the
precheck says already_reviewed: false.

## What to build
1. New module scripts/oversight/lib/review_events.py — the single vocabulary shared by reader and writer:
   - CANONICAL_REVIEW_EVENTS: pr-review, human-required, idempotent-skip (the only names the writer emits).
   - LEGACY_ALIASES: {"pr-reviewed": "pr-review", "pr-review-skipped-idempotent": "idempotent-skip"}
     — historical spellings written before this writer existed. Read-only: the reader matches them,
     the writer refuses them.
   - REVIEWED_EVENTS: frozenset union of the two, used by the reader.
   - A comment recording that propose-only-review-skipped is deliberately excluded: it records a
     skip, not a review of that head SHA; the precheck is corroborating evidence only (§1215 stays
     authoritative), so a miss costs a re-check, never a silent suppression.
   - A CLI: python3 -m scripts.oversight.lib.review_events write --pr <n> --head-sha <sha>
     --event <name> [--decision <s>] [--tier <s>] [--comment-url <url>] [--reason <s>] [--root <dir>]
     - --event must be in CANONICAL_REVIEW_EVENTS. On a legacy alias exit 2 with stderr
       "legacy alias '<x>'; write '<canonical>' instead". Any other unknown name: exit 2 listing allowed.
     - --pr must be a positive integer; --head-sha must be 40 lowercase hex. Else exit 2.
     - Record keys: event, pr (int), head_sha, timestamp (UTC YYYY-MM-DDTHH:MM:SSZ, generated), plus
       each optional field only when given (decision, tier, comment_url, reason).
     - Write through the existing canonical Python writer in scripts/oversight/lib/audit_log.py —
       never hand-serialize. Print the record relpath on stdout. --root defaults to ".".
2. Thin bash entry point scripts/oversight/write_pr_review_event.sh: forwards args to the module,
   resolving the repo root from the script's own dir. set -euo pipefail.
3. check_pr_reviewed.sh: replace the inline REVIEWED_EVENTS set with an import from
   scripts.oversight.lib.review_events, without changing [root] semantics or the output contract.
   Update the stale comment that claims overseer.md defines these names.
4. Tests (pytest, tmp_path, no leaked temp): alias records matched; propose-only-review-skipped,
   wrong pr, wrong sha not matched; writer refuses alias / unknown / bad pr / short or uppercase sha;
   round trip write -> check_pr_reviewed already_reviewed true with event pr-review; optional fields
   present only when passed. Run bash scripts/framework/run_tests_inner_loop.sh — must be green.
5. bash scripts/framework/regen_all.sh, then regen_all.sh --check must pass.

Self-flag per AGENTS.md at the end.
```

## Constraints Specified

- Python 3.10+ stdlib only; serialize through `audit_log.write_event`, never by hand.
- Writer refuses legacy aliases and unknown names (exit 2); reader accepts aliases read-only.
- `check_pr_reviewed.sh` output contract and `[root]` semantics unchanged.
- Must NOT edit `.claude/agents/` or `bootstrap/`, commit, push, or touch issues/labels.

## Refinement History

First attempt accepted. The orchestrating worker separately added the `overseer.md` §"Writing the
review audit event" paragraph (agent-definition edit, authored by the top-level session per CLAUDE.md
#1347), deliberately leaving `human-required` on `audit_write_event` because it carries SPEC-378
fields the writer does not model.

Later amendments in the same session:
- v2: after the risk assessment, the writer refuses `human-required`, since it has a SPEC-378 field set. This adds `WRITABLE_REVIEW_EVENTS`.
- v3: code review asked for `_SHA_RE` to use `fullmatch`, so a SHA with a trailing newline is rejected.
- v4: the second review (codex, CWE-426) found that a module in the caller's cwd could shadow these imports. Both entry points now run `python3 -I` and insert the repo root explicitly. A regression test plants a `scripts/` package in the cwd.

## Human Review Notes

<!-- After human review, record findings here. -->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session
2. Paste the prompt above unchanged
3. Compare key logic paths against `scripts/oversight/lib/review_events.py`
4. Note any drift in a new version artifact (`review_events.v1.md`)
