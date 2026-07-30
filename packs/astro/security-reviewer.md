## Astro security depth

This region adds Astro-framework attack surface to PACK:node's JS/TS security checks and CORE's generic security checklist. Apply every item below **in addition to** PACK:node and CORE. Do not duplicate either here.

---

### Review framing: presume a defect exists

Approach this checklist as an adversary hunting for one exploitable class below, not a checker confirming "looks secure." Establish which rendering mode (static/server/hybrid) and which trust boundary (build-time content vs. per-request input) the diff touches, then audit every applicable item below against an actual malicious input.

---

### XSS via `set:html`

- `set:html={value}` renders `value` as raw HTML with **no escaping** — any path where `value` originates from user input (a form field, a URL param, a request body), an external API response, or unsanitized CMS/database content is a **critical** finding (CWE-79). Astro's default expression interpolation (`{value}`) escapes automatically; `set:html` is the only place in a `.astro` template where that protection is deliberately bypassed.
- The only acceptable input to `set:html` is output from a sanitizing pipeline (a markdown renderer with a known-safe HTML allowlist, e.g. `rehype-sanitize`) or content the project treats as fully trusted (author-authored, not user-submitted). Verify the sanitizer is actually in the render path — `set:html={marked(userBio)}` without a sanitize step is still exploitable; markdown renderers do not sanitize raw HTML embedded in markdown source by default.
- Client-side equivalents (`dangerouslySetInnerHTML` in a hydrated React/Vue/Svelte island, or manual `innerHTML` assignment inside island component code) carry the identical risk and are not covered by PACK:node's generic checks unless the reviewer connects them explicitly — flag with the same severity.

---

### SSR endpoint input handling

- Every `src/pages/**.ts` endpoint handler (`GET`/`POST`/etc.) receives `params`, `request` (`await request.json()`/`.formData()`), and `cookies` as **untrusted external input** — the same trust boundary as an Express/Fastify route in PACK:node, not a framework-mediated safe zone. Missing validation on any of these before use in a query, filesystem path, shell command, or template render is the corresponding PACK:node finding class (injection, path traversal, command injection) applied to Astro's endpoint surface.
- `params.<dynamic segment>` from a `[id].ts`-style route is always `string | undefined` — an endpoint that passes it directly into an ORM/DB call, a filesystem read, or a redirect target without validating its shape (format, allowlist, existence check) is a finding at the severity the specific sink implies (SQL/NoSQL injection = critical, path traversal = high/critical, open redirect = medium/high).
- A redirect target built from `request.url` query params or `params` without validating against an allowlist of known-safe paths is an **open redirect** finding (CWE-601) — `Astro.redirect(userSuppliedUrl)` / `context.redirect(userSuppliedUrl)` must validate the target is a relative, in-app path or a pre-approved absolute URL.
- Endpoints that are reachable but unintentionally prerendered (missing `export const prerender = false`) serve one build-time-frozen response to every caller — not itself an injection bug, but flag it when the endpoint's apparent purpose (an auth check, a per-user response) implies it must run per-request; a security control that silently no-ops in production is a security finding, not just a functionality one.

---

### Secrets in client-shipped code

- Astro/Vite only exposes environment variables prefixed `PUBLIC_` to client-shipped (hydrated island) code — every other `import.meta.env.*` reference is server-only and stripped from the client bundle. A secret-shaped variable name (`*_SECRET`, `*_KEY`, `*_TOKEN`, `*_API_KEY`, a database URL, a signing secret) defined with the `PUBLIC_` prefix is a **critical** finding — it ships in the built client JS, readable by anyone who views source.
- Verify the inverse too: a genuinely public value (a publishable Stripe key, a public API base URL, an analytics ID) that is **not** `PUBLIC_`-prefixed will be `undefined` in client code — not a security bug, but confirm the diff's intent (client-needed vs. server-only) matches the prefix actually used, since a coder fixing an `undefined` bug by reflexively adding `PUBLIC_` to a secret is exactly how this class of leak happens in practice.
- Server-only code (an `.astro` frontmatter fence not hydrated to the client, an endpoint, middleware, `astro.config.mjs`) may read non-`PUBLIC_` env vars safely — do not flag those; the finding is specifically about values that reach client-hydrated island code or `set:html`/inline-script output.
- A `<script>` tag in an `.astro` file (not `is:inline`, processed by Vite) is bundled and shipped to the client exactly like an island's code — any `import.meta.env.*` reference inside it is subject to the same `PUBLIC_` rule. An `is:inline` script is emitted verbatim with no processing, so a template-interpolated secret (`<script is:inline>const key = "{serverSecret}"</script>`) is an even more direct leak — flag as **critical**.

---

### CSP for islands

- Hydrated islands load and execute framework runtime JS (React/Vue/Svelte) client-side — a project with a `Content-Security-Policy` header must account for the actual script sources Astro emits (its own hashed/bundled chunk URLs, plus `'self'` for same-origin builds) rather than a CSP copied from a non-Astro project's template.
- `set:html`-rendered content combined with a CSP that allows `'unsafe-inline'` for scripts defeats CSP's protection against the exact `set:html` XSS class above — if the project has (or should have) a CSP, verify `script-src` does not include `'unsafe-inline'` alongside any `set:html` usage that touches even partially-external content; prefer nonce-based or hash-based script allowances.
- Inline `<script is:inline>` tags are exempt from Vite's processing but are **not** exempt from CSP — a strict `script-src` CSP will block them unless a matching nonce or hash is applied. Verify the project's CSP strategy (nonce injection via middleware, or avoiding `is:inline` in favor of processed `<script>`) is actually consistent with what the diff adds.
- Third-party embeds inside islands (an ad script, an analytics snippet, a chat widget) loaded client-side introduce a script-src origin the CSP must explicitly allowlist — an island that adds a new third-party script without a corresponding CSP update is a finding when the project maintains a CSP.

---

### Execution evidence for exploit-dependent findings

XSS via `set:html`, SSR endpoint injection, and secret leakage are exploit-dependent — confirmed once a concrete malicious input or a built client bundle is shown to reach the sink. Before marking a **critical**/**high** finding in this region, prefer grounding it in an actual reproduction (a failing test, a built-output grep for the leaked secret, a REPL trace) over a static read of the diff. Where that grounding is unavailable, say so explicitly in the finding.
