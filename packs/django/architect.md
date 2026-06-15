## Django architecture depth

This region adds Django-stack architecture concerns to the stack-neutral CORE. Every item below applies to **any Django project** — do not duplicate CORE items here, and do not add project-specific deployment targets or domain models (those belong in PROJECT).

---

### App and project structure

Organise the codebase into one Django app per major domain area. Each app is a deployable, self-contained unit: it owns its models, migrations, views, forms, serializers, templates, and tests. Cross-app imports are allowed; circular dependencies are not — extract shared utilities to a `common` or `utils` app.

**When deciding app boundaries**, ask:
- Can this app's migrations be applied or rolled back independently?
- Does it have a coherent, single-sentence purpose?
- Would removing it leave all other apps intact?

Reject designs that place unrelated models in a single app for convenience, or that split a single coherent domain across multiple apps because the designer wanted to avoid a "large" app.

---

### Settings architecture

For any project that targets more than one environment (development, staging, production), require a settings package rather than a single flat `settings.py`:

```
project/
  settings/
    __init__.py
    base.py        # shared across all environments
    production.py  # imports base; overrides for prod
    local.py       # imports base; developer overrides (git-ignored)
```

`SECRET_KEY`, `DATABASE_URL`, and every application-level secret (encryption keys, API keys, VAPID keys, TOTP issuer secrets) must come from the environment — via `os.environ`, `django-environ`, or `python-decouple`. Hard-coded or version-controlled secrets are a blocking ADR concern. Reject any design that specifies a settings layout that does not enforce this.

`DEBUG` must resolve to `False` in production. Read it as a boolean from the environment: `DEBUG = env.bool("DEBUG", default=False)`. A string `"True"` that evaluates truthy is a settings architecture defect.

`ALLOWED_HOSTS` must be a restrictive, explicitly enumerated list — not `["*"]`.

---

### Model and schema strategy

When authoring or critiquing the data model, apply these decision rules:

**Field selection:**
- Optional string columns: `blank=True` with an empty-string default; never `null=True` on `CharField`/`TextField` (two representations of "no value" create ambiguous queries).
- Timestamps: `auto_now_add=True` for immutable creation timestamps; `default=timezone.now` (not `auto_now`) when the field must be settable in tests or migrations.
- `ForeignKey` and `OneToOneField` must always specify `on_delete` explicitly — `CASCADE` vs `SET_NULL` vs `PROTECT` is a correctness decision for the domain, not a default.

**DB-level constraints vs application-layer checks:**
Application-layer uniqueness checks (e.g. `ModelForm.clean()`, `validate_unique()`) are **not** sufficient for concurrent writes. Any uniqueness or exclusion invariant that must hold under concurrent requests must be enforced at the database level:
- Point uniqueness → `UniqueConstraint` in `model.Meta.constraints` (generates a DB unique index).
- Range non-overlap (time slots, date intervals, numeric ranges) → `ExclusionConstraint` with a GiST or SP-GiST index on the range column. PostgreSQL's `tstzrange` + a GiST exclusion constraint is the correct primitive for range-overlap safety; an application-layer check is a race condition.
- Invariant conditions → `CheckConstraint` in `model.Meta.constraints`.

Every constraint declared in `Meta.constraints` must appear in the migration — a constraint present in the model but absent from the migration is not enforced on existing databases. Flag this as a blocking ADR concern.

**Custom managers for scoped models:**
Any model that carries a tenant, organisation, site, or ownership FK must define a custom `Manager` subclass that overrides `get_queryset()` to apply the scope filter. The scoped manager must be the model's default manager (declared first). Reject designs that rely on inline `.filter(organization=…)` in every view — that is a missing-manager defect waiting to leak cross-tenant data.

Django Admin's `ModelAdmin.get_queryset(request)` must be overridden on every admin class that exposes scoped models; Django Admin bypasses custom managers.

---

### Migration strategy

Require a migration for every model change. Reject "we'll squash later" deferral.

For migrations that alter large tables (adding columns, adding indexes, dropping columns on tables with production data), assess whether the migration is safe to run without locking:
- Adding a nullable column → safe online in PostgreSQL.
- Adding a non-nullable column without a server-default → requires a lock; use the two-step pattern (add nullable → backfill → add NOT NULL constraint).
- Adding an index → use `CREATE INDEX CONCURRENTLY` via `atomic=False` in a `RunSQL` migration; the standard `AddIndex` operation takes an `ACCESS SHARE` lock but blocks writes during index build on older PG versions.
- Dropping a column still referenced by application code → deploy the code change first, then the migration.

`RunPython` operations must supply a reverse function (`RunPython.noop` when reversal is truly impossible). Document irreversible operations explicitly in the migration file.

---

### HTMX vs SPA vs DRF: the architectural decision

When the spec is ambiguous, apply this decision tree in the ADR:

1. **HTMX (server-rendered, Django templates + hyperscript/Alpine):** the correct default for Django projects where the team is comfortable with server-side rendering. Minimal JavaScript, CSRF handled naturally, no separate API surface to secure, Django Admin works out of the box. Choose this unless (2) or (3) applies.

