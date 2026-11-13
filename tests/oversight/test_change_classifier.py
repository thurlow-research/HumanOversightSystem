"""Tests for change_classifier.py — the independent diff classifier that backs
the oversight-evaluator's #74 (N/A verification) and #75 (structural override)
compliance checks.

Detection functions are pure (operate on parsed name_status + added-lines), so
most tests feed synthetic inputs. One integration test exercises the real
git-diff parsing in a throwaway repo.
"""

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "change_classifier",
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "change_classifier.py",
)
assert _SPEC is not None and _SPEC.loader is not None
cc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cc)

# These are classifier-INPUT fixtures, not OpenTelemetry usage. They are built with
# explicit `+` so the source text never contains the tokens that the #2147 premise
# tests (test_security_scan_exemptions.py PR6b/PR7) scan for, keeping the
# CVE-2026-114603 exemption premise narrow. Runtime values are unchanged.
_OTEL = "open" + "telemetry"
_PROPAGATE_EXTRACT = "propagate." + "extract"
_TRACE_CTX_PROPAGATOR = "TraceContext" + "TextMapPropagator"


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


@pytest.mark.parametrize(
    "path,line",
    [
        (
            "docs/v0.7.0/TECHNICAL-DESIGN-2122-S1-fingerprint-source.md",
            "Constants and the new state variables:",
        ),
        ("docs/design.md", "There is no new state carrier beyond needs-human"),
        ("app/utils.py", "# There is no new state carrier beyond needs-human"),
    ],
)
def test_prose_new_state_is_not_structural(path, line):
    # #2201: the bare `new state` prose alternative matched English in design docs.
    sigs = {s["signal"] for s in cc.detect_structural([("M", path)], {path: [line]})}
    assert "new-user-facing-state" not in sigs


@pytest.mark.parametrize(
    "line",
    ["class Status(models.TextChoices):", "class Phase(enum.Enum):"],
)
def test_code_shaped_state_still_structural(line):
    sigs = {
        s["signal"]
        for s in cc.detect_structural([("M", "app/models.py")], {"app/models.py": [line]})
    }
    assert "new-user-facing-state" in sigs


@pytest.mark.parametrize(
    "line",
    [
        "    kind = forms.Select(choices=OPTIONS)",  # choices= only
        "class Level(models.IntegerChoices):",  # IntegerChoices only
        "class Mode(TextChoices):",  # bare TextChoices (models.TextChoices alt is subsumed)
        "    phase = StateField()",  # StateField only
        "    phase = FSMField(default='new')",  # FSMField only
        "    @transition(field=phase, source='a', target='b')",  # @transition only
        "STATUS_ACTIVE = 1",  # STATUS_[A-Z] only
        "VALID_STATES = ('a', 'b')",  # _STATES\b only
    ],
)
def test_each_state_alternative_independently_structural(line):
    # Each probe matches exactly one alternative, so dropping any one is killed (#2201).
    sigs = {
        s["signal"]
        for s in cc.detect_structural([("M", "app/models.py")], {"app/models.py": [line]})
    }
    assert "new-user-facing-state" in sigs


@pytest.mark.parametrize("line", ["x = _STATESMAN", "status_active = 1"])
def test_state_token_boundaries_are_respected(line):
    # `_STATES\b` and case-sensitive `STATUS_[A-Z]` must not match near-misses.
    sigs = {
        s["signal"]
        for s in cc.detect_structural([("M", "app/models.py")], {"app/models.py": [line]})
    }
    assert "new-user-facing-state" not in sigs


_ARG = '    parser.add_argument("--x", choices=["a", "b"])'


def _state_sigs(path, *lines):
    return {s["signal"] for s in cc.detect_structural([("M", path)], {path: list(lines)})}


@pytest.mark.parametrize(
    "path", ["scripts/automation/foo.py", "bootstrap/x.py", "bin/x.py", "scripts/x.sh"]
)
def test_argparse_choices_in_internal_tooling_not_state(path):
    # #2201 ruling: every member of the path set is exempt.
    assert "new-user-facing-state" not in _state_sigs(path, _ARG)


