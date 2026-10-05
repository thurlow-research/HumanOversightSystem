"""#1944 S1 static guards over bin/hos-usage-poll and bin/lib/usage_pause.py (TD section 9.1)."""

import ast
import hashlib
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
        assert "_TIMEOUT_BIN" not in line, (name, line)
        # C-2: command invocations are banned; the item-6b basename set literal and its FAIL text are data, not a call
        if not (line.startswith("TIMEOUT_BIN_BASENAMES") or "basename is not" in line):
            assert "gtimeout" not in line, (name, line)
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


# ───────────────────────── #1944 S2: the hos-cron gate (TD 9.2, S2-ST1..ST10) ─────────────────────────

HOS_CRON = ROOT / "bin" / "hos-cron"
GATE_BEGIN = "# ── Usage-threshold pause gate (#1944, ADR-1944 AD-7/A2-4) ──────────"
GATE_SENTINEL_LINE = "# HOS-USAGE-PAUSE-GATE schema=1"
GATE_END = "# ── end usage-threshold pause gate (#1944) ──"
BREAKER_BLOCK_SHA256 = (
    "aacabf73001af2eb01231ae786e08a9819cd15651c8f4e98fbbc09ffd130044e"  # pragma: allowlist secret
)


def gate_block() -> str:
    text = HOS_CRON.read_text(encoding="utf-8")
    start = text.index(GATE_BEGIN)
    return text[start : text.index(GATE_END) + len(GATE_END)]


def gate_code_lines() -> list:
    return [ln for ln in gate_block().splitlines() if not ln.strip().startswith("#")]


def section(path: Path, heading: str, stop: str = "") -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    return text[start : text.index(stop, start + len(heading))] if stop else text[start:]


def test_s2_st1_gate_block_clean():
    """No state, network, suspend, metrics or file-write token anywhere in the block."""
    block = gate_block()
    for plain in ("poll_", ".prom", "last-claude-output", "HOS_CRON_MAX_SECONDS"):
        assert plain not in block, plain
    # the /usage command itself; the library path `lib/usage_pause.py` legitimately contains it
    assert not re.search(r"/usage(?![A-Za-z0-9_])", block)
    for word in (
        "suspend",
        "node_exporter",
        "ssh",
        "gh",
        "curl",
        "github",
        "mkdir",
        "touch",
        "rm",
        "mv",
        "cp",
    ):
        assert not re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(word), block), word
    assert ">" not in block, "the block redirects nothing into a file"


def test_s2_st2_gate_placement():
    text = HOS_CRON.read_text(encoding="utf-8")
    begin = text.index(GATE_BEGIN)
    audit_def = text.index("_audit() {")
    assert text.index("\n}\n", audit_def) < begin
    for later in (
        "# ── Audit log sync",
        'get_app_token.sh" --app',
        "_CLAUDE_AUTH_ENV=",
        "\n_pre_jitter_deps_check\n",
        "wakeup signal received",
    ):
        assert text.index(later) > begin, later
    for earlier in ('trap \'rm -rf "$_LOCK_DIR"', "HOS_CYCLE_ID=", "_HOS_DIR="):
        assert text.index(earlier) < begin, earlier


def test_s2_st3_reactive_breaker_code_unchanged():
    text = HOS_CRON.read_text(encoding="utf-8")
    start = text.index("# ── DISABLED 2026-09-01")
    block = text[start : text.index("# ── Post-cycle bookkeeping")]
    assert all(ln.startswith("#") or not ln.strip() for ln in block.splitlines())
    assert hashlib.sha256(block.encode("utf-8")).hexdigest() == BREAKER_BLOCK_SHA256
    cron_tests = (ROOT / "tests" / "automation" / "test_hos_cron.py").read_text(encoding="utf-8")
    klass = cron_tests.index("class TestUsageLimitBreaker")
    between = cron_tests[cron_tests.rindex("@pytest.mark.skip(", 0, klass) : klass]
    assert between.count("@pytest.mark") == 1, "TestUsageLimitBreaker stays skipped"


def test_s2_st4_check_invoked_once():
    block = gate_block()
    assert len(re.findall(r'usage_pause\.py" check ', block)) == 1
    assert HOS_CRON.read_text(encoding="utf-8").count("usage_pause.py") == 1


