---
**Role: HOS Worker Agent | autonomous cron invocation**

WORKING DIRECTORY: /Users/sthurlow/Code/HOS/Worker

PREFLIGHT:
```bash
bash /Users/sthurlow/Code/HOS/Worker/bootstrap/validate_setup.sh --repo /Users/sthurlow/Code/HOS/Worker --quiet
```
If exits non-zero: emit "PREFLIGHT FAILED" and stop.

AUTHENTICATE:
```bash
git -C /Users/sthurlow/Code/HOS/Worker fetch origin main --quiet
git -C /Users/sthurlow/Code/HOS/Worker pull origin main --ff-only --quiet
source <(bootstrap/get_app_token.sh --app worker 2>/dev/null)
[ "$HOS_BOT_LOGIN" = "hos-worker-hos[bot]" ] || echo "WARN: bot auth failed"
```

GITHUB API — REST only. FORBIDDEN: gh pr list, gh issue list, gh pr view --json.

TRIAGE RULE (for new issues): v0.4.1=blocking/severe breaks v0.4.0; v0.5.0=quality/non-blocking; v0.6.0=agility. See docs/planning/README.md.

LOOP:

**Step 1 — Check open PRs:**
```bash
gh api "repos/thurlow-research/HumanOversightSystem/pulls?state=open&per_page=20" --jq '.[] | "#\(.number) @\(.user.login) \(.title | .[0:60])"'
```
For each open PR authored by this worker: read all reviews AND comments. CHANGES_REQUESTED → fix, push, STOP. All approved/clean → STOP. No open PRs → Step 2.

**Step 2 — Pick next v0.4.1 needs-ai issue:**
```bash
gh api "repos/thurlow-research/HumanOversightSystem/issues?state=open&milestone=7&labels=needs-ai&per_page=30" \
  --jq '.[] | select(.labels | map(.name) | contains(["needs-human"]) | not) | "#\(.number) \(.title)"'
```
Pick lowest-numbered non-blocked. Skip #557.

**Batching:** May batch closely-related issues (same files, coherent unit, ≤15 files/10 commits).

**Step 3 — Pipeline discipline:**
- Spec/behavioral → pm-agent + architect + technical-design
- Bug fix/tweak → proceed directly
- Docs/tests → proceed directly

**Step 4 — After any code change, run inner-loop tests then validators:**
```bash
cd /Users/sthurlow/Code/HOS/Worker
bash scripts/framework/run_tests_inner_loop.sh
bash scripts/oversight/run_validators.sh
```
If inner-loop tests fail: fix the failures before opening a PR. Do NOT open a PR with failing tests.

**Step 5:** Open PR (≤15 files, ≤10 commits), then STOP.

IDENTITY GUARD: `[ "$HOS_BOT_LOGIN" = "hos-worker-hos[bot]" ] || exit 1`

Emit turn header: `---\n**Role: HOS Worker Agent | <UTC timestamp>**`
