"""security_scan.sh / secret_scan.sh must not fail-open on zero file args (#976),
AND (#1605) security_scan.sh's bandit verdict must come from the file bandit
wrote, never from the decorated stream, and must fail closed when that file is
unparseable or reports unscannable files; and dependency_audit.sh (the pip-audit lane, split out of
security_scan.sh) skips only on the runner's explicit --empty-changeset token and
is suspended independently of security_scan.sh.

Before the #976 fix both gates treated an empty FILES list as "nothing to scan"
and exited 0 — bandit was skipped outright and detect-secrets printed "No files
to scan" — so HIGH-severity findings and hardcoded secrets recorded a green
gate. The fix mirrors lint_check.sh: on empty FILES (and no --all/--staged)
default to a full-project scan.

Before the #1605 fix, security_scan.sh's bandit lane parsed bandit's STDOUT.
Bandit decorates stdout with a rich progress bar once a scan exceeds roughly a
second of elapsed time (pm-agent's V-2: a DURATION trigger, not a file-count
one — the same PR could pass on a fast runner and fail open on a slow or
loaded one, and a shared CI runner is exactly the slow, loaded case). A stub
is mandatory for the TC-S1..TC-S8 cases below, not a convenience: a natural-
reproduction test would pass or fail with runner speed, so only a stub-driven
test is a deterministic pin on the fix (bandit -o, never stdout).

The gates are driven as subprocesses with cwd set to a throwaway project so the
scripts' `find .` enumerates only the planted fixture files. Assertions that
depend on a tool (bandit / detect-secrets) are skipped when it is absent from
the oversight venv; the "default scan engaged" guards run regardless and pin the
regression directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import load_module_from_path
from tests.tmp_hygiene import child_env

_REPO = Path(__file__).resolve().parents[2]
_GATES = _REPO / "scripts" / "oversight" / "gates"
_SECURITY = _GATES / "security_scan.sh"
_SECRET = _GATES / "secret_scan.sh"
_DEPENDENCY = _GATES / "dependency_audit.sh"
_VENV_BIN = _REPO / "scripts" / "oversight" / ".venv" / "bin"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")

_BANDIT = (_VENV_BIN / "bandit").exists() or shutil.which("bandit") is not None
_DETECT_SECRETS = (_VENV_BIN / "detect-secrets").exists() or shutil.which(
    "detect-secrets"
) is not None

# A subprocess.Popen(..., shell=True) call is bandit B602 (HIGH severity) ONLY
# when the command is a variable, not a literal string (AV-6) — a fixture
# written with `subprocess.Popen("ls", shell=True)` is NOT HIGH at bandit's
# -lll severity and would make AC-5/AC-6 pass while pinning nothing. Do not
# "simplify" this to a literal — it is deliberate.
_HIGH_FINDING_PY = (
    "import subprocess\n"
    "def run(cmd):\n"
    "    subprocess.Popen(cmd, shell=True)  # bandit B602 HIGH\n"
)
# A recognizable AWS-style access key for detect-secrets.
_SECRET_PY = 'API_TOKEN = "AKIAIOSFODNN7EXAMPLEKEY1234567890abcd"\n'  # pragma: allowlist secret


def _run(
    script: Path,
    cwd: Path,
    *args: str,
    bandit_bin: str | None = None,
    pip_audit_bin: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    # Bound every tool invocation so the suite cannot hang on a slow tool. The
    # seams are cleared first so an ambient value can never leak into a case.
    env = {**os.environ, "GATE_TIMEOUT": "20", "GATE_RETRIES": "1"}
    env.pop("HOS_BANDIT_BIN", None)
    env.pop("HOS_PIP_AUDIT_BIN", None)
    if bandit_bin is not None:
        env["HOS_BANDIT_BIN"] = bandit_bin
    if pip_audit_bin is not None:
        env["HOS_PIP_AUDIT_BIN"] = pip_audit_bin
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=child_env(env),
    )


# ── bandit stub contracts (#1605 TD §6.1) ───────────────────────────────────
#
# Every stub MUST parse its own argv for `-o <path>` and write there — a stub
# that writes only to stdout would make a CORRECT implementation fail and an
# INCORRECT one pass (AD-8). Argv shape: -f json -lll -o <path> -- <file>...
# (SEC-M2). The stub finds `-o` by scanning argv, never by position, and treats
# everything after the first `--` as a file.

_STUB_PREAMBLE = """#!/usr/bin/env bash
OUT=""
prev=""
for a in "$@"; do
    if [[ "$prev" == "-o" ]]; then OUT="$a"; fi
    prev="$a"
