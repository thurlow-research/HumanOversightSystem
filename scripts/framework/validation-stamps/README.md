# Validation stamps

This directory holds the framework-validation stamps that `check_validation_current.sh`
reads in CI. A stamp is a small key/value text file that records that the framework
validation gate (`run_framework_validation.sh`) was run, and proves — via its git
commit timestamp — that no tracked file changed after the last validation.

`all-phases.stamp` is the canonical stamp the PR pipeline checks. The CI check is
AI-model-free: it only compares git commit times and reads the fields below.

## Stamp fields

```
validated: <ISO-8601 UTC>        # when the gate was run/authorized
phases: <space-separated>        # phases run
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

- **Absent** → there is no override; the expiry check is skipped (backward-compatible
  with normal clean stamps).
- **Present and in the future** → override is active; CI prints the days remaining and
  still requires the stamp to be current versus changed files.
- **Present and in the past** → CI **FAILS**. The deferred findings must be resolved
  (re-run the gate until it converges clean and commit a fresh, non-override stamp) or
  a human must re-authorize a new time-boxed override with a new `override_expires`.
- **Present but malformed/unparseable** → treated as **EXPIRED** and CI **FAILS**
  (fail-closed: any ambiguity forces resolution).

The expiry must be an ISO-8601 UTC instant of the exact form `YYYY-MM-DDTHH:MM:SSZ`
(e.g. `2026-06-22T00:00:00Z`).
