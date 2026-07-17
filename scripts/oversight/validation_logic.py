#!/usr/bin/env python3
"""validation_logic.py — dedup fingerprinting + verdict aggregation for the
cross-vendor validation scripts (SPEC-334 / Issue #334).

`scripts/framework/validate_agents.sh` and `scripts/framework/validate_scripts.sh`
both finalized their review verdict and recorded ledger dispositions with inline
`python3 - <<PYEOF` heredocs. Heredoc Python cannot be unit-tested, linted, or
imported. Per policy #314 (prefer Python for logic, shell for launch) this module
extracts that logic into named, importable, unit-testable functions, shared by
both scripts.

ARCHITECT BINDINGS (SPEC-334):
  1. New module at scripts/oversight/validation_logic.py.
  2. Canonical 7-rank severity ordering from validate_agents.sh:
       critical > high > blocking > warning > medium > low > none
     critical/high are NOT collapsed to blocking (that collapse was the
     validate_scripts.sh bug being fixed).
  3. The shell owns the pass cap. compute_verdict returns new_blocking_count;
     the shell enforces the count and the exit code. The CLI emits process exit
     codes ONLY for operational failure (bad args, unreadable output) — never
     for verdict logic.
  4. --record is unified: both scripts delegate ledger-entry writes to this
     module's `record` subcommand. --reset stays in the shell.
  5. The fingerprint checks BOTH `category` (agy) AND `type` (codex), preferring
     whichever is present (AC-2).
  6. The robust string-aware brace extractor from validate_agents.sh is the
     single extractor for both scripts.
  7. No-blocks-parsed behavior is flag-controlled (--strict-empty): set → "error"
     verdict (validate_agents.sh behavior); unset → "approve"/exit 0
     (validate_scripts.sh compat). Default OFF.
  8. Stdlib only; never sources config.sh; the logic functions perform no
     subprocess/network I/O. The only file I/O is reading the ledger (an input
     to the verdict) and the dedicated ledger append in record_ledger_entry; the
     output-file read/write lives in the CLI shim.

PURITY: extract_json_objects and fingerprint are pure (value in, value out).
compute_verdict reads the ledger path (its defined input). record_ledger_entry
appends exactly one ledger line (its defined operation). No other side effects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

# Canonical severity ordering (binding 2). Lower index = more severe. Applied to
# BOTH scripts; critical/high are never collapsed to blocking.
SEVERITIES = ["critical", "high", "blocking", "warning", "medium", "low", "none"]

# Severities that count as a blocking finding for verdict purposes.
BLOCKING_SEVERITIES = ("critical", "high", "blocking")

# A reviewer block carrying this verdict (e.g. agy/codex timed out and emitted
# {"verdict":"error","findings":[]}) is an operational FAILURE to review, not a
# clean pass. It counts as a blocking finding and is never dedup-silenced — a
# timeout has no stable fingerprint and must always gate (fail-closed, #670).
ERROR_VERDICT = "error"

# Verdict ordering for the pre-PR pipeline ratchet (higher = more blocking).
# `run_second_review.sh` runs `second_review_logic.py aggregate` (which rewrites
# `verdict: pending` → e.g. `approve`) BEFORE `validation_logic.py process`. When
# `process` re-keys the verdict it must be free to UPGRADE the file (this step's
# ledger-aware compute can raise an approve to request_changes — e.g. a #670
# error block, or a reviewer that returned {"verdict":"approve"} alongside a
# critical finding) but must NEVER DOWNGRADE a blocking verdict already written
# to approve (#683). Unknown verdicts rank below approve so a known computed
# verdict wins rather than an unrecognized string sticking.
_VERDICT_RANK = {
    "pending": 0,
    "skipped": 0,
    "approve": 1,
    "unparseable": 2,
    "request_changes": 3,
    "error": 4,
}


def _verdict_rank(verdict: str) -> int:
    return _VERDICT_RANK.get(str(verdict).strip().lower(), -1)


def _severity_rank(severity: str) -> int:
    """Rank a severity by the canonical ordering (lower index = more severe).
    Unknown severities rank least-severe so they never mask a known one."""
    try:
        return SEVERITIES.index(str(severity).strip().lower())
    except ValueError:
        return len(SEVERITIES)


# ── JSON extraction (binding 6) ───────────────────────────────────────────────
def _brace_objects(text: str) -> list[dict]:
    """String-aware extraction of every balanced {...} that parses as JSON —
    tolerant of prose the model emits inside/around the ```json fence (agy and
    codex both prepend commentary), and of braces inside JSON strings."""
    out: list[dict] = []
    n, i = len(text), 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc, j = 0, False, False, i
        while j < n:
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        out.append(json.loads(text[i:j + 1]))
                    except Exception:
                        pass
                    break
            j += 1
        i = j + 1
    return out


def extract_json_objects(text: str) -> list[dict]:
    """Extract reviewer JSON blocks from `text`.

    Fence-first: pull balanced objects from inside each ```json … ``` fence,
    keeping those that look like reviewer output (have findings/attacks/verdict).
    If the fenced pass yields nothing, fall back to a bare scan of the whole text,
    keeping objects with findings or attacks. Mirrors validate_agents.sh's
    extract_objects exactly (binding 6)."""
    objs: list[dict] = []
    for m in re.finditer(r"```json(.*?)```", text, re.DOTALL):
        objs.extend(
            o for o in _brace_objects(m.group(1))
            if "findings" in o or "attacks" in o or "verdict" in o
        )
    if not objs:
        objs.extend(
            o for o in _brace_objects(text)
            if "findings" in o or "attacks" in o
        )
    return objs


# ── Fingerprinting (binding 5) ────────────────────────────────────────────────
def _files_of(obj: dict) -> list[str]:
    """Files for a finding (`files` list, or a singular `file`), sorted."""
    files = obj.get("files")
    if not files:
        single = obj.get("file")
        files = [single] if single else []
    return sorted(files)


def _class_of_finding(finding: dict) -> str:
    """Finding class: agy uses `category`, codex uses `type` — prefer whichever
    is present (binding 5)."""
    return finding.get("category") or finding.get("type") or ""


def fingerprint(finding: dict) -> str:
    """Stable dedup key for a finding: a string derived from
    (sorted files, finding-class). agy uses `category`, codex uses `type`; either
    is the class (binding 5, AC-2). Returned as a deterministic JSON string so the
    value is trivially comparable and serializable."""
    return json.dumps([_files_of(finding), _class_of_finding(finding)], sort_keys=True)


def _ledger_fingerprint(entry: dict) -> str:
    """Fingerprint of a ledger entry, built with the SAME rule as `fingerprint`
    so AC-2 holds: a recorded entry whose `class` equals a finding's category/type
    (and same files) produces an equal key."""
    return json.dumps([_files_of(entry), entry.get("class", "")], sort_keys=True)


# Dispositions that RESOLVE a finding and may therefore silence a re-surfaced
# copy of it. Only `fixed` and `filed:#<issue>` mark a finding as dealt with;
# `noise`/`residual` (and any unknown/empty value) merely record that a finding
# was SEEN, not that it was resolved, so they must NEVER silence a later blocking
# finding with the same fingerprint (#983). Fail-closed: unknown ⇒ not resolving.
_FILED_RE = re.compile(r"^filed:#\d+$")


