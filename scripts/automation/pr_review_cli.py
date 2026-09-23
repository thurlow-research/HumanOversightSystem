#!/usr/bin/env python3
"""
pr_review_cli.py — L2 PR-review write primitive (#1657).

Two subcommands: `submit-verdict` posts exactly one review object (APPROVE
or COMMENT — never REQUEST_CHANGES, ADR-1657 AD-2) recording the overseer's
verdict on a PR; `request-reviewer` requests the CODEOWNERS human as a
required reviewer, but only on the three conditions ADR-1657 AD-3 pins
(above-ceiling tier, CRITICAL tier, or a protected-surface / CODEOWNERS-
human-owned path) — never universally.

This module decides the review event and the reviewer trigger itself (it is
the sole author of both, per ADR-1357-AMENDMENT-1 FC-2 — slice 4 calls this
primitive rather than re-deriving its guards). It performs no recompute of
`decide_merge_authority`'s own disposition and merges nothing.

Contract: docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md §4,
binding conditions in docs/v0.7.0/ADR-1657-overseer-review-objects.md §3.
Invoked exclusively through `bootstrap/pr_review.sh` (L3), which mints the
app token, invokes this module, and passes stdout/exit-code through
verbatim (mirrors ARCH-3a for #1357 — this module is the record schema's
sole author).

Importing this module performs no I/O, no config read, no `gh` call, and no
token mint — the only module-level work is the sys.path bootstrap below,
which makes the CLI cwd-immune (mirrors merge_authority_cli.py:33-38).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

# Import bootstrap: insert this CLI's own repo root at sys.path[0] before
# importing scripts.automation.lib.* so imports resolve regardless of cwd.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_DEFAULT_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from scripts.automation.lib import github, merge_authority, merge_config  # noqa: E402

SCHEMA_VERSION = 1

SUBCOMMANDS = ("submit-verdict", "request-reviewer")

_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_PR_RE = re.compile(r"^[0-9]+$")
_VALID_TIERS = ("SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL")


# ---------------------------------------------------------------------------
# Secret redaction for exception text embedded in the envelope (Finding 2,
# #1657 codex adversarial-security second review, CWE-200). Every exception
# this module stringifies into an `error`/`not_verified` field is printed to
# stdout and lands in a committed audit record — a prior review round added
# only an invariant *comment* asserting no code path embeds a secret in an
# exception message; codex correctly pointed out a comment is not
# enforcement. This scrubs the shapes that matter for this module's call
# graph (github.py/subprocess errors): the live GH_TOKEN value if present in
# the environment, Authorization/Bearer header patterns, and GitHub
# installation/PAT-shaped token prefixes.
# ---------------------------------------------------------------------------

_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*:\s*)(?:bearer\s+)?\S+")
_BEARER_ONLY_RE = re.compile(r"(?i)\bbearer\s+\S+\b")
_GH_TOKEN_SHAPE_RE = re.compile(
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{8,}\b|\bgithub_pat_[A-Za-z0-9_]{8,}\b"
)


def _scrub_secrets(text: str) -> str:
    """Redact secret-shaped substrings from free-form text before it is
    embedded into the JSON envelope. Order matters: the Authorization-header
    pattern is applied before the bare-Bearer pattern so "Authorization:
    Bearer <token>" is redacted as one unit rather than leaving a dangling
    "Bearer" behind; the GH_TOKEN literal-value replace runs first since it
    is the exact live secret, not a shape heuristic.
    """
    if not text:
        return text
    scrubbed = text
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if gh_token:
        scrubbed = scrubbed.replace(gh_token, "[REDACTED]")
    scrubbed = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)}[REDACTED]", scrubbed)
    scrubbed = _BEARER_ONLY_RE.sub("Bearer [REDACTED]", scrubbed)
    scrubbed = _GH_TOKEN_SHAPE_RE.sub("[REDACTED]", scrubbed)
    return scrubbed


def _scrub_exc(exc: BaseException) -> str:
    """`str(exc)`, scrubbed via `_scrub_secrets`. Every f-string in this
    module that interpolates an exception's text into an `error` or
    `not_verified` envelope field must go through this — never `str(exc)`
    directly — so a future github.py/subprocess error that happens to embed
    a token cannot publish it into stdout or the committed audit trail. Keeps
    the exception's own message (scrubbed) rather than dropping it, so the
    envelope stays diagnosable; callers that also want the exception's class
    name compose it themselves (e.g. `f"unhandled {type(exc).__name__}: "
    f"{_scrub_exc(exc)}"`).
    """
    return _scrub_secrets(str(exc))


# ---------------------------------------------------------------------------
# argv-level type validators — usage errors (exit 2), never a decision.
# ---------------------------------------------------------------------------


def _repo_type(value: str) -> str:
    if not _REPO_SLUG_RE.match(value):
        raise argparse.ArgumentTypeError(f"--repo must match owner/repo, got: {value!r}")
    return value


def _pr_type(value: str) -> int:
    if not _PR_RE.match(value):
        raise argparse.ArgumentTypeError(f"--pr must be a positive integer, got: {value!r}")
    return int(value)


def _tier_type(value: str) -> str:
    up = value.upper()
    if up not in _VALID_TIERS:
        # A typo must be loud, not merely conservative (ADR-1657 §4.1) — an
        # unrecognised tier is a usage error, never silently coerced to
        # CRITICAL the way require_tier_ceiling.tier_to_int's own fail-safe
        # default would.
        raise argparse.ArgumentTypeError(f"--tier must be one of {_VALID_TIERS}, got: {value!r}")
    return up


def _event_type(value: str) -> str:
    if value == "request_changes":
        raise argparse.ArgumentTypeError(
            "--event request_changes is not supported — REQUEST_CHANGES is excluded "
            "from this primitive's event enum (ADR-1657 AD-2: a bot CHANGES_REQUESTED "
            "has no autonomous clearing actor above OVERSEER_CEILING). Use "
            "bootstrap/post_review_thread.sh for a blocking, resolvable finding instead."
        )
    if value not in ("approve", "comment"):
        raise argparse.ArgumentTypeError(f"--event must be 'approve' or 'comment', got: {value!r}")
    return value


# ---------------------------------------------------------------------------
# The envelope and the single-producer argparse error path.
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
    """Raised by _EnvelopeArgumentParser.error() instead of calling
    sys.exit, so main() stays the sole owner of process-exit decisions."""

    def __init__(self, code: int):
        super().__init__(f"usage error, exit {code}")
        self.code = code


class _EnvelopeArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser whose error() emits the envelope on stdout (stdout
    is exactly one JSON object, always — including on a usage error) and
    the human-readable usage text on stderr, then raises _UsageExit(2)
    rather than calling sys.exit directly.

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
    """Build the argv contract (§4.1). --tier is required on both
    subcommands, uniformly — no conditionally-valid flag. Help is disabled
    everywhere so an unrecognised -h/--help is a plain usage error (exit 2
    via error()) rather than argparse's own sys.exit(0) help path, keeping
    main() the sole exit-code author.
    """
    parser = _EnvelopeArgumentParser(prog="pr_review_cli.py", add_help=False)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    common = _EnvelopeArgumentParser(add_help=False)
    common.add_argument("--app", required=True, choices=("worker", "overseer", "human"))
    common.add_argument("--repo", type=_repo_type, default=None)
    common.add_argument("--pr", type=_pr_type, required=True)
    common.add_argument("--tier", type=_tier_type, required=True)

    submit_p = subparsers.add_parser("submit-verdict", parents=[common], add_help=False)
    submit_p.add_argument("--event", type=_event_type, required=True)
    submit_p.add_argument("--body-file", required=True)

    request_p = subparsers.add_parser("request-reviewer", parents=[common], add_help=False)
    request_p.add_argument("--reviewer", default=None)

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
    payload: dict
    exit_code: int
    error: str | None = None
    not_verified: list[str] = field(default_factory=list)
    repo: str | None = None
    pr: int | None = None


@dataclass
class _Preamble:
    """Shared read state both subcommands need (§4.2)."""

    repo: str
    owner: str
    repo_name: str
    bot_login: str
    pr_obj: dict
    head_sha: str
    author_login: str
    requested_reviewers: list[str]
    reviews: list[dict]
    not_verified: list[str]


def _resolve_repo_or_fail(
    args: argparse.Namespace, ctx: _Context
) -> tuple[str, str, str] | _Outcome:
    """Resolve owner/repo, or return a ready-to-emit exit-1/exit-3 _Outcome.

    An explicit --repo is a formatting convenience only, never an
    authorization boundary (MUST_FIX 2, #1657 PR-1 review round 4):
    `merge_config.resolve_repo_slug` only regex-validates the slug shape and
    returns it verbatim, and this primitive performs state-changing GitHub
    writes with an App installation token that may have multi-repo access.
    So an explicit --repo that does not match the slug resolved from this
    checkout's own `origin` remote is refused (exit 3) before any GitHub
    call is made — never after, since a wrong-repo PR fetch would itself be
    the cross-repo leak this guard exists to prevent. This check lives here,
    not in merge_config.resolve_repo_slug, because merge_config is shared
    with the read-only merge_authority_cli and must not change behaviour for
    it.
    """
    try:
        repo = merge_config.resolve_repo_slug(ctx.repo_root, explicit=args.repo)
    except merge_config.ConfigError as exc:
        return _Outcome(payload={}, exit_code=1, error=_scrub_exc(exc))

    if args.repo is not None:
        try:
            origin_repo = merge_config.resolve_repo_slug(ctx.repo_root, explicit=None)
        except merge_config.ConfigError as exc:
            return _Outcome(
                payload={},
                exit_code=1,
                error=(
                    f"--repo could not be verified against the local checkout's "
                    f"origin remote: {_scrub_exc(exc)}"
                ),
            )
        if repo.lower() != origin_repo.lower():
            return _Outcome(
                payload={"refused": True, "refusal_reason": "repo_scope_mismatch"},
                exit_code=3,
                repo=repo,
            )

    owner, repo_name = repo.split("/", 1)
    return repo, owner, repo_name


def _resolve_preamble(args: argparse.Namespace, ctx: _Context) -> _Preamble | _Outcome:
    """§4.2 steps 3-6: resolve repo, HOS_BOT_LOGIN, the PR object, and the
    reviews list. Identical for both subcommands."""
    resolved = _resolve_repo_or_fail(args, ctx)
    if isinstance(resolved, _Outcome):
        return resolved
    repo, owner, repo_name = resolved

    bot_login = os.environ.get("HOS_BOT_LOGIN", "").strip()
    if not bot_login:
        mint_failed = os.environ.get("HOS_PR_REVIEW_TOKEN_MINT_FAILED", "").strip() == "1"
        if mint_failed:
            # pr_review.sh sets this when get_app_token.sh itself exited
            # non-zero — GH_TOKEN and HOS_BOT_LOGIN are exported together by
            # that one script, so a mint failure and a genuine configuration
            # problem are otherwise indistinguishable from here (SHOULD_FIX
            # F, #1657 PR-1 review round 2): a transient auth failure must
            # not be reported as if the environment were misconfigured, since
            # that masks "retry next cycle" behind "your config is broken".
            error = (
                "GitHub App token mint failed (bootstrap/get_app_token.sh "
                "exited non-zero) — HOS_BOT_LOGIN was never set as a result. "
                "This is a mint failure, not a configuration problem; it will "
                "very likely succeed on the next cycle"
            )
        else:
            error = (
                "HOS_BOT_LOGIN is unset or empty in the environment — the acting "
                "bot's identity is load-bearing for the self-authored and "
                "already-approved guards and must never be inferred (GitHub App "
                "installation tokens return an error on GET /user)"
            )
        return _Outcome(
            payload={},
            exit_code=1,
            error=error,
            repo=repo,
            pr=args.pr,
        )

    try:
        pr_obj = github.get_pull(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch PR #{args.pr}: {_scrub_exc(exc)}",
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

    not_verified: list[str] = []
    head_sha = (pr_obj.get("head") or {}).get("sha")
    if not head_sha:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"PR #{args.pr} has no usable head.sha",
            not_verified=["commit_id: PR object had no usable head.sha"],
            repo=repo,
            pr=args.pr,
        )

    author_login = (pr_obj.get("user") or {}).get("login", "")
    requested_reviewers = [
        r.get("login", "") for r in (pr_obj.get("requested_reviewers") or []) if r.get("login")
    ]

    try:
        reviews = github.list_pull_reviews(owner, repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch reviews: {_scrub_exc(exc)}",
            repo=repo,
            pr=args.pr,
        )

    review_comments_count = pr_obj.get("review_comments")
    if not reviews and isinstance(review_comments_count, int) and review_comments_count > 0:
        not_verified.append(
            f"reviews: list_pull_reviews returned empty but PR reports "
            f"review_comments={review_comments_count} — possible inconsistent read"
        )

    return _Preamble(
        repo=repo,
        owner=owner,
        repo_name=repo_name,
        bot_login=bot_login,
        pr_obj=pr_obj,
        head_sha=head_sha,
        author_login=author_login,
        requested_reviewers=requested_reviewers,
        reviews=reviews,
        not_verified=not_verified,
    )


def _load_require_tier_ceiling():
    """Load require_tier_ceiling.py by file path (scripts/framework is not
    an importable package — TD-VF-4). Same idiom as
    merge_config._load_require_tier_ceiling and
    require_overseer_approval.py:48-55; do not re-implement tier ordering
    (ADR-1657 §4.3)."""
    path = Path(__file__).resolve().parents[1] / "framework" / "require_tier_ceiling.py"
    spec = importlib.util.spec_from_file_location("hos_require_tier_ceiling_pr_review", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_codeowners_module():
    """Load scripts/oversight/codeowners.py by file path (it is not an
    importable package). Same idiom as
    merge_authority_cli.py._load_codeowners_module — the canonical
    CODEOWNERS module for this side of the trust boundary (ADR-1657 AD-4).
    Loaded lazily, only from inside a handler, so importing this CLI stays
    side-effect-free."""
    path = Path(__file__).resolve().parents[1] / "oversight" / "codeowners.py"
    spec = importlib.util.spec_from_file_location("hos_oversight_codeowners_pr_review", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# submit-verdict
# ---------------------------------------------------------------------------


# submit_pull_review itself is called with retries=0 — it is a
# non-idempotent POST with no idempotency key, so this module, not
# github.py's generic retry loop, decides how to recover from an ambiguous
# failure. It does not retry the POST in-process (#1657 PR-1 review round
# 3, MUST_FIX): GET /pulls/{n}/reviews publishes no read-after-write
# guarantee relative to the write that just failed, so a single recheck
# that comes back empty cannot distinguish "the write never landed" from
# "it landed but this GET hasn't caught up yet" — retrying in that second
# case would create a genuine duplicate, which is exactly the failure this
# recovery exists to prevent. The safe recovery for that residual case is
# the next cron cycle's fresh preamble read (G3/G4 dedup correctly once any
# lag has resolved), not a bounded retry here.


def _find_matching_review(
    owner: str,
    repo_name: str,
    pr_number: int,
    bot_login: str,
    head_sha: str,
    expected_state: str,
    body_text: str,
) -> dict | None:
    """Re-fetch reviews and look for the one this exact write would have
    created, for ambiguous-POST recovery. Returns the review dict or None.
    May itself raise github.GitHubError — callers must handle it (the
    recheck is a real network call and can fail too).

    Must compare `body` as well as (bot_login, commit_id, state) (#1657
    PR-1 review round 3, MUST_FIX): G4 deliberately permits multiple
    distinct COMMENT reviews on the same head SHA across cycles — its own
    comparison is byte-identical and never suppresses a body that differs
    by so much as a character. Without the body check here, a prior
    cycle's stale-content review (same bot, same head, same state) is
    indistinguishable from the write that just failed, and this function
    would report success for a write that never landed.
    """
    for review in github.list_pull_reviews(owner, repo_name, pr_number):
        reviewer_login = (review.get("user") or {}).get("login", "")
        if (
            reviewer_login.lower() == bot_login.lower()
            and review.get("commit_id") == head_sha
            and review.get("state") == expected_state
            and review.get("body", "") == body_text
        ):
            return review
    return None


def _verdict_payload_base(event: str, tier: str, ceiling: str, pr_author: str) -> dict:
    return {
        "posted": False,
        "skipped": False,
        "skip_reason": None,
        "refused": False,
        "refusal_reason": None,
        "event_requested": event,
        "review_id": None,
        "review_state": None,
        "review_url": None,
        "commit_id": None,
        "tier": tier,
        "overseer_ceiling": ceiling,
        "pr_author": pr_author,
        "body_bytes": None,
    }


def _cmd_submit_verdict(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    pre = _resolve_preamble(args, ctx)
    if isinstance(pre, _Outcome):
        return pre

    ceiling_name = ctx.config.overseer_ceiling.name
    base = _verdict_payload_base(args.event, args.tier, ceiling_name, pre.author_login)
    require_tier_ceiling = _load_require_tier_ceiling()

    # G0 — --app never authorizes an approve on its own (MUST_FIX 1, #1657
    # PR-1 review round 4). Elsewhere ctx.app_role/args.app is only ever
    # echoed into the envelope and no gate below reads it, so without this
    # check `--app worker --event approve` on a PR the worker did not author
    # would clear G1/G2 and post a real APPROVE review under the wrong
    # identity. Only the overseer app may ever request approve; non-approve
    # events (comment) are unaffected for every app role.
    if args.event == "approve" and ctx.app_role != "overseer":
        payload = {
            **base,
            "refused": True,
            "refusal_reason": "approve_requires_overseer_identity",
            "commit_id": pre.head_sha,
        }
        return _Outcome(
            payload=payload,
            exit_code=3,
            not_verified=pre.not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # G0b — --app alone is caller-supplied argv, trivially spoofable (Finding
    # 1, #1657 codex adversarial-security second review, CWE-863): G0 above
    # only proves the caller *claimed* --app overseer, not that it is. Cross-
    # check against the acting identity `pre.bot_login` resolved from
    # HOS_BOT_LOGIN (available here because _resolve_preamble already ran)
    # against the configured overseer handle. This is defence-in-depth, not
    # a cryptographic binding — HOS_BOT_LOGIN is itself environment-supplied,
    # so a caller that controls both --app and the environment defeats this
    # too. The authoritative protection is that GitHub attributes the posted
    # review to whoever owns the App installation token used for the POST,
    # and scripts/framework/require_overseer_approval.py checks that
    # attributed login before treating the review as a real approval — this
    # gate only narrows the window in which a mismatched identity can reach
    # the POST at all. Kept as a distinct refusal_reason from G0's (rather
    # than folded into it) so the audit envelope can tell "wrong --app" apart
    # from "right --app, wrong actual identity".
    if args.event == "approve" and pre.bot_login.lower() != ctx.config.overseer_handle.lower():
        payload = {
            **base,
            "refused": True,
            "refusal_reason": "approve_requires_overseer_identity_match",
            "commit_id": pre.head_sha,
        }
        return _Outcome(
            payload=payload,
            exit_code=3,
            not_verified=pre.not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # G1 — never approve above OVERSEER_CEILING (mechanises overseer.md:54:
    # require_tier_ceiling.py fails any PR the overseer approved above its
    # ceiling, so an approval there is never recoverable by the caller).
    if args.event == "approve" and require_tier_ceiling.tier_exceeds_ceiling(
        args.tier, ceiling_name
    ):
        payload = {
            **base,
            "refused": True,
            "refusal_reason": "above_ceiling_approve",
            "commit_id": pre.head_sha,
        }
        return _Outcome(
            payload=payload,
            exit_code=3,
            not_verified=pre.not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # G2 — never approve a PR this overseer App itself authored (mechanises
    # overseer.md:53).
    if args.event == "approve" and pre.author_login.lower() == pre.bot_login.lower():
        payload = {
            **base,
            "refused": True,
            "refusal_reason": "self_authored",
            "commit_id": pre.head_sha,
        }
        return _Outcome(
            payload=payload,
            exit_code=3,
            not_verified=pre.not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # G3 — already approved this exact head: skip, no POST.
    if args.event == "approve":
        for review in pre.reviews:
            reviewer_login = (review.get("user") or {}).get("login", "")
            if (
                review.get("state") == "APPROVED"
                and reviewer_login.lower() == pre.bot_login.lower()
                and review.get("commit_id") == pre.head_sha
            ):
                payload = {
                    **base,
                    "skipped": True,
                    "skip_reason": "already_approved_on_head",
                    "review_id": review.get("id"),
                    "review_state": review.get("state"),
                    "review_url": review.get("html_url"),
                    "commit_id": pre.head_sha,
                }
                return _Outcome(
                    payload=payload,
                    exit_code=0,
                    not_verified=pre.not_verified,
                    repo=pre.repo,
                    pr=args.pr,
                )

    # Read and validate the body file. Logically this is G5 ("body file
    # absent, unreadable, or empty"), evaluated here — ahead of G4 — because
    # G4's byte-identical comparison needs the body's content; G5 is a
    # precondition of evaluating G4, not a later, independent check.
    try:
        body_text = Path(args.body_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError is a ValueError subclass, not an OSError — a
        # body file with invalid UTF-8 bytes must still exit 2 per G5's
        # table, not fall through to main()'s generic exit-1 catch-all.
        return _Outcome(
            payload={},
            exit_code=2,
            error=f"--body-file unreadable: {_scrub_exc(exc)}",
            repo=pre.repo,
            pr=args.pr,
        )
    if not body_text.strip():
        return _Outcome(
            payload={},
            exit_code=2,
            error=f"--body-file is empty: {args.body_file}",
            repo=pre.repo,
            pr=args.pr,
        )

    # G4 — an identical COMMENT verdict already posted on this exact head:
    # skip, no POST. Narrow by design (byte-identical body, same head SHA):
    # it never suppresses an approval and never suppresses a body that
    # differs by so much as a character, so it cannot hide new information.
    if args.event == "comment":
        for review in pre.reviews:
            reviewer_login = (review.get("user") or {}).get("login", "")
            if (
                review.get("state") == "COMMENTED"
                and reviewer_login.lower() == pre.bot_login.lower()
                and review.get("commit_id") == pre.head_sha
                and review.get("body", "") == body_text
            ):
                payload = {
                    **base,
                    "skipped": True,
                    "skip_reason": "identical_comment_verdict_on_head",
                    "review_id": review.get("id"),
                    "review_state": review.get("state"),
                    "review_url": review.get("html_url"),
                    "commit_id": pre.head_sha,
                }
                return _Outcome(
                    payload=payload,
                    exit_code=0,
                    not_verified=pre.not_verified,
                    repo=pre.repo,
                    pr=args.pr,
                )

    gh_event = "APPROVE" if args.event == "approve" else "COMMENT"
    expected_state = "APPROVED" if args.event == "approve" else "COMMENTED"

    not_verified = list(pre.not_verified)
    try:
        result = github.submit_pull_review(
            pre.owner, pre.repo_name, args.pr, gh_event, body_text, pre.head_sha
        )
    except github.GitHubError as exc:
        status = getattr(exc, "status_code", None)
        if status == 422:
            return _Outcome(
                payload={},
                exit_code=1,
                error=(
                    f"commit_id {pre.head_sha} is stale (422) — the worker likely "
                    f"pushed between the read and this write: {_scrub_exc(exc)}"
                ),
                repo=pre.repo,
                pr=args.pr,
            )
        if status is not None and status < 500:
            # A definite client-side rejection: GitHub processed the
            # request and refused it, so no review object was created —
            # not ambiguous.
            return _Outcome(
                payload={},
                exit_code=1,
                error=f"failed to submit review: {_scrub_exc(exc)}",
                repo=pre.repo,
                pr=args.pr,
            )
        # Ambiguous failure (no parseable status, a timeout, or a 5xx —
        # submit_pull_review is called with retries=0 specifically so this
        # module decides deliberately, never github.py's generic retry
        # loop): the POST may have already reached GitHub and created a
        # review despite the failed response. Recheck once — deliberately
        # not in a retry loop, see the comment above _find_matching_review.
        try:
            existing = _find_matching_review(
                pre.owner,
                pre.repo_name,
                args.pr,
                pre.bot_login,
                pre.head_sha,
                expected_state,
                body_text,
            )
        except github.GitHubError as recheck_exc:
            return _Outcome(
                payload={},
                exit_code=1,
                error=(
                    f"failed to submit review ({_scrub_exc(exc)}) and the post-failure "
                    f"recheck also failed: {_scrub_exc(recheck_exc)}"
                ),
                not_verified=not_verified,
                repo=pre.repo,
                pr=args.pr,
            )
        if existing is not None:
            payload = {
                **base,
                "posted": True,
                "review_id": existing.get("id"),
                "review_state": existing.get("state"),
                "review_url": existing.get("html_url"),
                "commit_id": existing.get("commit_id"),
                "body_bytes": len(body_text.encode("utf-8")),
            }
            not_verified.append(
                f"review posted despite an ambiguous submit_pull_review response: {_scrub_exc(exc)}"
            )
            return _Outcome(
                payload=payload,
                exit_code=0,
                not_verified=not_verified,
                repo=pre.repo,
                pr=args.pr,
            )
        # The recheck came back empty: this write's outcome is genuinely
        # indeterminate from here. Do not retry in-process (see the comment
        # above _find_matching_review) — report failure and let the next
        # cron cycle's fresh preamble read reconcile via G3/G4.
        return _Outcome(
            payload={},
            exit_code=1,
            error=(
                f"failed to submit review, and the post-failure recheck found "
                f"no matching review — outcome indeterminate, not retrying "
                f"in-process; the next cron cycle's preamble read will "
                f"reconcile via G3/G4: {_scrub_exc(exc)}"
            ),
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # Read-back verification: a verdict that did not land as requested must
    # never report success.
    result_state = result.get("state")
    result_body = result.get("body") or ""
    if result_state != expected_state:
        return _Outcome(
            payload={},
            exit_code=1,
            error=(
                f"review posted but read-back state was {result_state!r}, "
                f"expected {expected_state!r}"
            ),
            repo=pre.repo,
            pr=args.pr,
        )
    if result_body.startswith("@/"):
        return _Outcome(
            payload={},
            exit_code=1,
            error=(
                "review posted but read-back body starts with '@/' — an @path "
                "literal was stored instead of file content (#752)"
            ),
            repo=pre.repo,
            pr=args.pr,
        )

    payload = {
        **base,
        "posted": True,
        "review_id": result.get("id"),
        "review_state": result_state,
        "review_url": result.get("html_url"),
        "commit_id": result.get("commit_id"),
        "body_bytes": len(body_text.encode("utf-8")),
    }
    return _Outcome(
        payload=payload,
        exit_code=0,
        not_verified=not_verified,
        repo=pre.repo,
        pr=args.pr,
    )


# ---------------------------------------------------------------------------
# request-reviewer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriggerResult:
    above_ceiling: bool
    critical_tier: bool
    protected_surface: bool
    triggered: bool


def evaluate_reviewer_trigger(
    tier: str, ceiling: str, changed_files: list[str], repo_root
) -> TriggerResult:
    """Pure predicate implementing the #1657 human-reviewer trigger scoping
    (ADR-1657 AD-3 — CONFIRMED, do not widen). No I/O beyond
    touches_protected_surface's own surfaces-file read.

    `critical_tier` is kept as its own term even though it is currently
    implied by `above_ceiling` (ceiling is HIGH): the ruling names the
    CRITICAL path separately, and `machine-accounts.env` permits the
    ceiling to be re-tuned — folding the terms together would let a future
    ceiling change silently drop the CRITICAL trigger.
    """
    require_tier_ceiling = _load_require_tier_ceiling()
    above_ceiling = require_tier_ceiling.tier_exceeds_ceiling(tier, ceiling)
    critical_tier = tier.upper() == "CRITICAL"
    protected_surface = merge_authority.touches_protected_surface(changed_files, str(repo_root))
    triggered = above_ceiling or critical_tier or protected_surface
    return TriggerResult(
        above_ceiling=above_ceiling,
        critical_tier=critical_tier,
        protected_surface=protected_surface,
        triggered=triggered,
    )


def _reviewer_payload_base(trigger: TriggerResult, changed_file_count: int, head_sha: str) -> dict:
    return {
        "requested": False,
        "skipped": False,
        "skip_reason": None,
        "refused": False,
        "refusal_reason": None,
        "resolved_reviewer": None,
        "resolution_source": None,
        "codeowners_owners": [],
        "codeowners_team_owners": [],
        "trigger": {
            "above_ceiling": trigger.above_ceiling,
            "critical_tier": trigger.critical_tier,
            "protected_surface": trigger.protected_surface,
        },
        "matched_protected_paths": [],
        "changed_file_count": changed_file_count,
        "head_sha": head_sha,
    }


def _cmd_request_reviewer(args: argparse.Namespace, ctx: _Context) -> _Outcome:
    pre = _resolve_preamble(args, ctx)
    if isinstance(pre, _Outcome):
        return pre

    try:
        files = github.list_pull_files(pre.owner, pre.repo_name, args.pr)
    except github.GitHubError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=f"failed to fetch changed files: {_scrub_exc(exc)}",
            repo=pre.repo,
            pr=args.pr,
        )
    changed_files = [f["filename"] for f in files if f.get("filename")]

    trigger = evaluate_reviewer_trigger(
        args.tier, ctx.config.overseer_ceiling.name, changed_files, ctx.repo_root
    )
    base = _reviewer_payload_base(trigger, len(changed_files), pre.head_sha)

    if not trigger.triggered:
        # Step 4 — fail-closed on an unevaluable trigger: a false "not
        # triggered" from an empty file list would silently skip a human
        # gate, so this is an operational failure (exit 1), never the
        # scoping refusal (exit 3).
        if not changed_files:
            return _Outcome(
                payload={},
                exit_code=1,
                error=(
                    "0 changed files reported — the protected-surface trigger "
                    "could not be evaluated"
                ),
                not_verified=pre.not_verified,
                repo=pre.repo,
                pr=args.pr,
            )

        # Step 3 — the ruling's scoping implemented as a mechanism (ARCH-3:
        # the refusal payload also carries codeowners_human_owned, purely
        # observational — never escalated to a trigger).
        codeowners_module = _load_codeowners_module()
        codeowners_human_owned = None
        not_verified = list(pre.not_verified)
        try:
            required, _matched, _reason = codeowners_module.check_pr_files(
                changed_files, ctx.repo_root, set(ctx.config.bot_accounts)
            )
            codeowners_human_owned = required
        except Exception as exc:  # noqa: BLE001 — observational only, never fatal
            not_verified.append(
                f"codeowners_human_owned: check_pr_files raised: {_scrub_exc(exc)}"
            )

        payload = {
            **base,
            "refused": True,
            "refusal_reason": "no_qualifying_trigger",
            "codeowners_human_owned": codeowners_human_owned,
        }
        return _Outcome(
            payload=payload,
            exit_code=3,
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # Step 5 — resolve the reviewer.
    not_verified = list(pre.not_verified)
    if args.reviewer:
        login = args.reviewer.strip()
        # Strip a leading '@' (SHOULD_FIX 5, #1657 PR-1 review round 4):
        # left un-stripped, the bot-account and PR-author self-request
        # checks below compare against un-prefixed logins and both miss,
        # and GitHub itself 422s a "@login" reviewer request. Same idiom as
        # scripts/oversight/codeowners.py's owner-normalisation.
        login = login[1:] if login.startswith("@") else login
        source = "explicit-flag"
        codeowners_owners: list[str] = []
        codeowners_team_owners: list[str] = []
    else:
        # Deliberately unguarded here (unlike check_pr_files above, whose
        # try/except is observational per ARCH-3): a raised exception —
        # e.g. an undecodable CODEOWNERS file — falls through to main()'s
        # catch-all, which still emits exactly one JSON envelope (exit 1).
        codeowners_module = _load_codeowners_module()
        resolution = codeowners_module.resolve_human_reviewer(
            changed_files,
            ctx.repo_root,
            set(ctx.config.bot_accounts),
            ctx.config.human_reviewer,
        )
        login = (resolution.login or "").strip()
        source = resolution.source
        codeowners_owners = resolution.codeowners_owners
        codeowners_team_owners = resolution.codeowners_team_owners
        if resolution.note:
            not_verified.append(f"resolver note: {resolution.note}")

    # Step 7's fail-closed terminal checks, applied to whichever login came
    # out of resolution above OR an explicit --reviewer (§4.5: --reviewer
    # skips steps 1-6 only, never step 7).
    if not login:
        return _Outcome(
            payload={},
            exit_code=1,
            error=(
                "resolved reviewer login is empty — machine-accounts.env's "
                "HUMAN_REVIEWER must not be skipped (fail-closed if absent)"
            ),
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )
    bot_accounts_lower = {b.lower() for b in ctx.config.bot_accounts}
    if login.lower() in bot_accounts_lower or login.lower().endswith("[bot]"):
        return _Outcome(
            payload={},
            exit_code=1,
            error=(
                f"resolved reviewer {login!r} is a bot account — requesting a bot "
                "as 'the human reviewer' would look like a satisfied gate and be none"
            ),
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )
    if login.lower() == pre.author_login.lower():
        return _Outcome(
            payload={},
            exit_code=1,
            error=(
                f"resolved reviewer {login!r} is the PR author — GitHub would "
                "422 this request anyway"
            ),
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    # Step 6 — idempotency, and I2, the livelock guard. I2 is not an
    # optimisation: decide_merge_authority returns HUMAN_REQUIRED on an
    # outstanding request from human_reviewer before it ever checks for a
    # human approval, so re-requesting a reviewer who has already reviewed
    # this exact head re-adds them to requested_reviewers and flips an
    # approved PR back to HUMAN_REQUIRED every cycle, forever, with the
    # approval sitting on the PR unread.
    requested_lower = {r.lower() for r in pre.requested_reviewers}
    if login.lower() in requested_lower:
        payload = {
            **base,
            "skipped": True,
            "skip_reason": "already_requested",
            "resolved_reviewer": login,
            "resolution_source": source,
            "codeowners_owners": codeowners_owners,
            "codeowners_team_owners": codeowners_team_owners,
        }
        return _Outcome(
            payload=payload,
            exit_code=0,
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    for review in pre.reviews:
        reviewer_login = (review.get("user") or {}).get("login", "")
        if reviewer_login.lower() == login.lower() and review.get("commit_id") == pre.head_sha:
            payload = {
                **base,
                "skipped": True,
                "skip_reason": "already_reviewed_head",
                "resolved_reviewer": login,
                "resolution_source": source,
                "codeowners_owners": codeowners_owners,
                "codeowners_team_owners": codeowners_team_owners,
            }
            return _Outcome(
                payload=payload,
                exit_code=0,
                not_verified=not_verified,
                repo=pre.repo,
                pr=args.pr,
            )

    # Step 7 (of §4.4) — the write.
    try:
        github.request_reviewers(pre.owner, pre.repo_name, args.pr, [login])
    except github.GitHubError as exc:
        status = getattr(exc, "status_code", None)
        return _Outcome(
            payload={
                "resolved_reviewer": login,
                "resolution_source": source,
                "codeowners_owners": codeowners_owners,
                "codeowners_team_owners": codeowners_team_owners,
            },
            exit_code=1,
            error=f"failed to request reviewer {login!r} (status={status}): {_scrub_exc(exc)}",
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )
    except ValueError as exc:
        return _Outcome(
            payload={},
            exit_code=1,
            error=_scrub_exc(exc),
            not_verified=not_verified,
            repo=pre.repo,
            pr=args.pr,
        )

    matched_protected_paths = [
        f
        for f in changed_files
        if merge_authority.touches_protected_surface([f], str(ctx.repo_root))
    ]

    payload = {
        **base,
        "requested": True,
        "resolved_reviewer": login,
        "resolution_source": source,
        "codeowners_owners": codeowners_owners,
        "codeowners_team_owners": codeowners_team_owners,
        "matched_protected_paths": matched_protected_paths,
    }
    return _Outcome(
        payload=payload,
        exit_code=0,
        not_verified=not_verified,
        repo=pre.repo,
        pr=args.pr,
    )


_HANDLERS = {
    "submit-verdict": _cmd_submit_verdict,
    "request-reviewer": _cmd_request_reviewer,
}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
    """Parse argv, dispatch to one subcommand handler, print exactly one
    JSON record, and return the exit code. Never calls sys.exit itself.

    `repo_root` is a keyword-only, test-only injection point — `argparse`
    never defines it and the `__main__` block never populates it from
    `sys.argv`, so it is unreachable from any command line.
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
            pr=args.pr,
            app_role=args.app,
            error=_scrub_exc(exc),
        )
        print(json.dumps(record))
        return 1

    ctx = _Context(repo_root=resolved_root, config=config, app_role=args.app)
    try:
        outcome = _HANDLERS[subcommand](args, ctx)
    except Exception as exc:  # noqa: BLE001 — catch-all guarantees the
        # envelope invariant ("stdout is exactly one JSON object, always")
        # against any exception a handler doesn't itself catch, mirroring
        # the merge_config.ConfigError handling above. Handlers that need a
        # specific, narrower exit code (e.g. G5's exit 2 for an unreadable
        # --body-file) catch that exception at the call site so it never
        # reaches here.
        #
        # Finding 2 (#1657 codex adversarial-security second review,
        # CWE-200): a prior round (SHOULD_FIX H) relied on an invariant
        # comment alone — "no code path may raise an exception embedding
        # GH_TOKEN" — which is not enforcement. `_scrub_exc` below redacts
        # the shapes that matter (the live GH_TOKEN value, Authorization/
        # Bearer patterns, GitHub token-shaped prefixes) so this boundary no
        # longer depends on every future github.py/subprocess error message
        # staying clean by convention.
        record = _envelope(
            subcommand=subcommand,
            repo_root=str(resolved_root),
            pr=args.pr,
            config_source=config.config_source,
            app_role=args.app,
            error=f"unhandled {type(exc).__name__}: {_scrub_exc(exc)}",
        )
        print(json.dumps(record))
        return 1

    record = _envelope(
        subcommand=subcommand,
        repo=outcome.repo,
        repo_root=str(resolved_root),
        pr=args.pr,
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
