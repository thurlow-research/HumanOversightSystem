"""Tests for change_classifier.py — the independent diff classifier that backs
the oversight-evaluator's #74 (N/A verification) and #75 (structural override)
compliance checks.

Detection functions are pure (operate on parsed name_status + added-lines), so
most tests feed synthetic inputs. One integration test exercises the real
git-diff parsing in a throwaway repo.
"""

import importlib.util
import subprocess
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "change_classifier",
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "change_classifier.py",
)
cc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cc)


# ── #75: structural-override signatures ──────────────────────────────────────
def test_new_external_dependency_is_structural():
    ns = [("M", "requirements.txt")]
    added = {"requirements.txt": ["celery==5.3"]}
    sigs = {s["signal"] for s in cc.detect_structural(ns, added)}
    assert "new-external-dependency" in sigs


def test_new_permission_state_is_structural():
    ns = [("M", "app/views.py")]
    added = {"app/views.py": ['@permission_required("app.view")']}
    sigs = {s["signal"] for s in cc.detect_structural(ns, added)}
    assert "new-permission-or-auth-state" in sigs


def test_new_route_is_structural():
    ns = [("M", "app/urls.py")]
    added = {"app/urls.py": ['    path("new/", views.home),']}
    sigs = {s["signal"] for s in cc.detect_structural(ns, added)}
    assert "new-user-flow-or-route" in sigs


def test_new_template_file_is_structural():
    ns = [("A", "app/templates/app/checkout.html")]
    added = {"app/templates/app/checkout.html": ["<html></html>"]}
    sigs = {s["signal"] for s in cc.detect_structural(ns, added)}
    assert "new-user-facing-surface" in sigs


def test_modified_template_is_not_a_new_surface():
    # A *modified* (not added) template is not a new surface on its own.
    ns = [("M", "app/templates/app/checkout.html")]
    added = {"app/templates/app/checkout.html": ["<p>tweak</p>"]}
    sigs = {s["signal"] for s in cc.detect_structural(ns, added)}
    assert "new-user-facing-surface" not in sigs


def test_new_state_enum_is_structural():
    ns = [("M", "app/models.py")]
    added = {"app/models.py": ["    status = models.CharField(choices=STATUS_CHOICES)"]}
    sigs = {s["signal"] for s in cc.detect_structural(ns, added)}
    assert "new-user-facing-state" in sigs


def test_benign_change_has_no_structural_signal():
    ns = [("M", "app/utils.py")]
    added = {"app/utils.py": ["    return x + 1  # fix off-by-one"]}
    assert cc.detect_structural(ns, added) == []


# ── #74: reviewer-domain detection ───────────────────────────────────────────
def test_template_change_touches_ui_a11y_security():
    ns = [("M", "app/templates/app/x.html")]
    touched = cc.detect_domains(ns, {})
    assert touched.get("ui", {}).get("touched")
    assert touched.get("a11y", {}).get("touched")
    assert touched.get("security", {}).get("touched")


def test_privacy_domain_by_path():
    ns = [("M", "accounts/models.py")]
    touched = cc.detect_domains(ns, {})
    assert "privacy" in touched


def test_ops_domain_by_added_line():
    ns = [("M", "app/tasks.py")]
    added = {"app/tasks.py": ["@shared_task", "def sync(): pass"]}
    touched = cc.detect_domains(ns, added)
    assert "ops" in touched


def test_infra_only_change_does_not_touch_security():
    # An infra-only diff must let security be legitimately N/A.
    ns = [("M", "docker-compose.yml")]
    touched = cc.detect_domains(ns, {})
    assert "infra" in touched
    assert "security" not in touched


def test_roles_scope_limits_detection():
    # Perf optimization: only the requested (N/A'd) roles are evaluated.
    ns = [("M", "app/templates/app/x.html")]
    touched = cc.detect_domains(ns, {}, roles=["privacy", "reliability"])
    assert touched == {}  # neither privacy nor reliability matched, ui/a11y not checked


