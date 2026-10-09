"""
Tests for scripts/automation/dimension_sweep_cli.py — the observation-only
measurement runner, #1643 W6 (docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md
Amendment G, T6.01-T6.29).

Every test drives `main(argv, repo_root=<tmp repo>)` in process against a `tmp_path` git
repository holding a copy of the registry, the agents and the postures, so no test writes
into the real `audit/log/` (TD-VF-43). The primitive is reached through one seam,
`_run_primitive`, which tests replace with canned W1 documents. Two autouse fixtures are
mandatory: one clears the nested-session environment (the inner loop runs inside worker
sessions and overseer cycles), and one puts a `claude` tripwire on PATH. None of these
tests is marked `slow` or `integration`.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

import scripts.automation.agent_invoke_cli as aic
import scripts.automation.dimension_sweep_cli as sweep
from scripts.automation.lib import dimension_registry as dr

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = "base"


@pytest.fixture(autouse=True)
def _clean_nested_session_env(monkeypatch):
    for var in ("HOS_CYCLE_ROLE", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _claude_tripwire(monkeypatch, tmp_path_factory):
    bin_dir = tmp_path_factory.mktemp("tripwire")
    sentinel = bin_dir / "SENTINEL"
    stub = bin_dir / "claude"
    stub.write_text(f"#!/bin/sh\necho launched > {sentinel}\nexit 99\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    yield
    assert not sentinel.exists(), "a test launched a real claude process"


def _real_measurement_files() -> int:
    # Only the two event families this module could pollute: concurrent cron cycles write
    # other records into the real tree, so counting every *.json would flake.
    log = REPO_ROOT / "audit" / "log"
    if not log.is_dir():
        return 0
    patterns = ("*dimension-measurement*.json", "*agent-invocation*.json")
    return sum(1 for pattern in patterns for _ in log.rglob(pattern))


@pytest.fixture(scope="module", autouse=True)
def _real_audit_tree_untouched():
    before = _real_measurement_files()
    yield
    assert _real_measurement_files() == before


# --------------------------------------------------------------------------- #
# fixtures and helpers
# --------------------------------------------------------------------------- #


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=60
    )
    return done.stdout.strip()


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _init_base_repo(root: Path) -> Path:
    """Build the identical base content, the `base` commit and the BASE tag from scratch.

    `--template=` keeps git from copying ~8 KB of `.git/hooks` samples into every repo.
    """
    root.mkdir(parents=True)
    _git(root, "init", "-q", "--template=", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    shutil.copytree(REPO_ROOT / "contract" / "dimensions", root / "contract" / "dimensions")
    shutil.copy(REPO_ROOT / "contract" / "resolved-packs.txt", root / "contract")
    shutil.copytree(REPO_ROOT / ".claude" / "agents", root / ".claude" / "agents")
    core_yaml = (root / "contract" / "dimensions" / "core.yaml").read_text()
    for tool in re.findall(r"^\s+(?:- |tool: )(scripts/\S+\.sh)$", core_yaml, re.MULTILINE):
        stub = root / tool
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    (root / "bootstrap").mkdir()
    shutil.copy2(REPO_ROOT / "bootstrap" / "query_issues.sh", root / "bootstrap")
    (root / "README.md").write_text("base\n")
    _commit(root, "base")
    _git(root, "tag", BASE)
    return root


# The module-scoped base repo `make_repo` clones from (#2054): ~45 tests used to rebuild it with
# `git init` + two commits each (~1.2 MiB per test dir). Bound by `_base_repo_template`.
_TEMPLATE: Path | None = None


@pytest.fixture(scope="module", autouse=True)
def _base_repo_template(tmp_path_factory):
    global _TEMPLATE
    _TEMPLATE = _init_base_repo(tmp_path_factory.mktemp("sweep-template") / "base")
    yield
    _TEMPLATE = None


def make_repo(root: Path, files: dict[str, str]) -> Path:
    """A repo at `root` holding the base commit (tagged BASE) plus one `change` commit.

    Clones the module's base template when bound; otherwise (variant bases, or use outside the
    fixture) builds the base from scratch.
    """
    if _TEMPLATE is None:
        _init_base_repo(root)
    else:
        root.parent.mkdir(parents=True, exist_ok=True)
        _git(_TEMPLATE, "clone", "-q", "--local", "--template=", str(_TEMPLATE), str(root))
        _git(root, "config", "user.email", "t@example.com")
        _git(root, "config", "user.name", "t")
        _git(root, "config", "commit.gpgsign", "false")
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _commit(root, "change")
    return root


@pytest.fixture
def repo(tmp_path) -> Path:
    return make_repo(tmp_path / "repo", {"src/a.py": "x = 1\n", "docs/x.md": "doc\n"})


def _records(root: Path, event: str | None = None) -> list[dict]:
    out = []
    for path in sorted((root / "audit" / "log").rglob("*.json")):
        record = json.loads(path.read_text())
        if event is None or record.get("event") == event:
            out.append(record)
    return out


def _records_start_files(root: Path) -> list[Path]:
    return list((root / "audit" / "log").rglob("*dimension-measurement-start*.json"))


def _doc(
    *,
    outcome="completed",
    detail=None,
    verdict="approve",
    exit_code=0,
    timed_out=False,
    envelope="default",
    findings=(),
    summary="a summary",
    digest="d" * 64,
    duration_ms=1234,
) -> dict:
    if envelope == "default":
        envelope = {
            "result": json.dumps({"verdict": "approve", "findings": [], "summary": "s"}),
            "permission_denials": [],
            "terminal_reason": "completed",
        }
    inv = {
        "started_at": "2026-10-04T14:00:00Z",
        "ended_at": "2026-10-04T14:02:00Z",
        "duration_ms": duration_ms,
        "timeout_seconds": 300,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "model": "sonnet",
        "model_source": "agent_frontmatter",
        "cli_version": "2.1.288",
        "num_turns": 3,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 2,
            "cache_read_input_tokens": 3,
            "output_tokens": 4,
            "service_tier": "extra",
        },
        "total_cost_usd": 0.25,
        "envelope": envelope,
        "envelope_unknown_fields": [],
    }
    return aic.build_document(
        outcome=outcome,
        outcome_detail=detail,
        verdict=verdict,
        summary=summary,
        findings=list(findings),
        attacks=[],
        applicability="applicable",
        applicability_reason="r",
        dimension="code-review",
        lens="code-review",
        binding=sweep.MEASURED_BINDING,
        agent="code-reviewer",
        posture="review-read-only",
        input_block={"input_digest": digest},
        invocation_block=inv,
        observability={"audit_record": "2026/10/x.json", "token_tracker_recorded": False},
    )


def _bytes(doc: dict) -> bytes:
    return (json.dumps(doc) + "\n").encode()


class Seam:
    """Stands in for `_run_primitive`; records every call and the input file it was given."""

    def __init__(self, stdout: bytes | None = None, *, rc=0, stderr=b"", exc=None, root=None):
        self.stdout = _bytes(_doc()) if stdout is None else stdout
        self.rc, self.stderr, self.exc, self.root = rc, stderr, exc, root
        self.calls: list[list[str]] = []
        self.timeouts: list[int] = []
        self.inputs: list[bytes] = []
        self.starts_seen: int | None = None

    def __call__(self, argv, *, timeout_s):
        self.calls.append(argv)
        self.timeouts.append(timeout_s)
        if "--input-file" in argv:
            self.inputs.append(Path(argv[argv.index("--input-file") + 1]).read_bytes())
        if self.root is not None:
            self.starts_seen = len(_records(self.root, sweep.EVENT_START))
        if self.exc is not None:
            raise self.exc
        return self.rc, self.stdout, self.stderr


def install(monkeypatch, seam: Seam) -> Seam:
    monkeypatch.setattr(sweep, "_run_primitive", seam)
    return seam


def measure(root: Path, capsys, *extra: str, base: str = BASE):
    rc = sweep.main(["measure", "--base", base, *extra], repo_root=root)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def result_of(root: Path) -> dict:
    results = _records(root, sweep.EVENT_RESULT)
    assert len(results) == 1, results
    return results[0]


def flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def eq_flag(argv: list[str], name: str) -> list[str]:
    """Values of `--name=<value>` tokens (the hardened `=` form, CWE-88)."""
    prefix = f"{name}="
    return [a[len(prefix) :] for a in argv if a.startswith(prefix)]


EXPECTED_KEYS = set(
    """event schema_version timestamp run_id mode runner_outcome error_code error_detail binding
    entry agent posture registry_digest prompt_template_version base_sha head_sha
    changed_files_count matched_files_count matched_lines_changed input_bytes input_digest
    input_digest_match reused_from primitive_exit_code launched outcome outcome_detail verdict
    terminal_reason_missing findings_count blocking_findings_count duration_ms runner_wall_ms
    timeout_seconds timed_out model cli_version num_turns total_cost_usd usage
    envelope_unknown_fields primitive_audit_record auth_mode permission_denied_tools
    payload_extractable""".split()
)


# --------------------------------------------------------------------------- #
# measure
# --------------------------------------------------------------------------- #


def test_T6_01_happy_path(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam(root=repo))
    rc, out, _ = measure(repo, capsys)
    assert rc == 0, out
    starts = _records(repo, sweep.EVENT_START)
    result = result_of(repo)
    assert len(starts) == 1 and seam.starts_seen == 1
    assert set(result) == EXPECTED_KEYS
    assert json.loads(out) == result
    assert result["runner_outcome"] == "measured" and result["launched"] is True
    assert result["head_sha"] == _git(repo, "rev-parse", "HEAD")
    assert result["base_sha"] == _git(repo, "rev-parse", BASE)
    assert result["matched_files_count"] == 1 and result["changed_files_count"] == 2
    assert result["matched_lines_changed"] == 1
    assert starts[0]["run_id"] == result["run_id"]
    assert result["cli_version"] == "2.1.288" and result["total_cost_usd"] == 0.25
    assert result["usage"] == {
        "input_tokens": 10,
        "cache_creation_input_tokens": 2,
        "cache_read_input_tokens": 3,
        "output_tokens": 4,
    }
    assert result["primitive_audit_record"] == "2026/10/x.json"
    assert result["registry_digest"] == dr.load(repo).digest


def test_T6_02_argv_shape(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    measure(repo, capsys)
    argv = seam.calls[0]
    assert isinstance(argv, list)
    assert argv[:2] == ["bash", str(repo / "bootstrap" / "invoke_agent.sh")]
    assert flag(argv, "--agent") == "code-reviewer"
    assert flag(argv, "--posture") == "review-read-only"
    assert flag(argv, "--timeout") == "300"
    assert flag(argv, "--dimension") == "code-review"
    assert flag(argv, "--binding") == "core:code-review/code"
    assert flag(argv, "--lens") == "code-review"
    assert flag(argv, "--base-sha") == _git(repo, "rev-parse", BASE)
    assert flag(argv, "--head-sha") == _git(repo, "rev-parse", "HEAD")
    assert flag(argv, "--prompt-template-version").startswith("sha256:")
    assert "--input-file" in argv
    assert eq_flag(argv, "--matched-file") == ["src/a.py"]
    assert "--matched-file" not in argv
    assert argv.count("--require-env-auth") == 1
    assert "shell=True" not in Path(sweep.__file__).read_text()


def test_T6_03_registry_is_the_only_source(repo, monkeypatch, capsys):
    core = repo / "contract" / "dimensions" / "core.yaml"
    text = core.read_text()
    start = text.index("id: core:code-review/code")
    end = text.index("- id: core:security/code")
    block = text[start:end]
    block = block.replace("agent: code-reviewer", "agent: security-reviewer")
    block = block.replace("posture: review-read-only", "posture: review-read-only-gh-read")
    block = block.replace("timeout_seconds: 300", "timeout_seconds: 120")
    core.write_text(text[:start] + block + text[end:])
    _commit(repo, "edit registry")
    seam = install(monkeypatch, Seam())
    rc, out, _ = measure(repo, capsys)
    assert rc == 0, out
    argv = seam.calls[0]
    assert flag(argv, "--agent") == "security-reviewer"
    assert flag(argv, "--posture") == "review-read-only-gh-read"
    assert flag(argv, "--timeout") == "120"
    assert result_of(repo)["agent"] == "security-reviewer"


def test_T6_03b_core_binding_cannot_be_suppressed_and_absent_binding_is_recorded(
    repo, monkeypatch, capsys
):
    project = repo / "contract" / "dimensions" / "project.yaml"
    project.write_text(
        project.read_text() + "suppress:\n  - binding: core:code-review/code\n    reason: x\n"
    )
    _commit(repo, "suppress")
    seam = install(monkeypatch, Seam())
    rc, _, _ = measure(repo, capsys)
    assert rc == 1 and not seam.calls
    assert result_of(repo)["runner_outcome"] == "registry_error"
    assert result_of(repo)["error_code"] == "suppress_core"


def test_T6_03c_binding_absent(repo, monkeypatch, capsys):
    monkeypatch.setattr(sweep, "MEASURED_BINDING", "core:code-review/nonexistent")
    seam = install(monkeypatch, Seam())
    rc, _, _ = measure(repo, capsys)
    assert rc == 1 and not seam.calls
    assert result_of(repo)["runner_outcome"] == "binding_absent"
    assert not _records(repo, sweep.EVENT_START)


def test_T6_04_template_version_and_input_prefix(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    measure(repo, capsys)
    template = (repo / "contract/dimensions/prompts/code-review.md").read_bytes()
    argv = seam.calls[0]
    assert flag(argv, "--prompt-template-version") == "sha256:" + sweep._sha256(template)
    assert seam.inputs[0].startswith(template)


def test_T6_05_render_is_deterministic_and_clean(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    measure(repo, capsys)
    text = seam.inputs[0].decode()
    run_id = result_of(repo)["run_id"]
    assert run_id not in text and str(repo) not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}", text)
    assert text.count(sweep.PAYLOAD_INSTRUCTION) == 1
    assert "one of " + ", ".join(aic.SEVERITIES) in text
    assert "Selected files:\n- src/a.py\n" in text
    base_sha, head_sha = _git(repo, "rev-parse", BASE), _git(repo, "rev-parse", "HEAD")
    first = sweep._render_input(b"T\n", base_sha, head_sha, ["b.py", "a.py"])
    assert first == sweep._render_input(b"T\n", base_sha, head_sha, ["a.py", "b.py"])
    severities = ", ".join(aic.SEVERITIES)
    literal = (
        "T\n"
        "\n## Changes under review\n"
        "\n"
        f"Base commit: {base_sha}\n"
        f"Head commit: {head_sha}\n"
        f"Inspect each selected file's change with: git diff {base_sha}...{head_sha} -- <path>\n"
        "\n"
        "Selected files:\n"
        "- a.py\n"
        "- b.py\n"
        "\n## Response format\n"
        "\n"
        "Respond with exactly one JSON object and nothing else.\n"
        "\n"
        "- `verdict` is one of `approve` or `request_changes`.\n"
        "- `findings` is a list. Each finding has `severity` (one of "
        f"{severities}), `file`, `line`, `category` and `description`.\n"
        "- `summary` is a string.\n"
        "- The keys `applicability`, `outcome`, `input` and `invocation` must not appear.\n"
    )
    assert first == literal.encode()


def test_T6_06_not_applicable(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path / "r", {"docs/x.md": "doc\n"})
    seam = install(monkeypatch, Seam(_bytes(_doc())))
    rc, _, _ = measure(root, capsys)
    assert rc == 0
    argv = seam.calls[0]
    assert "--not-applicable" not in argv and "--input-file" not in argv
    assert "matched no changed file" in eq_flag(argv, "--not-applicable")[0]
    assert result_of(root)["runner_outcome"] == "not_applicable"
    assert not _records(root, sweep.EVENT_START)


def test_T6_07_timeout_is_a_measurement(repo, monkeypatch, capsys):
    doc = _doc(
        outcome="invocation_failed",
        detail="timeout",
        verdict="error",
        exit_code=None,
        timed_out=True,
        envelope=None,
    )
    install(monkeypatch, Seam(_bytes(doc)))
    rc, _, _ = measure(repo, capsys)
    result = result_of(repo)
    assert rc == 0
    assert result["runner_outcome"] == "measured" and result["timed_out"] is True
    assert result["launched"] is True and result["outcome_detail"] == "timeout"


def _fixture_result(run_id: str, ts: str, **over) -> dict:
    rec = sweep._blank_record(run_id, "require-env-auth")
    rec.update(timestamp=ts, runner_outcome="measured")
    rec.update(over)
    return rec


def test_T6_08_terminal_reason_denominator(repo, monkeypatch, capsys):
    doc = _doc(outcome="invocation_failed", detail="terminal_reason_missing", verdict="error")
    install(monkeypatch, Seam(_bytes(doc)))
    assert measure(repo, capsys)[0] == 0
    assert result_of(repo)["terminal_reason_missing"] is True
    assert sweep.main(["report"], repo_root=repo) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["terminal_reason_missing_count"] == 1 and report["launched"] == 1
    assert report["terminal_reason_evaluated"] == 1
    assert (
        "dimension_sweep: terminal_reason_missing observed 1/1 launched — ADR-1643 §9.2: "
        "A4 reverts to tolerating absence; route to architect\n"
    ) == captured.err


def test_T6_08b_zero_count_prints_nothing_and_timeout_does_not_evaluate(tmp_path, capsys):
    root = tmp_path / "audit-only"
    write = lambda rec: sweep._write(rec, root)  # noqa: E731
    for i, detail in enumerate(["timeout", "unparseable", "permission_denied"]):
        write(
            _fixture_result(
                f"r{i}", f"2026-10-01T00:00:0{i}Z", launched=True, outcome_detail=detail
            )
        )
    assert sweep.main(["report"], repo_root=root) == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["launched"] == 3 and report["terminal_reason_evaluated"] == 1
    assert captured.err == ""

    only_timeouts = tmp_path / "timeouts"
    sweep._write(
        _fixture_result("t", "2026-10-01T00:00:00Z", launched=True, outcome_detail="timeout"),
        only_timeouts,
    )
    assert sweep.main(["report"], repo_root=only_timeouts) == 0
    err = capsys.readouterr().err
    assert (
        "dimension_sweep: terminal_reason evaluated on 0 runs — "
        "ADR-1643 §9.2 residual not yet discharged\n"
    ) == err


def test_T6_08c_runner_timeout_is_not_launched(tmp_path, capsys):
    root = tmp_path / "rt"
    sweep._write(
        _fixture_result("ok", "2026-10-01T00:00:01Z", launched=True, outcome_detail=None), root
    )
    sweep._write(
        _fixture_result(
            "rt", "2026-10-01T00:00:02Z", runner_outcome="runner_timeout", launched=True
        ),
        root,
    )
    assert sweep.main(["report"], repo_root=root) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["runs"] == 2 and report["by_runner_outcome"] == {
        "measured": 1,
        "runner_timeout": 1,
    }
    assert report["launched"] == 1 and report["terminal_reason_evaluated"] == 1
    assert report["by_outcome_detail"] == {"null": 1}


def test_T6_09_usage_limit(repo, monkeypatch, capsys):
    doc = _doc(outcome="invocation_failed", detail="usage_limit", verdict="error")
    line = b"agent_invoke: usage limit reached \xe2\x80\x94 nested invocation stopped\n"
    install(monkeypatch, Seam(_bytes(doc), stderr=line))
    rc, _, err = measure(repo, capsys)
    assert rc == 0 and err == line.decode()
    sweep.main(["report"], repo_root=repo)
    assert json.loads(capsys.readouterr().out)["usage_limit_count"] == 1


def test_T6_10_primitive_no_document(repo, monkeypatch, capsys):
    install(monkeypatch, Seam(b"", rc=1, stderr=b"x" * 2000 + b"boom"))
    rc, out, _ = measure(repo, capsys)
    result = result_of(repo)
    assert rc == 1 and json.loads(out) == result
    assert result["runner_outcome"] == "primitive_no_document"
    assert result["error_code"] == "exit_1"
    assert len(result["error_detail"]) <= 500 and result["error_detail"].endswith("boom")
    assert result["outcome"] is None and result["launched"] is False


@pytest.mark.parametrize(
    "stdout",
    [b'{"schema": "x"}\n{"schema": "y"}\n', b"not json", _bytes({"schema": "other"})],
)
def test_T6_11_primitive_bad_output(repo, monkeypatch, capsys, stdout):
    install(monkeypatch, Seam(stdout, rc=0))
    rc, _, _ = measure(repo, capsys)
    assert rc == 1 and result_of(repo)["runner_outcome"] == "primitive_bad_output"
    assert len(_records(repo, sweep.EVENT_START)) == 1


def test_T6_12_runner_timeout_kills_process_group(repo, monkeypatch, capsys, tmp_path):
    pidfile = tmp_path / "pid"
    stub = repo / "bootstrap" / "invoke_agent.sh"
    stub.parent.mkdir(exist_ok=True)
    # A detached background member that ignores SIGTERM: only an unconditional group
    # SIGKILL (TD §G.13 item 6) removes it once the leader has exited.
    stub.write_text(
        f"#!/bin/bash\necho $$ > {pidfile}\n"
        "(trap '' TERM; exec sleep 60) >/dev/null 2>&1 </dev/null &\n"
        "sleep 60\n"
    )
    monkeypatch.setattr(sweep, "_RUNNER_TIMEOUT_OVERRIDE_S", 1)
    monkeypatch.setattr(sweep, "_KILL_GRACE_S", 1)
    began = time.monotonic()
    rc, _, _ = measure(repo, capsys)
    assert time.monotonic() - began < 5
    assert rc == 1 and result_of(repo)["runner_outcome"] == "runner_timeout"
    pgid = int(pidfile.read_text())
    for _ in range(40):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("a process-group member survived the runner timeout")


def test_T6_13_registry_error(repo, monkeypatch, capsys):
    (repo / "contract/dimensions/core.yaml").write_text("schema: [unterminated\n")
    _commit(repo, "corrupt")
    with pytest.raises(dr.RegistryError) as expected:
        dr.load(repo)
    seam = install(monkeypatch, Seam())
    rc, _, _ = measure(repo, capsys)
    result = result_of(repo)
    assert rc == 1 and not seam.calls
    assert result["runner_outcome"] == "registry_error"
    assert result["error_code"] == expected.value.code


def test_T6_14_git_error_and_nul_separated_paths(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    rc, _, _ = measure(repo, capsys, base="no-such-ref")
    assert rc == 1 and not seam.calls
    assert result_of(repo)["runner_outcome"] == "git_error"
    assert result_of(repo)["error_code"] == "git_failed"

    shutil.rmtree(repo / "audit")
    (repo / "src" / "é.py").write_text("y = 2\n")
    _commit(repo, "non-ascii")
    rc, out, _ = measure(repo, capsys)
    assert rc == 0, out
    matched = eq_flag(seam.calls[0], "--matched-file")
    assert matched == ["src/a.py", "src/é.py"]


def test_T6_14_numstat_rename_and_binary_entries():
    out = b"1\t2\t\0old.py\0new.py\0-\t-\tbin.png\0" + "3\t0\tsrc/é.py\0".encode()
    assert sweep._parse_numstat(out) == {"new.py": 3, "bin.png": 0, "src/é.py": 3}
    with pytest.raises(sweep._Fail):
        sweep._parse_numstat(b"garbage\0")
    with pytest.raises(sweep._Fail):
        sweep._parse_numstat(b"1\t2\t\0only-old\0")


def test_T6_14_rename_is_matched_under_its_new_name(repo, monkeypatch, capsys):
    (repo / "src" / "old.py").write_text("a\nb\nc\nd\ne\n")
    _commit(repo, "add old")
    _git(repo, "tag", "mid")
    _git(repo, "mv", "src/old.py", "src/new.py")
    (repo / "src" / "new.py").write_text("a\nb\nc\nd\nZ\n")
    _commit(repo, "rename")
    seam = install(monkeypatch, Seam())
    rc, out, _ = measure(repo, capsys, base="mid")
    assert rc == 0, out
    matched = eq_flag(seam.calls[0], "--matched-file")
    assert matched == ["src/new.py"]
    assert result_of(repo)["matched_lines_changed"] == 2


def test_T6_14_pl1_bad_changed_file(repo, monkeypatch, capsys):
    (repo / "src" / "we\nird.py").write_text("z = 3\n")
    _commit(repo, "newline in path")
    seam = install(monkeypatch, Seam())
    rc, _, _ = measure(repo, capsys)
    result = result_of(repo)
    assert rc == 1 and not seam.calls
    assert result["runner_outcome"] == "git_error" and result["error_code"] == "bad_changed_file"


def test_T6_14b_option_like_base_is_a_usage_error(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    rc = sweep.main(["measure", "--base=--output=x"], repo_root=repo)
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert "must be a ref" in err
    assert rc == 2 and out == "" and err.count("\n") == 1 and not seam.calls
    assert not (repo / "audit").exists()


def test_T6_15_dirty_tree(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    (repo / "src" / "a.py").write_text("x = 2\n")
    rc, _, _ = measure(repo, capsys)
    assert rc == 1 and not seam.calls
    assert result_of(repo)["runner_outcome"] == "dirty_tree"
    (repo / "src" / "a.py").write_text("x = 1\n")
    (repo / "scratch.txt").write_text("untracked\n")
    assert measure(repo, capsys)[0] == 0 and seam.calls


@pytest.mark.parametrize(
    ("var", "value"),
    [("HOS_CYCLE_ROLE", "worker"), ("CLAUDECODE", "1"), ("CLAUDE_CODE_ENTRYPOINT", "cli")],
)
def test_T6_16_refusals(repo, monkeypatch, capsys, var, value):
    monkeypatch.setenv(var, value)
    seam = install(monkeypatch, Seam())

    def no_git(*a, **k):
        raise AssertionError("a git or subprocess call was made")

    monkeypatch.setattr(subprocess, "Popen", no_git)
    rc, out, err = measure(repo, capsys)
    assert rc == 2 and out == "" and not seam.calls
    assert err.count("\n") == 1 and var in err and err.startswith("dimension_sweep: refused:")
    assert not (repo / "audit").exists()


def test_T6_17_auth_default_and_keychain_opt_out(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    measure(repo, capsys)
    assert seam.calls[0].count("--require-env-auth") == 1
    assert result_of(repo)["auth_mode"] == "require-env-auth"
    shutil.rmtree(repo / "audit")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "dummy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    measure(repo, capsys, "--allow-keychain-auth")
    assert "--require-env-auth" not in seam.calls[1]
    assert result_of(repo)["auth_mode"] == "keychain"
    shutil.rmtree(repo / "audit")
    measure(repo, capsys)
    assert seam.calls[2].count("--require-env-auth") == 1


def test_T6_18_reuse(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    measure(repo, capsys)
    first = result_of(repo)
    rc, out, _ = measure(repo, capsys)
    assert rc == 0 and len(seam.calls) == 1
    reused = json.loads(out)
    assert reused["runner_outcome"] == "reused" and reused["launched"] is False
    assert reused["input_digest"] == first["input_digest"]
    assert (
        reused["reused_from"].endswith(".json") and "dimension-measurement" in reused["reused_from"]
    )
    assert (repo / "audit" / "log" / reused["reused_from"]).is_file()

    shutil.rmtree(repo / "audit")
    planted = _fixture_result("p", "2026-10-01T00:00:00Z", input_digest=first["input_digest"])
    planted["runner_outcome"] = "dirty_tree"
    sweep._write(planted, repo)
    assert measure(repo, capsys)[0] == 0
    assert len(seam.calls) == 2


def test_T6_19_digest_agreement_with_the_real_l2(repo, monkeypatch, capsys):
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "permission_denials": [],
        "subagent_stats": {"refused": {"depth_limit": 0, "concurrency_limit": 0}},
        "num_turns": 1,
        "session_id": "s",
        "total_cost_usd": 0.1,
        "usage": {"input_tokens": 2, "output_tokens": 9},
        "result": json.dumps({"verdict": "approve", "findings": [], "summary": "ok"}),
    }
    proc = aic.ProcResult(
        rc=0,
        timed_out=False,
        stdout_bytes=json.dumps(envelope).encode(),
        stderr_bytes=b"",
        duration_ms=100,
    )
    run_capped_calls: list[list[str]] = []

    def run_capped_spy(argv, *, stdin_bytes, cwd, timeout_s, grace_s):
        run_capped_calls.append(argv)
        return proc

    monkeypatch.setattr(aic, "run_capped", run_capped_spy)
    monkeypatch.setattr(aic, "_capture_cli_version", lambda: "2.1.271")
    monkeypatch.setattr(aic.shutil, "which", lambda n: "/usr/bin/claude" if n == "claude" else None)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "dummy")
    documents: list[dict] = []

    def real_l2(argv, *, timeout_s):
        sink = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(sink):
            rc = aic.main(argv[2:], repo_root=repo)
        sink.flush()
        raw = sink.buffer.getvalue()  # type: ignore[attr-defined]
        documents.append(json.loads(raw))
        return rc, raw, b""

    monkeypatch.setattr(sweep, "_run_primitive", real_l2)
    rc, _, _ = measure(repo, capsys)
    assert rc == 0 and len(run_capped_calls) == 1
    result = result_of(repo)
    assert documents[0]["outcome"] == "completed"
    assert result["input_digest_match"] is True
    assert result["input_digest"] == documents[0]["input"]["input_digest"]
    assert result["payload_extractable"] is True and result["permission_denied_tools"] == []


def test_T6_20_durability_and_abandoned(repo, monkeypatch, capsys, tmp_path):
    seam = install(monkeypatch, Seam(exc=KeyboardInterrupt(), root=repo))
    with pytest.raises(KeyboardInterrupt):
        sweep.main(["measure", "--base", BASE], repo_root=repo)
    capsys.readouterr()
    assert seam.starts_seen == 1
    result = result_of(repo)
    assert result["runner_outcome"] == "interrupted" and result["error_code"] == "KeyboardInterrupt"

    root = tmp_path / "planted"
    start = {
        "event": sweep.EVENT_START,
        "schema_version": 1,
        "timestamp": "2026-10-01T00:00:00Z",
        "run_id": "orphan",
        "binding": sweep.MEASURED_BINDING,
    }
    sweep._write(start, root)
    assert sweep.main(["report"], repo_root=root) == 0
    assert json.loads(capsys.readouterr().out)["abandoned"] == 1


def test_T6_20b_unwritable_start_record(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    real_write = sweep._write

    def failing_write(event, root):
        if event["event"] == sweep.EVENT_START:
            raise OSError("read-only")
        return real_write(event, root)

    monkeypatch.setattr(sweep, "_write", failing_write)
    rc, out, err = measure(repo, capsys)
    result = json.loads(out)
    assert rc == 1 and not seam.calls
    assert result["runner_outcome"] == "audit_unwritable"
    assert result["error_code"] == "start_record_unwritable" and result["launched"] is False
    assert any(line.startswith("dimension_sweep: record not written:") for line in err.splitlines())
    assert _records(repo, sweep.EVENT_RESULT) == [result]


def test_T6_20c_lock_file_unopenable_is_recorded(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    (repo / common / "hos-w6-measure.lock").mkdir()
    rc, out, _ = measure(repo, capsys)
    result = json.loads(out)
    assert rc == 1 and not seam.calls
    assert result["runner_outcome"] == "git_error" and result["error_code"] == "lock_unopenable"
    assert _records(repo, sweep.EVENT_RESULT) == [result]


def test_T6_20d_input_tempfile_failure_is_recorded(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())

    def boom(*a, **k):
        raise OSError("no space")

    monkeypatch.setattr(sweep.tempfile, "mkstemp", boom)
    rc, out, _ = measure(repo, capsys)
    result = json.loads(out)
    assert rc == 1 and not seam.calls and not _records(repo, sweep.EVENT_START)
    assert result["runner_outcome"] == "audit_unwritable"
    assert result["error_code"] == "input_tempfile_unwritable"


def test_T6_20e_malformed_audit_record_blocks_launch(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    bad = repo / "audit" / "log" / "2026" / "10" / "bad-record.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{")
    rc, out, _ = measure(repo, capsys)
    result = json.loads(out)
    assert rc == 1 and not seam.calls and not _records_start_files(repo)
    assert result["runner_outcome"] == "audit_unwritable"
    assert result["error_code"] == "audit_tree_unreadable"


def test_T6_20f_unreadable_audit_tree_blocks_launch(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())

    def boom(root):
        raise PermissionError("denied")
        yield b""  # pragma: no cover — makes this a generator, like read_stream

    monkeypatch.setattr(sweep._audit_log(), "read_stream", boom)
    rc, out, _ = measure(repo, capsys)
    result = json.loads(out)
    assert rc == 1 and not seam.calls
    assert result["runner_outcome"] == "audit_unwritable"
    assert result["error_code"] == "audit_tree_unreadable"


def test_T6_20g_actionable_failure_echo(repo, monkeypatch, capsys):
    install(monkeypatch, Seam())
    bad = repo / "audit" / "log" / "2026" / "10" / "bad-record.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{")
    rc, out, err = measure(repo, capsys)
    result = json.loads(out)
    assert rc == 1
    assert result["error_detail"].endswith("— repair or move that file and re-run")
    assert "bad-record.json" in result["error_detail"]
    echo = [ln for ln in err.splitlines() if ln.startswith("dimension_sweep: audit_unwritable:")]
    assert echo == [
        f"dimension_sweep: audit_unwritable: audit_tree_unreadable: {result['error_detail']}"
    ]


def test_T6_20h_sigterm_mid_seam_is_an_interrupt(repo, monkeypatch, capsys):
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}

    def seam(argv, *, timeout_s):
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("SIGTERM should have interrupted the seam")

    monkeypatch.setattr(sweep, "_run_primitive", seam)
    with pytest.raises(KeyboardInterrupt):
        sweep.main(["measure", "--base", BASE], repo_root=repo)
    capsys.readouterr()
    result = result_of(repo)
    assert result["runner_outcome"] == "interrupted"
    assert result["error_code"] == "KeyboardInterrupt"
    assert {sig: signal.getsignal(sig) for sig in before} == before


def test_T6_20i_sighup_mid_seam_is_an_interrupt(repo, monkeypatch, capsys):
    def seam(argv, *, timeout_s):
        os.kill(os.getpid(), signal.SIGHUP)
        raise AssertionError("SIGHUP should have interrupted the seam")

    monkeypatch.setattr(sweep, "_run_primitive", seam)
    with pytest.raises(KeyboardInterrupt):
        sweep.main(["measure", "--base", BASE], repo_root=repo)
    capsys.readouterr()
    assert result_of(repo)["runner_outcome"] == "interrupted"


def test_T6_22b_document_out_refuses_existing_file(repo, monkeypatch, capsys, tmp_path):
    install(monkeypatch, Seam())
    target = tmp_path / "existing.json"
    target.write_text("precious")
    rc, _, err = measure(repo, capsys, "--document-out", str(target))
    assert rc == 0 and target.read_text() == "precious"
    assert "--document-out not written" in err


def test_T6_22c_document_out_refuses_symlink_target(repo, monkeypatch, capsys, tmp_path):
    install(monkeypatch, Seam())
    victim = tmp_path / "victim.txt"
    victim.write_text("victim")
    link = tmp_path / "link.json"
    link.symlink_to(victim)
    rc, _, err = measure(repo, capsys, "--document-out", str(link))
    assert rc == 0 and victim.read_text() == "victim" and link.is_symlink()
    assert "--document-out not written" in err
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "does-not-exist")
    shutil.rmtree(repo / "audit")
    measure(repo, capsys, "--document-out", str(dangling))
    assert not (tmp_path / "does-not-exist").exists()


def test_T6_22d_document_out_is_created_private(repo, monkeypatch, capsys, tmp_path):
    install(monkeypatch, Seam())
    target = tmp_path / "fresh.json"
    assert measure(repo, capsys, "--document-out", str(target))[0] == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_T6_22e_document_out_confinement_rechecked_at_write(repo, tmp_path):
    with pytest.raises(OSError, match="inside the repository"):
        sweep._write_document(repo / "x.json", b"{}", repo.resolve())
    assert not (repo / "x.json").exists()


def test_T6_21_unwritable_result_record(repo, monkeypatch, capsys):
    install(monkeypatch, Seam())
    real_write = sweep._write

    def failing_write(event, root):
        if event["event"] == sweep.EVENT_RESULT:
            raise OSError("disk full")
        return real_write(event, root)

    monkeypatch.setattr(sweep, "_write", failing_write)
    rc, out, err = measure(repo, capsys)
    assert rc == 1
    assert json.loads(out)["runner_outcome"] == "measured"
    assert "dimension_sweep: record not written: disk full" in err
    assert not _records(repo, sweep.EVENT_RESULT)


def test_T6_22_no_prose_in_records_and_document_out_confined(repo, monkeypatch, capsys, tmp_path):
    template = repo / "contract/dimensions/prompts/code-review.md"
    template.write_text(template.read_text() + "\nSENTINEL_TEMPLATE\n")
    _commit(repo, "sentinel template")
    envelope = {
        "result": "SENTINEL_RESULT",
        "permission_denials": [
            {"tool_name": "Write", "tool_input": {"file_path": "SENTINEL_TOOLINPUT"}}
        ],
    }
    findings = [{"severity": "high", "file": "a.py", "description": "SENTINEL_FINDING"}]
    doc = _doc(
        outcome="invocation_failed",
        detail="permission_denied",
        verdict="error",
        envelope=envelope,
        findings=findings,
        summary="SENTINEL_SUMMARY",
    )
    seam = install(monkeypatch, Seam(_bytes(doc)))
    outside = tmp_path / "doc.json"
    assert measure(repo, capsys, "--document-out", str(outside))[0] == 0
    assert outside.read_bytes() == _bytes(doc)
    assert b"SENTINEL_TEMPLATE" in seam.inputs[0]
    blob = b"".join(p.read_bytes() for p in (repo / "audit" / "log").rglob("*.json"))
    for sentinel in (
        b"SENTINEL_SUMMARY",
        b"SENTINEL_FINDING",
        b"SENTINEL_RESULT",
        b"SENTINEL_TOOLINPUT",
        b"SENTINEL_TEMPLATE",
    ):
        assert sentinel not in blob
    assert result_of(repo)["permission_denied_tools"] == ["Write"]

    shutil.rmtree(repo / "audit")
    calls_before = len(seam.calls)
    for inside in (repo / "x.json", repo / "sub" / ".." / "x.json", repo):
        rc, out, err = measure(repo, capsys, "--document-out", str(inside))
        assert rc == 2 and out == "" and err.count("\n") == 1
    assert len(seam.calls) == calls_before and not (repo / "audit").exists()
    assert not (repo / "x.json").exists()


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #


def test_T6_23_report_exact_aggregation(tmp_path, capsys):
    root = tmp_path / "agg"

    def add(run_id, second, **over):
        defaults = dict(
            launched=True,
            outcome="invocation_failed",
            timed_out=False,
            payload_extractable=False,
            permission_denied_tools=[],
            terminal_reason_missing=False,
            input_digest_match=True,
            envelope_unknown_fields=[],
        )
        defaults.update(over)
        sweep._write(_fixture_result(run_id, f"2026-10-01T00:00:{second:02d}Z", **defaults), root)

    add(
        "r1",
        1,
        outcome="completed",
        duration_ms=100,
        total_cost_usd=0.1,
        num_turns=3,
        matched_lines_changed=10,
        payload_extractable=True,
        cli_version="2.1.288",
    )
    add(
        "r2",
        2,
        outcome_detail="permission_denied",
        duration_ms=200,
        total_cost_usd=0.2,
        num_turns=5,
        matched_lines_changed=20,
        payload_extractable=True,
        permission_denied_tools=["Write"],
    )
    add(
        "r3",
        3,
        outcome_detail="schema_violation",
        duration_ms=300,
        total_cost_usd=0.3,
        num_turns=7,
        matched_lines_changed=30,
        envelope_unknown_fields=["foo"],
    )
    add(
        "r4",
        4,
        outcome_detail="timeout",
        duration_ms=400,
        matched_lines_changed=40,
        timed_out=True,
        payload_extractable=None,
        permission_denied_tools=None,
    )
    add("r5", 5, launched=False, runner_outcome="not_applicable")
    add("r6", 6, launched=False, runner_outcome="reused", input_digest_match=None)
    add(
        "r7",
        7,
        outcome="completed",
        duration_ms=500,
        total_cost_usd=0.4,
        num_turns=9,
        matched_lines_changed=50,
        payload_extractable=True,
        input_digest_match=False,
        permission_denied_tools=["Bash", "Write"],
        cli_version="2.1.300",
    )
    add(
        "r8",
        8,
        outcome_detail="terminal_reason_missing",
        terminal_reason_missing=True,
        duration_ms=600,
        total_cost_usd=0.5,
        num_turns=2,
        matched_lines_changed=60,
    )
    base_start = {"event": sweep.EVENT_START, "schema_version": 1, "binding": "b"}
    sweep._write({**base_start, "timestamp": "2026-10-01T00:00:00Z", "run_id": "r1"}, root)
    sweep._write({**base_start, "timestamp": "2026-10-01T00:00:00Z", "run_id": "orphan"}, root)
    for i in range(500):
        sweep._write(
            {"event": "agent-invocation", "timestamp": "2026-10-01T00:01:00Z", "n": i}, root
        )

    assert sweep.main(["report"], repo_root=root) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "schema": "hos.dimension-measurement-report",
        "schema_version": 1,
        "binding": "core:code-review/code",
        "since": None,
        "runs": 8,
        "abandoned": 1,
        "by_runner_outcome": {"measured": 6, "not_applicable": 1, "reused": 1},
        "launched": 6,
        "by_outcome_detail": {
            "null": 2,
            "permission_denied": 1,
            "schema_violation": 1,
            "terminal_reason_missing": 1,
            "timeout": 1,
        },
        "terminal_reason_evaluated": 5,
        "terminal_reason_missing_count": 1,
        "usage_limit_count": 0,
        "timed_out_count": 1,
        "input_digest_mismatch_count": 1,
        "payload_extractable_count": 3,
        "by_permission_denied_tool": {"Bash": 1, "Write": 2},
        "duration_ms": {"n": 6, "min": 100, "p50": 300, "p90": 600, "max": 600},
        "duration_ms_completed_only": {"n": 2, "min": 100, "p50": 100, "p90": 500, "max": 500},
        "duration_ms_payload_produced": {"n": 3, "min": 100, "p50": 200, "p90": 500, "max": 500},
        "total_cost_usd": {"n": 5, "min": 0.1, "p50": 0.3, "p90": 0.5, "max": 0.5, "sum": 1.5},
        "num_turns": {"n": 5, "min": 2, "p50": 5, "p90": 9, "max": 9},
        "matched_lines_changed": {"n": 6, "min": 10, "p50": 30, "p90": 60, "max": 60},
        "envelope_unknown_fields": ["foo"],
        "cli_versions": ["2.1.288", "2.1.300"],
    }
    assert "observed 1/5 launched" in captured.err

    assert sweep.main(["report", "--since", "2026-10-02"], repo_root=root) == 0
    assert json.loads(capsys.readouterr().out)["runs"] == 0
    assert sweep.main(["report", "--since", "yesterday"], repo_root=root) == 2


def test_T6_23b_measured_preflight_document_is_not_a_launched_run(tmp_path, capsys):
    # A preflight document is recorded `measured` but never launched a model session
    # (launched False, outcome_detail null). It counts as a run and a measured outcome,
    # and must contribute to no launched-denominator statistic.
    root = tmp_path / "preflight"
    sweep._write(
        _fixture_result(
            "pre",
            "2026-10-01T00:00:01Z",
            launched=False,
            outcome="invocation_failed",
            outcome_detail=None,
            duration_ms=999,
            total_cost_usd=9.0,
            num_turns=99,
            matched_lines_changed=77,
            payload_extractable=True,
            permission_denied_tools=["Write"],
            cli_version="9.9.9",
        ),
        root,
    )
    sweep._write(
        _fixture_result(
            "real",
            "2026-10-01T00:00:02Z",
            launched=True,
            outcome="completed",
            duration_ms=100,
            total_cost_usd=0.1,
            num_turns=3,
            matched_lines_changed=10,
        ),
        root,
    )
    assert sweep.main(["report"], repo_root=root) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["runs"] == 2 and report["by_runner_outcome"] == {"measured": 2}
    assert report["launched"] == 1
    assert report["by_outcome_detail"] == {"null": 1}
    assert report["terminal_reason_evaluated"] == 1
    assert report["payload_extractable_count"] == 0
    assert report["by_permission_denied_tool"] == {}
    assert report["duration_ms"] == {"n": 1, "min": 100, "p50": 100, "p90": 100, "max": 100}
    assert report["total_cost_usd"]["n"] == 1 and report["total_cost_usd"]["sum"] == 0.1
    assert report["num_turns"]["n"] == 1
    assert report["matched_lines_changed"]["n"] == 1


def test_T6_24_report_empty_and_malformed(tmp_path, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    assert sweep.main(["report"], repo_root=root) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["runs"] == 0 and report["duration_ms"] == {"n": 0}
    assert report["total_cost_usd"] == {"n": 0}

    bad = root / "audit" / "log" / "2026" / "10" / "bad-record.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{")
    assert sweep.main(["report"], repo_root=root) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "bad-record.json" in err


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #


def test_T6_25_single_entry(repo, capsys):
    assert sweep.MEASURED_BINDING == "core:code-review/code"
    subparsers = sweep._build_parser()._subparsers._group_actions[0]  # type: ignore[union-attr]
    assert set(subparsers.choices) == {"measure", "report"}
    assert sweep.main(["measure", "--base", BASE, "--binding", "x"], repo_root=repo) == 2
    assert sweep.main([], repo_root=repo) == 2
    assert sweep.main(["sweep"], repo_root=repo) == 2
    capsys.readouterr()


def test_T6_26_observation_only_static():
    path = Path(sweep.__file__)
    source = path.read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {a.name for a in node.names}
    forbidden = {
        "merge_authority",
        "merge_config",
        "pr_readiness",
        "envelope",
        "correlation",
        "overseer_state",
    }
    assert not {part for name in imported for part in name.split(".")} & forbidden
    for name in (
        "post_comment.sh",
        "pr_review.sh",
        "submit_pr.sh",
        "hos-cron",
        "INVOKE_AGENT_PYTHON",
    ):
        assert name not in source
    cron = (REPO_ROOT / "bin" / "hos-cron").read_text()
    assert "dimension_sweep" not in cron and "run_dimensions" not in cron


def test_T6_27_no_deterministic_execution(repo, monkeypatch, capsys):
    seam = install(monkeypatch, Seam())
    argvs: list[list[str]] = []
    real_popen = subprocess.Popen

    def spy(argv, *args, **kwargs):
        argvs.append(list(argv))
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)
    assert measure(repo, capsys)[0] == 0
    argvs += seam.calls
    wrapper = ["bash", str(repo / "bootstrap" / "invoke_agent.sh")]
    assert argvs and all(a[0] == "git" or a[:2] == wrapper for a in argvs)
    tools = dr.load(repo).tools
    assert tools
    joined = [" ".join(a) for a in argvs]
    assert not any(tool in line for tool in tools for line in joined)


def test_T6_28_lock_and_aliases(repo, tmp_path, monkeypatch, capsys):
    import fcntl

    assert aic.matched_files_digest is aic._matched_files_digest
    assert aic.bounded_audit_str is aic._bounded_audit_str
    assert aic.bounded_audit_number is aic._bounded_audit_number
    assert aic.extract_payload is aic._extract_payload
    assert aic.blocking_severities is aic._BLOCKING_SEVERITIES

    seam = install(monkeypatch, Seam())
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    lock_file = (repo / common).resolve() / "hos-w6-measure.lock"
    with open(lock_file, "a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc, _, _ = measure(repo, capsys)
        assert rc == 1 and not seam.calls
        assert result_of(repo)["runner_outcome"] == "lock_held"

        linked = tmp_path / "linked"
        _git(repo, "worktree", "add", "-q", "--detach", str(linked))
        rc, _, _ = measure(linked, capsys)
        assert rc == 1 and not seam.calls
        assert result_of(linked)["runner_outcome"] == "lock_held"
    shutil.rmtree(repo / "audit")
    assert measure(repo, capsys)[0] == 0 and len(seam.calls) == 1


def test_T6_29_diagnostics(repo, monkeypatch, capsys):
    denied = {
        "permission_denials": [
            {"tool_name": "Write", "tool_input": {"content": "x"}},
            {"tool_name": "Write"},
            {"tool_name": "Bash"},
            "junk",
        ],
        "result": json.dumps({"verdict": "approve", "findings": [], "summary": "s"}),
    }
    markdown = {**denied, "result": "## Review\nLooks fine."}
    cases = [
        (denied, ["<malformed>", "Bash", "Write"], True),
        (markdown, ["<malformed>", "Bash", "Write"], False),
        ("default", [], True),
        (None, None, None),
    ]
    root = repo
    for index, (envelope, tools, extractable) in enumerate(cases):
        detail = "permission_denied" if envelope in (denied, markdown) else None
        outcome = "invocation_failed" if detail or envelope is None else "completed"
        doc = _doc(
            outcome=outcome,
            detail=detail or ("timeout" if envelope is None else None),
            envelope=envelope,
            exit_code=0 if envelope is not None else None,
            timed_out=envelope is None,
        )
        install(monkeypatch, Seam(_bytes(doc)))
        shutil.rmtree(root / "audit", ignore_errors=True)
        assert measure(root, capsys)[0] == 0
        result = result_of(root)
        assert result["permission_denied_tools"] == tools, index
        assert result["payload_extractable"] is extractable, index

    rows = [
        _fixture_result(
            "a",
            "2026-10-01T00:00:01Z",
            launched=True,
            duration_ms=10,
            payload_extractable=True,
            permission_denied_tools=["Write"],
        ),
        _fixture_result(
            "b",
            "2026-10-01T00:00:02Z",
            launched=True,
            duration_ms=20,
            payload_extractable=False,
            permission_denied_tools=["Write", "Bash"],
        ),
        _fixture_result(
            "c",
            "2026-10-01T00:00:03Z",
            launched=True,
            duration_ms=30,
            payload_extractable=True,
            permission_denied_tools=[],
        ),
    ]
    shutil.rmtree(root / "audit")
    for row in rows:
        sweep._write(row, root)
    assert sweep.main(["report"], repo_root=root) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["payload_extractable_count"] == 2
    assert report["by_permission_denied_tool"] == {"Bash": 1, "Write": 2}
    assert report["duration_ms_payload_produced"] == {
        "n": 2,
        "min": 10,
        "p50": 10,
        "p90": 30,
        "max": 30,
    }
