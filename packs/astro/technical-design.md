## Astro technical-design depth

This region adds Astro-stack design contract conventions to the stack-neutral CORE. Apply every item below when producing a technical design for an Astro project. Do not duplicate CORE items here.

---

### Rendering-mode specification per route

For every route (page or endpoint) in the design, state explicitly:

- **Mode** — prerendered (static) or server-rendered, and if the project's `output` is `hybrid`/mixed, the exact `export const prerender` value for that route.
- **Data dependency** — what the route reads that justifies the mode: build-time-only data (content collections, static config) justifies prerendering; request-time data (`Astro.request`, `Astro.cookies`, a session, query params affecting the response) requires SSR.
- **Revalidation** — for prerendered routes whose underlying content can change after build (a content collection updated via a rebuild-on-webhook pipeline, or an adapter feature providing revalidation), state the revalidation trigger and staleness tolerance. "Rebuilds on every deploy" is a valid answer but must be stated, not assumed.
- A route design that mixes build-time and request-time data sources (e.g. a mostly-static page with one personalized widget) should isolate the personalized part into a `client:*`-hydrated island or a nested SSR fetch, rather than forcing the entire route to SSR — state this decomposition explicitly so the coder doesn't default to the coarser, wasteful option.

---

### Adapter selection and deployment target

The `output: 'server'`/`'hybrid'` modes require an adapter (`@astrojs/node`, `@astrojs/vercel`, `@astrojs/cloudflare`, etc.) — the design must name it and justify the choice against the deployment target, not leave it as an implementation detail:

- **`@astrojs/node`** — self-hosted or containerized deployment (the project's own Docker/Compose infra, a VM, a platform expecting a standalone Node server). Correct when the project already owns its deployment infrastructure (compare to PACK:django's gunicorn/Compose topology) or needs long-running server processes, WebSocket support, or filesystem access at runtime.
- **`@astrojs/vercel`** — when the project deploys to Vercel; supports both serverless functions and (where enabled) edge functions. State which of the two the design targets — edge functions run on a constrained runtime (no full Node APIs, e.g. no `fs`) and any server code relying on Node-only APIs must avoid the edge runtime or be redesigned.
- **`@astrojs/cloudflare`** — when the project deploys to Cloudflare Pages/Workers; runs on the Workers runtime, which is even more constrained than Vercel edge (no Node `fs`, limited `process`, different `crypto` surface). A design targeting this adapter must audit every server-side dependency for Workers-runtime compatibility before the coder starts, not discover incompatibility at deploy time.
- State the CPU/memory/execution-time limits of the chosen target explicitly if the design includes any long-running server-side operation (a large data export, an image-processing endpoint) — serverless/edge targets impose hard execution-time ceilings that a Node-hosted deployment does not.

---

### Islands and hydration contract

For every interactive component the design introduces, specify:

- The `client:*` directive (see PACK:astro ux-designer for the UX reasoning) as part of the component's design contract, not left to the coder's judgment at implementation time.
- Whether the component needs any data fetched server-side and passed as props (the common pattern: fetch in the parent `.astro` frontmatter, pass as a prop to the island) vs. fetched client-side after hydration (needed when the data is genuinely request-time-personalized in a way the parent page's rendering mode doesn't already provide) — state which, since it determines whether the component needs its own loading state.
- Any shared client-side state spanning multiple islands (e.g. a cart total shown in a header island and updated by a product-page island) requires a state-sharing mechanism (nanostores is Astro's documented recommendation, or a framework-native store if all islands share one UI framework) — name the mechanism in the design; independent islands cannot share React `useState`/Vue `ref` across component boundaries.

---

### Content collections schema design

For each content collection, specify:

- **Schema** — the Zod schema (`defineCollection({ schema: z.object({...}) })`) with every field's type, optionality, and any cross-field validation (e.g. a `publishDate` that must not be in the future for a scheduled-publish design).
- **Collection type** — `type: 'content'` (Markdown/MDX) vs. `type: 'data'` (JSON/YAML) — state which per collection, since it determines the authoring format contributors use.
- **Routing** — the `getStaticPaths()` mapping from collection entries to URL segments, including the slug derivation rule (from the filename, a frontmatter `slug` field, or a generated identifier).
- **Reference relationships** — where one collection references another (a blog post referencing an author collection), specify via the schema's `reference()` helper rather than a bare string ID the design leaves untyped.

---

### Endpoint API contract

For each `src/pages/**.ts` endpoint, apply the same rigor PACK:django's technical-design applies to Django views:

1. **Path and methods** — the route path (including dynamic segments) and which HTTP methods it handles.
2. **Auth requirement** — how the endpoint verifies the caller (a session cookie checked via middleware-populated `context.locals`, a bearer token, or explicitly public).
3. **Request contract** — the expected body shape (for `POST`/`PUT`), query params, and how validation failures are reported (status code + error body shape).
4. **Response contract** — the success response shape and status code, and every distinct error status the endpoint can return.
5. **Rendering mode** — confirm `export const prerender = false` is specified where the project's output mode requires it (see rendering-mode specification above) — an endpoint design that omits this is incomplete.

---

### Critiquing the technical design: Astro-specific checklist

When `technical-design` produces a design document for an Astro project, check every item in the CORE critique list **and**:

- Does every route state its rendering mode and the data-dependency justification?
- Is an adapter named, and does it match the stated deployment target's runtime constraints (Node-only APIs on an edge/Workers adapter is a design defect, not an implementation detail to catch later)?
- Does every interactive component specify a hydration directive as part of its contract?
- Do content collection schemas cover every field the design's data model requires, with cross-field validation stated where needed?
- Are shared-state mechanisms across islands named explicitly, not left implicit?

"Astro will handle it" is never an acceptable answer to a rendering-mode or adapter-runtime question — name the specific mechanism (adapter, directive, schema) and where it is enforced.
