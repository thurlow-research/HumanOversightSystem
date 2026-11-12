#!/usr/bin/env python3
"""
merge_authority_cli.py — L2 primitives over merge_authority.py: read-only queries (#1357)
plus the overseer's route and bounce (#2209).

Fetches what each L1 function needs, calls it, and serializes the result as a
single JSON record. This module decides nothing itself — every boolean in
every payload traces to an `scripts.automation.lib.merge_authority` call; the
CLI's own job is fetch → call → assemble evidence → emit one envelope.

Contract: docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md §3.
Invoked exclusively through `bootstrap/merge_authority.sh` (L3), which mints
the app token, invokes this module, and passes stdout/exit-code through
verbatim (ARCH-3a — this module is the record schema's sole author).

Importing this module performs no I/O, no config read, no `gh` call, and no
token mint — the only module-level work is the sys.path bootstrap below,
which makes the CLI cwd-immune (it must not rely on being invoked from the
repo root, mirroring commit_onto_base.sh:114-118).
"""

from __future__ import annotations

import argparse
import dataclasses
import errno
import importlib.util
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Optional

# Import bootstrap (§2): insert this CLI's own repo root at sys.path[0] before
# importing scripts.automation.lib.* so imports resolve regardless of cwd.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_DEFAULT_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from scripts.automation.lib import (  # noqa: E402
    approval_merge,
    github,
    merge_authority,
    merge_config,
)

SCHEMA_VERSION = 1

SUBCOMMANDS = (
    "gate",
    "register",
    "bounce-count",
    "human-approval",
    "hold-directive",
    "protected-surface",
    "security-surface",
    "codeowners",
    "route",
    "bounce",
    "approval-merge",
    "merge-provenance",
)

# The two subcommands that write (a comment, an audit event, a label, the
# draft state) — overseer-only, #2209 TD-D8. Every other subcommand is read-only.
MUTATION_SUBCOMMANDS = frozenset({"route", "bounce"})

# Subcommands that fetch from GitHub — mirrored by bootstrap/merge_authority.sh
# (§7.3), which mints a token only for these.
NETWORK_SUBCOMMANDS = frozenset(
    {
        "gate",
        "human-approval",
        "hold-directive",
        "protected-surface",
        "security-surface",
        "codeowners",
        "route",
        "bounce",
        "approval-merge",
        "merge-provenance",
    }
)

_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_STEP_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
_PR_RE = re.compile(r"^[0-9]+$")


# ---------------------------------------------------------------------------
# argv-level type validators — usage errors (exit 2), never a decision.
# ---------------------------------------------------------------------------


def _repo_type(value: str) -> str:
    if not _REPO_SLUG_RE.match(value):
        raise argparse.ArgumentTypeError(f"--repo must match owner/repo, got: {value!r}")
    return value


def _step_type(value: str) -> str:
    if not _STEP_RE.match(value):
        raise argparse.ArgumentTypeError(f"--step must match ^[A-Za-z0-9._-]+$, got: {value!r}")
    return value


def _cid_type(value: str) -> str:
    if not _CID_RE.match(value):
        raise argparse.ArgumentTypeError(f"--cid must match ^[A-Za-z0-9._:-]+$, got: {value!r}")
    return value


def _pr_type(value: str) -> int:
    if not _PR_RE.match(value):
        raise argparse.ArgumentTypeError(f"--pr must be a positive integer, got: {value!r}")
    return int(value)


# ---------------------------------------------------------------------------
# The envelope (§3.2) and the single-producer argparse error path (§3.3).
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(
    *,
    subcommand: str | None = None,
    repo: str | None = None,
    repo_root: str | None = None,
    pr: int | None = None,
    config_source: str | None = None,
    app_role: str | None = None,
    error: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "subcommand": subcommand,
        "computed_at": _now_iso(),
        "repo": repo,
        "repo_root": repo_root,
        "pr": pr,
        "config_source": config_source,
        "app_role": app_role,
        "not_verified": [],
        "error": error,
    }


class _UsageExit(Exception):
    """Raised by _EnvelopeArgumentParser.error() instead of calling sys.exit,
    so main() stays the sole owner of process-exit decisions (§3.1)."""

    def __init__(self, code: int):
        super().__init__(f"usage error, exit {code}")
        self.code = code


