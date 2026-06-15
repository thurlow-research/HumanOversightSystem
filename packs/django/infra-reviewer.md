## Django deployment infrastructure depth

This region adds Django-stack deploy/config checks to the generic infra checks in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

The canonical deployment topology this pack assumes: a **gunicorn** app container behind a **reverse proxy** (Caddy, nginx, or equivalent), a **Postgres** database container on an internal-only network, and a **named volume** for database persistence. Specifics (domain names, proxy tool, host provider) live in PROJECT.

---

### Docker Compose service topology

When the project uses Docker Compose, verify the following:

**Web (gunicorn / uwsgi) service:**
- The `web` service must **not** publish a port directly to the host interface. All ingress arrives through the reverse proxy. A `ports:` entry on `web` that binds to `0.0.0.0` is a **blocking** finding — it exposes the app server unauthenticated.
- `restart: unless-stopped` (or `restart: always`) must be set on `web`, `db`, and the proxy service. An absent `restart:` policy means a crashed service does not recover after a transient failure.
- The gunicorn worker count, `--timeout`, and `--bind` socket are typically set in a `CMD` or `entrypoint`. Verify `--bind 0.0.0.0:8000` (or a Unix socket) is used — never a public IP:port directly. Flag `--bind 0.0.0.0:80` as **blocking**.

**Database (Postgres) service:**
- The `db` service must **not** have a `ports:` entry that publishes 5432 to the host or any external interface. The only acceptable forms are: `ports:` absent entirely, or `"127.0.0.1:5432:5432"` (loopback-only). Any `"0.0.0.0:5432:5432"` or bare `"5432:5432"` is a **blocking** exposure finding.
- Postgres data must use a **named volume** (e.g. `pgdata:` declared in the top-level `volumes:` section), not a host-path bind mount (e.g. `./data:/var/lib/postgresql/data`). A host-path mount breaks portability and can expose data to the host filesystem with predictable paths.
- The `POSTGRES_PASSWORD` (and any other Postgres credentials) must come from the `.env` file or a secrets mechanism — not hard-coded in the `environment:` block.

**Network topology:**
- The `web`/app service and `db` service must share an **internal** Docker network (no `external: true`). The DB must not be reachable from outside the host.
- The reverse proxy service must have access to both the app network and the external network (for ACME certificate challenges). The `db` service must have **no** external-network access.
- A service with `network_mode: host` exposes every port the container listens on; flag as **blocking** unless there is a documented justification and the design doc explicitly accepts it.

---

### Secrets and environment config

**Compose `environment:` blocks:**
- No literal secret values (passwords, tokens, keys) may appear in `environment:` blocks in `docker-compose.yml` (or `compose.yml`). All sensitive values must come from an `env_file:` directive or `${VAR}` references that are resolved from the runtime environment or a non-committed `.env` file.
- The `.env` file must be listed in `.gitignore`. A committed `.env` containing real secrets is a **blocking** finding.

**`.env.example` / `.env.template`:**
- Every environment variable the app requires must be present in the example file, with placeholder values only (never real secrets).
- `DEBUG` must default to `False` (or be absent and Django defaults to `False`). A `DEBUG=True` placeholder in the example file is a recommendation finding — it will be copied verbatim by anyone following the setup docs.
- `DATABASE_URL` must use the internal Docker service name as the host (e.g. `postgres://user:pass@db/myapp`), not `localhost` or `127.0.0.1`, which would fail inside the container network.
- `SECRET_KEY` placeholder must be present. Note it in findings if missing.
- `ALLOWED_HOSTS` placeholder must be present. A wildcard value (`*`) in the example is a recommendation finding.

