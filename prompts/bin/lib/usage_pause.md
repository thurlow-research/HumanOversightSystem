# Prompt Artifact — usage_pause.py

| Field | Value |
|---|---|
| **Generated file** | `bin/lib/usage_pause.py` |
| **Description** | Absent /usage session line means no 5-hour limit, not a read failure (#2229) |
| **Date** | 2026-11-05 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH (coder-declared; risk-assessor validated HIGH; validators composite MEDIUM) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Issue #2229, slice S1 (priority:critical bug). Repo <clone-root> [machine path redacted for the portability gate], already on branch worker-2229-session-absent-unlimited-261105080502-3156682. Do not switch/create branches, do not push. Commit your work (one or two commits).

## Problem
`bin/lib/usage_pause.py` (ADR-1944 usage pause) reads Claude's `/usage` text before each cron cycle. The user's plan no longer has a 5-hour session window, so `/usage` NEVER prints a `Current session: N% used · resets …` line now. Real current text (the `result` field, tips trimmed):

ʼʼʼ
You are currently using your subscription to power your Claude Code usage

Current week (all models): 7% used · resets Nov 6, 11:59pm (UTC)
Current week (Fable): 0% used · resets Nov 7, 12am (UTC)

What's contributing to your limits usage?
...
ʼʼʼ

`parse_usage` (~line 654) classifies weekly-present/session-absent as `missing_session` → read failure → with default `fail_mode=closed` every cycle pauses forever. Separately, `_evaluate` (~line 1075) rejects a success reading with no session value (`if session is None or weekly is None or models is None: return _unusable(... "reading_unreadable" ...)`) and always builds the `("session", session, threshold)` limit tuple. Both places must change, otherwise a fixed parser still yields reading_unreadable.

## Human ruling (authoritative; scope is exactly this)
- 5-hour/session line ABSENT → the session check fails open: it does not block; the decision rests on the other checks (weekly all-models + per-model weekly), which are enforced exactly as today.
- Session line PRESENT and parseable (`Current session: N% used`) → session threshold applies exactly as today (other plans / consumer installs still print it).
- Session line present but NOT understood (reworded) → genuine read failure, governed by `fail_mode` (default closed). Keep reason token `missing_session` for this case (it is in READ_FAILURE_REASONS; do not add a new token).
- Weekly (all models and per-model) and every other failure path: UNCHANGED, incl. missing/unparseable weekly → `missing_weekly`/read failure.
- Do NOT add per-check fail_mode overrides. No other behaviour changes.

## Required design
1. **Parser.** In `parse_usage`: when weekly is present and no `_SESSION_PCT_RE` match exists, the reading is valid (ok=True) with "no session limit" ONLY IF the text contains no unrecognised limit line. Define unrecognised limit line (a reworded session/5-hour line) as any line that either (a) contains `% used` (`_ANY_USED_RE`) but matches neither `_SESSION_PCT_RE` nor `_MODEL_RE` (which covers every `Current week (…): N% used` form incl. all-models), or (b) matches case-insensitively `^\s*Current session\b` but not `_SESSION_PCT_RE`. If any such line exists → keep today's `missing_session` failure. Verify against the window-block regexes (`_WINDOW_HEADER_RE`, `_HEAVY_RE` etc. say "% of your usage", "sessions") that existing fixtures don't trip (a)/(b). Represent "no session limit" explicitly in ParseResult (e.g. a new field `session_limit: str` = "none" vs "present", with a default so existing positional constructions still work) — never infer it from session_pct being None.
   Also: if the session line IS present, behaviour is unchanged even if an unrecognised line also exists? — No: keep it simple and conservative: unrecognised-line detection applies only in the session-absent branch; the present-session path stays byte-identical to today.
2. **Reading.** `_success_fields`: when there is no session limit, write `session_limit=none` and do NOT write `session_pct` / `session_resets` (or write them empty — pick one, but the decision must key off `session_limit=none`, not off a missing/blank pct). When a session line exists, write exactly today's keys (you may also add `session_limit=present`; your call, keep tests consistent).
3. **Decision.** In `_evaluate`: if `fields.get("session_limit") == "none"`: a `session_pct` key that is ALSO present with a value is an inconsistent reading → `reading_unreadable` (fail per fail_mode); otherwise drop the session tuple from `limits` and require only weekly + models as today. If `session_limit` is absent (old readings, or any other value than "none"), behaviour is identical to today (session required). Any other `session_limit` value besides none/present → reading_unreadable.
4. **Reporting.** The run summary/reason must show the session as unlimited so an operator can tell it from a real 0%, e.g. `session unlimited, weekly_all 7% < 90, weekly_model:Fable 0% < 90 (reading age 12s)`. The `Decision.session_pct` stays None → the gate verdict prints `session_pct=-`, which `bin/hos-cron`'s `_UP_VERDICT_RE` (line ~507) already accepts — confirm, and do not change bin/hos-cron. Keep within REASON_CAP_CHARS (use `_cap`).
5. **Doc.** `docs/CRON-SETUP.md:256` table row for `missing_session`/`missing_weekly`: update so it says an absent session line is NOT a failure (no 5-hour limit on the plan → session check skipped) and `missing_session` now means a session/limit line was present in a form the parser does not understand.
6. **Check reading schema/version handling** (`SCHEMA_VERSION`, `read_reading`, `_value_cap`, `check_gate_copies`, `run_check`/`_check_reading` and `_success_summary` ~line 1529, which may format session_pct): make every consumer of a success reading handle the no-session case without crashing or printing "None". If an older gate copy reads a new `session_limit=none` reading it will see session None → reading_unreadable → pause; that is the safe direction, note it but don't engineer around it.

## Tests (tests/automation/; reuse tests/automation/usage_support.py fixtures and the style of existing usage_pause tests — grep for parse_usage / evaluate_cycle tests first)
- Exact text above (weekly lines only) → parse ok, session_limit none; end-to-end reading → evaluate → decision=run, class ok, reason says session unlimited, verdict line `session_pct=-` and matches hos-cron's `_UP_VERDICT_RE`.
- Weekly over threshold, no session line → decision=pause class=limit.
- Per-model weekly over threshold, no session line → pause class=limit.
- Old text with session line under threshold → still parses, decision=run, unchanged keys; session over threshold → pause class=limit.
- Reworded session line (e.g. `Current session (5h): 12% used` and `Current 5-hour window: 12% used`, and `Current session: unlimited`) with weekly present → read failure `missing_session` → fail_mode closed pauses (class read_failed), fail_mode open → failopen.
- No weekly line → `missing_weekly`/unparseable failure unchanged.
- Reading with `session_limit=none` AND a numeric session_pct → reading_unreadable. Reading with neither session_pct nor session_limit (legacy shape) → reading_unreadable as today. Unknown session_limit value → reading_unreadable.
- The deadlock acceptance: a no-session text must never yield a read failure (i.e. not self-perpetuating) — covered by the first test; name it clearly.

Run: `scripts/oversight/.venv/bin/python -m pytest tests/automation -q -k usage` plus `tests/framework/test_usage_pause_static.py`, and ruff/mypy if the repo config uses them (check scripts/oversight/gates for lint gates) on the changed files. All must pass.

## Commit
Message to a file under /tmp/claude/ and `git commit -F`. Subject: `fix(usage-pause): an absent session line means no 5-hour limit, not a read failure (#2229)`. Use "Part of #2229" in the body — NO closing keywords (closes/fixes/resolves) anywhere. Trailers as ONE contiguous block after a single blank line:
Prompt-Artifact: none (pending risk assessment)
AI-Model: claude-opus-5-5[1m]
AI-Risk: HIGH
Supervised-by: ScottThurlow
(plus your own Co-Authored-By line if your attribution rule requires it.)

Report: commit SHA(s), files changed, test results (counts), and your AGENTS.md self-flag (RISK/CONFIDENCE/BLAST RADIUS), plus any place you deviated from this design and why.
```

## Constraints Specified

- Scope fixed by the human ruling on #2229 (2026-10-31): only the absent 5-hour/session line changes meaning (fails open); weekly all-models and per-model checks unchanged; reworded session line stays a `missing_session` read failure governed by `fail_mode`.
- Must NOT add per-check `fail_mode` overrides; must NOT change `bin/hos-cron`; must NOT add a new READ_FAILURE_REASONS token.
- The decision must key off an explicit `session_limit=none` reading field, never off a missing/blank `session_pct`.
- Legacy readings (no `session_limit`) behave exactly as before.

## Refinement History

v1 (prompt above): first coder pass. The guard against reworded session lines fired only on `Current session ...` or `% used`. The worker then ran `black` on `bin/lib/usage_pause.py` (lint_check gate formatting only, no logic change) and folded it into the commit.

v2 (risk-assessor finding: the guard failed open on a reworded line without those tokens): the worker sent this follow-up instruction, summarised. Make the guard allowlist-first. A line is recognised if it matches `_SESSION_PCT_RE`, `_MODEL_RE`, the window-block regexes or `_MARKER_RE`. Any other line fails closed (`missing_session`) if it contains a percentage or the word "percent", starts with "Current", or mentions a session or a 5-hour form. Add tests for `Current session: 12 % used`, `5-hour limit: 12%`, `Current 5h window: 12 percent`, `Session usage: 40% used` and a tips-style line. Coder deviation, accepted by prompt-fidelity: the session match is the singular `\bsession\b`, because the real `/usage` text contains "local sessions on this machine".

v3 (code-review round 1): the 5-hour form also accepts plurals (`hours?|hrs?`). An unrecognised line containing `limit(s)` or `reached` plus a digit fails closed. The digit requirement keeps tips prose such as "What's contributing to your limits usage?" valid. A test documents that `Current week (5-hour)` is enforced as a weekly per-model limit. A test comment records that `Rate limit hit` (no digit) staying fail-open is an accepted residual.

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
3. Compare key logic paths against `bin/lib/usage_pause.py`
4. Note any drift in a new version artifact (`usage_pause.v1.md`)
