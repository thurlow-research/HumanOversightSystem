# Prompt Artifact — usage_pause.py (#2229 S2: show-last-raw)

| Field | Value |
|---|---|
| **Generated file** | `bin/lib/usage_pause.py` |
| **Description** | Read-only `show-last-raw` diagnostic: print the last raw `/usage` reading and how the parser classifies it (#2229 item 4) |
| **Date** | 2026-11-05 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH (coder-declared expected; `bin/**` protected surface) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
Issue #2229, slice S2 (item 4 of the issue's "Required" list). Repo: the current working directory. You are on branch worker-2229-show-last-raw-261105182002-223581. Do not switch or create branches, do not push, and do not use git stash or git checkout. Commit your work in one commit with these trailers, in one contiguous block after a single blank line:
Prompt-Artifact: prompts/bin/lib/usage_pause.v2229s2.md
AI-Model: claude-opus-5-5[1m]
AI-Risk: HIGH
Supervised-by: ScottThurlow

## Context
`bin/lib/usage_pause.py` is the ADR-1944 usage pause. Each poll, `bin/hos-usage-poll` calls the `last-raw` subcommand (`_cmd_last_raw`), which writes `$STATE/usage-pause/last-raw` (mode 0600; `$STATE` defaults to `~/.hos`). The format is defined in TECHNICAL-DESIGN-1944 §1.6:
- line 1: `# hos-usage-poll last-raw run_epoch=<int> read=<exited|timeout|spawn_failed|none> rc=<int|-> stream=<stdout|stderr|none> bytes=<int>`
- then the raw bytes: the full stdout (the claude JSON envelope) when stream=stdout, or the stderr tail when stream=stderr.
Nothing reads `last-raw` for a decision. When a reading fails (for example `read_failed:missing_session`), today the only way to see why is `cat ~/.hos/usage-pause/last-raw`. The issue asks for a read-only subcommand that shows the raw reading and its parse result.

## Build
Add a subcommand `show-last-raw --state-dir DIR` to `bin/lib/usage_pause.py`:
1. **Strictly read-only.** No mkdir and no writes of any file, including `reading`, `last-raw`, history or `.prom`. Do not load or validate settings. Do not touch the network or ssh.
2. Read `DIR/usage-pause/last-raw`, capped at INPUT_CAP_BYTES plus a header allowance (reuse the existing read helpers or constants). If the file is missing or unreadable: print one `usage_pause show-last-raw: ...` line to stderr (use `_flatten`/`ascii_fold`) and return EXIT_FAIL.
3. Parse line 1 against the §1.6 header grammar with a strict regex. If the header does not match, still print the body (step 5), but report `parse: header_invalid` and do not classify.
4. When the header is valid and `stream=stdout`, re-run the **same** classifier that `poll-record` uses: `classify_read(ReadOutcome(read, rc, None), body, b"")`. Do not duplicate parsing logic. When `stream` is stderr or none, or `read != exited`, report `parse: not_classified (stream=<s> read=<r>)`. A re-classification of a transport failure from a stderr tail is not meaningful.
5. Output to stdout, plain ASCII, in this order:
   - `last_raw: <path>`
   - `header: run_epoch=<n> (<UTC ISO via _utc_iso>) read=<r> rc=<rc> stream=<s> bytes=<n>`, or `header: invalid`
   - `parse: outcome=<success|failure> reason=<reason or ->`, then whichever of these the Classification/ParseResult has: `session_limit=<present|none>`, `session_pct=`, `weekly_all_pct=`, and one `model <slug>=<pct>` per ModelWeekly; for a failure, the `detail` (flattened, ascii-folded, capped with `_cap` at the existing REASON_CAP_CHARS or a similar existing cap)
   - `--- result text ---` and then the envelope's `result_text` when the envelope parsed (that is the human-readable `/usage` text), otherwise `--- raw body ---` and the body.
   The raw or result text is untrusted terminal input: strip control characters except newline and tab (an ANSI escape must not reach the terminal), and replace non-ASCII with `?` via `ascii_fold`. The usage text has no secrets, so do not redact it.
6. Exit 0 whenever the file was read, even if the classification is a failure. The command reports and does not judge.
7. Register the subparser in `_build_parser` next to `last-raw`, with `--state-dir` required.

## Docs
In `docs/CRON-SETUP.md`, wherever the runbook says `cat ~/.hos/usage-pause/last-raw` or `cat last-raw` for parse-failure debugging (around lines 226, 251, 254, 256, 257 and 515), point to `python3 <clone>/bin/lib/usage_pause.py show-last-raw --state-dir ~/.hos` as the primary command, keeping `cat` as the fallback. Keep the edits minimal and match the surrounding style.

## Tests
Add `tests/automation/test_usage_pause_show_last_raw.py`, in the style of `tests/automation/test_usage_pause_check_cli.py`, using `tests/automation/usage_support.py` helpers and envelope fixtures where they exist. Cover:
(a) a current-format envelope with no session line (weekly lines only) → `outcome=success`, `session_limit=none`, the weekly pct appears, exit 0;
(b) an old-format envelope with a session line → session_pct shown;
(c) an envelope whose result has an unrecognised limit-like line → `outcome=failure reason=missing_session`, exit 0;
(d) a header-only `read=none` file → `not_classified`;
(e) a stderr-stream file → `not_classified`, and the body is printed;
(f) a missing file → EXIT_FAIL and a stderr message;
(g) a garbage header → `header: invalid`, and the body is still printed;
(h) read-only: the directory listing and every file's mtime and content under the state dir are unchanged after the call, and nothing is created when the `usage-pause/` dir is absent;
(i) an ANSI escape (`\x1b[31m`) and non-ASCII in the body do not appear in stdout.
If `tests/framework/test_usage_pause_static.py` has static invariants (for example a subcommand inventory, no-network or no-write lists), extend them so `show-last-raw` is covered.

Run `scripts/oversight/.venv/bin/python -m pytest tests/automation/test_usage_pause_*.py tests/automation/test_hos_usage_poll.py tests/framework/test_usage_pause_static.py -q` and make it pass. Run `black` on the files you touched if the repo uses it (check `pyproject.toml`).

Do NOT change behaviour of any existing subcommand, `bin/hos-cron`, `bin/hos-usage-poll`, the reading format, or the parser. Item 3 of the issue (escalation of a sustained pause) is out of scope.

End your reply with the AGENTS.md self-flag block (RISK / CONFIDENCE / BLAST RADIUS), the commit SHA, and the test result line.
```

## Refinement History

v1 (prompt above): first coder pass.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by: [initials or role]
     - Date reviewed:
     - Findings: [what was caught, what was confirmed correct]
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->
