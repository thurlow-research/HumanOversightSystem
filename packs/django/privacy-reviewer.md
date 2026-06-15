## Django privacy depth

This region adds Django-stack PII mechanics to the generic privacy checks in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

---

### Encrypted model fields

Field-level encryption (e.g. `django-cryptography`, `django-encrypted-model-fields`, or a custom descriptor) is the standard Django pattern for PII that must be read back:

- Verify that fields holding phone numbers, TOTP secrets, or any other "encrypt what you read back" PII use a Django-recognized encrypted field type — not a raw `CharField`/`TextField` with a comment.
- Confirm the encryption key is loaded from the environment (or a key-management backend) — never from `settings.SECRET_KEY` and never hardcoded. Using `SECRET_KEY` as the encryption key couples data security to application rotation, making key rotation destructive.
- `ImageField`/`FileField` storing PII-bearing uploads (e.g. identity documents) must also use an encrypted storage backend — field encryption alone does not protect file contents written to disk or object storage.

---

### `.values()`, `.only()`, and `.defer()` PII leakage

- `.values('email', 'phone', …)` returns a plain `dict` — it bypasses any property-level redaction on the model instance, and can expose encrypted-field raw bytes if the encrypted field type stores as bytes. Confirm that queryset serialization paths that use `.values()` or `.values_list()` on PII fields actually decrypt correctly and do not inadvertently expose ciphertext.
- `.only('email')` and `.defer(…)` narrow the field set but still produce model instances; encrypted descriptors are invoked, so they are generally safer. However, a deferred field that is later accessed triggers a per-row `SELECT` — confirm this does not produce unbounded PII reads in loops.
- DRF / django-ninja serializers that call `.values()` under the hood (e.g. via `source='*'` with a `to_representation` override) must be audited for the same leakage path.

---

### Queryset PII exposure via DRF serializers

- Every `ModelSerializer` that includes a PII field must declare `read_only=True` (or equivalent) unless write access is explicitly required.
- `SerializerMethodField` that returns PII from related objects must be bounded — check that it cannot traverse relationships to expose PII of users other than the request subject.
- `depth` on a `ModelSerializer` is a blanket PII risk: any nested related model that carries PII (e.g. a `User` foreign key resolved two levels deep) will be serialized in full. Flag any `depth > 0` that touches a model with PII fields.

---

### Right-to-erasure via ORM

Django's `on_delete` cascade behavior is the primary mechanism for relational PII cleanup:

- `ForeignKey(User, on_delete=CASCADE)` silently deletes child rows when a user is deleted — this is correct for some objects (sessions, tokens) but wrong for operational records (bookings, audit logs) that must be anonymized, not destroyed. Check every `ForeignKey` pointing to the user model and confirm the `on_delete` policy matches the erasure design.
- `on_delete=SET_NULL` or `on_delete=SET(anonymous_placeholder)` is appropriate for records that must survive erasure with the user identity stripped. Verify the field is `null=True` when `on_delete=SET_NULL` is used, or the `SET()` callable resolves to an anonymous placeholder row, not a live user.
- `on_delete=PROTECT` on a FK to the user model prevents erasure entirely — this is a blocking finding unless a migration path to a soft-delete / anonymization model is documented.
- Custom erasure functions that use `user.delete()` will fire cascades; custom erasure functions that instead zero out PII fields manually must explicitly handle every relationship. Audit for completeness: grep for `ForeignKey.*User` and `OneToOneField.*User` to enumerate all relationships that touch user PII.

---

### Anonymization vs deletion in data migrations (`RunPython`)

Data migrations that backfill, anonymize, or transform PII are high-risk:

- `RunPython` callbacks that read PII must not log it — check for `print()` or `logger` calls inside the callback body.
- A `RunPython` anonymization migration must be reversible via its `reverse_code` argument, or explicitly marked `RunPython(…, reverse_code=RunPython.noop)` with a comment explaining that reversal is intentionally destructive.
- Bulk `QuerySet.update(email=…)` inside a migration bypasses model-level encrypted field save logic — confirm that bulk updates to encrypted fields use the field's encryption encoder explicitly, or use `.save()` on individual instances.
- Migration files must not hardcode PII (e.g. seeding a specific email address or phone number for an initial admin row). Use environment variables or post-deploy management commands instead.

---

### Django auth, session, and user-model PII

- `AbstractUser` / `AbstractBaseUser` subclasses that add PII fields must be reflected in the erasure function — CORE checks that an erasure path exists, but here verify that the Django user model extension itself (e.g. a `Profile` OneToOneField or extra fields on the user model) is covered.
- `SESSION_COOKIE_AGE` and session invalidation on erasure: when a user's account is erased, all active Django sessions for that user must be invalidated. Calling `django.contrib.sessions.backends.db.SessionStore.flush()` or equivalent must be part of the erasure sequence; otherwise a valid session persists after PII is cleared.
- `request.session` must not be used to cache raw PII between requests. The session may store the user's primary key (`_auth_user_id`), but not email, name, phone, or other PII that could survive after erasure.
- Django's built-in `last_login` field updates on every login — this is a low-risk behavioral data point, but flag it if the project's privacy notice does not mention it.

---

### Django logging of PII

Django's logging integration has several surfaces where PII leaks unexpectedly:

- `LOGGING` configuration that sets `django.request` or `django.security` handlers to `DEBUG` or `INFO` level will log full request paths, which may contain PII in query strings or URL segments (e.g. `/users/search/?q=alice@example.com`).
- `django.request` at `ERROR` level logs the full request META dict on 5xx — this includes `HTTP_COOKIE` (session cookie), `HTTP_AUTHORIZATION`, and query strings. Confirm `LOGGING` does not route `django.request` to a persistent log sink at `DEBUG` or `INFO`.
- Custom model `__str__` methods that return PII fields (e.g. `return self.email`) cause that PII to appear in any log line, Django admin change history, or error traceback that stringifies the object. Check `__str__` on user-adjacent models.
- `ADMINS` in settings: Django emails tracebacks to `ADMINS` on 500 errors when `DEBUG = False` — those tracebacks can include request data containing PII. Confirm `ADMINS` is either empty or that the email transport for admin error mail is secured.

---

### Admin and shell PII exposure

- `ModelAdmin` classes that display PII fields in `list_display` must have `show_full_result_count = False` (or equivalent pagination) to prevent bulk enumeration.
- `ModelAdmin.search_fields` that searches on email or phone allows enumeration of PII by any staff user with admin access. Confirm this is intentional and that the admin is protected by 2FA.
- `django.contrib.admin.site.register(User)` without a custom `ModelAdmin` exposes all fields, including any encrypted PII, in the admin change form. Flag unregistered default admin for user models.
