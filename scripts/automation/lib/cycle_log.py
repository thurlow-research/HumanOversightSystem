"""
cycle_log.py — append structured cycle events to audit/oversight-log.jsonl

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

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _find_audit_log() -> Path:
    root = Path(__file__).resolve().parent
    while root != root.parent:
        candidate = root / "audit" / "oversight-log.jsonl"
        if candidate.parent.is_dir():
            return candidate
        root = root.parent
    return Path("audit/oversight-log.jsonl")


def log_event(event: str, **kwargs) -> None:
    entry = {
        "event": event,
        "role": "worker",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **kwargs,
    }
    log_path = _find_audit_log()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


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
