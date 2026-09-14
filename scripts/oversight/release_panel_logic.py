#!/usr/bin/env python3
"""release_panel_logic.py — range derivation, exclusions, and the AD-4 verdict
contract for the release panel (ADR-1340; TECHNICAL-DESIGN-1340-release-panel.md).

Pure logic + one injectable git seam (`run_git`). No vendor-CLI call (`agy`,
`codex`, `claude`) and no `gh` may appear anywhere in this module (AD-9 row 1,
TD-VF-6) — all GitHub I/O stays in the shell, through `bootstrap/` wrappers.
`git` is the one permitted subprocess dependency and is confined to `run_git`
so every AD-2 refusal and every AD-7 recomputation is unit-testable without a
real repository.

This module owns the verdict contract and nowhere else does (AD-9 row 1):
- AD-2  range derivation, with the three release-only refusals a PR/validator
        range derivation does not need (`derive_range`)
- AD-3  the committed exclusion list, hashed into the verdict
- AD-4  the verdict shape (`compose_verdict`) and the issue-comment body
        (`render_comment_body`)
- AD-7  extraction/selection of a posted verdict from the issue's comment
        stream, and recomputation-based verification (`verify_verdict`) — the
        load-bearing property is that VERIFICATION RECOMPUTES, IT NEVER TRUSTS
        THE CLAIM: four of the ten checks are fresh recomputations against the
        repository state at verification time, not comparisons against fields
        copied out of the artifact itself.

Deliberately inert in PR 1 (ADR-1340 AD-9): nothing in this repository calls
this module yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# `scripts.framework.require_human_approval` is the shipped glob matcher
# (AD-3 / TD §1.5 — "no second glob engine", D41). Import by putting the repo
# root on sys.path, the record_agent_model.py idiom.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.framework.require_human_approval import glob_to_regex, load_globs  # noqa: E402

# --------------------------------------------------------------------------- #
# 1.1 Constants                                                               #
# --------------------------------------------------------------------------- #

EXCLUSIONS_PATH_DEFAULT = "scripts/oversight/release_panel_exclusions.txt"
VERDICT_ARTIFACT = "hos-release-panel-verdict"
VERDICT_SCHEMA_VERSION = 1
VERDICT_MARKER = "<!-- hos-release-panel-verdict v1 -->"
DERIVATION = "since-tag"

_COMPLETED_AT_FMT = "%Y-%m-%dT%H:%M:%SZ"

# AD-7 §4 — each check's stable failure slug, in table order (also the order
# `verify_verdict` evaluates them, and the order `verdict_reason` is drawn
# from — "the first failing clause" per TD §1.6).
_CHECK_FAILURE_SLUGS = {
    "schema_version": "schema-version-mismatch",
    "head_sha": "head-sha-mismatch",
    "base_sha": "base-sha-mismatch",
    "exclusions_sha256": "exclusions-hash-mismatch",
    "files_digest": "files-digest-mismatch",
    "coverage_arithmetic": "coverage-mismatch",
    "chunks": "chunk-shortfall",
    "result": "result-not-pass",
    "arbiter_salvaged": "arbiter-salvaged",
    "tier1_undispositioned": "tier1-undispositioned",
}


# --------------------------------------------------------------------------- #
# 1.2 The git seam — the ONLY subprocess call in this module                  #
# --------------------------------------------------------------------------- #


def run_git(args: list[str], *, cwd: str = ".") -> tuple[int, str, str]:
    """Run `git <args>` in `cwd`. Never raises on a non-zero exit.

    Every git call in this module goes through this one function; tests
    monkeypatch it. No other function here may call subprocess directly.
    """
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def is_shallow(cwd: str = ".") -> bool:
    code, out, _ = run_git(["rev-parse", "--is-shallow-repository"], cwd=cwd)
    return code == 0 and out == "true"


def latest_tag(cwd: str = ".") -> str | None:
    code, out, _ = run_git(["describe", "--tags", "--abbrev=0"], cwd=cwd)
    if code != 0 or not out:
        return None
    return out


def rev_parse(rev: str, cwd: str = ".") -> str | None:
    code, out, _ = run_git(["rev-parse", "--verify", "--quiet", rev], cwd=cwd)
    if code != 0 or not out:
        return None
    return out


def changed_files(base: str, head: str, cwd: str = ".") -> list[str]:
    """`git diff --name-only <base> <head>` — TWO-dot, never three-dot (AD-7).

    Byte-identical semantics to `run_review_chain.sh:135` and to AD-7's
    `base..head`. Three-dot would silently change what "the release range"
    means between the runner and the verifier.
    """
    code, out, _ = run_git(["diff", "--name-only", base, head], cwd=cwd)
    if code != 0 or not out:
        return []
    return out.splitlines()


# --------------------------------------------------------------------------- #
# 1.3 RangeResult                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RangeResult:
    state: str  # "OK" | "SHALLOW" | "NO_TAG" | "NO_CONTENT"
    base_ref: str | None
    base_sha: str | None
    head_sha: str | None
    derivation: str
    files_in_range: int
    files_excluded: int
    reviewed: tuple[str, ...]
    excluded: tuple[str, ...]
    reason: str
    remediation: str


def _refused(
    state: str,
    reason: str,
    *,
    base_ref: str | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
    files_in_range: int = 0,
    files_excluded: int = 0,
    reviewed: tuple[str, ...] = (),
    excluded: tuple[str, ...] = (),
    remediation: str = "",
) -> RangeResult:
    return RangeResult(
        state=state,
        base_ref=base_ref,
        base_sha=base_sha,
        head_sha=head_sha,
        derivation=DERIVATION,
        files_in_range=files_in_range,
        files_excluded=files_excluded,
        reviewed=reviewed,
        excluded=excluded,
        reason=reason,
        remediation=remediation,
    )


# --------------------------------------------------------------------------- #
# 1.4 derive_range — the single implementation, called by BOTH runner and     #
# verifier (AD-2). Order is normative and must not be reordered: a SHALLOW    #
# clone also fails `git describe`, so precedence determines which reason the  #
# operator sees.                                                              #
# --------------------------------------------------------------------------- #


def derive_range(*, cwd: str = ".", exclusions_path: str = EXCLUSIONS_PATH_DEFAULT) -> RangeResult:
    if is_shallow(cwd=cwd):
        return _refused(
            "SHALLOW",
            "range-derivation-failed: shallow clone",
            remediation="git fetch --unshallow --tags",
        )

    tag = latest_tag(cwd=cwd)
    if not tag:
        return _refused("NO_TAG", "range-derivation-failed: no tag reachable from HEAD")

    base_sha = rev_parse(f"{tag}^{{commit}}", cwd=cwd)
    head_sha = rev_parse("HEAD", cwd=cwd)
    if not base_sha or not head_sha:
        # A fifth internal condition that maps onto NO_TAG (TD §1.3) — never a
        # fifth public state.
        return _refused(
            "NO_TAG",
            "range-derivation-failed: base sha unresolvable",
            base_ref=tag,
            base_sha=base_sha,
            head_sha=head_sha,
        )

    files = changed_files(base_sha, head_sha, cwd=cwd)
    globs = load_exclusions(exclusions_path)
    reviewed, excluded = apply_exclusions(files, globs)

    if not reviewed:
        return _refused(
            "NO_CONTENT",
            "NO-CONTENT: zero files after exclusions",
            base_ref=tag,
            base_sha=base_sha,
            head_sha=head_sha,
            files_in_range=len(files),
            files_excluded=len(excluded),
            reviewed=tuple(reviewed),
            excluded=tuple(excluded),
        )

    return RangeResult(
        state="OK",
        base_ref=tag,
        base_sha=base_sha,
        head_sha=head_sha,
        derivation=DERIVATION,
        files_in_range=len(files),
        files_excluded=len(excluded),
        reviewed=tuple(reviewed),
        excluded=tuple(excluded),
        reason="",
        remediation="",
    )


# --------------------------------------------------------------------------- #
# 1.5 Exclusions                                                              #
# --------------------------------------------------------------------------- #


def load_exclusions(path: str) -> list[str]:
    """Parse the committed exclusion-glob file.

    A missing/unreadable file is FATAL, not an empty list: silently reviewing
    excluded files would change `files_digest` and break verification, and
    silently reviewing nothing would be worse.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"release panel exclusions file not found: {path}")
    return load_globs(p)


