# Prompt Artifact — github.py (#2171 slice 2, behavior 2)

| Field | Value |
|---|---|
| **Generated file** | `scripts/automation/lib/github.py` (+ `bootstrap/get_app_token.sh`, `tests/automation/test_github.py`, `tests/automation/test_get_app_token_identity.py`) |
| **Description** | Re-mint the GitHub App token once and retry a `gh api` call that fails with HTTP 401, then fail loud |
| **Date** | 2026-10-29 |
| **Model** | claude-opus-5-5[1m] |
| **Risk level** | HIGH |
| **Human review status** | ⬜ Pending |

---

## Prompt

The spec is GitHub issue #2171, required behavior 2 only:

```
2. Retry once on 401 in the shared read path. scripts/automation/lib/github.py
   re-mints once and retries a call that fails with 401, then fails loud.
Acceptance: github.py retries once on 401 with a fresh token, with a test.
```

Slice 1 (behaviors 1 and 3) merged as PR #2207. Behavior 4 (agent-session
refresh) and the other deferred items are out of scope.

## Constraints Specified

The worker gave the `coder` these design decisions:

- **Role source:** `bootstrap/get_app_token.sh` also exports
  `HOS_TOKEN_APP_ROLE='<role>'`. It is not a secret.
- **Re-mint:** `_remint_token()` runs `bootstrap/get_app_token.sh --app <role>`
  as an argv list, with no shell and a 90 s timeout. It parses only lines of the
  form `export GH_TOKEN|HOS_BOT_LOGIN='…'` and never evals them.
- **Identity pin:** the new `HOS_BOT_LOGIN` must equal the current one. On
  success the function sets `GH_TOKEN` in this process's env only.
- **Token secrecy:** the token value is never logged and never appears in an
  exception message.
- **401 handling:** the first 401 in a `_run_gh` call triggers one re-mint and
  one re-send. That re-send sits outside the `retries` budget, so it also
  happens for `retries=0` writes: a 401 means GitHub rejected the request.
  When the re-mint fails, or the re-sent request also returns 401, the call
  raises `GitHubError(status_code=401)`. A 401 is never backed off and never
  returned as `None` or data.
- **Tests:** they must never run the real mint script.

## Refinement History

1. `d3c4a2cfb`: the initial implementation and tests.

## Human Review Notes

Protected surface (`bootstrap/get_app_token.sh`): this needs CODEOWNERS human
approval.

## Reproducibility Check

Covered by `TestRunGh401` in `tests/automation/test_github.py`.