def test_s2_st5_up_bound_expansions_set_u_safe_and_named_values():
    block = gate_block()
    safe = '${_UP_BOUND[@]+"${_UP_BOUND[@]}"}'
    assert block.count(safe) == 1
    assert "_UP_BOUND[@]" not in block.replace(safe, "")
    assert "_UP_BOUND[*]" not in block
    code = gate_code_lines()
    assert code[0].startswith("_UP_CHECK_TIMEOUT_S=") and code[1].startswith(
        "_UP_CHECK_KILL_AFTER_S="
    )
    assert block.count("_UP_CHECK_TIMEOUT_S=") == 1 and block.count("_UP_CHECK_KILL_AFTER_S=") == 1
    # no other numeric literal: drop the two named values, the regex line, comments and strings
    for line in code[2:]:
        if line.startswith("_UP_VERDICT_RE="):
            continue
        bare = line.split(" # ")[0]
        for number in re.findall(r"(?<![A-Za-z_$0-9])[0-9]+(?![A-Za-z_0-9])", bare):
            assert number in ("0", "1"), (number, line)


def test_s2_st6_gate_never_reads_max_seconds():
    assert "HOS_CRON_MAX_SECONDS" not in gate_block()
    assert "HOS_CRON_MAX_SECONDS" not in LIB.read_text(encoding="utf-8")


def test_s2_st7_sentinel_unique_and_second_line():
    block = gate_block().splitlines()
    assert block[0] == GATE_BEGIN and block[1] == GATE_SENTINEL_LINE
    text = HOS_CRON.read_text(encoding="utf-8")
    for anchor in (GATE_BEGIN, GATE_END):
        assert text.count(anchor) == 1, anchor
    hits = []
    for path in sorted((ROOT / "bin").rglob("*")):
        if path.is_file() and not path.name.endswith(".pyc"):
            body = path.read_text(encoding="utf-8", errors="replace").splitlines()
            hits += [path.name for ln in body if ln.rstrip() == GATE_SENTINEL_LINE]
    assert hits == ["hos-cron"]
    ns = {}
    exec(compile(LIB.read_text(), str(LIB), "exec"), ns)
    assert ns["GATE_SENTINEL"] == GATE_SENTINEL_LINE


def test_s2_st8_check_never_reads_poll_keys():
    ns = {}
    exec(compile(LIB.read_text(), str(LIB), "exec"), ns)
    assert not any(key.startswith("poll_") for key in ns["CHECK_READ_KEYS"])
    tree = ast.parse(LIB.read_text())
    wanted = {"evaluate_cycle", "_evaluate", "_model_entries", "gate_verdict", "_cmd_check"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            found.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    assert not sub.value.startswith("poll_"), (node.name, sub.value)
    assert found == wanted


H1_SENTENCE = "fail_mode=open without a running poller means no quota protection"


def test_s2_st9_upgrade_checklist_and_release_note_present():
    checklist = section(
        ROOT / "docs" / "UPGRADE-PR-REVIEW-CHECKLIST.md", "## H. Usage-pause gate (#1944)", "\n---"
    )
    notes = section(ROOT / "docs" / "releases" / "v0.7.0.md", "## Upgrade notes")
    for text in (checklist, notes):
        assert H1_SENTENCE in text
        assert "cycle-usage-unchecked" in text
        assert "docs/CRON-SETUP.md" in text and "--check" in text
        assert "API" in text
        assert re.search(r"stops? (all )?autonomous work", text)
    assert checklist.count("- [ ]") == 4 and "item 8" in checklist and "item 8" in notes


def test_s2_st10_runbook_content():
    runbook = ROOT / "docs" / "CRON-SETUP.md"
    note = section(runbook, "### 2a.0 ", "### 2a.1 ")
    failopen = section(runbook, "### 2a.9 ", "### 2a.10 ")
    for text in (note, failopen):
        assert H1_SENTENCE in text and "cycle-usage-unchecked" in text
    assert "safe **only once alerting is live**" in failopen
    whole = runbook.read_text(encoding="utf-8")
    assert "item 8 must be green after every upgrade" in whole
    assert "single place the poller's install path is defined" in whole
    assert "A paused cycle never pushes audit records" in " ".join(whole.split())
