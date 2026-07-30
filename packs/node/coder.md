## Node/JS-TS implementation depth

This region adds generic JS/TS-stack idioms and conventions to the stack-neutral CORE. Apply every item below when writing JavaScript or TypeScript application code. Do not duplicate CORE items here. Framework-specific depth (Astro islands, SSR, etc.) lives in a layered pack, not here.

---

### Module system

- Use ESM (`import`/`export`) for new code unless the project's `package.json` has no `"type": "module"` and no `.mts`/`.cts` split — check `package.json` `type` field and existing file extensions before choosing. Do not mix `require()` and `import` in the same file.
- Barrel files (`index.ts` that only re-exports) are acceptable for a package's public surface; do not create one purely to shorten import paths for internal-only modules — it obscures the real dependency graph and can create circular-import cycles that ESM resolves lazily and CJS does not.
- Prefer named exports over a single default export for anything with more than one public symbol — default exports rename silently at the call site and make refactors (and reviews) harder to grep for.

---

### TypeScript strictness

- The project's `tsconfig.json` is the contract — never weaken `strict`, `noImplicitAny`, or add a local `// @ts-ignore`/`@ts-expect-error` to silence a real type error. If a type genuinely cannot be expressed, narrow it explicitly (a type guard, a discriminated union) rather than widening to `any` or `unknown` without a subsequent narrowing check.
- `any` is a last resort, not a convenience. `unknown` + explicit narrowing is correct at a genuine boundary (JSON.parse output, an external API response); `any` elsewhere defeats the type checker for every downstream consumer of that value.
- Prefer `interface` for object shapes that a consumer might extend/implement, `type` for unions, mapped types, and anything that is not meant to be extended. Do not flip-flop between the two for the same kind of shape within one module.

---

### Async patterns and error handling

- Every `async function` call that is not `await`ed and not explicitly fire-and-forget (with a `.catch()` attached) is a bug: an unhandled promise rejection. Attach `.catch()` or wrap in `try/catch` at the point where an async call is intentionally not awaited (e.g. a background task kicked off from a request handler).
- Do not mix `.then()` chains with `async`/`await` in the same function — pick one style per function for readability and to avoid double-handling rejections.
- `Promise.all()` for a batch of independent async operations; `Promise.allSettled()` when partial failure is expected and must not abort the batch. A bare `Promise.all()` over operations where one is expected to sometimes fail is a correctness bug — the whole batch rejects on the first failure.
- Never swallow an error with an empty `catch {}` block. At minimum log it with context; if the error is truly expected and ignorable, comment why.

---

### `package.json` conventions

- Runtime dependencies go in `dependencies`; anything only used for building, linting, or testing goes in `devDependencies`. A test-only or build-only package in `dependencies` bloats the production install and widens the supply-chain attack surface unnecessarily.
- Pin the `engines.node` field to match the project floor (`>=22` per the framework's Node floor) so a mismatched runtime fails fast at `npm install` rather than at some later runtime surprise.
- Commit the lockfile (`package-lock.json`, `pnpm-lock.yaml`, or `yarn.lock` — whichever the project uses) with every dependency change. Never hand-edit a lockfile; regenerate it via the package manager.
- Use exact or caret-ranged versions consistent with the rest of the file — do not introduce a `*` or a bare tag range for a new dependency when every existing entry is caret-pinned.

---

### Environment and configuration

- Read configuration from `process.env`, never hard-code secrets, API keys, or environment-specific URLs in source. Validate required environment variables at process startup (fail fast) rather than at first use deep in a call stack.
- Do not read `.env` files directly in application code that is expected to run in production (a process manager or the deploy environment supplies real env vars); a `dotenv`-style loader is appropriate only for local development, gated so it does not run in production.

---

### Error objects and propagation

- Throw `Error` (or a subclass) — never throw a bare string or plain object. A thrown string loses the stack trace and breaks `instanceof Error` checks in calling code.
- Define custom error subclasses for error categories the caller needs to distinguish (e.g. `ValidationError`, `NotFoundError`) rather than inspecting a message string to decide behavior.
- Re-throw with context (wrap the original error, preserve `cause`) rather than catching and re-throwing a generic error that loses the original stack — use the `Error` `cause` option (`new Error("...", { cause: err })`) where the runtime supports it.
