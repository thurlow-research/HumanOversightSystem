"""
Observability — JSONL-first run ledger consumers and derived Markdown log (T14, R11.8).

Design (R11.8):
  - JSONL is authoritative; the Markdown log is derived and regenerable
  - If only the JSONL write succeeds, no data is lost
  - Never treat the Markdown as a source of truth
  - Roll-ups are separate regenerated artifacts, not in-place edits

The Markdown automation-log is append-only within a session and fully
regenerable from the JSONL files at any time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from scripts.automation.lib.ledger import _iter_run_records, _AUDIT_ROOT

# ---------------------------------------------------------------------------
# Markdown log generation (R11.8 — derived, never authoritative)
# ---------------------------------------------------------------------------

_LOG_FILENAME = "automation-log.md"


def _format_record_md(rec: dict) -> str:
    ts = rec.get("ts", "?")
    event = rec.get("event", "?")
    who = rec.get("who", "?")
    what = rec.get("what", "")
    cid = rec.get("cid") or ""
    cost = rec.get("token_cost")
    cost_str = f" ({cost:,} tokens)" if cost else ""
    cid_str = f" `{cid}`" if cid else ""
    return f"| {ts} | {event} | {who} |{cid_str} {what}{cost_str} |"


def regenerate_markdown_log(customer: str, repo_root: str = ".") -> None:
    """
    Regenerate the per-customer automation-log.md from all JSONL run files.

    This is a full regeneration — the existing file is overwritten.
    Safe to call at any time; the JSONL files are authoritative.
    """
    records = list(_iter_run_records(customer, repo_root))
    log_path = Path(repo_root) / _AUDIT_ROOT / customer / _LOG_FILENAME

    lines = [
        f"# HOS Automation Log — {customer}",
        f"",
        f"*Generated from JSONL run files. Do not edit by hand.*",
        f"",
        f"| Timestamp | Event | Actor | Details |",
        f"|---|---|---|---|",
    ]
    for rec in records:
        lines.append(_format_record_md(rec))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_to_markdown_log(customer: str, rec: dict, repo_root: str = ".") -> None:
    """
    Append one record to the Markdown log without full regeneration.

    Used during a live run for real-time visibility. The JSONL is always
    written first; this is a best-effort append.
    """
    log_path = Path(repo_root) / _AUDIT_ROOT / customer / _LOG_FILENAME
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if not log_path.is_file():
        # Bootstrap the header on first write
        log_path.write_text(
            f"# HOS Automation Log — {customer}\n\n"
            f"*Generated from JSONL run files. Do not edit by hand.*\n\n"
            f"| Timestamp | Event | Actor | Details |\n"
            f"|---|---|---|---|\n",
            encoding="utf-8",
        )

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(_format_record_md(rec) + "\n")


# ---------------------------------------------------------------------------
# Run summary (for human-readable escalation / handoff)
# ---------------------------------------------------------------------------

def summarize_run(
    customer: str,
    instance_id: str,
    repo_root: str = ".",
    window_hours: float = 24.0,
) -> str:
    """
    Produce a human-readable summary of a specific instance run.

    Used in §8.2 escalation bodies and handoff documents.
    """
    records = [
        r for r in _iter_run_records(customer, repo_root)
        if r.get("instance_id") == instance_id
    ]
    if not records:
        return f"No records found for instance {instance_id}"

    events = [r["event"] for r in records]
    total_cost = sum(r.get("token_cost") or 0 for r in records)
    total_prs = sum(r.get("prs") or 0 for r in records)
    total_issues = sum(r.get("issues") or 0 for r in records)
    cids = list({r["cid"] for r in records if r.get("cid")})

    lines = [
        f"**Instance:** `{instance_id}`",
        f"**Customer:** {customer}",
        f"**Events:** {', '.join(events)}",
        f"**Work items:** {', '.join(cids) or 'none'}",
        f"**Token spend:** {total_cost:,}",
        f"**Blast radius:** {total_prs} PRs, {total_issues} issues",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Activity report (forensics — "what did it do at 3am and why?")
# ---------------------------------------------------------------------------

def activity_report(
    customer: str,
    window_hours: float = 12.0,
    repo_root: str = ".",
) -> str:
    """
    Produce a forensic activity report for the given time window.

    Answers "what did the loop do and why?" — suitable for incident review.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    records = [
        r for r in _iter_run_records(customer, repo_root)
        if _parse_ts(r.get("ts")) and _parse_ts(r["ts"]) >= cutoff
    ]

    if not records:
        return f"No activity recorded in the last {window_hours}h for {customer}."

    total_cost = sum(r.get("token_cost") or 0 for r in records)
    merges = [r for r in records if r.get("event") == "merge"]
    escalations = [r for r in records if r.get("event") == "escalate"]
    halts = [r for r in records if r.get("event") == "halt"]

    lines = [
        f"## HOS Activity Report — {customer}",
        f"Window: last {window_hours}h  |  Records: {len(records)}",
        f"Token spend: {total_cost:,}  |  Merges: {len(merges)}  "
        f"|  Escalations: {len(escalations)}  |  Halts: {len(halts)}",
        "",
        "### Timeline",
    ]
    for r in records:
        lines.append(
            f"- `{r.get('ts', '?')}` [{r.get('event', '?')}] "
            f"{r.get('who', '?')} — {r.get('what', '')} "
            f"{'(cid: ' + r['cid'] + ')' if r.get('cid') else ''}"
        )

    return "\n".join(lines)


def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
