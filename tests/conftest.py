"""
Add the validators directory to sys.path so tests can import validators
directly without package-relative imports.

Also add the project root so `from scripts.automation.lib.X import ...`
works for the automation subsystem (scripts/ is a namespace package).
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parent.parent


def load_module_from_path(name: str, path: Path, *, register: bool = False) -> ModuleType:
    """Load a module from a file path for tests that import project scripts
    directly rather than as installed packages.

    Narrows importlib.util's Optional return types once so call sites don't
    each repeat the same `assert spec is not None and spec.loader is not None`.

    `register=True` registers the module in sys.modules under `name` before
    executing it — needed when the module's own top-level code (e.g. a
    @dataclass that introspects sys.modules[cls.__module__]) requires the
    module to already be resolvable during exec.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Allow `import schema`, `import rn_calculator`, etc. from tests
VALIDATORS_DIR = ROOT / "scripts" / "oversight" / "validators"
OVERSIGHT_DIR = ROOT / "scripts" / "oversight"
for p in (str(VALIDATORS_DIR), str(OVERSIGHT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Allow `from scripts.automation.lib.X import ...`
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Surface pytest-rerunfailures retry-rescues (#1244 ruling item 4).

    A test that fails once then passes on the --reruns 1 retry doesn't fail
    the build, but going silent about it is exactly the drift this repo's
    testability work exists to catch. Detection/formatting logic lives in
    retry_rescue_logic.py (importable, unit-tested); this hook only reads
    pytest's own per-outcome report buckets and does the I/O.

    Best-effort only: on a CI checkout (`permissions: contents: read` in
    tests.yml) the audit-log write happens on a filesystem that is never
    committed back, so it doesn't durably land — the terminal-summary lines
    below are what keeps CI visible in that case. Persisting CI-originated
    events and escalating a threshold breach into a filed bug ticket needs
    its own design (state channel, de-dup) and is tracked separately.
    """
    from retry_rescue_logic import build_retry_rescue_event, now_iso, rescued_nodeids

    rerun_nodeids = [r.nodeid for r in terminalreporter.stats.get("rerun", [])]
    if not rerun_nodeids:
        return
    passed_nodeids = [r.nodeid for r in terminalreporter.stats.get("passed", [])]
    rescues = rescued_nodeids(rerun_nodeids, passed_nodeids)
    if not rescues:
        return

    terminalreporter.section("retry-rescues (#1244 ruling item 4)")
    ts = now_iso()
    pr_number = os.environ.get("PR_NUMBER") or None
    for nodeid in rescues:
        terminalreporter.write_line(f"RETRY-RESCUE: {nodeid} failed once, passed on retry")
        try:
            from scripts.oversight.lib.audit_log import write_event

            write_event(build_retry_rescue_event(nodeid, ts, pr_number), root=str(ROOT))
        except Exception as exc:  # best-effort — never fail the test run over logging
            terminalreporter.write_line(f"  (audit write skipped: {exc})")
