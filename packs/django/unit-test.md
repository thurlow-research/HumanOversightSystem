## Django test-stack depth

This region adds Django-specific test tooling, idioms, and patterns to the generic unit-test role defined in CORE. Apply everything below **in addition to** the CORE targets and iteration discipline. Do not duplicate CORE items here.

---

### Test stack: tools and invocation

**Test runner and coverage:**

```bash
# Run tests with coverage
coverage run --source='.' manage.py test
coverage report --fail-under=80

# Or via pytest-django (preferred for new suites)
pytest --ds=<settings_module> --cov=. --cov-fail-under=80 --cov-report=term-missing
```

Resolve the settings module from the project's `config.sh` or `manage.py` — do not hard-code it. Install missing tools with:

```bash
pip install pytest pytest-django coverage pytest-cov mutmut
```

**Mutation testing:**

```bash
# Run full mutmut suite
mutmut run

# Check results
mutmut results

# Inspect a specific surviving mutant
mutmut show <id>
```

Target: survived mutants / total non-equivalent mutants ≤ 25% (≥ 75% killed). Run mutmut after coverage targets are met; surviving mutants identify undertested logic branches, not just uncovered lines.

---

### pytest-django: database access idioms

Mark every test that touches the database:

```python
import pytest

@pytest.mark.django_db
def test_something_db_touching():
    ...

@pytest.mark.django_db(transaction=True)
def test_something_requiring_real_transactions():
    # Use when testing select_for_update(), signals fired post-commit,
    # or DB-level integrity constraints (IntegrityError on concurrent inserts).
    ...
```

For Django `TestCase`-based tests (class style), database access is implicit inside the class; use `TestCase` for DB-touching tests and `SimpleTestCase` for pure-logic tests:

```python
from django.test import TestCase, SimpleTestCase

class MyModelTest(TestCase):       # wraps each test in a transaction; rolls back after
    ...

class MyPureLogicTest(SimpleTestCase):  # no DB; faster
    ...
```

Prefer `pytest-django` for new test files; `TestCase` subclasses are acceptable when the existing suite uses them — do not rewrite working tests.

---

### Query-count assertions

Use `django_assert_num_queries` (pytest-django fixture) to pin query counts on critical paths and catch N+1 regressions:

```python
def test_no_n_plus_one(django_assert_num_queries, client):
    # Seed data first, then measure
    with django_assert_num_queries(3):
        response = client.get("/some/list/")
    assert response.status_code == 200
```

Use `django.test.Client` (or `pytest-django`'s `client` fixture) for view-layer tests; do not mock the ORM for integration-level tests.

---

### Factory-based test data

Use `factory_boy` or `model_bakery` (`baker`) for test data. Never copy-paste fixture dicts. Never rely on fixture files for anything beyond read-only seed data:

```python
# factory_boy
import factory
from myapp.models import MyModel

class MyModelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MyModel
    name = factory.Sequence(lambda n: f"item-{n}")

# model_bakery
from model_bakery import baker
obj = baker.make("myapp.MyModel", name="test")
```

Keep factories in `tests/factories.py` (or a `factories/` package for large suites). Factories should not hard-code PKs — let the DB assign them.

---

### Time-dependent tests: freezegun

Use `freezegun` for any test whose behavior changes with the current date/time (e.g., expiry windows, scheduled intervals, time-bucketed metrics):

```python
from freezegun import freeze_time

@freeze_time("2025-01-15 10:00:00")
def test_something_time_sensitive():
    # now() is frozen at 2025-01-15 10:00:00 UTC inside this test
    ...
```

Never use `datetime.now()` directly in tests — always freeze or inject the time. Tests that call real-clock `now()` are non-deterministic.

---

### Model constraint testing patterns

Test DB-level constraints directly — do not assume application-layer validation is sufficient:

```python
from django.db import IntegrityError
import pytest

@pytest.mark.django_db(transaction=True)
def test_unique_constraint_enforced():
    MyModelFactory(field="value")
    with pytest.raises(IntegrityError):
        MyModelFactory(field="value")  # duplicate — must raise

@pytest.mark.django_db(transaction=True)
def test_overlap_constraint_enforced():
    # For PostgreSQL range exclusion constraints (ExclusionConstraint)
    RecordFactory(range=DateTimeTZRange("2025-01-01 10:00", "2025-01-01 12:00"))
    with pytest.raises(IntegrityError):
        RecordFactory(range=DateTimeTZRange("2025-01-01 11:00", "2025-01-01 13:00"))
```

Test field-level validators via `full_clean()` before saving, not just at the view layer:

```python
from django.core.exceptions import ValidationError

def test_field_validation_rejects_bad_value():
    obj = MyModel(field=invalid_value)
    with pytest.raises(ValidationError):
        obj.full_clean()
```

---

### Manager and queryset method testing

Test custom `Manager` and `QuerySet` methods in isolation against real DB rows:

```python
@pytest.mark.django_db
def test_scoped_manager_excludes_other_tenant():
    org_a = OrgFactory()
    org_b = OrgFactory()
    item_a = MyModelFactory(org=org_a)
    item_b = MyModelFactory(org=org_b)

    results = MyModel.objects.for_org(org_a)
    assert item_a in results
    assert item_b not in results
```

Never bypass a scoped manager in tests with `MyModel._default_manager.all()` to "see everything" — that pattern replicates the production bug you are supposed to be catching.

---

### Transaction and rollback test handling

When testing behavior that depends on commit vs. rollback semantics:

- Use `@pytest.mark.django_db(transaction=True)` (pytest) or `TransactionTestCase` (class style) for tests that need real `COMMIT`/`ROLLBACK` behavior (e.g., `on_commit` signal handlers, `select_for_update` rows visible to a second connection).
- Standard `TestCase` / `@pytest.mark.django_db` wraps each test in a `SAVEPOINT` that never commits; `on_commit` hooks will not fire — use `TestCase.captureOnCommitCallbacks(execute=True)` (Django 4.1+) or `mute_signals` if you need them in the non-transactional style.

---

### Recommended test file layout

Organize tests to mirror the responsibility being tested, not the model hierarchy:

```
tests/
  factories.py           # or factories/ package
  test_models.py         # field constraints, full_clean, __str__, properties
  test_managers.py       # custom Manager/QuerySet methods
  test_forms.py          # form validation, clean(), save()
  test_views.py          # request/response, status codes, redirect targets
  test_signals.py        # signal handlers fire correctly
  test_tasks.py          # Celery/background tasks (if present)
  test_<domain>.py       # one file per major domain invariant or workflow
```

Each test method: one behavioral focus, named after what it pins — `test_<thing>_<outcome>_when_<condition>`. Prefer flat test functions (pytest style) over deeply nested `setUp`/`tearDown` hierarchies.
