# Setting Up the Agent Pipeline Framework in a New Project

This guide walks through applying the [your project] agent pipeline framework to a new project repository. The framework is the agent definitions, validation scripts, and oversight tooling — not the application code.

**Just want to get running?** See **[QUICKSTART.md](QUICKSTART.md)** (three commands). This guide is the full walkthrough.

For customization guidance after setup, see `docs/CUSTOMIZATION.md`.
For the agent roles and pipeline structure, see `docs/AGENTS.md`.

---

## Prerequisites

### Required
- **Claude Code** CLI or desktop app (authenticated)
- A project **git repository** — the framework is applied to a repo root
- **Python 3.10+**, **git**, **gh** (GitHub CLI) — installed by the machine bootstrap below
- **agy** (Antigravity/Gemini) + **codex** (OpenAI) CLIs — the cross-vendor reviewers (also installed by the bootstrap)

### Step 0 — Machine bootstrap (once per machine)

Get the bootstrap scripts from the latest release and run the machine bootstrap. **You do not clone the repo** — `hos_install.sh` fetches the validated framework from the release.

```bash
# Pull the bootstrap scripts (the only files you copy to a machine):
mkdir -p hos-bootstrap && cd hos-bootstrap
for f in hos_bootstrap.sh setup_clis.sh hos_install.sh; do
  curl -fsSLO https://github.com/ScottThurlow/HumanOversightSystem/releases/latest/download/$f
done && chmod +x *.sh

# (recommended) verify what you downloaded:
curl -fsSLO https://github.com/ScottThurlow/HumanOversightSystem/releases/latest/download/SHA256SUMS
shasum -a 256 -c SHA256SUMS      # or: sha256sum -c SHA256SUMS

# Install prerequisites + agent CLIs (may prompt for sudo and browser auth):
./hos_bootstrap.sh
```

Check availability when done:
```bash
python3 --version && gh --version && agy --version && codex --version
```

> Already have the repo cloned? The same scripts live in `bootstrap/` — run `bootstrap/hos_bootstrap.sh`.

---

## Step 1 — Install the framework into your project (from a release)

`hos_install.sh` fetches the **latest validated release** and scaffolds it into your target repo. It needs no sudo — it verifies prerequisites and points back to the bootstrap if any are missing.

```bash
# From the hos-bootstrap folder (or bootstrap/ in a clone):
./hos_install.sh --pack django /path/to/your-new-project
#   no stack depth:  ./hos_install.sh --no-pack            /path/to/your-new-project
#   pin a version:   ./hos_install.sh --release v0.3.0 --pack django /path/to/your-new-project
#   dev install:     ./hos_install.sh --local --pack django /path/to/your-new-project   (unvalidated)
```

