# Prompt Artifact — get_app_token.sh (`--app human` case)

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/get_app_token.sh` |
| **Description** | Add a `human` role case to the App-token minting script, mirroring the existing `worker`/`overseer` cases |
| **Date** | 2026-07-29 |
| **Model** | claude-sonnet-4-6 |
| **Risk level** | HIGH (authentication/credential-minting logic) |
| **Human review status** | ⬜ Pending |

---

## Prompt

```
bootstrap/get_app_token.sh mints a GitHub App installation token for HOS bot
identities. Its --app flag only accepts worker or overseer, but apps.env has
carried a fully-provisioned third identity (HOS_HUMAN_APP_ID / HOS_HUMAN_PEM /
HOS_HUMAN_BOT_LOGIN, App slug scottthurlow-claude[bot]) since #629-era setup.
Acting as the human's proxy in this repo, I have no way to authenticate gh
against a public read/write need without either hand-rolling the JWT/curl
sequence (explicitly disallowed by prior session guidance) or borrowing
worker/overseer credentials (which would misattribute actor identity in any
resulting commit/PR — see AGENT-IDENTITY.md).

Add a `human` case to the case "$APP_ROLE" in ... esac block, mirroring the
worker/overseer cases exactly: APP_ID=$HOS_HUMAN_APP_ID,
PEM_PATH=$HOS_HUMAN_PEM, DECLARED_BOT_LOGIN=${HOS_HUMAN_BOT_LOGIN:-}. Update
the --app usage strings/comments and error messages to list human alongside
worker/overseer. Do not touch anything past the case block — the rest of the
script (JWT generation, API identity verification, installation-token fetch)
is already role-agnostic and needs no changes.

Constraints: match the existing case arms byte-for-byte in structure; do not
add human-specific branching anywhere else in the file; do not change the
identity-verification logic (#631/#703) which already generalizes over
APP_ROLE.
```

## Constraints Specified

- **Mirror existing structure exactly** — new case arm has the same three assignments as `worker`/`overseer`, no new logic paths.
- **No changes past the case block** — JWT generation, `/app` identity verification, and installation-token fetch are already generic over `$APP_ID`/`$PEM_PATH`/`$DECLARED_BOT_LOGIN`.
- **Update all three touchpoints that hardcode the two-role assumption**: the usage comment block, the arg-parse fallback message, and the case's default-error arm.

## Refinement History

First attempt — mechanical mirror of the `worker`/`overseer` case arms; verified end-to-end against the live `scottthurlow-claude` App installation (token mint succeeded, `gh auth status` confirmed identity `scottthurlow-claude[bot]`) before submitting.

## Human Review Notes

<!-- After human review, record findings here:
     - Reviewed by:
     - Date reviewed:
     - Findings:
     - Status: APPROVED / APPROVED WITH CHANGES / REJECTED
-->

---

## Reproducibility Check

To verify this prompt still produces equivalent output in a new session:
1. Open a fresh Claude Code session in the Human repo
2. Paste the prompt above verbatim
3. Compare the resulting diff against `bootstrap/get_app_token.sh`'s `human)` case arm and the three updated usage/error strings
4. Note any drift in a new version artifact (`get_app_token.v2.md`)
