## Node/JS-TS idiom depth for code review

This region adds generic JS/TS-stack correctness and idiom checks to the generic review criteria in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

---

### Unhandled promise rejections

Check every `async` call site:

- A call to an `async function` (or anything returning a `Promise`) that is neither `await`ed, `.catch()`-handled, nor explicitly assigned/returned to a caller that will handle it is a **blocking finding** — an unhandled rejection crashes a Node process by default (since Node 15) or leaks silently, depending on runtime config.
- `Promise.all()` over a set of operations where the reviewer can identify at least one operation that is expected to sometimes fail independently of the others is a correctness finding — the whole batch aborts on first rejection when `Promise.allSettled()` was the intended semantics.
- An `async` function used as an Express/Fastify/Koa-style route handler without a wrapping error boundary (try/catch, or a framework helper that forwards rejections to error-handling middleware) will not surface a thrown error to the framework's error handler in frameworks that do not auto-catch async handlers — verify the project's framework version and middleware setup account for this.

---

### Module system consistency

- Flag any file mixing `require()` and `import` syntax — this is a correctness risk under bundlers/transpilers that assume one module system per file, not just a style nit.
- Circular imports between modules that both execute top-level side effects (not just export declarations) are a finding — ESM's live bindings can partially initialize under a cycle, producing `undefined` where a value is expected.
- A default export re-assigned or mutated after module load (`module.exports.foo = …` outside the initial declaration, or a `let`-bound default export mutated by a consumer) is a finding — it makes the module's public surface implicit and order-dependent.

---

### TypeScript type-safety

- Any new `any` (explicit or via an un-typed third-party import with no `@types` package and no local declaration file) is a finding unless justified with a comment explaining why the boundary cannot be typed narrower.
- A new `// @ts-ignore` or `@ts-expect-error` suppressing a real type error (not a known compiler limitation) is a **blocking finding** — request the actual type fix.
- Non-null assertions (`value!`) on a value whose nullability the reviewer can trace back to genuinely uncertain input (a fetch response, a `Map.get()` result, a DOM query) are a finding — request an explicit null check or a fallback instead of asserting away the compiler's warning.

---

### `package.json` diff review

- A new dependency added to `dependencies` that is only imported from a test file or a build script belongs in `devDependencies` — flag the misplacement.
- A lockfile present in the diff without a corresponding `package.json` dependency change (or vice versa — a `package.json` change with no lockfile update) is a finding; they must move together.
- A new dependency with a version range wider than the rest of the file's convention (e.g. `*` or `latest` when every other entry is caret-pinned) is a finding — inconsistent pinning defeats reproducible installs.

---

### Callback and event-emitter idioms

- Node-style callbacks `(err, result) => {}` must check `err` first and return/throw before touching `result` — a callback that reads `result` before checking `err` is a correctness bug (result is `undefined`/garbage on error).
- `EventEmitter`-based code must attach an `'error'` listener on any emitter that can emit one — an emitter with no `'error'` listener throws synchronously and can crash the process when an `'error'` event fires.

---

### Error propagation and typing

- A caught error re-thrown as a new generic `Error` without preserving the original message/stack (no `cause` option, no message interpolation) loses debugging context — flag it as a finding when the surrounding code is diagnostic-sensitive (top-level handlers, logging paths).
- Thrown non-`Error` values (a string, a plain object, a number) are a blocking finding — they break `instanceof Error` checks and lose stack traces for every catcher up the call chain.

---

### Node version and engine assumptions

- Code using an API gated behind a Node version newer than the project's `engines.node` floor (check `package.json`) is a finding — verify against the declared floor, not the reviewer's local Node version.
