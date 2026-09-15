"""ADR-1683 (#1683) — agy invocation moves to stdin via scripts/oversight/lib/vendor_invoke.sh.

`scripts/run_second_review.sh` used to pass the assembled agy prompt as a single
argv element (`agy ... -p "$prompt"`). Linux caps one argv element at
`MAX_ARG_STRLEN` (131,072 bytes); any prompt over that died at `execve` with a
silent `E2BIG`, which `2>/dev/null` turned into the generic `"agy invocation
failed"` — disabling the mandatory cross-vendor review on any large diff with a
misleading diagnosis. The fix moves the prompt to a tmpfile read on stdin
through the shared `vendor_invoke` helper, and replaces the collapsed
"invocation failed" string with a harness/vendor failure taxonomy (D-4).

These tests drive the real script as a subprocess with a stubbed `agy` on PATH,
following the established pattern in test_red_team_fail_closed.py and
test_second_review_request_changes_gate.py. They are hermetic: no real agy or
codex is invoked (a fake `agy` shadows the real one — this machine has agy
genuinely installed — by being placed first on PATH), and no network is used.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_second_review.sh"
_VENDOR_INVOKE_SH = _REPO_ROOT / "scripts" / "oversight" / "lib" / "vendor_invoke.sh"

# Real binaries this script (and vendor_invoke.sh / run_with_retry.sh) need,
# for the minimal-PATH "binary genuinely absent" test.
_REQUIRED_BINS = [
    "bash",
    "python3",
    "git",
    "cat",
    "grep",
    "awk",
    "sed",
    "mkdir",
    "date",
    "head",
    "wc",
    "tr",
    "cut",
    "dirname",
    "mktemp",
    "rm",
    "env",
    "tail",
    "find",
    "timeout",
]


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _make_target(tmp_path: Path, size: int = 0) -> Path:
    """A real file to review -> non-empty DIFF_CONTENT via the `--files`
    cat-fallback (tmp_path is not a git repo, so `git diff HEAD` fails)."""
    target = tmp_path / "target.py"
    if size:
        target.write_text("x = 1\n" * (size // 6 + 1))
    else:
        target.write_text("def f():\n    return 1\n")
    return target


def _run(
    tmp_path: Path,
    fake_bin: Path,
    *extra_args: str,
    path_override: str | None = None,
    score: str = "0.5",
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = path_override if path_override is not None else f"{fake_bin}:{env['PATH']}"
    return subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "3",
            "--tier",
            "MEDIUM",
            "--score",
            score,
            *extra_args,
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


def _artifact_text(tmp_path: Path, step: str = "3") -> str:
    matches = sorted((tmp_path / ".claudetmp" / "second-review").glob(f"step{step}-*.md"))
    assert matches, "no second-review artifact written"
    return matches[-1].read_text()


def _agy_json(content: str) -> dict:
    """Parse the fenced JSON block under the '## agy' section."""
    m = re.search(r"## agy.*?```json\n(.*?)\n```", content, re.S)
    assert m, content
    return json.loads(m.group(1))


def _run_lib_snippet(
    tmp_path: Path, body: str, pre_source: str = ""
) -> subprocess.CompletedProcess:
    """Run a small bash snippet that sources vendor_invoke.sh directly, with
    an isolated TMPDIR so leftover-directory assertions are unambiguous.

    `pre_source`, when given, runs BEFORE the library is sourced — this is the
    exact ordering the risk-assessor's own reproduction used ("`trap ... `
    then source the helper") and matches the realistic caller pattern D-6
    anticipates: a script sets up its own signal handling during its early
    setup, then later sources/uses this shared library. `body` always runs
    after sourcing."""
    snippet = tmp_path / "snippet.sh"
    isolated_tmp = tmp_path / "isolated_tmp"
    isolated_tmp.mkdir(exist_ok=True)
    snippet.write_text(f'{pre_source}\nsource "{_VENDOR_INVOKE_SH}"\n{body}\n')
    env = dict(os.environ)
    env["TMPDIR"] = str(isolated_tmp)
    return subprocess.run(
        ["bash", str(snippet)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(tmp_path),
    )


# ── 1. Headline regression: an oversized prompt reaches the reviewer on stdin ─


def test_oversized_prompt_reaches_the_reviewer_on_stdin(tmp_path):
    """A prompt comfortably over 131,072 bytes must not die at execve. A
    `#!/bin/sh` stub is just as unable to be launched with a 174 KB argv
    element as the real agy — E2BIG is raised by the kernel, independent of
    the target binary — so this fails before the fix and passes after."""
    _make_target(tmp_path, size=200_000)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_exec(
        fake_bin / "agy",
        """#!/bin/sh
