"""
Append-only per-run cost/action ledger for the HOS automation loop.

Design principles (O4, R11.6, read-your-writes invariant):
  - One JSONL file per orchestrator run under audit/automation/<customer>/runs/
  - Records are append-only — never mutated after write
  - Per-window summation reads all run files; no shared mutable counter
  - Two concurrent instances write different files → zero write contention
  - The JSONL file is authoritative; the derived Markdown log is regenerable (R11.8)
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Directory layout (O4 resolution)
# ---------------------------------------------------------------------------
# audit/automation/
#   <customer>/
#     runs/
#       <instance-id>-<ISO8601-compact>.jsonl   # one file per orchestrator run
#     manifest.jsonl                             # one line per run file
#     automation-log.md                          # derived human-readable (R11.8)

_AUDIT_ROOT = Path("audit") / "automation"


def _run_dir(customer: str) -> Path:
    return _AUDIT_ROOT / customer / "runs"


def _manifest_path(customer: str) -> Path:
    return _AUDIT_ROOT / customer / "manifest.jsonl"


# ---------------------------------------------------------------------------
# Record schema (one JSONL line per event)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_record(
    instance_id: str,
    cid: Optional[str],
    customer: str,
    event: str,
    who: str,
    what: str,
    why: str = "",
    token_cost: Optional[int] = None,
    files_touched: int = 0,
    prs: int = 0,
    issues: int = 0,
) -> dict[str, Any]:
    """
    Build one ledger record. All correctness-sensitive summation uses this schema.

    event vocabulary: spawn | triage | estimate | gate-start | gate-end | merge |
      escalate | propose | suppress | halt | stale-lock-reclaim | heartbeat | ...
    who: "hos-worker" | "hos-overseer"
    """
    return {
        "ts": _now_iso(),
        "instance_id": instance_id,
        "cid": cid,
        "customer": customer,
        "event": event,
        "who": who,
        "what": what,
        "why": why,
        "token_cost": token_cost,
        "files_touched": files_touched,
        "prs": prs,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# LedgerWriter — one per orchestrator run
# ---------------------------------------------------------------------------

class LedgerWriter:
    """
    Append-only writer for one orchestrator run.

    Each run gets its own JSONL file. Multiple concurrent instances write
    different files — no lock needed for writes.
    """

    def __init__(self, customer: str, instance_id: Optional[str] = None, repo_root: str = "."):
        self.customer = customer
        self.instance_id = instance_id or str(uuid.uuid4())
        self._repo_root = Path(repo_root)
        self._run_dir = self._repo_root / _run_dir(customer)
        ts = _compact_ts()
        self._run_file = self._run_dir / f"{self.instance_id}-{ts}.jsonl"
        self._manifest = self._repo_root / _manifest_path(customer)
        self._started = _now_iso()
        self._initialized = False

    def _ensure_dirs(self) -> None:
        if self._initialized:
            return
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._manifest.parent.mkdir(parents=True, exist_ok=True)
        # Append manifest entry on first write.
        manifest_record = json.dumps({
            "file": str(self._run_file.relative_to(self._repo_root)),
            "instance_id": self.instance_id,
            "started": self._started,
            "ended": None,
            "customer": self.customer,
        })
        with self._manifest.open("a", encoding="utf-8") as fh:
            fh.write(manifest_record + "\n")
        self._initialized = True

    def append(self, record: dict[str, Any]) -> None:
        """Append one record to the run file. Thread-safe via O_APPEND."""
        self._ensure_dirs()
        line = json.dumps(record, ensure_ascii=False)
        with self._run_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def log(
        self,
        event: str,
        who: str,
        what: str,
        cid: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Convenience wrapper — builds and appends a record."""
        record = make_record(
            instance_id=self.instance_id,
            cid=cid,
            customer=self.customer,
            event=event,
            who=who,
            what=what,
            **kwargs,
        )
        self.append(record)

    def close(self, ended: Optional[str] = None) -> None:
        """Write the end timestamp to the manifest entry (best-effort)."""
        # Re-write the manifest to mark this run as ended. Since manifest is
        # append-only by design, we append a "close" record rather than mutating.
        if not self._initialized:
            return
        close_record = json.dumps({
            "type": "run-end",
            "instance_id": self.instance_id,
            "ended": ended or _now_iso(),
            "customer": self.customer,
        })
        with self._manifest.open("a", encoding="utf-8") as fh:
            fh.write(close_record + "\n")


# ---------------------------------------------------------------------------
# Summation at read (read-your-writes: reads all run files, never a counter)
# ---------------------------------------------------------------------------

def _iter_run_records(customer: str, repo_root: str = ".") -> list[dict[str, Any]]:
    """Yield all records from all run files for this customer."""
    run_dir = Path(repo_root) / _run_dir(customer)
    if not run_dir.is_dir():
        return []
    records = []
    for run_file in sorted(run_dir.glob("*.jsonl")):
        try:
            with run_file.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass
    return records


def sum_window_tokens(
    customer: str,
    window_hours: float = 1.0,
    repo_root: str = ".",
) -> int:
    """
    Sum token_cost across all records within the rolling window.

    Read-your-writes: reads every run file; never relies on a cached counter.
    Used by budget.py for per-window budget enforcement (R8.2).
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    total = 0
    for rec in _iter_run_records(customer, repo_root):
        try:
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts >= cutoff and rec.get("token_cost"):
            total += int(rec["token_cost"])
    return total


def sum_window_blast_radius(
    customer: str,
    window_hours: float = 24.0,
    repo_root: str = ".",
) -> dict[str, int]:
    """
    Sum PRs/issues/files_touched across the rolling window (R11.2).

    Read-your-writes — summation at read, no cached totals.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    totals = {"prs": 0, "issues": 0, "files": 0}
    for rec in _iter_run_records(customer, repo_root):
        try:
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts >= cutoff:
            totals["prs"] += int(rec.get("prs", 0))
            totals["issues"] += int(rec.get("issues", 0))
            totals["files"] += int(rec.get("files_touched", 0))
    return totals


def last_k_median_cost(
    customer: str,
    triage_class: str,
    k: int = 20,
    repo_root: str = ".",
) -> Optional[float]:
    """
    Median token_cost of the last K completed tasks of the given triage class.

    Used by budget.py O5 historical-floor estimation.
    Returns None when fewer than 3 data points exist (insufficient history).
    """
    costs = []
    for rec in reversed(_iter_run_records(customer, repo_root)):
        if rec.get("event") == "gate-end" and rec.get("what", "").startswith(triage_class):
            cost = rec.get("token_cost")
            if cost is not None:
                costs.append(int(cost))
        if len(costs) >= k:
            break
    if len(costs) < 3:
        return None
    sorted_costs = sorted(costs)
    mid = len(sorted_costs) // 2
    if len(sorted_costs) % 2 == 0:
        return (sorted_costs[mid - 1] + sorted_costs[mid]) / 2
    return float(sorted_costs[mid])