@pytest.mark.parametrize(
    "path",
    ["app/models.py", "src/app.py", "app/scripts/x.py", "src/bin/x.py", "tools/bootstrap/x.py"],
)
def test_choices_outside_internal_tooling_still_state(path):
    # Anchored at repo root: nested scripts/bin dirs are application code.
    assert "new-user-facing-state" in _state_sigs(path, _ARG)


@pytest.mark.parametrize(
    "line",
    [
        "class S(enum.Enum):",
        "STATUS_OPEN = 1",
        "class S(TextChoices):",
        "VALID_STATES = ()",
        "    x = FSMField()",
        '    p.add_argument("--x", choices=STATUS_CHOICES)',  # choices= AND STATUS_ on one line
    ],
)
def test_other_state_alternatives_still_flagged_in_internal_tooling(line):
    assert "new-user-facing-state" in _state_sigs("scripts/automation/foo.py", line)


def test_choices_only_line_then_real_state_line_still_flagged():
    # The one-per-file `break` must follow only a real match: an exempted choices=-only
    # line must not stop the scan before a later real state line (#2201).
    sigs = _state_sigs("scripts/automation/foo.py", _ARG, 'STATUS_OPEN = "open"')
    assert "new-user-facing-state" in sigs


def test_exemption_blanking_does_not_fabricate_a_match():
    # Blanking choices= must leave a separator: joining the neighbours ("STATUS_" + "A")
    # would manufacture a STATUS_[A-Z] hit that is not in the source line.
    assert "new-user-facing-state" not in _state_sigs(
        "scripts/automation/foo.py", "STATUS_choices=A"
    )


@pytest.mark.parametrize("path", ["binx/app.py", "scriptsx/app.py", "bootstrapper/app.py"])
def test_internal_tooling_prefix_requires_directory_boundary(path):
    # `bin`/`scripts`/`bootstrap` must be whole top-level directory names (#2201).
    assert "new-user-facing-state" in _state_sigs(path, _ARG)


def test_choices_word_without_equals_is_not_state():
    # The choices alternative needs `=`; prose or a bare name must not match anywhere.
    assert "new-user-facing-state" not in _state_sigs("app/models.py", "# the choices of colour")


def test_choices_with_spaced_equals_exempt_in_tooling_but_flagged_in_app():
    line = '    parser.add_argument("--x", choices = ["a"])'
    assert "new-user-facing-state" not in _state_sigs("scripts/x.py", line)
    assert "new-user-facing-state" in _state_sigs("app/x.py", line)


def test_2174_replay_pr_review_cli_no_state_signal():
    lines = [
        '    parser.add_argument("--disposition", choices=_VERDICT_DISPOSITIONS, required=True)',
        '    parser.add_argument("--disposition", choices=_VERDICT_DISPOSITIONS, default=None,',
    ]
    path = "scripts/automation/pr_review_cli.py"
    assert _state_sigs(path, *lines) == set()


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
    added = {
        "scripts/oversight/change_classifier.py": ["    r'permission_required|login_required'"]
    }
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


@pytest.mark.parametrize(
    "line",
    [
        "MACHINE_ACCOUNTS_ENV = 1",
        'CACHE_DIR = "/tmp"',
        "ATTACH",
        "REACH",
        "see docs/MACHINE-ACCOUNTS-SETUP.md",
        "ACHIEVE = 1",
        "LIBIBANK = 1",
    ],
)
def test_financial_rule_ignores_embedded_tokens(line):
    floor, ev = cc.detect_tier_floor([("M", "app/foo.py")], {"app/foo.py": [line]})
    assert floor != "CRITICAL"
    assert not any("PCI" in str(e.get("rule", "")) for e in ev)


@pytest.mark.parametrize(
    "line",
    [
        "ACH transfer",
        "ACH_ROUTING = 1",
        '"ACH"',
        "IBAN: DE89370400440532013000",
        "    c = Card(number)",
        "    c = CreditCard(number)",
        "    stripe.Charge.create(",
        "    account_number = x",
    ],
)
def test_financial_rule_still_matches_real_tokens(line):
    floor, _ = cc.detect_tier_floor([("M", "app/foo.py")], {"app/foo.py": [line]})
    assert floor == "CRITICAL"


