# Finding: An Autonomous Loop That Reads Governance Config From a Local Checkout Has a Currency Gap

**Role:** oversight-mechanism — reliability of governance enforcement in autonomous systems

**First observed:** 2026-06-16, issue #300 filed during #254 unattended worker Phase C implementation

---

## The Finding

The HOS unattended worker reads its governance configuration (`PROJECT/hos-coordination.yaml`) from a **local git checkout** on the machine running the cron. This config determines critical security properties: what the loop may do, how many tokens it may spend, and which requesters it obeys.

If that checkout is stale — because no one ran `git pull` between a governance config change merging and the next cron fire — **the loop runs under outdated governance permissions**. A tightened budget threshold, a removed user from the requester allowlist, or a newly-set `enabled: false` will not take effect until the checkout is updated. In the worst case, a governance change that was carefully human-approved and merged has zero operational effect until a manual pull.

This is a **currency gap**: the governance config is authoritative on GitHub (committed, CODEOWNERS-gated, auditable) but operationally stale on the machine. The gap is exactly as wide as the time between the last pull and the next configuration change. For a 30-minute cron, that gap is at most 30 minutes for cadence changes — but for governance changes, it depends entirely on operator discipline.

The immediate mitigation is a `git pull --ff-only` as the first gate in the orchestrator (step 0, #300). This bounds the currency gap to at most one probe interval. But this mitigation has its own failure mode: if the local branch has uncommitted changes or has diverged, `git pull --ff-only` fails and the orchestrator continues on the stale checkout (the `|| warn && continue` behavior), because stopping the loop entirely on a failed pull is more disruptive than a single stale cycle.

## Why This Matters

Governance-by-committed-file is a pattern HOS uses deliberately: a config file that is CODEOWNERS-gated and must be human-approved to change is both auditable and tamper-resistant. But the pattern has an implicit assumption — that the running system reads the config *from the authoritative source* (GitHub), not from a local copy that may drift. When the reading is from a local checkout, the governance guarantee becomes "the config is correct *once pulled*," which is weaker than the implied "the config is enforced immediately."

For passive systems (CI, code review), the local checkout is refreshed on every job run, so the gap is negligible. For a standing cron-based autonomous loop, the gap is structural and requires explicit attention. The principle generalizes: **any autonomous system that reads governance config from local state rather than an authoritative remote source has a currency gap proportional to its sync frequency.** The governance model must account for this gap explicitly.

The correct long-run fix may be to read governance config via the GitHub API (always authoritative) rather than from the local file, accepting the API call cost. The pre-pull mitigation is a pragmatic intermediate that bounds the gap without requiring an architectural change.

## Evidence

- Issue #300 (this session) — filed as a blocker on B11 (`hos_orchestrator.sh`), documenting the gap and three resolution options.
- `scripts/automation/hos_orchestrator.sh` step 0 (this session) — `git pull --ff-only` added as the first gate, before activation check, with a non-fatal failure path that logs a warning and continues.
- `scripts/automation/lib/config_resolver.py` — the 4-layer resolver reads layer 2a from a local file (`PROJECT/hos-coordination.yaml`), not from the GitHub API.

## Implications for Research

1. **Governance-by-committed-file requires a sync model.** Deploying this pattern for standing autonomous processes requires being explicit about the sync frequency and the failure mode when sync fails. "Committed and human-approved" describes the authorization; "currently running under" requires a separate currency guarantee.
2. **The gap is observable and measurable.** The time between a governance config change merging and the autonomous loop picking it up is a concrete metric — "governance propagation latency." It should be bounded and monitored for any standing autonomous system.
3. **The fail-open vs. fail-closed tension.** When the pre-run pull fails, continuing on stale config (fail-open) is less disruptive but allows the governance gap to widen; stopping entirely (fail-closed) preserves governance currency but could halt legitimate work. This tension is unresolved and the right answer likely depends on how often governance changes happen vs. how often the pull legitimately fails.

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — the broader principle that a rule that is correct on paper but cannot be checked at runtime is operationally weaker than it appears.
- `a-guard-that-doesnt-halt-is-not-a-guard.md` — the related failure mode where a gate that can be bypassed (here, by stale config) doesn't provide the guarantee it claims.
- `stamp-based-ci-enforcement.md` — the HOS pattern of enforcing governance via committed artifacts; this finding surfaces the currency limit of that pattern.