It will:
1. Verify prerequisites (Python 3.10+, git, gh, agy/codex)
2. Fetch the validated release (gate: refuses anything that isn't a published release)
3. Scaffold the target: `.claude/agents/`, `scripts/`, `scripts/oversight/`, `AGENTS.md`, `contract/`, `audit/`, `.ai-local/` (SQC salt), `.github/`, `.gitignore`
4. Record the installed tag at the target's `.hos-release`

> **Re-running / updates:** safe to re-run — it skips files you've customized unless you pass `--force`. To move to a new framework version, re-run with `--release <tag>` (or just re-run for the latest).

### Pack selection

HOS ships a **canonical base agent team** (16 agents: pm-agent, architect, technical-design, coder, the 8 reviewers, unit-test, system-test, ops-designer, ux-designer). Each agent file is divided into layered regions — the consumer no longer needs to hand-roll the team from scratch.

**`--pack <name>`** installs the base team with stack-specific depth for the named pack. The only shipping pack today is `django`, which adds Django-depth content to 12 of the 16 agents (security-reviewer, unit-test, coder, code-reviewer, system-test, a11y, privacy, architect, technical-design, ui, ux, infra); the remaining 4 (pm-agent, ops-reviewer, ops-designer, reliability-reviewer) are CORE-only in all packs.

**`--no-pack`** installs the bare CORE layer without any stack depth. CORE is intentionally shallow — you will need to add stack idioms yourself in the PROJECT region of each agent. Use this only if no pack fits your stack.

The selected pack is recorded in `scripts/framework/config.sh` as `PACK=django` (or `PACK=none`). For the agent region model (CORE / PACK / PROJECT) and what this means for upgrades and customization, see **[CUSTOMIZATION.md](CUSTOMIZATION.md)**.

---

## Step 1b — Configure project-specific values

> **How configuration works:** `hos_install.sh` scaffolds the agent files with `{PROJECT_NAME}`/`{SPEC_FILE}`/`{DESIGN_PACK_DIR}` placeholders and substitutes any values already in `scripts/framework/config.sh`. On an **interactive** install it then runs the config tool (`scripts/framework/install.sh`) for you to generate/fill `config.sh` and substitute the rest — so one `hos_install.sh` run yields a fully-configured project (#87). In **non-interactive/CI** runs it skips that step (set values via env or `config.sh`, then re-run `--force`); pass `HOS_NO_CONFIG=1` to opt out of the config step. Re-run `scripts/framework/install.sh` any time to update values.

## Step 2 — Configuration values

During the install, you will be prompted for six values. These are saved to `scripts/framework/config.sh` and used by every framework script. The last two are also substituted directly into the copied agent files.

| Value | What it is | Example |
|---|---|---|
| `PROJECT_NAME` | Human-readable name — substituted into agent files | `"MyApp"` |
| `PROJECT_STACK` | Tech stack description for the reviewers | `"Rails 7 + PostgreSQL"` |
| `PROJECT_NON_AGENT_TOKENS` | Pipe-separated hostnames/services in your agent files that aren't agent names — the static checker needs these to avoid false positives | `"myserver\|mydb\|staging-host"` |
| `DESIGN_PACK_PATH` | Path to your design system doc, relative to repo root — included in AI review | `"docs/design-system/DESIGN.md"` or blank if none |
| `SPEC_FILE` | Path to your primary spec file — substituted into agent files that read the spec directly (`spec-red-team`, `ux-designer`) | `"Specs/SPEC-1.md"` |
| `DESIGN_PACK_DIR` | Path to your design pack directory — substituted into `ux-designer` | `"Specs/design-pack"` or blank if none |

**Placeholder substitution:** after copying agent files, `install.sh` automatically replaces `{PROJECT_NAME}`, `{SPEC_FILE}`, and `{DESIGN_PACK_DIR}` in every copied agent file with the values you provided. This means agent files work out of the box without manual editing.

Edit `scripts/framework/config.sh` directly at any time, or re-run `install.sh` to update values interactively.

---

## Step 3 — Add your design pack (if you have one)

`ux-designer` and `ui-reviewer` both require a design pack. If your project has a design system:

1. Copy or create your design pack directory (e.g., `Specs/design-pack/`).
2. At minimum, the pack needs:
   - `DESIGN.md` — design rules, color tokens, component specs, voice/tone
   - `css/tokens.css` — CSS custom properties for every design token
   - `style-guide.html` — rendered component reference (open in a browser)
   - `feedback-states.html` — error/warning/success/info states
3. Update the path references in `ux-designer.md` and `ui-reviewer.md` to match your actual path.
4. Set `DESIGN_PACK_PATH` in `config.sh` to point to your `DESIGN.md`.

If you have no design system yet, `ux-designer` will create one from scratch during the initial design audit.

---

## Step 4 — Verify the installation

Invoke the `framework-setup-validator` agent in Claude Code:

```
Invoke framework-setup-validator
```

It will run through this checklist and report anything missing:
- All required directories exist
- All required agent files are present (including consumer agents and the validator agents: `framework-validator`, `framework-setup-validator`, `doc-validator`, `spec-compliance-validator`, and `post-change-sweep`)
- Framework scripts are executable
- `config.sh` has non-placeholder values
- `agy` and `codex` CLIs are available (warns if not — validation still works without them, but AI review is skipped)
- The static validator script runs successfully
- Output directories (such as docs/pm, docs/architecture, docs/design) are writable by the agents

If everything is green: `framework-setup-validator` prints "Framework is correctly installed."

---

## Step 5 — Customize agents for your project

Before running the project start sequence, update these agents with project-specific content:

| Agent | What to update |
|---|---|
| `pm-agent` | Spec file paths (`Specs/SPEC-1-pilot.md` → your spec files); pilot scope description |
| `architect` | Stack description; deployment host/URL; ADR output path |
| `technical-design` | Stack-specific design items (replace Django/GiST/HTMX with your equivalents) |
| `coder` | Build order (replace §12 of SPEC-1 reference); stack conventions (replace Django idioms) |
| `ux-designer` | Design pack file paths |
| `ui-reviewer` | Design pack file paths; project-specific component rules |
| `infra-reviewer` | Canonical URL; deployment host; infra stack (replace Compose/Caddy checks if needed) |
| `deploy-verify` | Production URL; alias domains; backup paths |

See `docs/CUSTOMIZATION.md` for detailed guidance on each agent and what to change.

After customizing, validate:
```bash
bash scripts/framework/run_framework_validation.sh --static-only
```

---

## Step 6 — Run the project start sequence

With the framework installed and agents customized, invoke agents in this order before writing any code:

```bash
# In Claude Code, invoke each agent in sequence:

# 1. PM agent — spec review and human Q&A
# "Invoke pm-agent for initial spec review"
# Wait for pm-agent to complete Q&A and write docs/pm/CONFIRMED-REQUIREMENTS.md

# 2. UX designer — design pack audit
# "Invoke ux-designer for initial design audit"
# Wait for ux-designer to fill gaps and write docs/design/UX-DESIGN-READINESS.md
# pm-agent validates that the design pack faithfully represents product intent

# 3. Architect — technical architecture
# "Invoke architect for initial architecture review"
# Answer architect's questions; wait for docs/architecture/ADR-001-pilot.md

# 4. Ops designer — telemetry spec (SKIP if no ops complexity)
# "Invoke ops-designer to produce the telemetry spec"
# ops-designer reads spec + ADR and writes docs/ops/TELEMETRY-SPEC.md
# architect signs off on the spec
# Skip for CLI tools, libraries, or projects without background jobs,
# external integrations, or multi-service architecture

# 5. Technical design — detailed spec
# "Invoke technical-design to produce the technical design"
# Iterates with architect until approved; produces docs/design/TECHNICAL-DESIGN.md
```

**Gate:** Do not start build step 1 until `docs/design/TECHNICAL-DESIGN.md` is architect-approved.

---

## Step 7 — Validate before first commit

Before committing anything (including the customized agent files), run the full framework validation:

```bash
bash scripts/framework/run_framework_validation.sh
```

This runs four phases (no phase may be skipped without explicit human approval):
1. `check_agents_static.sh` — confirms agent file references are valid and escalation paths resolve
2. `validate_agents.sh` — agy and codex review the agent definitions for consistency and gaps
3. `validate_docs.sh` — documentation coverage check (omissions, stale claims)
4. `validate_spec_compliance.sh` — governance requirements compliance check

Fix any blocking findings before committing.

---

## Ongoing: before every commit

After any change to agent files, pipeline docs, or application code:

```bash
# See what needs reviewing:
bash scripts/framework/run_post_change_sweep.sh

# Then in Claude Code:
# "Run post-change sweep"
```

The sweep agent categorizes your diff and drives all relevant reviews (code-reviewer, security-reviewer, ui-reviewer, etc.) in the correct dependency order.

---

## Reference: directory structure after install

```
your-project/
├── .claude/
│   └── agents/                  ← 24 agent definition files (from consumer_agents.txt)
├── docs/
│   ├── AGENTS.md                ← pipeline documentation
│   ├── OVERSIGHT-RUNBOOK.md     ← operational runbook
│   ├── SETUP.md                 ← this file
│   ├── CUSTOMIZATION.md         ← customization guide
│   ├── pm/                      ← pm-agent output (created at project start)
│   ├── architecture/            ← architect output
│   └── design/                  ← technical-design + ux-designer output
├── scripts/
│   └── framework/
│       ├── install.sh           ← run to install or update
│       ├── config.sh            ← generated; your project-specific values
│       ├── check_agents_static.sh
│       ├── validate_agents.sh
│       ├── run_framework_validation.sh
│       └── run_post_change_sweep.sh
└── audit/
    └── oversight-log.jsonl      ← append-only audit trail
```
