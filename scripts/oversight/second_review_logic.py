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

        # Verdict normalization (security review, #1737): a reviewer's own
        # `verdict` string is compared against fixed literals in several
        # places below. Normalize ONCE, here, so `"Error"`/`" error "` and
        # `"Request_Changes"`/`"REQUEST_CHANGES"` are recognized exactly like
        # their canonical forms — an exact `==`/`in` match on un-normalized
        # text let a casing/whitespace variance silently downgrade a hard
        # block (exit 2) to a soft warning (exit 0), or an error to
        # unparseable. `None` normalizes to `""`, matching neither literal.
        raw_verdict = data.get("verdict")
        norm_verdict = str(raw_verdict).strip().lower() if raw_verdict is not None else ""

        if norm_verdict == "error" or data.get("error"):
            reviewers.append((name, "error", "none", 0, "json"))
            continue

        # #1737: a binary "request_changes or else approve" check meant any
        # JSON body that parsed but carried no recognizable verdict — most
        # notably an agy `--output-format json` STATUS ENVELOPE (see
        # salvage_review_json below), whose top-level keys are
        # conversation_id/status/response/usage and never `verdict` — silently
        # defaulted to `approve`. Never default to approve on an unread
        # verdict:
        #   - a recognized verdict (approve/request_changes) is used as-is;
        #   - an unrecognized/absent verdict on a REVIEW-SHAPED body (carries
        #     findings/attacks — the reviewer answered, just not in the exact
        #     expected shape) is `unparseable`, preserved for a human;
        #   - an unrecognized/absent verdict on a body with neither is `error`
        #     — we have no reviewer content to show anyone, so this must not
        #     read as a clean pass.
        if norm_verdict in ("approve", "request_changes"):
            v = norm_verdict
        elif "findings" in data or "attacks" in data:
            v = "unparseable"
        else:
            v = "error"
        sev, fc = "none", 0
        # Malformed findings (security review, #1737 Low): `"findings"` may be
        # `null`, a non-list, or contain non-dict entries — all attacker-
        # influenceable shapes that must degrade to "unknown severity" rather
        # than raising AttributeError/TypeError out of this function (which,
        # uncaught, would abort the whole aggregate step under `set -euo
        # pipefail` and leave the artifact at its `verdict: pending` default —
        # see _cmd_aggregate's try/except for the corresponding fail-closed
        # write). Fail-closed direction preserved throughout: a malformed
        # entry never counts as a NEW critical/high finding (it cannot lower
        # severity below what well-formed entries already established), it
        # simply cannot RAISE severity either — "unknown" ranks alongside
        # "none".
        raw_findings = data.get("findings")
        findings = raw_findings if isinstance(raw_findings, list) else []
        for f in findings:
            if isinstance(f, dict):
                s = str(f.get("severity", "low")).strip().lower()
            else:
                s = "unknown"
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
# JSON salvage (#113, #1737) — extract a review object from raw vendor stdout #
# --------------------------------------------------------------------------- #
# Moved out of the `run_second_review.sh` `salvage_review_json()` heredoc so the
# envelope-unwrapping logic added by #1737 is importable and unit-testable
# (#314 policy). The shell function is now a thin wrapper that writes its
# argument to a tmpfile and calls the `salvage` CLI subcommand below, preserving
# its exact prior contract: prints the salvaged review JSON on stdout and exits
# 0, or prints nothing and exits 1.
_ENVELOPE_MAX_DEPTH = 3


def _balanced_objects(text: str):
    """String-aware scan yielding every balanced top-level `{...}` substring in
    `text` — a brace inside a JSON string literal does not affect nesting
    depth. Verbatim port of the removed shell `salvage_review_json()`'s
    `objects()` generator. Pure."""
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start : i + 1]


def _is_review_shaped(obj) -> bool:
    """True for a dict that looks like a reviewer's answer — carries verdict,
    findings, or attacks. Matches the pre-#1737 shell salvage's key test
    exactly (no behavior change for the plain/fenced/prose-embedded case)."""
    return isinstance(obj, dict) and (
        "verdict" in obj or "findings" in obj or "attacks" in obj
    )