def _is_resolving(disposition) -> bool:
    """True only for `fixed` or `filed:#<issue>` — the dispositions that mark a
    finding RESOLVED. Everything else (`noise`, `residual`, unknown, empty)
    returns False so it can never dedup-silence a blocking finding (#983)."""
    d = str(disposition or "").strip().lower()
    return d == "fixed" or bool(_FILED_RE.match(d))


def _is_degenerate(files: list[str], cls: str) -> bool:
    """A fingerprint with NO files AND no class is degenerate: it collapses every
    file-less, class-less finding onto the single key `[[], ""]`, so one such
    ledger entry would silence ALL of them (#983). A degenerate key can neither
    silence nor be silenced — fail-closed, mirroring the #670 no-stable-
    fingerprint rule for reviewer-error blocks."""
    return not files and not cls


def load_ledger(ledger_path: str) -> set[str]:
    """Read a JSONL ledger and return the set of SILENCING fingerprints. Tolerates
    a missing file (empty set) and malformed lines (skipped). (Spec R1.)

    Only entries with a RESOLVING disposition (`fixed`/`filed:#N`) and a non-
    degenerate fingerprint contribute a silencing key: a `noise`/`residual` or
    class-less/file-less entry records that a finding was seen but must not
    silence a later, materially different blocking finding (#983)."""
    seen: set[str] = set()
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not _is_resolving(entry.get("disposition", "")):
                    continue
                if _is_degenerate(_files_of(entry), entry.get("class", "")):
                    continue
                seen.add(_ledger_fingerprint(entry))
    except FileNotFoundError:
        pass
    return seen