done
"""


def _write_stub(tmp_path: Path, body: str, name: str = "bandit_stub.sh") -> Path:
    stub = tmp_path / name
    stub.write_text(_STUB_PREAMBLE + body)
    stub.chmod(0o755)
    return stub


_SB1_HIGH_FIXTURE = (
    '{"errors": [], "metrics": {"./vuln.py": {}, "_totals": {}}, '
    '"results": [{"filename": "./vuln.py", "line_number": 3, "test_id": "B602", '
    '"issue_severity": "HIGH", "issue_text": "subprocess call with shell=True '
    'identified, security issue."}]}'
)

# SB-1 — the defect: decorated stdout, real HIGH finding only in the -o file.
_SB1_BODY = f"""
echo "Working... XXXXXXXXXX 100% 0:00:02"
cat > "$OUT" <<'JSON'
{_SB1_HIGH_FIXTURE}
JSON
exit 1
"""

# SB-2 — contamination immunity: a HIGH finding on stdout, a clean -o file.
_SB2_BODY = f"""
cat <<'JSON'
{_SB1_HIGH_FIXTURE}
JSON
cat > "$OUT" <<'JSON'
{{"errors": [], "metrics": {{"./mod.py": {{}}, "_totals": {{}}}}, "results": []}}
JSON
exit 0
"""

# SB-3 — unparseable output file.
_SB3_BODY = """
echo "not json" > "$OUT"
exit 0
"""

# SB-4 — exit 2 (usage error), nothing written.
_SB4_BODY = """
exit 2
"""

# SB-5 — an unscannable file (AV-5).
_SB5_BODY = """
cat > "$OUT" <<'JSON'
{"errors": [{"filename": "./x.py",
             "reason": "syntax error while parsing AST from file"}],
 "metrics": {"./x.py": {}, "_totals": {}},
 "results": []}
JSON
exit 0
"""

# SB-6 — schema deviation (results is not a list).
_SB6_BODY = """
cat > "$OUT" <<'JSON'
{"results": "nope", "metrics": {}, "errors": []}
JSON
exit 0
"""

# SB-7 — the rc gate precedes the file: HIGH JSON written, then exit 2.
_SB7_BODY = f"""
cat > "$OUT" <<'JSON'
{_SB1_HIGH_FIXTURE}
JSON
exit 2
"""


def _sb8_body(counter_path: Path) -> str:
    # SB-8 / AV-3: a timeout-killed attempt N-1 can leave its output file behind.
    # Attempt 1 writes a HIGH finding then fails (exit 2); attempt 2 writes
    # nothing and succeeds. Without the gate's own `: > "$BANDIT_JSON"`
    # truncation, attempt 2 would parse attempt 1's leftover file and report a
    # finding this attempt never produced.
    return f"""
COUNTER="{counter_path}"
N=$(cat "$COUNTER" 2>/dev/null || echo 0)
N=$((N + 1))
echo "$N" > "$COUNTER"
if [[ "$N" -eq 1 ]]; then
    cat > "$OUT" <<'JSON'
{_SB1_HIGH_FIXTURE}
JSON
    exit 2
else
    exit 0
fi
"""


def _sb9_body(record: Path) -> str:
    # SB-9 — argv recorder (SEC-M2). Appends the full argv, NUL-separated, to
    # `record` (an absent record file therefore means bandit was never invoked),
    # then reports a clean scan with one metrics entry per post-`--` file.
    return f"""
printf '%s\\0' "$@" >> "{record}"
# COV-2: the gate deletes its pinned ini on exit, so copy it while it exists.
prev=""
for a in "$@"; do
    if [[ "$prev" == "--ini" ]]; then cp "$a" "{record.parent / "ini.rec"}"; fi
    prev="$a"
done
FILES_JSON=""
seen=0
for a in "$@"; do
    if [[ "$seen" -eq 1 ]]; then
        FILES_JSON="$FILES_JSON\\"$a\\": {{}}, "
    fi
    if [[ "$a" == "--" ]]; then seen=1; fi
done
cat > "$OUT" <<JSON
{{"errors": [], "results": [], "metrics": {{$FILES_JSON"_totals": {{}}}}}}
JSON
exit 0
"""


# HIGH finding and unscannable file together: the success branch runs two
# independent `if`s, not `if/elif` ("a run with both must report both").
_SB_BOTH_BODY = """
cat > "$OUT" <<'JSON'
{"errors": [{"filename": "./x.py",
             "reason": "syntax error while parsing AST from file"}],
 "metrics": {"./vuln.py": {}, "./x.py": {}, "_totals": {}},
 "results": [{"filename": "./vuln.py",
              "line_number": 3,
              "test_id": "B602",
              "issue_severity": "HIGH",
              "issue_text": "subprocess call with shell=True identified, security issue."}]}