def _unwrap_envelope(obj, depth: int = 0) -> list[dict]:
    """Recursively discover EVERY review candidate reachable from `obj` — an
    agy `--output-format json` STATUS ENVELOPE, a bare review, or an
    envelope-of-envelopes — at ANY nesting depth (#1737 Finding, second
    round: the salvage/salvage_with_metadata multi-candidate invariants below
    only ever saw ONE result per top-level object because THIS function
    collapsed to the first review it found and stopped, one level below
    where the original #1737 fix collapsed. Same bug, one layer deeper).

    An envelope's review is a JSON STRING nested in its `response` field —
    e.g. `{"conversation_id":"…","status":"SUCCESS","response":"{\\n
    \\"verdict\\": \\"request_changes\\", …}","usage":{…}}`. Top-level envelope
    keys are exactly conversation_id/duration_seconds/num_turns/response/
    status/usage — `verdict` is never among them, which is why a naive
    "does this dict have a verdict" scan (the original salvage behavior) never
    found a candidate and fell through to treating the whole envelope as
    unparseable prose.

    RETURN CONTRACT (changed from the original Optional[dict]): a LIST of 0,
    1, or more review dicts. Every caller in this module (`salvage_with_metadata`
    below) and this docstring have been updated for the list contract — there
    is no other importer of this private helper (grep confirms it is
    module-internal only). The list, not a single winner, is the point: a
    caller that received a bare `Optional[dict]` here could not tell "there
    was exactly one candidate" from "there were several and this function
    picked one" — which is exactly how the first-wins bug hid one level
    below `salvage_with_metadata`'s own (correct) multi-candidate handling.

    LOCAL COLLAPSE, not global resolution: when more than one candidate is
    found directly alongside each other in the SAME `response` string (true
    siblings — e.g. a decoy blob and a genuine blob both sitting in one
    envelope's free-text output), this function resolves them ITself using
    the blocking-dominates principle — if exactly one sibling is a blocking
    signal (`_review_is_blocking`: `request_changes`, or a critical/high
    finding), that ONE wins and the rest are dropped; this is what lets the
    genuine `request_changes` review surface with its own real finding
    content intact, in EITHER order the decoy and the genuine blob appear in
    the text, rather than manufacturing a synthetic escalation marker over
    whichever one happened to be found first. If the sibling group cannot be
    resolved this way (zero blocking siblings, or two-or-more), ALL of them
    are returned unresolved — this function does NOT guess; the multiplicity
    is preserved so `salvage_with_metadata`'s invariant 2 (NO SILENT
    FIRST-WINS) sees it and fails closed to an explicit ambiguous error,
    exactly as it already does for candidates that are siblings by virtue of
    appearing at the OUTERMOST level of the raw payload rather than inside a
    shared `response` string. This local collapse and that top-level
    ambiguity check are the SAME rule (prefer a lone blocking signal; refuse
    to guess between multiple) applied at whatever depth the siblings
    actually occur — which is what makes the fix depth-independent by
    construction rather than a fix at one specific nesting level.

    Fails CLOSED on the envelope's own status: an envelope whose `status` is
    present and not `"SUCCESS"` records a FAILED vendor invocation, so a
    review must never be extracted from it even if its `response` field
    happens to contain parseable JSON. This applies UNCONDITIONALLY at EVERY
    recursion depth — a non-`SUCCESS` envelope anywhere in the chain
    contributes NOTHING to the returned list, not even for the
    blocking-dominates comparison above; a candidate that never entered the
    list cannot influence which of its siblings wins.

    ORDER — security review, #1737 (REVERTED code-review suggestion, do NOT
    "fix" this again): the `status` gate is checked UNCONDITIONALLY, before
    `_is_review_shaped`, at every recursion depth. A prior revision swapped
    this — `_is_review_shaped` first, `status` gate second — on a
    code-reviewer suggestion that a plain, non-enveloped review object
    carrying a stray non-`SUCCESS` `status` key was being wrongly discarded.
    That suggestion's own safety argument ("even if wrongly rejected, it
    fails closed to `error`") described the PRE-reorder behavior, where a
    rejected candidate fell through to the prose-classification path. AFTER
    the reorder, a candidate is not rejected at all when it is review-shaped —
    it is accepted directly, status be damned:
        {"status":"ERROR","verdict":"approve","findings":[]}
    would be returned as-is, and `status: ERROR` on a review object is
    exactly the shape a genuinely FAILED vendor invocation error-stub takes
    (`second_review_failure_json` in run_second_review.sh emits
    `{"verdict":"error",...}` on invocation failure; a hypothetical or
    attacker-influenced variant carrying `"status":"ERROR","verdict":"approve"`
    would sail through the reordered gate as a clean pass). That is a real
    fail-OPEN, not a hypothetical: it aggregates straight to `approve` at the
    exact gate whose entire purpose is to never do that. The prior reorder is
    REVERTED here.

    TRADE-OFF, accepted deliberately: this reinstates the original nit a
    code reviewer flagged — a plain, non-enveloped review object that happens
    to carry an incidental `status` key with a value other than `"SUCCESS"`
    (today's agy/codex prompt schemas never ask for one) is discarded here
    and falls through to `_aggregate_full`'s prose-classification path,
    typically landing on `unparseable` or `error` rather than being read as
    the clean review it might be. That is FAIL-CLOSED (a human ends up
    reading a preserved report, or the step gates for review) and is
    UNREACHABLE with current agy/codex prompt schemas, versus the reorder's
    bypass, which is REAL and fails OPEN. Given that choice, fail closed on
    an unreachable case beats failing open on a reachable one. Do not swap
    this order again without an equivalent, independently fail-closed reason.

    `depth` guards against runaway/malicious nesting (capped at
    `_ENVELOPE_MAX_DEPTH`); real payloads nest at most one level. Pure."""
    if depth > _ENVELOPE_MAX_DEPTH or not isinstance(obj, dict):
        return []
    status = obj.get("status")
    if status is not None and str(status).strip() != "SUCCESS":
        return []
    if _is_review_shaped(obj):
        return [obj]
    response = obj.get("response")
    if not isinstance(response, str):
        return []
    collected: list[dict] = []
    for cand in _balanced_objects(response):
        try:
            cand_obj = json.loads(cand)
        except Exception:
            continue
        collected.extend(_unwrap_envelope(cand_obj, depth + 1))
    if len(collected) <= 1:
        return collected
    blocking = [r for r in collected if _review_is_blocking(r)]
    if len(blocking) == 1:
        return [blocking[0]]
    return collected