# ── Verdict aggregation (bindings 2, 3, 7) ────────────────────────────────────
def compute_verdict(
    findings: list[dict],
    ledger_path: str,
    *,
    strict_empty: bool = False,
) -> dict:
    """Aggregate the verdict across parsed reviewer blocks.

    `findings` is the list of parsed reviewer JSON blocks (as returned by
    extract_json_objects); each block has a `findings` and/or `attacks` list,
    and may carry a block-level `verdict`. A block whose verdict is "error" (a
    reviewer that timed out / failed to review) counts as one NEW blocking
    finding so the aggregate fails closed rather than silently approving (#670).
    The ledger at `ledger_path` supplies the seen-fingerprint set.

    Returns {verdict, highest_severity, blocking_count, new_blocking_count,
    dedup_count}. Does NOT decide pass/fail exit codes and does NOT read the pass
    counter — the shell owns the cap (binding 3)."""
    seen = load_ledger(ledger_path)
    highest = "none"
    blocking_count = 0
    new_blocking_count = 0

    for block in findings:
        # A reviewer that failed to review (timeout → verdict "error") is a
        # blocking signal in its own right, regardless of its (empty) findings.
        # It always counts as NEW blocking: an operational failure has no stable
        # fingerprint to dedup against, so it must never be silenced (#670).
        if str(block.get("verdict", "")).lower() == ERROR_VERDICT:
            blocking_count += 1
            new_blocking_count += 1
            if SEVERITIES.index("blocking") < SEVERITIES.index(highest):
                highest = "blocking"

        for item in block.get("findings", []) + block.get("attacks", []):
            sev = str(item.get("severity", "low")).lower()
            try:
                if SEVERITIES.index(sev) < SEVERITIES.index(highest):
                    highest = sev
            except ValueError:
                pass
            if sev in BLOCKING_SEVERITIES:
                blocking_count += 1
                # A degenerate (file-less, class-less) finding has no stable
                # fingerprint to dedup against, so it always counts as NEW —
                # never silenced by a `[[], ""]` ledger key (#983, cf. #670).
                if _is_degenerate(_files_of(item), _class_of_finding(item)) \
                        or fingerprint(item) not in seen:
                    new_blocking_count += 1

    # Verdict keyed on NEW (un-ledgered) blocking findings: convergence is "zero
    # non-noise", not zero findings (external review is non-deterministic).
    if not findings:
        verdict = "error" if strict_empty else "approve"
    elif new_blocking_count > 0:
        verdict = "request_changes"
    else:
        verdict = "approve"

    return {
        "verdict": verdict,
        "highest_severity": highest,
        "blocking_count": blocking_count,
        "new_blocking_count": new_blocking_count,
        "dedup_count": blocking_count - new_blocking_count,
    }


