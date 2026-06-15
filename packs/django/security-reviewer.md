## Django security depth

This region adds Django-stack attack surface to the generic security checks in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

---

### Django settings hardening

Check the project's settings module(s) — look for a `settings/` package, `settings.py`, or environment-split files (`settings_production.py`, `base.py` + `production.py`):

- `SECRET_KEY` must come from the environment (`os.environ` / `django-environ` / `python-decouple`); a hard-coded or version-controlled value is a **critical** finding.
- `DEBUG` must be `False` in production settings (or resolved from an env var that defaults `False`). A string `"True"` that evaluates truthy when it should be `False` is a high finding.
- `ALLOWED_HOSTS` must be a restrictive list — not `['*']` and not derived solely from user-supplied input.
- `DATABASE_URL` or individual `DATABASES` credentials must come from the environment, not from source.
- Any application-specific secrets injected into settings (API keys, encryption keys, VAPID keys, TOTP issuer secrets) must follow the same env-only rule.

---

### Django security middleware and headers

Verify the settings configure:

- `SECURE_HSTS_SECONDS` is non-zero in production (recommend ≥ 31536000).
- `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`.
- `SESSION_COOKIE_SECURE = True` and `CSRF_COOKIE_SECURE = True`.
- `X_FRAME_OPTIONS = "DENY"` (or `"SAMEORIGIN"` only when a justified embed exists).
- `SECURE_BROWSER_XSS_FILTER = True` (legacy but harmless; flag absence only when the project targets older browsers per its design doc).
- A Content-Security-Policy header is configured (via middleware such as `django-csp` or a custom middleware) and does **not** allow `unsafe-inline` for scripts.

---

### Django ORM injection

The CORE forbids string-concatenated queries; the Django-specific forms to check are:

- `.extra(where=…)`, `.extra(select=…)` — user-controlled values passed into `where` or `select` kwargs without parameterization (CWE-89).
- `RawSQL("… %s …", params)` — verify `%s` placeholders are used and the params tuple is passed, not string-formatted.
- `Model.objects.raw("SELECT … WHERE x = %s" % value)` — percent-formatting into `.raw()` is injection; `%s` with a params list is safe.
- `Queryset.annotate(…)` or `filter(…)` calls where a field name itself comes from user input (e.g. `qs.filter(**{user_field: value})` where `user_field` is not allowlisted).

---

### Django template injection and `mark_safe`

- `|safe` filter applied to a variable derived from user input is a **critical** XSS finding.
- `mark_safe(user_data)` or `format_html(…)` where the substituted value is unescaped user data is an **critical** XSS finding.
- `TEMPLATES[0]['OPTIONS']['autoescape']` must not be set to `False` globally.

---

### CSRF: middleware coverage and HTMX

- `django.middleware.csrf.CsrfViewMiddleware` must be present in `MIDDLEWARE` and not commented out.
- `@csrf_exempt` on any state-changing view is a finding unless there is a documented justification (e.g. a webhook endpoint verified by HMAC) — even then, note it as a medium requiring human sign-off.
- HTMX state-changing requests (`hx-post`, `hx-put`, `hx-patch`, `hx-delete`) must deliver the CSRF token. Acceptable mechanisms: `HX-Headers` JavaScript snippet that injects the token from the cookie, a `{% csrf_token %}` in the form, or `hx-headers='{"X-CSRFToken": "…"}'` populated from the template context. An HTMX partial that triggers state changes without any of these is a **high** CSRF finding.

---

### Django authentication decorator coverage

Audit every URL-dispatched view (class-based and function-based) that handles authenticated data:

- `@login_required` (or `LoginRequiredMixin`) is present on every view that reads or writes user-specific data.
- `@permission_required` (or `PermissionRequiredMixin`) is present on every view that performs privileged actions.
- Class-based views that override `get()`, `post()`, etc. without calling `super()` may silently bypass mixin enforcement — check that `dispatch()` is not overriding the mixin gate.
- API views (Django REST Framework or `django-ninja`) must have explicit `permission_classes` on every viewset and view; the global default `DEFAULT_PERMISSION_CLASSES` should be `IsAuthenticated` at minimum, not `AllowAny`.

---

### Multi-tenant / org-scoped queryset isolation

Any Django app with org or tenant scoping must verify:

- Every `Model.objects.get(pk=…)` or `.filter(pk=…)` on a tenant-scoped model is immediately followed by an org/tenant equality check — not just an existence check. A user who guesses another tenant's PK must not receive that object (CWE-639 IDOR).
- Custom `Manager` subclasses that implement org-scoping (`get_queryset` filtered by `organization` / `tenant` / `site` / equivalent) are used consistently; never bypassed with `.objects.all()` or `Model._default_manager` when org context is available.
- Django Admin `ModelAdmin.get_queryset(request)` is overridden on every admin class that exposes tenant-scoped objects; the base `get_queryset` returns all rows regardless of org.

---

### Race conditions: `select_for_update`

Concurrent-request atomicity on resource claims, inventory counters, and one-time-use tokens:

- Any operation that reads then writes a value that must be unique or monotonically consumed (e.g. "claim a slot", "consume a one-time code", "decrement a count") must use `Model.objects.select_for_update()` inside a `transaction.atomic()` block. Without this, two concurrent requests can both read the same pre-decrement value and both succeed (CWE-362).
- Recovery codes, invite tokens, and any single-use credential must be consumed atomically — a code that can be used twice under concurrent requests is a **critical** finding.

---

### TOTP / 2FA implementation

For any app that implements time-based or one-time-password 2FA:

- The TOTP secret must be stored encrypted at rest — not as plaintext in the database. Verify the ADR or design doc specifies the encryption mechanism; if the field stores raw bytes without a documented encryption layer, flag it as **critical**.
- Time window tolerance for TOTP validation must be at most ±1 step (±30 seconds). A wider window (e.g. `valid_window=5`) significantly extends replay opportunity; flag as **high**.
- Failed TOTP attempts must be rate-limited (separate from the password rate limit, since TOTP can be probed independently after password entry).
- The TOTP enrollment page (QR code display, secret reveal) must require an authenticated session and must only be accessible when the user has not yet enrolled — it must not be reachable via a guessable URL without authentication.
- TOTP must be verified on every view or action that requires 2FA enforcement — not only at the initial login step. If the design doc specifies 2FA-gated views, check each one has the verification gate.

---

### File upload paths

- `FileField` and `ImageField` `upload_to` arguments must not be set from user-supplied input without sanitization. A user who can influence the storage path can write to arbitrary locations or overwrite existing files.
- Uploaded file names must be sanitized or replaced (e.g. `uuid4()` filenames) before storage; Django's `FileSystemStorage` does not sanitize names by default.

---

### Shell execution with user input

- `subprocess.run(…)`, `subprocess.Popen(…)`, `os.system(…)`, and `os.popen(…)` must never receive unsanitized user input. If any shell command is constructed dynamically, confirm `shell=False` and a list argument form is used; `shell=True` with any user-derived string is a **critical** command-injection finding (CWE-78).
