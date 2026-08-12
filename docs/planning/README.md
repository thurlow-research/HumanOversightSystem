# Release Planning

Forward-looking release plans for HOS development. Each file captures the theme, bucket rationale, feature list, triage criteria, and open decisions for a release.

| File | Release | Theme | Status |
|------|---------|-------|--------|
| [v0.4.0.md](v0.4.0.md) | v0.4.0 — Autonomous Worker | Make the loop truly autonomous | ✅ **Shipped** 2026-06-20 |
| [v0.4.1.md](v0.4.1.md) | v0.4.1 — Operational Polish | Fix what broke, stabilize what shipped | ✅ **Shipped** |
| [v0.5.0.md](v0.5.0.md) | v0.5.0 — Governance, Accuracy & Usability | Tighten governance, improve accuracy, fix usability gaps | ✅ **Shipped** 2026-07-13 |
| v0.5.1 — Patch | Bug/governance fixes to shipped v0.5.0 code — on the `release/0.5.x` branch | ☠️ **Dead — no further updates.** Closed to new triage (#1173); its last remaining issue (#1215) was moved to v0.6.0 on 2026-08-10, leaving it with zero open issues. Do not re-target work here. |
| [v0.6.0.md](v0.6.0.md) | v0.6.0 — Astro & JS Support | node + astro packs, JS/TS validator & gate parity | ✅ **Shipped** 2026-08-12 |
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

When a new issue is filed, triage it to the appropriate release:

| Release | Take if... |
|---------|-----------|
| **v0.6.0** | Astro / JS-TS stack support — node/astro packs, JS validator or gate parity, pack `requires` resolution (epic #1029). Also: governance/security/accuracy gaps surfaced during active development (Human-clone beta, oversight-pipeline gaps) — the active line absorbs these while v0.5.1 is drained. |
| **v0.7.0** | Quality or reliability improvement that isn't blocking — measurement, MTTF certification, lean waste, quality ratchet. Also: autonomous worker/overseer finalization (e.g. sandbox hardening) that isn't required to unblock v0.6.0. |
| **v0.7.4** | Test-regime work — coverage/mutation scope, test-exemption accounting, shell→Python migration of decision logic, or a CI gate that enforces any of it. See [v0.7.4.md](v0.7.4.md). |
| **v0.8.0** | Agility improvement — reduces friction, improves throughput, pull-system flow, developer experience. Not blocking anything today. |
| **Backlog** | Nice-to-have with no clear theme fit, or requires human design decision before scoping. |

**v0.5.1 is dead — closed to new triage and receiving no further updates (#1173).** No decision rule above may select it — a bug or governance gap found today, even one that traces back to shipped v0.5.0 code, routes to v0.6.0 (the active line) unless a human explicitly authorizes a maintenance-branch fix. This isn't just a triage preference: until #1173's worker milestone-eligibility fix lands (`milestone == active` → `milestone <= active`), any issue left in v0.5.1 is permanently unreachable to the autonomous worker the moment the active milestone moves past it — exactly what stranded #1166, #1155, and (until 2026-08-10) #1215. Treat v0.5.1 as closed for good; if it ever needs one more fix, that requires explicit human authorization of a maintenance-branch exception, not a milestone re-open.

**Decision rule:** Astro/JS stack work or a governance/security gap in the active line → v0.6.0. Testability, coverage scope, or shell→Python logic migration → v0.7.4. Quality measurement or worker/overseer finalization → v0.7.0. Agility/DX → v0.8.0.

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
