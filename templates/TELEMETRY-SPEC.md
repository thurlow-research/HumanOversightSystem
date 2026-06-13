# Telemetry Specification

*Produced by `ops-designer`. Validated by `architect`. Enforced by `ops-reviewer`.*
*Completed: [date]. Spec is cleared for ops-reviewer to enforce.*

---

## Logging conventions

**Format:** [structured JSON / key-value pairs / framework default]

**Required fields on every log entry:**
- `timestamp` — ISO 8601
- `level` — one of: DEBUG, INFO, WARNING, ERROR, CRITICAL
- `operation` — the action being performed (e.g. `booking.create`, `auth.totp_verify`)
- `user_id` — authenticated user identifier (omit for unauthenticated paths)
- `request_id` — trace/correlation identifier for request-scoped operations

**Log level definitions:**
- `ERROR` — operation failed; requires investigation
- `WARNING` — operation succeeded but with a degraded condition
- `INFO` — normal operation events worth recording
- `DEBUG` — diagnostic detail; off in production

**Silent failure policy:** All exception handlers must log at ERROR before returning or re-raising. Bare `except: pass` is a spec violation.

---

## Metric conventions

**Naming scheme:** `[service].[component].[operation].[unit]`
Examples: `bookings.create.duration_ms`, `auth.totp.failures_total`

**Required metric types per operation class:**

| Operation class | Required metrics |
|---|---|
| API endpoint | Request counter (by status code), latency histogram |
| Background job | Run counter, duration histogram, failure counter |
| Queue consumer | Messages processed counter, processing latency, dead-letter counter |
| External API call | Call counter (by outcome), latency histogram, timeout counter |
| Database operation | Query counter, latency histogram (on slow-query threshold) |

**Label conventions:**
- `status` — `success` / `failure` / `timeout`
- `endpoint` — route identifier (not full URL — avoid high cardinality)
- `job_type` — for background jobs

---

## Tracing requirements

**Boundaries requiring trace context propagation:**
- [List service-to-service call boundaries]
- [List async task dispatch points]
- [List external API call sites]

**Span naming convention:** `[service].[operation]` (e.g. `booking-service.create_booking`)

**Required span attributes:**
- `user.id` — on all authenticated spans
- `db.statement` — on database spans (parameterized, no PII values)

---

## Health check requirements

**Per dependency type:**

| Dependency type | Health check requirement |
|---|---|
| Relational database | Connection pool check; fail if no connections available |
| Cache (Redis/Memcached) | Ping check; degrade gracefully on failure (not hard fail) |
| Message queue | Queue reachability check; report depth if available |
| Third-party API | Lightweight status endpoint or cached last-known-good |
| Background job scheduler | Heartbeat check; alert if no heartbeat within 2× interval |

**Readiness vs. liveness:**
- Liveness: is the process running?
- Readiness: are all dependencies available? Do not mark ready until all required dependencies are reachable.

---

## Dashboard and alerting intent

*Intent is required; tooling implementation is out of scope for this spec.*

**Must be dashboarded:**
- [List key operational metrics that require a dashboard panel]

**Must alert:**

| Condition | Severity | Suggested threshold |
|---|---|---|
| Error rate > X% over 5min | Page | [set per component] |
| P95 latency > Xms | Warn | [set per component] |
| Background job failure | Page | Any failure in critical job |
| Dead-letter queue depth > 0 | Warn | Investigate within 1 business hour |
| Health check failing > 2min | Page | Dependency may be down |

---

## Runbook coverage requirements

A runbook entry (or a filed intent note) is required for:
- Any background job or scheduled task that can fail silently
- Any external integration that can become unavailable
- Any data migration that is not fully reversible
- Any operation that requires manual intervention to recover

**Runbook location:** `docs/ops/runbooks/[component].md`

---

## Component coverage

*Fill in one section per major system component.*

### [Component name]

**Operations:** [what it does]
**Required logging:** [what must be logged]
**Required metrics:** [what must be measured]
**Tracing required:** [yes/no — which boundaries]
**Health check:** [what check is required]
**Dashboard intent:** [what panels are needed]
**Runbook required:** [yes/no — for which failure modes]

---

## Out of scope

The following are explicitly not covered by this telemetry spec:

- Security audit logging (who accessed what data) — `security-reviewer`
- GDPR/data retention logging — `privacy-reviewer`
- Deployment configuration and infrastructure health — `infra-reviewer`
- Dashboard and alerting rule implementation — tracked separately as operational work
