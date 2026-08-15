# `tests/framework/fixtures/sandbox/` — provenance

## `pre-existing-live-human.json`

**This is a synthetic reconstruction. It is NOT a capture of any real
machine's `.claude/settings.local.json`.**

`gen_sandbox_config.py` (#1221) runs inside a sandbox whose own boundary
prevents reading another clone's live settings file, and there is no operator
present in an autonomous cron cycle to assist a capture. Separately, committing
a capture of a real machine's file is exactly what
`scripts/framework/strip_internal_paths.sh` /
`scripts/framework/installer-internal-paths.txt` exist to prevent. See
`docs/v0.6.0/TECHNICAL-DESIGN-1221-clone-sandbox-config-generation.md` §0.2 for
the full reasoning.

### How it was derived

1. Start from `contract/sandbox-policy.template.json` **at its
   pre-reconciliation state** — the content committed before PR #1221's §8
   template edit (three `bin/**` deny spellings, three values-sidecar deny
   spellings, two additional force-push deny spellings).
2. Substitute the seven placeholders with the fixture values below —
   deliberately non-production, invented values; no real operator path
   appears anywhere in this file.
3. Add the deltas that encode the pre-reconciliation *live* state
   (§5 of the technical design):
   - `permissions.allow` gains `"Bash(claude *)"` — the live-only allow FR-13
     declines to carry over.
   - `permissions.deny` gains `"Bash(git push* -f*)"` and
     `"Bash(git push*--force*)"` — the two live-only force-push spellings.

| Placeholder | Fixture value |
|---|---|
| `ROLE` | `human` |
| `HOS_ROOT` | `/srv/hos` |
| `PROJECT_ROOT` | `/srv/hos/Human` |
| `CONFIG_DIR` | `/srv/hos/.config/hos` |
| `HOME` | `/home/hosuser` |
| `HANDOFF_DIR` | `/srv/hos/handoff/human` |
| `CLAUDE_PROJECT_STATE` | `/home/hosuser/.claude/projects/-srv-hos-Human` |

This fully exercises AC4's property — "generated output is a semantic
superset of the pre-existing live file" — as a real, reviewable computation
over a committed artifact. It simply does not literally reproduce the real
Human clone's edit history.

### Where the real evidence lives

The literal AC1b/AC4 evidence against the *real* Human clone is a **manual
transcript pasted into PR #1221's body** by the operator (captured at the
first `--force` run against the live clone), not a test. Do not treat this
fixture as that evidence.
