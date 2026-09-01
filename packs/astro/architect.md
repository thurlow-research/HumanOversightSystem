## Astro architecture depth

This region adds Astro-stack architecture concerns to the stack-neutral CORE. Every item below applies to **any Astro project** — do not duplicate CORE items here, and do not add project-specific deployment targets or domain models (those belong in PROJECT).

---

### Project structure

Organize by Astro's conventional directory contract, extended for domain scale:

```
src/
  pages/          route-driven: .astro pages + **.ts/.js endpoints
  layouts/        shared page shells (<html>, header/footer, slot regions)
  components/     .astro components + framework (React/Vue/Svelte) islands
  content/        content collections + config.ts schema
  middleware.ts   request-level middleware (SSR only)
  env.d.ts        ImportMetaEnv / App.Locals type declarations
```

For a project of meaningful size, group `components/` and `content/` by domain area (`components/checkout/`, `content/blog/`) rather than by technical type (`components/buttons/`, `components/cards/`) once the flat directory exceeds a handful of files per concern — the same domain-cohesion principle PACK:django applies to app boundaries. Reject a design that scatters one feature's components, content schema, and endpoints across unrelated directory groupings.

---

### Rendering-mode architecture: the project-level decision

`astro.config.mjs`'s `output` setting is a project-wide architectural decision, not a per-page implementation detail — resolve it in the ADR before technical-design proceeds:

1. **`output: 'static'`** — the correct default when the majority of routes are prerenderable (marketing sites, docs, blogs, portfolios). A handful of routes needing request-time data are handled via per-route `export const prerender = false` (hybrid behavior) rather than forcing the whole project to `server`.
2. **`output: 'server'`** — required when the majority of routes are inherently per-request (an authenticated dashboard, a personalized app). Individual genuinely-static routes (`export const prerender = true`) opt out on a per-route basis.
3. **Decision rule:** count routes by data dependency (build-time-only vs. request-time) during the ADR, not by guessing — a project that is 90% static content with one login-gated settings page should default `static`+opt-outs, not `server`. Choosing `server` when `static` (with opt-outs) would serve the actual route mix forfeits CDN-edge caching and adds adapter cold-start latency to every route, including the ones that never needed it.

Record the decision and the route-count justification in the ADR — this is exactly the class of decision PACK:django's HTMX-vs-DRF-vs-SPA decision tree makes explicit for its own stack.

---

### Adapter selection

`output: 'server'`/`'hybrid'` requires an adapter; treat adapter choice as inseparable from deployment topology, and resolve both together in the same ADR:

- **`@astrojs/node`** (standalone or middleware mode) — pairs with self-hosted/containerized deployment (a Docker Compose topology comparable to PACK:django's gunicorn+Compose stack, or a bare VM). Choose when the project needs full Node API access at runtime (filesystem, long-running connections, native modules) or already owns deployment infrastructure.
- **`@astrojs/vercel`** — pairs with Vercel deployment. Offers a serverless-functions mode (full Node runtime, cold starts) and an edge-functions mode (V8 isolate runtime, near-zero cold start, but no Node `fs`/many `process` APIs and a smaller compatible-package surface). The ADR must state which mode and confirm every server-side dependency the design will need is compatible with the chosen runtime *before* technical-design proceeds — discovering an incompatible dependency (e.g. a native Node addon) after adapter selection forces a costly adapter change late.
- **`@astrojs/cloudflare`** — pairs with Cloudflare Pages/Workers deployment. Runs exclusively on the Workers runtime (no Node `fs`, a different `crypto`/`stream` surface, execution-time and memory ceilings per the Workers plan tier). Reserve for projects deploying to Cloudflare's edge network; audit dependency compatibility with the same rigor as the Vercel-edge case.
- **Static-only projects** (`output: 'static'` with no SSR routes) need no adapter — deploy the build output to any static host/CDN. Do not add an adapter "for future flexibility" when the project has no current SSR requirement; it adds a runtime dependency and a deployment-topology constraint for no present benefit.

---

### Islands architecture: state and framework-plurality decisions

Astro allows multiple UI frameworks (React, Vue, Svelte) to coexist as islands on the same page — this flexibility is an architectural liability if unmanaged:

- **Pick one framework as the project default** for new interactive components unless there is a specific, stated reason to introduce a second (e.g. adopting a pre-built component library only available for a different framework). Each additional framework adds its own runtime to the client bundle for pages using it, and its own islands-state-sharing mechanism.
- **Cross-island shared state** (a cart total updated by one island and displayed by another) requires a framework-agnostic store — the ADR should name the mechanism (nanostores is Astro's documented cross-framework option) once, so every subsequent feature reuses it rather than each island inventing its own approach.
- **Server-fetched vs. client-fetched data for islands:** the default architecture is server-side fetch in the parent `.astro` file's frontmatter, passed as props — this avoids a client-side loading state entirely for data available at render time. Reserve client-side fetching inside an island for genuinely request-time-personalized data unavailable to the parent's render context. A design that defaults every island to client-side fetching forfeits this and adds unnecessary loading states.

---

### Content collections as the data-modeling layer

For any project with structured, author-managed content (as opposed to purely dynamic/database-backed data), content collections are the correct architectural primitive — not a hand-rolled `fs`-reading utility, and not a full CMS/database for content that doesn't need one:

- Choose content collections when content is authored by developers or trusted contributors via the repository (Markdown/MDX/JSON committed to `src/content/`).
- Choose a database + admin UI (or a headless CMS) when content must be editable by non-technical users at runtime without a deploy, or when the volume/query needs (full-text search across thousands of entries, complex filtering) exceed what build-time-loaded collections handle well.
- A project can use both — content collections for genuinely static editorial content, a database for user-generated or frequently-changing data — but the ADR must state which data belongs to which system; a design that is ambiguous about this boundary leads to duplicated content-modeling effort.

---

### Middleware architecture

Middleware (`src/middleware.ts`) only executes for SSR-rendered requests — it is invisible to prerendered/static output served directly by the host/CDN. This has an architectural consequence: any cross-cutting concern implemented in middleware (auth gating, request logging, header injection, i18n locale detection) is **only enforced on routes that are actually SSR-rendered**.

- If the ADR's threat model or design requires a control (auth, security headers) to apply project-wide including static routes, middleware alone cannot deliver that — the control must additionally be enforced at the CDN/host/reverse-proxy layer for prerendered output, or the relevant routes must be forced into SSR. State this explicitly; it is a common architectural gap when a project mixes rendering modes and assumes middleware provides blanket coverage.
- `sequence(a, b, c)` composition order matters when middleware functions have dependencies (an auth-check middleware must run before a middleware that reads `context.locals.user`) — the ADR should state the required ordering when more than one middleware function is introduced.

---

### Critiquing the architecture: Astro-specific checklist

- Is the project-wide `output` mode justified by an actual route-mix count, not a default guess?
- Is the adapter choice paired with an explicit deployment-topology decision, and has runtime-compatibility (Node APIs vs. edge/Workers constraints) been checked for every server-side dependency the design anticipates?
- Is a single default UI framework for islands named, with cross-island state-sharing mechanism specified if more than one interactive component needs shared state?
- Is the content-collections-vs-database boundary stated for every category of data the project handles?
- Does the design account for middleware's SSR-only execution scope wherever a cross-cutting control is assumed to apply project-wide?

"Astro will figure it out" is never an acceptable architectural answer to a rendering-mode or adapter question — name the specific mode, adapter, and runtime constraint, and where each is enforced.