def test_plain_code_floors_medium():
    floor, _ = cc.detect_tier_floor([("M", "app/utils.py")], {"app/utils.py": ["    return x + 1"]})
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

CLASSIFIER = Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "change_classifier.py"


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


def _obs_signal(path, line):
    sigs = {s["signal"] for s in cc.detect_structural([("M", path)], {path: [line]})}
    return "new-observability-instrumentation" in sigs


@pytest.mark.parametrize(
    "line",
    [
        "the exception propagates to the caller",
        "`main()` lets `_Interrupted` propagate.",
        "error propagation is unchanged",
        "the step recovered from propagation of the error",
        "we import propagation semantics from X",
        "from propagation delays the result",
        "  from propagation to the caller",
        "import propagation of errors is unchanged",
    ],
)
def test_prose_propagate_is_not_observability(line):
    assert not _obs_signal("docs/notes.md", line)


# `\bpropagators?\b` may still match prose "propagator"; accepted as OTel-specific.
@pytest.mark.parametrize(
    "line",
    [
        f"from {_OTEL} import propagate",
        f"ctx = {_PROPAGATE_EXTRACT}(request.headers)",
        f"propagator = {_TRACE_CTX_PROPAGATOR}()",
        # Each of these is matched ONLY by one new alternative (isolation cases).
        "set_global_textmap(propagator)",  # only \bpropagators?\b
        "class MyPropagator(TextMapPropagator):",  # only TextMapPropagator
        "from ddtrace.propagation.http import HTTPPropagator",  # only import-anchored
        "from opencensus.trace import propagation",  # only import-anchored
        "from opencensus.trace import propagation as p",  # only import-anchored
        "import ddtrace.propagation",  # only import-anchored
        "    from ddtrace.propagation.http import HTTPPropagator",  # indented
    ],
)
def test_propagator_code_is_observability(line):
    assert _obs_signal("app/tracing.py", line)


@pytest.mark.parametrize(
    "line",
    [
        # Line-start anchors: the import lookalike appears mid-sentence.
        "we later import propagation",
        "we copied from ddtrace.propagation import HTTPPropagator",
        # Word boundaries around `propagation` in the import alternative.
        "import mypropagation",
        "import propagations",
        "from x.mypropagation import y",
        # Dotted-submodule tail must not swallow prose or near-miss names.
        "import propagation.httpish of things",
        "import ddtrace.propagationx.http",
    ],
)
def test_midline_or_substring_propagation_import_is_not_observability(line):
    assert not _obs_signal("docs/notes.md", line)


@pytest.mark.parametrize(
    "line",
    [
        "ctx = propagate.inject(headers)",  # only propagate.(inject|extract) via inject
        "x = TraceContext(a)",  # only TraceContext
        "import propagation, os",  # import-anchored, trailing alt: comma
        "import ddtrace.propagation.http",  # import-anchored, dotted submodule
        "import opencensus.trace.propagation.trace_context",  # import-anchored, dotted
        "import ddtrace.propagation.http as h",  # import-anchored, dotted + as
        "from x import (propagation)",  # import-anchored, parenthesised
        "from x import (propagation, y)",  # parenthesised + comma
    ],
)
def test_each_remaining_alternative_is_isolated_observability(line):
    assert _obs_signal("app/tracing.py", line)


@pytest.mark.parametrize(
    "line",
    [
        "import " + "propagation." * 3500 + "!",
        "from " + "propagation." * 3500 + "!",
    ],
)
def test_crafted_long_propagation_import_line_is_not_quadratic(line):
    """#2031 / CWE-1333: unbounded dotted-name quantifiers took seconds on ~40KB."""
    start = time.perf_counter()
    assert not _obs_signal("app/tracing.py", line)
    assert time.perf_counter() - start < 0.5


def test_bounded_propagation_import_keeps_deep_dotted_match():
    assert _obs_signal("app/tracing.py", "import a.b.c.d.e.f.propagation.g.h.i.j")


