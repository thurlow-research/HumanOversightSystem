"""#1944 S1 static guards over bin/hos-usage-poll and bin/lib/usage_pause.py (TD section 9.1)."""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLLER = ROOT / "bin" / "hos-usage-poll"
LIB = ROOT / "bin" / "lib" / "usage_pause.py"
FILES = (POLLER, LIB)


def code_lines(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("#"):
            yield line


def all_code():
    for path in FILES:
        for line in code_lines(path):
            yield path.name, line


def test_no_credential_sourcing_or_unsetting():
    forbidden = [
        r"claude-auth\.env",
        r"CLAUDE_CODE_OAUTH_TOKEN=",
        r"(^|\s)(source|\.)\s+\S*\.config/hos",
        r"env -u",
        r"\bunset\s",
        r"os\.environ\.pop",
        r"del os\.environ",
        r"unsetenv",
        r"\b(Popen|run)\([^)]*\benv=",
    ]
    for name, line in all_code():
        for pat in forbidden:
            assert not re.search(pat, line), (name, pat, line)
    for node in ast.walk(ast.parse(LIB.read_text())):
        if isinstance(node, ast.Call):
            assert not any(k.arg == "env" for k in node.keywords)


def test_poller_and_lib_never_reference_suspend_or_halt():
    for name, line in all_code():
        assert not re.search(r"suspend|halt|projects\.conf", line, re.I), (name, line)


def test_lib_never_uses_hos_config_dir():
    assert "HOS_CONFIG_DIR" not in LIB.read_text()
    assert "HOS_CONFIG_DIR" not in POLLER.read_text()


def test_lib_stdlib_only():
    allowed = {
        "__future__",
        "argparse",
        "dataclasses",
        "datetime",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "shlex",
        "shutil",
        "signal",
        "stat",
        "subprocess",
        "sys",
        "time",
        "typing",
    }
    found = set()
    for node in ast.walk(ast.parse(LIB.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0])
    assert found <= allowed, found - allowed


def test_sandbox_allowwrite_excludes_decision_inputs():
    policy = json.loads((ROOT / "contract" / "sandbox-policy.template.json").read_text())
    allow = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "allowWrite":
                    allow.extend(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(policy)
    assert allow
    targets = [
        "/h/.hos/usage-pause/reading",
        "/h/.config/hos/usage-pause.conf",
        "/var/lib/hos-usage/x",
    ]
    for entry in allow:
        base = entry.replace("__HOME__", "/h")
        for target in targets:
            assert not (target == base or target.startswith(base.rstrip("/") + "/")), (
                entry,
                target,
            )


def test_consumer_files_list_both():
    listed = [
        ln.split("#", 1)[0].strip()
        for ln in (ROOT / "scripts/framework/framework_consumer_files.txt").read_text().splitlines()
    ]
    assert "bin/hos-usage-poll" in listed and "bin/lib/usage_pause.py" in listed
    assert not any(ln.startswith("contrib/") for ln in listed)


def test_test_only_overrides_absent_from_runbook():
    text = (ROOT / "docs" / "CRON-SETUP.md").read_text()
    for name in ("HOS_USAGE_PAUSE_CONF", "HOS_USAGE_PROM_PATH", "HOS_USAGE_KEY_PATH"):
        assert name not in text


def test_one_ssh_call_site():
    for line in code_lines(POLLER):
        assert not re.search(r"(^|[\s;&|(])ssh\s", line), line
    tree = ast.parse(LIB.read_text())
    popen = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) == "Popen"
    ]
    assert len(popen) == 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            first = node.elts[0]
            assert not (
                isinstance(first, ast.Constant) and first.value in ("timeout", "gtimeout")
            ), node.lineno
    for name, line in all_code():
        assert "_TIMEOUT_BIN" not in line and "gtimeout" not in line, (name, line)
        assert not re.search(r"(^|[\s;&|(])timeout\s+-", line), (name, line)
        assert not re.search(r"(^|[\s;&|(])timeout\s+[\"$0-9]", line), (name, line)


def test_staleness_range_nonempty_for_every_interval():
    ns = {}
    exec(compile(LIB.read_text(), str(LIB), "exec"), ns)
    for interval in range(
        ns["POLL_INTERVAL_MIN"], ns["POLL_INTERVAL_MAX"] + 1, ns["POLL_INTERVAL_STEP"]
    ):
        timeout_max = interval - ns["READ_TIMEOUT_MARGIN"]
        assert timeout_max >= ns["READ_TIMEOUT_MIN"]
        assert interval + ns["READ_TIMEOUT_MIN"] < ns["STALENESS_MAX"]


def test_defaults_block_single_and_no_threshold_literals():
    text = LIB.read_text()
    begin = "# ── BEGIN SETTINGS DEFAULTS AND BOUNDS (ADR-1944 A2-10; the only place these numbers appear) ──"
    end = "# ── END SETTINGS DEFAULTS AND BOUNDS ──"
    assert text.count(begin) == 1 and text.count(end) == 1
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if (
                    isinstance(operand, ast.Constant)
                    and isinstance(operand.value, (int, float))
                    and not isinstance(operand.value, bool)
                ):
                    assert operand.value in (0, 1), (node.lineno, operand.value)
    banned = {90, 300, 900, 60, 100}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, int)
                    and not isinstance(sub.value, bool)
                ):
                    assert sub.value not in banned, (sub.lineno, sub.value)
    block_start = text.index(begin)
    block_end = text.index(end)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and node.value.value in banned
        ):
            name = node.targets[0].id
            in_block = (
                block_start
                <= sum(len(ln) + 1 for ln in text.splitlines()[: node.lineno - 1])
                <= block_end
            )
            assert in_block or (name.isupper() and not name.startswith("DEFAULT_")), name


def test_no_git_or_clone_assumption():
    for name, line in all_code():
        assert not re.search(r"(^|[^A-Za-z])git\s|\.git\b|rev-parse", line), (name, line)


def test_no_github_or_network():
    for name, line in all_code():
        assert not re.search(
            r"(^|[^A-Za-z])gh\s|curl|github|urllib|http\.client|socket", line, re.I
        ), (name, line)


def test_nothing_parses_detail():
    for name, line in all_code():
        assert not re.search(r"detail\.(startswith|split|find|index)", line), (name, line)
        assert not re.search(r"(startswith|re\.\w+)\(.*\bdetail\b", line), (name, line)
