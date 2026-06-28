# Release Planning

Forward-looking release plans for HOS development. Each file captures the theme, bucket rationale, feature list, triage criteria, and open decisions for a release.

| File | Release | Theme | Status |
|------|---------|-------|--------|
| [v0.4.0.md](v0.4.0.md) | v0.4.0 — Autonomous Worker | Make the loop truly autonomous | ✅ **Shipped** 2026-06-20 |
| [v0.4.1.md](v0.4.1.md) | v0.4.1 — Operational Polish | Fix what broke, stabilize what shipped | ✅ **Shipped** |
| [v0.5.0.md](v0.5.0.md) | v0.5.0 — Governance, Accuracy & Usability | Tighten governance, improve accuracy, fix usability gaps | 🔄 **Active** |
| [v0.6.0.md](v0.6.0.md) | v0.6.0 — Quality | Measure and improve quality over time | Planning |
| [v0.7.0.md](v0.7.0.md) | v0.7.0 — Agility | Fully embrace agile | Planning (early) |

## Triage criteria (worker decision guide)

When a new issue is filed, triage it to the appropriate release:

| Release | Take if... |
|---------|-----------|
| **v0.5.0** | Blocking or severe — governance gap, accuracy regression, security vulnerability, consumer install failure, data loss risk, or usability issue severe enough to block productive use. Ship fast. |
| **v0.6.0** | Quality or reliability improvement that isn't blocking — aligns with Quality theme (measurement, MTTF certification, lean waste, quality ratchet). |
| **v0.7.0** | Agility improvement — reduces friction, improves throughput, pull-system flow, developer experience. Not blocking anything today. |
| **Backlog** | Nice-to-have with no clear theme fit, or requires human design decision before scoping. |

**Decision rule:** if it breaks something or is a governance/security/accuracy gap → v0.5.0. If it's quality measurement → v0.6.0. If it's agility/DX → v0.7.0.

## Conventions

- **Planning docs** (this directory) are forward-looking and evolve throughout the release.
- **Release notes** (`docs/releases/`) are backward-looking and frozen at ship time.
- The GitHub milestone is the machine-readable version; planning docs are the human-readable rationale.
- The worker updates planning docs when issues are filed, milestones change, or open decisions resolve.
- Humans author the theme and bucket structure. Workers fill in the issue table and triage new issues per the criteria above.

## Active milestone config

The worker's active target milestone is **not** hardcoded in any prompt. It is
set in `~/.config/hos/projects.conf` as `<project>_target_release=<title>` (e.g.
`hos_target_release=v0.5.0`). `bin/hos-cron` resolves the milestone number via
the REST API at each cycle start. To roll to the next release, change one line in
`projects.conf` — see `docs/CRON-SETUP.md §3` for the full procedure.