class _EnvelopeArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser whose error() emits the §3.2 envelope on stdout
    (AD-2 rule 2: stdout is exactly one JSON object, always — including on a
    usage error) and the human-readable usage text on stderr, then raises
    _UsageExit(2) rather than calling sys.exit directly.

    `add_subparsers()` propagates this class to every subparser it creates
    (`kwargs.setdefault('parser_class', type(self))`), so an error at the
    subcommand level uses the same envelope-producing error().
    """

    def error(self, message: str) -> NoReturn:
        record = _envelope(error=f"usage: {message}")
        if self.prog.split()[-1] in MUTATION_SUBCOMMANDS:
            record["error_class"] = None
        print(json.dumps(record))
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise _UsageExit(2)


def _build_parser() -> _EnvelopeArgumentParser:
    """Build the argv contract (§3.4). No --repo-root, no --manifest, no
    --config, no --force/--skip-*/--no-verify/--head-sha anywhere on this
    surface (§3.4.0 Rule A) — help is disabled everywhere so an unrecognised
    -h/--help is a plain usage error (exit 2 via error()) rather than
    argparse's own sys.exit(0) help path, keeping main() the sole exit-code
    author.
    """
    parser = _EnvelopeArgumentParser(
        prog="merge_authority_cli.py", add_help=False, allow_abbrev=False
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    common = _EnvelopeArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--app", required=True, choices=("worker", "overseer", "human"))
    common.add_argument("--repo", type=_repo_type, default=None)

    gate_p = subparsers.add_parser("gate", parents=[common], add_help=False, allow_abbrev=False)
    gate_p.add_argument("--branch", default=None)

    register_p = subparsers.add_parser(
        "register", parents=[common], add_help=False, allow_abbrev=False
    )
    register_p.add_argument("--step", type=_step_type, required=True)

    bounce_p = subparsers.add_parser(
        "bounce-count", parents=[common], add_help=False, allow_abbrev=False
    )
    bounce_p.add_argument("--cid", type=_cid_type, required=True)

    for name in (
        "human-approval",
        "hold-directive",
        "protected-surface",
        "security-surface",
        "codeowners",
        "approval-merge",
        "merge-provenance",
    ):
        pr_p = subparsers.add_parser(name, parents=[common], add_help=False, allow_abbrev=False)
        pr_p.add_argument("--pr", type=_pr_type, required=True)

    # route / bounce write, so --app accepts only the overseer (TD-D8) and
    # --step is a subject selector, the same as `register --step` (TD-D7).
    mutation = _EnvelopeArgumentParser(add_help=False, allow_abbrev=False)
    mutation.add_argument("--app", required=True, choices=("overseer",))
    mutation.add_argument("--repo", type=_repo_type, default=None)
    mutation.add_argument("--pr", type=_pr_type, required=True)
    mutation.add_argument("--step", type=_step_type, required=True)
    route_p = subparsers.add_parser("route", parents=[mutation], add_help=False, allow_abbrev=False)
    route_p.add_argument("--findings-file", required=True)
    subparsers.add_parser("bounce", parents=[mutation], add_help=False, allow_abbrev=False)

    return parser


# ---------------------------------------------------------------------------
# Handler plumbing
# ---------------------------------------------------------------------------


@dataclass
class _Context:
    repo_root: Path
    config: merge_config.MergeConfig
    app_role: str


@dataclass
class _Outcome:
    """A handler's result: the subcommand's own payload keys (never an
    envelope key — §3.2's 'payload keys never collide with envelope keys'),
    the exit code, and whatever envelope fields only the handler can know
    (repo, pr, error, not_verified)."""

    payload: dict
    exit_code: int
    error: str | None = None
    not_verified: list[str] = field(default_factory=list)
    repo: str | None = None
    pr: int | None = None


def _resolve_repo_or_fail(
    args: argparse.Namespace, ctx: _Context
) -> tuple[str, str, str] | _Outcome:
    """Resolve owner/repo, or return a ready-to-emit exit-1 _Outcome."""
    try:
        repo = merge_config.resolve_repo_slug(ctx.repo_root, explicit=args.repo)
    except merge_config.ConfigError as exc:
        return _Outcome(payload={}, exit_code=1, error=str(exc))
    owner, repo_name = repo.split("/", 1)
    return repo, owner, repo_name


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------


def _cmd_gate(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    not_verified: list[str] = []
    branch = args.branch
    branch_source = "flag"
    if branch is None:
        repo_obj = None
        try:
            repo_obj = github.get_repo(owner, repo_name)
        except github.GitHubError:
            repo_obj = None
        default_branch = (repo_obj or {}).get("default_branch")
        if default_branch:
            branch = default_branch
            branch_source = "repo.default_branch"
        else:
            branch = "main"
            branch_source = "fallback-main"
            not_verified.append(
                f"branch: could not resolve repo.default_branch for {repo} — "
                "falling back to 'main'"
            )

    protection = None
    try:
        protection = github.get_branch_protection(owner, repo_name, branch)
    except github.GitHubError as exc:
        not_verified.append(f"checked_contexts: branch protection read failed: {exc}")

    checked_contexts = None
    if protection is not None:
        rsc = protection.get("required_status_checks") or {}
        contexts = set(rsc.get("contexts") or [])
        for check in rsc.get("checks") or []:
            if isinstance(check, dict) and check.get("context"):
                contexts.add(check["context"])
        checked_contexts = sorted(contexts)
    elif not not_verified:
        not_verified.append("checked_contexts: branch protection absent or unreadable")

    gate_result = merge_authority.detect_server_side_gate(
        owner,
        repo_name,
        branch,
        ctx.config.overseer_handle,
    )

    tier_ceiling_check_required = None
    if checked_contexts is not None:
        tier_ceiling_check_required = ctx.config.tier_ceiling_check_name in checked_contexts

    payload = {
        "autonomous_capable": gate_result.autonomous_capable,
        "reason": gate_result.reason,
        "branch": branch,
        "branch_source": branch_source,
        "checked_contexts": checked_contexts,
        "tier_ceiling_check_name": ctx.config.tier_ceiling_check_name,
        "tier_ceiling_check_required": tier_ceiling_check_required,
        "overseer_handle": ctx.config.overseer_handle,
    }
    return _Outcome(payload=payload, exit_code=0, not_verified=not_verified, repo=repo)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def _cmd_register(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    manifest_path = ctx.repo_root / "contract" / "step-manifest.yaml"
    result = merge_authority.check_register_completeness(
        args.step,
        repo_root=str(ctx.repo_root),
        manifest_path=str(manifest_path),
    )
    # Same identical manifest path as the decision call above (T6.4) — the
    # evidence-only path the library itself consults (_find_human_approval's
    # pattern, §3.4).
    required_signoffs = merge_authority._required_signoffs_for_step(manifest_path, args.step)
    required_roles_resolved = len(required_signoffs)
    gate_evaluable = required_roles_resolved > 0

    not_verified: list[str] = []
    if not gate_evaluable:
        not_verified.append(
            f"register gate not evaluable: no required_signoffs resolved for step "
            f"{args.step} from {manifest_path} (missing, malformed, or no entry for "
            "this step)"
        )

    payload = {
        "step": args.step,
        "bounce_required": result.bounce_required,
        "failures": list(result.failures),
        "reason_category": result.reason_category,
        "summary": result.summary,
        "register_path": merge_authority._bounce_register_path(args.step),
        "manifest_path": str(manifest_path),
        "required_signoffs": required_signoffs,
        "required_roles_resolved": required_roles_resolved,
        "gate_evaluable": gate_evaluable,
    }
    return _Outcome(payload=payload, exit_code=0, not_verified=not_verified)


# ---------------------------------------------------------------------------
# bounce-count
# ---------------------------------------------------------------------------


def _cmd_bounce_count(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    count = merge_authority.bounce_count(args.cid, repo_root=str(ctx.repo_root))
    cap = merge_authority.BOUNCE_CAP
    payload = {
        "cid": args.cid,
        "count": count,
        "cap": cap,
        "at_cap": count >= cap,
        "cap_source": "merge_authority.BOUNCE_CAP",
        "query": {"event": "pr-bounced", "cid": args.cid},
    }
    return _Outcome(payload=payload, exit_code=0)


# ---------------------------------------------------------------------------
# human-approval
# ---------------------------------------------------------------------------


def _stale_approvals(reviews: list[dict], human_reviewer: str, head_sha: str) -> list[dict]:
    """Evidence only — never a decision. APPROVED reviews from human_reviewer
    whose commit_id is not the current head SHA."""
    out = []
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        if (
            review.get("state") == "APPROVED"
            and login.lower() == human_reviewer.lower()
            and review.get("commit_id") != head_sha
        ):
            out.append(
                {
                    "commit_id": review.get("commit_id"),
                    "submitted_at": review.get("submitted_at"),
                    "html_url": review.get("html_url"),
                }
            )
    return out


def _cmd_human_approval(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    try:
        pr_obj = github.get_pull(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch PR #{args.pr}: {exc}",
            repo=repo,
            pr=args.pr,
        )
    if pr_obj is None:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"PR #{args.pr} not found",
            repo=repo,
            pr=args.pr,
        )
    head_sha = (pr_obj.get("head") or {}).get("sha")
    if not head_sha:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"PR #{args.pr} has no usable head.sha",
            repo=repo,
            pr=args.pr,
        )

    try:
        reviews = github.list_pull_reviews(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch reviews: {exc}",
            repo=repo,
            pr=args.pr,
        )

    human_reviewer = ctx.config.human_reviewer
    has_approval = merge_authority.has_human_approval(reviews, human_reviewer, head_sha)
    evidence = merge_authority._find_human_approval(reviews, human_reviewer, head_sha)

    if bool(has_approval) != (evidence is not None):
        return _Outcome(
            payload={},
            exit_code=1,
            error="approval decision and evidence disagree",
            repo=repo,
            pr=args.pr,
        )

    approver = approved_sha = approved_at = None
    if evidence is not None:
        approver = (evidence.get("user") or {}).get("login")
        approved_sha = evidence.get("commit_id")
        approved_at = evidence.get("submitted_at")

    payload = {
        "head_sha": head_sha,
        "human_reviewer": human_reviewer,
        "has_approval": has_approval,
        "approver": approver,
        "approved_sha": approved_sha,
        "approved_at": approved_at,
        "stale_approvals": _stale_approvals(reviews, human_reviewer, head_sha),
        "reviews_scanned": len(reviews),
    }
    return _Outcome(payload=payload, exit_code=0, repo=repo, pr=args.pr)


# ---------------------------------------------------------------------------
# hold-directive
# ---------------------------------------------------------------------------


def _cmd_hold_directive(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    try:
        pr_obj = github.get_pull(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch PR #{args.pr}: {exc}",
            repo=repo,
            pr=args.pr,
        )
    if pr_obj is None:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"PR #{args.pr} not found",
            repo=repo,
            pr=args.pr,
        )
    head_sha = (pr_obj.get("head") or {}).get("sha")
    if not head_sha:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"PR #{args.pr} has no usable head.sha",
            repo=repo,
            pr=args.pr,
        )

    not_verified: list[str] = []
    head_committed_at = None
    commit_obj = None
    try:
        commit_obj = github.get_commit(owner, repo_name, head_sha)
    except github.GitHubError:
        commit_obj = None
    if commit_obj is not None:
        head_committed_at = ((commit_obj.get("commit") or {}).get("committer") or {}).get("date")
    if not head_committed_at:
        head_committed_at = None
        not_verified.append(
            f"head_committed_at: could not read committer date for {head_sha} — "
            "every matching directive counts (library fail-safe)"
        )

    try:
        comments = github.list_issue_comments(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch comments: {exc}",
            repo=repo,
            pr=args.pr,
        )

    human_reviewer = ctx.config.human_reviewer
    directive = merge_authority.detect_human_hold_directive(
        comments, human_reviewer, head_committed_at
    )

    hold_active = directive is not None
    comment_url = created_at = matched_phrase = None
    if directive is not None:
        comment_url = directive.get("html_url")
        created_at = directive.get("created_at")
        match = merge_authority._HOLD_DIRECTIVE_RE.search(directive.get("body") or "")
        if match:
            matched_phrase = match.group(0)
        else:
            not_verified.append(
                "matched_phrase: library matched a hold directive but "
                "_HOLD_DIRECTIVE_RE found no match against the same comment body"
            )

    payload = {
        "head_sha": head_sha,
        "head_committed_at": head_committed_at,
        "hold_active": hold_active,
        "comment_url": comment_url,
        "created_at": created_at,
        "matched_phrase": matched_phrase,
        "human_reviewer": human_reviewer,
        "comments_scanned": len(comments),
    }
    return _Outcome(payload=payload, exit_code=0, not_verified=not_verified, repo=repo, pr=args.pr)


# ---------------------------------------------------------------------------
# protected-surface / security-surface (identical shape, §3.4)
# ---------------------------------------------------------------------------


def _cmd_surface(
    args: argparse.Namespace, ctx: _Context, *, l1_fn, surfaces_relpath: str, label: str
) -> _Outcome:
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    try:
        files = github.list_pull_files(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch changed files: {exc}",
            repo=repo,
            pr=args.pr,
        )

    changed_files = [f["filename"] for f in files if f.get("filename")]

    touches = l1_fn(changed_files, str(ctx.repo_root))
    matched_paths = [f for f in changed_files if l1_fn([f], str(ctx.repo_root))]

    not_verified: list[str] = []
    if touches and not matched_paths:
        not_verified.append(
            f"matched_paths: {label} reported touches=true for the full changed-file "
            "list but no single file matched individually"
        )

    surfaces_path = ctx.repo_root / surfaces_relpath
    surfaces_file_present = surfaces_path.is_file()
    if not surfaces_file_present:
        not_verified.append(
            f"{label} gate not evaluable: {surfaces_path} absent; touches=false is "
            "the library's permissive default, not a clean result"
        )
    if not changed_files:
        not_verified.append(
            f"changed_file_count: 0 changed files reported for PR #{args.pr} — the "
            "read did not see the PR's content; this is not a verified clean result"
        )

    payload = {
        "touches": touches,
        "matched_paths": matched_paths,
        "changed_file_count": len(changed_files),
        "surfaces_file": surfaces_relpath,
        "surfaces_file_present": surfaces_file_present,
    }
    return _Outcome(payload=payload, exit_code=0, not_verified=not_verified, repo=repo, pr=args.pr)


def _cmd_protected_surface(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    return _cmd_surface(
        args,
        ctx,
        l1_fn=merge_authority.touches_protected_surface,
        surfaces_relpath="scripts/framework/protected_surfaces.txt",
        label="protected-surface",
    )


def _cmd_security_surface(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    return _cmd_surface(
        args,
        ctx,
        l1_fn=merge_authority.touches_security_surface,
        surfaces_relpath="scripts/framework/security_surfaces.txt",
        label="security-surface",
    )


# ---------------------------------------------------------------------------
# codeowners
# ---------------------------------------------------------------------------


def _load_codeowners_module():
    """Load scripts/oversight/codeowners.py by file path (TD-VF-4 — it is not
    an importable package). A module-level function, but loaded lazily, only
    from inside the codeowners handler, so importing this CLI stays
    side-effect-free (§3.1)."""
    path = Path(__file__).resolve().parents[1] / "oversight" / "codeowners.py"
    spec = importlib.util.spec_from_file_location("hos_oversight_codeowners", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cmd_codeowners(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    try:
        files = github.list_pull_files(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch changed files: {exc}",
            repo=repo,
            pr=args.pr,
        )

    changed_files = [f["filename"] for f in files if f.get("filename")]

    codeowners_module = _load_codeowners_module()
    # bot_accounts is always the resolved AD-9 set, explicitly, as a mutable
    # `set` — check_pr_files's own type is `set[str] | None`; MergeConfig.
    # bot_accounts stays frozenset (§6.1), converted here at the boundary
    # (ARCH-3b). Passing None is prohibited: it would let check_pr_files fall
    # back to its own env-var default (AF-4's silent-default class).
    required, matched_paths, reason = codeowners_module.check_pr_files(
        changed_files,
        ctx.repo_root,
        set(ctx.config.bot_accounts),
    )

    not_verified: list[str] = []
    codeowners_relpath = ".github/CODEOWNERS"
    codeowners_path = ctx.repo_root / codeowners_relpath
    codeowners_present = codeowners_path.is_file()
    if not codeowners_present:
        not_verified.append(
            f"codeowners gate not evaluable: {codeowners_path} absent; "
            "required=false is 'no CODEOWNERS file', not a cleared gate"
        )
    if not changed_files:
        not_verified.append(
            f"changed_file_count: 0 changed files reported for PR #{args.pr} — the "
            "read did not see the PR's content; this is not a verified clean result"
        )

    payload = {
        "required": required,
        "matched_paths": matched_paths,
        "reason": reason,
        "changed_file_count": len(changed_files),
        "codeowners_path": codeowners_relpath,
        "codeowners_present": codeowners_present,
        "bot_accounts": sorted(ctx.config.bot_accounts),
    }
    return _Outcome(payload=payload, exit_code=0, not_verified=not_verified, repo=repo, pr=args.pr)


# ---------------------------------------------------------------------------
# route / bounce (#2209 S1a) — overseer-only mutation subcommands
# ---------------------------------------------------------------------------

# S1a never collects the validator artifact, so collectors are never complete and
# route cannot return PROCEED (TD-D4). S1b replaces this constant with the real
# collector result.
_COLLECTORS_COMPLETE_S1A = False
_NOT_VERIFIED_COLLECTORS = "collectors_complete=false: validator-artifact collector lands in S1b"
_NOT_VERIFIED_S1B = "s1b inputs stubbed: path blocks, disputes, veto window not evaluated"
_S1B_STUBBED_INPUTS = [
    "blocks",
    "pending_rulings",
    "upheld_unescalated",
    "withdrawn_on_head",
    "veto",
]

_PAYLOAD_KEYS = {
    "route": (
        "step",
        "cid",
        "cid_source",
        "head_sha",
        "base_sha",
        "worker_authored",
        "disposition",
        "rule",
        "trigger",
        "reasons",
        "findings",
        "open_finding_keys",
        "overruled_keys",
        "actions",
        "bounce",
        "epoch_start",
        "epoch_bounce_count",
        "bounce_cap",
        "reviewer",
        "reviewer_act",
        "escalation",
        "hold_directive",
        "effective_head_time",
        "collectors",
        "s1b_inputs_stubbed",
        "error_code",
        "error_class",
    ),
    "bounce": (
        "step",
        "cid",
        "cid_source",
        "head_sha",
        "bounced",
        "reason",
        "at_cap",
        "findings",
        "bounce",
        "epoch_start",
        "epoch_bounce_count",
        "bounce_cap",
        "collectors",
        "error_code",
        "error_class",
    ),
}


class _Fail(Exception):
    """An exit-1 condition: a closed error_code, its class, and any extra payload."""

    def __init__(self, code: str, message: str, klass: str, extra: dict | None = None):
        super().__init__(message, code, klass, extra)
        self.code = code
        self.klass = klass
        self.extra = extra or {}


def _gh_call(fn, *args, **kwargs):
    """Call a github.py read; any GitHubError becomes a classified _Fail."""
    try:
        return fn(*args, **kwargs)
    except github.GitHubError as exc:
        raise _Fail(
            "github_read_failed",
            f"{fn.__name__} failed: {exc}",
            merge_authority.classify_github_error(exc),
        ) from exc


def _nfc_paths(files: list[dict]) -> list[str]:
    return [unicodedata.normalize("NFC", f["filename"]) for f in files if f.get("filename")]


def _run_mutation(handler, args: argparse.Namespace, ctx: _Context) -> _Outcome:
    """Run a route/bounce handler; turn a _Fail into the exit-1 outcome with
    error_code and error_class (AR1-C6). Exit 0 carries error_class null."""
    state: dict = {"repo": None, "pr": args.pr}
    try:
        outcome = handler(args, ctx, state)
    except _Fail as fail:
        return _Outcome(
            payload={"error_code": fail.code, "error_class": fail.klass, **fail.extra},
            exit_code=1,
            error=fail.args[0],
            repo=state["repo"],
            pr=args.pr,
        )
    outcome.payload.setdefault("error_code", None)
    outcome.payload.setdefault("error_class", None)
    return outcome


def _preflight(args: argparse.Namespace, ctx: _Context, state: dict) -> tuple[str, str, str]:
    """TD-D8: the acting identity must be the overseer, before any fetch."""
    login = os.environ.get("HOS_BOT_LOGIN", "").strip()
    if login.lower() != ctx.config.overseer_handle.lower():
        raise _Fail(
            "acting_identity_not_overseer",
            "HOS_BOT_LOGIN is unset or is not the configured overseer identity",
            "deterministic",
        )
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        raise _Fail("repo_unresolved", resolved.error or "repo unresolved", "deterministic")
    state["repo"] = resolved[0]
    return resolved


def _fetch_open_pr(owner: str, repo_name: str, number: int) -> dict:
    pr = _gh_call(github.get_pull, owner, repo_name, number)
    if pr is None or not (pr.get("head") or {}).get("sha"):
        raise _Fail(
            "pr_not_found", f"PR #{number} not found or has no usable head.sha", "deterministic"
        )
    if pr.get("state") != "open":
        raise _Fail("pr_not_open", f"PR #{number} is not open", "deterministic")
    return pr


def _resolve_cid(pr: dict, owner: str, repo_name: str, ctx: _Context, not_verified: list[str]):
    resolution = merge_authority.bounce_cid(
        pr,
        worker_login=ctx.config.worker_handle,
        issue_lookup=lambda n: _gh_call(github.get_issue, owner, repo_name, n),
    )
    if resolution.source == "pr-fallback":
        note = f"cid: {resolution.cid} fallback ({resolution.warn})"
        not_verified.append(note)
        print(f"WARN: {note}", file=sys.stderr)
    return resolution


def _is_worker_authored(pr: dict, ctx: _Context) -> bool:
    user = pr.get("user") or {}
    return (
        str(user.get("login", "")).lower() == ctx.config.worker_handle.lower()
        and user.get("type") == "Bot"
    )


def _changed_paths(owner: str, repo_name: str, pr: dict) -> list[str]:
    files = _gh_call(github.list_pull_files, owner, repo_name, pr["number"])
    if len(files) >= _GITHUB_FILES_CAP:
        raise _Fail(
            "changed_files_truncated",
            f"PR has {len(files)} changed files; GitHub caps the list at {_GITHUB_FILES_CAP}",
            "deterministic",
        )
    if len(files) != pr.get("changed_files"):
        raise _Fail(
            "changed_files_mismatch",
            f"listed {len(files)} files but the PR reports {pr.get('changed_files')!r}",
            "transient",
        )
    return _nfc_paths(files)


_GITHUB_FILES_CAP = 3000


def _epoch(
    owner: str, repo_name: str, pr: dict, cid: str, ctx: _Context, not_verified: list[str]
) -> tuple[Optional[str], int]:
    """TD §3.5: sibling closures, epoch_start and the epoch-relative count."""
    root = str(ctx.repo_root)
    try:
        bounces = merge_authority.bounce_events(cid, repo_root=root)
        escalations = merge_authority.escalation_records(cid, repo_root=root)
    except ValueError as exc:
        raise _Fail("audit_unreadable", f"audit log unreadable: {exc}", "deterministic") from exc
    siblings = sorted(
        {n for n in (e.get("pr") for e in bounces) if isinstance(n, int)}
        | {e.pr for e in escalations if e.pr}
    )
    siblings = [n for n in siblings if n != pr["number"]]
    if len(siblings) > merge_authority._EPOCH_MAX_SIBLING_PRS:
        raise _Fail(
            "epoch_siblings_exceeded",
            f"{len(siblings)} sibling PRs for {cid} exceeds {merge_authority._EPOCH_MAX_SIBLING_PRS}",
            "deterministic",
        )
    closures: list[merge_authority.PrClosure] = []
    for number in siblings:
        sibling = _gh_call(github.get_pull, owner, repo_name, number)
        if sibling is None:
            raise _Fail("epoch_sibling_missing", f"sibling PR #{number} not found", "deterministic")
        if sibling.get("merged_at"):
            merger = sibling.get("merged_by") or {}
            if not merger.get("login"):
                raise _Fail(
                    "epoch_sibling_missing",
                    f"merged sibling PR #{number} has no merged_by login",
                    "deterministic",
                )
            closures.append(
                merge_authority.PrClosure(
                    number,
                    "merged",
                    sibling["merged_at"],
                    str(merger.get("login", "")),
                    str(merger.get("type", "")),
                )
            )
        elif sibling.get("state") == "closed":
            try:
                events = github.list_issue_events(
                    owner, repo_name, number, max_pages=merge_authority._ISSUE_EVENTS_MAX_PAGES
                )
            except github.ListTruncatedError as exc:
                raise _Fail("issue_events_truncated", str(exc), "deterministic") from exc
            except github.GitHubError as exc:
                raise _Fail(
                    "github_read_failed",
                    f"list_issue_events failed: {exc}",
                    merge_authority.classify_github_error(exc),
                ) from exc
            closed = [e for e in events if e.get("event") == "closed" and e.get("created_at")]
            if not closed:
                # A wrong epoch can only be fixed by a human looking, so fail closed.
                raise _Fail(
                    "epoch_sibling_missing",
                    f"closed sibling PR #{number} has no closed event",
                    "deterministic",
                )
            last = max(
                closed,
                key=lambda e: (
                    merge_authority._parse_iso(e["created_at"])
                    or datetime.min.replace(tzinfo=timezone.utc),
                    e.get("id") or 0,
                ),
            )
            actor = last.get("actor") or {}
            if not actor.get("login"):
                raise _Fail(
                    "epoch_sibling_missing",
                    f"closed sibling PR #{number} has a closed event with no actor login",
                    "deterministic",
                )
            closures.append(
                merge_authority.PrClosure(
                    number,
                    "closed",
                    last["created_at"],
                    str(actor.get("login", "")),
                    str(actor.get("type", "")),
                )
            )
    start = merge_authority.epoch_start(
        this_pr_created_at=str(pr.get("created_at") or ""),
        escalations=escalations,
        sibling_closures=closures,
        worker_login=ctx.config.worker_handle,
    )
    try:
        count = merge_authority.bounce_count(cid, repo_root=root, since=start)
    except ValueError as exc:
        raise _Fail("audit_unreadable", f"audit log unreadable: {exc}", "deterministic") from exc
    return start, count


def _prior_on_head(cid: str, head_sha: str, ctx: _Context):
    try:
        return merge_authority.bounced_on_head(cid, head_sha, repo_root=str(ctx.repo_root))
    except ValueError as exc:
        raise _Fail("audit_unreadable", f"audit log unreadable: {exc}", "deterministic") from exc


def _pin_head(owner: str, repo_name: str, number: int, head_sha: str) -> None:
    again = _gh_call(github.get_pull, owner, repo_name, number)
    if again is None:
        raise _Fail("pr_not_found", f"PR #{number} disappeared during the run", "deterministic")
    if (again.get("head") or {}).get("sha") != head_sha:
        raise _Fail(
            "head_moved", "the PR head changed during the run; nothing was written", "transient"
        )


def _finding_row(f: merge_authority.Finding, ids: Optional[dict] = None) -> dict:
    row = {"key": f.key, "class": f.cls, "origin": f.origin, "path": f.path, "summary": f.summary}
    if ids and f.key in ids:
        row["id"] = ids[f.key]
    return row


def _bounce_payload(result: merge_authority.BounceResult) -> dict:
    return {
        "comment_url": result.comment_url,
        "audit_relpath": result.audit_relpath,
        "bounce_number": result.bounce_number,
        "finding_ids": list(result.finding_ids),
        "finding_keys": list(result.finding_keys),
        "skipped": result.skipped,
        "at_cap": result.at_cap,
        "adopted": result.adopted,
        "finalize_errors": list(result.finalize_errors),
        "finalize_repaired": list(result.finalize_repaired),
    }


def _repair_read_fail(exc: merge_authority.RepairReadError) -> _Fail:
    if isinstance(exc.__cause__, github.ListTruncatedError):
        return _Fail("issue_events_truncated", str(exc), "deterministic")
    return _Fail("github_read_failed", str(exc), merge_authority.classify_github_error(exc))


def _lock_timeout_fail(exc: merge_authority.BounceLockTimeout) -> _Fail:
    return _Fail("bounce_lock_timeout", str(exc), "transient", {"comment_posted": False})


def _lock_unavailable_fail(exc: merge_authority.BounceLockUnavailable) -> _Fail:
    code = exc.errno
    extra: dict = {"comment_posted": False, "errno": code}
    name = errno.errorcode.get(code) if code is not None else None
    if name:
        extra["errno_name"] = name
    return _Fail("bounce_lock_unavailable", str(exc), exc.classification, extra)


def _repair_finalize(owner, repo_name, number, cid, head_sha, ctx, errors) -> list[str]:
    try:
        return merge_authority.repair_bounce_finalize(
            owner,
            repo_name,
            number,
            cid=cid,
            head_sha=head_sha,
            repo_root=str(ctx.repo_root),
            errors=errors,
        )
    except merge_authority.RepairReadError as exc:
        raise _repair_read_fail(exc) from exc
    except merge_authority.BounceLockTimeout as exc:
        raise _lock_timeout_fail(exc) from exc
    except merge_authority.BounceLockUnavailable as exc:
        raise _lock_unavailable_fail(exc) from exc
    except ValueError as exc:
        raise _Fail("audit_unreadable", f"audit log unreadable: {exc}", "deterministic") from exc


def _write_bounce(
    owner: str, repo_name: str, pr: dict, cid: str, ctx: _Context, to_bounce, epoch: Optional[str]
) -> merge_authority.BounceResult:
    """Call record_pr_bounce and classify its failures (TD §3.16)."""
    try:
        return merge_authority.record_pr_bounce(
            owner,
            repo_name,
            pr["number"],
            cid=cid,
            reason_category=merge_authority.derive_reason_category(f.cls for f in to_bounce),
            summary=merge_authority.bounce_summary_for(to_bounce, pr["head"]["sha"]),
            repo_root=str(ctx.repo_root),
            head_sha=pr["head"]["sha"],
            findings=list(to_bounce),
            epoch_since=epoch,
            cap=merge_authority.BOUNCE_CAP,
        )
    except merge_authority.RepairReadError as exc:
        raise _repair_read_fail(exc) from exc
    except merge_authority.BounceLockTimeout as exc:
        raise _lock_timeout_fail(exc) from exc
    except merge_authority.BounceLockUnavailable as exc:
        raise _lock_unavailable_fail(exc) from exc
    except github.GitHubError as exc:
        raise _Fail(
            "bounce_comment_failed",
            f"bounce comment failed: {exc}",
            merge_authority.classify_github_error(exc),
            {"comment_posted": False},
        ) from exc
    except merge_authority.BounceAuditWriteError as exc:
        raise _Fail(
            "bounce_audit_write_failed", str(exc), "deterministic", {"comment_posted": True}
        ) from exc
    except ValueError as exc:  # only reached before the comment is posted
        raise _Fail("audit_unreadable", f"audit log unreadable: {exc}", "deterministic") from exc
    except Exception as exc:
        raise _Fail(
            "bounce_unexpected_error",
            f"unexpected {exc.__class__.__name__} while bouncing; post state unknown",
            "deterministic",
            {"comment_posted": None},
        ) from exc


def _cmd_route(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    return _run_mutation(_route, args, ctx)


def _route(args: argparse.Namespace, ctx: _Context, state: dict) -> _Outcome:
    repo, owner, repo_name = _preflight(args, ctx, state)
    root = str(ctx.repo_root)
    not_verified = [_NOT_VERIFIED_COLLECTORS, _NOT_VERIFIED_S1B]

    try:
        with open(args.findings_file, "rb") as fh:
            findings_bytes = fh.read(merge_authority.FINDINGS_FILE_MAX_BYTES + 1)
    except OSError as exc:
        raise _Fail(
            "findings_file_invalid",
            f"cannot read findings file: {exc.__class__.__name__}",
            "deterministic",
        ) from exc
    if len(findings_bytes) > merge_authority.FINDINGS_FILE_MAX_BYTES:
        raise _Fail("findings_file_invalid", "findings file is oversize", "deterministic")
    # Parse before any GitHub call so a malformed file fails on every PR,
    # including the non-worker early return below.
    try:
        findings_raw = merge_authority.parse_findings_bytes(findings_bytes)
    except merge_authority.FindingsFileError as exc:
        raise _Fail("findings_file_invalid", str(exc), "deterministic") from exc

    pr = _fetch_open_pr(owner, repo_name, args.pr)
    head_sha = pr["head"]["sha"]
    base_sha = (pr.get("base") or {}).get("sha")
    if not base_sha:
        raise _Fail("pr_not_found", f"PR #{args.pr} has no usable base.sha", "deterministic")
    resolution = _resolve_cid(pr, owner, repo_name, ctx, not_verified)
    cid = resolution.cid
    worker_authored = _is_worker_authored(pr, ctx)

    base_payload = {
        "step": args.step,
        "cid": cid,
        "cid_source": resolution.source,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "worker_authored": worker_authored,
        "bounce_cap": merge_authority.BOUNCE_CAP,
        "s1b_inputs_stubbed": list(_S1B_STUBBED_INPUTS),
    }

    if not worker_authored:
        decided = merge_authority.route_pr(
            merge_authority.RouteInputs(
                pr=args.pr,
                worker_authored=False,
                head_sha=head_sha,
                findings=(),
                collectors_complete=_COLLECTORS_COMPLETE_S1A,
                hold_on_head=False,
                prior_on_head=(),
                epoch_bounce_count=0,
            )
        )
        payload = _route_payload(
            base_payload,
            decided,
            findings=(),
            ids=None,
            bounce=None,
            epoch=None,
            epoch_count=0,
            reviewer=None,
            reviewer_act=None,
            escalation=None,
            hold=None,
            eff=None,
            evidence={},
            reasons=list(decided.reasons),
        )
        return _Outcome(
            payload=payload, exit_code=0, not_verified=not_verified, repo=repo, pr=args.pr
        )

    changed = _changed_paths(owner, repo_name, pr)
    check_runs = _gh_call(github.list_check_runs_for_ref, owner, repo_name, head_sha)
    run_names = [r["name"] for r in check_runs if isinstance(r, dict) and r.get("name")]
    try:
        llm_findings, reasons = merge_authority.canonicalize_findings_ex(
            findings_raw,
            changed_paths=changed,
            head_check_runs=run_names,
            repo_slug=repo,
        )
    except merge_authority.FindingsSchemaError as exc:
        raise _Fail("findings_schema", f"findings_schema: {exc}", "deterministic") from exc

    code_findings, evidence = _collect(owner, repo_name, args, pr, changed, ctx)
    if evidence.get("required_checks_degraded"):
        not_verified.append("required-checks read degraded; collectors treated as incomplete")

    prior = _prior_on_head(cid, head_sha, ctx)
    epoch, epoch_count = _epoch(owner, repo_name, pr, cid, ctx, not_verified)

    try:
        text = merge_authority.fetch_codeowners_text(owner, repo_name, base_sha)
    except merge_authority.CodeownersUnreadableError as exc:
        raise _Fail("codeowners_unreadable", str(exc), "deterministic") from exc
    except github.GitHubError as exc:
        raise _Fail(
            "github_read_failed",
            f"get_contents failed: {exc}",
            merge_authority.classify_github_error(exc),
        ) from exc
    resolved = merge_authority.resolve_reviewer_from_text(
        text,
        changed,
        bot_accounts=ctx.config.bot_accounts,
        human_reviewer=ctx.config.human_reviewer,
    )
    try:
        merge_authority.check_resolution_consistent(resolved, text)
    except merge_authority.CodeownersDriftError as exc:
        raise _Fail("codeowners_resolution_drift", str(exc), "deterministic") from exc

    reviews = _gh_call(github.list_pull_reviews, owner, repo_name, args.pr)
    escalations = [
        e for e in merge_authority.escalation_records(cid, repo_root=root) if e.head_sha == head_sha
    ]
    escalation = max(
        escalations,
        key=lambda e: merge_authority._parse_iso(e.created_at)
        or datetime.min.replace(tzinfo=timezone.utc),
        default=None,
    )
    label_events: list = []
    if escalation is not None:
        try:
            label_events = github.list_issue_events(
                owner, repo_name, args.pr, max_pages=merge_authority._ISSUE_EVENTS_MAX_PAGES
            )
        except github.ListTruncatedError as exc:
            raise _Fail("issue_events_truncated", str(exc), "deterministic") from exc
        except github.GitHubError as exc:
            raise _Fail(
                "github_read_failed",
                f"list_issue_events failed: {exc}",
                merge_authority.classify_github_error(exc),
            ) from exc
    bots = ctx.config.bot_accounts
    reviewer_act = merge_authority.latest_reviewer_act(
        reviews, [], resolved.login, head_sha, None, bot_accounts=bots
    )
    escalation_act = (
        merge_authority.latest_reviewer_act(
            reviews,
            label_events,
            resolved.login,
            head_sha,
            escalation.created_at,
            bot_accounts=bots,
        )
        if escalation is not None
        else None
    )

    comments = _gh_call(github.list_issue_comments, owner, repo_name, args.pr)
    commit = _gh_call(github.get_commit, owner, repo_name, head_sha)
    committed = ((commit or {}).get("commit") or {}).get("committer", {}).get("date")
    try:
        suites = github.list_check_suites_for_ref(
            owner, repo_name, head_sha, max_pages=merge_authority._ISSUE_EVENTS_MAX_PAGES
        )
    except github.GitHubError as exc:
        raise _Fail(
            "github_read_failed",
            f"list_check_suites_for_ref failed: {exc}",
            (
                "deterministic"
                if isinstance(exc, github.ListTruncatedError)
                else merge_authority.classify_github_error(exc)
            ),
        ) from exc
    eff = merge_authority.effective_head_time(committed, suites, head_sha=head_sha)
    directive = None
    for login in dict.fromkeys(
        name.lower() for name in (ctx.config.human_reviewer, resolved.login)
    ):
        directive = merge_authority.detect_human_hold_directive(comments, login, eff)
        if directive is not None:
            break

    all_findings = tuple(code_findings) + tuple(llm_findings)
    decided = merge_authority.route_pr(
        merge_authority.RouteInputs(
            pr=args.pr,
            worker_authored=True,
            head_sha=head_sha,
            findings=all_findings,
            collectors_complete=_COLLECTORS_COMPLETE_S1A,
            hold_on_head=directive is not None,
            prior_on_head=prior,
            epoch_bounce_count=epoch_count,
            reviewer_act_on_head=reviewer_act,
            escalation=escalation,
            escalation_act=escalation_act,
        )
    )

    _pin_head(owner, repo_name, args.pr, head_sha)

    bounce = None
    ids = None
    if decided.disposition is merge_authority.Disposition.BOUNCE:
        written = _write_bounce(owner, repo_name, pr, cid, ctx, decided.to_bounce, epoch)
        bounce = _bounce_payload(written)
        ids = dict(zip(written.finding_keys, written.finding_ids))
        if written.at_cap:
            # Report the lock-time outcome as route_pr's rule 6d would have.
            decided = dataclasses.replace(
                decided,
                disposition=merge_authority.Disposition.ESCALATE,
                rule="6d",
                trigger="bounce-cap",
                to_bounce=(),
                reasons=(
                    *decided.reasons,
                    "the bounce cap was reached under the bounce lock; nothing was posted or written",
                ),
            )
        elif written.skipped:
            # Every finding was already bounced on this head: route_pr's rule 6c.
            decided = dataclasses.replace(
                decided,
                disposition=merge_authority.Disposition.NOOP,
                rule="6c",
                to_bounce=(),
                reasons=(*decided.reasons, "no-new-keys"),
            )
        for err in written.finalize_errors:
            not_verified.append(f"bounce finalize: {err}")
    elif (
        decided.disposition is merge_authority.Disposition.NOOP
        and "repair-finalize" in decided.actions
    ):
        repair_errors: list[str] = []
        repaired = _repair_finalize(owner, repo_name, args.pr, cid, head_sha, ctx, repair_errors)
        bounce = {"skipped": True, "finalize_repaired": repaired, "finalize_errors": repair_errors}
        for err in repair_errors:
            not_verified.append(f"bounce finalize: {err}")

    payload = _route_payload(
        base_payload,
        decided,
        findings=all_findings,
        ids=ids,
        bounce=bounce,
        epoch=epoch,
        epoch_count=epoch_count,
        reviewer={"login": resolved.login, "source": resolved.source, "note": resolved.note},
        reviewer_act=(
            {"kind": reviewer_act.kind, "source_id": reviewer_act.source_id, "at": reviewer_act.at}
            if reviewer_act
            else None
        ),
        escalation=(
            {"trigger": escalation.trigger, "created_at": escalation.created_at}
            if escalation
            else None
        ),
        hold=(
            {"comment_url": directive.get("html_url"), "created_at": directive.get("created_at")}
            if directive
            else None
        ),
        eff=eff,
        evidence=evidence,
        reasons=list(decided.reasons) + list(reasons),
    )
    return _Outcome(payload=payload, exit_code=0, not_verified=not_verified, repo=repo, pr=args.pr)


def _collect(owner, repo_name, args, pr, changed, ctx):
    try:
        return merge_authority.collect_code_findings(
            owner,
            repo_name,
            step=args.step,
            head_sha=pr["head"]["sha"],
            pr=pr,
            changed_paths=changed,
            repo_root=str(ctx.repo_root),
            default_branch=(pr.get("base") or {}).get("ref") or "main",
        )
    except github.GitHubError as exc:
        raise _Fail(
            "github_read_failed",
            f"required-checks read failed: {exc}",
            merge_authority.classify_github_error(exc),
        ) from exc


def _route_payload(
    base: dict,
    decided,
    *,
    findings,
    ids,
    bounce,
    epoch,
    epoch_count,
    reviewer,
    reviewer_act,
    escalation,
    hold,
    eff,
    evidence,
    reasons,
) -> dict:
    return {
        **base,
        "disposition": decided.disposition.value,
        "rule": decided.rule,
        "trigger": decided.trigger,
        "reasons": reasons,
        "findings": [_finding_row(f, ids) for f in findings],
        "open_finding_keys": [f.key for f in decided.open_findings],
        "overruled_keys": list(decided.overruled_keys),
        "actions": list(decided.actions),
        "bounce": bounce,
        "epoch_start": epoch,
        "epoch_bounce_count": epoch_count,
        "reviewer": reviewer,
        "reviewer_act": reviewer_act,
        "escalation": escalation,
        "hold_directive": hold,
        "effective_head_time": eff,
        "collectors": {
            "register": evidence.get("register"),
            "required_checks": evidence.get("required_checks"),
            "size": evidence.get("size"),
            "validator_artifact": "not-implemented-s1a",
        },
    }


def _cmd_bounce(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    return _run_mutation(_bounce, args, ctx)


def _bounce(args: argparse.Namespace, ctx: _Context, state: dict) -> _Outcome:
    repo, owner, repo_name = _preflight(args, ctx, state)
    not_verified: list[str] = []
    pr = _fetch_open_pr(owner, repo_name, args.pr)
    head_sha = pr["head"]["sha"]
    resolution = _resolve_cid(pr, owner, repo_name, ctx, not_verified)
    cid = resolution.cid

    def done(
        bounced,
        reason,
        *,
        findings=(),
        ids=None,
        bounce=None,
        epoch=None,
        count=0,
        at_cap=False,
        evidence=None,
    ) -> _Outcome:
        evidence = evidence or {}
        payload = {
            "step": args.step,
            "cid": cid,
            "cid_source": resolution.source,
            "head_sha": head_sha,
            "bounced": bounced,
            "reason": reason,
            "at_cap": at_cap,
            "findings": [_finding_row(f, ids) for f in findings],
            "bounce": bounce,
            "epoch_start": epoch,
            "epoch_bounce_count": count,
            "bounce_cap": merge_authority.BOUNCE_CAP,
            "collectors": {
                "register": evidence.get("register"),
                "required_checks": evidence.get("required_checks"),
                "size": evidence.get("size"),
                "validator_artifact": "not-implemented-s1a",
            },
        }
        return _Outcome(
            payload=payload, exit_code=0, not_verified=not_verified, repo=repo, pr=args.pr
        )

    if not _is_worker_authored(pr, ctx):
        return done(False, "non-worker-pr")

    changed = _changed_paths(owner, repo_name, pr)
    findings, evidence = _collect(owner, repo_name, args, pr, changed, ctx)
    if evidence.get("required_checks_degraded"):
        not_verified.append(
            "required-checks read degraded; the required-checks collector saw nothing"
        )
    prior = _prior_on_head(cid, head_sha, ctx)
    epoch, count = _epoch(owner, repo_name, pr, cid, ctx, not_verified)
    common = dict(findings=findings, epoch=epoch, count=count, evidence=evidence)

    if not findings:
        return done(False, "clean", **common)
    prior_identities = {p.identity for p in prior}
    new = [f for f in findings if f.identity not in prior_identities]
    if new and count >= merge_authority.BOUNCE_CAP:
        return done(False, "at-cap", at_cap=True, **common)

    _pin_head(owner, repo_name, args.pr, head_sha)
    # With nothing new, record_pr_bounce skips (and repairs an unfinished finalize).
    to_write = new or findings
    written = _write_bounce(owner, repo_name, pr, cid, ctx, to_write, epoch)
    for err in written.finalize_errors:
        not_verified.append(f"bounce finalize: {err}")
    ids = dict(zip(written.finding_keys, written.finding_ids))
    if written.at_cap:
        return done(False, "at-cap", at_cap=True, bounce=_bounce_payload(written), **common)
    if written.skipped:
        return done(False, "same-head", bounce=_bounce_payload(written), **common)
    return done(True, "bounced", ids=ids, bounce=_bounce_payload(written), **common)


# ---------------------------------------------------------------------------
# approval-merge / merge-provenance (#2213) — read-only; neither ever exits 3
# ---------------------------------------------------------------------------


def _cmd_approval_merge(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    """Would the overseer merge this PR on a designated human's approval?

    Informational only, never an authorization (TD-D19): the mutating command
    recomputes the decision itself. `current_user_can_bypass` describes the
    caller, so `gate_evaluated_as` names whose answer the gate field is, and
    R12's audit half reads this clone's audit log only (#1803).
    """
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    from scripts.automation.pr_review_cli import _scrub_secrets

    snapshot = None
    try:
        snapshot = approval_merge.fetch_snapshot(
            owner,
            repo_name,
            args.pr,
            ctx.config,
            repo_root=ctx.repo_root,
            now=datetime.now(timezone.utc),
        )
        decision = approval_merge.decide_merge_on_human_approval(snapshot, ctx.config)
    except approval_merge.SnapshotReadError as exc:
        decision = approval_merge.read_error_decision(exc, scrub=_scrub_secrets)

    gate = snapshot.gate if snapshot is not None else None
    payload = {
        "decision": decision.to_dict(),
        "would_merge": decision.outcome is approval_merge.ApprovalMergeOutcome.MERGE,
        "gate_evaluated_as": os.environ.get("HOS_BOT_LOGIN") or None,
        "gate": (
            None
            if gate is None
            else {
                "autonomous_capable": gate.autonomous_capable,
                "reason": gate.reason,
                "ruleset_ids": list(gate.ruleset_ids),
                "evidence": gate.evidence,
            }
        ),
    }
    return _Outcome(payload=payload, exit_code=0, repo=repo, pr=args.pr)


def _cmd_merge_provenance(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    """Classify an already-merged PR: did the overseer merge it on a recorded
    human-approval authorization (AD-9)?"""
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    from scripts.automation.pr_review_cli import _scrub_exc

    try:
        pull = github.get_pull(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"pull request read failed: {_scrub_exc(exc)}",
            repo=repo,
        )
    if not isinstance(pull, dict):
        return _Outcome(payload={}, exit_code=1, error=f"PR #{args.pr} not found", repo=repo)
    try:
        events = approval_merge.read_audit_events(ctx.repo_root, args.pr)
    except (OSError, ValueError, RuntimeError) as exc:
        return _Outcome(
            payload={}, exit_code=1, error=f"audit read failed: {_scrub_exc(exc)}", repo=repo
        )

    head = (pull.get("head") or {}).get("sha")
    payload = {
        "classification": "not_merged",
        "merged_by": None,
        "head_sha": head,
        "merge_commit_sha": pull.get("merge_commit_sha"),
        "authorized_record_present": False,
        "completion_record_present": False,
    }
    if pull.get("merged") is True:
        merged_by = (pull.get("merged_by") or {}).get("login") or ""
        result = approval_merge.classify_bot_merge(
            args.pr, str(head), merged_by, events, ctx.config.overseer_handle
        )
        payload.update(
            classification=result.classification.value,
            merged_by=merged_by or None,
            authorized_record_present=result.authorized_record is not None,
            completion_record_present=result.completion_record_present,
        )
    return _Outcome(payload=payload, exit_code=0, repo=repo, pr=args.pr)


_HANDLERS = {
    "gate": _cmd_gate,
    "register": _cmd_register,
    "bounce-count": _cmd_bounce_count,
    "human-approval": _cmd_human_approval,
    "hold-directive": _cmd_hold_directive,
    "protected-surface": _cmd_protected_surface,
    "security-surface": _cmd_security_surface,
    "codeowners": _cmd_codeowners,
    "route": _cmd_route,
    "bounce": _cmd_bounce,
    "approval-merge": _cmd_approval_merge,
    "merge-provenance": _cmd_merge_provenance,
}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
    """Parse argv, dispatch to one subcommand handler, print exactly one JSON
    record, and return the exit code. Never calls sys.exit itself.

    `repo_root` is a keyword-only, test-only injection point (§3.4.0) —
    `argparse` never defines it and the `__main__` block never populates it
    from `sys.argv`, so it is unreachable from any command line (T1.7/T1.8).
    """
    resolved_root = Path(repo_root).resolve() if repo_root is not None else _DEFAULT_REPO_ROOT

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageExit as exc:
        return exc.code

    subcommand: str = args.subcommand

    try:
        config = merge_config.resolve_config(resolved_root)
    except merge_config.ConfigError as exc:
        record = _envelope(
            subcommand=subcommand,
            repo_root=str(resolved_root),
            app_role=args.app,
            error=str(exc),
        )
        if subcommand in MUTATION_SUBCOMMANDS:
            record["error_code"] = "config_unresolved"
            record["error_class"] = "deterministic"
        print(json.dumps(record))
        return 1

    ctx = _Context(repo_root=resolved_root, config=config, app_role=args.app)
    outcome = _HANDLERS[subcommand](args, ctx)

    record = _envelope(
        subcommand=subcommand,
        repo=outcome.repo,
        repo_root=str(resolved_root),
        pr=outcome.pr,
        config_source=config.config_source,
        app_role=args.app,
        error=outcome.error,
    )
    record["not_verified"] = outcome.not_verified
    record.update(outcome.payload)
    print(json.dumps(record))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
