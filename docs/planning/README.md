# Release Planning

Forward-looking release plans for HOS development. Each file captures the theme, bucket rationale, feature list, triage criteria, and open decisions for a release.

| File | Release | Theme | Status |
|------|---------|-------|--------|
| [v0.4.0.md](v0.4.0.md) | v0.4.0 — Autonomous Worker | Make the loop truly autonomous | ✅ **Shipped** 2026-06-20 |
| [v0.4.1.md](v0.4.1.md) | v0.4.1 — Operational Polish | Fix what broke, stabilize what shipped | ✅ **Shipped** |
| [v0.5.0.md](v0.5.0.md) | v0.5.0 — Governance, Accuracy & Usability | Tighten governance, improve accuracy, fix usability gaps | ✅ **Shipped** 2026-07-13 |
| v0.5.1 — Patch | Bug/governance fixes to shipped v0.5.0 code — on the `release/0.5.x` branch | ☠️ **Dead — no further updates.** Closed to new triage (#1173); its last remaining issue (#1215) was moved to v0.6.0 on 2026-08-10, leaving it with zero open issues. Do not re-target work here. |
| [v0.6.0.md](v0.6.0.md) | v0.6.0 — Astro & JS Support | node + astro packs, JS/TS validator & gate parity | ✅ **Shipped** 2026-08-12. Closed to new triage — patches route to v0.6.1. |
| v0.6.1 — Stabilization | Bug/patch fixes to shipped v0.6.0 code (node/astro packs, JS/TS validators & gates) | 🔄 **Active** — the patch line for v0.6.0, same role v0.5.1 played for v0.5.0. |
| [v0.7.0.md](v0.7.0.md) | v0.7.0 — Quality | Measure and improve quality over time | Planning — see the v0.7.x line below |
| [v0.8.0.md](v0.8.0.md) | v0.8.0 — Agility | Fully embrace agile | Planning (early) |

## The v0.7.x line

v0.7 is split into themed point releases rather than one release.

**Numbering convention: even numbers are themes; odd numbers are reserved for stabilization and patch releases.** A new theme therefore takes an even slot, which may require renumbering the ones after it.

| Release | Theme | Plan |
|---------|-------|------|
| [v0.7.0 — Quality](https://github.com/thurlow-research/HumanOversightSystem/milestone/2) | Bugs, correctness, structural improvements, governance hardening | [v0.7.0.md](v0.7.0.md) |
| [v0.7.1 — Stabilization](https://github.com/thurlow-research/HumanOversightSystem/milestone/11) | Stabilization pass after v0.7.0 — defects and follow-ups it surfaces | — |
| [v0.7.2 — Sandboxing & Isolation](https://github.com/thurlow-research/HumanOversightSystem/milestone/12) | Sandboxed HOS processes, worker/overseer isolation, egress control, Human clone sync | — |
| [v0.7.4 — Testability](https://github.com/thurlow-research/HumanOversightSystem/milestone/18) | Everything testable and tested — invert the test regime, drive the exemption set to zero, classify the shell surface | [v0.7.4.md](v0.7.4.md) |
| [v0.7.6 — Design-Chain Panel (ADR-033)](https://github.com/thurlow-research/HumanOversightSystem/milestone/13) | Cross-vendor design-chain panel: spec + ADR + technical design reviewed together, pre-coding | — |
| [v0.7.8 — Governance Enforceability](https://github.com/thurlow-research/HumanOversightSystem/milestone/14) | Convert prose-only human clearance into enforceable artifacts; anti-gaming; reviewer stopping conditions | — |
| [v0.7.10 — Tooling, Identity & Validators](https://github.com/thurlow-research/HumanOversightSystem/milestone/15) | Mint/act/revoke wrapper family, PAT→GitHub App migration, API robustness, validator depth | — |
| [v0.7.12 — Docs, Drift & Observability](https://github.com/thurlow-research/HumanOversightSystem/milestone/16) | Documentation-reality drift detection, research index, operator dashboard | — |

> **Renumbered 2026-08-03.** `v0.7.4 — Testability` was inserted, cascading the themes after it up by two. Issues and comments written before that date cite the **old** numbers:
>
> | Cited as (pre-2026-08-03) | Now |
> |---|---|
> | v0.7.4 — Design-Chain Panel | **v0.7.6** |
> | v0.7.6 — Governance Enforceability | **v0.7.8** |
> | v0.7.8 — Tooling, Identity & Validators | **v0.7.10** |
> | v0.7.10 — Docs, Drift & Observability | **v0.7.12** |
>
> Milestone **ids** did not change, so links by id still resolve. Renaming a milestone keeps its issues attached; a cascade must run **top-down** (10→12 first) or GitHub rejects the duplicate title mid-way.

## Triage criteria (worker decision guide)

When a new issue is filed, triage it to the appropriate release.

**Precedence rule — priority and field-reports override theme match (#1387):**

1. **`priority:critical` always routes to the active release track** — the current
   active thematic milestone or its patch/stabilization companion (whichever is
   nearer to shipping), never deferred to a later thematic milestone on
   theme-match grounds alone. As of this writing the active track is v0.6.0
   (shipped, closed to new triage) with **v0.6.1** as its open patch line, so a
   `priority:critical` bug lands in v0.6.1 unless it's a v0.6.0-unrelated new
   capability, in which case it still takes the *nearest* open milestone, not
   the theme-correct-but-later one.
2. **`field-report` issues are biased toward the active patch/stabilization
   milestone** (v0.6.1 today; its future v0.7.1/v0.7.x-odd successors per the
   even=theme/odd=stabilization convention above) when the fix is **isolated and
   minor** — small, contained, doesn't require redesigning already-shipped
   functionality. This is a bias, not an automatic rule: a field report that
   turns out to be a larger design gap still routes by theme as below.

Apply this precedence rule first; if neither clause applies, fall through to the
theme table:

| Release | Take if... |
|---------|-----------|
| **v0.6.1** | Bug/patch fix to already-shipped v0.6.0 code — node/astro packs, JS/TS validator or gate parity, pack `requires` resolution (epic #1029). The role v0.6.0 played while active (absorbing this class of fix) now belongs to v0.6.1; v0.6.0 itself is closed to new triage. Also takes any `priority:critical` bug or isolated/minor `field-report` fix per the precedence rule above, regardless of theme. |
| **v0.7.0** | Quality or reliability improvement that isn't blocking — measurement, MTTF certification, lean waste, quality ratchet. Also: general governance/security/accuracy gaps not specific to shipped v0.6.0 code (the role v0.6.0 played while it was the active development line), and autonomous worker/overseer finalization (e.g. sandbox hardening). |
| **v0.7.4** | Test-regime work — coverage/mutation scope, test-exemption accounting, shell→Python migration of decision logic, or a CI gate that enforces any of it. See [v0.7.4.md](v0.7.4.md). |
| **v0.8.0** | Agility improvement — reduces friction, improves throughput, pull-system flow, developer experience. Not blocking anything today. |
| **Backlog** | Nice-to-have with no clear theme fit, or requires human design decision before scoping. |

**v0.5.1 is dead — closed to new triage and receiving no further updates (#1173).** No decision rule above may select it. This isn't just a triage preference: until #1173's worker milestone-eligibility fix lands (`milestone == active` → `milestone <= active`), any issue left in v0.5.1 is permanently unreachable to the autonomous worker the moment the active milestone moves past it — exactly what stranded #1166, #1155, and (until 2026-08-10) #1215. Treat v0.5.1 as closed for good; if it ever needs one more fix, that requires explicit human authorization of a maintenance-branch exception, not a milestone re-open.

**v0.6.0 is shipped (2026-08-12) — closed to new triage.** A bug found today in v0.6.0's own delivered code (node/astro packs, JS/TS validators, gates) routes to **v0.6.1**, its patch line — not back to v0.6.0. This mirrors the v0.5.0 → v0.5.1 pattern; unlike v0.5.1, v0.6.1 is not dead and stays open to absorb this work (subject to the same #1173 milestone-eligibility caveat above once the active line moves past it).

**Decision rule:** `priority:critical` → active release track (v0.6.1 today), regardless of theme. Isolated/minor `field-report` fix → biased toward v0.6.1. Otherwise: bug in shipped v0.6.0 code → v0.6.1. Testability, coverage scope, or shell→Python logic migration → v0.7.4. Quality measurement, general governance/security gaps, or worker/overseer finalization → v0.7.0. Agility/DX → v0.8.0.

**Scope of triage:** only issues filed **without** a milestone are triaged (worker Step 0). Issues that already carry a milestone are left as-is — corrections made here are stable and won't be re-triaged on a later cycle.

## Conventions

- **Planning docs** (this directory) are forward-looking and evolve throughout the release.
- **Release notes** (`docs/releases/`) are backward-looking and frozen at ship time.
- The GitHub milestone is the machine-readable version; planning docs are the human-readable rationale.
- The worker updates planning docs when issues are filed, milestones change, or open decisions resolve.
- Humans author the theme and bucket structure. Workers fill in the issue table and triage new issues per the criteria above.
- **A point release does not require a planning doc.** The milestone description carries the theme; a doc is added when the release needs bucket rationale, sequencing, or open decisions recorded. Rows marked `—` above are intentionally doc-less for now.

## Active milestone config

The worker's active target milestone is **not** hardcoded in any prompt. It is
set in `~/.config/hos/projects.conf` as `<project>_target_release=<title>` (e.g.
`hos_target_release=v0.6.0`). `bin/hos-cron` resolves the milestone number via
the REST API at each cycle start. To roll to the next release, change one line in
`projects.conf` — see `docs/CRON-SETUP.md §3` for the full procedure.

> **Operational note (2026-07-26):** the Astro work is milestone **v0.6.0 — Astro & JS Support**.
> The remote cron host is still keyed to the `v0.5.x` line, so to make the worker pick up the
> Astro issues, set `<project>_target_release=v0.6.0` in that host's `~/.config/hos/projects.conf`.
> That is a change on the machine running the cron — **not** in this repo, so I can't do it from here.
