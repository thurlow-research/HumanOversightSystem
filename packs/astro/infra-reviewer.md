## Astro deployment infrastructure depth

This region adds Astro-stack deploy/config checks to the generic infra checks in CORE and to PACK:node's Node-runtime checks. Apply every item below **in addition to** CORE and PACK:node. Do not duplicate either here.

---

### Static hosting vs. SSR runtime: matching the deploy config to `output`

The single most common Astro deployment defect is a mismatch between `astro.config.mjs`'s `output` setting and the actual hosting configuration:

- `output: 'static'` (no adapter) produces a plain `dist/` directory of HTML/CSS/JS — it must be deployed as a static site (any CDN, object-storage-plus-CDN, or static-hosting platform). A deploy pipeline that runs the SSR runtime entry point against a static-mode build is a **blocking** finding — that entry point does not exist under `output: 'static'`; verify the actual build output matches what the deploy step expects.
- `output: 'server'`/`'hybrid'` with an adapter produces a runtime entry point that must actually run as a long-lived (or per-invocation, for serverless) process — a deploy pipeline that copies `dist/` to a static host and serves it with no server process is **blocking**: every SSR/dynamic route 404s or serves the adapter's raw build artifacts instead of rendered pages.
- Verify the adapter installed in `package.json` (`@astrojs/node`, `@astrojs/vercel`, `@astrojs/cloudflare`, etc.) matches the actual deploy target — an `@astrojs/vercel` adapter build deployed to a plain Node host (or vice versa) produces an entry point the target's runtime does not know how to invoke.

---

### `@astrojs/node` deployments (self-hosted / containerized)

When the project uses the Node adapter, the deployment is architecturally a Node HTTP server — apply PACK:node's Node-runtime deployment checks plus:

- **Standalone mode** (`adapter: node({ mode: 'standalone' })`) produces a self-contained server started from a generated SSR entry point — the container/process manager (Docker `CMD`, systemd unit, PM2) must invoke this exact entry point. Verify it is not confused with the dev server or the preview server, neither of which is production-appropriate (dev is unoptimized and insecure; preview is documented as not hardened for production traffic).
- **Middleware mode** (`adapter: node({ mode: 'middleware' })`) integrates into an existing Express/Connect-style server the project already runs — verify the integration point (mounting the generated SSR handler) is actually wired in, and that static assets (`dist/client/`) are served separately (typically via a static-file middleware) since middleware mode does not serve them itself.
- The Node adapter respects `HOST`/`PORT` environment variables — verify the container/process manager sets these to match the reverse-proxy's expected upstream target, the same convention PACK:django's gunicorn `--bind` check applies.
- **Health check:** the `web` service (or equivalent) should define a healthcheck against a real route the SSR server serves (not a static asset) — a healthcheck hitting only `dist/client/` static files can report healthy while the SSR entry point has crashed.

---

### `@astrojs/vercel` deployments

- Confirm the runtime config (edge vs. the default serverless Node runtime) matches what the design/architecture ADR specified — an edge-runtime deployment silently fails at runtime (not build time, in some configurations) if server code imports a Node-only API (`fs`, certain `crypto` methods, native addons); verify the actual dependency tree was audited for edge compatibility, not assumed compatible.
- Environment variables must be configured in the platform's project settings (or its environment-injection integration) for every var the server-side code reads — a var present only in local `.env` and never configured in the deploy target is a silent production `undefined`, the deployment-config analog of PACK:django's `.env.example` completeness check.
- Verify any deploy-config override file (if present) does not hardcode a build command or output directory that has drifted from the project's actual `astro.config.mjs` output — a stale override is a recommendation finding worth flagging even though it doesn't block deploy today.

---

### `@astrojs/cloudflare` deployments

- The Workers/Pages runtime enforces its own execution-time and memory limits (plan-tier dependent) and lacks Node's `fs` module entirely — verify no server-side code path (including a transitive dependency) attempts filesystem access; this fails at request time, not build time, unless the project's CI includes a Workers-compatibility check.
- The Workers deploy config (`wrangler.toml` or the platform dashboard equivalent) must declare every binding the server code depends on (KV namespaces, D1 databases, R2 buckets, environment variables/secrets) — a binding referenced in code but absent from the config is a **blocking** deploy-config finding; it will throw at request time in production while working in local dev if the developer manually configured local bindings that were never added to the deploy config.
- Secrets for Cloudflare deployments must be set via the platform's secret-management command or dashboard, not committed as plaintext values in a config file's variable table — a secret-shaped value committed in plaintext is a **blocking** finding, the Cloudflare-specific instance of PACK:django's "no literal secrets in compose `environment:`" check.

---

### Static-hosting-specific checks (`output: 'static'`, no adapter)

- Verify the deploy target serves `dist/` with correct routing for Astro's static-build conventions — trailing-slash behavior (`trailingSlash` config) must match the host's routing rules, or deep links 404 (a common static-host misconfiguration: Astro may emit `about/index.html` where the host expects `about.html`, or vice versa).
- A custom 404 page (`src/pages/404.astro`) must be wired to the host's error-document configuration explicitly on hosts that don't auto-detect it — verify this is configured, not assumed.
- CDN cache headers/invalidation: a static deploy that doesn't invalidate the CDN cache on redeploy can serve stale HTML referencing old (now-404ing) hashed asset filenames — verify the deploy pipeline either invalidates on deploy or the host's default behavior (many static hosts version deploys atomically) makes this a non-issue, and state which applies.

---

### Node version floor

Astro (and every adapter above) requires the framework-wide Node floor (`>=22`, per PACK:node) at both build time and, for SSR deployments, runtime — verify the deploy target's configured Node runtime version (a platform-configured Node version, a Dockerfile `FROM node:` tag) meets the floor independently of what's pinned in `package.json engines.node`; a deploy platform silently defaulting to an older LTS is a **blocking** finding since the build may succeed while runtime behavior diverges from what was tested locally.

---

### Portability check (Astro-specific)

For an Astro project, portability means: given a fresh checkout on a new host with the correct Node version, a clean install and build produces a deployable `dist/` (static) or runtime bundle (SSR) with no manual state beyond environment variables. Flag any step that requires manual intervention not captured by this — for example: a build that reads from a local filesystem path outside the repo, a content collection that depends on a locally-cached external fetch with no documented refresh mechanism, or adapter configuration hardcoded to one environment's binding IDs (a Cloudflare KV namespace ID committed instead of injected per-environment).
