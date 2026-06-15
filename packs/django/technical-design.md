## Django technical-design depth

This region adds Django-stack design contract conventions to the stack-neutral CORE. Apply every item below when producing a technical design for a Django project. Do not duplicate CORE items here.

---

### Django models: the design contract

For each model in the design, specify:

- **Field inventory** — exact field names, Django field types (e.g. `CharField(max_length=…)`, `DecimalField(max_digits=…, decimal_places=…)`, `DateTimeField(auto_now_add=True)`), and nullability (`null=True`, `blank=True` only when justified).
- **Constraints and indexes** — every `UniqueConstraint`, `CheckConstraint`, and database index (`Meta.indexes`). For range-overlap exclusion, specify the GiST exclusion constraint DDL (e.g. `ExclusionConstraint` from `django.contrib.postgres.constraints` with `using="gist"` and the overlap operator `&&`).
- **PostgreSQL-native field types** — when the design calls for a time range, specify `DateTimeRangeField` / `DateTimeTZRangeField` (from `django.contrib.postgres.fields`) and note that the column type will be `tstzrange` or `daterange`. When the design calls for JSON storage, specify `JSONField` and the expected schema.
- **Encrypted fields** — for any field storing PII or a secret (encryption key, TOTP secret, recovery code), name the encrypted field type specified in the ADR (e.g. a library such as `django-encrypted-model-fields` or `pgcrypto`). State whether the value is encrypted at rest or hashed (e.g. recovery codes are hashed, not encrypted). Never leave the encryption approach as "TBD" in an approved design.
- **Meta options** — `ordering`, `verbose_name`, `verbose_name_plural`, `default_manager_name` when a scoped manager replaces the default. State the `app_label` if the model lives in a non-obvious app.
- **Relations** — `ForeignKey` `on_delete` behavior for every FK (`CASCADE`, `PROTECT`, `SET_NULL`). For a protected hierarchy, state which side owns the deletion gate.

---

### Multi-tenant org scoping

Any model that belongs to a tenant, organization, or site must have its scoping contract specified in the design:

- Name the FK field that carries the scope (e.g. `organization = ForeignKey(Organization, on_delete=PROTECT)`).
- Name the custom `Manager` subclass that enforces it (e.g. `OrgScopedManager`) and state exactly what `get_queryset` returns: `super().get_queryset().filter(organization=<scope>)`. The design must say where `<scope>` comes from (request middleware, thread-local, explicit argument).
- State which models use the scoped manager as `objects` and which retain an unscoped manager under a secondary name (e.g. `unscoped = Manager()`) for admin or cross-tenant operations.
- Specify how the Django Admin `ModelAdmin.get_queryset(request)` is overridden for every admin class that exposes tenant-scoped objects. A base `ModelAdmin` returns all rows; the design must state the override pattern.

---

### URL structure

Provide a `urlpatterns` skeleton for every URL-dispatched view, grouped by area (e.g. member, account, admin, staff). For each URL entry, specify:

- The URL pattern string (using `<int:pk>`, `<slug:slug>`, or `<uuid:uuid>` converters as appropriate).
- The view class or function name.
- The `name=` for reverse resolution.
- The `include()` prefix and app namespace (`app_name`) for each area.

