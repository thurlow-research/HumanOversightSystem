# bootstrap/ — the copy-to-machine bundle

This folder holds the small set of standalone scripts you copy to a machine to
get HOS running. **Everything else** — the agents, validators, gates, contract,
docs — is fetched from a validated **release** by `hos_install.sh`, never copied
by hand.

| Script | Scope | Run | Sudo? |
|---|---|---|---|
| `hos_bootstrap.sh` | **machine** — Python, ScanCode, gh, pip pkgs; delegates to `setup_clis.sh` for the agent CLIs | once per machine | may need it |
| `setup_clis.sh` | **machine** — Node + `claude`/`codex`/`agy` + browser auth (repo-independent) | once per machine (called by `hos_bootstrap.sh`) | no |
| `hos_install.sh` | **project** — fetches a release and scaffolds it into a target repo | once per project (and on release bumps) | **no** |

## Two-step flow

```bash
# 1. Once per machine — install prerequisites + agent CLIs:
bash bootstrap/hos_bootstrap.sh

# 2. Once per project — install HOS from the latest validated release:
bash bootstrap/hos_install.sh /path/to/your/project
#    pin a version:   bash bootstrap/hos_install.sh --release v0.3.0 /path/to/project
#    dev install:     bash bootstrap/hos_install.sh --local /path/to/project
```

## Why the split

- **Different lifecycles** — the machine is set up once; projects are installed
  repeatedly (and on every release bump).
- **Different privilege** — bootstrap may need `sudo` for system packages;
  install never escalates (it only copies files). `hos_install.sh` *checks*
  prerequisites and points you back here if they're missing.
- **Reproducibility** — `hos_install.sh` installs from a fetched, validated
  **release** by default, not from whatever happens to be on a local working
  copy (which, with batched validation, is not guaranteed shippable). The
  installed release tag is recorded in the target at `.hos-release`.

See `DECISIONS.md` for the design rationale (release-pinned install; bootstrap
vs. install separation).
