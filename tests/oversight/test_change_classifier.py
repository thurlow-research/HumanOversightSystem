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


# ── #121: structural MODIFICATION detection (Category A — auth/permission) ────
def test_modified_permission_decorator_is_flagged():
    ns = [("M", "app/views.py")]
    added = {"app/views.py": ["@permission_required('app.use')"]}
    removed = {"app/views.py": ["@permission_required('app.admin')"]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-permission-or-auth-state" in sigs


def test_removed_login_required_with_replacement_auth_is_flagged():
    # login_required removed, a weaker auth line added in its place on the same file.
    ns = [("M", "app/views.py")]
    added = {"app/views.py": ["    # @login_required removed", "@user_passes_test(lambda u: True)"]}
    removed = {"app/views.py": ["@login_required"]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-permission-or-auth-state" in sigs


def test_pure_move_of_auth_decorator_is_not_flagged():
    # Identical stripped auth line removed and re-added (a move/reorder) — not a change.
    ns = [("M", "app/views.py")]
    added = {"app/views.py": ["@permission_required('app.view')", "def newpos(): pass"]}
    removed = {"app/views.py": ["@permission_required('app.view')"]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-permission-or-auth-state" not in sigs


def test_auth_modification_in_framework_tooling_is_exempt():
    # binding 3: scripts/oversight/*.py is exempt — its literal patterns self-match.
    ns = [("M", "scripts/oversight/change_classifier.py")]
    added = {"scripts/oversight/change_classifier.py": ["    r'permission_required|login_required'"]}
    removed = {"scripts/oversight/change_classifier.py": ["    r'permission_required'"]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-permission-or-auth-state" not in sigs


def test_added_only_auth_is_not_a_modification():
    # An auth line added with nothing removed is condition-10's job, not a modification.
    ns = [("M", "app/views.py")]
    added = {"app/views.py": ["@permission_required('app.view')"]}
    removed = {"app/views.py": []}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-permission-or-auth-state" not in sigs


# ── #121: structural MODIFICATION detection (Category B — tracked docs) ───────
def test_modified_doc_structural_section_file_level_fallback():
    # No base/head ⇒ file-level fallback + over-detect keyword test on changed lines.
    f = "docs/specs/SPEC-42-thing.md"
    ns = [("M", f)]
    added = {f: ["User may approve the request."]}
    removed = {f: ["Admin authorization is required to approve."]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-doc-structural-section" in sigs


def test_modified_doc_non_structural_keywords_not_flagged():
    # A tracked SPEC doc edited with no structural keyword in the changed lines.
    f = "docs/specs/SPEC-42-thing.md"
    ns = [("M", f)]
    added = {f: ["The widget renders a blue button."]}
    removed = {f: ["The widget renders a green button."]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-doc-structural-section" not in sigs


def test_untracked_doc_not_flagged():
    f = "README.md"
    ns = [("M", f)]
    added = {f: ["Authorization is required."]}
    removed = {f: ["No authorization needed."]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert sigs == set()


def test_telemetry_spec_any_section_is_structural():
    f = "docs/ops/TELEMETRY-SPEC.md"
    ns = [("M", f)]
    added = {f: ["counter emitted on checkout"]}
    removed = {f: ["counter emitted on cart"]}
    sigs = {s["signal"] for s in cc.detect_structural_modifications(ns, added, removed)}
    assert "modified-doc-structural-section" in sigs


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


# ── #94: independent tier-floor re-derivation ────────────────────────────────
def test_auth_path_floors_high():
    floor, ev = cc.detect_tier_floor([("M", "app/auth/views.py")], {})
    assert floor == "HIGH"
    assert any("auth" in e["rule"].lower() for e in ev)


def test_payment_path_floors_critical():
    floor, _ = cc.detect_tier_floor([("M", "shop/payment/charge.py")], {})
    assert floor == "CRITICAL"


def test_migration_path_floors_high():
    floor, _ = cc.detect_tier_floor([("A", "app/migrations/0007_add_field.py")], {})
    assert floor == "HIGH"


def test_pii_added_line_floors_high():
    floor, _ = cc.detect_tier_floor(
        [("M", "app/models.py")], {"app/models.py": ["    email = models.EmailField()"]}
    )
    assert floor == "HIGH"


def test_financial_added_line_floors_critical():
    floor, _ = cc.detect_tier_floor(
        [("M", "svc/pay.py")], {"svc/pay.py": ["    intent = stripe.PaymentIntent.create()"]}
    )
    assert floor == "CRITICAL"


def test_plain_code_floors_medium():
    floor, _ = cc.detect_tier_floor(
        [("M", "app/utils.py")], {"app/utils.py": ["    return x + 1"]}
    )
    assert floor == "MEDIUM"


def test_non_code_floors_low():
    floor, _ = cc.detect_tier_floor([("M", "README.md")], {})
    assert floor == "LOW"


def test_empty_diff_floors_low():
    floor, ev = cc.detect_tier_floor([], {})
    assert floor == "LOW"
    assert ev == []


def test_highest_tier_wins():
    # An auth path (HIGH) and a payment path (CRITICAL) in one diff -> CRITICAL.
    floor, _ = cc.detect_tier_floor(
        [("M", "app/auth/views.py"), ("M", "shop/payment/charge.py")], {}
    )
    assert floor == "CRITICAL"


def test_framework_tooling_exempts_added_line_not_path():
    # Binding 3: a financial LITERAL inside a framework-tooling .py is exempted
    # (self-match, HOS#117) -> the added-line rule does not fire. With no other
    # signal the floor is MEDIUM (it is still application-code by extension).
    floor, ev = cc.detect_tier_floor(
        [("M", "scripts/oversight/foo.py")],
        {"scripts/oversight/foo.py": ["    account_number = 1"]},
    )
    assert floor == "MEDIUM"
    assert not any("added-line" in e["rule"] for e in ev)
    # But a financial PATH in the framework tree still floors CRITICAL (path rule
    # is NOT exempted).
    floor2, _ = cc.detect_tier_floor([("A", "scripts/oversight/payment_helper.py")], {})
    assert floor2 == "CRITICAL"


def test_tier_floor_evidence_shape():
    _, ev = cc.detect_tier_floor([("M", "app/auth/login.py")], {})
    assert ev and all({"rule", "file", "pattern"} <= set(e) for e in ev)


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
        # SPEC-121: collect_diff returns a 3-tuple (name_status, added, removed).
        ns, added, removed = cc.collect_diff("HEAD~1", "HEAD")
    finally:
        os.chdir(prev)
    assert ("M", "requirements.txt") in ns
    assert "celery==5.3" in added["requirements.txt"]
    assert "django==4.2" not in added["requirements.txt"]  # unchanged line not in added set
    # SPEC-121: a pure addition removes nothing — the removed channel is empty.
    assert isinstance(removed, dict)
    assert removed.get("requirements.txt", []) == []


def test_collect_diff_captures_removed_lines(tmp_path):
    """SPEC-121 AC-2: removed content lands in `removed`, the `--- a/` header does not."""
    repo = tmp_path

    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("@require_permission('admin')\ndef view(): pass\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / "app.py").write_text("@require_permission('user')\ndef view(): pass\n")
    run("add", "-A")
    run("commit", "-qm", "change")

    import os

    prev = os.getcwd()
    try:
        os.chdir(repo)
        ns, added, removed = cc.collect_diff("HEAD~1", "HEAD")
    finally:
        os.chdir(prev)
    assert "@require_permission('admin')" in removed["app.py"]
    assert "@require_permission('user')" in added["app.py"]
    # the `--- a/app.py` file header must never be captured as removed content
    assert not any(ln.startswith("-- a/") or "a/app.py" in ln for ln in removed["app.py"])


# ── #121: CLI integration — byte-stability and --modifications-only ───────────
import json  # noqa: E402
import os  # noqa: E402

CLASSIFIER = (
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "change_classifier.py"
)


def _make_auth_mod_repo(repo):
    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "views.py").write_text("@permission_required('app.admin')\ndef view():\n    return 1\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / "views.py").write_text("@permission_required('app.use')\ndef view():\n    return 1\n")
    run("add", "-A")
    run("commit", "-qm", "weaken auth")
    return run


def _cli(repo, *flags):
    return subprocess.run(
        ["python3", str(CLASSIFIER), "--base", "HEAD~1", "--head", "HEAD", *flags],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_cli_main_unpacks_three_tuple_without_error(tmp_path):
    """SPEC-121 AC-1: default mode runs (main() 3-tuple unpack does not raise)."""
    _make_auth_mod_repo(tmp_path)
    out = json.loads(_cli(tmp_path))
    assert "domains_touched" in out
    assert "structural_signals" in out
    # binding 6 / AC-1: default mode never gains a modification key.
    assert "structural_modifications" not in out


def test_cli_structural_only_byte_stable(tmp_path):
    """SPEC-121 AC-5: --structural-only carries no modification signals."""
    _make_auth_mod_repo(tmp_path)
    out = json.loads(_cli(tmp_path, "--structural-only"))
    assert "structural_signals" in out
    assert "structural_modifications" not in out


def test_cli_modifications_only_emits_only_modifications(tmp_path):
    """SPEC-121 AC-6: --modifications-only emits ONLY structural_modifications."""
    _make_auth_mod_repo(tmp_path)
    out = json.loads(_cli(tmp_path, "--modifications-only"))
    assert set(out.keys()) == {"structural_modifications"}
    signals = {m["signal"] for m in out["structural_modifications"]}
    assert "modified-permission-or-auth-state" in signals
    mod = next(m for m in out["structural_modifications"] if m["file"] == "views.py")
    assert mod["section"] is None
    assert "app.admin" in mod["evidence"] and "app.use" in mod["evidence"]


def test_cli_default_output_byte_identical_with_unused_removed(tmp_path):
    """SPEC-121 AC-1 (strict): default JSON for a diff with removals is byte-stable.

    The diff removes and re-adds an auth line, so `removed` is non-empty — yet the
    default output must not reference it. We assert the exact key set and that no
    modification signal leaks into the default channel.
    """
    _make_auth_mod_repo(tmp_path)
    out = json.loads(_cli(tmp_path))
    assert set(out.keys()) == {"base", "head", "domains_touched", "structural_signals"}