Example structure (illustrative — adapt URL prefixes to the project's domain):

```
urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("<int:pk>/edit/", views.ItemUpdateView.as_view(), name="item-edit"),
]
```

---

### Views and forms: the design contract

For each view, state:

1. **View name** — the class or function name (e.g. `BookingCreateView`).
2. **HTTP methods** — which of `GET`, `POST`, `PUT`, `PATCH`, `DELETE` the view handles.
3. **Auth requirement** — `LoginRequiredMixin` / `@login_required`, `PermissionRequiredMixin` / `@permission_required`, or explicitly "unauthenticated public".
4. **Form class** — the `ModelForm` or `Form` subclass name, its model (if a `ModelForm`), and the fields it exposes. State any `clean_<field>` or `clean()` cross-field invariants.
5. **HTMX contract** — whether the view returns a full-page response or an HTML partial (triggered by `HX-Request` header). If it returns a partial, name the partial template. If it emits `HX-Trigger` headers, name the events.
6. **Key logic** — the steps the view performs in order, at the level of "what must happen," not how (e.g. "1. look up org-scoped reservation by pk; 2. verify state is `pending`; 3. call `reservation.cancel()`; 4. return 200 partial").
7. **Error paths** — what the view returns on auth failure (redirect to login), permission failure (403), object-not-found (404), and form validation failure (re-render with errors).

For forms, state any database uniqueness constraints that the form's `clean()` must surface as `ValidationError` (rather than letting the database raise an `IntegrityError`).

---

### Algorithm specifications

For every non-trivial computation (availability windows, rolling-window metrics, scheduling, rate-limiting counters), the design must specify:

- **The exact ORM query or SQL** — not a description of the intent, but the method chain or raw SQL. For range arithmetic, write out the PostgreSQL range operator (e.g. `tstzrange(start, end) && existing_range` via `django.contrib.postgres.fields.DateTimeTZRangeField` and `__overlap=` or `__contained_by=` lookups).
- **Where it runs** — view layer, `Manager` method, signal receiver, Celery task, or management command.
- **Caching / materialization contract** — if the result is stored on the model (e.g. a cached counter column), state: (a) when it is written, (b) what triggers a recompute (signal, explicit call, scheduled job), and (c) what happens if it is stale.
- **Edge cases to handle** — what the algorithm returns for an empty input, a zero-duration window, or a range that spans midnight or a DST boundary.

Example: for a range-overlap availability check, the design specifies the `__overlap` queryset filter on `tstzrange`, the `select_for_update()` guard, and that the result is the set of windows minus the union of overlapping confirmed reservations — not merely "check if available."

---

### TOTP and recovery-code flow

For any feature involving time-based one-time passwords or multi-factor authentication, specify:

- **Enrollment steps** — in order: how the secret is generated, how the QR code is presented, which view handles confirmation, and what is written to the database on successful confirmation.
- **TOTP secret storage** — state whether the secret is stored encrypted at rest (name the field type and the key source) or hashed. Plaintext storage in the database is not acceptable; the approved design must name the encryption mechanism.
- **Verification flow** — the exact validation call (e.g. `totp.verify(token, valid_window=1)`), the maximum tolerance window in steps (must be ≤ 1, i.e. ±30 seconds), and which views enforce the TOTP gate (not only the login view).
- **Recovery codes** — how many are generated, how they are stored (hashed, not plaintext), how one-time consumption is enforced atomically (name the `select_for_update()` pattern), and what happens after all recovery codes are exhausted.
- **Rate limiting** — specify a separate rate limit for TOTP verification attempts (distinct from the password rate limit).

---

### Notification dispatch

For each notification event in the design, specify the full dispatch chain:

- **Trigger** — which Django signal (`post_save`, `pre_delete`, a custom signal), which view's `form_valid()`, or which management command fires the event.
- **Handler** — the signal receiver or service function that receives the trigger, the module it lives in, and any filtering logic (e.g. "only when `created=True`").
- **Channel** — which channel(s) the handler dispatches to (email via `send_mail` / a task queue, push via a VAPID key / third-party service, in-app). For each channel, state the template name or payload schema.
- **Failure mode** — whether delivery failure is silent (fire-and-forget), retried (task queue with backoff), or blocks the triggering transaction (must not, in general).

---

### Admin surfaces

For each administrative surface, specify whether it extends Django's built-in admin or is a custom view:

- **Django admin extensions** — which models get a `ModelAdmin`, what `list_display` / `list_filter` / `search_fields` are set, and how `get_queryset(request)` is overridden to enforce tenant scoping. Any `inlines` that expose cross-tenant objects must also scope their querysets.
- **Custom admin views** — for privileged surfaces that extend beyond `ModelAdmin` capabilities (e.g. a staff aggregate dashboard with computed stats), name the view class, its URL, its auth/permission requirement, and the data it exposes.
- **Admin write actions** — for any `ModelAdmin` `action` that performs bulk mutations, state the transaction boundary and whether it emits an audit log entry.

---

### Right-to-erasure and data lifecycle

For any model that stores personal data, the design must specify the erasure path:

- **Fields scrubbed** — list each field that is overwritten with a null or anonymized value on erasure request (e.g. `name = "Deleted User"`, `email = NULL`). State whether the field allows `null=True` or whether a sentinel value is used.
- **Fields deleted** — list models or rows that are hard-deleted on erasure (e.g. session tokens, MFA secrets, uploaded files).
- **Cascade trigger** — how the erasure is initiated (a management command, a view action, a Django signal) and what it walks through (e.g. `User → Reservation → the audit model's scrub()`).
- **What is retained** — state explicitly what is kept for legal or audit purposes and why (e.g. anonymized reservation records with personal fields nulled out).
- **Idempotency** — the erasure operation must be safe to run twice; state how re-erasure of an already-erased record is handled without raising an error.

---

### Migration plan

For each model change in the build step, specify the migration strategy before the coder writes any code:

- **Migration type** — additive (new column nullable, new table), destructive (drop column, drop table), or constraint-altering (add NOT NULL, add index, add exclusion constraint).
- **Online-safe assessment** — for large tables, state whether the migration can run without a table lock. If it cannot (e.g. adding a NOT NULL column with no default), state the two-step pattern: add nullable → backfill data → add constraint / set NOT NULL. The design must specify each step as a separate migration file.
- **Data migration** — if rows must be populated before a constraint is added, describe the `RunPython` operation or the management command that performs the backfill, and state the order relative to the schema migration.
- **Rollback path** — for destructive migrations, state whether the migration is reversible and what the `database_backwards` step does.