**Django settings from environment:**
- All production Django settings (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` / `DATABASES`, any PII encryption keys, email credentials, third-party API keys) must be read from the environment — via `os.environ`, `django-environ`, `python-decouple`, or equivalent — not hard-coded or version-controlled.
- Check for a split-settings layout (`settings/base.py` + `settings/production.py`, or `settings_production.py`). The production settings file must explicitly override `DEBUG = False` and set `ALLOWED_HOSTS` from the environment.

---

### Reverse proxy and TLS

**TLS in production:**
- No `tls internal` (self-signed) or self-signed certificate configuration in the production proxy config. Flag as **blocking**.
- The proxy must redirect HTTP to HTTPS — a bare HTTP listener that does not redirect is a **blocking** finding.
- HSTS (`Strict-Transport-Security`) must be set in exactly one place — either in the proxy config or in Django's `SECURE_HSTS_SECONDS` — not both. Two layers fighting produce inconsistent headers and can cause hard-to-debug client behavior; flag duplicate HSTS as a recommendation.
- TLS certificate auto-renewal (e.g. ACME via Let's Encrypt) must be configured; a manual certificate with no renewal mechanism is a recommendation finding.

**Static and media files:**
- Django's `collectstatic` output must be served by the reverse proxy or via WhiteNoise middleware — never through gunicorn directly in production. Verify one of: the proxy serves the `STATIC_ROOT` path, or `whitenoise.middleware.WhiteNoiseMiddleware` is in `MIDDLEWARE` and `STATICFILES_STORAGE` is a WhiteNoise storage backend.
- `MEDIA_ROOT` for user-uploaded files must be on a persistent volume, not the container filesystem. A container restart must not delete uploads.
- If the proxy directly serves `STATIC_ROOT` or `MEDIA_ROOT`, confirm the path in the proxy config matches the volume mount or `STATIC_ROOT` setting exactly.

**Security headers via proxy:**
- When the proxy sets security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Content-Security-Policy`), confirm Django is not also setting conflicting values for the same headers. Duplicated headers with different values are a recommendation finding.

---

### Database migrations on deploy

- The deployment procedure (Dockerfile `CMD`, `entrypoint.sh`, or Compose `command`) must run `manage.py migrate` **before** the gunicorn process starts accepting requests.
- A recommended pattern: a `command: sh -c "python manage.py migrate && gunicorn …"` on the `web` service, or a dedicated migration init-container / one-shot Compose service that completes before `web` starts.
- An app that starts without running migrations may serve requests against an out-of-date schema — flag the absence of a migration step as a **blocking** finding.
- Verify there is no `migrate --run-syncdb` in production (syncdb bypasses the migration framework and can silently create unmanaged tables).

---

### Healthchecks

- The `web` (gunicorn) service should have a Docker `healthcheck:` that hits the app's health endpoint (e.g. `curl -f http://localhost:8000/health/` or `wget -qO- http://localhost:8000/health/`). Absence of a healthcheck means Docker cannot distinguish a running-but-broken container from a healthy one; flag as a recommendation.
- The `db` service should have a `healthcheck:` using `pg_isready`. Without it, the app container may start and attempt DB connections before Postgres is ready, causing startup race failures.
- The `depends_on:` directive alone does not wait for the DB to be *ready* — it only waits for the container to start. A healthcheck condition (`condition: service_healthy`) on the `db` dependency closes this gap.

---

### Backups (Django/Postgres specifics)

- A `pg_dump`-based backup must exist — either a cron job, a management command, or a sidecar container. Verify it targets the `db` service by its Docker network hostname (e.g. `pg_dump -h db …`), not `localhost`.
- Backup output must be written to a volume or path **outside the database container** — inside-container backup files are lost on container recreation.
- Backup files should be compressed (e.g. `.sql.gz`) and rotated — flag an unbounded accumulation of unrotated backups as a recommendation.
- A restore procedure must be documented (script, README section, or runbook comment). An undocumented backup is not recoverable under pressure; flag its absence as a recommendation.
- If media uploads are stored on a volume, the backup strategy must include that volume, not only the database.

---

### Portability check (Django-specific)

For a Django/Postgres Compose stack, portability means: given a new host with Docker and the project repo, an operator should be able to restore the app by:
1. Copying the `.env` file.
2. Restoring the `pg_dump` into a fresh `db` container.
3. Pointing the DNS CNAME to the new host.

Flag any step that requires manual state not captured by the above — for example: hardcoded `STATIC_ROOT` paths that assume a specific host directory, media files not on a named volume, or TLS certificates not auto-provisioned (requiring manual cert copy).
