# Release Planning

Forward-looking release plans for HOS development. Each file captures the theme, bucket rationale, feature list, triage criteria, and open decisions for a release.

| File | Release | Theme | Status |
|------|---------|-------|--------|
| [v0.4.0.md](v0.4.0.md) | v0.4.0 — Autonomous Worker | Make the loop truly autonomous | ✅ **Shipped** 2026-06-20 |
| [v0.4.1.md](v0.4.1.md) | v0.4.1 — Operational Polish | Fix what broke, stabilize what shipped | ✅ **Shipped** |
| [v0.5.0.md](v0.5.0.md) | v0.5.0 — Governance, Accuracy & Usability | Tighten governance, improve accuracy, fix usability gaps | ✅ **Shipped** 2026-07-13 |
| v0.5.1 — Patch | Bug/governance fixes to shipped v0.5.0 code — on the `release/0.5.x` branch | 🔧 **Maintenance** |
| [v0.6.0.md](v0.6.0.md) | v0.6.0 — Astro & JS Support | node + astro packs, JS/TS validator & gate parity | 🔄 **Active** (accelerated for tutelare.ai) |
| [v0.7.0.md](v0.7.0.md) | v0.7.0 — Quality | Measure and improve quality over time | Planning |
| [v0.8.0.md](v0.8.0.md) | v0.8.0 — Agility | Fully embrace agile | Planning (early) |

## Triage criteria (worker decision guide)

When a new issue is filed, triage it to the appropriate release:

| Release | Take if... |
|---------|-----------|
| **v0.5.1** | Bug or governance/security/accuracy gap in **shipped** v0.5.0 code — fail-open, regression, install failure. Lands on the `release/0.5.x` maintenance branch. |
| **v0.6.0** | Astro / JS-TS stack support — node/astro packs, JS validator or gate parity, pack `requires` resolution (epic #1029). The active feature line. |
| **v0.7.0** | Quality or reliability improvement that isn't blocking — measurement, MTTF certification, lean waste, quality ratchet. |
| **v0.8.0** | Agility improvement — reduces friction, improves throughput, pull-system flow, developer experience. Not blocking anything today. |
| **Backlog** | Nice-to-have with no clear theme fit, or requires human design decision before scoping. |

**Decision rule:** breaks/gap in shipped code → v0.5.1 (maintenance). Astro/JS stack work → v0.6.0. Quality measurement → v0.7.0. Agility/DX → v0.8.0.

## Conventions

- **Planning docs** (this directory) are forward-looking and evolve throughout the release.
- **Release notes** (`docs/releases/`) are backward-looking and frozen at ship time.
- The GitHub milestone is the machine-readable version; planning docs are the human-readable rationale.
- The worker updates planning docs when issues are filed, milestones change, or open decisions resolve.
- Humans author the theme and bucket structure. Workers fill in the issue table and triage new issues per the criteria above.

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