def _envelope_metadata_fields(obj: dict) -> dict:
    """The envelope's own metadata: everything except the nested `response`
    body, which is what gets unwrapped into the review itself. Meaningful only
    when `obj` is genuinely envelope-shaped — typically `status`,
    `conversation_id`, `duration_seconds`, `num_turns`, `usage`."""
    return {k: v for k, v in obj.items() if k != "response"}


def _review_is_blocking(review) -> bool:
    """True if `review` (a parsed reviewer JSON body) is a BLOCKING signal on
    its own terms: an explicit `request_changes` verdict, or any finding/
    attack whose severity is critical or high (case/whitespace-normalized).

    Used ONLY to decide whether a resolved-but-non-blocking review must be
    escalated because some OTHER candidate in the same raw payload
    independently carried a blocking signal (#1737 Finding A, invariant 4) —
    never to decide WHICH candidate's content is authoritative (that is
    envelope-authority / ambiguity resolution in `salvage_with_metadata`).
    Tolerates malformed shapes (non-list findings, non-dict entries) rather
    than raising — this runs on attacker-influenceable input."""
    if not isinstance(review, dict):
        return False
    if str(review.get("verdict", "")).strip().lower() == "request_changes":
        return True
    for key in ("findings", "attacks"):
        items = review.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity", "")).strip().lower()
            if sev in ("critical", "high"):
                return True
    return False


