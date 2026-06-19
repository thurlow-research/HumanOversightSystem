# /hos-triage

Triage a GitHub issue using the HOS autonomous worker protocol.

## What this does

Applies the verify-first triage flow (Faberix R2 shape):
1. Read the issue title, body, and labels
2. Classify: bug / feature / communication / security-report / spec-gap / duplicate / invalid
3. Check HOS claim criteria (is this actionable by the worker autonomously?)
4. Propose a disposition: AUTOWORK / SUPERVISED_HUMAN / NEEDS_HUMAN / BLOCKED
5. Either begin work (if AUTOWORK) or explain why it needs human input

## Usage

```
/hos-triage #<issue-number>
```

Example: "Run /hos-triage on issue #372."

## Classification rules

| Class | Autonomous? | Action |
|---|---|---|
| `bug` + LOW/MEDIUM tier | Yes (AUTOWORK) | Fix per HOS pipeline |
| `bug` + HIGH/CRITICAL tier | Supervised (SUPERVISED_HUMAN) | Propose fix, human approves |
| `feature` | No (NEEDS_HUMAN) | Queue for human review |
| `security-report` | No (NEEDS_HUMAN) | Embargo + alert human immediately |
| `spec-gap` | Supervised | Route to pm-agent |
| `communication` | Yes (AUTOWORK) | Respond per context |
| `duplicate` | Yes | Close with reference |
| `invalid` | Yes | Close with explanation |

## What the worker should do

When invoked, the worker should:

1. Read the issue: `gh issue view <number> --repo thurlow-research/HumanOversightSystem`
2. Apply `scripts/automation/lib/triage.py` classification logic
3. Check: does the issue have `needs-ai` label? Is it assigned to `hos-worker-hos[bot]`?
4. Check: is there an open PR already covering this issue? (avoid duplicate work)
5. Report the classification and proposed disposition
6. If AUTOWORK: confirm with human (via /hos-build-step or direct action) then proceed
7. If SUPERVISED_HUMAN or NEEDS_HUMAN: explain what human input is required and why
8. Never proceed on security-report issues without human authorization

## Safety rules

- Never auto-close a security-report
- Never start work on a feature without human authorization
- Never claim an issue that is assigned to another agent
- Always check `correlation.py` / the cid to avoid duplicate work
