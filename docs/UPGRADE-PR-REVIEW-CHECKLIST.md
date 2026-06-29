# Upgrade PR review checklist

Use this when reviewing the PR produced by `hos_install.sh --pr` — especially a
**`--squash` adoption** (taking HOS's canonical CORE/PACK wholesale, e.g. a
consumer moving onto the v0.3.x layered base team). Ordered by risk. A squash
upgrade is **safe for everything the framework now ships and lossy for anything
project-specific it doesn't** — so the *deletions* in the diff, not the
additions, are the real review surface.

> Replace "your project's domain terms" below with your own model names, role
> names, and business-rule identifiers before you start.

---

## A. The installer behaved safely (30-second sanity)
- [ ] **PR exists; the base branch is untouched** — the upgrade is on the
  `hos-upgrade/<ref>` branch only; the base branch has no framework commits.
  *(Red flag: any framework change on the base branch — the `--pr` guard failed.
  Fixed in v0.3.1; on ≥ v0.3.1 this cannot silently happen.)*
- [ ] **`.hos-release`** records the expected tag, and **`config.sh`** has the
  expected `PACK=` value.
- [ ] **You ran the installer once per *repo*, not once per *role*.** How many
  upgrade PRs to expect depends on deployment topology, not on the number of
  roles. **Single-repo deployment** (Worker, Human, and Overseer all share one
  GitHub repo — the default the installer scaffolds, where `*_worker_root` and
  `*_overseer_root` point at the same path): **one PR is the entire upgrade** —
  do not open a separate PR per role. **Split-repo deployment** (each role in its
  own repo): run the installer in each repo and review one PR per repo. *(Red
  flag: trying to push three per-role branches into one shared repo — that's the
  push failure in #949/#950; a single-repo deployment needs exactly one PR.)*

## B. Data-loss review — read the *deletions* (the critical pass)
- [ ] **Every deleted agent block is framework-absorbed, not project-unique.**
  The removed lines are your old (often flat, marker-less) agent bodies. For
  each, ask: *is this check / instruction now present in the new `CORE` or
  `PACK:<name>` region?* If yes → fine. If it is genuinely project-specific and
  **not** reproduced anywhere → it is a real loss; lift it into that agent's
  `PROJECT` region before merging.
- [ ] **Domain-specific content didn't vanish silently** — search the deletions
  for your project's domain terms (model/entity names, role names, business-rule
  identifiers, account/identity values). Anything still operationally needed
  belongs in a `PROJECT` region.
- [ ] **`dep-mapper` (only replaced under `--force`):** confirm the generic
  `dep-mapper` + the pack's blast-radius depth covers what your version did.
  *(Red flag: your `dep-mapper` had stack-specific tracing — signals, middleware,
  templates — the generic one lacks. Drop `--force` for that file, or re-add the
  depth to PROJECT.)*

## C. Prune / orphans
- [ ] **`.hos-archive/` contains only expected removals** — framework files the
  new version folded or dropped (e.g. an agent merged into another).
  *(Red flag: a project-authored custom agent in the archive that HOS does not
  replace — that's a capability drop; restore it.)*

## D. Layering correctness
- [ ] **Agent count and regions are right** — packed agents carry
  `CORE` + `PACK:<name>` + `PROJECT`; CORE-only agents carry `CORE` + `PROJECT`;
  the oversight-layer agents are present.
- [ ] **`PROJECT` regions exist (even if empty)** — that is the seam your
  project-specific guidance goes into, and it survives every future upgrade.

## E. Project-owned files must be untouched
- [ ] **No changes to your project's own files** — design pack / design tokens,
  spec, application code, and the committed **audit log**. The upgrade should
  touch *only* framework files (`.claude/agents/`, `scripts/framework/`,
  `AGENTS.md`, `contract/`, `.github/`). *(Red flag: any app / design / spec file
  in the diff.)*
- [ ] **`.claude/settings.json` was *merged*, not overwritten** — your existing
  permissions are still present, with HOS's added.

## F. The equivalence bet — spot-check
- [ ] On the 2–3 deepest agents (e.g. `security-reviewer`, `unit-test`,
  `coder`), confirm the composed `CORE + PACK:<name>` reads as **richer than or
  equal to** what you had. This is the adoption acceptance bar — functional
  equivalence, not byte-identical — verified in practice on the diff.

---

## G. Consumer packs (REQ-DM-05, #275)

*This section applies when the upgraded project uses a consumer pack (`--pack <slug>`) in addition to, or instead of, a HOS-shipped base pack.*

- [ ] **dep-mapper depth resolution is correct.** The blast-radius tracing depth follows a three-layer model:
  1. *Base pack* (`PACK:django` or equivalent) — generic, stack-aware tracing. Lives in `packs/django/dep-mapper.md`.
  2. *Consumer pack* (`PACK:<slug>`) — project-specific tracing rules that extend the base. The consumer-pack layer is the more-specific layer; where it names a pattern, it governs. The author keeps the layers coherent — there is no automated conflict resolution based on file ordering.
  3. *PROJECT region* — one-off rules until a consumer pack is scaffolded; once `--scaffold-pack` runs, this content moves to `packs/<slug>/dep-mapper.md` and the PROJECT region becomes an empty stub.
  Confirm the tracing depth you expect is actually present (scan for the rules you care about in `dep-mapper.md` and in `packs/<slug>/dep-mapper.md`).

- [ ] **Consumer pack was resolved from consumer-local `packs/`**, not silently from HOS source.
  Look for the log line: `[pack] Resolved <slug> from consumer-local packs/ (not HOS-shipped)`.
  If you see `Resolved <slug> from HOS source (HOS-shipped)` for a slug that should be consumer-local, the `packs/<slug>/` directory was not found — check that it is committed and the slug name matches exactly.

- [ ] **Both a base pack and a consumer pack inject into dep-mapper** (if both are active).
  Open the installed `.claude/agents/dep-mapper.md` and confirm both markers are present:
  ```
  <!-- HOS:PACK:django:START -->   ← base pack region
  <!-- HOS:PACK:<slug>:START -->   ← consumer pack region
  ```
  If either is missing, the corresponding `packs/<name>/dep-mapper.md` body file may be absent — verify the pack directory contains a `dep-mapper.md` and re-run the installer (AC-DM-01).

---

### The one asymmetry to keep in mind
`--squash --force` is **safe for everything the framework absorbed** and **lossy
for everything it didn't**. Section B is where that line gets drawn, and the PR
diff is the only place it's visible — once merged, deleted project content is
gone from the working tree (recoverable from git history, but nobody goes
looking). Review the deletions.