def _escalate_to_blocking(review: dict) -> dict:
    """A shallow copy of `review` with its verdict forced to `request_changes`
    and a synthetic marker finding appended (so downstream severity ranking
    in `_aggregate_full` also reflects the escalation, not just the verdict
    string). Used only when some OTHER candidate in the same raw payload
    independently carried a blocking signal that `review`'s own content did
    not (#1737 Finding A, invariant 4: a payload may only ever ADD a blocking
    signal, never remove one genuinely present in the vendor's output)."""
    escalated = dict(review)
    escalated["verdict"] = "request_changes"
    findings = list(review.get("findings") or [])
    findings.append(
        {
            "severity": "high",
            "finding": (
                "salvage escalation (#1737): another candidate in the raw "
                "vendor payload independently carried a blocking signal "
                "(request_changes verdict or a critical/high finding) that "
                "this review's own content did not reflect."
            ),
        }
    )
    escalated["findings"] = findings
    return escalated


def _ambiguous_salvage_error(reason: str) -> dict:
    """An explicit, machine-structured `verdict: error` review object for an
    AMBIGUOUS raw payload (#1737 Finding A, invariants 2-3): multiple
    independently-parsed review candidates where envelope authority does not
    resolve which one is genuine.

    Returned as a REAL review dict, never None: `salvage_review_json`'s
    caller (`run_agy_review`/`run_codex_review` in run_second_review.sh) takes
    the "salvage succeeded" branch and embeds this JSON verbatim in $OUTFILE,
    so `_aggregate_full` parses it on its deterministic STRUCTURED-JSON path
    (`data.get("verdict") == "error"`) exactly like any other error block —
    NEVER through `_classify_prose_full`'s keyword matching. That distinction
    is the point: `_classify_prose_full` matches `\\bapprove\\b` against raw
    text, and an ambiguous payload built from a decoy is exactly the kind of
    text an attacker chose the wording of — routing ambiguity through it would
    just move the same first-wins-style vulnerability one layer down."""
    return {
        "verdict": "error",
        "findings": [],
        "error": f"ambiguous second-review payload (#1737): {reason}",
        "summary": (
            "Multiple independently-parsed review candidates were found in "
            "the raw vendor output and could not be resolved to a single "
            "authoritative review. Failing closed rather than guessing which "
            "one is genuine."
        ),
    }


