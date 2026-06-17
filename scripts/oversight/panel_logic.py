#!/usr/bin/env python3
"""panel_logic.py — corroboration counting and tier ranking for the review panel.

SPEC-376 / Issue #376. The HOS cross-vendor panel arbiter (run_panel.sh ARBITER
stage) deduplicates the independent reviewers' findings. This module adds the
missing CORROBORATION-RANKING step on top of that dedup pass: it counts how many
INDEPENDENT vendors agreed on each deduplicated finding, classifies findings into
two corroboration tiers, and orders them so cross-vendor-confirmed findings
surface to the human first.

Why this matters (research grounding):
  - CodeRabbit produces ~1.7x single-reviewer volume (Loker 2025); panel volume
    scales with roster size. Without ranking, reviewer fatigue is the failure mode.
  - AgenticSCR's detector->validator architecture raised precision while cutting
    comment volume 81% by surfacing corroborated findings first (Charoenwet 2026).

Authoritative clustering stays with Sonnet (architect binding 2): the arbiter
prompt emits per-finding `merged_from` membership, and THIS module counts vendor
corroboration deterministically from that membership. Same-vendor / different-lens
(codex:security + codex:adversary) collapses to ONE independent source (binding 3).

PURITY (binding 6 / AC4): count_corroboration, reconcile_membership, and
rank_findings perform NO subprocess, network, or file I/O. They are importable
and unit-testable with plain dicts. Only the __main__ CLI shim does I/O.

FAIL-OPEN (binding 7): a finding with no resolvable membership defaults to
corroborated_by=1, corroboration_tier=2. Nothing is ever suppressed (binding 9).
"""

from __future__ import annotations

import argparse
import json
import sys

# Severity rank: lower = more severe = ordered earlier. Unknown sorts last.
_SEVERITY_RANK = {"tier1": 0, "tier2": 1, "tier3": 2, "tier4": 3}
_SEVERITY_UNKNOWN = 99

# Line-proximity tolerance for the fallback reconciliation (OQ-1 default, ratified).
_LINE_PROXIMITY = 5


def count_corroboration(deduplicated_finding: dict) -> tuple[int, list[str]]:
    """Count INDEPENDENT vendors that corroborate one deduplicated finding.

    Reads `merged_from` (list of {"reviewer","lens"}) — the membership list the
    Sonnet arbiter emits (binding 2). Counts DISTINCT `reviewer` (vendor) values:
    the same vendor under two lenses collapses to one (binding 3).

    Returns (corroborated_by_count, sorted_unique_reviewers). The count is always
    >= 1 (binding 7 fail-open): a finding with missing/empty/malformed membership
    defaults to a single corroborating reviewer (its own `reviewer`, or "unknown").
    Pure: no I/O, does not mutate the input.
    """
    merged_from = deduplicated_finding.get("merged_from")
    if isinstance(merged_from, list) and merged_from:
        vendors = sorted(
            {
                entry["reviewer"]
                for entry in merged_from
                if isinstance(entry, dict) and entry.get("reviewer")
            }
        )
        if vendors:
            return (len(vendors), vendors)

    # Fail-open floor: a finding always counts as corroborated by at least itself.
    own = deduplicated_finding.get("reviewer") or "unknown"
    return (1, [own])


def reconcile_membership(raw_findings: list, finding: dict) -> list:
    """Reconstruct membership by file+line proximity — FALLBACK ONLY (binding 3).

    Called only when a finding's `merged_from` is missing/empty (a degraded
    arbiter response). Matches a raw finding to `finding` iff they share the same
    file path AND their line numbers are within +/-5 (binding 3 / OQ-1 default).

    Returns a list of {"reviewer","lens"} dicts (the reconstructed membership)
    suitable to assign to finding["merged_from"]. A finding with no file/line, or
    no matches, returns []. Pure: reads only its two arguments; no I/O.
    """
    f_file = finding.get("file")
    f_line = finding.get("line")
    if not f_file or f_line is None or not isinstance(raw_findings, list):
        return []
    try:
        f_line_i = int(f_line)
    except (TypeError, ValueError):
        return []

    membership: list[dict] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        if not raw.get("file") or raw.get("file") != f_file:
            continue
        r_line = raw.get("line")
        if r_line is None:
            continue
        try:
            r_line_i = int(r_line)
        except (TypeError, ValueError):
            continue
        if abs(r_line_i - f_line_i) <= _LINE_PROXIMITY:
            membership.append(
                {"reviewer": raw.get("reviewer"), "lens": raw.get("lens")}
            )
    return membership


