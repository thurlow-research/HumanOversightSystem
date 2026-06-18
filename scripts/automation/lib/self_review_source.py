"""
Scheduled self-review work source (T12, §3.2, O6, O9).

Runs validate_self on a cadence, files each NEW finding as a tracked issue,
and maintains a suppression ledger to avoid re-filing known/won't-fix items.

This is the whole of #131, generalized into the unattended loop rather than
a standalone cron — it inherits the loop's budget gate, ledger, kill switch,
and observability instead of re-implementing them.

Key properties:
  - Exact-key fingerprint dedup (O6): (sorted_files, finding_class) key
  - RAW finding text recorded for later reconcile
  - Suppression ledger: HOS-shipped baseline + per-repo overlay (O9)
  - Three dispositions: fix | won't-fix+suppress | escalate (R3.2.5)
  - O10: human-only suppression classes (security/privacy/license) — mechanism
    built but final class list flagged for human ratification
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Fingerprint (O6 resolution — exact-key, record RAW text)
# ---------------------------------------------------------------------------

def fingerprint(files: list[str], finding_class: str) -> str:
    """
    Exact-key fingerprint: sha256(sorted_files_joined + "|" + finding_class)[:16].

    Deterministic across instances. Two findings are the same iff their
    (sorted file list, class) pair matches — fuzzy matching deferred to v2.
    """
    key = "|".join(sorted(files)) + "|" + finding_class
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Suppression ledger (O9 — baseline + per-repo overlay)
# ---------------------------------------------------------------------------

_LEDGER_DIR = Path("audit") / "automation" / "self-review-ledger"
_SUPPRESSION_BASELINE = Path("scripts") / "automation" / "self-review-suppressions.jsonl"
_SUPPRESSION_OVERLAY_DIR = Path(".ai-local") / "hos-automation"
_SUPPRESSION_OVERLAY = _SUPPRESSION_OVERLAY_DIR / "self-review-suppressions.jsonl"

# O10 — human-only suppression classes. DO NOT modify without human approval.
# HUMAN-DECISION-REQUIRED: O10 — this list is a default pending human ratification.
HUMAN_ONLY_SUPPRESSION_CLASSES = frozenset({"security", "privacy", "license"})


def _load_suppressions(repo_root: str = ".") -> set[str]:
    """Load the combined suppression set (baseline + overlay)."""
    keys: set[str] = set()
    for path in [
        Path(repo_root) / _SUPPRESSION_BASELINE,
        Path(repo_root) / _SUPPRESSION_OVERLAY,
    ]:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    rec = json.loads(line)
                    keys.add(rec["fingerprint"])
                except (json.JSONDecodeError, KeyError):
                    pass
        except OSError:
            pass
    return keys


def is_suppressed(fp: str, repo_root: str = ".") -> bool:
    """Return True if this fingerprint is in the suppression ledger."""
    return fp in _load_suppressions(repo_root)


def suppress(
    fp: str,
    reason: str,
    finding_class: str,
    raw_text: str,
    ttl_days: int = 90,
    repo_root: str = ".",
) -> None:
    """
    Add a fingerprint to the per-repo suppression overlay.

    Human-only classes (O10) are rejected — they must be suppressed manually.
    """
    if finding_class in HUMAN_ONLY_SUPPRESSION_CLASSES:
        raise ValueError(
            f"Class '{finding_class}' is in HUMAN_ONLY_SUPPRESSION_CLASSES (O10) — "
            "cannot be auto-suppressed. A human must review and suppress this manually."
        )

    path = Path(repo_root) / _SUPPRESSION_OVERLAY
    path.parent.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = json.dumps({
        "fingerprint": fp,
        "finding_class": finding_class,
        "reason": reason,
        "raw_text": raw_text[:500],  # Truncate for storage
        "suppressed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": expires,
    })
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record + "\n")


# ---------------------------------------------------------------------------
# Self-review dedup ledger
# ---------------------------------------------------------------------------

_FILED_ISSUES_FILE = Path("audit") / "automation" / "self-review-filed.jsonl"


def _load_filed(repo_root: str = ".") -> dict[str, dict]:
    """Load the set of already-filed self-review findings keyed by fingerprint."""
    path = Path(repo_root) / _FILED_ISSUES_FILE
    filed: dict[str, dict] = {}
    if not path.is_file():
        return filed
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                filed[rec["fingerprint"]] = rec
            except (json.JSONDecodeError, KeyError):
                pass
    except OSError:
        pass
    return filed


def _record_filed(fp: str, issue_number: int, raw_text: str, repo_root: str = ".") -> None:
    path = Path(repo_root) / _FILED_ISSUES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps({
        "fingerprint": fp,
        "issue_number": issue_number,
        "filed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw_text": raw_text[:500],
    })
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record + "\n")


# ---------------------------------------------------------------------------
# Finding data structure
# ---------------------------------------------------------------------------

class SelfReviewFinding:
    __slots__ = ("files", "finding_class", "description", "raw_text", "severity")

    def __init__(
        self,
        files: list[str],
        finding_class: str,
        description: str,
        raw_text: str,
        severity: str = "medium",
    ):
        self.files = files
        self.finding_class = finding_class
        self.description = description
        self.raw_text = raw_text
        self.severity = severity

    @property
    def fp(self) -> str:
        return fingerprint(self.files, self.finding_class)


# ---------------------------------------------------------------------------
# File new findings as issues
# ---------------------------------------------------------------------------

def file_finding_as_issue(
    owner: str,
    repo: str,
    finding: SelfReviewFinding,
    repo_root: str = ".",
) -> Optional[int]:
    """
    File a self-review finding as a GitHub issue with the hos-coordination label.

    Returns the new issue number, or None on failure.
    The filed fingerprint is recorded so the same finding isn't filed twice.
    """
    from scripts.automation.lib.github import _run_gh, GitHubError

    title = f"[AI: self-review] {finding.finding_class}: {finding.description[:80]}"
    body = (
        f"---hos-envelope\n"
        f"type: report\n"
        f"correlation-id: {finding.fp}\n"
        f"from: hos-worker\n"
        f"protocol-version: \"1.0\"\n"
        f"---\n\n"
        f"**Self-review finding**\n\n"
        f"**Class:** {finding.finding_class}\n"
        f"**Severity:** {finding.severity}\n"
        f"**Files:** {', '.join(finding.files)}\n\n"
        f"**Description:** {finding.description}\n\n"
        f"**Raw finding:**\n```\n{finding.raw_text[:1000]}\n```\n\n"
        f"**Dispositions:** fix | won't-fix+suppress | escalate\n"
        f"Reply with `Decision: fix`, `Decision: suppress <reason>`, or `Decision: escalate`."
    )
    try:
        result = _run_gh([
            f"/repos/{owner}/{repo}/issues",
            "--method", "POST",
            "--field", f"title={title}",
            "--field", f"body={body}",
            "--field", "labels=[\"hos-coordination\", \"needs-ai\"]",
        ])
        if result:
            issue_number = result.get("number")
            if issue_number:
                _record_filed(finding.fp, issue_number, finding.raw_text, repo_root)
                return issue_number
    except GitHubError:
        pass
    return None


# ---------------------------------------------------------------------------
# Main: run validate_self and file new findings
# ---------------------------------------------------------------------------

def run_self_review_cycle(
    owner: str,
    repo: str,
    repo_root: str = ".",
    cross_vendor: bool = False,
) -> list[SelfReviewFinding]:
    """
    Run validate_self, parse findings, dedup against filed+suppressed, return new ones.

    Findings in HUMAN_ONLY_SUPPRESSION_CLASSES are returned but flagged —
    the caller (triage) escalates them to human rather than auto-acting.
    """
    # Run validate_self (the HOS self-review script)
    result = subprocess.run(
        ["bash", "scripts/framework/validate_self.sh", "--json"],
        capture_output=True, text=True, check=False,
        cwd=repo_root,
    )
    raw_output = result.stdout + result.stderr

    # Parse findings — validate_self.sh outputs one JSON object per finding
    findings: list[SelfReviewFinding] = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
            finding = SelfReviewFinding(
                files=rec.get("files", []),
                finding_class=rec.get("class", "unknown"),
                description=rec.get("description", ""),
                raw_text=line,
                severity=rec.get("severity", "medium"),
            )
            findings.append(finding)
        except (json.JSONDecodeError, KeyError):
            pass

    # Dedup: skip already-filed and suppressed
    already_filed = _load_filed(repo_root)
    new_findings: list[SelfReviewFinding] = []
    for f in findings:
        if f.fp in already_filed:
            continue
        if is_suppressed(f.fp, repo_root):
            continue
        new_findings.append(f)

    return new_findings


# ---------------------------------------------------------------------------
# Burndown metric (M6)
# ---------------------------------------------------------------------------

def burndown_count(repo_root: str = ".") -> dict[str, int]:
    """
    Return open vs closed self-review finding counts (M6).

    A rising open count is an alert signal.
    """
    filed = _load_filed(repo_root)
    return {
        "total_filed": len(filed),
        # Open count would require querying GitHub for open issues by fingerprint —
        # deferred to the observability layer; this returns what we can compute locally.
        "suppressions": len(_load_suppressions(repo_root)),
    }
