## Django implementation depth

This region adds Django-stack idioms and conventions to the stack-neutral CORE. Apply every item below when writing Django application code. Do not duplicate CORE items here.

---

### App structure

Organize code into one Django app per major domain area (e.g. `accounts`, `core`, `notifications`, `admin_portal`). Each app owns its models, views, forms, serializers, and templates. Cross-app imports are allowed; circular dependencies are not — extract shared logic to a `common` or `utils` app rather than letting apps import each other cyclically.

---

### ORM: querysets and managers

- Write custom `Manager` subclasses (override `get_queryset`) for any model that requires scoping by organization, tenant, or site. Every default queryset must apply that filter — a caller must never need to remember to add it.
- Never bypass a scoped manager with `.objects.all()` or `Model._default_manager` when the request has a scope context. The design doc is the authority on which models are scoped.
- Use `select_related("foreign_key")` for single-object traversals (avoids an N+1 on a ForeignKey or OneToOneField). Use `prefetch_related("m2m_field")` for ManyToMany and reverse FK sets. Add these at the queryset level in the view or manager — not inside a template or serializer.
- Use `only(…)` or `defer(…)` when a view fetches large rows but uses only a small subset of fields and the performance savings are non-trivial; add a comment explaining why.
- Annotate with `Count`, `Sum`, `Avg`, `Max` via `.annotate()` rather than computing aggregates in Python over fetched rows.

---

### Transactions and `select_for_update`

- Wrap any operation that reads and then conditionally writes a shared resource (claim a slot, consume a one-time token, decrement a counter) in `transaction.atomic()` with `Model.objects.select_for_update()` before the read. Without this two concurrent requests can both read the pre-write value and both succeed.
- Database-level constraints (e.g. a GiST exclusion constraint on a time range) are the final arbiter of correctness under concurrency; `select_for_update` is the application-level gate that makes the failure deterministic rather than a silent data race.
- Never rely solely on application-level uniqueness checks — always pair them with a `unique_together`, `UniqueConstraint`, or a database-level constraint.

---

### Migrations

- Always write migrations; never use `--fake` or skip them.
- Run `makemigrations` after every model change and commit the generated file with the code that requires it.
- For migrations that alter large tables (adding columns, adding indexes, dropping columns), assess whether the migration is safe to run online. If the design doc calls out a "safe migration" requirement, use a two-step pattern (add nullable → backfill → add constraint / set NOT NULL) rather than a single blocking migration. Add a comment in the migration file explaining the rationale.
- Do not hand-edit generated migration dependency graphs without a comment explaining why.

---

### Views: class-based and function-based

- Prefer class-based views (CBVs) for standard CRUD patterns (`CreateView`, `UpdateView`, `DeleteView`, `ListView`, `DetailView`) — they reduce boilerplate and make permission mixin injection explicit.
- Use `LoginRequiredMixin` (CBV) or `@login_required` (FBV) on every view that reads or writes user-specific data.
- Use `PermissionRequiredMixin` / `@permission_required` on every view that performs privileged actions.
- For CBVs, do not override `dispatch()` in a way that bypasses a mixin's authentication gate — the mixin's `dispatch()` must be the outermost logic path.
- **2FA/step-up:** for any app with TOTP/2FA, enforce the step-up verification gate at the **view layer on every sensitive action** — not only at login. A view that performs a privileged or irreversible action must verify the second factor is satisfied for the current session, not assume login implies it.
- Verify tenant / org ownership on every view that fetches or mutates a scoped object: `get_object_or_404(Model, pk=pk, organization=request.user.organization)` is the idiomatic form; a bare `get_object_or_404(Model, pk=pk)` followed by a separate ownership check is also acceptable but must be immediately adjacent.

---

### Forms and validation

- Validate at the form layer (or serializer layer for APIs); keep views thin.
- Use `ModelForm` for forms that map directly to models. Add `clean_<field>` methods for field-level cross-validation and `clean()` for cross-field invariants.
- Never perform database writes in a form's `clean()` — that belongs in the view's `form_valid()` (or an equivalent service function).

---

### HTMX partial patterns

- Return an HTTP partial (an HTML fragment, not a full page) when the request carries an `HX-Request: true` header. Return the full page for direct (non-HTMX) navigation to the same URL. A typical pattern:

  ```python
  if request.headers.get("HX-Request"):
      return render(request, "myapp/_partial.html", context)
  return render(request, "myapp/full_page.html", context)
  ```