n=$(wc -c)
if [ "$n" -gt 131072 ]; then
    printf '%s' '{"reviewer":"agy","lens":"correctness+spec","findings":[],"verdict":"approve","summary":"clean"}'
fi
""",
    )

    r = _run(tmp_path, fake_bin)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    content = _artifact_text(tmp_path)
    assert "verdict: approve" in content, content
    assert "invocation failed" not in content, content
    assert '"outcome": "invocation_failed"' not in content, content


# ── 2. No prompt content ever reaches argv ────────────────────────────────────


def test_argv_still_carries_no_prompt_content(tmp_path):
    """Pins the property directly (longest argv element < 4096 bytes) rather
    than inferring it from a size threshold, so it keeps holding if the cap
    ever changes."""
    _make_target(tmp_path, size=200_000)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record_file = tmp_path / "argv_record.txt"
    _write_exec(
        fake_bin / "agy",
        f"""#!/bin/sh
maxlen=0
for a in "$@"; do
    l=${{#a}}
    if [ "$l" -gt "$maxlen" ]; then maxlen=$l; fi
done
echo "$# $maxlen" > {record_file}
cat > /dev/null
printf '%s' '{{"reviewer":"agy","lens":"correctness+spec","findings":[],"verdict":"approve","summary":"clean"}}'
""",
    )

    r = _run(tmp_path, fake_bin)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert record_file.exists(), "stub never ran"
    argc, maxlen = record_file.read_text().split()
    assert int(argc) > 0
    assert int(maxlen) < 4096, f"an argv element was {maxlen} bytes"


# ── 3. rc!=0 with real output on stderr -> classified vendor ─────────────────


def test_vendor_nonzero_exit_is_classified_vendor(tmp_path):
    _make_target(tmp_path)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_exec(
        fake_bin / "agy",
        """#!/bin/sh
cat > /dev/null
echo "auth: credentials expired; run \\`agy login\\`" >&2
exit 3
""",
    )

    r = _run(tmp_path, fake_bin)
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    record = _agy_json(_artifact_text(tmp_path))
    assert record["failure_class"] == "vendor", record
    assert record["outcome_detail"] == "vendor_nonzero_exit", record
    assert record["outcome"] == "invocation_failed", record
    assert record["exit_code"] == 3, record
    assert "credentials expired" in record["stderr_tail"], record


# ── 4. Missing binary -> classified harness, never reported as vendor ────────


def test_missing_binary_is_classified_harness(tmp_path):
    """No `agy` anywhere on a minimal PATH (the required-binaries-only PATH,
    with the real agy/codex excluded). Per §4 item 4, this may resolve via the
    script's own pre-flight AGY_AVAILABLE check rather than inside
    vendor_invoke — either is acceptable, but it must never be reported as a
    vendor-side failure."""
    _make_target(tmp_path)
    import shutil

    import pytest

    resolved = {b: shutil.which(b) for b in _REQUIRED_BINS}
    missing = [b for b, p in resolved.items() if p is None]
    if missing:
        pytest.skip(f"required binaries unavailable for minimal-PATH test: {missing}")

    stub = tmp_path / "stub_bin"
    stub.mkdir()
    for b, p in resolved.items():
        (stub / b).symlink_to(p)

    r = _run(tmp_path, stub, path_override=str(stub))
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert '"failure_class": "vendor"' not in r.stdout + r.stderr
    combined = (r.stdout + r.stderr).lower()
    assert "unavailable" in combined or "harness" in combined, combined


# ── 4b. rc=2 argument-parse failure (ADR gap) -> classified harness ──────────


def test_arg_parse_failure_is_classified_harness_not_vendor(tmp_path):
    """The rc classification gap ADR-1683 D-2 leaves open: a Go-style flag
    package rejecting an unrecognized/misused flag exits 2 with EMPTY stdout
    and a usage/flag-error message on stderr. Under the ADR's literal
    'rc != 0 otherwise -> vendor' rule this misclassifies a harness defect
    (wrong flags shipped in this repo) as a vendor failure, sending an
    operator to check agy's auth/quota instead of the invocation code."""
    _make_target(tmp_path)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_exec(
        fake_bin / "agy",
        """#!/bin/sh
cat > /dev/null
echo "flag needs an argument: -p" >&2
exit 2
""",
    )

    r = _run(tmp_path, fake_bin)
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    record = _agy_json(_artifact_text(tmp_path))
    assert record["failure_class"] == "harness", record
    assert record["outcome_detail"] == "arg_parse_failed", record
    assert record["exit_code"] == 2, record


# ── 5. stderr_tail is redacted and bounded ────────────────────────────────────


def test_stderr_tail_is_redacted_and_bounded(tmp_path):
    _make_target(tmp_path)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    token = "ghp_" + ("a" * 36)
    _write_exec(
        fake_bin / "agy",
        f"""#!/bin/sh
cat > /dev/null
echo "leaked token: {token}" >&2
i=0
while [ "$i" -lt 200 ]; do
    echo "noise line $i" >&2
    i=$((i + 1))
done
exit 3
""",
    )

    r = _run(tmp_path, fake_bin)
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    record = _agy_json(_artifact_text(tmp_path))
    tail = record["stderr_tail"]
    assert len(tail.encode("utf-8")) <= 500, tail
    assert "\n" not in tail, tail
    assert token not in tail, tail
    assert "ghp_" not in tail, tail


# ── 6. No temp files leak on a failing call ───────────────────────────────────


def test_no_temp_files_leak_on_failure(tmp_path):
    _make_target(tmp_path)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_exec(
        fake_bin / "agy",
        """#!/bin/sh
cat > /dev/null
echo "boom" >&2
exit 3
""",
    )

    isolated_tmp = tmp_path / "isolated_tmp"
    isolated_tmp.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["TMPDIR"] = str(isolated_tmp)
    r = subprocess.run(
        [
            "bash",
            str(_SCRIPT),
            "--files",
            "target.py",
            "--step",
            "3",
            "--tier",
            "MEDIUM",
            "--score",
            "0.5",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    leftover = list(isolated_tmp.rglob("*"))
    assert leftover == [], f"leaked temp files: {leftover}"


# ── 7. Temp directory is created 0700, not umask-dependent ───────────────────


def test_tmpdir_is_created_mode_0700(tmp_path):
    """`mkdir -p` on this machine's default umask (0002) yields mode 775 —
    world-readable/executable — for a directory holding full reviewed-diff
    prompt content. `mktemp -d` must yield 700 regardless of umask."""
    r = _run_lib_snippet(
        tmp_path,
        """
umask 0002
_vendor_invoke_init_tmpdir
echo "TMPDIR=$_VENDOR_INVOKE_TMPDIR"
echo "MODE=$(stat -c %a "$_VENDOR_INVOKE_TMPDIR")"
""",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    mode = next(line.split("=", 1)[1] for line in r.stdout.splitlines() if line.startswith("MODE="))
    assert mode == "700", f"expected mode 700, got {mode}\nstdout={r.stdout}\nstderr={r.stderr}"


def test_tmpdir_init_is_idempotent_within_one_process(tmp_path):
    """Repeated calls in one process must reuse the one directory (D-6)."""
    r = _run_lib_snippet(
        tmp_path,
        """
_vendor_invoke_init_tmpdir
first="$_VENDOR_INVOKE_TMPDIR"
_vendor_invoke_init_tmpdir
second="$_VENDOR_INVOKE_TMPDIR"
echo "FIRST=$first"
echo "SECOND=$second"
""",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    values = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    assert values["FIRST"] == values["SECOND"], r.stdout


# ── 8. Trap chaining survives a pre-existing handler with an embedded quote ──


def test_trap_chain_survives_existing_handler_with_single_quote(tmp_path):
    """Direct reproduction of the risk-assessor's finding (trap set, THEN the
    helper is sourced — the same order the finding itself used): a
    pre-existing `trap "echo 'hi'" EXIT` must still run its own output on
    exit, AND the vendor_invoke temp directory must still be removed — both,
    not just one. Before the fix this composed a syntactically broken trap and
    silently dropped both the original handler and the cleanup."""
    r = _run_lib_snippet(
        tmp_path,
        'echo "TMPDIR=$_VENDOR_INVOKE_TMPDIR"',
        pre_source="trap \"echo 'existing-handler-ran'\" EXIT",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "existing-handler-ran" in r.stdout, f"stdout={r.stdout}\nstderr={r.stderr}"
    tmpdir = next(
        line.split("=", 1)[1] for line in r.stdout.splitlines() if line.startswith("TMPDIR=")
    )
    assert not Path(tmpdir).exists(), f"vendor_invoke temp dir was not cleaned up: {tmpdir}"


def test_trap_chain_survives_existing_handler_with_double_quote_and_semicolon(tmp_path):
    """Broader quoting stress case than the single-quote reproduction above:
    embedded double quotes and a semicolon inside the pre-existing handler.

    `pre_source` is written verbatim into the snippet as a line of shell, so it
    must be spelled as shell, not re-quoted for Python: the `'"'"'` idiom is a
    *shell* way to embed a single quote inside a single-quoted word, and using
    it inside a Python literal silently produces `echo 'handler; ran''` — which
    bash splits at the `;` into a bogus `ran` command, breaking the test rather
    than the code it is meant to pin. A raw string keeps the `'\\''` escapes
    intact so bash receives the handler exactly as written."""
    r = _run_lib_snippet(
        tmp_path,
        'echo "TMPDIR=$_VENDOR_INVOKE_TMPDIR"',
        pre_source=r"""trap 'echo "existing"; echo '\''handler; ran'\''' EXIT""",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert (
        "existing" in r.stdout and "handler; ran" in r.stdout
    ), f"stdout={r.stdout}\nstderr={r.stderr}"
    tmpdir = next(
        line.split("=", 1)[1] for line in r.stdout.splitlines() if line.startswith("TMPDIR=")
    )
    assert not Path(tmpdir).exists(), f"vendor_invoke temp dir was not cleaned up: {tmpdir}"


def test_trap_chain_cleans_up_with_no_pre_existing_handler(tmp_path):
    """Baseline: no pre-existing trap at all — cleanup still installs and runs."""
    r = _run_lib_snippet(
        tmp_path,
        """
echo "TMPDIR=$_VENDOR_INVOKE_TMPDIR"
""",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    tmpdir = next(
        line.split("=", 1)[1] for line in r.stdout.splitlines() if line.startswith("TMPDIR=")
    )
    assert not Path(tmpdir).exists(), f"vendor_invoke temp dir was not cleaned up: {tmpdir}"


# ── 9. Unknown vendor gets its own detail value, not a reused one ────────────


def test_unknown_vendor_gets_its_own_detail_value(tmp_path):
    """A bad vendor name must not reuse `binary_not_found` — nothing was
    looked up on PATH yet, and #1364's future variable-vendor-name call sites
    need an unambiguous signal distinct from a genuinely missing binary."""
    r = _run_lib_snippet(
        tmp_path,
        """
: > prompt.txt
vendor_invoke bogus-vendor 5 prompt.txt stdout.txt || true
echo "CLASS=$VENDOR_INVOKE_CLASS"
echo "DETAIL=$VENDOR_INVOKE_DETAIL"
""",
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    values = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    assert values["CLASS"] == "harness", r.stdout
    assert values["DETAIL"] == "unknown_vendor", r.stdout