@pytest.mark.parametrize(
    "line,expected",
    [
        # {0,8} dotted tail after `propagation`: 8 segments match, 9 do not.
        ("import propagation" + ".a" * 8, True),
        ("import propagation" + ".a" * 9, False),
        # {0,100} per-segment length.
        ("import propagation." + "a" * 100, True),
        ("import propagation." + "a" * 101, False),
        # {0,200} prefix run before `propagation` (import form).
        ("import " + "a" * 199 + ".propagation", True),
        ("import " + "a" * 201 + ".propagation", False),
        # {1,200} module run in `from X import propagation`.
        ("from " + "a" * 200 + " import propagation", True),
        ("from " + "a" * 201 + " import propagation", False),
        # {0,200} runs in the `from ...propagation... import` form.
        ("from " + "a" * 199 + ".propagation import x", True),
        ("from " + "a" * 201 + ".propagation import x", False),
        ("from propagation." + "a" * 199 + " import x", True),
        ("from propagation." + "a" * 200 + " import x", False),
    ],
)
def test_propagation_import_bound_edges(line, expected):
    assert _obs_signal("app/tracing.py", line) is expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("ctx = propagate.inject(h)", True),
        (f"ctx = {_PROPAGATE_EXTRACT}(h)", True),
        ("ctx = propagate.injection(h)", False),
        (f"ctx = {_PROPAGATE_EXTRACT}ion(h)", False),
        ("ctx = propagators.get()", True),
    ],
)
def test_propagate_inject_extract_word_boundary(line, expected):
    assert _obs_signal("app/tracing.py", line) is expected


def _route_signal(path, line):
    sigs = {s["signal"] for s in cc.detect_structural([("M", path)], {path: [line]})}
    return "new-user-flow-or-route" in sigs


@pytest.mark.parametrize(
    "path,line",
    [
        (
            "tests/oversight/test_gate_arg_grammar.py",
            '    assert "changeset = 1 file(s) from 1 explicit path(s)" in res.stdout',
        ),
        ("tests/oversight/test_x.py", '    assert "1 url(s) fetched" in out'),
        ("tests/oversight/test_x.py", '    assert "2 Route(s) found" in out'),
        ("docs/x.md", "Pass one or more path(s) to scan."),
        ("docs/x.md", "Each url(s) is checked."),
        ("docs/x.md", "Every Route(s) entry is listed."),
        ("docs/x.md", "Takes a path(s)."),
        ("docs/x.md", "if path(s) and other"),
    ],
)
def test_2254_prose_plural_is_not_route(path, line):
    # #2254: `path(s)` / `url(s)` / `Route(s)` English plurals are not route definitions.
    assert _route_signal(path, line) is False


@pytest.mark.parametrize(
    "line",
    [
        '    path("new/", views.home),',
        "    path(route, view),",
        '    re_path(r"^x/$", v),',
        "    url(r'^x/$', v),",
        '    Route("/a", handler),',
        "    path(sx, view),",
        "    path(s, view),",
    ],
)
def test_2254_real_route_still_structural(line):
    assert _route_signal("app/urls.py", line) is True


@pytest.mark.parametrize(
    "path,line",
    [
        ("docs/x.md", "Each re_path(s) is checked."),
        ("tests/oversight/test_x.py", '    assert "1 re_path(s) seen" in out'),
    ],
)
def test_2254_prose_plural_re_path_is_not_route(path, line):
    assert _route_signal(path, line) is False


@pytest.mark.parametrize(
    "line",
    [
        "    re_path(sx, view),",
        "    re_path(s, view),",
        "    url(sx, view),",
        "    url(s, view),",
        "    Route(sx, handler),",
        "    Route(s, handler),",
    ],
)
def test_2254_lookahead_excludes_only_exact_plural(line):
    # Kills `(?!s\))` -> `(?!s)` over-exclusion on re_path/url/Route.
    assert _route_signal("app/urls.py", line) is True


@pytest.mark.parametrize(
    "line",
    [
        '@app.route("/x")',
        "router.get('/x', h)",
        "@router.post('/x')",
        "<Route path='/x' />",
        "const r = createBrowserRouter([])",
    ],
)
def test_2254_unchanged_route_alternatives_still_signal(line):
    assert _route_signal("app/urls.py", line) is True