- HTMX state-changing requests (`hx-post`, `hx-put`, `hx-patch`, `hx-delete`) must carry the CSRF token. Acceptable mechanisms: a `{% csrf_token %}` inside the triggering `<form>`, or a JavaScript snippet that injects the token from the cookie into all HTMX requests via `htmx.on("htmx:configRequest", …)`. A partial that triggers state changes with no CSRF mechanism is a security finding.
- Use `HX-Trigger` response headers to signal client-side events (e.g. show a toast, refresh a sibling element) rather than inlining JavaScript in partials.
- Target swaps (`hx-target`, `hx-swap`) must be consistent: the partial returned must match the target element's expected content — a mismatch produces broken UI without an explicit error.

---

### Templates and design tokens

- The project's design pack (declared in `config.sh`) specifies the token stylesheet and the CSS custom-property conventions. Load that stylesheet before any page CSS.
- Never hard-code hex colors, pixel values, or spacing constants that are defined in the token stylesheet — reference them via `var(--token-name)`.
- Apply component classes (buttons, badges, status indicators, layout primitives) exactly as named in the design pack's component reference. Do not invent class names for components that the design pack already defines.
- Template inheritance: extend a base template that loads the token stylesheet; block-override only `{% block content %}` (and `{% block extra_css %}` / `{% block extra_js %}` when needed). Do not re-include the stylesheet in every child template.
- Use `{% url 'app:view-name' %}` for all internal links — never hard-code URL paths.

---

### Settings and configuration

- Use a settings package (`settings/base.py` + `settings/production.py`, or equivalent) rather than a single flat `settings.py` when the project targets multiple environments.
- `SECRET_KEY`, `DATABASE_URL`, and all application-level secrets (encryption keys, API keys, VAPID keys) must come from the environment — read via `os.environ`, `django-environ`, or `python-decouple`. Never hard-code or version-control them.
- `DEBUG` must resolve to `False` in production. A string `"True"` that evaluates truthy when it should be `False` is a misconfiguration; read it as a boolean: `DEBUG = env.bool("DEBUG", default=False)`.
- `ALLOWED_HOSTS` must be a restrictive list — not `["*"]`.
- Production settings must set: `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, `SECURE_HSTS_SECONDS` (≥ 31536000), `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`, `X_FRAME_OPTIONS = "DENY"`.

---

### Password hashing

- Use `Argon2PasswordHasher` as the first entry in `PASSWORD_HASHERS`. Django ships it as an optional dependency (`argon2-cffi`); add it to the project's requirements. Do not use bcrypt unless the ADR explicitly specifies it.

---

### Encrypted fields and PII

- Store PII (names, emails, phone numbers, addresses, government IDs) using an encrypted field library specified in the ADR. Never store PII in plaintext columns.
- The encryption key must come from the environment, not from source code or a migration.
- Admin list and search views that expose encrypted fields must override `get_queryset` and decrypt carefully — avoid accidentally logging or caching decrypted values.

---

### Signals and middleware

- Use Django signals (`post_save`, `pre_delete`, etc.) only when a receiver genuinely needs to be decoupled from the sender and the coupling would create a circular import. Prefer explicit service-layer calls when the coupling is intentional.
- Middleware that reads or modifies the request/response cycle must be listed in `MIDDLEWARE` in the correct order. Middleware that depends on `request.user` must come after `AuthenticationMiddleware`.
- Custom middleware must implement both `__init__(self, get_response)` and `__call__(self, request)` (the new-style Django middleware interface).

---

### Management commands

- Implement long-running or scheduled operations as `manage.py` commands (subclass `BaseCommand`). This makes them testable, loggable, and invokable from cron / a task scheduler.
- Use `self.stdout.write` and `self.stderr.write` (not `print`) so output is captured correctly in tests and when the command is run non-interactively.
- Management commands that mutate data must be idempotent where possible, and must document their idempotency contract in the class `help` string.

---

### Audit logging

- Every privileged action (staff-only mutation, administrative override, permission grant/revoke, destructive operation) must write an audit log entry to the project's audit model (or the audit mechanism specified in the design doc). The entry must record: who performed the action, what object was affected, and when.
- Audit log entries must be written inside the same `transaction.atomic()` block as the mutation they record — so a rolled-back operation does not produce a phantom audit entry.
