"""
Tests for scripts/automation/lib/posture.py — shared posture validation
V1-V14 (ADR-1643 TD-D26, §C.2.8; test T5.46(b)).

Every rule has one fixture that breaks exactly that rule. The L2 adapter
(`agent_invoke_cli.load_posture`) is pinned by the unmodified W1 suites
(T5.46(a)); `test_T5_46a_adapter_*` here only checks the V1 / non-V1 mapping.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

import scripts.automation.agent_invoke_cli as cli
from scripts.automation.lib import posture

NAME = "review-read-only"

SETTINGS = {
    "permissions": {
        "defaultMode": "manual",
        "disableBypassPermissionsMode": "disable",
        "allow": ["Read", "Grep", "Glob", "Bash(git diff *)"],
        "deny": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Bash(gh *)"],
    }
}
SIDECAR = {
    "schema": "hos.invocation-posture",
    "schema_version": 1,
    "id": NAME,
    "permission_mode": "manual",
    "allowed_tools": ["Read", "Grep", "Glob"],
    "disallowed_tools": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"],
}


def write_posture(root: Path, settings: dict | None = None, sidecar: dict | None = None) -> None:
    d = root / "contract" / "dimensions" / "postures"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.settings.json").write_text(json.dumps(SETTINGS if settings is None else settings))
    (d / f"{NAME}.hos.json").write_text(json.dumps(SIDECAR if sidecar is None else sidecar))


def mutated(which: str, fn) -> tuple[dict, dict]:
    settings, sidecar = copy.deepcopy(SETTINGS), copy.deepcopy(SIDECAR)
    fn(settings if which == "settings" else sidecar)
    return settings, sidecar


def test_T5_46b_valid_posture_loads(tmp_path):
    """T5.46(b): a conforming posture loads; sha256 covers settings + NUL + sidecar."""
    write_posture(tmp_path)
    p = posture.load_posture(tmp_path, NAME)
    assert p.id == NAME and p.permission_mode == "manual"
    assert p.allowed_tools == ["Read", "Grep", "Glob"]
    assert len(p.sha256) == 64


def test_T5_46b_V1_unknown_name(tmp_path):
    """T5.46(b): V1 unknown posture name."""
    with pytest.raises(posture.PostureError) as exc:
        posture.load_posture(tmp_path, "not-a-posture")
    assert exc.value.rule == "V1"


def test_T5_46b_V2_missing_files(tmp_path):
    """T5.46(b): V2 a posture file is absent."""
    with pytest.raises(posture.PostureError) as exc:
        posture.load_posture(tmp_path, NAME)
    assert exc.value.rule == "V2"


def _v3_not_json(root: Path) -> None:
    write_posture(root)
    (root / "contract/dimensions/postures" / f"{NAME}.hos.json").write_text("{not json")


def _v3_not_object(root: Path) -> None:
    write_posture(root)
    (root / "contract/dimensions/postures" / f"{NAME}.settings.json").write_text("[]")


@pytest.mark.parametrize("breaker", [_v3_not_json, _v3_not_object])
def test_T5_46b_V3_malformed_json(tmp_path, breaker):
    """T5.46(b): V3 invalid JSON, or JSON that is not an object."""
    breaker(tmp_path)
    with pytest.raises(posture.PostureError) as exc:
        posture.load_posture(tmp_path, NAME)
    assert exc.value.rule == "V3"


def _drop_exec(p: Path) -> None:
    os.chmod(p, 0o644)


CASES = [
    ("V4", *mutated("sidecar", lambda s: s.update(schema="wrong"))),
    ("V4", *mutated("sidecar", lambda s: s.update(schema_version=2))),
    ("V5", *mutated("sidecar", lambda s: s.update(id="other"))),
    ("V6", *mutated("sidecar", lambda s: s.update(permission_mode="bypassPermissions"))),
    ("V7", *mutated("settings", lambda s: s["permissions"].pop("disableBypassPermissionsMode"))),
    ("V8", *mutated("settings", lambda s: s["permissions"].update(allow="Read"))),
    ("V8", *mutated("settings", lambda s: s["permissions"].update(deny=[1]))),
    ("V8", *mutated("sidecar", lambda s: s.update(allowed_tools="Read"))),
    ("V8", *mutated("sidecar", lambda s: s.update(disallowed_tools=None))),
    ("V9", *mutated("sidecar", lambda s: s["allowed_tools"].append("Write"))),
    ("V10", *mutated("settings", lambda s: s["permissions"].update(deny=["Write"]))),
    (
        "V11",
        *mutated("settings", lambda s: s["permissions"].update(defaultMode="bypassPermissions")),
    ),
    ("V11", *mutated("settings", lambda s: s.update(note="--dangerously-skip"))),
    ("V12", *mutated("sidecar", lambda s: s["allowed_tools"].append("Read"))),
    ("V13", *mutated("sidecar", lambda s: s["allowed_tools"].append("Bash"))),
    ("V14", *mutated("settings", lambda s: s["permissions"]["allow"].append("Bash(/bin/ls *)"))),
    (
        "V14",
        *mutated("settings", lambda s: s["permissions"]["allow"].append("Bash(scripts/x.sh *)")),
    ),
]


@pytest.mark.parametrize(
    "rule,settings,sidecar", CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)]
)
def test_T5_46b_each_rule_fires(tmp_path, rule, settings, sidecar):
    """T5.46(b): one fixture per V4-V14 raises PostureError with the right rule."""
    if rule == "V12":
        # A bare grant alongside a rule-scoped entry for the same tool.
        settings["permissions"]["allow"].append("Read(docs/*)")
        sidecar["allowed_tools"] = ["Read"]
    if rule == "V13":
        # Bare Bash grant with no rule-scoped Bash(...) entry (else V12 fires first).
        settings["permissions"]["allow"] = ["Read", "Grep", "Glob"]
    write_posture(tmp_path, settings, sidecar)
    with pytest.raises(posture.PostureError) as exc:
        posture.load_posture(tmp_path, NAME)
    assert exc.value.rule == rule


def test_T5_46b_V14_non_executable_script(tmp_path):
    """T5.46(b): V14 a Bash(<script-path> *) entry whose script lost its exec bit."""
    settings, sidecar = mutated(
        "settings", lambda s: s["permissions"]["allow"].append("Bash(scripts/x.sh *)")
    )
    write_posture(tmp_path, settings, sidecar)
    script = tmp_path / "scripts" / "x.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    _drop_exec(script)
    with pytest.raises(posture.PostureError) as exc:
        posture.load_posture(tmp_path, NAME)
    assert exc.value.rule == "V14"
    os.chmod(script, 0o755)
    assert posture.load_posture(tmp_path, NAME).id == NAME


def test_T5_46a_adapter_maps_v1_to_usage_and_others_to_preflight(tmp_path):
    """T5.46(a): the L2 adapter keeps W1 behaviour (V1 -> usage, V2+ -> posture_invalid)."""
    with pytest.raises(cli._UsageError):
        cli.load_posture(tmp_path, "not-a-posture")
    with pytest.raises(cli._PreflightFailure) as exc:
        cli.load_posture(tmp_path, NAME)
    assert exc.value.detail == "posture_invalid"
    assert cli.KNOWN_POSTURES is posture.KNOWN_POSTURES
    assert cli.Posture is posture.Posture
