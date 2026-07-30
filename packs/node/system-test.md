## Node/JS-TS end-to-end test stack

This region adds generic JS/TS-specific system/integration-test depth to the stack-neutral CORE. Apply every item here **in addition to** the CORE guidance. Do not duplicate CORE items. Browser/UI-layer end-to-end tooling (Playwright, component testing) is framework-specific and belongs to the layered pack (e.g. astro), not here.

---

### HTTP-layer testing

For a Node HTTP server (Express, Fastify, Koa, or a bare `http.Server`), drive requests through the actual request/response cycle rather than calling route handlers directly:

```javascript
import request from "supertest";
import { app } from "../src/app.js";

test("returns 404 for an unknown route", async () => {
  const res = await request(app).get("/does-not-exist");
  expect(res.status).toBe(404);
});
```

Start the server on an ephemeral port (`0`) for the test process — never hard-code a port a parallel test run could collide on. Prefer passing the app/handler instance directly to the test HTTP client (supertest accepts an app instance without a listening socket) over spinning up a real listening server when the framework supports it — faster and avoids port contention entirely.

---

### Authentication in tests

Exercise the real auth flow at least once per protected route class (login → session/token issuance → authenticated request), then use a lightweight shortcut (a pre-signed test token, a seeded session) for the remaining tests of that route to avoid re-running the full login flow hundreds of times. Do not hard-code a static "test" token that bypasses signature verification in code paths that also run in production — gate any test-only auth shortcut behind an environment check that cannot be true outside the test runner.

---

### Response assertions

- Assert on status code, response body shape (not just presence — use the project's schema/type if one exists), and relevant headers (`Content-Type`, `Location` on redirects).
- For JSON APIs, parse and assert against the parsed object (`res.body` in supertest, `await res.json()` for `fetch`) — do not assert on the raw string unless testing serialization itself.
- For streaming or chunked responses, assert on the fully-consumed stream content, not just that the response started.

---

### Contract-first independence

When the project publishes a machine-readable API contract (an OpenAPI/Swagger document, a shared Zod/io-ts schema package, a tRPC or GraphQL SDL definition), validate the actual response against that contract — not only against hand-written assertions that happen to match the handler's current output:

```javascript
import { orderResponseSchema } from "../../src/contracts/order.js";

test("GET /orders/:id matches the published contract", async () => {
  const res = await request(app).get(`/orders/${id}`);
  expect(() => orderResponseSchema.parse(res.body)).not.toThrow();
});
```

The contract is the durable, reviewable oracle; the handler's current serialization is not. Do not derive the contract validator from the handler's current output (e.g. snapshotting today's response into a schema file) — trace it back to the spec/design doc or to a contract file the coder did not generate from the implementation. A response that satisfies your hand-written assertions but fails contract validation is a drift signal to report, not a passing test.

---

### Real dependencies over mocks at the system level

System tests exist to catch integration bugs that unit tests (which mock the boundary) cannot. Run system tests against a real (or realistic containerized) instance of the database, cache, or queue the service depends on — not a mock of the client library. Reserve mocking, at this layer, for genuinely external third-party services (a payment gateway, an email provider) that cannot be run locally; use a recorded-fixture/sandbox mode for those where the provider offers one.

---

### Process and CLI testing

For a CLI tool or a script entry point, invoke the actual built/compiled entry point as a child process rather than importing and calling its internal functions:

```javascript
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const run = promisify(execFile);

test("prints usage when called with no arguments", async () => {
  const { stdout } = await run("node", ["./bin/cli.js"]);
  expect(stdout).toContain("Usage:");
});
```

This catches packaging/entry-point bugs (a missing shebang, a broken `bin` field in `package.json`, an unhandled top-level exception) that in-process function calls cannot.

---

### Time-dependent scenarios

Use the runner's fake-timer facility (`vi.useFakeTimers()` / `jest.useFakeTimers()`) at the system-test layer the same as at unit-test layer for any flow with expiry, scheduled intervals, or elapsed-time accumulation. For flows that genuinely require wall-clock elapsed time crossing process boundaries (a background worker in a separate process), prefer an injectable clock/time-source in the application code over sleeping the test.

---

### Test isolation and cleanup

Each system test must leave shared external state (database rows, queue messages, cache entries) in the state it found it, or run against an isolated per-test/per-suite resource (a per-test database schema, a namespaced queue). A test that depends on execution order or leftover state from a prior test is flaky by construction — flag this in review, don't just re-run until it passes.

---

### Test file layout

Organize system/integration tests under a `test/system/` or `test/integration/` directory, separate from `test/unit/`. Name files `<flow>.test.ts` after the user-facing or API-facing flow under test, not after the internal module it happens to exercise most.
