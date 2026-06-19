# /hos-review-pr

Run the HOS outer-loop panel review for an open PR.

## What this does

Dispatches the cross-vendor panel for a PR and makes a merge decision:
1. Read the PR's `panel-context.md` (structural signals only — no internal findings)
2. Run `./scripts/run_panel.sh <PR_NUMBER>`
3. Read the panel findings and the sign-off register
4. Apply the merge-authority matrix to produce AUTO_MERGE / HUMAN_REQUIRED / PROPOSE_ONLY
5. Act on the decision (merge, escalate, or propose)

## Usage

```
/hos-review-pr #<pr-number>
```

Example: "Run /hos-review-pr on PR #395."

## Merge authority matrix (OVERSEER_CEILING = LOW)

| Tier | Security surface | Protected surface | Panel verdict | Decision |
|---|---|---|---|---|
| LOW | No | No | PASS | AUTO_MERGE |
| LOW | No | No | CONDITIONAL | PROPOSE_ONLY |
| MEDIUM+ | Any | Any | Any | HUMAN_REQUIRED |
| Any | Yes | Any | Any | HUMAN_REQUIRED |
| Any | Any | Yes | Any | HUMAN_REQUIRED |

## What the overseer should do

When invoked, the overseer should:

1. **Identity check**: verify `$HOS_BOT_LOGIN` equals `hos-overseer-hos[bot]` (GitHub App tokens cannot call `GET /user` — use the env var set by `bootstrap/get_app_token.sh --app overseer`)
2. Read the PR: `gh pr view <number>`
3. Check for `panel-context.md`: `.claudetmp/oversight/step<N>-panel-context.md`
4. If panel hasn't run: run `./scripts/run_panel.sh <number>`
5. Wait for panel to complete; read the verdict from the panel output
6. Read the sign-off register: `.claudetmp/signoffs/`
7. Run `require-tier-ceiling` CI check logic to confirm tier ≤ OVERSEER_CEILING
8. Apply the merge-authority matrix
9. If AUTO_MERGE: `gh pr merge <number> --squash --auto`
10. If HUMAN_REQUIRED: post escalation comment, label `needs-human`, assign ScottThurlow
11. If PROPOSE_ONLY: post PROCEED recommendation but do not merge

## Safety constraints

- **Never** merge a PR you opened (no self-approval)
- **Never** merge above OVERSEER_CEILING (check `scripts/framework/machine-accounts.env`)
- **Never** merge when `hos-halt` label is present on any open issue
- **Never** operate outside the repo established at session start
- Batch merge: serialize one at a time, re-check approval before each (dismiss_stale_reviews)
