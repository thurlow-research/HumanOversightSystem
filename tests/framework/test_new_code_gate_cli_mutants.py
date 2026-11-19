"""Behaviour pins for the new-code gate's command line, found by a mutation run of the gate itself.

`build_parser` and the `command_*` handlers are the glue between the CI workflow and the phases.
The existing tests reach the phases directly or run the CLI as a subprocess (which a mutation run
cannot trace); these call the handlers in process with the phase functions replaced by recorders,
and assert exactly what each handler hands on and writes.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from scripts.framework import new_code_gate as gate


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    made = tmp_path / "made"
    made.mkdir()

    def fake_mkdtemp(prefix=None, **kwargs):
        assert prefix == "ncg-run-" and not kwargs
        path = made / f"{prefix}x"
        path.mkdir(exist_ok=True)
        return str(path)

    monkeypatch.setattr(gate.tempfile, "mkdtemp", fake_mkdtemp)


# --------------------------------------------------------------------------
# build_parser
# --------------------------------------------------------------------------

# phase -> (required string flags, required int flags, optional string flags, optional int flags)
SPEC = {
    "meta": (["--coverage-file", "--out"], [], ["--durations"], []),
    "plan": (
        [
            "--gated-sha",
            "--pr-head-sha",
            "--coverage-file",
            "--meta",
            "--out",
            "--tests-result",
            "--run-id",
        ],
        ["--pr", "--run-attempt"],
        ["--github-output", "--job-start-file"],
        [],
    ),
    "shard": (
        ["--plan-dir", "--gated-sha", "--run-id", "--out"],
        ["--index", "--pr", "--run-attempt"],
        ["--job-start-file"],
        [],
    ),
    "verdict": (
        [
            "--plan-dir",
            "--fragments-dir",
            "--plan-result",
            "--shard-result",
            "--gated-sha",
            "--run-id",
            "--records-out",
            "--out",
            "--summary",
        ],
        ["--pr", "--run-attempt"],
        [],
        [],
    ),
    "_enumerate": (["--file", "--gated-lines-json"], [], [], []),
    "_collect": (["--file"], [], [], []),
}


def full_argv(phase):
    strs, ints, opt_strs, opt_ints = SPEC[phase]
    argv = [phase]
    for flag in strs:
        argv += [flag, "s-" + flag.lstrip("-")]
    for flag in ints:
        argv += [flag, "7"]
    for flag in opt_strs:
        argv += [flag, "o-" + flag.lstrip("-")]
    for flag in opt_ints:
        argv += [flag, "5"]
    return argv


def without(argv, flag):
    out = list(argv)
    at = out.index(flag)
    del out[at : at + 2]
    return out


def parse_fails(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        gate.build_parser().parse_args(argv)
    capsys.readouterr()
    return caught.value.code


def test_parser_program_name_and_phase_is_required(capsys):
    assert gate.build_parser().prog == "new_code_gate"
    assert parse_fails([], capsys) == 2


def test_parser_rejects_an_unknown_phase(capsys):
    assert parse_fails(["bogus"], capsys) == 2


@pytest.mark.parametrize("phase", sorted(SPEC))
def test_parser_accepts_every_flag_of_the_phase_with_typed_values(phase):
    args = gate.build_parser().parse_args(full_argv(phase))
    strs, ints, opt_strs, _ = SPEC[phase]
    assert args.phase == phase
    for flag in strs:
        assert getattr(args, flag.lstrip("-").replace("-", "_")) == "s-" + flag.lstrip("-")
    for flag in ints:
        assert getattr(args, flag.lstrip("-").replace("-", "_")) == 7
    for flag in opt_strs:
        assert getattr(args, flag.lstrip("-").replace("-", "_")) == "o-" + flag.lstrip("-")


@pytest.mark.parametrize(
    "phase,flag",
    [(p, f) for p in sorted(SPEC) for f in SPEC[p][0] + SPEC[p][1]],
)
def test_parser_requires_each_required_flag(phase, flag, capsys):
    assert parse_fails(without(full_argv(phase), flag), capsys) == 2


@pytest.mark.parametrize("phase,flag", [(p, f) for p in sorted(SPEC) for f in SPEC[p][1]])
def test_parser_rejects_a_non_integer_value_for_an_integer_flag(phase, flag, capsys):
    argv = without(full_argv(phase), flag) + [flag, "not-a-number"]
    assert parse_fails(argv, capsys) == 2


@pytest.mark.parametrize("phase", ["meta", "plan", "shard"])
def test_parser_optional_flags_default_to_none(phase):
    args = gate.build_parser().parse_args(
        full_argv(phase)[:1] + sum([[f, v] for f, v in _required_only(phase)], [])
    )
    for flag in SPEC[phase][2]:
        assert getattr(args, flag.lstrip("-").replace("-", "_")) is None


def _required_only(phase):
    argv = full_argv(phase)[1:]
    optional = set(SPEC[phase][2])
    pairs = [(argv[i], argv[i + 1]) for i in range(0, len(argv), 2)]
    return [(f, v) for f, v in pairs if f not in optional]


def test_parser_run_defaults_and_flags(capsys):
    args = gate.build_parser().parse_args(["run"])
    assert (args.base, args.keep_workspace, args.only_shard) == ("origin/main", False, None)
    args = gate.build_parser().parse_args(
        ["run", "--base", "main", "--keep-workspace", "--only-shard", "3"]
    )
    assert (args.base, args.keep_workspace, args.only_shard) == ("main", True, 3)
    assert parse_fails(["run", "--only-shard", "three"], capsys) == 2


def test_parser_hidden_phases_are_not_listed_in_help():
    text = gate.build_parser().format_help()
    assert "_enumerate" not in text.split("{")[0] and "plan" in text and "verdict" in text


# --------------------------------------------------------------------------
# command_meta
# --------------------------------------------------------------------------


def test_command_meta_passes_its_arguments_to_build_meta_and_writes_the_result(
    tmp_path, monkeypatch
):
    seen = {}

    def fake_build_meta(repo, coverage_file, environ, durations):
        seen.update(repo=repo, coverage=coverage_file, environ=environ, durations=durations)
        return {"meta": 1}

    monkeypatch.setattr(gate, "build_meta", fake_build_meta)
    args = gate.build_parser().parse_args(
        ["meta", "--coverage-file", "cov", "--out", "out/meta.json", "--durations", "dur.json"]
    )
    assert gate.command_meta(args) == 0
    assert seen == {
        "repo": Path.cwd(),
        "coverage": Path("cov"),
        "environ": os.environ,
        "durations": Path("dur.json"),
    }
    assert json.loads(Path("out/meta.json").read_text(encoding="utf-8")) == {"meta": 1}


def test_command_meta_without_durations_passes_none(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        gate, "build_meta", lambda repo, cov, env, durations: seen.update(d=durations) or {}
    )
    args = gate.build_parser().parse_args(["meta", "--coverage-file", "c", "--out", "o.json"])
    gate.command_meta(args)
    assert seen == {"d": None}


# --------------------------------------------------------------------------
# command_plan and command_shard
# --------------------------------------------------------------------------


@pytest.fixture
def phases(monkeypatch):
    calls = {"sigterm": 0}
    monkeypatch.setattr(
        gate, "install_sigterm_handler", lambda: calls.update(sigterm=calls["sigterm"] + 1)
    )
    monkeypatch.setattr(gate, "installed_versions", lambda: {"mutmut": "9.9"})
    monkeypatch.setattr(gate, "python_version", lambda: "3.99.0")
    return calls


def plan_args(*extra):
    return gate.build_parser().parse_args(
        [
            "plan",
            "--gated-sha",
            "G",
            "--pr-head-sha",
            "H",
            "--pr",
            "12",
            "--coverage-file",
            "cov",
            "--meta",
            "meta.json",
            "--out",
            "plan/new-code-plan.json",
            "--tests-result",
            "success",
            "--run-id",
            "R",
            "--run-attempt",
            "2",
            *extra,
        ]
    )


def test_command_plan_hands_every_option_to_plan_and_writes_its_document(phases, monkeypatch):
    seen = {}

    def fake_plan(opts, runner, clock):
        seen.update(opts=opts, runner=runner, clock=clock)
        return {"N": 2}, 0

    monkeypatch.setattr(gate, "plan", fake_plan)
    code = gate.command_plan(plan_args("--job-start-file", "js.txt"))
    assert code == 0 and phases["sigterm"] == 1
    opts = seen["opts"]
    assert opts == gate.PlanOptions(
        repo=Path.cwd(),
        gated_sha="G",
        pr_head_sha="H",
        pr=12,
        coverage_file=Path("cov"),
        meta_path=Path("meta.json"),
        tests_result="success",
        run_id="R",
        run_attempt=2,
        mode="ci",
        base_ref=None,
        installed={"mutmut": "9.9"},
        python="3.99.0",
        python_exe=sys.executable,
        environ=dict(os.environ),
        keep_workspace=False,
        job_start_file=Path("js.txt"),
        github_output=None,
    )
    assert isinstance(seen["runner"], gate.SubprocessRunner)
    assert isinstance(seen["clock"], gate.Clock)
    assert json.loads(Path("plan/new-code-plan.json").read_text(encoding="utf-8")) == {"N": 2}


def test_command_plan_appends_the_job_outputs_when_the_plan_succeeds(phases, monkeypatch):
    monkeypatch.setattr(gate, "plan", lambda opts, runner, clock: ({"N": 3}, 0))
    out = Path("gh-output")
    out.write_text("keep=1\n", encoding="utf-8")
    code = gate.command_plan(plan_args("--github-output", str(out)))
    assert code == 0
    assert out.read_text(encoding="utf-8") == "keep=1\ncount=3\nshards=[1,2,3]\n"


def test_command_plan_writes_no_job_outputs_when_the_plan_failed(phases, monkeypatch):
    monkeypatch.setattr(gate, "plan", lambda opts, runner, clock: ({"N": 3}, 3))
    out = Path("gh-output")
    code = gate.command_plan(plan_args("--github-output", str(out)))
    assert code == 3 and not out.exists()
    assert Path("plan/new-code-plan.json").exists()


def test_command_plan_with_no_output_file_writes_no_job_outputs(phases, monkeypatch):
    monkeypatch.setattr(gate, "plan", lambda opts, runner, clock: ({"N": 3}, 0))

    def boom(*args):
        raise AssertionError("job outputs written without a file")

    monkeypatch.setattr(gate, "write_job_outputs", boom)
    assert gate.command_plan(plan_args()) == 0


def test_command_shard_hands_every_option_to_run_shard_and_writes_the_fragment(phases, monkeypatch):
    seen = {}

    def fake_run_shard(opts, runner, clock):
        seen.update(opts=opts, runner=runner, clock=clock)
        return {"fragment": True}, 1

    monkeypatch.setattr(gate, "run_shard", fake_run_shard)
    args = gate.build_parser().parse_args(
        [
            "shard",
            "--index",
            "2",
            "--plan-dir",
            "pd",
            "--gated-sha",
            "G",
            "--pr",
            "12",
            "--run-id",
            "R",
            "--run-attempt",
            "4",
            "--out",
            "frag/f.json",
            "--job-start-file",
            "js.txt",
        ]
    )
    assert gate.command_shard(args) == 1 and phases["sigterm"] == 1
    assert seen["opts"] == gate.ShardOptions(
        repo=Path.cwd(),
        gated_sha="G",
        pr=12,
        run_id="R",
        run_attempt=4,
        mode="ci",
        index=2,
        plan_dir=Path("pd"),
        installed={"mutmut": "9.9"},
        python="3.99.0",
        python_exe=sys.executable,
        environ=dict(os.environ),
        keep_workspace=False,
        job_start_file=Path("js.txt"),
    )
    assert isinstance(seen["runner"], gate.SubprocessRunner)
    assert isinstance(seen["clock"], gate.Clock)
    assert json.loads(Path("frag/f.json").read_text(encoding="utf-8")) == {"fragment": True}


# --------------------------------------------------------------------------
# command_verdict
# --------------------------------------------------------------------------


def test_command_verdict_hands_the_inputs_to_verdict_and_returns_its_code(monkeypatch):
    seen = {}

    def fake_verdict(inputs, records_out, out, summary, clock):
        seen.update(inputs=inputs, records_out=records_out, out=out, summary=summary, clock=clock)
        return 4

    monkeypatch.setattr(gate, "verdict", fake_verdict)
    args = gate.build_parser().parse_args(full_argv("verdict"))
    assert gate.command_verdict(args) == 4
    assert seen["inputs"] == gate.VerdictInputs(
        plan_dir=Path("s-plan-dir"),
        fragments_dir=Path("s-fragments-dir"),
        plan_result="s-plan-result",
        shard_result="s-shard-result",
        gated_sha="s-gated-sha",
        pr=7,
        run_id="s-run-id",
        run_attempt=7,
    )
    assert (seen["records_out"], seen["out"], seen["summary"]) == (
        Path("s-records-out"),
        Path("s-out"),
        Path("s-summary"),
    )
    assert isinstance(seen["clock"], gate.Clock)


# --------------------------------------------------------------------------
# command_run and command_run_partial
# --------------------------------------------------------------------------


def run_args(*extra):
    return gate.build_parser().parse_args(["run", *extra])


def test_command_run_writes_records_and_verdict_and_prints_the_summary(
    phases, monkeypatch, capsys, tmp_path
):
    seen = {}
    opts = object()
    monkeypatch.setattr(gate, "local_options", lambda args, repo: seen.update(repo=repo) or opts)
    result = gate.LocalRun({"r": 1}, {"v": 2}, "SUMMARY TEXT", 1, None)

    def fake_run_local(o, runner, clock, out_dir):
        seen.update(opts=o, runner=runner, clock=clock, out_dir=out_dir)
        return result

    monkeypatch.setattr(gate, "run_local", fake_run_local)
    assert gate.command_run(run_args()) == 1
    assert seen["repo"] == Path.cwd() and seen["opts"] is opts and phases["sigterm"] == 1
    assert isinstance(seen["runner"], gate.SubprocessRunner)
    assert isinstance(seen["clock"], gate.Clock)
    out_dir = seen["out_dir"]
    assert out_dir.name == "ncg-run-x"
    assert json.loads((out_dir / gate.RECORDS_FILENAME).read_text(encoding="utf-8")) == {"r": 1}
    assert json.loads((out_dir / gate.VERDICT_FILENAME).read_text(encoding="utf-8")) == {"v": 2}
    captured = capsys.readouterr()
    assert captured.out == "SUMMARY TEXT\n"
    assert captured.err == f"records and verdict written to {out_dir}\n"


def test_command_run_with_only_shard_runs_the_partial_path_and_never_a_gate_result(
    phases, monkeypatch, capsys
):
    opts = object()
    monkeypatch.setattr(gate, "local_options", lambda args, repo: opts)
    fragment = {"index": 2}
    shard_run = gate.ShardRun(
        {"N": 4, "internal_errors": [{"code": "c1", "message": "m1"}]}, 0, [fragment], True
    )
    seen = {}

    def fake_run_shards(o, runner, clock, out_dir, only):
        seen.update(opts=o, runner=runner, clock=clock, only=only)
        return shard_run

    monkeypatch.setattr(gate, "run_shards", fake_run_shards)
    monkeypatch.setattr(gate.ncs, "fragment_summary", lambda f: f"FRAGMENT {f['index']}")

    def boom(*args):
        raise AssertionError("a partial run produced a gate result")

    monkeypatch.setattr(gate, "run_local", boom)
    assert gate.command_run(run_args("--only-shard", "2")) == 3
    assert seen["opts"] is opts and seen["only"] == 2
    assert isinstance(seen["runner"], gate.SubprocessRunner)
    assert isinstance(seen["clock"], gate.Clock)
    captured = capsys.readouterr()
    assert captured.out == "FRAGMENT 2\nplan: c1: m1\n"
    assert captured.err == "partial run: shard 2 of 4 is not a gate result\n"


# --------------------------------------------------------------------------
# command_enumerate and command_collect
# --------------------------------------------------------------------------


def test_command_enumerate_reads_the_gated_lines_and_prints_the_child_result(monkeypatch, capsys):
    Path("lines.json").write_text("[3, 4]", encoding="utf-8")
    seen = {}

    def fake_enumerate(file, lines, root):
        seen.update(file=file, lines=lines, root=root)
        return {"names": ["a"]}

    monkeypatch.setattr(gate, "enumerate_child", fake_enumerate)
    args = gate.build_parser().parse_args(
        ["_enumerate", "--file", "pkg/m.py", "--gated-lines-json", "lines.json"]
    )
    assert gate.command_enumerate(args) == 0
    assert seen == {"file": "pkg/m.py", "lines": [3, 4], "root": Path.cwd()}
    assert json.loads(capsys.readouterr().out) == {"names": ["a"]}


def test_command_collect_prints_the_child_result(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(
        gate, "collect_child", lambda file, root: seen.update(file=file, root=root) or {"s": 1}
    )
    args = gate.build_parser().parse_args(["_collect", "--file", "pkg/m.py"])
    assert gate.command_collect(args) == 0
    assert seen == {"file": "pkg/m.py", "root": Path.cwd()}
    assert json.loads(capsys.readouterr().out) == {"s": 1}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def test_main_dispatches_the_phase_and_maps_failures_to_exit_three(monkeypatch, capsys):
    monkeypatch.setitem(gate.HANDLERS, "_collect", lambda args: 0)
    assert gate.main(["_collect", "--file", "x.py"]) == 0

    def gate_error(args):
        raise gate.GateError("stop here")

    monkeypatch.setitem(gate.HANDLERS, "_collect", gate_error)
    assert gate.main(["_collect", "--file", "x.py"]) == 3
    assert capsys.readouterr().err == "new_code_gate: stop here\n"

    def crash(args):
        raise ValueError("boom")

    monkeypatch.setitem(gate.HANDLERS, "_collect", crash)
    assert gate.main(["_collect", "--file", "x.py"]) == 3
    assert capsys.readouterr().err == "new_code_gate: internal error: ValueError: boom\n"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def test_clock_epoch_is_whole_seconds_since_the_unix_epoch():
    import time

    before = int(time.time())
    got = gate.Clock().epoch()
    after = int(time.time())
    assert isinstance(got, int) and before <= got <= after