def _severity_key(finding: dict) -> int:
    return _SEVERITY_RANK.get(finding.get("severity"), _SEVERITY_UNKNOWN)


def rank_findings(findings: list) -> list:
    """Order findings: Tier 1 (corroborated_by >= 2) before Tier 2, severity within.

    Sort key (all ascending, binding 3 + 4):
      1. corroboration_tier   (1 before 2; absent -> fail-open 2)
      2. severity rank        (tier1 most severe first; absent -> last)
      3. file, then line      (stable, deterministic tie-break)

    Returns a NEW sorted list. Pure: does not mutate inputs or perform I/O.
    Findings missing corroboration_tier are ordered as tier 2 (binding 7) without
    being mutated.
    """
    if not isinstance(findings, list):
        return []

    def key(finding: dict):
        tier = finding.get("corroboration_tier")
        if tier not in (1, 2):
            tier = 2  # fail-open ordering
        return (
            tier,
            _severity_key(finding),
            str(finding.get("file") or ""),
            int(finding.get("line") or 0) if str(finding.get("line") or "0").lstrip("-").isdigit() else 0,
        )

    return sorted(findings, key=key)


# --------------------------------------------------------------------------- #
# CLI shim — the ONLY place in this module that performs I/O (binding 6 note). #
# Reads the arbiter JSON object on stdin, annotates each finding with the      #
# corroboration fields, reorders findings, writes the object to stdout.        #
# --------------------------------------------------------------------------- #
def annotate_and_rank(arbiter_obj: dict, raw_findings: list | None = None) -> dict:
    """Annotate every finding with corroboration fields and reorder them.

    For a finding with empty/missing `merged_from`, if `raw_findings` is provided
    reconstruct membership via reconcile_membership first (binding 3 fallback).
    Then count corroboration, assign tier, and rank. Returns a NEW object; the
    `summary` field is passed through untouched. Never suppresses a finding
    (binding 9).
    """
    findings = arbiter_obj.get("findings")
    if not isinstance(findings, list):
        return arbiter_obj

    annotated: list[dict] = []
    for finding in findings:
        if not isinstance(finding, dict):
            annotated.append(finding)
            continue
        f = dict(finding)  # do not mutate caller's dict
        mf = f.get("merged_from")
        if (not isinstance(mf, list) or not mf) and raw_findings:
            recovered = reconcile_membership(raw_findings, f)
            if recovered:
                f["merged_from"] = recovered
        count, reviewers = count_corroboration(f)
        f["corroborated_by"] = count
        f["corroborating_reviewers"] = reviewers
        f["corroboration_tier"] = 1 if count >= 2 else 2
        annotated.append(f)

    out = dict(arbiter_obj)
    out["findings"] = rank_findings(annotated)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Annotate + corroboration-rank panel arbiter findings (SPEC-376)."
    )
    parser.add_argument(
        "--raw",
        default=None,
        help="path to findings.raw.json (fallback membership reconciliation)",
    )
    args = parser.parse_args(argv)

    data = sys.stdin.read()
    # Fail-closed-safe: any parse/processing error -> echo input unchanged, exit 0.
    # Ranking is an enhancement, never a gate; the panel must still post findings.
    try:
        arbiter_obj = json.loads(data)
    except Exception:
        sys.stdout.write(data)
        return 0

    raw_findings = None
    if args.raw:
        try:
            with open(args.raw, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, list):
                raw_findings = loaded
        except Exception:
            raw_findings = None

    try:
        result = annotate_and_rank(arbiter_obj, raw_findings)
    except Exception:
        sys.stdout.write(json.dumps(arbiter_obj))
        return 0

    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