JSON
exit 1
"""

# An exit code that is neither 0/1 nor 2 nor a failed extraction: the exhaustion
# ladder's third, generic message (a bandit crash surfaces here).
_SB_CRASH_BODY = """
exit 42
"""


# ── security_scan.sh ──────────────────────────────────────────────────────────


def test_security_scan_has_no_dependency_section(tmp_path):
    # TC-S11 / AC-1 — security_scan.sh is standalone and offline: the pip-audit
    # lane moved to dependency_audit.sh entirely (#1605).
    (tmp_path / "mod.py").write_text("x = 1\n")
    res = _run(_SECURITY, tmp_path, "mod.py")
    assert "pip-audit" not in res.stdout
    assert "dependency vulnerabilit" not in res.stdout


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(cwd: Path) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    _git(cwd, "config", "core.quotepath", "false")


def _recorded_argv(record: Path) -> list[str]:
    return record.read_bytes().decode("utf-8").split("\0")[:-1]


def test_security_scan_no_args_engages_full_scan(tmp_path):
    # With scannable Python present and no positional args, the empty-FILES
    # default branch must fire — the pre-fix code skipped bandit outright.
    (tmp_path / "mod.py").write_text("x = 1\n")
    res = _run(_SECURITY, tmp_path)
    assert "no files specified — defaulting" in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_security_scan_no_args_detects_high_finding(tmp_path):
    # bandit must actually scan the planted file and flag the HIGH finding
    # TC-S9 — the real venv
    # binary is used because HOS_BANDIT_BIN is absent (inertness, AD-7);
    # `_run` removes it from the child env explicitly.
    assert "HOS_BANDIT_BIN" not in os.environ
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    res = _run(_SECURITY, tmp_path)
    assert "HIGH severity bandit finding" in res.stdout
    assert "vuln.py" in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_security_scan_ignores_path_fallback_stub(tmp_path):
    # TC-S10 — AD-7's no-PATH-fallback rule: a stub literally named `bandit` on
    # PATH, with the seam unset, must never be used. Only the venv binary (or
    # the seam) may ever run.
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    stub = fake_bin / "bandit"
    stub.write_text("#!/usr/bin/env bash\necho FAKE-BANDIT-USED\nexit 0\n")
    stub.chmod(0o755)
    res = _run(
        _SECURITY,
        tmp_path,
        "vuln.py",
        env_extra={"PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
    )
    assert "HIGH severity bandit finding" in res.stdout
    assert "FAKE-BANDIT-USED" not in res.stdout


def test_security_scan_bandit_stub_sb1_contaminated_stdout_real_high(tmp_path):
    # TC-S1 / SB-1 / AC-5 — the defect, pinned.
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    stub = _write_stub(tmp_path, _SB1_BODY)
    res = _run(_SECURITY, tmp_path, "vuln.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "HIGH severity bandit finding" in res.stdout
    assert "B602" in res.stdout
    assert "vuln.py:3" in res.stdout
    assert "OK: no HIGH severity findings" not in res.stdout


def test_security_scan_bandit_stub_sb2_stdout_high_finding_never_consulted(tmp_path):
    # TC-S2 / SB-2 — contamination immunity: a HIGH finding on stdout must never
    # surface; only the -o file is ever read.
    (tmp_path / "mod.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB2_BODY)
    res = _run(_SECURITY, tmp_path, "mod.py", bandit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK: no HIGH severity findings (1 file(s) scanned, 0 unscannable)" in res.stdout
    assert "HIGH severity bandit finding" not in res.stdout


def test_security_scan_bandit_stub_sb3_unparseable_fails_closed(tmp_path):
    # TC-S3 / SB-3 / AC-4 — unparseable output must fail closed, never pass.
    (tmp_path / "mod.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB3_BODY)
    res = _run(_SECURITY, tmp_path, "mod.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "its JSON output could not be parsed" in res.stdout
    assert "OK: no HIGH severity findings" not in res.stdout
    assert "did not complete after retries" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_bandit_stub_sb4_exit_2_is_usage_error(tmp_path):
    # TC-S4 / SB-4 — exit 2 is a usage error, distinguishable from flakiness.
    (tmp_path / "mod.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB4_BODY)
    res = _run(_SECURITY, tmp_path, "mod.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "bandit rejected its arguments (exit 2" in res.stdout
    assert "did not complete after retries" not in res.stdout


def test_security_scan_bandit_stub_sb5_unscannable_file_fails_closed(tmp_path):
    # TC-S5 / SB-5 / AV-5 — a file bandit could not parse is a scan failure, not
    # a clean file.
    (tmp_path / "x.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB5_BODY)
    res = _run(_SECURITY, tmp_path, "x.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "could not scan 1 file(s)" in res.stdout
    assert "./x.py" in res.stdout
    assert "syntax error while parsing AST from file" in res.stdout
    assert "OK: no HIGH severity findings" not in res.stdout


def test_security_scan_bandit_stub_sb6_schema_deviation_fails_closed(tmp_path):
    # TC-S6 / SB-6 — a schema deviation (results not a list) fails closed.
    (tmp_path / "mod.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB6_BODY)
    res = _run(_SECURITY, tmp_path, "mod.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "its JSON output could not be parsed" in res.stdout
    assert "OK: no HIGH severity findings" not in res.stdout


def test_security_scan_bandit_stub_sb7_failed_attempt_file_never_read(tmp_path):
    # TC-S7 / SB-7 — the rc gate precedes the file: a HIGH-finding JSON written
    # by an attempt that then exits 2 must never be reported.
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    stub = _write_stub(tmp_path, _SB7_BODY)
    res = _run(_SECURITY, tmp_path, "vuln.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "bandit rejected its arguments (exit 2" in res.stdout
    assert "HIGH severity bandit finding" not in res.stdout


def test_security_scan_bandit_stub_sb8_truncation_prevents_stale_read(tmp_path):
    # TC-S8 / SB-8 / AV-3 — the only case that observes `: > "$BANDIT_JSON"`.
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    counter = tmp_path / "attempt_count"
    stub = _write_stub(tmp_path, _sb8_body(counter))
    res = _run(_SECURITY, tmp_path, "vuln.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "its JSON output could not be parsed" in res.stdout
    assert "HIGH severity bandit finding" not in res.stdout


def test_security_scan_high_and_unscannable_are_both_reported(tmp_path):
    # §3.6 — the two success-branch checks are `if`, not `if/elif`.
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    (tmp_path / "x.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB_BOTH_BODY)
    res = _run(_SECURITY, tmp_path, "vuln.py", "x.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "HIGH severity bandit finding" in res.stdout
    assert "could not scan 1 file(s)" in res.stdout
    assert "GATE FAIL: 2 security check(s) failed" in res.stdout


def test_security_scan_unrecognised_exit_is_the_generic_message(tmp_path):
    # §3.6 table row 3: neither a usage error (2) nor a failed extraction (65).
    (tmp_path / "mod.py").write_text("x = 1\n")
    stub = _write_stub(tmp_path, _SB_CRASH_BODY)
    res = _run(_SECURITY, tmp_path, "mod.py", bandit_bin=str(stub))
    assert res.returncode != 0
    assert "bandit did not complete after retries" in res.stdout
    assert "bandit rejected its arguments" not in res.stdout
    assert "could not be parsed" not in res.stdout


@pytest.mark.slow
@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_security_scan_all_real_bandit_detects_high_among_many_files(tmp_path):
    # TC-S12 / AC-6 — end-to-end positive control: a real bandit run over a file
    # set large enough to trigger the bar on this machine, containing one
    # genuine HIGH finding. Corroboration only; TC-S1/AC-5 is the enforcing,
    # deterministic test — this must not gate CI on timing.
    for i in range(200):
        (tmp_path / f"mod_{i}.py").write_text(f"x_{i} = {i}\n")
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    res = _run(_SECURITY, tmp_path, "--all")
    assert "GATE FAIL" in res.stdout
    assert "HIGH severity bandit finding" in res.stdout
    assert "vuln.py" in res.stdout


def test_security_scan_non_python_explicit_file_skips(tmp_path):
    # TC-S13 / AD-5 — the branch that stops AD-5 part 2 reddening every docs PR
    # (also covered by TC-G5 in test_gate_arg_grammar.py).
    (tmp_path / "only.md").write_text("# doc\n")
    res = _run(_SECURITY, tmp_path, "only.md")
    assert res.returncode == 0, res.stderr
    assert "SKIP — 0 of 1 changeset file(s) are Python" in res.stdout


def test_security_scan_all_empty_project_not_checked(tmp_path):
    # TC-S14 / §3.4 — a whole-project claim (--all/unscoped with zero Python
    # files anywhere) is NOT CHECKED, never a hidden GATE PASS.
    res = _run(_SECURITY, tmp_path, "--all")
    assert res.returncode == 0, res.stderr
    assert "NOT CHECKED — the project contains no Python file(s)" in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_explicit_option_like_name_fails_closed(tmp_path):
    # TC-S15 / SEC-M2 — on the explicit-argv path an option-like filename turns
    # the gate red (exit 2, from the shared grammar) and bandit never runs.
    work = tmp_path / "work"
    _init_repo(work)
    (work / "--baseline=x.py").write_text("x = 1\n")
    _git(work, "add", "--", "--baseline=x.py")
    _git(work, "commit", "-q", "-m", "option-like name")
    record = tmp_path / "argv.record"
    stub = _write_stub(tmp_path, _sb9_body(record))
    res = _run(_SECURITY, work, "--baseline=x.py", bandit_bin=str(stub))
    assert res.returncode == 2
    assert "refusing to treat it as a filename" in res.stderr
    assert not record.exists()
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_git_sourced_option_like_name_follows_double_dash(tmp_path):
    # TC-S16 / SEC-M2 — names that come from git (--diff/--step/--staged) are
    # not checked for a leading `-`, so `--` before the file list is load-bearing.
    work = tmp_path / "work"
    _init_repo(work)
    (work / "base.py").write_text("x = 1\n")
    _git(work, "add", "base.py")
    _git(work, "commit", "-q", "-m", "base")
    (work / "--baseline=x.py").write_text("y = 2\n")
    _git(work, "add", "--", "--baseline=x.py")
    _git(work, "commit", "-q", "-m", "option-like name")
    record = tmp_path / "argv.record"
    stub = _write_stub(tmp_path, _sb9_body(record))
    res = _run(_SECURITY, work, "--diff", "HEAD~1", bandit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    argv = _recorded_argv(record)
    assert "--" in argv
    sep = argv.index("--")
    assert argv[:sep][:2] == ["-f", "json"]
    assert all(a != "--baseline=x.py" for a in argv[:sep])
    assert argv[sep + 1 :] == ["--baseline=x.py"]
    assert "OK: no HIGH severity findings (1 file(s) scanned, 0 unscannable)" in res.stdout


def test_security_scan_non_ascii_python_name_is_scanned_not_skipped(tmp_path):
    # TC-S17 / SEC-M2 — a raw UTF-8 `.py` name is Python. The quoted form git
    # prints under the default core.quotepath (`"\303\251.py"`, quotes included)
    # would fail the `*.py` kind filter and be silently skipped, which is why
    # the CI file listing must never produce it.
    work = tmp_path / "work"
    _init_repo(work)
    (work / "é.py").write_text("x = 1\n")
    record = tmp_path / "argv.record"
    stub = _write_stub(tmp_path, _sb9_body(record))
    res = _run(_SECURITY, work, "é.py", bandit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    argv = _recorded_argv(record)
    assert argv[argv.index("--") + 1 :] == ["é.py"]
    assert "SKIP — 0 of 1 changeset file(s) are Python" not in res.stdout


def test_security_scan_quoted_non_ascii_name_would_be_skipped(tmp_path):
    # TC-S17 companion — the literal quoted form is what the kind filter skips.
    (tmp_path / "plain.py").write_text("x = 1\n")
    quoted = '"\\303\\251.py"'
    (tmp_path / quoted).write_text("x = 1\n")
    res = _run(_SECURITY, tmp_path, quoted)
    assert "SKIP — 0 of 1 changeset file(s) are Python" in res.stdout


def _sb10_stub(tmp_path: Path, fixture: str) -> Path:
    # SB-10 (COV-1) — cats a fixed JSON fixture to `-o`, exit 0. Unlike SB-9 the
    # `metrics` keys are independent of what the stub was handed.
    (tmp_path / "sb10.json").write_text(fixture)
    return _write_stub(tmp_path, f'cat "{tmp_path / "sb10.json"}" > "$OUT"\nexit 0\n')


_SB10_EMPTY = '{"results": [], "errors": [], "metrics": {"_totals": {}}}'
_SB10_ONE = '{"results": [], "errors": [], "metrics": {"./a.py": {}, "_totals": {}}}'


def test_security_scan_coverage_zero_scanned_of_two_fails_closed(tmp_path):
    # TC-S20a / COV-1 — rc 0, nothing scanned, is NOT a clean scan.
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    stub = _sb10_stub(tmp_path, _SB10_EMPTY)
    res = _run(_SECURITY, tmp_path, "a.py", "b.py", bandit_bin=str(stub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "GATE FAIL: bandit scanned 0 of 2 file(s) given" in res.stdout
    assert "  a.py: not scanned by bandit" in res.stdout
    assert "  b.py: not scanned by bandit" in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_coverage_partial_names_only_the_unscanned(tmp_path):
    # TC-S20b / COV-1 — scanned < given lists exactly the unscanned path.
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    stub = _sb10_stub(tmp_path, _SB10_ONE)
    res = _run(_SECURITY, tmp_path, "a.py", "b.py", bandit_bin=str(stub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "bandit scanned 1 of 2 file(s) given" in res.stdout
    assert "  b.py: not scanned by bandit" in res.stdout
    assert "  a.py: not scanned by bandit" not in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_coverage_duplicate_paths_are_not_a_false_red(tmp_path):
    # TC-S20c / COV-1, M-3 — duplicates collapse in bandit's file set, so the
    # comparison is against DISTINCT given paths.
    (tmp_path / "a.py").write_text("x = 1\n")
    stub = _sb10_stub(tmp_path, _SB10_ONE)
    res = _run(_SECURITY, tmp_path, "a.py", "a.py", bandit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK: no HIGH severity findings (1 file(s) scanned, 0 unscannable)" in res.stdout
    assert "GATE PASS" in res.stdout


def test_security_scan_coverage_not_reported_twice_when_errors_present(tmp_path):
    # TC-S20d / COV-1, M-4 — an unreadable file is in `errors` but not
    # `metrics`; the coverage check must not report it a second time.
    (tmp_path / "u.py").write_text("x = 1\n")
    stub = _sb10_stub(
        tmp_path,
        '{"results": [], "errors": [{"filename": "./u.py", "reason": "Permission denied"}],'
        ' "metrics": {"_totals": {}}}',
    )
    res = _run(_SECURITY, tmp_path, "u.py", bandit_bin=str(stub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "could not scan 1 file(s)" in res.stdout
    assert "bandit scanned" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_coverage_scanned_exceeding_given_fails_closed(tmp_path):
    # COV-1 -ne (not -lt) — scanned > given means the accounting is broken; the
    # gate must fail closed rather than read it as covered.
    (tmp_path / "a.py").write_text("x = 1\n")
    stub = _sb10_stub(
        tmp_path,
        '{"results": [], "errors": [], "metrics": {"./a.py": {}, "./z.py": {}, "_totals": {}}}',
    )
    res = _run(_SECURITY, tmp_path, "a.py", bandit_bin=str(stub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "bandit scanned 2 of 1 file(s) given" in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_empty_metrics_dict_fails_closed_as_parse_failure(tmp_path):
    # Numeric guard — an empty metrics dict yields scanned=-1, which must fail
    # closed (rc 65 path), not read as zero or as a clean scan.
    (tmp_path / "a.py").write_text("x = 1\n")
    stub = _sb10_stub(tmp_path, '{"results": [], "errors": [], "metrics": {}}')
    res = _run(_SECURITY, tmp_path, "a.py", bandit_bin=str(stub))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "JSON output could not be parsed" in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_pinned_ini_creation_failure_fails_closed(tmp_path):
    # COV-2 — if the gate-owned ini cannot be created, bandit must never run
    # (it would otherwise discover a committed .bandit).
    (tmp_path / "a.py").write_text("x = 1\n")
    record = tmp_path / "argv.record"
    stub = _write_stub(tmp_path, _sb9_body(record))
    shim = tmp_path / "shim"
    shim.mkdir()
    real = shutil.which("mktemp")
    (shim / "mktemp").write_text(
        f'#!/usr/bin/env bash\ncase "$*" in *bandit_ini_*) exit 1;; esac\nexec "{real}" "$@"\n'
    )
    (shim / "mktemp").chmod(0o755)
    res = _run(
        _SECURITY,
        tmp_path,
        "a.py",
        bandit_bin=str(stub),
        env_extra={"PATH": f"{shim}:{os.environ['PATH']}"},
    )
    assert res.returncode == 1, res.stdout + res.stderr
    assert "could not create bandit's pinned config" in res.stdout
    assert not record.exists()
    assert "GATE PASS" not in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_security_scan_coverage_directories_named_py_real_bandit(tmp_path):
    # TC-S20e / COV-1 — the reviewer's repro: an empty directory d.py and a
    # symlink dl.py -> d.py; bandit exits 0 with scanned=0.
    (tmp_path / "d.py").mkdir()
    (tmp_path / "dl.py").symlink_to("d.py")
    res = _run(_SECURITY, tmp_path, "d.py", "dl.py")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "bandit scanned 0 of 2 file(s) given" in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_security_scan_bandit_ini_in_symlinked_dir_does_not_suppress_finding(tmp_path):
    # TC-S20f / COV-1 amended by COV-2 — a `.bandit` with `skips = B602`
    # behind a symlinked directory target must NOT suppress the finding: the
    # pinned --ini means it is never read.
    (tmp_path / "v.py").write_text(_HIGH_FINDING_PY)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / ".bandit").write_text("[bandit]\nskips = B602\n")
    (tmp_path / "sl.py").symlink_to("cfg")
    res = _run(_SECURITY, tmp_path, "v.py", "sl.py")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "bandit scanned 1 of 2 file(s) given" in res.stdout
    assert "  sl.py: not scanned by bandit" in res.stdout
    assert "HIGH severity bandit finding" in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
@pytest.mark.parametrize("variant", ["recursive_skips", "baseline"])
def test_security_scan_bandit_ini_cannot_suppress_via_recursive_or_baseline(tmp_path, variant):
    # TC-S20g / COV-2, M-5 — the case that defeats rule (b) alone. With
    # `recursive = true` the directory target counts as scanned (scanned == given),
    # so only the pinned --ini stands between the .bandit and a green gate.
    (tmp_path / "v.py").write_text(_HIGH_FINDING_PY)
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "x.py").write_text("x = 1\n")
    if variant == "recursive_skips":
        content = "[bandit]\nskips = B602\nrecursive = true\n"
    else:
        report = tmp_path / "baseline.json"
        subprocess.run(
            [str(_VENV_BIN / "bandit"), "-f", "json", "-lll", "-o", str(report), "--", "v.py"],
            cwd=str(tmp_path),
            capture_output=True,
            env=child_env({**os.environ}),
        )
        assert report.exists()
        content = f"[bandit]\nbaseline = {report}\n"
    (cfg / ".bandit").write_text(content)
    (tmp_path / "sl.py").symlink_to("cfg")
    res = _run(_SECURITY, tmp_path, "v.py", "sl.py")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "HIGH severity bandit finding" in res.stdout
    assert "bandit scanned 1 of 2 file(s) given" in res.stdout
    assert "  sl.py: not scanned by bandit" in res.stdout
    assert "OK:" not in res.stdout
    assert "GATE PASS" not in res.stdout


def test_security_scan_bandit_is_pinned_to_a_gate_owned_ini(tmp_path):
    # TC-S21 / COV-2 — `--ini <one path>` precedes `--`, the file holds exactly
    # `[bandit]\n`, and it is removed when the gate exits.
    (tmp_path / "a.py").write_text("x = 1\n")
    record = tmp_path / "argv.record"
    stub = _write_stub(tmp_path, _sb9_body(record))
    res = _run(_SECURITY, tmp_path, "a.py", bandit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK: no HIGH severity findings (1 file(s) scanned, 0 unscannable)" in res.stdout
    argv = _recorded_argv(record)
    sep = argv.index("--")
    assert argv.count("--ini") == 1
    ini_at = argv.index("--ini")
    assert ini_at + 1 < sep
    assert argv[:sep].count(argv[ini_at + 1]) == 1
    assert (tmp_path / "ini.rec").read_text() == "[bandit]\n"
    assert not Path(argv[ini_at + 1]).exists()


def test_security_scan_ci_job_is_wired_with_the_security_amendments():
    # TC-S18 / SEC-M2 + SEC-S1 — workflow static test. The job lists changed
    # files NUL-delimited (a quoted non-ASCII name would be skipped as
    # non-Python), asserts the scanner exists before running the gate (no green
    # job that scanned nothing), and never sets the test-only bandit seam.
    yaml = pytest.importorskip("yaml")
    path = _REPO / ".github" / "workflows" / "oversight-gates.yml"
    text = path.read_text()
    assert "HOS_BANDIT_BIN" not in text
    assert "dependency_audit.sh" not in text  # AC-11: the dependency half is not wired here
    job = yaml.safe_load(text)["jobs"]["oversight-gate-security-scan"]
    steps = job["steps"]
    names = [st.get("name", "") for st in steps]
    venv = names.index("Build oversight venv")
    assert_present = names.index("Assert the scanner is present")
    run_gate = names.index("Run security_scan")
    assert venv < assert_present < run_gate
    assert "test -x scripts/oversight/.venv/bin/bandit" in steps[assert_present]["run"]
    run = steps[run_gate]["run"]
    assert "git diff -z --name-only" in run
    assert "mapfile -t -d ''" in run
    assert 'security_scan.sh "${FILES[@]}"' in run
    assert "--all" not in run


_OPTION_LIKE_NAMES = ("--help", "-h", "--all")


def _workflow_prefix_line() -> str:
    # The exact statement the CI job runs between building FILES and calling the
    # gate, read from the workflow so the test cannot drift from it.
    text = (_REPO / ".github" / "workflows" / "oversight-gates.yml").read_text()
    job = text.split("  oversight-gate-security-scan:", 1)[1].split(
        "\n  oversight-gate-repo-scoped:", 1
    )[0]
    lines = [ln.strip() for ln in job.splitlines() if ln.strip().startswith("FILES=(")]
    assert lines == ['FILES=("${FILES[@]/#/./}")'], lines
    # The harness below mirrors this listing; deletions must stay excluded.
    assert 'git diff -z --name-only --diff-filter=d "origin/$GITHUB_BASE_REF...HEAD"' in job
    return lines[0]


def _option_named_changeset_repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    _init_repo(work)
    (work / "base.txt").write_text("base\n")
    _git(work, "add", "base.txt")
    _git(work, "commit", "-q", "-m", "base")
    (work / "vuln.py").write_text(_HIGH_FINDING_PY)
    (work / "gone.py").write_text("x = 1\n")
    _git(work, "add", "gone.py")
    _git(work, "commit", "-q", "-m", "to be deleted")
    _git(work, "rm", "-q", "gone.py")
    for name in _OPTION_LIKE_NAMES:
        (work / name).write_text("x\n")
    _git(work, "add", "--", "vuln.py", *_OPTION_LIKE_NAMES)
    _git(work, "commit", "-q", "-m", "option-like names plus a HIGH finding")
    return work


def _run_ci_call_shape(work: Path, prefix: str, bandit_bin: str | None = None):
    # Mirrors the workflow step: NUL-delimited git listing, optional prefix,
    # then the gate with the array.
    script = (
        "set -euo pipefail\n"
        "mapfile -t -d '' FILES < <(git diff -z --name-only --diff-filter=d HEAD~1...HEAD)\n"
        f"{prefix}\n"
        f'bash "{_SECURITY}" "${{FILES[@]}}"\n'
    )
    env = {**os.environ, "GATE_TIMEOUT": "20", "GATE_RETRIES": "1"}
    env.pop("HOS_BANDIT_BIN", None)
    if bandit_bin:
        env["HOS_BANDIT_BIN"] = bandit_bin
    return subprocess.run(
        ["bash", "-c", script],
        cwd=str(work),
        env=child_env(env),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_ci_call_shape_unprefixed_help_name_fails_open(tmp_path):
    # Pins the reason for the ./ prefix (#1605, SEC re-review 2026-10-31): the
    # shared grammar answers a bare `--help` anywhere in argv with usage and
    # exit 0, so the scan never runs. A parser-level fix is a separate follow-up.
    work = _option_named_changeset_repo(tmp_path)
    res = _run_ci_call_shape(work, ":")
    assert res.returncode == 0
    assert "GATE FAIL" not in res.stdout
    assert "bandit received" not in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_ci_call_shape_prefixed_option_like_names_still_scan_and_fail(tmp_path):
    work = _option_named_changeset_repo(tmp_path)
    res = _run_ci_call_shape(work, _workflow_prefix_line())
    assert res.returncode == 1, res.stdout + res.stderr
    assert "GATE FAIL: 1 HIGH severity bandit finding(s)" in res.stdout
    assert "vuln.py" in res.stdout


def test_ci_call_shape_prefixed_names_reach_the_gate_as_paths(tmp_path):
    work = _option_named_changeset_repo(tmp_path)
    record = tmp_path / "argv.record"
    stub = _write_stub(tmp_path, _sb9_body(record))
    res = _run_ci_call_shape(work, _workflow_prefix_line(), bandit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    argv = _recorded_argv(record)
    assert argv[argv.index("--") + 1 :] == ["./vuln.py"]
    assert "Usage" not in res.stdout


# ── dependency_audit.sh ───────────────────────────────────────────────────────
#
# Repo-scoped: it takes no file arguments (they are ignored). The lane is the
# one #1776 gave security_scan.sh, moved unchanged, so its verdict, roster and
# NOT CHECKED behaviour are pinned in test_security_scan_exemptions.py (g1-g5).
# What is pinned here is what the split itself added: the AD-2a skip, and the
# independence of the two suspension keys.
#
# Stdout-JSON stub, the shape the lane reads (`cat <payload>; exit <rc>`).

_DEP_CLEAN_JSON = '{"dependencies": [{"name": "anyio", "version": "4.4.0", "vulns": []}]}'
_DEP_FINDING_JSON = (
    '{"dependencies": [{"name": "requests", "version": "2.0.0", "vulns": '
    '[{"id": "CVE-2099-0001", "fix_versions": ["2.1.0"], "aliases": [], "description": "d"}]}]}'
)


def _pip_audit_stub(tmp_path: Path, payload: str, rc: int, marker: Path | None = None) -> Path:
    stub = tmp_path / "pip_audit_stub.sh"
    touch = f"touch '{marker}'\n" if marker is not None else ""
    stub.write_text(f"#!/usr/bin/env bash\n{touch}cat <<'JSON'\n{payload}\nJSON\nexit {rc}\n")
    stub.chmod(0o755)
    return stub


def test_dependency_audit_empty_changeset_skips_before_pip_audit(tmp_path):
    # AD-2a — the literal --empty-changeset token is the runner's explicit
    # "this invocation verifies nothing" signal: NOT CHECKED, exit 0, and the
    # audit binary is never spawned (the marker file proves it).
    marker = tmp_path / "pip_audit_invoked.marker"
    stub = _pip_audit_stub(tmp_path, _DEP_CLEAN_JSON, 0, marker)
    res = _run(_DEPENDENCY, tmp_path, "--empty-changeset", pip_audit_bin=str(stub))
    assert res.returncode == 0, res.stderr
    assert (
        "dependency_audit: NOT CHECKED — empty changeset "
        "(nothing was checked; this is not a pass)"
    ) in res.stdout
    assert "GATE PASS" not in res.stdout
    assert not marker.exists()


def test_dependency_audit_path_argument_ignored_not_treated_as_scope(tmp_path):
    # AD-2a — only the one literal token skips. A path argument is ignored, not
    # reinterpreted as "suppresses the run": the audit binary IS spawned.
    marker = tmp_path / "pip_audit_invoked.marker"
    stub = _pip_audit_stub(tmp_path, _DEP_CLEAN_JSON, 0, marker)
    res = _run(_DEPENDENCY, tmp_path, "some/file.py", pip_audit_bin=str(stub))
    assert res.returncode == 0, res.stdout + res.stderr
    assert marker.exists()
    assert "GATE PASS: no blocking dependency vulnerabilities" in res.stdout


def _init_repo_with_suspension(tmp_path: Path, suspended_key: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    (contract_dir / "gate-suspension.md").write_text(
        f"Authorized by: Test Human\nSUSPENDED: {suspended_key} review-by: 2099-01-01\n"
    )


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_dependency_suspension_does_not_suspend_security(tmp_path):
    # TC-D6 / AC-9 — suspending `dependencies` must not suspend `security`.
    # suspension_manager.py resolves contract/gate-suspension.md relative to cwd
    # (TV-9), so cwd=tmp_path with a planted file is enough.
    _init_repo_with_suspension(tmp_path, "dependencies")
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    stub = _pip_audit_stub(tmp_path, _DEP_FINDING_JSON, 1)

    dep = _run(_DEPENDENCY, tmp_path, pip_audit_bin=str(stub))
    assert "GATE SUSPENDED: dependencies" in dep.stdout
    assert dep.returncode == 0

    sec = _run(_SECURITY, tmp_path, "vuln.py")
    assert "HIGH severity bandit finding" in sec.stdout
    assert "GATE SUSPENDED" not in sec.stdout


def test_security_suspension_does_not_suspend_dependency(tmp_path):
    # TC-D7 / AC-9 (converse) — the audit still reports its findings.
    _init_repo_with_suspension(tmp_path, "security")
    (tmp_path / "mod.py").write_text("x = 1\n")

    sec = _run(_SECURITY, tmp_path, "mod.py")
    assert "GATE SUSPENDED: security" in sec.stdout
    assert sec.returncode == 0

    stub = _pip_audit_stub(tmp_path, _DEP_FINDING_JSON, 1)
    dep = _run(_DEPENDENCY, tmp_path, pip_audit_bin=str(stub))
    assert dep.returncode == 1, dep.stdout + dep.stderr
    assert "requests 2.0.0 [CVE-2099-0001]" in dep.stdout
    assert "GATE SUSPENDED" not in dep.stdout


def test_dependency_and_security_not_auto_checkable():
    # TC-D8 / AC-7 — neither key is in AUTO_CHECKABLE_GATES (imported, not
    # re-implemented: a passing dependency scan is not reproducible on demand,
    # and `security` has a reviewer counterpart a scan cannot satisfy).
    sm = load_module_from_path(
        "suspension_manager_1605",
        _REPO / "scripts" / "oversight" / "suspension_manager.py",
    )
    assert "security" not in sm.AUTO_CHECKABLE_GATES
    assert "dependencies" not in sm.AUTO_CHECKABLE_GATES


# ── secret_scan.sh ────────────────────────────────────────────────────────────


def test_secret_scan_no_args_engages_full_scan(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    res = _run(_SECRET, tmp_path)
    assert "no files specified — defaulting" in res.stdout
    # The old fail-open path must be gone when scannable files exist.
    assert "No files to scan" not in res.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_secret_scan_no_args_detects_planted_secret(tmp_path):
    (tmp_path / "creds.py").write_text(_SECRET_PY)
    res = _run(_SECRET, tmp_path)
    assert res.returncode == 1
    assert "potential secret" in res.stdout.lower()


# Validation stamps carry a 64-hex-char content-fingerprint `hash:` line by
# design; detect-secrets flags it as a Hex High Entropy String. CI invokes
# secret_scan.sh with an explicit changed-file list (bypassing the extension
# filters used by --staged/full-scan), so the gate must skip stamp paths
# itself rather than relying on those filters. (#1572)
_STAMP_RELPATH = "scripts/framework/validation-stamps/phase1-deadbeef.stamp"
_STAMP_BODY = (
    "step: phase1\n" "hash: d1a2fa7687ede91e80a8441414f99db7216da56f51154e1d0f80f9fbc5d502ce\n"
)


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_secret_scan_skips_validation_stamp_hash_line(tmp_path):
    stamp = tmp_path / _STAMP_RELPATH
    stamp.parent.mkdir(parents=True)
    stamp.write_text(_STAMP_BODY)
    res = _run(_SECRET, tmp_path, _STAMP_RELPATH)
    assert res.returncode == 0
    assert "GATE PASS" in res.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_secret_scan_still_flags_real_secret_alongside_stamp(tmp_path):
    stamp = tmp_path / _STAMP_RELPATH
    stamp.parent.mkdir(parents=True)
    stamp.write_text(_STAMP_BODY)
    (tmp_path / "creds.py").write_text(_SECRET_PY)
    res = _run(_SECRET, tmp_path, _STAMP_RELPATH, "creds.py")
    assert res.returncode == 1
    assert "potential secret" in res.stdout.lower()
    assert "creds.py" in res.stdout
