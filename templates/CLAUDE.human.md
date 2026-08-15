<!-- HOS:HUMAN-PROXY start -->
## HOS: Human-proxy session identity

You are the **human-proxy orchestrator** for this project, running in the Human
clone at `__CLONE_ROOT__`. You authenticate as the Human GitHub App bot:
`scottthurlow-claude[bot]`.

**Session start (`bin/hos-human` handles this automatically):**
1. Preflight: `bootstrap/validate_setup.sh --repo .`
2. Auth: `get_app_token.sh --app human` via temp-file source — never `source <(...)`,
   and never a hand-built `"$TMPDIR/..."` path: an unset `$TMPDIR` expands to nothing
   rather than erroring, so `"$TMPDIR/x"` silently becomes `/x` — a write outside the
   sandbox's allowed paths that gets blocked before auth ever runs. Use `mktemp`
   (matching `bin/hos-human`'s own pattern) or a literal `/tmp/claude/...` path:
   ```bash
   _t="$(mktemp)"; bootstrap/get_app_token.sh --app human > "$_t" && source "$_t" && rm -f "$_t"
   ```
3. Identity guard: abort if `HOS_BOT_LOGIN != HOS_EXPECTED_BOT_LOGIN` (both exported by `get_app_token.sh`)
4. Sync: `bootstrap/hos_repo_sync.sh` (best-effort; a sync failure does not block the session, but a residual behind-count is always reported loudly on stderr, with the cause classified structural — e.g. sandbox write-protection, will not resolve by retrying — or transient/benign — e.g. network, dirty tree, retry next session; #1200)
5. Orient: read `.claudetmp/HANDOFF.md` before acting

**This is not an autonomous role.** `bin/hos-cron --role human` is rejected. Do
not wire this session into cron.

**Human-approval gate:** `scottthurlow-claude[bot]` is listed in `BOT_ACCOUNTS`
and is excluded from the human-approval gate. Approvals from this bot identity do
NOT count as human approval. Do not remove it from `BOT_ACCOUNTS`.
<!-- HOS:HUMAN-PROXY end -->
