## Django idiom depth for code review

This region adds Django-stack correctness and idiom checks to the generic review criteria in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

---

### ORM queryset correctness

Check every queryset in views, serializers, management commands, and signals for:

- **N+1 queries:** any loop that calls a related-object accessor (e.g. `obj.related_set.all()` or `obj.foreign_key`) without a preceding `select_related()` or `prefetch_related()` is an N+1 finding. The fix is not performance — it is correctness: a queryset that fires one SQL per loop iteration changes behaviour under pagination, timeouts, and test isolation.
- **Queryset evaluation site:** a queryset is lazy and evaluates on first iteration, `len()`, `list()`, `bool()`, or slicing. A queryset stored in a variable and then re-evaluated in a different scope (e.g. passed to a template and iterated twice) executes the query twice. Flag any queryset that could be evaluated more than once without being cached via `list()` or `queryset.all()`.
- **Unguarded `.get(pk=…)` on tenant-scoped models:** `.get(pk=…)` without an accompanying scope filter returns any row in the table. On any model with a multi-tenant scope field (`organization`, `tenant`, `site`, or equivalent), every `.get()` and `.filter(pk=…)` must include the scope field. A bare `.get(pk=…)` on a scoped model is a blocking finding.
- **`.all()` bypassing a scoped manager:** if the model defines a custom `Manager` that filters by org/tenant scope, calling `.objects.all()` or falling back to `Model._default_manager` silently bypasses that scope. Verify the correct manager is used consistently.

---

### Custom managers and scoped querysets

For any model that carries a tenant, organisation, or site FK:

- A custom `Manager` subclass (overriding `get_queryset`) must be defined and set as the model's default manager for every model in that scope. Ad-hoc `.filter(organization=…)` inline in views signals the manager is missing or being bypassed.
- The manager must be the first manager declared on the model (Django makes the first manager the default; a third-party app that declares its own manager early can silently displace the scoped one).
- `ModelAdmin.get_queryset(request)` must be overridden on every admin class that exposes scoped models — Django Admin bypasses custom managers and calls `_default_manager.get_queryset()` directly.

---

### Transaction boundaries and `select_for_update`

Any operation that reads then conditionally writes a shared resource (slot, inventory counter, one-time token, unique enrollment) must be wrapped in `transaction.atomic()`:

- The read **and** the write must both be inside the same `atomic()` block.
- Concurrent-claim operations (e.g. "claim the last available unit") must use `Model.objects.select_for_update()` on the read query inside the `atomic()` block. Without `select_for_update`, two concurrent requests can both read the same pre-claim state and both succeed.
- `select_for_update()` outside `transaction.atomic()` raises a `TransactionManagementError` at runtime — verify every `select_for_update()` call is enclosed in an `atomic()` block.
- Avoid long-running work (network calls, file I/O) inside an `atomic()` block — it holds the row lock for the duration and can cause contention.

---

### Signals

- Signal handlers must not perform blocking I/O (network calls, file writes) synchronously. Blocking I/O in a `post_save` or `post_delete` handler executes inside the request/response cycle and couples DB commit latency to external service latency. Defer to a task queue.
- Signal handlers must not import the sender model at module level if that creates a circular import. Use `apps.get_model()` or an `AppConfig.ready()` import guard.
- A signal handler that raises an exception aborts the surrounding transaction if the signal fires inside `atomic()`. Any handler that can raise must be written to fail gracefully or be connected with an explicit exception guard.
- Prefer explicit method calls over signals for in-process coordination: signals are appropriate for cross-app decoupling, not for orchestrating logic within a single app.

---

### Form and view validation separation

