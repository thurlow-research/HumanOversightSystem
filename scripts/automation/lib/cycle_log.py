"""
cycle_log.py — write structured cycle events as per-entry audit records.

Each event becomes one write-once file under audit/log/<YYYY>/<MM>/ via the
canonical helper (scripts/oversight/lib/audit_log.py), so two branches that each
log a cycle event never touch the same file and never merge-conflict (SPEC-888,
#888 P2). This replaces the old append to the single audit/oversight-log.jsonl.

Usage (from bash in cron/LOOP context):
  python3 -m scripts.automation.lib.cycle_log cycle-stop reason=pr-awaiting-review pr=587
  python3 -m scripts.automation.lib.cycle_log cycle-pick issue=559 title="two codeowners.py"
  python3 -m scripts.automation.lib.cycle_log cycle-pr-opened pr=613 issue=559

Events:
  cycle-start          logged by bin/hos-worker-cron (shell-level)
  cycle-preflight-fail logged by bin/hos-worker-cron (shell-level)
  cycle-stop           logged here; reason=<enum>
  cycle-pick           logged here; issue=<N> title=<str>
  cycle-pr-opened      logged here; pr=<N> issue=<N>
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_audit_log():
    """Load the canonical per-entry audit-record helper by file path.

    cycle_log may run as a plain script or as a module, so load the sibling
    scripts/oversight/lib/audit_log.py directly rather than relying on the
    package import resolving in every invocation context.
    """
    path = Path(__file__).resolve().parents[2] / "oversight" / "lib" / "audit_log.py"
    spec = importlib.util.spec_from_file_location("hos_audit_log", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AUDIT_LOG = _load_audit_log()


def _find_root() -> Path:
    """Repo root = nearest ancestor containing an audit/ directory (else ".")."""
    root = Path(__file__).resolve().parent
    while root != root.parent:
        if (root / "audit").is_dir():
            return root
        root = root.parent
    return Path(".")


def log_event(event: str, **kwargs) -> None:
    entry = {
        "event": event,
        "role": "worker",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **kwargs,
    }
    # write_event derives the record's filename timestamp from entry["timestamp"],
    # so the path and the record stay in lockstep.
    _AUDIT_LOG.write_event(entry, root=str(_find_root()))


def _parse_args(args: list[str]) -> tuple[str, dict]:
    if not args:
        print("Usage: cycle_log.py <event> [key=value ...]", file=sys.stderr)
        sys.exit(1)
    event = args[0]
    kwargs: dict = {}
    for arg in args[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            try:
                kwargs[k] = int(v)
            except ValueError:
                kwargs[k] = v
        else:
            kwargs[arg] = True
    return event, kwargs


if __name__ == "__main__":
    event, kwargs = _parse_args(sys.argv[1:])
    log_event(event, **kwargs)
