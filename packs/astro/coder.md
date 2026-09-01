## Astro implementation depth

This region adds Astro-framework idioms to the generic JS/TS depth in PACK:node. Apply every item below when writing `.astro` components, pages, endpoints, or middleware. Do not duplicate PACK:node or CORE items here.

---

### Islands architecture and hydration directives

Astro ships zero client-side JS by default — every framework component (`.astro`, or a React/Vue/Svelte component imported into one) renders to static HTML unless explicitly hydrated with a `client:*` directive. Choose the directive deliberately, not reflexively:

- `client:load` — hydrates immediately on page load. Reserve for above-the-fold interactive elements the user needs the instant the page is usable (a nav toggle, a cart badge). Overusing it defeats the islands model — it ships and runs JS as eagerly as a traditional SPA.
- `client:idle` — hydrates once the main thread is idle (`requestIdleCallback`). Correct default for interactive-but-not-critical components (a newsletter signup, a "load more" button below the fold).
- `client:visible` — hydrates when the component enters the viewport (`IntersectionObserver`). Correct for below-the-fold interactive widgets (a comment form, a carousel further down the page).
- `client:media="(query)"` — hydrates only when a media query matches. Use for components that are only interactive at a given breakpoint (a mobile-only hamburger menu) — do not hydrate desktop-only interactivity on mobile viewports.
- `client:only="react"` (or `vue`/`svelte`/…) — skips server rendering entirely; the component renders client-side only. Only correct when the component genuinely cannot render without a browser API (e.g. reads `window`/`localStorage` at first render) — flag any other use as a missed SSR opportunity.
- A component imported without any `client:*` directive is inert HTML/CSS only — no framework runtime ships for it. Verify every interactive component the design calls for actually carries a directive; a missing directive is a silent functionality bug, not a build error.

---

### Rendering modes: SSG vs SSR vs hybrid

`astro.config.mjs`'s `output` setting governs the whole project's default:

- `output: 'static'` — every route is prerendered at build time. Correct default for content that does not depend on request-time data (marketing pages, docs, blog posts).
- `output: 'server'` — every route renders per-request via the configured adapter. Required when most routes need request-time data (auth-gated dashboards, personalized content).
- `output: 'hybrid'` (static by default, opt individual routes into SSR with `export const prerender = false`) or, on `output: 'server'`, the inverse (`export const prerender = true` to force a route static) — use the per-route `prerender` export to mix modes rather than forcing the whole project into `server` because one route needs it. A project with a handful of dynamic routes and mostly static content should default `static`/`hybrid` with `prerender = false` opt-outs, not `server` with static routes achieving no benefit from the extra opt-in.
- A route reading `Astro.request` (headers, method) or `Astro.cookies` at render time requires `prerender = false` (or `output: 'server'`) — this will build successfully under `static` output but silently see build-time-only defaults in production; verify the rendering mode matches the route's actual data dependency.

---

### Content collections

Structured content (blog posts, docs, product data) belongs in `src/content/` under a `defineCollection()` schema (`src/content/config.ts`), not ad-hoc frontmatter parsing:

- Define a Zod schema (`schema: z.object({...})`) for every collection so malformed frontmatter fails at build time, not at render time in production.
- Query with `getCollection('name', filterFn)` / `getEntry()` — never hand-roll a `fs.readdir` + gray-matter parse when a content collection covers the case; that duplicates work the framework already validates and caches.
- For collections rendering full documents, use `render(entry)` to get the `<Content />` component and headings — don't reimplement markdown rendering.
- A collection referenced from a dynamic route (`getStaticPaths()` mapping collection entries to routes) must handle an empty collection (build-time empty array) without throwing — verify a fallback or explicit empty-state page exists.

---

### Endpoints (`src/pages/**.ts` API routes)

A `.ts`/`.js` file under `src/pages/` exporting `GET`/`POST`/`PUT`/`DELETE`/`ALL` is a server endpoint, not a page:

- Type the handler with `APIRoute` (`import type { APIRoute } from 'astro'`) so the `context` parameter (`params`, `request`, `cookies`, `redirect`) is fully typed — an untyped `(context) => {}` handler loses this for no benefit.
- Endpoints require `export const prerender = false` unless the project's `output` is already `'server'` — a prerendered endpoint runs once at build time and serves a static response forever, which is almost never the intent for anything reading `request`/`params`.
- Return a `Response` object (`new Response(JSON.stringify(data), { status, headers })`, or the `Astro.redirect`/`context.redirect` helper for redirects) — do not return a bare object or string; endpoints are raw HTTP handlers, not framework-magic serializers.
- Dynamic segments (`src/pages/api/[id].ts`) read `params.id` — validate and coerce it (it is always a `string | undefined`) before using it in a query or lookup; an unvalidated `params.id` reaching a database call is the same class of bug PACK:node's injection guidance covers.

---

### Middleware

`src/middleware.ts` (or `.js`) exporting `onRequest` (via `defineMiddleware`) runs on every request in SSR mode:

- Use `defineMiddleware((context, next) => {...})` for type safety over a bare exported function.
- Chain multiple middleware with `sequence(a, b, c)` from `astro:middleware` rather than nesting manual `next()` calls — sequence's ordering is explicit and reviewable; hand-rolled chaining is not.
- Data attached to `context.locals` for downstream pages/endpoints must be typed via an `App.Locals` interface declaration (`src/env.d.ts`) — an untyped `locals.user = ...` assignment is invisible to every consumer's type checker.
- Middleware that never calls `next()` short-circuits the entire request (correct for an auth redirect); middleware that conditionally forgets to call `next()` on the success path hangs the response — verify every code path either calls `next()` or returns a `Response` explicitly.
- Middleware only executes for SSR-rendered routes (`prerender: false` or `output: 'server'`); it does not run against prerendered static output served directly by the CDN/host. A middleware-based check (auth, header injection) intended to protect a route that is itself prerendered is a design bug, not a middleware bug — the route must be forced to SSR for the middleware to have any effect.

---

### Environment variables

- Read env vars via `import.meta.env.VAR_NAME`, not `process.env`, in `.astro` files or client-shipped code — `import.meta.env` is Vite's statically-analyzed, build-time-inlined mechanism and is what makes the `PUBLIC_` prefix rule (see PACK:astro security-reviewer) enforceable at all. `process.env` is only valid in Node-context server code (an endpoint, middleware, or `astro.config.mjs`) running under an SSR adapter.
- Define the shape of `import.meta.env` in `src/env.d.ts` (`interface ImportMetaEnv`) so a missing or misnamed env var is a type error, not a silent `undefined` at runtime.
