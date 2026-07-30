## Node/JS-TS security depth

This region adds generic JS/TS-stack attack surface to the generic security checks in CORE. Apply every item below **in addition to** the CORE checklist. Do not duplicate CORE items here.

---

### npm supply-chain risk

- A new dependency added without checking its maintenance status, download count, and whether it ships install-time lifecycle scripts (`preinstall`/`install`/`postinstall`) is a **high** finding when the package is unfamiliar or low-usage — lifecycle scripts execute arbitrary code at install time with the installing user's privileges.
- The lockfile (`package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`) must be committed and its integrity hashes must not be stripped or regenerated without a corresponding intentional dependency change — a lockfile diff with no `package.json` change is a signal worth flagging (possible tampering or an unreviewed transitive bump).
- A scoped-but-unpublished-looking package name, or a name one character off a well-known package (typosquatting), is a **critical** finding — verify the exact package name against the intended dependency before approving.
- CI/build scripts that run `npm install`/`npm ci` should prefer `npm ci` (uses the lockfile exactly, fails on drift) over `npm install` in any reproducible build or deploy path.

---

### Prototype pollution

- Any recursive merge/assign helper (a hand-written deep-merge, a config-merging utility, `Object.assign` in a loop over user-controlled keys) that does not reject or skip `__proto__`, `constructor`, and `prototype` keys is a **critical** finding (CWE-1321) — an attacker-controlled JSON payload with a `__proto__` key can pollute `Object.prototype` for the entire process, affecting every object in the runtime.
- `JSON.parse` output merged directly into an existing object (e.g. request-body merged into a config or session object) without a denylist/allowlist on keys is the same class of finding — treat parsed JSON from any external source as hostile input for merge operations.
- Prefer `Object.create(null)` or a `Map` for any object used purely as a key-value store keyed by external input — it has no prototype chain to pollute.

---

### Dynamic code execution

- `eval()`, `new Function(...)`, `vm.runInNewContext`/`vm.runInThisContext` (Node's `vm` module) executing any string built from or influenced by user input, request data, or an external API response is a **critical** finding (CWE-95) — equivalent to SQL injection but for the JS runtime itself.
- `setTimeout`/`setInterval` called with a string argument instead of a function (implicitly invokes `eval`) is a finding even without direct user input, since it signals a pattern that is easy to make unsafe later.

---

### Command injection via child processes

- `child_process.exec()` or `execSync()` with any user-influenced string interpolated into the command is a **critical** finding (CWE-78) — require `child_process.execFile()`/`spawn()` with an argument array instead, which does not invoke a shell by default.
- `spawn()`/`execFile()` called with `{ shell: true }` reintroduces the same risk as `exec()` — flag any `shell: true` option where the command or arguments include external input.

---

### Secrets in bundled/client-reachable code

- Any environment variable read in code that is bundled for the browser (check the project's bundler config — Vite/webpack/esbuild inline `process.env.*` references at build time) must be verified as safe to ship publicly. A secret (API key, signing secret, database URL) referenced from client-bundled code is a **critical** finding — it ends up in the shipped JS, readable by anyone.
- Bundler-specific public-prefix conventions (e.g. a `PUBLIC_`/`VITE_`/`NEXT_PUBLIC_` env-var naming convention) exist precisely to draw this line — a secret-shaped variable name (`*_SECRET`, `*_KEY`, `*_TOKEN`) using the public prefix is a finding regardless of framework.

---

### Regular-expression denial of service (ReDoS)

- A regular expression with nested quantifiers or overlapping alternation (e.g. `(a+)+`, `(a|a)+`, `(.*)+`) applied to attacker-controlled input (a request body, header, query string) is a **high** finding (CWE-1333) — catastrophic backtracking on adversarial input can block the Node event loop, a single-threaded resource shared by every concurrent request.
- Prefer validating input length before regex evaluation, and prefer a linear-time library/pattern for user-facing validation (e.g. email/URL parsing) over a hand-rolled complex pattern.

---

### Path traversal via the filesystem

- Any `fs.readFile`/`fs.writeFile`/`fs.createReadStream` (or `path.join`) call where a path segment comes from user input without normalization and a containment check (resolve the path, verify it stays under the intended root directory) is a **high**/**critical** finding (CWE-22) depending on whether the operation reads or writes.

---

### Log and metrics output neutralization (CWE-117)

Dynamic values written into a structured-log record or a metrics emitter (Prometheus text exposition, a custom telemetry line) are an injection sink, not just an observability concern. Code that interpolates a header, env var, hostname, or any user/external-derived string into a log line or a metric label without stripping CR/LF or validating against the target format's metacharacters is a finding — unsanitized newlines enable log forging; unescaped label delimiters (`"`, `}`, `\`) can forge or malform emitted metric lines. Require a fail-closed validator (allowlist regex, or explicit escaping) before the value reaches the sink.
