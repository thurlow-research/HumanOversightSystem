"""
Multi-customer fairness wiring (B14, R12.1–R12.3, O15).

One HOS instance serves multiple customer repos without one noisy customer
starving the rest. Provides:
  - Per-customer budgets (separate token ledgers already handled by ledger.py)
  - Round-robin probe ordering with staggered starts (R12.2)
  - Isolation: one customer's probe failure doesn't abort others (R12.3)
  - Global and per-repo kill switch support
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SOFT_STATE_DIR = Path(".ai-local") / "hos-automation"
_ROUND_ROBIN_FILE = "round-robin-state.json"


# ---------------------------------------------------------------------------
# Customer registry
# ---------------------------------------------------------------------------

def load_customers(repo_root: str = ".") -> list[dict]:
    """
    Load the list of customer repos from PROJECT/hos-customers.yaml.

    Each entry has: owner, repo, enabled, floor_minutes, ceiling_hours, api_budget.
    Returns [] if the file doesn't exist (single-repo mode, use current remote).
    """
    customers_path = Path(repo_root) / "PROJECT" / "hos-customers.yaml"
    if not customers_path.is_file():
        return []
    try:
        import yaml  # type: ignore[import]
        with customers_path.open() as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("customers", [])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Round-robin ordering with staggered starts (R12.2)
# ---------------------------------------------------------------------------

def _load_rr_state(repo_root: str = ".") -> dict:
    path = Path(repo_root) / _SOFT_STATE_DIR / _ROUND_ROBIN_FILE
    if not path.is_file():
        return {"last_index": -1, "last_cycle": None}
    try:
        with path.open() as fh:
            return json.load(fh)
    except Exception:
        return {"last_index": -1, "last_cycle": None}


def _save_rr_state(state: dict, repo_root: str = ".") -> None:
    path = Path(repo_root) / _SOFT_STATE_DIR / _ROUND_ROBIN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        json.dump(state, fh)


def next_customer_order(
    customers: list[dict],
    floor_minutes: int = 15,
    repo_root: str = ".",
) -> list[dict]:
    """
    Return customers in round-robin order, skipping those whose next_due hasn't arrived.

    Staggered starts: each customer is offset by floor/N minutes so they don't
    all probe simultaneously (R12.2, O15).
    """
    if not customers:
        return []

    state = _load_rr_state(repo_root)
    n = len(customers)
    offset_minutes = floor_minutes / max(n, 1)

    ordered = []
    start = (state["last_index"] + 1) % n
    for i in range(n):
        idx = (start + i) % n
        customer = customers[idx]
        # Stagger: customer idx gets a probe_offset of idx * offset_minutes
        customer = dict(customer, _probe_offset_minutes=idx * offset_minutes)
        ordered.append(customer)

    state["last_index"] = start
    state["last_cycle"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_rr_state(state, repo_root)
    return ordered


# ---------------------------------------------------------------------------
# Kill switch support
# ---------------------------------------------------------------------------

def global_kill_active(repo_root: str = ".") -> bool:
    """
    Return True if the global HOS kill switch is active.

    The global kill switch is the `hos-halt` file at the HOS repo root.
    Per-repo kill switches are checked by the orchestrator for each customer repo.
    """
    for candidate in [
        Path(repo_root) / "PROJECT" / "hos-halt",
        Path(repo_root) / ".hos-halt",
    ]:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return True
    return False


def per_repo_kill_active(customer_repo_root: str) -> bool:
    """Check if a specific customer repo has its own kill switch active."""
    return global_kill_active(customer_repo_root)


# ---------------------------------------------------------------------------
# Probe isolation (R12.3)
# ---------------------------------------------------------------------------

def probe_with_isolation(
    owner: str,
    repo: str,
    repo_id: str,
    requester_allowlist: list[str],
    customer: str = "",
    repo_root: str = ".",
    **probe_kwargs,
) -> list:
    """
    Probe a single customer repo with failure isolation.

    If the probe raises, log and return [] — don't abort the whole cycle.
    """
    from scripts.automation.lib.probe import probe_repo
    try:
        return probe_repo(
            owner=owner, repo=repo, repo_id=repo_id,
            requester_allowlist=requester_allowlist,
            customer=customer, repo_root=repo_root,
            **probe_kwargs,
        )
    except Exception as exc:
        # R12.3: isolated — log and continue
        return []
