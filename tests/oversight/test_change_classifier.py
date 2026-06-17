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
        ns, added = cc.collect_diff("HEAD~1", "HEAD")
    finally:
        os.chdir(prev)
    assert ("M", "requirements.txt") in ns
    assert "celery==5.3" in added["requirements.txt"]
    assert "django==4.2" not in added["requirements.txt"]  # unchanged line not in added set