# ── integration: real git diff parsing ───────────────────────────────────────
def test_collect_diff_parses_added_lines(tmp_path):
    repo = tmp_path

    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "requirements.txt").write_text("django==4.2\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / "requirements.txt").write_text("django==4.2\ncelery==5.3\n")
    run("add", "-A")
    run("commit", "-qm", "change")

    # collect_diff shells out to git in cwd; run it from the repo dir.
    import os

    prev = os.getcwd()
    try:
        os.chdir(repo)
        ns, added, removed = cc.collect_diff("HEAD~1", "HEAD")
    finally:
        os.chdir(prev)
    assert ("M", "requirements.txt") in ns
    assert "celery==5.3" in added["requirements.txt"]
    assert "django==4.2" not in added["requirements.txt"]  # unchanged line not in added set
    # removed contains the original django line (replaced by both lines in the new file,
    # but since django==4.2 is still present in the new version, diff shows no removal
    # for it — only the new celery line is added). removed may be empty for this diff.
    assert isinstance(removed, dict)


# ── detect_tier_floor ─────────────────────────────────────────────────────────

def test_tier_floor_auth_path_gives_high():
    ns = [("M", "app/auth/views.py")]
    result = cc.detect_tier_floor(ns, {})
    assert result["tier_floor"] == "HIGH"


def test_tier_floor_payment_path_gives_critical():
    ns = [("M", "app/payment/views.py")]
    result = cc.detect_tier_floor(ns, {})
    assert result["tier_floor"] == "CRITICAL"


def test_tier_floor_financial_api_added_line_gives_critical():
    ns = [("M", "app/orders/views.py")]
    added = {"app/orders/views.py": ["stripe.PaymentIntent.create(amount=100)"]}
    result = cc.detect_tier_floor(ns, added)
    assert result["tier_floor"] == "CRITICAL"


def test_tier_floor_migration_gives_high():
    ns = [("A", "app/migrations/0002_add_user.py")]
    result = cc.detect_tier_floor(ns, {})
    assert result["tier_floor"] == "HIGH"


def test_tier_floor_plain_py_gives_medium():
    ns = [("M", "app/utils/helpers.py")]
    result = cc.detect_tier_floor(ns, {})
    assert result["tier_floor"] == "MEDIUM"


def test_tier_floor_framework_tooling_not_raised_by_line_rules():
    # The classifier's own source contains EmailField as a literal — must not self-match.
    ns = [("M", "scripts/oversight/change_classifier.py")]
    added = {"scripts/oversight/change_classifier.py": ["EmailField"]}
    result = cc.detect_tier_floor(ns, added)
    # FRAMEWORK_TOOLING — path exempt from path and added-line rules
    # app-logic also exempt; result should be LOW (no other file).
    assert result["tier_floor"] == "LOW"


def test_tier_floor_readme_only_gives_low():
    ns = [("M", "README.md")]
    result = cc.detect_tier_floor(ns, {})
    assert result["tier_floor"] == "LOW"


def test_tier_floor_evidence_populated():
    ns = [("M", "app/auth/login.py")]
    result = cc.detect_tier_floor(ns, {})
    assert len(result["evidence"]) >= 1
    assert result["evidence"][0]["rule"] in ("auth-path", "payment-path", "app-logic")


# ── detect_warranted_lanes ────────────────────────────────────────────────────

def test_warranted_lanes_requests_gives_reliability():
    ns = [("M", "app/services.py")]
    added = {"app/services.py": ["response = requests.get(url, timeout=5)"]}
    result = cc.detect_warranted_lanes(ns, added)
    assert "reliability" in result["warranted"]


def test_warranted_lanes_shared_task_gives_ops():
    ns = [("M", "app/tasks.py")]
    added = {"app/tasks.py": ["@shared_task", "def process(): pass"]}
    result = cc.detect_warranted_lanes(ns, added)
    assert "ops" in result["warranted"]


def test_warranted_lanes_password_field_gives_security():
    ns = [("M", "app/accounts/forms.py")]
    added = {"app/accounts/forms.py": ['password = forms.CharField(widget=forms.PasswordInput)']}
    result = cc.detect_warranted_lanes(ns, added)
    # Security domain is triggered by .py files (file_rx check in DOMAIN_RULES).
    assert "security" in result["warranted"]


def test_warranted_lanes_no_match_gives_empty():
    ns = [("M", "README.md")]
    result = cc.detect_warranted_lanes(ns, {})
    assert result["warranted"] == {}


def test_warranted_lanes_structure():
    ns = [("M", "app/tasks.py")]
    added = {"app/tasks.py": ["@shared_task"]}
    result = cc.detect_warranted_lanes(ns, added)
    assert "warranted" in result
    if result["warranted"]:
        first = next(iter(result["warranted"].values()))
        assert "by" in first
        assert "file" in first


# ── detect_structural_modifications ──────────────────────────────────────────

def test_structural_mod_tracked_doc_both_sides():
    # A technical design doc with both removals and additions → reported.
    ns = [("M", "docs/v0.4.0/TECHNICAL-DESIGN-foo.md")]
    added = {"docs/v0.4.0/TECHNICAL-DESIGN-foo.md": ["## New Section"]}
    removed = {"docs/v0.4.0/TECHNICAL-DESIGN-foo.md": ["## Old Section"]}
    result = cc.detect_structural_modifications(ns, added, removed)
    mods = result["doc_modifications"]
    assert len(mods) == 1
    assert mods[0]["file"] == "docs/v0.4.0/TECHNICAL-DESIGN-foo.md"
    assert "removed" in mods[0]["evidence"]
    assert "added" in mods[0]["evidence"]


def test_structural_mod_pure_addition_not_reported():
    # Only additions, no removals → not a modification.
    ns = [("M", "docs/v0.4.0/TECHNICAL-DESIGN-foo.md")]
    added = {"docs/v0.4.0/TECHNICAL-DESIGN-foo.md": ["## Authorization"]}
    removed = {}
    result = cc.detect_structural_modifications(ns, added, removed)
    assert result["doc_modifications"] == []


def test_structural_mod_readme_not_tracked():
    # README is not a tracked governance doc.
    ns = [("M", "README.md")]
    added = {"README.md": ["new line"]}
    removed = {"README.md": ["old line"]}
    result = cc.detect_structural_modifications(ns, added, removed)
    assert result["doc_modifications"] == []


def test_structural_mod_agent_file_tracked():
    # .claude/agents/*.md is in the tracked set.
    ns = [("M", ".claude/agents/coder.md")]
    added = {".claude/agents/coder.md": ["new instruction"]}
    removed = {".claude/agents/coder.md": ["old instruction"]}
    result = cc.detect_structural_modifications(ns, added, removed)
    assert len(result["doc_modifications"]) == 1


def test_structural_mod_contract_tracked():
    ns = [("M", "contract/OVERSIGHT-CONTRACT.md")]
    added = {"contract/OVERSIGHT-CONTRACT.md": ["## New section"]}
    removed = {"contract/OVERSIGHT-CONTRACT.md": ["## Old section"]}
    result = cc.detect_structural_modifications(ns, added, removed)
    assert len(result["doc_modifications"]) == 1


def test_structural_mod_result_structure():
    ns = [("M", "docs/specs/SPEC-foo.md")]
    added = {"docs/specs/SPEC-foo.md": ["added"]}
    removed = {"docs/specs/SPEC-foo.md": ["removed"]}
    result = cc.detect_structural_modifications(ns, added, removed)
    assert "doc_modifications" in result
    m = result["doc_modifications"][0]
    assert "file" in m
    assert "section" in m
    assert "evidence" in m
    assert "removed" in m["evidence"]
    assert "added" in m["evidence"]