2. **Django REST Framework (DRF) or django-ninja:** required when the project exposes a public API consumed by external clients (mobile apps, third-party integrations). If the *only* consumer is the project's own frontend, this is overengineering — prefer HTMX.

3. **SPA (React/Vue/etc. + DRF):** required only when the UX demands client-side state management that is unworkable in HTMX (e.g. complex multi-step wizard with heavy client-side validation, real-time collaborative editing). The cost is a separate build pipeline, a separate auth surface (JWT or session cookie CORS), and loss of Django's template/form tooling.

Record the choice in the ADR with an explicit justification. Do not mix paradigms (e.g. some views HTMX, some DRF) without an architectural reason — the result is two authentication surfaces and two CSRF models.

---

### Sync vs async and Celery

Django's synchronous request/response model is the correct default. Introduce async (Django ASGI views, `asyncio`, Channels) only when the design doc identifies a concrete requirement — real-time WebSocket events, long-polling — that cannot be served by synchronous views plus background tasks.

For deferred or scheduled work (email delivery, webhook delivery, report generation, scheduled jobs), the correct pattern is a task queue:
- **Celery + Redis (or RabbitMQ):** the standard Django choice. Requires a separate worker process. Appropriate for high-throughput or complex workflow graphs.
- **Django-Q2 or Huey:** lighter weight; suitable for moderate throughput without the operational overhead of a full Celery + broker stack.
- **`manage.py` command via cron:** acceptable for low-frequency scheduled jobs (nightly, hourly) that do not need fan-out or retry logic.

Reject designs that perform long-running work synchronously in views (network I/O, report generation, email sending) — this ties up a gunicorn worker for the duration of the task and degrades availability under load.

Signal handlers must not perform blocking I/O synchronously; defer to a task queue.

---

### Caching layers

When the design requires caching, require the ADR to specify:

1. **What is cached:** query results, rendered template fragments, or computed aggregates. Each has different invalidation properties.
2. **Cache backend:** `django.core.cache.backends.redis.RedisCache` (or `django-redis`) for multi-process deployments; the local-memory backend is process-local and incorrect for gunicorn workers.
3. **Invalidation strategy:** time-based TTL, signal-driven invalidation, or cache-key versioning. "Invalidate on write" via signals is correct for model-derived caches; TTL alone is incorrect for data with strong consistency requirements.
4. **Cache poisoning surface:** cached content that includes user-supplied data must not be shared across users. Require cache keys to include the user or org identifier when caching user-specific or tenant-specific content.

The `CACHES` setting must use the same backend in production and in tests (or tests must be run with `--keepdb` and cache clearing between test cases that assert on cached state).

---

### Encrypted PII and secret field strategy

When the design calls for encrypted-at-rest PII (names, emails, phone numbers, government IDs) or secrets (TOTP keys, recovery codes), require the ADR to resolve:

1. **Library:** `django-encrypted-model-fields` (symmetric, AES, simple) or `pgcrypto` extension (server-side encryption, avoids key material in app process). Document the tradeoffs in the ADR.
2. **Key source:** encryption key from the environment; never from source code or a migration.
3. **Key rotation path:** how keys are rotated without re-encrypting all rows synchronously. Acceptable patterns: field-level key versioning (store key ID alongside ciphertext), dual-read period (old key still readable during rotation).
4. **Admin exposure:** Django Admin list views that expose encrypted fields must not decrypt in bulk queryset evaluation; override `get_queryset` and decrypt only on the detail view. Avoid logging or caching decrypted values.

TOTP secrets specifically: the TOTP secret must be stored encrypted at rest. A design that stores TOTP secrets as plaintext bytes is a blocking security concern — escalate to security-reviewer.

---

### Deployment topology: gunicorn, Docker Compose, Caddy

When the design targets a Docker Compose deployment, require the ADR to specify:

**Service topology:**
- `web`: gunicorn serving the Django WSGI application. Require `--workers` set to `2 * CPU + 1` (the standard gunicorn formula) and `--timeout` appropriate for the slowest expected request. Do not use `--reload` in production.
- `db`: PostgreSQL with a named volume for persistence. The DB service must **not** be exposed on a host port — internal-only access via the Compose network.
- Reverse proxy (Caddy, nginx, or equivalent): TLS termination, static file serving, and HTTP→HTTPS redirect. Caddy is the correct default for automatic TLS with Let's Encrypt; nginx is appropriate when TLS certificates are managed externally.
- `worker` (if Celery is used): same image as `web`; entrypoint overridden to `celery -A project worker`.
- `beat` (if scheduled tasks): same image; entrypoint overridden to `celery -A project beat`.

**Static files:**
`STATIC_ROOT` must be set and `collectstatic` must run as part of the container build or entrypoint — not assumed to be present. The reverse proxy must serve `/static/` directly without passing through gunicorn.

