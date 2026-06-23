#!/usr/bin/env bash
# config.sh — HumanOversightSystem framework source configuration.
#
# This is the config for running the validation suite on the HOS repo itself
# (self-governance). Consumer projects generate their own config.sh via install.sh.
#
# HOS is the framework source, not a consumer project. It contains oversight-specific
# agents (.claude/agents/) and documentation describing the full pipeline including
# consumer-project agents. EXTERNAL_AGENTS tells the static checker which agent names
# are valid but intentionally absent from .claude/agents/ here — they live in
# consumer project repos, installed via scripts/framework/install.sh.

# ── Project identity ─────────────────────────────────────────────────────────
export PROJECT_NAME="HumanOversightSystem"
export PROJECT_STACK="(framework source — not a specific application stack)"

# ── Non-agent tokens ─────────────────────────────────────────────────────────
export PROJECT_NON_AGENT_TOKENS=""

# ── External agents ──────────────────────────────────────────────────────────
# Pipeline agents documented in docs/AGENTS.md but installed only in consumer
# projects. They are valid escalation targets in framework agents (e.g.
# ux-designer escalates to ui-reviewer) but do not have .md files in this repo.
export EXTERNAL_AGENTS="pm-agent|architect|technical-design|coder|code-reviewer|security-reviewer|privacy-reviewer|ui-reviewer|a11y-reviewer|infra-reviewer|unit-test|system-test|deploy-verify"

# ── Design pack ───────────────────────────────────────────────────────────────
# HOS has no design pack — it's a framework, not a product.
export DESIGN_PACK_PATH=""

# ── Extra review files ────────────────────────────────────────────────────────
export EXTRA_REVIEW_FILES=""