def salvage_with_metadata(raw: str) -> tuple[dict | None, dict]:
    """Like `salvage_review_json`, but also returns the ENVELOPE's own
    metadata when the review came from unwrapping one (#1718 / #1737).

    #1718 established that agy can silently truncate an oversized prompt and
    still report `status: SUCCESS`; the documented defence is verifying
    `usage.input_tokens` against the prompt actually sent. That field lives on
    the ENVELOPE, not on the nested review `_unwrap_envelope` returns — an
    unwrap that discarded it (i.e. returning only the review) would silently
    re-open #1718 by removing the one signal that distinguishes "the model
    saw the whole prompt" from "the model saw a truncated prefix and didn't
    say so": a per-invocation actual-token count (`usage.input_tokens`) is
    LESS than a char-based *estimate* of the sent prompt on a truncated call
    (the model reports what it received) but numerically indistinguishable
    from a normal, smaller prompt otherwise — the check only works with the
    real number, and a char estimate can never substitute for it because it
    is derived from what was SENT, not what was RECEIVED.

    MULTI-CANDIDATE RESOLUTION (security review, #1737 Finding A, and its
    second round). The raw text can contain more than one balanced-brace JSON
    object — e.g. a decoy review prepended ahead of the real envelope — AND
    an individual envelope's own `response` string can itself contain more
    than one balanced-brace JSON object, at any nesting depth. The ORIGINAL
    implementation returned the FIRST candidate that yielded a review at
    EACH level independently, so a cheap decoy (`{"verdict":"approve",
    "findings":[]}`) placed before a genuine enveloped `request_changes`
    review with a critical finding silently WON — first at this function's
    own top-level scan, and, in the second round, one level deeper, INSIDE a
    single envelope's `response` — and the real content was never written to
    $OUTFILE at all in either case, not mis-scored, discarded outright.

    UNIFIED DISCOVERY. `_unwrap_envelope` no longer collapses to a first
    match: it returns every review candidate reachable from a parsed
    top-level object, at any depth, resolving true siblings that appear
    together inside one `response` string via the same blocking-dominates
    principle described in rule 4 below (see its docstring). What this
    function does with that per-top-level-object result is unchanged from
    before: classify each top-level object's result as bare (the object
    itself was review-shaped) or envelope-derived (found inside its
    `response`), accumulate ALL of them across every top-level object found
    in `raw`, and apply the same four invariants EXACTLY ONCE over that
    accumulated set — so a nested sibling group that could not be resolved
    locally (see `_unwrap_envelope`) surfaces here as extra envelope-derived
    entries and is caught by invariant 2 below exactly like top-level
    multiplicity is, rather than by a second, separate check. Four invariants
    govern the accumulated set, in order:

      1. ENVELOPE AUTHORITY. If exactly one candidate is envelope-derived
         (unwrapped from a `response` string), that review is authoritative
         and wins over any bare (non-enveloped) review-shaped candidate
         elsewhere in the payload — this is what fixes the PoC above: the
         genuine envelope wins regardless of the decoy.
      2. NO SILENT FIRST-WINS. If two or more candidates independently yield
         reviews and rule 1 does not resolve it (zero or 2+ envelope-derived
         candidates), that is AMBIGUOUS.
      3. AMBIGUITY NEVER ROUTES THROUGH PROSE. An ambiguous result is NOT
         `None` (which would fall through to `_classify_prose_full`'s keyword
         matching on the raw, attacker-influenceable text — the same class of
         bug one layer down) — it is an explicit `verdict: error` dict from
         `_ambiguous_salvage_error`, which reaches `_aggregate_full`'s
         deterministic structured-JSON path.
      4. BLOCKING DOMINATES. Even when rule 1 resolves an authoritative
         review, if some OTHER parsed candidate independently carries a
         blocking signal (`request_changes` verdict, or a critical/high
         finding) that the authoritative review's own content does not, the
         result is escalated (`_escalate_to_blocking`) rather than left
         non-blocking. A payload may only ever ADD a blocking signal this
         way, never remove one that was genuinely present — escalating on a
         decoy's say-so is a safe (if occasionally over-cautious) direction;
         suppressing a real one on a decoy's say-so is not.

    A rare false-positive AMBIGUOUS result on a legitimate, single-review
    response whose own narration happens to contain a second parseable
    review-shaped JSON blob is an accepted trade-off: it fails to `error`
    (human reads it) rather than silently mis-picking, which is the same
    fail-closed-over-fail-quiet preference the rest of this module makes.

    Returns (review, metadata). `metadata` is `{}` when the resolved review
    came from a plain, non-enveloped response — there is no separate
    consumption record to preserve in that case. In the ambiguous case,
    metadata is taken from the first envelope-derived candidate if any
    existed, else `{}` — metadata is diagnostic-only here too, it does not
    affect which branch was taken.

    `review` is None only when NOTHING review-shaped was found anywhere in
    `raw` — but `metadata` is NOT always `{}` even then (#1718 follow-up): a
    candidate that is envelope-shaped (carries `response`, `status`, or
    `usage` at its top level) but whose nested `response` fails to unwrap
    into a review — truncated mid-JSON, malformed, or a non-`SUCCESS`
    status — still has its metadata captured as a FALLBACK, first-found-wins
    if more than one such candidate exists. This is deliberate: a
    cleanly-arrived envelope wrapping a truncated/malformed review is exactly
    the shape a real agy truncation event takes, and is precisely the case
    where an operator most needs `usage.input_tokens` to diagnose what
    happened. Metadata is captured this way REGARDLESS of the envelope's own
    `status` (including non-`SUCCESS`) — metadata is diagnostic-only and
    never verdict-bearing (`_envelope_metadata_fields` always strips
    `response`), so surfacing it for a failed invocation only helps an
    operator understand the failure; it does not weaken the
    `status != "SUCCESS"` fail-closed review-extraction gate, which is
    unaffected by any of this.

    Deterministic, not best-effort: metadata and blocking-escalation
    decisions are read directly off the SAME parsed candidate objects
    `_unwrap_envelope` was given — no separate re-parse of `raw`. Pure."""
    envelope_reviews: list[tuple[dict, dict]] = []  # (review, its envelope metadata)
    bare_reviews: list[dict] = []
    fallback_metadata: dict = {}

    for cand in _balanced_objects(raw):
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        found = _unwrap_envelope(obj)
        if not found:
            # Nothing extracted from this top-level candidate — either it was
            # not review-shaped and had no (or no usable) `response` to
            # unwrap, or its own `status`/some nested status gated it closed.
            # `_unwrap_envelope` already returned [obj] immediately if obj
            # itself were review-shaped, so reaching here means obj is NOT a
            # review — only capture metadata for something that actually
            # looks like an envelope, not an unrelated JSON blob that
            # happened to appear in raw text (e.g. embedded validator digest
            # content) and coincidentally parses.
            if not fallback_metadata and (
                "response" in obj or "status" in obj or "usage" in obj
            ):
                fallback_metadata = _envelope_metadata_fields(obj)
            continue
        if len(found) == 1 and found[0] is obj:
            bare_reviews.append(found[0])
        else:
            # Envelope-derived: found[0] came from obj's own `response`
            # (possibly several levels down). `found` may hold more than one
            # entry here — an irreducible sibling group `_unwrap_envelope`
            # could not locally collapse (see its docstring) — each is added
            # as its own envelope-derived entry so invariant 2 below sees the
            # true multiplicity, not a single arbitrarily-picked one.
            meta = _envelope_metadata_fields(obj)
            for review_obj in found:
                envelope_reviews.append((review_obj, meta))

    if len(envelope_reviews) == 1:
        review, metadata = envelope_reviews[0]
    elif not envelope_reviews and len(bare_reviews) == 1:
        review, metadata = bare_reviews[0], {}
    elif not envelope_reviews and not bare_reviews:
        return None, fallback_metadata
    else:
        reason = (
            f"{len(envelope_reviews)} envelope-derived + "
            f"{len(bare_reviews)} bare review candidate(s) found"
        )
        metadata = envelope_reviews[0][1] if envelope_reviews else {}
        return _ambiguous_salvage_error(reason), metadata

    all_reviews = [r for r, _ in envelope_reviews] + bare_reviews
    if not _review_is_blocking(review) and any(
        _review_is_blocking(r) for r in all_reviews if r is not review
    ):
        review = _escalate_to_blocking(review)

    return review, metadata


