# Human Approval Model Design — HOS Merge Authority

**Source:** Design session with ScottThurlow, 2026-06-19 (#599)  
**Issues:** #599, #600, #601  
**Status:** Implemented in v0.4.0

---

## Finding 1 — Labels route, comments authorize

Labels (`needs-ai`, `needs-human`) are routing signals. Anyone with triage permissions can apply them, so they cannot serve as authorization records. The authorization record is always a structured comment from a verified human identity. The overseer checks WHO made the comment (and when), not just that the label state changed.

**Implication:** An issue moving from `needs-human` to `needs-ai` is not self-authorizing. The overseer must verify a qualifying human comment predates the label transition.

---

## Finding 2 — Issue approval and PR approval are distinct gates

Approving an issue = authorizing the work to begin.  
Approving a PR = authorizing the merge.

These are separate human decisions, even for the same change. Issue approval does not imply PR approval. A human who approves a bug-fix issue has not pre-authorized the specific implementation the worker produced.

---

## Finding 3 — 3-gate model for changes above OVERSEER_CEILING

Features and redesigns (not bugs) that produce PRs above `OVERSEER_CEILING` require:

| Gate | What | Who |
|------|------|-----|
| 1 — Problem | `needs-human` comment on the issue | Human reviewer |
| 2 — Design | pm-agent + architect + technical-design artifacts; `needs-human` again | Human reviewer |
| 3 — Implementation | PR review approval | Human reviewer |

**Bugs skip Gates 1 and 2** — faster turnaround is prioritized. Gate 3 still applies if the change is above the ceiling.

**Rationale:** Features introduce new behavior that wasn't specified; bugs correct behavior to match existing spec. The spec pre-authorizes bug fixes implicitly.

---

## Finding 4 — OVERSEER_CEILING is the configurable authority dial

The tier threshold for human approval is not hardcoded. `OVERSEER_CEILING` in `scripts/framework/machine-accounts.env` determines what the overseer can auto-approve:

- Everything **at or below** the ceiling: overseer approves + merges autonomously
- Everything **above** the ceiling: human gate required (CRITICAL tier or explicit security/protected-surface flags)

Raising the ceiling increases autonomous throughput. Lowering it increases human oversight per-change. This is the primary governance tuning knob. v0.4.0 raised it from `LOW` to `HIGH` (#600).

---

## Finding 5 — Human maintainer list derives from CODEOWNERS

Human maintainer = any CODEOWNERS entry **not** in `BOT_ACCOUNTS`.  
Overridable via `HUMAN_REVIEWER` in `machine-accounts.env`.

Avoids hardcoding individual logins in multiple places; stays current as the team changes. The CODEOWNERS gate in `codeowners.py` re-reads on every call (no caching) so CODEOWNERS changes take effect immediately without a deploy.

---

## Finding 6 — High-security areas require pre-authorization

The following change classes always warrant `needs-human` on the issue before work begins (Gate 1 is mandatory regardless of tier):

- Auth mechanisms and identity guards
- Human gate logic (`require_human_approval.py`, `merge_authority.py`)
- Audit trail and oversight log format
- Branch protection configuration
- The oversight contract (`contract/OVERSIGHT-CONTRACT.md`)
- Autonomous agent behavioral specs (`worker.md`, `overseer.md`)

**Canonical example:** Changing how the bot authenticates to GitHub (the #542 App migration) required human authorization before any code was written.

**Rationale:** These are the components that the safety argument rests on. A compromised identity guard or a tampered audit trail could allow unauthorized merges to pass undetected. Pre-authorization ensures the human has read and agreed to the structural change, not just reviewed the implementation.

---

## Tradeoffs considered

| Option | Rejected because |
|--------|-----------------|
| Hardcode maintainer logins in scripts | Drift: team changes break gates silently |
| Trust label state as authorization | Labels are too easily set; not a signed artifact |
| Single approval gate for all changes | Too slow for bugs; insufficient for features |
| Fixed OVERSEER_CEILING (no config) | Governance needs to be tunable per-project and over time |

---

## Related findings

- `human-gate-enforcement-limits.md` — what the server-side gate can and cannot enforce
- `self-classification-cannot-gate-the-human-boundary.md` — why bots cannot self-authorize
- `actor-identity-vs-determination-honesty.md` — identity vs. determination in oversight