**Environment variables:**
All secrets (`SECRET_KEY`, `DATABASE_URL`, encryption keys) must be injected via environment variables — not baked into the image or committed to `docker-compose.yml`. Use a `.env` file (git-ignored) for local development; use a secrets manager or CI/CD variable injection for production.

**Health checks:**
The `web` service should define a Docker health check (`HEALTHCHECK`) that calls `manage.py check --deploy` or a lightweight `/health/` endpoint. This allows Compose (and any orchestrator layered on top) to detect a misconfigured or failed app process.

---

### TOTP / 2FA architecture

When the design includes TOTP-based 2FA, require the ADR to resolve these architectural questions before technical-design proceeds:

1. **TOTP library:** `pyotp` (pure Python, widely audited) is the correct default. Record the choice in the ADR.
2. **Secret storage:** encrypted at rest (see encrypted field strategy above). This is non-negotiable.
3. **Enrollment flow:** the enrollment endpoint must require an authenticated session, must only be reachable when the user has *not* yet enrolled, and must be rate-limited independently of the password endpoint.
4. **Recovery codes:** generated as a set of one-time-use codes at enrollment. Each code must be stored as a hash (not plaintext). Consumption must be atomic — `select_for_update()` inside `transaction.atomic()` — so two concurrent requests cannot both redeem the same code.
5. **Time window tolerance:** ±1 step (±30 seconds) maximum. A wider window extends replay opportunity; flag any `valid_window > 1` as a high finding.
6. **2FA gate coverage:** TOTP must be verified on every view that the design doc specifies as 2FA-gated — not only at the initial login step. Name each gated view in the ADR.

---

### Django Admin extension strategy

When the design includes a staff/operator admin UI or any staff-facing administrative interface:

**Prefer extending Django Admin** over building a separate admin application, unless the design doc explicitly requires a consumer-grade UX for non-technical operators. Django Admin gives model CRUD, list/search/filter, inline editing, and audit history (via `django-simple-history` or equivalent) with minimal code.

**When extending Admin:**
- Subclass `ModelAdmin` for each model; do not rely on auto-generated admin for any model that carries access-control implications.
- Override `get_queryset(request)` on every `ModelAdmin` that exposes scoped or tenant-specific data — Django Admin bypasses custom managers.
- Override `has_add_permission`, `has_change_permission`, `has_delete_permission` for models where staff roles differ (read-only auditor vs operator vs superuser).
- Use `readonly_fields` on audit fields (`created_at`, `created_by`, etc.) — never allow staff to edit them.
- Register all admin classes in the app's `admin.py` (not in models or views); use `admin.site.register(Model, ModelAdmin)` or the `@admin.register(Model)` decorator.

**When not to use Django Admin:** public-facing portals used by non-staff end users (tenants, members, end users) should be separate views — Django Admin is a staff tool and its session/auth model is separate from the application's user auth.

---

### Web push architecture

When the design includes web push notifications (PWA service worker + VAPID):

1. **VAPID keys:** generated once per deployment environment; stored in the environment (not in source). Require the ADR to specify where keys are generated and rotated.
2. **Service worker scope:** the service worker must be served from the root path (`/service-worker.js`) or a path whose scope covers all pages that should receive push events. A service worker served from `/static/` has a `/static/` scope by default — it will not intercept push events for pages outside that path. Require an explicit `Service-Worker-Allowed: /` response header if the file is served from a sub-path.
3. **Subscription storage:** push subscription objects (endpoint + keys) are per-device, not per-user. The data model must store subscriptions with a FK to the user, allowing one user to have multiple active subscriptions (desktop, mobile, multiple browsers).
4. **Delivery reliability:** web push delivery is best-effort. For notifications that must not be silently dropped (e.g. time-sensitive alerts or confirmations), pair the push notification with a fallback email delivery. Record in the ADR whether the design requires "at most once" or "at least once" delivery semantics.

---

### Critiquing the technical design: Django-specific checklist

When `technical-design` produces a design document for a Django project, check every item in the CORE critique list **and** these Django-specific concerns:

- **Constraint enforcement level:** is every uniqueness or exclusion invariant enforced at the database layer (UniqueConstraint, ExclusionConstraint, CheckConstraint), not only at the application layer?
- **Scoped manager coverage:** does every tenant- or org-scoped model have a custom manager? Is the manager the default (first declared)?
- **Migration safety:** does the design call out any large-table alterations? If so, is the safe-migration pattern (two-step add or CONCURRENT index) specified?
- **Settings architecture:** does the design specify a settings package (not a flat file) with env-only secrets?
- **Sync vs async:** if the design defers work to background tasks, is a task queue specified? Are views synchronous unless a concrete async requirement is documented?
- **HTMX CSRF coverage:** for every HTMX state-changing action in the design, is a CSRF delivery mechanism specified?
- **Encrypted fields:** for every PII or secret field, is an encryption library and key management path specified?
- **Admin scoping:** for every ModelAdmin in the design, is `get_queryset` overridden?

"The ORM will handle it" is never an acceptable answer to a scoping or constraint question. Name the specific ORM mechanism and where it is enforced.
