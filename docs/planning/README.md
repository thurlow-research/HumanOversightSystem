# Release Planning

Forward-looking release plans for HOS development. Each file captures the theme, bucket rationale, feature list, triage criteria, and open decisions for a release.

| File | Release | Theme | Status |
|------|---------|-------|--------|
| [v0.4.0.md](v0.4.0.md) | v0.4.0 — Autonomous Worker | Make the loop truly autonomous | ✅ **Shipped** 2026-06-20 |
| [v0.4.1.md](v0.4.1.md) | v0.4.1 — Operational Polish | Fix what broke, stabilize what shipped | 🔄 **Active** |
| [v0.5.0.md](v0.5.0.md) | v0.5.0 — Quality | Measure and improve quality over time | Planning |
| [v0.6.0.md](v0.6.0.md) | v0.6.0 — Agility | Fully embrace agile | Planning (early) |

## Triage criteria (worker decision guide)

When a new issue is filed, triage it to the appropriate release:

| Release | Take if... |
|---------|-----------|
| **v0.4.1** | Blocking or severe — breaks existing v0.4.0 functionality, security vulnerability, consumer install failure, data loss risk. Ship fast. |
| **v0.5.0** | Quality or reliability improvement that isn't blocking — aligns with Quality theme (measurement, dashboards, stamp redesign, infrastructure hardening, governance). |
| **v0.6.0** | Agility improvement — reduces friction, improves throughput, pull-system flow, developer experience. Not blocking anything today. |
| **Backlog** | Nice-to-have with no clear theme fit, or requires human design decision before scoping. |

**Decision rule:** if it breaks something that shipped in v0.4.0 → v0.4.1. If it's new capability → v0.5.0 or v0.6.0 by theme match.

## Conventions

- **Planning docs** (this directory) are forward-looking and evolve throughout the release.
- **Release notes** (`docs/releases/`) are backward-looking and frozen at ship time.
- The GitHub milestone is the machine-readable version; planning docs are the human-readable rationale.
- The worker updates planning docs when issues are filed, milestones change, or open decisions resolve.
- Humans author the theme and bucket structure. Workers fill in the issue table and triage new issues per the criteria above.
