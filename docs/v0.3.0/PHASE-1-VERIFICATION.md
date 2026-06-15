# Phase 1 — End-to-end verification (PROVEN 2026-06-15)

The v0.3.0 layering install mechanism, proven through the real `hos_install.sh`
bash path (not just unit tests). Every three-way-upgrade path exercised:

| Path | How verified | Result |
|---|---|---|
| **first install / migration** | `--local` into a fresh repo | flat agents wrapped flat→CORE + empty PROJECT stub; schema-v2 manifest written ✔ |
| **idempotent (KEEP)** | re-install, identical template | zero churn, manifest byte-identical ✔ |
| **REFRESH** (HOS updated CORE, consumer unedited) | changed a source agent body, re-installed | consumer's installed CORE took HOS's new body ✔ |
| **PROJECT preserved across REFRESH** | injected a consumer rule into PROJECT, then REFRESHed CORE | **consumer PROJECT survived** the upgrade ✔ |
| **HARDSTOP** (consumer-edited CORE drift, no `--squash`) | edited installed CORE, re-installed | exit 4, **nothing written, no version stamp** (§4.3) ✔ |
| **`--squash`** | drift + `--squash` | drift→REFRESH (HOS's version taken), PROJECT untouched ✔ |
| **`--dry-run`** | with pending changes | prints planned actions, writes nothing ✔ |
| **DROP** (HOS removed a region) | unit-tested (plan_upgrade) | unedited→DROP, edited→HARDSTOP ✔ |

**The load-bearing guarantee holds:** HOS pushes CORE/PACK improvements; the
consumer's PROJECT region is never written. Built dogfood-style — agent pipeline
(architect→technical-design→coder→code-reviewer) **and** HOS's own gate inner-loop
(lint/type/validators) applied to every module. 132 framework tests green.

## Caveats / follow-ups (not blockers for the mechanism)
1. Base-agent templates are still **flat** (no markers yet — that's Phase 0b/2
   authoring); a forward-compat shim wraps them as CORE, a no-op once markers ship.
2. `validate()` not yet wired as a fail-closed gate before compose (TD §7.1).
3. The `--release` tarball-fetch path and `--pr` path with the new agent writes,
   and a genuine cross-release upgrade, were not exercised (need a real release).
4. The `dispatches:`/completeness gate (§6), git-clean migration precondition
   (§5.1), and newly-introduced-CORE-over-flat (§5.3) are not yet wired in.
