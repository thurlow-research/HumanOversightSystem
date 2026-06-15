## Django end-to-end test stack

This region adds Django-specific test-client depth to the stack-neutral CORE. Apply every item here **in addition to** the CORE guidance. Do not duplicate CORE items. The PROJECT section supplies this project's specific flows, role names, models, and test-file layout.

---

### Test client

Use the Django test client for all HTTP-layer tests. Two forms are acceptable; choose the one that fits the project's installed harness:

- **Django's built-in `Client`** (`from django.test import Client, TestCase`) — instantiate per test or share a `setUp`-assigned instance.
- **`pytest-django`'s `client` and `admin_client` fixtures** — drop-in equivalents when the project uses `pytest` as the runner. The `admin_client` fixture provides a pre-authenticated superuser session and is the right choice for admin-portal and operator-console flows.

Every test drives the full HTTP request/response cycle: method, URL, request body or query params, response status, redirect chain, and any final response content. Do not call model methods or view functions directly from tests — go through the client.

---

### URL construction

Construct URLs with `django.urls.reverse` (or the `pytest-django` `django_url` fixture). Hard-coding URL strings in tests couples them to the URL conf in a way that makes silent breakage likely. Pattern:

```python
url = reverse("app:view-name", kwargs={"pk": obj.pk})
response = client.get(url)
```

For namespaced URLs, pass the `urlconf` argument to `reverse` only when the test is deliberately targeting a non-default conf; otherwise rely on the project's root URL conf.

---

### Authentication in tests

Test each authenticated flow by logging in through the client first. Prefer the test-client `.login()` / `.force_login()` pair:

- `client.login(username=…, password=…)` — exercises the full authentication backend, including any custom backend or 2FA middleware. Use this for flows that test the login process itself.
- `client.force_login(user)` — bypasses the authentication backend entirely; use it for flows that assume an already-authenticated session and want to skip credential mechanics. Appropriate for most role/permission-boundary tests.

When the project enforces two-factor authentication at the middleware level (e.g. `django-allauth` MFA, `django-two-factor-auth`, or a custom session flag), `force_login` may still not satisfy the 2FA gate. In that case, either use a test-mode TOTP code (when the project provides a test hook) or patch the middleware's session flag directly on the test client's session.

---

### Response and template assertions

After each client call, assert on:

- **Status code** — use Django's `assertRedirects`, `assertEqual(response.status_code, 200)`, or `assertContains`/`assertNotContains`. Prefer `assertRedirects(response, expected_url, status_code=302)` over a bare `assertEqual` on redirects — it also follows the chain and checks the final destination.
- **Template used** — `assertTemplateUsed(response, "app/template.html")` confirms the view rendered the right template without inspecting raw HTML.
- **Response content** — use `assertContains(response, "text or selector")` for presence checks; `assertNotContains` for absence. For JSON responses (`Content-Type: application/json`), parse with `response.json()` and assert on the dict.
- **HTMX partial responses** — when a view returns an HTML fragment rather than a full page (triggered by `HX-Request: true`), assert on `response.content` directly or use `assertContains` on the fragment string. Pass the `HTTP_HX_REQUEST="true"` kwarg to the client call to trigger HTMX paths: `client.get(url, HTTP_HX_REQUEST="true")`.

---

### Real database; no ORM mocking

Tests run against Django's test database (created fresh per test run). Do not mock `Model.objects` or any ORM method. Use the database directly for setup — `Model.objects.create(…)` in `setUp` or `@pytest.fixture` — and assert against the database after the action when the spec requires a persistent-state outcome:

```python
# assert the DB reflects the spec's postcondition, not just the response
obj.refresh_from_db()
assert obj.status == "cancelled"
```

---

### Fixtures and migration setup

Use Django's `TestCase` (or `pytest-django`'s `db` / `django_db` marker) to get an isolated transaction per test. For shared reference data (permission groups, site config, roles), prefer `TestCase.setUpTestData` (class-level, one DB write per class) over `setUp` (per-test). For complex fixture graphs, use `Model.objects.create` chains rather than `.json` fixtures, which become opaque and fragile. Migrations must be applied before tests run; if a migration is missing, the test runner will fail before tests execute — treat this as a blocking issue to route to the coder.

---

### Time-dependent scenarios

For any test that exercises time-sensitive behavior (expiry, horizon advancement, elapsed-time accumulation, cold-start grace periods, token/code lifetimes), use `freezegun`:

```python
from freezegun import freeze_time

@freeze_time("2025-01-15 12:00:00")
def test_expired_invite_rejected(self):
    ...
```

Set the frozen time to a value that makes the spec's precondition deterministic. Do not rely on `datetime.now()` without freezing — results will differ across runs. When testing time-advance scenarios, use two `freeze_time` blocks or `tick=True` + manual advance.

---

### Permission-boundary test mechanics

For every permission boundary in the spec, write a pair of tests: one that confirms the permitted action succeeds (correct status code, correct data returned) and one that confirms the denied action is blocked (correct denial code — `403`, `404`, or redirect to login, per the spec's definition).

Django's test permission tooling:

- Assign permissions to users via `user.user_permissions.add(permission)` or by adding to a group: `user.groups.add(group)`.
- Use `Permission.objects.get(codename="…")` to look up permissions by codename.
- After modifying permissions, call `user = User.objects.get(pk=user.pk)` (or `user.refresh_from_db()` and clear the permission cache: `del user._perm_cache`) before re-testing — the ORM caches permissions on the instance.

For class-based views with `PermissionRequiredMixin` or `LoginRequiredMixin`, the test for the "denied" case must confirm the redirect destination matches the spec (e.g. redirects to `/login/?next=…`, not to a generic 403).

---

### Cross-scope isolation

For any multi-tenant or multi-org application, include a cross-scope isolation test for every model that is scoped to an org/tenant/building. The test:

1. Creates two separate scope entities (e.g. two buildings, two organizations).
2. Creates an object in scope A.
3. Authenticates as a user in scope B.
4. Attempts to access or mutate the scope-A object via the HTTP layer (using its PK in the URL or request body).
5. Asserts the response is `403` or `404` — not `200` (even a `200` that leaks no visible content is still an IDOR).

---

### LiveServerTestCase and browser-layer tests

If the project includes Playwright, Cypress, or Selenium tests, they belong in a separate test directory (e.g. `tests/browser/`) and run via `LiveServerTestCase` or the `pytest-django` `live_server` fixture. Browser-layer tests should cover only flows that cannot be fully verified at the HTTP layer (e.g. JavaScript-driven state that never reaches the server, WebSocket interactions). For all other flows, prefer the Django test client — it is faster, deterministic, and does not require a running browser.

When `LiveServerTestCase` is used:

- Each test class that inherits from it spins up a real WSGI server; do not mix it with standard `TestCase` in the same class.
- Use `self.live_server_url` to construct absolute URLs instead of `reverse`.
- Ensure Playwright/Selenium teardown (`browser.close()`, `playwright.stop()`) happens in `tearDownClass` or the equivalent fixture finalizer to avoid dangling processes.

---

### Test file layout

Organize test files under a `tests/system/` directory at the project root or inside the primary app package. One file per logical flow domain. Name files `test_<domain>.py`. Name test methods `test_<role>_<action>_<condition>` to make the scenario self-documenting in the test runner output. Do not put system tests in the same file as unit tests.
