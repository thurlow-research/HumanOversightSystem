#!/usr/bin/env python3
"""
merge_authority_cli.py — L2 read-only primitives over merge_authority.py (#1357 slice 1).

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
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# Import bootstrap (§2): insert this CLI's own repo root at sys.path[0] before
# importing scripts.automation.lib.* so imports resolve regardless of cwd.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_DEFAULT_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from scripts.automation.lib import github, merge_authority, merge_config  # noqa: E402

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
)

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
    parser = _EnvelopeArgumentParser(prog="merge_authority_cli.py", add_help=False)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    common = _EnvelopeArgumentParser(add_help=False)
    common.add_argument("--app", required=True, choices=("worker", "overseer", "human"))
    common.add_argument("--repo", type=_repo_type, default=None)

    gate_p = subparsers.add_parser("gate", parents=[common], add_help=False)
    gate_p.add_argument("--branch", default=None)

    register_p = subparsers.add_parser("register", parents=[common], add_help=False)
    register_p.add_argument("--step", type=_step_type, required=True)

    bounce_p = subparsers.add_parser("bounce-count", parents=[common], add_help=False)
    bounce_p.add_argument("--cid", type=_cid_type, required=True)

    for name in (
        "human-approval",
        "hold-directive",
        "protected-surface",
        "security-surface",
        "codeowners",
    ):
        pr_p = subparsers.add_parser(name, parents=[common], add_help=False)
        pr_p.add_argument("--pr", type=_pr_type, required=True)

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


_HANDLERS = {
    "gate": _cmd_gate,
    "register": _cmd_register,
    "bounce-count": _cmd_bounce_count,
    "human-approval": _cmd_human_approval,
    "hold-directive": _cmd_hold_directive,
    "protected-surface": _cmd_protected_surface,
    "security-surface": _cmd_security_surface,
    "codeowners": _cmd_codeowners,
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