def apply_exclusions(files: list[str], globs: list[str]) -> tuple[list[str], list[str]]:
    """Split `files` into (reviewed, excluded), both sorted.

    Delegates matching to `require_human_approval.glob_to_regex` — no second
    glob engine (D41). Paths are compared exactly as git emits them
    (repo-relative, forward slashes, no leading `./`).
    """
    patterns = [glob_to_regex(g) for g in globs]
    reviewed: list[str] = []
    excluded: list[str] = []
    for f in files:
        f = f.strip()
        if not f:
            continue
        if any(rx.match(f) for rx in patterns):
            excluded.append(f)
        else:
            reviewed.append(f)
    return sorted(reviewed), sorted(excluded)


def exclusions_sha256(path: str) -> str:
    """sha256 over the exclusions file's raw bytes (not the parsed globs).

    A comment-only edit changes the hash — the intended "widening the list
    invalidates the run" property of AD-3.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files_digest(reviewed: list[str]) -> str:
    """sha256 of the sorted reviewed-path list. Runner and verifier must agree
    byte-for-byte, so the formula is normative down to the trailing newline.
    """
    payload = "".join(p + "\n" for p in sorted(reviewed))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 1.6 Verdict composition (AD-4)                                              #
# --------------------------------------------------------------------------- #


def compose_verdict(
    *,
    range_result: RangeResult,
    panel: dict,
    exclusions_path: str,
    run_id: str,
    issue: int,
    panel_exit_code: int,
) -> dict:
    """Compose the AD-4 verdict object. Field names are verbatim from AD-4 and
    may not be renamed or removed; additive fields are permitted.

    `result` is computed here, never passed in. NO_CONTENT is composed for the
    record and is never PASS.
    """
    reviewed = list(range_result.reviewed)
    coverage = {
        "files_in_range": range_result.files_in_range,
        "files_excluded": range_result.files_excluded,
        "files_reviewed": len(reviewed),
        "files_digest": files_digest(reviewed),
        "chunks_attempted": int(panel.get("chunks_attempted", 0) or 0),
        "chunks_completed": int(panel.get("chunks_completed", 0) or 0),
        "exclusion_globs": load_exclusions(exclusions_path),
    }

    raw_findings = panel.get("findings") or {}
    findings = {
        "total": int(raw_findings.get("total", 0) or 0),
        "tier1": int(raw_findings.get("tier1", 0) or 0),
        "tier2": int(raw_findings.get("tier2", 0) or 0),
        "tier1_undispositioned": int(raw_findings.get("tier1_undispositioned", 0) or 0),
    }

    arbiter_salvaged = bool(panel.get("arbiter_salvaged", False))

    verdict_reason = ""
    if range_result.state == "NO_CONTENT":
        result = "NO-CONTENT"
    elif panel_exit_code != 0:
        result, verdict_reason = "FAIL", "panel-exit-nonzero"
    elif len(reviewed) != range_result.files_in_range - range_result.files_excluded:
        result, verdict_reason = "FAIL", "coverage-mismatch"
    elif coverage["chunks_attempted"] != coverage["chunks_completed"]:
        result, verdict_reason = "FAIL", "chunk-shortfall"
    elif findings["tier1_undispositioned"] != 0:
        result, verdict_reason = "FAIL", "tier1-undispositioned"
    elif arbiter_salvaged is not False:
        result, verdict_reason = "FAIL", "arbiter-salvaged"
    else:
        result = "PASS"

    return {
        "artifact": VERDICT_ARTIFACT,
        "schema_version": VERDICT_SCHEMA_VERSION,
        "result": result,
        "issue": issue,
        "panel_exit_code": panel_exit_code,
        "verdict_reason": verdict_reason,
        "range": {
            "base_ref": range_result.base_ref,
            "base_sha": range_result.base_sha,
            "head_sha": range_result.head_sha,
            "derivation": range_result.derivation,
        },
        "exclusions": {
            "path": exclusions_path,
            "sha256": exclusions_sha256(exclusions_path),
        },
        "coverage": coverage,
        "risk": {
            "effective_tier": panel.get("effective_tier", ""),
            "deterministic_floor": panel.get("deterministic_floor", ""),
            "validator_tier": panel.get("validator_tier", ""),
            "sqc": panel.get("sqc", {}),
        },
        "roster": panel.get("roster", []),
        "findings": findings,
        "arbiter_salvaged": arbiter_salvaged,
        "run": {
            "run_id": run_id,
            "run_dir": panel.get("run_dir", ""),
            "arbiter_sha256": panel.get("arbiter_sha256", ""),
            "findings_raw_sha256": panel.get("findings_raw_sha256", ""),
        },
        "completed_at": datetime.now(timezone.utc).strftime(_COMPLETED_AT_FMT),
    }


def render_comment_body(*, verdict: dict, panel_summary_md: str) -> str:
    """Compose the REQ-A2 issue comment: prose + coverage paragraph + the
    panel's own summary + the marked, fenced verdict JSON block.

    The marker sits on its own line immediately before the fence — the
    extraction parser (§1.7) relies on that adjacency.
    """
    range_ = verdict.get("range", {})
    coverage = verdict.get("coverage", {})
    head_sha = range_.get("head_sha") or "?"
    base_ref = range_.get("base_ref") or "?"
    base_sha = range_.get("base_sha") or ""
    base_sha12 = base_sha[:12] if base_sha else "?"
    head_sha12 = head_sha[:12] if head_sha and head_sha != "?" else "?"
    exclusion_globs = coverage.get("exclusion_globs") or []

    lines = [
        "## 🔭 Release panel — verdict",
        f"**Result:** {verdict.get('result', '?')}",
        "",
        f"**Release candidate SHA:** {head_sha}",
        f"**Reviewed range:** {base_ref} ({base_sha12})..{head_sha12}",
        "",
        (
            f"**Coverage:** {coverage.get('files_reviewed', 0)} file(s) reviewed of "
            f"{coverage.get('files_in_range', 0)} in range "
            f"({coverage.get('files_excluded', 0)} excluded) · chunks "
            f"{coverage.get('chunks_completed', 0)}/{coverage.get('chunks_attempted', 0)} completed. "
            "Exclusion globs applied: "
            + (", ".join(f"`{g}`" for g in exclusion_globs) if exclusion_globs else "(none)")
            + "."
        ),
        "",
        panel_summary_md,
        "",
        VERDICT_MARKER,
        "```json",
        json.dumps(verdict, indent=2, sort_keys=True),
        "```",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 1.7 Verdict extraction, selection, verification (AD-7)                      #
# --------------------------------------------------------------------------- #

_FENCE_JSON_RE = re.compile(r"```json\s*(.*?)```", re.S | re.IGNORECASE)


def extract_verdicts(ndjson_text: str) -> list[dict]:
    """Extract every release-panel verdict block from `--comments-json` output.

    Input is one `{"user","created_at","body"}` JSON object per line — never
    the `--comments` text stream, which is author-spoofable (TD-VF-5). A
    malformed line, or a malformed fenced block, is skipped, not fatal.

    A comment containing MORE THAN ONE `VERDICT_MARKER` is refused outright —
    the whole comment yields zero candidates. A legitimate verdict-posting
    comment never contains more than one marker; two or more is itself a
    tamper/injection signal (e.g. attacker-controlled text — reviewer
    findings that echo attacker-planted diff/code-comment content, this
    suite's own stated prompt-injection threat model — landing in the same
    bot-authored comment as the genuine verdict, via `render_comment_body`'s
    `panel_summary_md` concatenation). Refusing the whole comment, rather
    than best-effort-picking the "right" marker among several, is what
    closes that forgery vector: `select_verdict` never even sees a forged
    second block to choose between.
    """
    results: list[dict] = []
    for line in ndjson_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        user = obj.get("user")
        created_at = obj.get("created_at")
        body = obj.get("body") or ""

        if body.count(VERDICT_MARKER) > 1:
            continue

        pos = 0
        while True:
            marker_idx = body.find(VERDICT_MARKER, pos)
            if marker_idx == -1:
                break
            after = body[marker_idx + len(VERDICT_MARKER) :]
            m = _FENCE_JSON_RE.search(after)
            pos = marker_idx + len(VERDICT_MARKER)
            if not m:
                break
            try:
                verdict = json.loads(m.group(1))
            except Exception:
                continue
            results.append({"user": user, "created_at": created_at, "verdict": verdict})
    return results


def select_verdict(
    candidates: list[dict], *, head_sha: str, author: str
) -> tuple[dict | None, str]:
    """AD-7 §3 selection: author + head_sha match, newest comment wins.

    "Newest" is the comment's own GitHub-authenticated `created_at` (the
    field `extract_verdicts` threads through from `--comments-json`) —
    NEVER `completed_at` from inside the `verdict` payload itself, which is
    self-reported JSON an attacker fully controls. Tie-breaking on the
    untrusted field would let a forged block with a future `completed_at`
    win selection over the genuine one; `created_at` cannot be backdated by
    the comment's author.

    NOT the newest *passing* candidate — a stale PASS must not shadow a fresh
    FAIL at the same SHA. Ties: the later position in the (chronologically
    ordered) input list wins.
    """
    if not author:
        raise ValueError("select_verdict: author must be non-empty")

    filtered = [
        c
        for c in candidates
        if c.get("user") == author
        and isinstance(c.get("verdict"), dict)
        and (c["verdict"].get("range") or {}).get("head_sha") == head_sha
    ]
    if not filtered:
        return None, "verdict-missing"

    def _created_at(entry: dict) -> datetime:
        raw = entry.get("created_at", "")
        try:
            return datetime.strptime(raw, _COMPLETED_AT_FMT)
        except (TypeError, ValueError):
            return datetime.min

    best_index, best_entry = max(
        enumerate(filtered), key=lambda pair: (_created_at(pair[1]), pair[0])
    )
    return best_entry, ""


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    expected: str
    actual: str


@dataclass(frozen=True)
class VerifyResult:
    result: str  # "PASS" | "FAIL"
    reason: str  # "" on PASS; else the first failing check's slug
    checks: tuple[CheckResult, ...]


def verify_verdict(
    verdict: dict,
    *,
    range_result: RangeResult,
    exclusions_path: str,
    cwd: str = ".",
) -> VerifyResult:
    """AD-7: run all ten checks, even after the first failure, so the operator
    sees the full picture in one pass. `reason` reports the first failure in
    table order. Four checks are fresh RECOMPUTATIONS (never comparisons
    against a copied claim): head_sha, base_sha, exclusions_sha256,
    files_digest.

    A missing or wrong-typed field fails its OWN check, never raises and never
    defaults — `2 == "2"` is a failure, not a coercion.

    If `range_result` itself is a refusal (SHALLOW/NO_TAG/NO_CONTENT), the ten
    checks are never reached: the gate FAILs immediately with the refusal's
    own reason (AD-7 step 1 — a shallow clone must fail the gate, never
    silently pass a one-commit review).
    """
    if range_result.state != "OK":
        return VerifyResult(result="FAIL", reason=range_result.reason, checks=())

    checks: list[CheckResult] = []

    def add(name: str, ok: bool, expected: object, actual: object) -> None:
        checks.append(CheckResult(name=name, ok=ok, expected=str(expected), actual=str(actual)))

    _range = verdict.get("range")
    range_claim: dict = _range if isinstance(_range, dict) else {}
    _exclusions = verdict.get("exclusions")
    exclusions_claim: dict = _exclusions if isinstance(_exclusions, dict) else {}
    _coverage = verdict.get("coverage")
    coverage_claim: dict = _coverage if isinstance(_coverage, dict) else {}
    _findings = verdict.get("findings")
    findings_claim: dict = _findings if isinstance(_findings, dict) else {}

    # 1. schema_version — literal.
    schema_version = verdict.get("schema_version")
    add(
        "schema_version",
        schema_version == VERDICT_SCHEMA_VERSION,
        VERDICT_SCHEMA_VERSION,
        schema_version,
    )

    # 2. head_sha — RECOMPUTE.
    recomputed_head = rev_parse("HEAD", cwd=cwd)
    claimed_head = range_claim.get("head_sha")
    add(
        "head_sha",
        recomputed_head is not None and recomputed_head == claimed_head,
        recomputed_head,
        claimed_head,
    )

    # 3. base_sha — RE-DERIVE (range_result was produced by §1.4 at verify time).
    claimed_base = range_claim.get("base_sha")
    add(
        "base_sha",
        range_result.base_sha is not None and range_result.base_sha == claimed_base,
        range_result.base_sha,
        claimed_base,
    )

    # 4. exclusions_sha256 — RE-HASH the committed file.
    recomputed_hash = exclusions_sha256(exclusions_path)
    claimed_hash = exclusions_claim.get("sha256")
    add("exclusions_sha256", recomputed_hash == claimed_hash, recomputed_hash, claimed_hash)

    # 5. files_digest — RECOMPUTE over the freshly re-derived reviewed set.
    recomputed_digest = files_digest(list(range_result.reviewed))
    claimed_digest = coverage_claim.get("files_digest")
    add("files_digest", recomputed_digest == claimed_digest, recomputed_digest, claimed_digest)

    # 6. coverage arithmetic.
    files_reviewed = coverage_claim.get("files_reviewed")
    files_in_range = coverage_claim.get("files_in_range")
    files_excluded = coverage_claim.get("files_excluded")
    ok6 = (
        isinstance(files_reviewed, int)
        and isinstance(files_in_range, int)
        and isinstance(files_excluded, int)
        and files_reviewed == files_in_range - files_excluded
    )
    add(
        "coverage_arithmetic",
        ok6,
        "files_reviewed == files_in_range - files_excluded",
        f"{files_reviewed} vs {files_in_range}-{files_excluded}",
    )

    # 7. chunks — a skipped chunk is a FAIL.
    chunks_attempted = coverage_claim.get("chunks_attempted")
    chunks_completed = coverage_claim.get("chunks_completed")
    ok7 = (
        isinstance(chunks_attempted, int)
        and isinstance(chunks_completed, int)
        and chunks_attempted == chunks_completed
    )
    add(
        "chunks",
        ok7,
        "chunks_attempted == chunks_completed",
        f"{chunks_attempted} vs {chunks_completed}",
    )

    # 8. result.
    result_claim = verdict.get("result")
    add("result", result_claim == "PASS", "PASS", result_claim)

    # 9. arbiter_salvaged — strict `is False`; the string "false" fails.
    arbiter_salvaged_claim = verdict.get("arbiter_salvaged")
    add("arbiter_salvaged", arbiter_salvaged_claim is False, False, arbiter_salvaged_claim)

    # 10. tier1_undispositioned — strict int, no coercion.
    tier1_undispositioned = findings_claim.get("tier1_undispositioned")
    ok10 = (
        isinstance(tier1_undispositioned, int)
        and not isinstance(tier1_undispositioned, bool)
        and tier1_undispositioned == 0
    )
    add("tier1_undispositioned", ok10, 0, tier1_undispositioned)

    first_failure = next((c for c in checks if not c.ok), None)
    if first_failure is None:
        return VerifyResult(result="PASS", reason="", checks=tuple(checks))
    return VerifyResult(
        result="FAIL", reason=_CHECK_FAILURE_SLUGS[first_failure.name], checks=tuple(checks)
    )


# --------------------------------------------------------------------------- #
# (de)serialization helpers for the CLI shim                                  #
# --------------------------------------------------------------------------- #


def _range_result_to_dict(rr: RangeResult) -> dict:
    d = asdict(rr)
    d["reviewed"] = list(rr.reviewed)
    d["excluded"] = list(rr.excluded)
    return d


def _range_result_from_dict(d: dict) -> RangeResult:
    return RangeResult(
        state=d["state"],
        base_ref=d.get("base_ref"),
        base_sha=d.get("base_sha"),
        head_sha=d.get("head_sha"),
        derivation=d.get("derivation", DERIVATION),
        files_in_range=int(d.get("files_in_range", 0) or 0),
        files_excluded=int(d.get("files_excluded", 0) or 0),
        reviewed=tuple(d.get("reviewed", []) or []),
        excluded=tuple(d.get("excluded", []) or []),
        reason=d.get("reason", ""),
        remediation=d.get("remediation", ""),
    )


def _verify_result_to_dict(vr: VerifyResult) -> dict:
    return {"result": vr.result, "reason": vr.reason, "checks": [asdict(c) for c in vr.checks]}


# --------------------------------------------------------------------------- #
# 1.8 CLI surface — argparse. Called only by the two shell scripts. No        #
# subcommand writes to GitHub, spawns a vendor CLI, or reads .ai-local/       #
# except as told by an explicit path argument.                                #
# --------------------------------------------------------------------------- #


def _cmd_derive_range(args: argparse.Namespace) -> int:
    rr = derive_range(cwd=args.cwd, exclusions_path=args.exclusions)
    sys.stdout.write(json.dumps(_range_result_to_dict(rr)))
    return 0 if rr.state == "OK" else 4


def _cmd_new_run_id(_args: argparse.Namespace) -> int:
    sys.stdout.write(str(uuid.uuid4()))
    return 0


def _cmd_files_digest(_args: argparse.Namespace) -> int:
    paths = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    sys.stdout.write(files_digest(paths))
    return 0


def _cmd_exclusions_sha256(args: argparse.Namespace) -> int:
    sys.stdout.write(exclusions_sha256(args.exclusions))
    return 0


def _cmd_compose(args: argparse.Namespace) -> int:
    range_result = _range_result_from_dict(json.loads(Path(args.range_json).read_text()))
    panel = json.loads(Path(args.panel_json).read_text())

    panel_summary_md = ""
    summary_path = panel.get("summary_body_path")
    if summary_path and Path(summary_path).is_file():
        panel_summary_md = Path(summary_path).read_text()

    verdict = compose_verdict(
        range_result=range_result,
        panel=panel,
        exclusions_path=args.exclusions,
        run_id=args.run_id,
        issue=args.issue,
        panel_exit_code=args.panel_exit,
    )
    body = render_comment_body(verdict=verdict, panel_summary_md=panel_summary_md)

    Path(args.out_verdict).write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    Path(args.out_body).write_text(body + "\n")

    head12 = (verdict["range"].get("head_sha") or "")[:12]
    sys.stdout.write(
        f"release-panel: compose {verdict['result']} "
        f"reason={verdict['verdict_reason'] or 'none'} head={head12 or 'none'}\n"
    )
    return 0 if verdict["result"] == "PASS" else 6


def _cmd_verify(args: argparse.Namespace) -> int:
    range_result = derive_range(cwd=args.cwd, exclusions_path=args.exclusions)
    if range_result.state != "OK":
        result = VerifyResult(result="FAIL", reason=range_result.reason, checks=())
        sys.stdout.write(json.dumps(_verify_result_to_dict(result)))
        return 8

    ndjson_text = Path(args.comments_json).read_text()
    candidates = extract_verdicts(ndjson_text)
    block, select_reason = select_verdict(
        candidates, head_sha=range_result.head_sha or "", author=args.author
    )
    if block is None:
        result = VerifyResult(result="FAIL", reason=select_reason, checks=())
        sys.stdout.write(json.dumps(_verify_result_to_dict(result)))
        return 7

    result = verify_verdict(
        block["verdict"],
        range_result=range_result,
        exclusions_path=args.exclusions,
        cwd=args.cwd,
    )
    sys.stdout.write(json.dumps(_verify_result_to_dict(result)))
    return 0 if result.result == "PASS" else 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Release panel logic — range derivation, exclusions, verdict compose/verify (ADR-1340)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dr = sub.add_parser("derive-range", help="derive the release range (AD-2)")
    p_dr.add_argument("--exclusions", default=EXCLUSIONS_PATH_DEFAULT)
    p_dr.add_argument("--cwd", default=".")

    sub.add_parser("new-run-id", help="print a fresh UUID4 run id")

    sub.add_parser("files-digest", help="sha256 digest of a file list (stdin, one path per line)")

    p_esha = sub.add_parser("exclusions-sha256", help="sha256 of the exclusions file")
    p_esha.add_argument("--exclusions", required=True)

    p_compose = sub.add_parser("compose", help="compose the AD-4 verdict + comment body")
    p_compose.add_argument("--range-json", required=True)
    p_compose.add_argument("--panel-json", required=True)
    p_compose.add_argument("--exclusions", required=True)
    p_compose.add_argument("--run-id", required=True)
    p_compose.add_argument("--issue", type=int, required=True)
    p_compose.add_argument("--panel-exit", type=int, required=True)
    p_compose.add_argument("--out-verdict", required=True)
    p_compose.add_argument("--out-body", required=True)

    p_verify = sub.add_parser("verify", help="verify a posted verdict by recomputation (AD-7)")
    p_verify.add_argument("--comments-json", required=True)
    p_verify.add_argument("--exclusions", default=EXCLUSIONS_PATH_DEFAULT)
    p_verify.add_argument("--author", required=True)
    p_verify.add_argument("--cwd", default=".")

    args = parser.parse_args(argv)

    handlers = {
        "derive-range": _cmd_derive_range,
        "new-run-id": _cmd_new_run_id,
        "files-digest": _cmd_files_digest,
        "exclusions-sha256": _cmd_exclusions_sha256,
        "compose": _cmd_compose,
        "verify": _cmd_verify,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