# ── Ledger write (binding 4) ──────────────────────────────────────────────────
def record_ledger_entry(finding: dict, ledger_path: str) -> None:
    """Append exactly one JSONL disposition entry to the ledger. `finding` carries
    `files` (list), `class`, and `disposition`. The timestamp matches the bash
    `date -u +%Y-%m-%dT%H:%M:%SZ` both scripts produced. Append-only — never
    rewrites or truncates the ledger."""
    entry = {
        "files": list(finding.get("files", [])),
        "class": finding.get("class", ""),
        "disposition": finding.get("disposition", ""),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── CLI shim ──────────────────────────────────────────────────────────────────
def _cmd_process(args: argparse.Namespace) -> int:
    """Read the output file, compute the verdict, rewrite the four header lines in
    place. Exit 0 regardless of verdict (binding 3 — the shell decides pass/fail)."""
    try:
        with open(args.file, encoding="utf-8") as fh:
            content = fh.read()
    except Exception:
        # The shell's own guards handle a missing/unreadable output file.
        return 0

    blocks = extract_json_objects(content)
    result = compute_verdict(blocks, args.ledger, strict_empty=args.strict_empty)
    verdict = result["verdict"]
    highest = result["highest_severity"]
    blocking = result["blocking_count"]
    new_blocking = result["new_blocking_count"]

    # RATCHET against the verdict/severity already in the file. In the pre-PR
    # pipeline, `second_review_logic.py aggregate` has ALREADY rewritten the
    # header away from its `pending`/`none`/`0` defaults before we run, so
    # anchoring the rewrite on those literals (as this did) matched nothing and
    # silently dropped this step's ledger-aware verdict on the floor — a reviewer
    # returning {"verdict":"approve"} alongside a critical finding, or a #670
    # error block, stayed `approve` in the file the evaluator reads (#982). We
    # therefore match the CURRENT value and never DOWNGRADE a blocking verdict to
    # approve (#683), while still letting a stronger computed verdict land (#670).
    existing_verdict_m = re.search(r"^verdict: (\S+)$", content, flags=re.M)
    existing_verdict = existing_verdict_m.group(1) if existing_verdict_m else "pending"
    if _verdict_rank(existing_verdict) >= _verdict_rank(verdict):
        verdict = existing_verdict
    # A blocking final verdict must present a non-zero gate to any count-based
    # consumer even when this step's own (deduped) new-blocking tally is zero:
    # the reviewer's blocking intent, not the count, is authoritative (#683).
    if verdict in ("request_changes", ERROR_VERDICT) and new_blocking == 0:
        new_blocking = 1
        blocking = max(blocking, new_blocking)

    existing_sev_m = re.search(r"^highest_severity: (\S+)$", content, flags=re.M)
    existing_sev = existing_sev_m.group(1) if existing_sev_m else "none"
    if _severity_rank(existing_sev) <= _severity_rank(highest):
        highest = existing_sev

    new_content = re.sub(
        r"^verdict: \S+$", f"verdict: {verdict}", content, count=1, flags=re.M
    )
    new_content = re.sub(
        r"^highest_severity: \S+$", f"highest_severity: {highest}", new_content, count=1, flags=re.M
    )
    new_content = re.sub(
        r"^blocking_count: \d+$", f"blocking_count: {blocking}", new_content, count=1, flags=re.M
    )
    new_content = re.sub(
        r"^new_blocking_count: \d+$", f"new_blocking_count: {new_blocking}", new_content, count=1, flags=re.M
    )
    with open(args.file, "w", encoding="utf-8") as fh:
        fh.write(new_content)

    print(
        f"  verdict={verdict} highest_severity={highest} "
        f"blocking={blocking} new={new_blocking}"
    )
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    """Append one disposition entry to the ledger (unified --record, binding 4)."""
    files = [f for f in args.files.split(",") if f]
    record_ledger_entry(
        {"files": files, "class": args.cls, "disposition": args.disposition},
        args.ledger,
    )
    print(f"Recorded to ledger: [{args.files}] {args.cls} → {args.disposition}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validation dedup fingerprinting + verdict aggregation (SPEC-334)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_proc = sub.add_parser(
        "process",
        help="Compute the verdict from an output file and rewrite its header in place.",
    )
    p_proc.add_argument("--file", required=True, help="validation output file path")
    p_proc.add_argument("--ledger", required=True, help="dedup ledger (JSONL) path")
    p_proc.add_argument(
        "--strict-empty",
        action="store_true",
        help="empty parse → 'error' verdict (validate_agents.sh behavior); "
        "without it, empty parse → 'approve' (validate_scripts.sh compat).",
    )
    p_proc.set_defaults(func=_cmd_process)

    p_rec = sub.add_parser(
        "record",
        help="Append one disposition entry to the dedup ledger.",
    )
    p_rec.add_argument("--ledger", required=True, help="dedup ledger (JSONL) path")
    p_rec.add_argument("--files", required=True, help="comma-separated file list")
    p_rec.add_argument("--class", dest="cls", required=True, help="finding class (category|type)")
    p_rec.add_argument("--disposition", required=True, help="fixed|filed:#N|residual|noise")
    p_rec.set_defaults(func=_cmd_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
