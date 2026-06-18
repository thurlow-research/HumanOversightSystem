"""
Per-task token estimation and per-window budget gate for the HOS automation loop.

Design (R8.1–R8.7, O5):
  - Estimate is a cheap heuristic — no model pre-pass (R8.1, R8.6, O5)
  - Per-task gate: estimate > per_task_threshold → create permission request
  - Per-window gate: cumulative spend + estimate > window_budget → gate all GATED work
  - Default-deny on approval timeout (R8.3): silence ≠ yes
  - GATED vs UNGATED classification (R8.7): triage/estimate/heartbeat always allowed

Classification:
  GATED    = full build-chain run, self-review run, cross-vendor validation
  UNGATED  = triage, envelope parse, estimation, drafting escalations, heartbeat, label ops
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from scripts.automation.lib.ledger import (
    last_k_median_cost,
    sum_window_tokens,
)


class WorkClass(Enum):
    GATED = auto()    # requires budget gate before proceeding
    UNGATED = auto()  # always allowed, even when budget is exhausted


# GATED work types — any full build-chain invocation
GATED_EVENTS = frozenset({
    "spawn", "gate-start", "gate-end", "merge",
    "self-review-run", "cross-vendor-run",
})

# UNGATED work types — always allowed (R8.7)
UNGATED_EVENTS = frozenset({
    "triage", "estimate", "heartbeat", "label-op",
    "escalate", "propose", "envelope-parse", "claim",
    "stale-lock-reclaim", "probe-complete",
})


# ---------------------------------------------------------------------------
# O5 resolution — token estimation signals + formula (no model pre-pass)
# ---------------------------------------------------------------------------

# Base token costs by triage class (calibration constants; tunable via config)
BASE_COST: dict[str, int] = {
    "bug": 40_000,
    "communication": 8_000,
    "spec-gap": 15_000,
    "default": 30_000,
}

# Multipliers per signal (calibration constants; tunable via config)
PER_1K_BODY_CHARS: int = 6
PER_CHANGED_FILE: int = 1_500
PER_DIFF_LINE: int = 8
PER_BLAST_RADIUS_UNIT: int = 1_000
HISTORICAL_FLOOR_MULTIPLIER: float = 1.25
HISTORICAL_WINDOW_K: int = 20


@dataclass
class EstimationSignals:
    """All signals are free from already-fetched GitHub objects or git."""
    triage_class: str = "default"
    issue_body_chars: int = 0
    changed_file_count: int = 0
    total_diff_lines: int = 0
    blast_radius: int = 0


def estimate_tokens(
    signals: EstimationSignals,
    customer: str,
    repo_root: str = ".",
) -> int:
    """
    Estimate token cost for a task.

    Formula (O5 resolution):
      estimate = BASE[class]
               + PER_1K_BODY_CHARS * (body_chars / 1000)
               + PER_CHANGED_FILE * changed_files
               + PER_DIFF_LINE * diff_lines
               + PER_BLAST_RADIUS_UNIT * blast_radius
      estimate = max(estimate, historical_median * HISTORICAL_FLOOR_MULTIPLIER)

    No model pre-pass — estimation error is acceptable by design; R8.6 re-asks
    on mid-flight overrun. Errs high intentionally (HISTORICAL_FLOOR_MULTIPLIER).
    """
    base = BASE_COST.get(signals.triage_class, BASE_COST["default"])
    estimate = (
        base
        + PER_1K_BODY_CHARS * (signals.issue_body_chars / 1_000)
        + PER_CHANGED_FILE * signals.changed_file_count
        + PER_DIFF_LINE * signals.total_diff_lines
        + PER_BLAST_RADIUS_UNIT * signals.blast_radius
    )

    # Historical floor — calibrate upward from recent same-class tasks.
    historical = last_k_median_cost(
        customer, signals.triage_class, HISTORICAL_WINDOW_K, repo_root
    )
    if historical is not None:
        estimate = max(estimate, historical * HISTORICAL_FLOOR_MULTIPLIER)

    return int(estimate)


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------

@dataclass
class BudgetDecision:
    allowed: bool
    reason: str
    estimate: int
    window_spent: int
    work_class: WorkClass


class BudgetGate:
    """
    Evaluates the per-task and per-window budget gates.

    Reads window spend from the ledger at call time (read-your-writes).
    Never caches window totals — the ledger is the source of truth.
    """

    def __init__(
        self,
        per_task_threshold: int,
        window_budget: int,
        customer: str,
        repo_root: str = ".",
        window_hours: float = 1.0,
    ):
        self.per_task_threshold = per_task_threshold
        self.window_budget = window_budget
        self.customer = customer
        self.repo_root = repo_root
        self.window_hours = window_hours

    def evaluate(
        self,
        event: str,
        estimate: int,
    ) -> BudgetDecision:
        """
        Decide whether a task may proceed.

        UNGATED events: always allowed regardless of budget.
        GATED events: blocked when per-task estimate OR per-window budget exceeded.
        """
        work_class = (
            WorkClass.UNGATED if event in UNGATED_EVENTS else WorkClass.GATED
        )

        if work_class == WorkClass.UNGATED:
            return BudgetDecision(
                allowed=True,
                reason="UNGATED — always allowed",
                estimate=estimate,
                window_spent=0,
                work_class=work_class,
            )

        # Per-task estimate gate (R8.1)
        if estimate > self.per_task_threshold:
            return BudgetDecision(
                allowed=False,
                reason=(
                    f"Per-task estimate {estimate:,} exceeds threshold "
                    f"{self.per_task_threshold:,} — human approval required"
                ),
                estimate=estimate,
                window_spent=0,
                work_class=work_class,
            )

        # Per-window budget gate (R8.2) — read-your-writes
        window_spent = sum_window_tokens(
            self.customer, self.window_hours, self.repo_root
        )
        if window_spent + estimate > self.window_budget:
            return BudgetDecision(
                allowed=False,
                reason=(
                    f"Per-window budget would be exceeded: spent {window_spent:,} "
                    f"+ estimate {estimate:,} > limit {self.window_budget:,}"
                ),
                estimate=estimate,
                window_spent=window_spent,
                work_class=work_class,
            )

        return BudgetDecision(
            allowed=True,
            reason=f"Within budget (window spent {window_spent:,}, estimate {estimate:,})",
            estimate=estimate,
            window_spent=window_spent,
            work_class=work_class,
        )

    def escalation_body(
        self,
        decision: BudgetDecision,
        blast_radius_summary: str,
        deadline_iso: str,
    ) -> str:
        """
        Format a §8.2 escalation body for a budget-gated permission request.

        Must carry: problem + risk + background, options, recommendation,
        token estimate + blast-radius summary, default-deny deadline (R8.2b).
        """
        return (
            f"## HOS Budget Approval Request\n\n"
            f"**Problem:** {decision.reason}\n\n"
            f"**Token estimate:** {decision.estimate:,} tokens\n"
            f"**Window spent so far:** {decision.window_spent:,} tokens\n"
            f"**Blast radius:** {blast_radius_summary}\n\n"
            f"**Options:**\n"
            f"- Approve: the loop will proceed with this task\n"
            f"- Deny (default): the task is queued as `needs-human`; no tokens spent\n\n"
            f"**Recommendation:** Approve if the task is expected and within budget.\n\n"
            f"**Default-deny deadline:** {deadline_iso} — silence is treated as denied (R8.3).\n\n"
            f"Reply with `Decision: approve` or `Decision: deny`."
        )
