"""Shared harness for the `run_validators.sh` routing tests (#1034).

Two ways to drive the real script:

* :func:`filelist_split` — runs it through the `RUN_VALIDATORS_FILELIST_ONLY`
  seam, which prints the resolved `ALL_FILES` / `PY_FILES` / `JS_FILES` split and
  exits before any validator runs. Fast, no tooling required.
* :func:`hermetic_run` — runs it end-to-end with `PYTHON` pointed at
  `fixtures/validator_python_shim.py`, so validator invocations return canned
  envelopes and the composite becomes deterministic (see the shim's docstring).

Both operate inside a throwaway git repo so the script's relative `OUT_DIR`
(`.claudetmp/oversight/validators`) lands under the temp dir, never the real one.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "oversight" / "run_validators.sh"
SHIM_SRC = Path(__file__).resolve().parent / "fixtures" / "validator_python_shim.py"
OUT_REL = Path(".claudetmp") / "oversight" / "validators"

SPLIT_KEYS = ("ALL_FILES", "PY_FILES", "JS_FILES")


def init_repo(cwd: Path, subject: str = "base") -> None:
    """Initialise a throwaway git repo with one seed commit."""
    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
        )

    _git("init", "-q")
    _git("config", "user.email", "t@example.com")
    _git("config", "user.name", "t")
    (cwd / "seed.txt").write_text("seed\n")
    _git("add", "seed.txt")
    _git("commit", "-q", "-m", subject)


def commit_files(cwd: Path, files: dict[str, str], subject: str = "add files") -> None:
    """Write `files` (relative path -> content) and commit them."""
    for rel, content in files.items():
        path = cwd / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(
        ["git", "add", *files], cwd=str(cwd), check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", subject],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def filelist_split(cwd: Path, *script_args: str) -> dict[str, list[str]]:
    """Drive the file-list seam; return the ALL_FILES / PY_FILES / JS_FILES split."""
    env = {**os.environ, "RUN_VALIDATORS_FILELIST_ONLY": "1"}
    res = subprocess.run(
        ["bash", str(SCRIPT), *script_args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, f"seam run failed:\n{res.stdout}\n{res.stderr}"
    split: dict[str, list[str]] = {k: [] for k in SPLIT_KEYS}
    for line in res.stdout.splitlines():
        key, tab, val = line.partition("\t")
        if tab and key in split:
            split[key].append(val)
    return split


def install_shim(tmp_path: Path) -> Path:
    """Copy the canned-validator Python shim into tmp_path and make it executable."""
    dst = tmp_path / "validator_python_shim.py"
    shutil.copy2(SHIM_SRC, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


ARGV_LOG_NAME = "shim-argv.jsonl"


def hermetic_run(
    cwd: Path, *script_args: str, script: Path | None = None
) -> subprocess.CompletedProcess:
    """Run the script end-to-end with every validator call served by the shim.

    `script` overrides which run_validators.sh is executed (used to capture a
    baseline from a pre-change copy); it must live in `scripts/oversight/` so
    SCRIPT_DIR resolves the validators and sourced libs identically.
    """
    shim = install_shim(cwd)
    env = {
        **os.environ,
        "PYTHON": str(shim),
        "HOS_SHIM_ARGV_LOG": str(cwd / ARGV_LOG_NAME),
        # The venv python is the real interpreter the shim hands off to; falling
        # back to the shim's own `sys.executable` is fine when it is absent.
        "HOS_SHIM_REAL_PYTHON": str(REPO / "scripts" / "oversight" / ".venv" / "bin" / "python3"),
        "VALIDATOR_TIMEOUT": "20",
        "NETWORK_TIMEOUT": "20",
        "VALIDATOR_RETRIES": "0",
    }
    env.pop("RUN_VALIDATORS_FILELIST_ONLY", None)
    return subprocess.run(
        ["bash", str(script or SCRIPT), *script_args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def argv_fingerprint(cwd: Path) -> list[list[str]]:
    """Every validator dispatch as [script_basename, *args], sorted for stability."""
    log = cwd / ARGV_LOG_NAME
    if not log.exists():
        return []
    calls = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return sorted(calls)


def composite_fingerprint(cwd: Path) -> dict:
    """Reduce the produced summary.json to the AC-2 golden shape."""
    summary = json.loads((cwd / OUT_REL / "summary.json").read_text())
    return {
        "composite_score": summary["composite_score"],
        "tier": summary["tier"],
        "validator_count": summary["validator_count"],
        "successful_validators": summary["successful_validators"],
        "dimensions": sorted(
            [r.get("dimension"), r.get("score"), r.get("weight")]
            for r in summary.get("results", [])
        ),
    }
