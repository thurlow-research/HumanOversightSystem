"""#1853 / #2057: the codex security-lens prompt must (a) let a clean diff come
back `approve` instead of forcing a basis-less `request_changes` (which
compute_verdict deliberately fail-closes since #2032), and (b) carry a generic,
optionally project-configured threat model rather than a hardcoded one.

Drives the REAL script with fake `codex`/`agy` on a minimal PATH; the codex
stub records its stdin so the prompt can be inspected. Hermetic.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.oversight.test_second_review_envelope_gate import (
    _SCRIPT,
    _artifact_fields,
    _minimal_stub_path,
)
from tests.tmp_hygiene import child_env

_CLEAN_CODEX = (
    '{"reviewer":"codex","lens":"security-adversarial","findings":[],'
    '"verdict":"approve","summary":"no exploitable defect"}'
)
_CLEAN_AGY = (
    '{"reviewer":"agy","lens":"correctness","findings":[],"verdict":"approve","summary":"ok"}'
)
_CPS_TERMS = ("HOA", "building", "resident", "booking", "TOTP")


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, *, with_agy: bool = False, config: str = "") -> tuple:
    (tmp_path / "target.py").write_text("def f():\n    return 1\n")
    if config:
        cfg = tmp_path / "scripts" / "framework"
        cfg.mkdir(parents=True)
        (cfg / "config.sh").write_text(config)
    stub = _minimal_stub_path(tmp_path)
    for tool in ("realpath",):
        resolved = shutil.which(tool)
        assert resolved is not None, f"{tool} not on PATH"
        target = stub / tool
        if not target.exists():
            target.symlink_to(resolved)
    captured = tmp_path / "codex_prompt.txt"
    _exe(
        stub / "codex",
        f"#!/usr/bin/env bash\ncat > {captured}\ncat <<'JSON'\n{_CLEAN_CODEX}\nJSON\n",
    )
    if with_agy:
        _exe(
            stub / "agy",
            f"#!/usr/bin/env bash\ncat > /dev/null\ncat <<'JSON'\n{_CLEAN_AGY}\nJSON\n",
        )
    env = dict(os.environ)
    env["PATH"] = str(stub)
    r = subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "1853",
            "--tier",
            "HIGH",
            "--score",
            "0.9",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=child_env(env),
    )
    prompt = captured.read_text() if captured.exists() else ""
    return r, prompt


def test_prompt_has_verdict_rule_and_no_forced_rejection(tmp_path):
    r, prompt = _run(tmp_path)
    assert prompt, r.stderr
    assert "Do not approve" not in prompt
    assert "ONLY when `findings` contains at least one finding" in prompt
    assert '"verdict": "approve"' in prompt


def test_default_prompt_is_project_neutral(tmp_path):
    r, prompt = _run(tmp_path)
    assert prompt, r.stderr
    for term in _CPS_TERMS:
        assert term not in prompt, term
    assert "unauthenticated attacker" in prompt
    assert "Shell/argument injection" in prompt


def test_configured_threat_model_replaces_default(tmp_path):
    (tmp_path / "TM.md").write_text("- Primary: a rogue plugin author UNIQUE-TM-MARKER\n")
    r, prompt = _run(tmp_path, config='export THREAT_MODEL_FILE="TM.md"\n')
    assert "UNIQUE-TM-MARKER" in prompt, r.stderr
    assert "unauthenticated attacker, and untrusted input" not in prompt
    assert "WARNING: THREAT_MODEL_FILE" not in r.stderr


@pytest.mark.parametrize(
    ("setup", "value", "reason"),
    [
        ("missing", "nope.md", "not a regular file"),
        ("dotdot", "../outside.md", "resolves outside the repo root"),
        ("absolute", "/etc/hostname", "resolves outside the repo root"),
        ("symlink", "link.md", "resolves outside the repo root"),
        ("oversize", "big.md", "larger than 16384 bytes"),
        ("newline_at_cap", "nl.md", "larger than 16384 bytes"),
        ("empty", "empty.md", "empty or unreadable"),
        ("dotdir", ".claudetmp/tm.md", "resolves into a dot-path (hidden file or directory)"),
        ("dotfile", ".env", "resolves into a dot-path (hidden file or directory)"),
    ],
)
def test_invalid_threat_model_falls_back_with_warning(tmp_path, setup, value, reason):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside.md"
    repo.mkdir()
    if setup == "dotdot":
        value = f"../{outside.name}"
    if setup in ("dotdot", "symlink"):
        outside.write_text("OUTSIDE-SECRET")
    if setup == "symlink":
        (repo / "link.md").symlink_to(outside)
    if setup == "dotdir":
        (repo / ".claudetmp").mkdir()
        (repo / value).write_text("DOT-SECRET")
    if setup == "dotfile":
        (repo / value).write_text("DOT-SECRET")
    if setup == "newline_at_cap":
        (repo / "nl.md").write_bytes(b"A" * 16384 + b"\n" + b"B" * 3615)
    if setup == "empty":
        (repo / "empty.md").write_text("")
    if setup == "oversize":
        (repo / "big.md").write_text("A" * 16385)
    r, prompt = _run(repo, config=f'export THREAT_MODEL_FILE="{value}"\n')
    assert prompt, r.stderr
    assert f"WARNING: THREAT_MODEL_FILE '{value}' ignored ({reason})" in r.stderr, r.stderr
    assert "OUTSIDE-SECRET" not in prompt
    assert "DOT-SECRET" not in prompt
    assert "unauthenticated attacker" in prompt
    assert r.returncode == 0, r.stderr


def test_file_exactly_at_cap_is_accepted(tmp_path):
    (tmp_path / "TM.md").write_text("UNIQUE-TM-MARKER " + "A" * (16384 - len("UNIQUE-TM-MARKER ")))
    r, prompt = _run(tmp_path, config='export THREAT_MODEL_FILE="TM.md"\n')
    assert "UNIQUE-TM-MARKER" in prompt, r.stderr
    assert "WARNING: THREAT_MODEL_FILE" not in r.stderr


def test_clean_approve_from_both_vendors_passes(tmp_path):
    r, _ = _run(tmp_path, with_agy=True)
    fields, artifact = _artifact_fields(tmp_path, "1853")
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}\n{artifact.read_text()}"
    assert fields.get("verdict") == "approve", fields
    assert fields.get("unresolved_findings") == "0", fields
