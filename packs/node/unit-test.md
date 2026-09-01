## Node/JS-TS test-stack depth

This region adds generic JS/TS-specific test tooling, idioms, and patterns to the generic unit-test role defined in CORE. Apply everything below **in addition to** the CORE targets and iteration discipline. Do not duplicate CORE items here.

---

### Spec-derived test independence

Derive each assertion's expected value from the technical design and the module's documented contract — its exported TypeScript interface, JSDoc `@param`/`@returns`, or a runtime schema (Zod, io-ts, TypeBox) — not by running the implementation and copying its current output into the assertion. A test whose expected value was captured that way is not a test; it certifies whatever the implementation does today, bugs included, and keeps passing after a regression that changes the output.

Where the module defines a runtime schema, validate against it directly instead of hand-writing shape assertions that merely happen to match the implementation's return value:

```typescript
import { orderSchema } from "../src/schemas/order.js";

test("computes order total from line items", () => {
  const result = computeOrderTotal(fixture);
  expect(orderSchema.parse(result)).toEqual(result); // throws if result violates the documented schema
  expect(result.total).toBe(4599); // value derived from the spec's pricing rule, not from running computeOrderTotal
});
```

When you can see the diff that produced the code under test, do not read the diff to decide what to assert — read the spec/design section first, write the expected value from that, then check it against the diff. Coverage and mutant score (CORE targets) measure how much of the implementation your tests exercise; they say nothing about whether the exercised behavior is correct. Assertions sourced from the implementation instead of the spec can meet both targets and still certify nothing.

---

### Test stack: tools and invocation

**Test runner and coverage:**

```bash
# vitest (preferred for new Vite-based or ESM-native projects)
npx vitest run --coverage

# jest (use when the project already standardizes on it — do not migrate an
# existing suite without an explicit design decision)
npx jest --coverage
```

Resolve the runner from the project's `package.json` `scripts.test` entry and any existing config file (`vitest.config.ts`, `jest.config.js`) — do not assume one over the other; use whichever the project already has installed.

Target coverage: ≥ 80% line coverage on changed files, matching the framework's stack-neutral floor. A coverage config with `--fail-under`/`coverageThreshold` set below that floor for a build step is a finding for the reviewer, not something the test-writer silently accepts.

---

### Module mocking

- Use the runner's native mocking (`vi.mock()` for vitest, `jest.mock()` for jest) to replace a module's exports for a test file; both hoist the mock above imports at transform time — do not rely on import order to make a manual mock take effect.
- Mock at the boundary the test actually needs isolated (an HTTP client, a database driver, a filesystem call) — do not mock the module under test itself, and do not mock so deep that the test stops exercising real logic.
- Reset or restore mocks between tests (`vi.restoreAllMocks()` / `jest.restoreAllMocks()` in an `afterEach`) — a mock that leaks its call history or return value into the next test produces order-dependent failures.

---

### Async test patterns

- `async`/`await` every test body that exercises a promise-returning function; a test that returns a promise without awaiting it can report false-green (the assertion inside the promise never runs before the test framework marks it passed).
- Use the runner's async-rejection matcher (`await expect(promise).rejects.toThrow(...)` in vitest/jest) rather than wrapping in a manual `try/catch` with a `fail()` call in the `catch` — the matcher form fails loudly if the promise unexpectedly resolves instead of rejecting.
- Fake timers (`vi.useFakeTimers()` / `jest.useFakeTimers()`) for any test whose behavior depends on `setTimeout`/`setInterval`/`Date.now()` — advance them explicitly (`vi.advanceTimersByTime(...)`) rather than using real `sleep`-style waits, which make the suite slow and flaky under CI load.

---

### Snapshot testing

- Snapshots are appropriate for stable, reviewed output (a serialized config object, a rendered error message) — not for output that changes on every run (timestamps, generated IDs, non-deterministic ordering). Normalize or exclude volatile fields before snapshotting.
- Treat a snapshot update (`--update`/`-u`) as a code change requiring the same review scrutiny as the underlying logic change — an accepted snapshot update that silently absorbs a regression is a common false-negative in JS suites.

---

### Fixture and factory data

- Use a small builder/factory function per domain type rather than copy-pasted literal objects across test files — a shape change to the type should require updating one factory, not every test file that constructs that shape.
- Keep factories in a `test/factories/` (or `__fixtures__/`) directory; do not inline large literal fixtures inside test bodies where they obscure the actual assertion being made.

---

### TypeScript in tests

- Test files should type-check under the same `tsconfig.json` strictness as application code — a test-only `any` to work around a typing friction point defeats the purpose of writing tests in TypeScript. Prefer typed test helpers (a generic factory function, a typed mock builder) over casting.
- Do not use `@ts-ignore` in test files to suppress a real type error in the code under test — that is a signal the test found a real typing bug; fix the underlying type, don't silence the test.

---

### Test file layout

Organize tests to mirror the module under test, not an arbitrary grouping:

```
src/
  orders/
    order-service.ts
    order-service.test.ts    # co-located, or:
test/
  unit/
    orders/
      order-service.test.ts  # mirrored tree, whichever the project already uses
```

Name test files `<module>.test.ts` (or `.spec.ts` — match the project's existing convention, do not introduce a second one). Name test cases `it("does X when Y", ...)` / `test("...")` — one behavioral focus per test, named after what it pins.
