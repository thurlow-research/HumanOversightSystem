## Astro idiom depth for code review

This region adds Astro-framework correctness checks to PACK:node's JS/TS review depth and CORE's generic review criteria. Apply every item below **in addition to** PACK:node and CORE. Do not duplicate either here.

---

### Review framing: presume a defect exists

Approach an Astro diff assuming it contains at least one violation from the list below, not with an open-ended "does this look right?" pass. Work in two passes: (1) identify which rendering mode, hydration strategy, and data-access pattern the diff is using, then (2) audit it point-by-point against every item below. A verdict reached without first establishing which rendering mode a route actually runs under is unreliable — several findings below are only detectable once that is established.

---

### Hydration directive correctness

- A component with `onClick`/`onChange`/any DOM event handler, internal `useState`/reactive state, or a `useEffect`/lifecycle hook that has **no** `client:*` directive ships as inert HTML — the handlers never attach. This is a functionality bug, not a style nit; flag it as **blocking**.
- The inverse: a component with no interactivity (pure presentational markup) carrying a `client:load`/`client:idle`/`client:visible` directive ships unnecessary JS to every visitor. Flag as a finding — ask whether the directive is load-bearing.
- `client:only="<framework>"` skips SSR for that component entirely — verify this is intentional (a genuine browser-API dependency) and not a workaround for a hydration mismatch the diff should instead fix at the source.
- A directive mismatched to the component's actual urgency (`client:load` on a below-the-fold widget, `client:visible` on an above-the-fold critical control) is a performance finding — cite the component's position in the page and the directive's actual hydration timing.

---

### Rendering-mode / data-access mismatches

- Any `.astro` file reading `Astro.request.headers`, `Astro.cookies`, `Astro.clientAddress`, or `Astro.request.method` without `export const prerender = false` (on `hybrid`/`static` output) is a **blocking** finding — under prerendering these resolve to build-time defaults (or throw), not the values the code assumes; the bug is invisible in local dev under `server` output and only surfaces in a static/hybrid production build.
- An API endpoint (`src/pages/**.ts` exporting `GET`/`POST`/etc.) with no `export const prerender = false` on a `static`/`hybrid`-output project is a **blocking** finding for any endpoint reading `params`, `request`, or `cookies` — it will serve a single build-time-frozen response to every request in production.
- `getStaticPaths()` used on a route whose data is genuinely per-request (not enumerable at build time) is a design mismatch — flag it and ask whether the route should be SSR instead.

---

### `set:html` and raw markup injection

- `set:html={value}` where `value` is not from a trusted, sanitized, or statically-known source (markdown rendered through a sanitizing pipeline, a CMS field, a database column, request-derived data) is a **critical** XSS finding — see PACK:astro security-reviewer for the full exploit framing; a code-quality reviewer must still catch it, not defer entirely to the security pass.
- Prefer expression interpolation (`{value}`, which Astro escapes by default) over `set:html` wherever the value is plain text — `set:html` should be reserved for content that is genuinely pre-rendered HTML from a trusted pipeline (a markdown-to-HTML render step), never a shortcut for avoiding escaping.

---

### Content collections usage

- A route iterating `getCollection()` results without handling the empty-collection case (no `.length === 0` branch, no fallback UI) is a finding when the collection can legitimately be empty (a freshly-scaffolded blog, a filtered subset).
- Frontmatter fields accessed without going through the collection's Zod schema (e.g. a hand-parsed `entry.body` regex instead of `render(entry)` / the typed `entry.data`) duplicates validation the schema already provides and is a finding — request the schema-typed accessor instead.
- A `getStaticPaths()` that derives `params` from collection entries without slugifying/validating entry IDs that may contain URL-unsafe characters is a finding — verify the slug source is safe for direct use as a URL segment.

---

### Endpoint and middleware correctness

- An endpoint handler that does not type its parameter as `APIRoute` loses `params`/`request`/`cookies` typing — a finding when the file also uses any of those without explicit typing/validation.
- An endpoint returning a bare object/string instead of a `Response` (or Astro's typed helpers) either fails the build or silently serves a wrong content-type — **blocking** finding.
- Middleware (`src/middleware.ts`) with a code path that neither calls `next()` nor returns a `Response` is a **blocking** finding — that path hangs the request.
- Data written to `context.locals` in middleware without a corresponding `App.Locals` type declaration (`src/env.d.ts`) is a finding — downstream consumers get an implicit `any`.

---

### View transitions and scoped styles

- `<style>` blocks in `.astro` files are scoped to the component by default (a hashed class/attribute is added); a rule using `is:global` to bypass this must have a stated reason (a genuine global reset, a third-party widget's markup) — an unexplained `is:global` is a finding, since it silently reintroduces the cross-component leakage the scoping exists to prevent.
- Elements meant to persist across a view transition (the `<ClientRouter />`/`<ViewTransitions />` navigation, e.g. a persistent audio player or header) need a matching `transition:persist` (or `transition:name`) on both the outgoing and incoming page's element — a mismatched or missing `transition:name` produces a jarring re-mount instead of the intended persistence; flag when the diff's intent (per the design/spec) was persistence.

---

### Execution evidence for rendering-mode findings

A finding that depends on actual render-time behavior — a prerendered route serving stale build-time data, a hydration mismatch, a middleware hang — is stronger when grounded in the project's test/execution output (resolved from `config.sh`) than argued from reading the diff alone. Where a `blocking` finding in this region cannot be grounded in an actual build/run, say so explicitly.
