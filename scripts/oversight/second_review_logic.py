#!/usr/bin/env python3
"""second_review_logic.py — reviewer selection + verdict aggregation for second review.

SPEC-331 / Issue #331. `run_second_review.sh` (the pre-PR cross-vendor second
review) previously made two deterministic decisions with inline `python3 -c`
fragments and a ~100-line `python3 - <<PYEOF` heredoc:

  1. REVIEWER SELECTION — should agy and/or codex fire, given the composite risk
     score, the validated tier, and the two configured thresholds.
  2. VERDICT AGGREGATION — parse the second-review output file's reviewer
     sections, classify JSON-or-prose responses, compute the aggregate severity
     and final verdict (error > request_changes > unparseable > approve), and
     rewrite the three machine-readable header lines in place.

Both are deterministic rule logic (#314 policy: prefer Python for logic, shell for
launch). This module extracts them into named, importable, unit-testable functions
so a bug in threshold comparison or verdict precedence can be caught without
running the full shell script or any live model.

PURITY (architect binding 5 / spec R4): select_reviewers, classify_prose, and
aggregate_verdicts perform NO subprocess, network, or file I/O. They take/return
plain values and are unit-testable with synthetic content strings. Only the
__main__ CLI shim reads argv and reads/writes the output file (binding 2: the
logic takes `content: str`, the shim does the in-place rewrite).

This is a NEW module, NOT merged into panel_logic.py (binding 1). classify_prose
stays here, not shared with panel_logic.py (binding 3 — sharing deferred).

NO BEHAVIOR CHANGE (spec §5): the regexes, branch ordering, severity ranking, and
verdict precedence are reproduced from the original heredoc exactly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Severity ordering: lower index = more severe. Unknown severity ranks as "none"
# (least severe), matching the heredoc's SEV_RANK.get(s, 4).
_SEVERITIES = ["critical", "high", "medium", "low", "none"]
_SEV_RANK = {s: i for i, s in enumerate(_SEVERITIES)}
_SEV_UNKNOWN_RANK = 4

# Tier floors (architect ratchet): MEDIUM+ forces agy; HIGH+ forces both.
_AGY_TIERS = {"MEDIUM", "HIGH", "CRITICAL"}
_CODEX_TIERS = {"HIGH", "CRITICAL"}


# --------------------------------------------------------------------------- #
# R1 — reviewer selection                                                     #
# --------------------------------------------------------------------------- #
def select_reviewers(
    score: float,
    tier: str,
    agy_threshold: float,
    codex_threshold: float,
) -> tuple[bool, bool]:
    """Decide which second-review reviewers fire for a step.

    Returns (run_agy, run_codex) — ORDER IS FIXED: agy first, codex second.

    Matches run_second_review.sh lines 126-138 exactly:
      - agy fires if tier is MEDIUM/HIGH/CRITICAL (case-insensitive) OR
        score >= agy_threshold.
      - codex fires if tier is HIGH/CRITICAL (case-insensitive) OR
        score >= codex_threshold.

    The tier comparison is the ratchet FLOOR: a HIGH/CRITICAL step forces both
    reviewers regardless of score; a MEDIUM step forces agy. Comparison is `>=`
    (inclusive). Pure: no env/.env read, no I/O. Threshold DEFAULTS live in the
    shell only (spec R3) — this function receives them as arguments.
    """
    tier_uc = (tier or "").strip().upper()
    run_agy = (tier_uc in _AGY_TIERS) or (score >= agy_threshold)
    run_codex = (tier_uc in _CODEX_TIERS) or (score >= codex_threshold)
    return (run_agy, run_codex)


# --------------------------------------------------------------------------- #
# Prose classification (R2 helper)                                            #
# --------------------------------------------------------------------------- #
def _classify_prose_full(text: str) -> tuple[str, str]:
    """Best-effort (verdict, severity) from a non-JSON markdown review report.

    Verbatim port of the heredoc (run_second_review.sh lines 623-637). The branch
    ORDER is load-bearing: risk-critical/high and the blocking keywords are checked
    BEFORE the approve keywords, so a body containing both "critical" and "approve"
    classifies as request_changes. The regexes are copied byte-for-byte; do not
    paraphrase. verdict is one of approve|request_changes|unparseable.
    """
    low = text.lower()
    risk = re.search(r"\brisk:\s*(critical|high|medium|low|none)\b", low)
    blocking = re.search(
        r"must[ -]?fix|tier\s*1\b|request[_ ]changes|\bblocking\b|\bcritical\b", low
    )
    approve = re.search(
        r"\bverdict:\s*approve\b|no (issues|findings|problems)|lgtm|looks good|\bapprove\b",
        low,
    )
    if risk and risk.group(1) in ("critical", "high"):
        return "request_changes", risk.group(1)
    if blocking:
        sev = "critical" if "critical" in low else "high"
        return "request_changes", sev
    if approve or (risk and risk.group(1) in ("low", "none")):
        return "approve", (risk.group(1) if risk else "none")
    return "unparseable", (risk.group(1) if risk else "none")


def classify_prose(text: str) -> str:
    """Keyword verdict extraction from a non-JSON reviewer response.

    Returns the verdict only — one of approve|request_changes|unparseable. The
    severity half of the heredoc rule is available to aggregate_verdicts via the
    private _classify_prose_full helper (no rule duplication). Pure.
    """
    return _classify_prose_full(text)[0]


# --------------------------------------------------------------------------- #
# R2 — verdict aggregation                                                    #
# --------------------------------------------------------------------------- #
def _fenced_body(text: str) -> str:
    """Content inside the outer ```json ... ``` block if present, else whole text.

    Verbatim port of heredoc lines 618-621. Pure.
    """
    m = re.search(r"```(?:json)?\s*\n(.*)\n```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def _split_sections(content: str) -> list[str]:
    """Split the output file into "## " sections, HONORING fenced code blocks.

    `run_second_review.sh` embeds each reviewer's raw output verbatim inside a
    ```` ```json … ``` ```` fence. When a reviewer returns a prose markdown
    report instead of JSON (the documented #113 degradation path), that report
    routinely carries its own "## " headings (e.g. "## Critical Issues"). Those
    are reviewer CONTENT, not section boundaries: splitting on them truncated the
    reviewer's section at its first internal heading, so a "looks good" preamble
    classified as approve while the must-fix content below was silently discarded
    (#982 — regression class of #113/#670/#683).

    Only "## " lines that appear OUTSIDE a fenced block — the reviewer/advisory
    headers the shell itself writes at column 0 — start a new section. This is
    the non-forgeable boundary: reviewer output can contain any "## " it likes
    without being mistaken for a shell-written header. Each returned element
    begins immediately after its "## " marker, matching the prior
    `re.split(r"(?m)^## ", content)[1:]` contract.
    """
    sections: list[str] = []
    current: list[str] | None = None
    in_fence = False
    for line in content.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if current is not None:
                current.append(line)
            continue
        if not in_fence and line.startswith("## "):
            if current is not None:
                sections.append("".join(current))
            current = [line[3:]]  # drop the "## " marker (old split contract)
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        sections.append("".join(current))
    return sections


def _aggregate_full(content: str) -> tuple[dict, bool]:
    """Aggregate reviewer sections → (result_dict, parsed_any_prose).

    result_dict has EXACTLY: verdict, highest_severity, unresolved_findings.
    parsed_any_prose is True if any reviewer section was parsed from prose (the
    shim uses it to render the parity prose-note). Verbatim port of the heredoc
    aggregation (run_second_review.sh lines 599-699). Pure: no file I/O.
    """
    # Each element starts after a "## " heading (fence-aware: a "## " inside a
    # reviewer's fenced body is content, not a section boundary — see #982).
    sections = _split_sections(content)

    reviewers = []  # (name, verdict, severity, finding_count, parsed_from)
    for sec in sections:
        head = sec.splitlines()[0] if sec.splitlines() else ""
        hl = head.lower()
        if hl.startswith("agy"):
            name = "agy"
        elif hl.startswith("codex"):
            name = "codex"
        else:
            continue  # not a reviewer section (verdict header, advisory, etc.)
        if "skipped" in hl:
            continue  # a skipped reviewer is handled by the pre-check

        body = _fenced_body(sec[len(head) :])
        if not body:
            reviewers.append((name, "error", "none", 0, "empty"))  # crash / no output
            continue

        # Structured path: the body is valid JSON exactly as the prompt asked.
        try:
            data = json.loads(body)
        except Exception:
            v, sev = _classify_prose_full(body)
            fc = len(re.findall(r"(?m)^\s*#{1,4}\s", body)) if v == "request_changes" else 0
            reviewers.append((name, v, sev, fc, "prose"))
            continue

        if data.get("verdict") == "error" or data.get("error"):
            reviewers.append((name, "error", "none", 0, "json"))
            continue

        v = "request_changes" if data.get("verdict") == "request_changes" else "approve"
        sev, fc = "none", 0
        for f in data.get("findings", []):
            s = str(f.get("severity", "low")).lower()
            if _SEV_RANK.get(s, _SEV_UNKNOWN_RANK) < _SEV_RANK[sev]:
                sev = s
            if s in ("critical", "high"):
                fc += 1
        reviewers.append((name, v, sev, fc, "json"))

    # Aggregate. Precedence: error > request_changes > unparseable > approve.
    # An empty reviewer list produces verdict=error (binding 4) — must never
    # silently become a PASS.
    if not reviewers:
        verdict, highest, finding_count = "error", "none", 0
    else:
        highest = "none"
        finding_count = 0
        for _, _, sev, fc, _ in reviewers:
            if _SEV_RANK.get(sev, _SEV_UNKNOWN_RANK) < _SEV_RANK[highest]:
                highest = sev
            finding_count += fc
        verds = [v for _, v, _, _, _ in reviewers]
        if "error" in verds:
            verdict = "error"
        elif "request_changes" in verds:
            verdict = "request_changes"
        elif "unparseable" in verds:
            verdict = "unparseable"
        else:
            verdict = "approve"

    parsed_any_prose = any(pf == "prose" for *_, pf in reviewers)
    result = {
        "verdict": verdict,
        "highest_severity": highest,
        "unresolved_findings": finding_count,
    }
    return result, parsed_any_prose


def aggregate_verdicts(content: str) -> dict:
    """Compute the aggregate second-review verdict from output-file text.

    Returns EXACTLY {verdict, highest_severity, unresolved_findings}:
      verdict           — approve | request_changes | unparseable | error
      highest_severity  — critical | high | medium | low | none
      unresolved_findings — count of critical/high findings across all reviewers

    Pure: takes the full output-file text as a string (binding 2 / spec R2),
    performs no file I/O. The CLI shim handles reading and rewriting the file.
    """
    return _aggregate_full(content)[0]


# --------------------------------------------------------------------------- #
# R5 (ADR-1683 D-3) — validator-summary digest                                #
# --------------------------------------------------------------------------- #
# `run_second_review.sh` no longer interpolates the raw validators/summary.json
# into the agy prompt verbatim — that document's `evidence`/`findings`/
# `checklist_items` arrays are exactly the internal-reviewer "anchoring" content
# the script's own header says must NOT be passed to these reviewers. Build a
# derived digest instead, in three deterministic tiers, degrading only as far as
# needed to fit a fixed byte cap. Pure: takes/returns plain dict + list of str;
# no file I/O (the CLI shim below does the reading and stderr printing).
_DIGEST_CAP_BYTES = 16384


def _digest_tier1(summary: dict) -> dict:
    """Top-level scalars + per-result scores/weights/floors + evidence COUNTS
    (not the evidence/findings/checklist_items arrays themselves — those are
    the anchoring content D-3 excludes)."""
    results = []
    for r in summary.get("results") or []:
        if not isinstance(r, dict):
            continue
        results.append(
            {
                "dimension": r.get("dimension"),
                "score": r.get("score"),
                "weight": r.get("weight"),
                "tier_floor": r.get("tier_floor"),
                "error": r.get("error"),
                "raw_value": r.get("raw_value"),
                "evidence_count": len(r.get("evidence") or []),
                "finding_count": len(r.get("findings") or []),
                "checklist_count": len(r.get("checklist_items") or []),
            }
        )
    return {
        "composite_score": summary.get("composite_score"),
        "tier": summary.get("tier"),
        "validator_count": summary.get("validator_count"),
        "successful_validators": summary.get("successful_validators"),
        "results": results,
    }


def _digest_tier2(tier1: dict) -> dict:
    """Tier 1 minus each result's `raw_value`."""
    out = json.loads(json.dumps(tier1))
    for r in out["results"]:
        r.pop("raw_value", None)
    return out


def _digest_tier3(summary: dict) -> dict:
    """Top-level scalars plus a bare `dimension: score` map — no per-validator
    detail at all."""
    scores = {}
    for r in summary.get("results") or []:
        if isinstance(r, dict):
            scores[str(r.get("dimension"))] = r.get("score")
    return {
        "composite_score": summary.get("composite_score"),
        "tier": summary.get("tier"),
        "validator_count": summary.get("validator_count"),
        "successful_validators": summary.get("successful_validators"),
        "scores": scores,
    }


def _digest_bytes(obj: dict) -> int:
    return len(json.dumps(obj).encode("utf-8"))


def digest_validators(summary: dict) -> tuple[dict, list[str]]:
    """Build the D-3 three-tier validator digest.

    Tries tier 1; if its serialized size exceeds `_DIGEST_CAP_BYTES`, drops to
    tier 2, then tier 3 (tier 3 has no further fallback and is always used once
    reached). The chosen digest always carries `_digest_tier` (1|2|3) and
    `_digest_note` naming what was dropped, so the reviewer model and any human
    reading the artifact see the degradation — never a silent truncation.

    Returns (digest, stderr_lines). stderr_lines is empty at tier 1; every
    degradation below tier 1 appends one line naming the tier and the byte
    count that missed the cap (D-3: "silence is not acceptable and is not
    permitted here").
    """
    stderr_lines: list[str] = []

    tier1 = _digest_tier1(summary)
    tier1_bytes = _digest_bytes(tier1)
    if tier1_bytes <= _DIGEST_CAP_BYTES:
        tier1["_digest_tier"] = 1
        tier1["_digest_note"] = "full detail: no fields dropped"
        return tier1, stderr_lines

    stderr_lines.append(
        "run_second_review: validator digest degraded to tier 2 "
        f"(tier 1 digest {tier1_bytes} B > {_DIGEST_CAP_BYTES} B cap)"
    )
    tier2 = _digest_tier2(tier1)
    tier2_bytes = _digest_bytes(tier2)
    if tier2_bytes <= _DIGEST_CAP_BYTES:
        tier2["_digest_tier"] = 2
        tier2["_digest_note"] = "raw_value dropped per validator to fit the size cap"
        return tier2, stderr_lines

    stderr_lines.append(
        "run_second_review: validator digest degraded to tier 3 "
        f"(tier 2 digest {tier2_bytes} B > {_DIGEST_CAP_BYTES} B cap)"
    )
    tier3 = _digest_tier3(summary)
    tier3["_digest_tier"] = 3
    tier3["_digest_note"] = "per-validator detail dropped; only dimension:score retained"
    return tier3, stderr_lines


# --------------------------------------------------------------------------- #
# CLI shim — the ONLY place in this module that performs I/O (binding 2).     #
# --------------------------------------------------------------------------- #
def _cmd_select_reviewers(args: argparse.Namespace) -> int:
    run_agy, run_codex = select_reviewers(
        args.score, args.tier, args.agy_threshold, args.codex_threshold
    )
    # Emit shell-eval-friendly KEY=value lines so run_second_review.sh can `eval`
    # them straight into its existing RUN_AGY / RUN_CODEX booleans.
    print(f"RUN_AGY={'true' if run_agy else 'false'}")
    print(f"RUN_CODEX={'true' if run_codex else 'false'}")
    return 0


def _cmd_aggregate(args: argparse.Namespace) -> int:
    # File read: mirror the heredoc — a read failure is not a hard error here
    # (the shell's own guards handle a missing file); print nothing, exit 0.
    try:
        with open(args.file, encoding="utf-8") as fh:
            content = fh.read()
    except Exception:
        return 0

    result, parsed_any_prose = _aggregate_full(content)
    verdict = result["verdict"]
    highest = result["highest_severity"]
    finding_count = result["unresolved_findings"]

    # Rewrite the three machine-readable header lines in place, exactly as the
    # heredoc did (lines 701-703).
    new_content = re.sub(r"^verdict: pending$", f"verdict: {verdict}", content, flags=re.M)
    new_content = re.sub(
        r"^highest_severity: none$",
        f"highest_severity: {highest}",
        new_content,
        flags=re.M,
    )
    new_content = re.sub(
        r"^unresolved_findings: 0$",
        f"unresolved_findings: {finding_count}",
        new_content,
        flags=re.M,
    )
    with open(args.file, "w", encoding="utf-8") as fh:
        fh.write(new_content)

    prose_note = (
        " (parsed from prose — agy returned a markdown report, not JSON)"
        if parsed_any_prose
        else ""
    )
    print(f"  verdict={verdict} highest_severity={highest} unresolved={finding_count}{prose_note}")
    return 0


def _cmd_digest_validators(args: argparse.Namespace) -> int:
    # Mirrors _cmd_aggregate's convention: a read/parse failure here is not a
    # hard error (the shell only calls this when the summary file already
    # exists); print nothing and exit 0 so the caller falls back to an empty
    # VALIDATOR_SUMMARY, same as a missing file did before this digest existed.
    #
    # The guard spans the digest call too, not just the read: a summary.json
    # that parses but is not an object (a JSON list, or `null`) would otherwise
    # reach _digest_tier1's .get() and raise AttributeError, and because the
    # shell assigns this via VALIDATOR_DIGEST=$(python3 …) under
    # `set -euo pipefail`, a non-zero exit here takes run_second_review.sh down
    # with it — turning a degraded digest into a dead second review, which is
    # the exact failure class #1683 exists to remove.
    # Exiting 0 is not the same as degrading silently. Both bail-outs below emit
    # one stderr line naming what was lost, so the "every degradation names
    # itself on stderr" guarantee D-3 states holds on every path out of this
    # function, not only on the tier 2/3 drops inside digest_validators().
    try:
        with open(args.file, encoding="utf-8") as fh:
            summary = json.load(fh)
        if not isinstance(summary, dict):
            print(
                f"run_second_review: validator digest omitted — {args.file} parsed as "
                f"{type(summary).__name__}, expected a JSON object; "
                "reviewer prompt carries an empty validator summary",
                file=sys.stderr,
            )
            return 0
        digest, stderr_lines = digest_validators(summary)
    except Exception as exc:
        print(
            f"run_second_review: validator digest omitted — could not read or digest "
            f"{args.file}: {type(exc).__name__}: {exc}; "
            "reviewer prompt carries an empty validator summary",
            file=sys.stderr,
        )
        return 0

    for line in stderr_lines:
        print(line, file=sys.stderr)
    print(json.dumps(digest))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Second-review reviewer selection + verdict aggregation (SPEC-331)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sel = sub.add_parser(
        "select-reviewers",
        help="Decide whether agy/codex fire. Prints RUN_AGY=/RUN_CODEX= lines.",
    )
    p_sel.add_argument("--score", type=float, required=True)
    p_sel.add_argument("--tier", default="")
    p_sel.add_argument("--agy-threshold", type=float, required=True)
    p_sel.add_argument("--codex-threshold", type=float, required=True)
    p_sel.set_defaults(func=_cmd_select_reviewers)

    p_agg = sub.add_parser(
        "aggregate",
        help="Aggregate verdict from an output file and rewrite its header in place.",
    )
    p_agg.add_argument("--file", required=True, help="second-review output file path")
    p_agg.set_defaults(func=_cmd_aggregate)

    p_dig = sub.add_parser(
        "digest-validators",
        help="Print the ADR-1683 D-3 three-tier digest of a validator summary.json.",
    )
    p_dig.add_argument("--file", required=True, help="validators summary.json path")
    p_dig.set_defaults(func=_cmd_digest_validators)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
