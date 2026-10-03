# Usage fixtures (#1944)

Fixtures for the usage-pause poller (TD-1944 section 9). Byte-exact fixtures are
asserted by sha256 in the tests.

| File | Provenance |
|---|---|
| `d1-loopback-2026-10-02.txt` | D-1 loopback capture (faberix, 2026-10-02), TD 1.9.1 verbatim, 1091 bytes, sha256 `c8d52b0a...6196683` |
| `d1-envelope-derived.json` | Derived: `{"result": <D-1 text without its final LF>, "total_cost_usd": 0, "usage": {four token fields: 0}}`, `json.dumps(..., ensure_ascii=False, indent=2) + "\n"` |
| `capture2-envelope-2026-10-03.json` | Capture 2 (human, faberix, 2026-10-03, jq-filtered to `result`, `total_cost_usd`, `usage`), TD 1.9.2 verbatim, 1621 bytes, sha256 `c72987a8...b4de5` |
| `live-full-envelope-2026-10-03.json` | The first full, unfiltered envelope (20 top-level keys) from a real forced-command read over the loopback key, 2026-10-03, byte-exact, 2210 bytes, sha256 `68533dec...a0e5`. Session 6%, all models 4%, Fable 0%, cost 0, tokens 0. Contains the read's own `session_id` and `uuid`. |
| `capture2-plus-fields.json` | Capture 2 plus top-level `type`, `subtype`, `is_error`, `session_id`, `duration_ms`, `num_turns` and `usage.extra` |
| `empty-session-pr1450-test1.txt` | PR #1450 2026-08-17T07:48:32Z Test 1, TD 1.9.3 verbatim, 207 bytes, sha256 `f14701ef...39d14` |
| `empty-session-envelope-blank.json` | Synthetic (TD 1.9.4): `"result": ""`, cost 0, tokens 0 |
| `empty-session-envelope-legacy-text.json` | Synthetic (TD 1.9.4): `"result"` = the PR #1450 text |
| `ac1-real-shape-envelope.json` | Envelope whose `result` is D-1 lines 1-5 with session 4, all models 29, Fable 6 (AC-1); no breakdown |
| `envelope-session-only.json` | Capture 2 with the `Current week (all models)` line removed |
| `envelope-weekly-only.json` | Capture 2 with the `Current session` line removed |
| `envelope-no-model.json` | Capture 2 with the `Current week (Fable)` line removed |
| `envelope-two-models.json` | Capture 2 plus `Current week (Opus): 7% used · resets Oct 10, 12am (UTC)` after the Fable line |
| `envelope-not-json.txt` | Plain text, not JSON |
| `envelope-result-missing.json` | Capture 2 without `result` |
| `envelope-result-number.json` | Capture 2 with `"result": 5` |
| `envelope-array.json` | Capture 2 wrapped in a JSON array |
| `envelope-duplicate-result.json` | Capture 2 with a second top-level `"result"` key |
| `envelope-nan-cost.json` | Capture 2 with `"total_cost_usd": NaN` |
| `envelope-negative-cost.json` | Capture 2 with `"total_cost_usd": -1` |
| `envelope-tokens-partial.json` | Capture 2 without `usage.cache_read_input_tokens` |
| `envelope-decimal-percent.json` | Capture 2 with `Current session: 48.5%` |
| `envelope-over-100.json` | Capture 2 with `Current session: 150%` |
| `envelope-ansi-crlf.json` | Capture 2 `result` with an OSC title, a bold CSI around `Current session`, and CRLF line endings |
| `envelope-breakdown-garbled.json` | Capture 2 with the 24h subagent-heavy line and top line garbled |
| `envelope-top-bad-item.json` | Capture 2 with `architect six` in the 24h top list |
| `envelope-third-window.json` | Capture 2 plus a `Last 30d` window |
