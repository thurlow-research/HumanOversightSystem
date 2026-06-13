# HOS Quickstart

The fastest path to a HOS-governed project. (For the full walkthrough,
customization, and project-start sequence, see [SETUP.md](SETUP.md).)

You install HOS **from a validated release** — you don't clone this repo. You copy
three small bootstrap scripts to your machine; they fetch everything else.

---

## 1. Get the bootstrap scripts (once per machine)

```bash
mkdir -p hos-bootstrap && cd hos-bootstrap
for f in hos_bootstrap.sh setup_clis.sh hos_install.sh; do
  curl -fsSLO https://github.com/ScottThurlow/HumanOversightSystem/releases/latest/download/$f
done && chmod +x *.sh

# Verify what you downloaded (recommended):
curl -fsSLO https://github.com/ScottThurlow/HumanOversightSystem/releases/latest/download/SHA256SUMS
shasum -a 256 -c SHA256SUMS      # Linux: sha256sum -c SHA256SUMS
```

## 2. Set up the machine (once)

Installs Python 3.10+, ScanCode, gh, the analysis packages, and the agent CLIs
(`claude`/`agy`/`codex`). May prompt for sudo and browser sign-in.

```bash
./hos_bootstrap.sh
```

## 3. Install HOS into your project

Your project must be a git repo. This fetches the latest validated release and
scaffolds it in — no sudo.

```bash
./hos_install.sh /path/to/your-project
#   pin a version:  ./hos_install.sh --release v0.1.0 /path/to/your-project
```

That's it — your project now has the oversight agents, validators, gates, the
contract, and the audit trail. The installed version is recorded at
`/path/to/your-project/.hos-release`.

---

## What you get

| In your project | What it is |
|---|---|
| `.claude/agents/` | the oversight agents (risk-assessor, evaluator, orchestrator, …) |
| `scripts/oversight/` | risk validators + blocking gates |
| `scripts/` | the review runners (`run_panel.sh`, `run_second_review.sh`, `run_red_team.sh`, …) |
| `AGENTS.md`, `contract/` | the self-flagging protocol + the step manifest to fill in |
| `audit/` | the committed audit trail |

## Next

1. Fill in `contract/step-manifest.yaml` (your build steps + risk tiers).
2. Configure project values — see [SETUP.md Step 1b/2](SETUP.md) (and [CUSTOMIZATION.md](CUSTOMIZATION.md)).
3. Run the project-start sequence — see [SETUP.md Step 6](SETUP.md).

## Notes

- **No `curl | bash`.** HOS reviews what automation does to your code; piping a
  remote script straight into a shell would fail its own test. Download, verify
  `SHA256SUMS`, then run.
- **Already cloned the repo?** The same scripts live in `bootstrap/` — use those.
- **Updating?** Re-run `hos_install.sh` (latest) or `--release <tag>` to move
  versions. Re-running skips files you've customized unless you pass `--force`.
