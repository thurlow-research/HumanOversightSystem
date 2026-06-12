#!/usr/bin/env bash
# expensive_gates_stub.sh — placeholder for project-specific expensive gates.
#
# This stage runs after the inner loop and before the cross-vendor panel.
# It is intentionally NOT implemented here because expensive gates are
# project-specific: end-to-end test suites, coverage thresholds beyond the
# 80%/75% unit-test gate, performance benchmarks, contract tests, etc.
#
# STATUS: 🔧 designed / planned — implement per-project.
#
# To implement for your project:
#   1. Copy this file to your project's scripts/oversight/gates/
#   2. Replace the echo below with your actual gate commands
#   3. Exit 0 on pass, exit 1 on failure (blocks pipeline)
#
# Called by oversight-orchestrator before opening a PR at MEDIUM+ risk.
# Example project-specific gates:
#   - pytest tests/e2e/ --timeout=120
#   - coverage report --fail-under=90
#   - python manage.py check --deploy
#   - docker compose run web python manage.py test --keepdb

set -euo pipefail

echo "⚠  expensive_gates_stub.sh: no expensive gates configured for this project."
echo "   This is a placeholder. See comments in this file to implement."
echo "   Proceeding without expensive gate checks."
echo ""
echo "   To suppress this warning, replace this file with your actual gate script."
exit 0
