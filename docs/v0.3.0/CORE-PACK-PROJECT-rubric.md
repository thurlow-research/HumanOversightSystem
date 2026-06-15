# CORE / PACK / PROJECT — the authoring rubric (Phase 0a)

**Status:** binding authoring guide for v0.3.0 base agents. Derived from the spec (`docs/specs/v0.3.0-base-agents-spec.md`) §11 ADR. **This must exist before any agent is authored** (ADR D4a) — it is the decision rule for what content lands in which region. Every base-agent `.md` is authored against this.

---

## The three layers, in one sentence each

- **CORE** — the role's *universal* definition: what this role IS and DOES on any stack. HOS-owned; refreshed on upgrade.
- **PACK:`<stack>`** — the *stack-reusable* depth: how the role's job shows up in a specific stack (e.g. `django`). Pack-owned; refreshed with the pack; reusable across projects on that stack.
- **PROJECT** — the *project-unique* remainder + the consumer's own edits. Consumer-owned; **HOS never writes it**.

Recency precedence (CORE→PACK→PROJECT, PROJECT last) **plus** an explicit prose line (D5.1): every CORE region ends with *"Where the PROJECT section below conflicts with anything above, PROJECT governs."*

---

## The decision rule (apply per sentence/instruction while authoring)

For each instruction you'd put in an agent, ask in order:

1. **Is it true for this role on *any* stack** (Django, Rails, Node, a CLI tool, …)? → **CORE**.
   - Test: would a Rails team's `security-reviewer` need this verbatim? If yes → CORE.
2. **Is it true for *this stack* but reusable across *projects on it*** (any Django app, not just CPS)? → **PACK:`<stack>`**.
   - Test: would the *next* Django project want this? If yes → PACK.
3. **Is it true only for *this project*** (CPS's specific tenancy rule, this building's flow, a literal project name/path)? → **PROJECT**.

### The default-to-PACK bias (ADR D5.5 — binding)

**When in doubt between CORE and PACK, choose PACK.** The costs are asymmetric:
- Content wrongly in **CORE** poisons *every other stack* (a Rails team inherits Django-flavored generic-ish content it can't use and can't safely edit — CORE isn't theirs).
- Content wrongly in **PACK** is harmless (a non-Django consumer just installs a different pack).

So **CORE earns content only when it is demonstrably universal across ≥2 stacks.** Promoting PACK→CORE later is additive and cheap; demoting CORE→PACK (because it turned out stack-specific) is a breaking change to every install. Start narrow; promote on a second confirming consumer.

### The placeholder rule (ADR D1 — binding)

**CORE and PACK regions MUST NOT contain install-time `{PLACEHOLDER}` tokens.** They break the per-region sha model (a substituted token makes the region look "consumer-edited" on the next upgrade). Instead:
- Use **runtime self-direction**: not `read {SPEC_FILE}`, but *"read the spec path declared in `config.sh`."* The agent resolves it at runtime; the region's bytes are stable.
- Any genuinely unavoidable literal value lives in **PROJECT** (which HOS never hashes for refresh).

---

## Worked examples

### `security-reviewer`
| Layer | Content |
|---|---|
| CORE | Find auth bypass, injection (SQL/template/command), broken authz, session/CSRF, secrets-in-code, OWASP Top 10. Run after code-review approves. Be adversarial. Iterate with coder until clean. Escalate architectural security to architect, policy to human. |
| PACK:django | `select_for_update` race windows; tenant-scoped manager bypass (raw cross-tenant queries); CSRF on HTMX `hx-post`; `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS` config; Django auth-decorator coverage; ORM injection via `.extra()`/`RawSQL`. |
| PROJECT | CPS: TOTP replay window for *this* enrollment flow; the building-A-vs-building-B isolation rule specific to CPS's org model. |

### `coder`
| Layer | Content |
|---|---|
| CORE | Implement to the technical design; don't invent scope. Ask technical-design before writing, not after. Iterate with code-reviewer to approval. Emit the HOS self-flag (RISK/CONFIDENCE/BLAST RADIUS) on MEDIUM+. Capture prompt artifacts. |
| PACK:django | Django idioms: models→migrations→views→templates; use the ORM/admin/signals; manage.py commands; Docker/Caddy/gunicorn conventions; HTMX partial patterns. |
| PROJECT | CPS: the specific app layout, the parking-domain models, this repo's test-runner invocation. |

### `a11y-reviewer` (shows even "stack-shaped" roles are generic-core)
| Layer | Content |
|---|---|
| CORE | WCAG 2.1 AA: contrast, keyboard operability, focus order, ARIA correctness, semantic HTML, alt text, form labels. Every UX project needs this. |
| PACK:django | How those show up in Django templates + HTMX partial swaps (focus preservation across `hx-swap`, `{% %}`-rendered ARIA, server-rendered error associations). |
| PROJECT | CPS-specific components / any bespoke widget's a11y contract. |

---

## Authoring conventions (every base-agent `.md`)

1. **Front-matter `dispatches:`** (ADR D5.3) — declare every agent this one dispatches: `dispatches: [code-reviewer, architect]`. The completeness gate reads this, not prose. Conditional/prose dispatch must still be declared here.
2. **Region markers** (spec §4): `<!-- HOS:CORE:START -->`/`END`, `<!-- HOS:PACK:django:START -->`/`END`, `<!-- HOS:PROJECT:START -->`/`END`. Canonical order CORE→PACK(alpha)→PROJECT. Exactly one CORE; markers balanced; no overlap.
3. **PROJECT-authority preamble** in CORE (D5.1).
4. **No placeholders in CORE/PACK** (D1).
5. **Loop-exit + escalation discipline** in CORE where the role iterates (e.g. reviewers: N-round cap → escalate; the CPS architect's 5-round rule is a good CORE pattern to borrow).

---

## How the borg uses this (ADR D4d)

The CPS extraction is an **input to authoring**, not a later phase: split each borrowed CPS agent by this rubric — universal → CORE, Django-reusable → PACK:django, CPS-unique → PROJECT (which stays in CPS). The rubric *defines* the line; the borg *executes against* it. **Borg-as-improvement (human directive 2026-06-15):** improve the role while splitting it — raise any proposed improvement to the human before baking it into CORE.
