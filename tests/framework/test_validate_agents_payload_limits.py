"""Tests for validate_agents.sh's agy/codex payload-size handling (#1384).

Third instance of the argv/payload-size class already fixed once for
validate_self.sh (#1368) and tracked for run_second_review.sh (#1355): at
release scale the agent-file review package can run to ~2MB, which blows past
two independent ceilings:

  - agy: `agy -p "$(cat file)"` passes the whole package as a CLI argument,
    hitting the combined argv+environment ARG_MAX ceiling (same shape as
    #1368). agy's `-p` has no stdin-reading form, so the fix routes the
    prompt through a private `--add-dir` directory instead.
  - codex: already stdin-based (not an ARG_MAX issue), but codex's own
    `turn/start` API hard-rejects any single input over 1,048,576 characters
    with `input_too_large` — confirmed empirically, not a timeout. The fix
    pre-checks locally (`CODEX_MAX_INPUT_CHARS`, env-overridable) and returns
    a specific, diagnosable error instead of invoking codex and losing its
    real stderr to `run_capped`'s `2>/dev/null`.

Both fakes below are driven as real subprocesses against the actual script,
hermetically (no real agy/codex, no network, no gh).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "framework" / "validate_agents.sh"

_AGY_STUB = """#!/usr/bin/env bash
adddir=""
prompt=""
prev=""
for a in "$@"; do
    case "$prev" in
        --add-dir) adddir="$a" ;;
        -p) prompt="$a" ;;
    esac
    prev="$a"
done
printf '%s' "$prompt" > "$AGY_STUB_PROMPT_LOG"
total=0
if [[ -n "$adddir" ]]; then
    for f in "$adddir"/*; do
        [[ -f "$f" ]] || continue
        sz=$(wc -c < "$f")
        total=$(( total + sz ))
    done
fi
cat <<JSON
{"reviewer":"agy","lens":"consistency-completeness","findings":[],"verdict":"approve","summary":"stub saw $total chars via add-dir"}
JSON
"""

_CODEX_STUB = """#!/usr/bin/env bash
touch "$CODEX_STUB_INVOKED_MARKER"
cat > /dev/null
cat <<'JSON'
{"reviewer":"codex","lens":"adversarial-gaps","attacks":[],"verdict":"approve","summary":"stub ok"}
JSON
"""


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    agents_dir = tmp_path / "agents"
    docs_dir = tmp_path / "docs"
    agents_dir.mkdir()
    docs_dir.mkdir()
    (agents_dir / "coder.md").write_text(
        "---\nname: coder\n---\n\nImplementation agent. " + ("x" * 400) + "\n"
    )
    return agents_dir, docs_dir


def _write_stub(bin_dir: Path, name: str, body: str) -> Path:
    p = bin_dir / name
    p.write_text(body)
    p.chmod(0o755)
    return p


def _base_env(tmp_path: Path, bin_dir: Path) -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOS_FEED_KNOWN_ISSUES"] = "0"  # hermetic: no `gh` calls
    return env


def _latest_outfile(tmp_path: Path) -> str:
    matches = sorted((tmp_path / ".claudetmp" / "framework").glob("validation-*.md"))
    assert matches, "no validation output file written"
    return matches[-1].read_text()


# ── agy: file-based delivery, not argv ───────────────────────────────────────
def test_agy_receives_review_package_via_add_dir_not_argv(tmp_path):
    agents_dir, docs_dir = _write_fixture(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "agy", _AGY_STUB)

    prompt_log = tmp_path / "agy_prompt.log"
    env = _base_env(tmp_path, bin_dir)
    env["AGY_STUB_PROMPT_LOG"] = str(prompt_log)

    r = subprocess.run(
        ["bash", str(_SCRIPT), "--agents-dir", str(agents_dir), "--docs-dir", str(docs_dir),
         "--skip-codex"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

    # The -p argument itself must stay short (well under ARG_MAX) — it is an
    # instruction pointing at a file, never the review package's raw content.
    prompt_value = prompt_log.read_text()
    assert len(prompt_value) < 1000, prompt_value
    assert "=== FILE:" not in prompt_value, "review package leaked into argv"

    # The content must still have reached agy — just via the file, not argv.
    out = _latest_outfile(tmp_path)
    assert "stub saw" in out
    assert "stub saw 0 chars" not in out, out


def test_agy_prompt_survives_a_payload_larger_than_a_typical_arg_max(tmp_path):
    """Directly exercises the failure #1384 reported: a review package too big
    for a CLI argument. A 1.5MB agent file here mirrors the empirically-tested
    scale (see module docstring) without needing a real 2MB release diff."""
    agents_dir, docs_dir = _write_fixture(tmp_path)
    (agents_dir / "huge.md").write_text("y" * 1_500_000)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "agy", _AGY_STUB)

    prompt_log = tmp_path / "agy_prompt.log"
    env = _base_env(tmp_path, bin_dir)
    env["AGY_STUB_PROMPT_LOG"] = str(prompt_log)

    r = subprocess.run(
        ["bash", str(_SCRIPT), "--agents-dir", str(agents_dir), "--docs-dir", str(docs_dir),
         "--skip-codex"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert len(prompt_log.read_text()) < 1000

    out = _latest_outfile(tmp_path)
    assert "stub saw" in out
    # The stub's --add-dir read must have seen (at least) the huge file.
    import re

    m = re.search(r"stub saw (\d+) chars", out)
    assert m and int(m.group(1)) > 1_500_000, out


# ── codex: hard input-size cap, checked before invocation ──────────────────
def test_codex_invokes_normally_under_the_size_cap(tmp_path):
    agents_dir, docs_dir = _write_fixture(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "codex", _CODEX_STUB)

    marker = tmp_path / "codex_invoked"
    env = _base_env(tmp_path, bin_dir)
    env["CODEX_STUB_INVOKED_MARKER"] = str(marker)

    r = subprocess.run(
        ["bash", str(_SCRIPT), "--agents-dir", str(agents_dir), "--docs-dir", str(docs_dir),
         "--skip-agy"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert marker.exists(), "codex should have been invoked for a small payload"
    assert "stub ok" in _latest_outfile(tmp_path)


def test_codex_oversized_payload_is_rejected_without_invoking_codex(tmp_path):
    agents_dir, docs_dir = _write_fixture(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "codex", _CODEX_STUB)

    marker = tmp_path / "codex_invoked"
    env = _base_env(tmp_path, bin_dir)
    env["CODEX_STUB_INVOKED_MARKER"] = str(marker)
    # The real cap is 1,048,576 chars; force the tiny fixture over it cheaply.
    env["CODEX_MAX_INPUT_CHARS"] = "100"

    r = subprocess.run(
        ["bash", str(_SCRIPT), "--agents-dir", str(agents_dir), "--docs-dir", str(docs_dir),
         "--skip-agy"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, env=env,
    )
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert not marker.exists(), "codex must not be invoked once the size cap is exceeded"

    out = _latest_outfile(tmp_path)
    assert "input exceeds its 100-char hard limit" in out, out
    assert '"verdict":"error"' in out, out