- Field validation, cross-field validation, and business-rule validation belong in the form or serializer (`clean_<field>`, `clean()`), not duplicated in the view. A view that re-implements validation logic that already exists in the form is a blocking finding — the form layer is the contract; the view should call `form.is_valid()` and trust it.
- `ModelForm.save(commit=False)` is appropriate when the view needs to set fields not present in the form (e.g. `obj.owner = request.user`) before saving; it is not appropriate as a way to bypass the form's `clean()` — `form.instance` must still be valid before `.save(commit=True)`.
- Class-based view mixins (`LoginRequiredMixin`, `PermissionRequiredMixin`, form mixins) enforce their contracts in `dispatch()`. A CBV that overrides `dispatch()` without calling `super()` silently discards all mixin enforcement — flag any such override.

---

### HTMX partial responses

- A view that can be called by both a full-page request and an HTMX partial request must branch on the `HX-Request` header (`request.headers.get("HX-Request")`). Returning a full-page response to an HTMX request (which expects a fragment) will replace the swap target with a full HTML document.
- HTMX-triggered state-changing requests (`hx-post`, `hx-put`, `hx-patch`, `hx-delete`) must include the CSRF token. This is a correctness check (the response will be a 403 otherwise), not a security check — note it here if the mechanism is absent; the security-reviewer owns the security classification.
- An `hx-swap` that targets an element by `id` will silently no-op if the element is absent from the DOM. Verify the target selector exists in the template that renders the swap target.
- After a successful state-changing HTMX request, a redirect is usually handled via `HX-Redirect` response header (or `HX-Location`), not a standard `HttpResponseRedirect` — a standard redirect response is not followed by HTMX; the partial swap target receives the redirect response body instead.

---

### Migration correctness

- Every model field addition, removal, rename, or constraint change must have a corresponding migration. A model change without a migration is a blocking finding (the application will fail at deployment or test setup).
- **Database-level constraints:** constraints declared in `model.Meta.constraints` (e.g. `UniqueConstraint`, `CheckConstraint`, `ExclusionConstraint`) must be present in the migration — not only in the model's `Meta`. A constraint present in the model but absent from the migration is not enforced on existing databases.
- Migration dependencies: a migration that references a field or model from another app must list that app's migration in its `dependencies`. A missing cross-app dependency causes `migrate` to fail on a clean database.
- `RunPython` and `RunSQL` operations in a migration must be wrapped in `atomic=False` only when they are performing operations that cannot run inside a transaction (e.g. `CREATE INDEX CONCURRENTLY` on PostgreSQL). A `RunPython` that modifies data defaults to running inside the migration's transaction; do not disable atomicity unnecessarily.
- Reversible migrations: every `RunPython` should supply a reverse function (or `RunPython.noop` if reversal is truly impossible). An irreversible migration should be explicitly documented.

---

### Settings and configuration

- Environment-specific settings (database credentials, `SECRET_KEY`, `DEBUG`, third-party API keys) must not be hard-coded in a settings file. This is a correctness check for the settings module structure — note it here; the security-reviewer and infra-reviewer own the security and deployment classifications respectively.
- `INSTALLED_APPS` must list the app's `AppConfig` dotted path (e.g. `'myapp.apps.MyAppConfig'`) rather than the bare module name when the app defines an `AppConfig` — Django uses the `AppConfig` for signal connection in `ready()`.
- `AUTH_USER_MODEL` must be set before the first migration if the project uses a custom user model. Changing it after initial migrations have been applied requires a complex migration path.

---

### Model field idioms

- `CharField` and `TextField` on models should not use `null=True` — Django convention is `blank=True` with an empty string default for optional string fields. A `null=True` on a string field introduces two representations of "no value" (`None` and `""`).
- `DateTimeField(auto_now_add=True)` and `auto_now=True` are not editable via forms or serializers. If the field needs to be set programmatically (e.g. in tests or migrations), use `default=timezone.now` and manage it explicitly instead.
- `ForeignKey` and `OneToOneField` must specify `on_delete` explicitly — Django requires it and `CASCADE` vs `SET_NULL` vs `PROTECT` is a correctness decision, not a default.
- `GenericForeignKey` fields must declare both `ct_field` and `fk_field` explicitly and the related `ContentType` FK must exist on the model.
