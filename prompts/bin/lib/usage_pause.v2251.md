# Prompt Artifact — usage_pause.py (#2251: anchored limit lines, duplicates fail closed)

| Field | Value |
|---|---|
| **Generated file** | `bin/lib/usage_pause.py`, `tests/automation/test_usage_pause_parse.py` |
| **Description** | Anchor the `/usage` session / weekly / per-model limit-line matches to whole lines; more than one session or all-models weekly line fails closed as `unparseable` (#2251) |
| **Date** | 2026-11-07 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH (coder-declared expected; `bin/**` protected surface; security-labelled parser change) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Issue #2251. Repo: the current working directory. You are on branch worker-2251-usage-pause-anchored-lines-261107032001-3548466. Do not switch or create branches, do not push, and do not use git stash or git checkout. Commit your work in one commit with these trailers, in one contiguous block after a single blank line:
Prompt-Artifact: prompts/bin/lib/usage_pause.v2251.md
AI-Model: claude-opus-5-5[1m]
AI-Risk: HIGH
Supervised-by: ScottThurlow

## Context
`bin/lib/usage_pause.py` is the ADR-1944 usage pause; it runs before every worker and overseer cron cycle and parses Claude's `/usage` text (`parse_usage`, ~line 710). The text has already been ANSI-stripped and CR-stripped by `decode_result_text`. Today the session and all-models weekly percentages are found with UNANCHORED, last-match-wins searches over the whole text (`_last_match(_SESSION_PCT_RE, text)`, `_SESSION_RESETS_RE`, `_WEEKLY_ALL_PCT_RE`, `_WEEKLY_ALL_RESETS_RE`), and per-model weekly lines with an unanchored `_MODEL_RE.finditer` in `_extract_models`. `/usage` also prints agent-influenced content, e.g. `  Top subagents: <name> N%, ...` where names come from subagent definitions. A substring such as `Current session: 1% used` inside that content, after the real session line, wins and lowers the reading the threshold is checked against. Real lines look like:
  Current session: 11% used · resets Oct 3, 2:40am (UTC)
  Current week (all models): 1% used · resets Oct 10, 12am (UTC)
  Current week (Fable): 0% used · resets Oct 10, 12am (UTC)
(the reset suffix may be absent; see the fixtures in tests/automation/fixtures/usage/ and the existing tests in tests/automation/test_usage_pause_parse.py).

## Build
1. Anchor every limit-line match to a whole line: optional leading horizontal whitespace, the line form, an optional ` · resets <text>` suffix, optional trailing horizontal whitespace, end of line. Use re.MULTILINE (keep re.ASCII) and `[ \t]` rather than `\s` for the leading/trailing whitespace so a match can never span lines. This applies to the session line, the all-models weekly line and the per-model weekly line (`_extract_models`) — the per-model line is the same defect class. Prefer one regex per line kind that captures both the percentage and the reset text, so pct and resets always come from the same line; remove the now-redundant separate *_RESETS_RE patterns if nothing else uses them. `_is_recognised_line` must still recognise these lines (it matches against `line.strip()`).
2. More than one anchored session line, or more than one anchored all-models weekly line, is ambiguous: `parse_usage` must return ok=False with reason `unparseable` (which `fail_mode` already governs). It must NOT fall through to the #2229 "no session limit" path — with two session lines and session_pct unset, that path would otherwise report SESSION_LIMIT_NONE. Do not pick first or last. Leave the per-model duplicate-slug behaviour unchanged (only anchor it).
3. Do not change the #2229 semantics: an absent session line with a present weekly line and no unrecognised limit-like line is still success with SESSION_LIMIT_NONE; `_has_unrecognised_limit_line` stays as is. Do not change any other reason string, ParseResult shape, or caller.
4. Tests in tests/automation/test_usage_pause_parse.py:
   - Replace `test_last_match_wins` with a test that two session lines -> ok False, reason `unparseable`; add the same for two all-models weekly lines; and assert neither yields SESSION_LIMIT_NONE.
   - A real over-threshold session line (e.g. 95%) followed by `  Top subagents: Current session: 1% used 5%, coder 2%` (and a variant where the fake text is any non-line-start substring) must still read 95, ok True. Same for the weekly all-models line (real 95%, fake `Current week (all models): 1% used` embedded mid-line) and for a per-model line (a fake mid-line `Current week (Fable): 1% used` must not override a real Fable line).
   - A fake session substring mid-line with NO real session line must not produce a session reading (session_pct None).
   - Reset text still parses from the same line (existing fixture tests keep passing; add one assertion that resets come from the anchored line).
   - All existing fixtures must parse identically: run the whole tests/automation/test_usage_pause_*.py set and tests/automation/test_hos_usage_poll.py and tests/framework/test_usage_pause_static.py, and keep them green.
5. Self-flag per AGENTS.md (RISK / CONFIDENCE / BLAST RADIUS) in your final report, and list exactly which functions and regexes you changed.
```
