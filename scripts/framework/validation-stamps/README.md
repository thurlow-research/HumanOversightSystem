# Validation stamps

This directory holds the framework-validation stamps that `check_validation_current.sh`
reads in CI. Stamps are content-hash-based (#552): the filename encodes a SHA-256 hash
of all `.claude/agents/*.md` file contents, so the same agent files produce the same
stamp name regardless of git history. Stamps survive rebase without conflicts.

## Filename scheme

```
phase1-<HASH>.stamp      # written by check_agents_static.sh (the CI check target)
phase2-<HASH>.stamp      # written by validate_agents.sh (informational)
all-phases-<HASH>.stamp  # written by run_framework_validation.sh (informational)
```

`HASH` is computed as:
```bash
find .claude/agents -name "*.md" | sort | xargs sha256sum | sha256sum | cut -d' ' -f1
```

CI (`check_validation_current.sh`) checks that `phase1-<HASH>.stamp` exists and is
committed for the current agent content. If the stamp is missing, re-run validation:
```bash
bash scripts/framework/run_framework_validation.sh
git add scripts/framework/validation-stamps/
git commit
```

## Stamp fields

```
validated_at: <ISO-8601 UTC>     # when the gate was run/authorized
hash: <sha256>                   # redundant with filename; aids manual inspection
phase: <phase-id>                # phase this stamp covers (e.g. 1-static)
phases: <space-separated>        # for all-phases stamps: all phases run
skipped: <space-separated>       # phases skipped (requires human approval)
result: pass | human-authorized-override
```

## Override fields

These are present **ONLY** on a human-authorized override (a clean pass has none):

```
override: HOS_ALLOW_UNVALIDATED
override_authorized_by: <name>
override_reason: <text + issue refs>
override_expires: <ISO-8601 UTC>  # CI FAILS after this instant — overrides are never permanent
```

### `override_expires` semantics (fail-closed)

A human-authorized validation override is **time-boxed** and can never be permanent.
`check_validation_current.sh` enforces this:

- **Absent** → no override; the expiry check is skipped.
- **Present and in the future** → override is active; CI prints the days remaining.
- **Present and in the past** → CI **FAILS**. Re-run validation and commit a fresh stamp,
  or a human must re-authorize with a new `override_expires`.
- **Present but malformed/unparseable** → treated as **EXPIRED** and CI **FAILS**
  (fail-closed: any ambiguity forces resolution).

The expiry must be an ISO-8601 UTC instant of the exact form `YYYY-MM-DDTHH:MM:SSZ`
(e.g. `2026-06-22T00:00:00Z`).