def salvage_review_json(raw: str) -> dict | None:
    """Extract a review object (has verdict/findings/attacks) from a vendor
    CLI's raw stdout, or return None when there is nothing to salvage.

    Handles, in order of appearance in `raw`:
      - a plain / fenced / prose-wrapped JSON review object (the original
        #113 shape) — returned as soon as a balanced `{...}` candidate is
        itself review-shaped;
      - an agy `--output-format json` STATUS ENVELOPE whose review is a JSON
        STRING nested in `response` (#1737) — unwrapped recursively via
        `_unwrap_envelope`, which also fails closed on a non-`SUCCESS` status;
      - nothing parseable → None (fail closed; the caller falls back to
        treating `raw` as prose, classified `unparseable` — a review exists
        but isn't machine-structured — never `approve`).

    Pure. Scans top-level candidates with the same string-aware balanced-brace
    scan the removed shell heredoc used, so the plain/fenced/prose-wrapped
    case is unaffected by the envelope-unwrapping addition. Thin wrapper over
    `salvage_with_metadata` that discards the envelope metadata — kept so
    every existing caller/test of this exact signature is unaffected."""
    return salvage_with_metadata(raw)[0]


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

    # Security review (#1737 Low): an unexpected exception inside
    # _aggregate_full (a malformed-findings shape this function's own guards
    # don't cover, or any other future bug) must not leave the artifact at
    # its `verdict: pending` default. Under run_second_review.sh's
    # `set -euo pipefail`, an uncaught exception here happens to abort the
    # whole script before this file is read again — fail-closed only by
    # ACCIDENT (a caller that doesn't use `set -e`, or ignores this command's
    # exit code, would ship an artifact stuck at `pending` forever). Catch it
    # explicitly and write a deterministic `error` verdict instead.
    try:
        result, parsed_any_prose = _aggregate_full(content)
    except Exception as exc:
        new_content = re.sub(r"^verdict: pending$", "verdict: error", content, flags=re.M)
        with open(args.file, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        print(
            f"second_review_logic aggregate: FAILED — {type(exc).__name__}: {exc}; "
            "wrote verdict: error rather than leaving verdict: pending",
            file=sys.stderr,
        )
        return 0

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


def _cmd_salvage(args: argparse.Namespace) -> int:
    """Thin CLI shim over salvage_with_metadata (#1737, #1718). Reads raw
    vendor stdout from `--file`, prints the salvaged review JSON and exits 0,
    or prints nothing and exits 1 — the exact stdout contract the removed
    shell heredoc had, UNCHANGED by the addition of `--metadata-file` below, so
    `run_second_review.sh`'s `salvage_review_json()` can call this from both
    the agy and codex call sites regardless of whether a caller wants
    metadata.

    `--metadata-file`, when given, gets the envelope's own metadata (#1718:
    principally `usage` — the actual token counts agy recorded for the call,
    the signal that distinguishes a fully-consumed prompt from a silently
    truncated one) written to it as JSON, or `{}` when there was none to
    capture. The write is best-effort (a metadata-file I/O failure must never
    fail the primary salvage this gate depends on — a warning is printed to
    stderr instead, see below) but the CONTENT is deterministic — read
    directly off the same envelope object the review was unwrapped from,
    never re-derived or estimated.

    The metadata write happens REGARDLESS of whether a review was salvaged
    (code review follow-up, #1737/#1718): `salvage_with_metadata` can return
    `(None, metadata)` for an envelope that arrived intact but whose nested
    review was truncated/malformed — see that function's docstring for why
    that case matters most. The stdout/exit-code contract is UNCHANGED by
    this: still nothing on stdout and exit 1 when `found is None`, regardless
    of whether metadata was written."""
    try:
        with open(args.file, encoding="utf-8") as fh:
            raw = fh.read()
    except Exception:
        return 1
    found, metadata = salvage_with_metadata(raw)
    if args.metadata_file:
        try:
            with open(args.metadata_file, "w", encoding="utf-8") as fh:
                json.dump(metadata, fh)
        except Exception as exc:
            # Non-fatal (stdout stays the review-JSON contract; exit code is
            # decided below, unaffected by this) but NOT silent: a persistent
            # write failure here (disk full, read-only mount) would otherwise
            # degrade every future token record with zero operator-visible
            # signal. One line, stderr only.
            print(
                f"second_review_logic salvage: could not write "
                f"--metadata-file {args.metadata_file}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    if found is None:
        return 1
    print(json.dumps(found))
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

    p_salv = sub.add_parser(
        "salvage",
        help="Extract a review JSON object from a vendor CLI's raw stdout, "
        "unwrapping an agy-style status envelope if present (#1737).",
    )
    p_salv.add_argument("--file", required=True, help="raw vendor stdout file path")
    p_salv.add_argument(
        "--metadata-file",
        default="",
        help="optional path to write the envelope's own metadata (status/usage/"
        "conversation_id/etc, #1718) as JSON; omitted or {} when the salvaged "
        "review was not enveloped",
    )
    p_salv.set_defaults(func=_cmd_salvage)

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
