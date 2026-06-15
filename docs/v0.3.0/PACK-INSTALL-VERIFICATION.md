# v0.3.0 Pack-Install End-to-End Verification

**Date:** 2026-06-15 · **Method:** real `bootstrap/hos_install.sh --local` runs into throwaway temp git targets (not the unit/install-path tests, not a composition simulation — the actual installer end-to-end). Proves the v0.3.0 pack layer installs and upgrades correctly with the real 16 base agents + 12 django-packs.

## Scenarios proven

| # | Scenario | Command | Result |
|---|---|---|---|
| 1 | **Fresh `--pack django` install** | `hos_install.sh --local --pack django T` | ✔ 24 agents installed (16 base + 8 oversight); **12 carry `PACK:django`, 4 CORE-only** (pm-agent, ops-reviewer, ops-designer, reliability-reviewer); `config.sh` records `PACK="django"`; `.hos-manifest` has 12 `PACK:django` rows |
| 2 | **PROJECT preserved on re-install** | edit a PROJECT region → re-run `--pack django` | ✔ exit 0; the consumer's PROJECT edit **survived**; CORE+PACK refreshed. The core upgrade promise (consumer edits are never clobbered) holds |
| 3 | **CORE drift → fail-closed** | edit an HOS-owned CORE region → re-run | ✔ **exit 4**, *"refusing the whole upgrade (nothing written, no version stamped)"* + the D2 remediation (`--squash` or move to PROJECT); other agents + `.hos-manifest` verified **byte-unchanged** (decide-all-then-act holds) |
| 4 | **`--no-pack` strip (B1/R2a)** | on the django target: `--no-pack` | ✔ exit 0; **#237 bare-core WARN** fires; `config.sh PACK` cleared (`django → (none)`); all **12 `PACK:django` regions stripped** via the removed-region sweep; the **PROJECT edit survived the strip** (only PACK dropped) |
| 5 | **Fresh greenfield `--no-pack`** | new target: `--local --no-pack` | ✔ exit 0; 24 agents, **0 PACK regions**, all 24 validate; #237 WARN fired |

## What this confirms

- **The headline claim is real, not simulated:** a clean `--pack django` install produces the full layered base team, so **CPS can adopt v0.3.0 by clean install and lose nothing**.
- **The fail-closed invariants the design↔architect loop fought for hold on a real install:** CORE-drift writes nothing (exit 4); the `--no-pack` strip is the B1/R2a fix working (the bug was `--no-pack` being silently ignored when a `PACK=` was recorded — now it wins, clears config, and drops the pack via the removed-sweep while keeping PROJECT).
- **The three-way merge is correct end-to-end:** PROJECT is never written; CORE/PACK REFRESH on a clean re-install; drift hard-stops; a pack→none strip DROPs cleanly.

## Not yet exercised (follow-ups, not blockers for the pack layer)

- `--pr` install path (greenfield + upgrade-via-PR) — separate verification.
- Multi-pack (`--pack a --pack b`) — permit-but-warn path (untested by design, spec §10.1).
- `--release <tag>` fetch path (this verification used `--local`).
- hos-dev-pack install (`--pack hos-dev`) — pending the pack's authoring.
