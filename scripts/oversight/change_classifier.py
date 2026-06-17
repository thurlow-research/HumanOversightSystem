#!/usr/bin/env python3
"""change_classifier.py — deterministic, independent classification of a diff.

This is the *independent* check that closes two governance holes the
oversight-evaluator otherwise trusts upstream actors to get right:

  #75  Self-classification of change type is an unaudited gate to the
       human-approval boundary. Each authoring agent labels its OWN change
       clarifying / additive / structural, and only `structural` escalates to a
       human. Nothing audits the label. This module detects MECHANICAL
       STRUCTURAL SIGNATURES from the diff — new external dependency, new
       permission/auth state, new user-facing flow step/route, new user-facing
       state enum — that FORCE `structural` regardless of the author's label.

  #74  post-change-sweep can write `Status: N/A` register entries on behalf of
       skipped reviewers. An advisory tool mis-determining a domain as "not
       applicable" silently waives a required reviewer. This module independently
       reports which reviewer DOMAINS the diff actually touches, so the evaluator
       can reject an N/A for a domain that was, in fact, changed.

Design stance — fail toward the human (the ratchet):
  The heuristics are a FLOOR, deliberately biased to over-detect. A false
  positive forces a human to look (conservative, safe). A false negative is the
  only real failure mode, so signatures err on the side of catching more.
  Projects with a known stack can extend SIGNATURES / DOMAIN_RULES below; this
  generic base targets Python/Django + common JS/route conventions.

Output: JSON to stdout.
  {
    "base": "<sha>", "head": "<sha>",
    "domains_touched": {"security": {...}, "ui": {...}, ...},
    "structural_signals": [ {"signal": "...", "file": "...", "evidence": "..."} ]
  }

Exit: 0 always (this is a reporter; the evaluator decides). 2 on git error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# ── Reviewer-domain detection (for #74 N/A verification) ─────────────────────
# Maps a reviewer ROLE key (as used in step-manifest role_mappings and the
# sign-off register) to how we decide the diff "touched" that domain. Each rule
# is (changed-file-path regex, added-line regex) — either match marks touched.
# `None` means that channel is not used for the role.
#
# Deliberately broad: a domain marked touched simply means "an N/A for this role
# is not credible — require a real review." Mirrors post-change-sweep Step 2.
DOMAIN_RULES: dict[str, tuple[str | None, str | None]] = {
    # security: any application code or template change carries security context
    "security": (r"\.(py|html|js|ts|jsx|tsx)$", None),
    # privacy: paths or code touching identity / PII / data-subject rights
    "privacy": (
        r"(account|user|profile|pii|gdpr|privacy|consent|erasure|retention|personal|email|address|phone)",
        r"(PII|personal_data|anonymi|pseudonymi|erasure|retention|consent|EmailField|"
        r"first_name|last_name|date_of_birth|ssn|national_id)",
    ),
    # ui / a11y: template / component changes
    "ui": (r"(templates/.*\.html$|\.(jsx|tsx|vue|svelte)$)", None),
    "a11y": (r"(templates/.*\.html$|\.(jsx|tsx|vue|svelte)$)", None),
    # ops: background jobs, external calls, async, queues, schedules
    "ops": (
        None,
        r"(celery|@shared_task|@task\b|async\s+def|await\s|requests\.|httpx|aiohttp|"
        r"kafka|rabbit|boto3|queue|BackgroundTask|cron|schedule\(|apscheduler)",
    ),
    # reliability: outbound connections that can time out / fail
    "reliability": (
        None,
        r"(requests\.|httpx|aiohttp|urllib|socket\.|\.execute\(|cursor|"
        r"cache\.(get|set)|redis|\.objects\.(all|filter|get|create)|session\.(get|post|put|delete))",
    ),
    # infra: deployment / orchestration config
    "infra": (
        r"(docker-compose.*\.ya?ml$|Caddyfile$|Dockerfile$|\.env\.example$|"
        r"nginx.*\.conf$|k8s/.*\.ya?ml$|terraform/.*\.tf$|\.github/workflows/.*\.ya?ml$)",
        None,
    ),
}

# ── Structural-override signatures (for #75) ─────────────────────────────────
# Each entry: signal name → (added-line regex, optional added-file-status check).
# A match FORCES the change to be treated as `structural` (human gate), no matter
# how the authoring agent classified it. These encode the prose already in
# ux-designer.md / ops-designer.md ("new user decision point, new blocked/
# permission state, new completion criterion, new step in a user flow,
# previously uninstrumented component, new external dependency") as a
# deterministic, independently-checkable set.
ADDED_LINE_SIGNATURES: list[tuple[str, str]] = [
    (
        "new-permission-or-auth-state",
        r"(permission_required|login_required|IsAuthenticated|IsAdminUser|has_perm|"
        r"PermissionDenied|user_passes_test|staff_member_required|LoginRequiredMixin|"
        r"PermissionRequiredMixin|AccessMixin|@roles?_required|@authorize|require_role)",
    ),
    (
        "new-user-flow-or-route",
        r"(\bpath\(|\bre_path\(|\burl\(|@app\.route|@router\.(get|post|put|delete|patch)|"
        r"router\.(get|post|put|delete|patch)|\bRoute\(|createBrowserRouter|<Route\b)",
    ),
    (
        "new-user-facing-state",
        r"(choices\s*=|TextChoices|IntegerChoices|models\.TextChoices|StateField|FSMField|"
        r"@transition|STATUS_[A-Z]|_STATES\b|enum\.Enum|new\s+state\b)",
    ),
    (
        # A telemetry retrofit instruments a previously-uninstrumented component
        # without adding any other §2a signature, so ops-designer could under-
        # classify it as additive (#84). High-confidence telemetry primitives only
        # — deliberately NOT routine `logger.info(...)` or `collections.Counter(`,
        # which would force spurious human gates (the #117 false-match lesson).
        "new-observability-instrumentation",
        r"(get_tracer|start_as_current_span|add_span_processor|TracerProvider|"
        r"\.set_attribute\(|SpanKind|get_current_span|propagat|TraceContext|"
        r"opentelemetry|\bOTLP\b|prometheus|statsd|push_to_gateway|"
        r"structlog\.(get_logger|configure)|logging\.config|dictConfig|\bLOGGING\s*=)",
    ),
]

# Dependency manifests — an ADDED line here is a new external dependency.
DEPENDENCY_MANIFESTS = re.compile(
    r"(requirements[^/]*\.txt$|pyproject\.toml$|setup\.py$|setup\.cfg$|Pipfile$|"
    r"package\.json$|go\.mod$|Gemfile$|Cargo\.toml$|pom\.xml$|build\.gradle)"
)
# Within a manifest, lines that look like a real dependency addition (skip
# comments, blanks, section headers, and pure version bumps of existing deps are
# still flagged — a new pinned version is structural enough to merit a glance).
DEP_LINE = re.compile(r"^[A-Za-z0-9_.\-\"']")

# Templates added as NEW files are a new user-facing surface.
TEMPLATE_FILE = re.compile(r"(templates/.*\.html$|\.(jsx|tsx|vue|svelte)$)")

# The HOS framework tooling tree. The added-line signatures below describe
# APPLICATION behavior (auth state, routes, user-facing state); the oversight
# tooling's own source contains those very patterns as literal regex/string
# definitions, so scanning it makes the classifier match ITSELF — phantom
# structural signals whenever a framework file is in the diff (HOS#117).
# Exempt the tooling tree from application-domain signature scanning only;
# dependency-manifest and new-template signals still apply everywhere (a real
# dep added to oversight requirements.txt IS structural).
FRAMEWORK_TOOLING = re.compile(r"(^|/)scripts/(oversight|framework)/.*\.py$")


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        print(f"change_classifier: git {' '.join(args)} failed: {e.stderr}", file=sys.stderr)
        sys.exit(2)


def resolve_range(base: str | None, head: str | None) -> tuple[str, str]:
    head = head or _git(["rev-parse", "HEAD"]).strip()
    if not base:
        # Default base: merge-base with the default branch, else previous commit.
        mb = _git(["merge-base", "HEAD", "origin/main"]).strip() if _has_ref("origin/main") else ""
        base = mb or _git(["rev-parse", "HEAD~1"]).strip()
    return base, head


def _has_ref(ref: str) -> bool:
    try:
        subprocess.run(["git", "rev-parse", "--verify", ref], capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def collect_diff(
    base: str, head: str
) -> tuple[
    list[tuple[str, str]],  # name_status: (status_letter, path)
    dict[str, list[str]],  # added_by_file: path -> added content lines (no leading '+')
    dict[str, list[str]],  # removed_by_file: path -> removed content lines (no leading '-')
]:
    """Return (name_status, added_lines_by_file, removed_lines_by_file).

    name_status: list of (status_letter, path). status A=added, M=modified, etc.
    added_lines_by_file: path → list of added content lines (without leading '+').
    removed_lines_by_file: path → list of removed content lines (without leading '-').
    """
    name_status: list[tuple[str, str]] = []
    for line in _git(["diff", "--name-status", f"{base}..{head}"]).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            name_status.append((parts[0][0], parts[-1]))

    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    current_added: str | None = None
    current_removed: str | None = None
    # --unified=0 keeps only changed lines; parse per-file added and removed content.
    for line in _git(["diff", "--unified=0", f"{base}..{head}"]).splitlines():
        if line.startswith("+++ b/"):
            current_added = line[6:]
            added.setdefault(current_added, [])
        elif line.startswith("+++ "):
            current_added = None
        elif line.startswith("--- a/"):
            current_removed = line[6:]
            removed.setdefault(current_removed, [])
        elif line.startswith("--- "):
            current_removed = None
        elif current_added and line.startswith("+") and not line.startswith("+++"):
            added[current_added].append(line[1:])
        elif current_removed and line.startswith("-") and not line.startswith("---"):
            removed[current_removed].append(line[1:])
    return name_status, added, removed


def detect_domains(name_status, added, roles=None) -> dict[str, dict]:
    files = [p for _, p in name_status]
    result: dict[str, dict] = {}
    rules = (
        DOMAIN_RULES if roles is None else {r: DOMAIN_RULES[r] for r in roles if r in DOMAIN_RULES}
    )
    for role, (file_rx, line_rx) in rules.items():
        evidence = None
        if file_rx:
            for f in files:
                if re.search(file_rx, f, re.IGNORECASE):
                    evidence = {"by": "path", "file": f}
                    break
        if not evidence and line_rx:
            for f, lines in added.items():
                for ln in lines:
                    if re.search(line_rx, ln):
                        evidence = {"by": "added-line", "file": f, "line": ln.strip()[:120]}
                        break
                if evidence:
                    break
        if evidence:
            result[role] = {"touched": True, "evidence": evidence}
    return result


def detect_structural(name_status, added) -> list[dict]:
    signals: list[dict] = []

    # New external dependency — added line in a dependency manifest.
    for _status, path in name_status:
        if DEPENDENCY_MANIFESTS.search(path):
            for ln in added.get(path, []):
                if DEP_LINE.match(ln.strip()):
                    signals.append(
                        {
                            "signal": "new-external-dependency",
                            "file": path,
                            "evidence": ln.strip()[:120],
                        }
                    )
                    break

    # New user-facing surface — a template/component added as a NEW file.
    for status, path in name_status:
        if status == "A" and TEMPLATE_FILE.search(path):
            signals.append(
                {
                    "signal": "new-user-facing-surface",
                    "file": path,
                    "evidence": "new template/component file",
                }
            )

    # Added-line signatures — permission/auth, route/flow, state enums.
    # Skip the framework tooling tree: these application-domain patterns appear
    # there only as the classifier's own literal definitions, not as real app
    # behavior, so scanning it self-matches (HOS#117).
    for name, rx in ADDED_LINE_SIGNATURES:
        crx = re.compile(rx)
        for f, lines in added.items():
            if FRAMEWORK_TOOLING.search(f):
                continue
            for ln in lines:
                if crx.search(ln):
                    signals.append({"signal": name, "file": f, "evidence": ln.strip()[:120]})
                    break  # one per file per signal is enough to force structural

    return signals


# ── Tier-floor rule table ─────────────────────────────────────────────────────
# Evaluated in descending tier order; highest matching tier wins.
# Each entry: (rule_name, tier, channel, patterns)
#   channel: "path" → match against changed file paths (case-insensitive fnmatch)
#            "added-line" → match against added content lines (case-insensitive regex)
# Path patterns use ** convention; added-line patterns are compiled as regex.

_TIER_PATH_RULES: list[tuple[str, str, list[str]]] = [
    (
        "payment-path",
        "CRITICAL",
        [
            "**/payment*", "**/billing*", "**/financial*", "**/checkout*",
            "**/subscription*", "**/invoice*", "**/stripe*", "**/braintree*",
            "**/paypal*",
        ],
    ),
    (
        "auth-path",
        "HIGH",
        [
            "**/auth*", "**/login*", "**/logout*", "**/session*", "**/token*",
            "**/credential*", "**/password*", "**/mfa*", "**/totp*", "**/oauth*",
            "**/sso*", "**/jwt*", "**/permission*",
        ],
    ),
    (
        "migration",
        "HIGH",
        ["**/migrations/*.py"],
    ),
    (
        "prod-settings",
        "HIGH",
        ["**/settings/production*"],
    ),
    (
        "privacy-path",
        "HIGH",
        ["**/pii*", "**/gdpr*", "**/privacy*", "**/consent*"],
    ),
    (
        "app-logic",
        "MEDIUM",
        [],  # handled specially: .py/.js/.ts/.jsx/.tsx + gates/ .sh
    ),
]

_TIER_LINE_RULES: list[tuple[str, str, str]] = [
    (
        "financial-api",
        "CRITICAL",
        r"stripe\.|braintree\.|PaymentIntent|\bcharge\(|\bCard\(|\bACH\b|\bIBAN\b|account_number",
    ),
    (
        "pii-field",
        "HIGH",
        r"EmailField|first_name|last_name|date_of_birth|\bssn\b|national_id|phone_number|\baddress\b|personal_data",
    ),
]

_TIER_RANK: dict[str, int] = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _path_matches_any(path: str, patterns: list[str]) -> str | None:
    """Return the first matching pattern, or None. Case-insensitive, ** supported."""
    import fnmatch
    path_lower = path.lower()
    for pat in patterns:
        # Convert ** glob to fnmatch-compatible: fnmatch doesn't support ** natively.
        # Strategy: strip a leading **/ and check suffix, or use re for full support.
        if fnmatch.fnmatch(path_lower, pat.lower()):
            return pat
        # Also match path segments: if pattern is **/foo* match any component.
        if pat.startswith("**/"):
            suffix_pat = pat[3:]  # e.g. "payment*"
            # Check every path segment against the suffix pattern.
            parts = path_lower.replace("\\", "/").split("/")
            for i in range(len(parts)):
                candidate = "/".join(parts[i:])
                if fnmatch.fnmatch(candidate, suffix_pat.lower()):
                    return pat
    return None


def detect_tier_floor(
    name_status: list[tuple[str, str]],
    added: dict[str, list[str]],
) -> dict:
    """Return the deterministic tier floor and the evidence that set it.

    Returns:
      {
        "tier_floor": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
        "evidence": [ {"rule": "<rule-name>", "file": "<path>",
                       "pattern": "<matched-pattern-or-line>"}, ... ],
      }

    The lowest output is "LOW" — "SAFE" is never returned.
    Evaluate ALL rules; the HIGHEST resulting floor wins.
    """
    import re

    floor = "LOW"
    evidence: list[dict] = []
    # Track which rules have already fired (one entry per rule name).
    fired_rules: set[str] = set()

    files = [p for _, p in name_status]

    # Path rules (except app-logic which is handled below).
    for rule_name, tier, patterns in _TIER_PATH_RULES:
        if rule_name == "app-logic":
            continue
        for path in files:
            if FRAMEWORK_TOOLING.search(path):
                continue
            matched = _path_matches_any(path, patterns)
            if matched and rule_name not in fired_rules:
                fired_rules.add(rule_name)
                evidence.append({"rule": rule_name, "file": path, "pattern": matched})
                if _TIER_RANK[tier] > _TIER_RANK[floor]:
                    floor = tier
                break  # one evidence entry per rule

    # Added-line rules (skip FRAMEWORK_TOOLING files).
    for rule_name, tier, rx in _TIER_LINE_RULES:
        if rule_name in fired_rules:
            continue
        crx = re.compile(rx, re.IGNORECASE)
        for path, lines in added.items():
            if FRAMEWORK_TOOLING.search(path):
                continue
            for ln in lines:
                if crx.search(ln):
                    fired_rules.add(rule_name)
                    evidence.append({"rule": rule_name, "file": path, "pattern": ln.strip()[:120]})
                    if _TIER_RANK[tier] > _TIER_RANK[floor]:
                        floor = tier
                    break
            if rule_name in fired_rules:
                break

    # app-logic: any .py/.js/.ts/.jsx/.tsx (not already higher-tier) or .sh in gates/.
    if "app-logic" not in fired_rules and _TIER_RANK["MEDIUM"] > _TIER_RANK[floor]:
        import re as _re
        _app_rx = _re.compile(r"\.(py|js|ts|jsx|tsx)$", re.IGNORECASE)
        _gates_sh_rx = _re.compile(r"scripts/oversight/gates/.*\.sh$", re.IGNORECASE)
        for path in files:
            if FRAMEWORK_TOOLING.search(path):
                continue
            if _app_rx.search(path) or _gates_sh_rx.search(path):
                fired_rules.add("app-logic")
                evidence.append({"rule": "app-logic", "file": path, "pattern": path})
                floor = "MEDIUM"
                break

    return {"tier_floor": floor, "evidence": evidence}


def detect_warranted_lanes(
    name_status: list[tuple[str, str]],
    added: dict[str, list[str]],
) -> dict:
    """Return reviewer lanes the diff deterministically warrants.

    Thin wrapper over detect_domains() — warranted lanes are exactly the domains
    detect_domains() reports as touched. No separate pattern set (single source of truth).

    Returns:
      {
        "warranted": { "<lane>": {"by": "path"|"added-line",
                                   "file": "<path>", "evidence": "<...>"}, ... }
      }
    """
    domains = detect_domains(name_status, added)
    warranted: dict[str, dict] = {}
    for role, data in domains.items():
        if data.get("touched"):
            ev = data.get("evidence", {})
            warranted[role] = {
                "by": ev.get("by", "unknown"),
                "file": ev.get("file", ""),
                "evidence": ev.get("line", ev.get("file", "")),
            }
    return {"warranted": warranted}


# Tracked governance documents — a file in scope for structural-modification detection.
_TRACKED_DOC_GLOBS: list[str] = [
    "docs/specs/SPEC-*.md",
    "docs/v*/SPEC-*.md",
    "docs/v*/TECHNICAL-DESIGN-*.md",
    "TECHNICAL-DESIGN-*.md",
    "docs/v*/DESIGN*.md",
    "DESIGN.md",
    "contract/OVERSIGHT-CONTRACT.md",
    ".claude/agents/*.md",
    "TELEMETRY-SPEC.md",
    "docs/ops/TELEMETRY-SPEC.md",
]


def _is_tracked_doc(path: str, globs: list[str] | None = None) -> bool:
    """Return True if path matches any tracked-document glob."""
    import fnmatch
    check_globs = globs if globs is not None else _TRACKED_DOC_GLOBS
    for pat in check_globs:
        if fnmatch.fnmatch(path, pat):
            return True
        # Also match without leading directory noise for patterns without **.
        if fnmatch.fnmatch(path.split("/")[-1], pat.split("/")[-1]):
            # Confirm directory prefix matches too if pattern has directory parts.
            dir_part = "/".join(pat.split("/")[:-1])
            if not dir_part or fnmatch.fnmatch("/".join(path.split("/")[:-1]), dir_part):
                return True
    return False


def detect_structural_modifications(
    name_status: list[tuple[str, str]],
    added: dict[str, list[str]],
    removed: dict[str, list[str]],
) -> dict:
    """Detect non-additive edits to existing sections of tracked governance docs.

    Per-file both-sides test: a file is reported iff it appears in both removed
    (non-empty) and added (non-empty) AND matches the tracked-document path set.
    Pure additions (removed empty) are never reported.

    Returns:
      {
        "doc_modifications": [
          {"file": "<path>", "section": "<nearest-header-or-'(unknown)'>",
           "evidence": {"removed": "<one removed line>", "added": "<one added line>"}},
          ...
        ]
      }
    """
    import re as _re

    doc_modifications: list[dict] = []
    files = {p for _, p in name_status}

    for path in files:
        if not _is_tracked_doc(path):
            continue
        file_removed = removed.get(path, [])
        file_added = added.get(path, [])
        if not file_removed or not file_added:
            # Pure addition (no removals) or pure deletion — not a modification.
            continue
        # Both sides non-empty → structural modification detected.
        # Best-effort section from diff hunk context — informational only.
        section = "(unknown)"
        doc_modifications.append(
            {
                "file": path,
                "section": section,
                "evidence": {
                    "removed": file_removed[0].strip()[:120],
                    "added": file_added[0].strip()[:120],
                },
            }
        )

    return {"doc_modifications": doc_modifications}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Independent diff classification for the oversight evaluator."
    )
    ap.add_argument("--base", help="base SHA (default: merge-base with origin/main, else HEAD~1)")
    ap.add_argument("--head", help="head SHA (default: HEAD)")
    ap.add_argument("--explain", action="store_true", help="human-readable output instead of JSON")
    # Scoped invocation (the ratchet applied to verification cost): the evaluator
    # only pays to re-derive in the LOOSENING direction. Run --domains-only with
    # --roles for the specific reviewers an N/A would waive (#74); run
    # --structural-only only for steps that did NOT already go through a human
    # gate (#75). No need to verify when upstream asked for MORE review.
    ap.add_argument("--domains-only", action="store_true", help="only report domains_touched (#74)")
    ap.add_argument(
        "--structural-only", action="store_true", help="only report structural_signals (#75)"
    )
    ap.add_argument(
        "--roles",
        help="comma-separated reviewer roles to check (default: all). "
        "Pass only the N/A'd roles to avoid scanning domains nobody waived.",
    )
    ap.add_argument(
        "--tier-floor",
        action="store_true",
        help="only report the deterministic tier floor (REQ-TIER-3)",
    )
    ap.add_argument(
        "--warranted-lanes",
        action="store_true",
        help="only report warranted reviewer lanes (REQ-REV-1)",
    )
    ap.add_argument(
        "--modifications-only",
        action="store_true",
        help="only report structural modifications to tracked governance docs (REQ-MOD-5)",
    )
    args = ap.parse_args()

    base, head = resolve_range(args.base, args.head)
    name_status, added, removed = collect_diff(base, head)

    # Scoped flags — each suppresses the combined default output, mirroring
    # --domains-only / --structural-only.
    scoped = args.tier_floor or args.warranted_lanes or args.modifications_only

    if args.tier_floor:
        result = detect_tier_floor(name_status, added)
        out = {"base": base, "head": head, **result}
        if args.explain:
            print(f"Diff {base[:8]}..{head[:8]}")
            print(f"Tier floor: {result['tier_floor']}")
            for ev in result["evidence"]:
                print(f"  [{ev['rule']}] {ev['file']}  «{ev['pattern']}»")
        else:
            print(json.dumps(out, indent=2))
        return 0

    if args.warranted_lanes:
        result = detect_warranted_lanes(name_status, added)
        out = {"base": base, "head": head, **result}
        if args.explain:
            print(f"Diff {base[:8]}..{head[:8]}")
            print(f"Warranted lanes ({len(result['warranted'])}):")
            for lane, ev in result["warranted"].items():
                print(f"  {lane:14s} ← {ev['by']}: {ev['file']}  «{ev['evidence']}»")
        else:
            print(json.dumps(out, indent=2))
        return 0

    if args.modifications_only:
        result = detect_structural_modifications(name_status, added, removed)
        out = {"base": base, "head": head, **result}
        if args.explain:
            print(f"Diff {base[:8]}..{head[:8]}")
            mods = result["doc_modifications"]
            print(f"Structural doc modifications ({len(mods)}):")
            for m in mods:
                print(f"  {m['file']} (section: {m['section']})")
                print(f"    removed: «{m['evidence']['removed']}»")
                print(f"    added:   «{m['evidence']['added']}»")
            if not mods:
                print("  (none)")
        else:
            print(json.dumps(out, indent=2))
        return 0

    want_domains = not args.structural_only
    want_structural = not args.domains_only
    roles = [r.strip() for r in args.roles.split(",")] if args.roles else None

    domains = detect_domains(name_status, added, roles) if want_domains else {}
    structural = detect_structural(name_status, added) if want_structural else []

    out = {
        "base": base,
        "head": head,
        "domains_touched": domains,
        "structural_signals": structural,
    }

    if args.explain:
        print(f"Diff {base[:8]}..{head[:8]}")
        print(f"\nDomains touched ({len(domains)}):")
        for role, d in domains.items():
            print(f"  {role:14s} ← {d['evidence']}")
        print(f"\nStructural signals ({len(structural)}) — these FORCE `structural`:")
        for s in structural or []:
            print(f"  {s['signal']:28s} {s['file']}  «{s['evidence']}»")
        if not structural:
            print("  (none)")
    else:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
