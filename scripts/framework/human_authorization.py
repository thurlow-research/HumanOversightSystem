"""human_authorization.py — the GitHub-native human-authorization verifier (S1 of #2101, ADR-2101).

Protected surface. Answers exactly one question: "has a verified human
CODEOWNER, from their own GitHub account, authorized THIS step's content?"
S1 ships the verifier inert: nothing calls it until S2 wires the consumers.

Rules (TECHNICAL-DESIGN-2101 §2):
  1. Purity boundary. parse_act, render_form, render_request, canonicalize_path,
     decide and fingerprint read no clock, environment, file or network.
  2. Four I/O seams, and only four, each a module attribute tests replace:
     `_run_gh_get` (all GitHub REST reads), `_run_gh_graphql` (the one fixed
     read-only deletion query, S1b), `_run_git` (all git), `_audit_write`
     (the audit subprocess). Nothing else spawns a process or opens a socket.
  3. No decision on incomplete data. `decide` runs only after every input is
     complete; any earlier failure is exit 3 with covered == [] and
     refusals == [].
  4. Nothing in a clone confers authority. CODEOWNERS and the default-branch
     bot baseline are read from the server's default branch, never from disk.
     The one local trust input is the bot DENYLIST: the local
     machine-accounts.env plus the BOT_ACCOUNTS environment variable are
     unioned into it (union-only, so they can only ADD exclusions; an absent
     local file is exit 3). No `.claudetmp/**` auth file is read. The only
     local file read besides that is the `--audit-on-change` record
     (`.claudetmp/human-authorization/audit-on-change.json`, TD §4.11); it can
     only SUPPRESS an audit write and never feeds `decide` or the exit code.
  5. Import graph. Standard library, scripts.framework.require_human_approval
     and scripts.framework.requester_trust only. No scripts.automation or
     scripts.oversight import; the audit writer is reached solely as
     `python3 -m scripts.oversight.lib.audit_log` in a subprocess argv.
  6. Only exit 0 means authorized. `covered` is non-empty only on exit 0, or
     exit 1 with the acceptance audit event written or suppressed under
     --audit-on-change; on exit 2, 3 and 4 it is [].

Binding position-soundness (TD-2101 §4.7 steps 5/5a, ruling R-A6): `git patch-id`
ignores hunk positions, so the diff is taken at the smallest context in
CONTEXT_LADDER = (3, 10, 30, 100, whole-file) at which every hunk's pre-image
is unique in its old blob. Residual R-S1-6: a later reviewed `main` change that
relocates a pre-image block verbatim lets an identical re-pointed edit carry
the binding.

Deleted-later refusal (S1b, #2151, TD-2101 §10.4, R-A8): a CODEOWNER (or
unknown-author) comment deleted at or after the governing authorize's
created_at voids that authorize (`deleted-later`), because the deleted comment
may have been a newer decline. Residuals, disclosed not mitigated:
  R-S1b-1  a CODEOWNER deleting their OWN comment is probably not recorded by
           GitHub, so their older authorize governs again (their own act).
  R-S1b-2  GraphQL completeness for deletions is measured only against REST;
           `filteredCount` is a same-source pagination-integrity check, NOT a
           completeness proof (closed before S2 by the S2-PRE-6 write test).
  R-S1b-4  the BINDING_BYTES_MAX cap is checked on bytes already captured, so
           one oversize git output is held in memory once before the refusal.
The deletion/act timestamp comparison is a string compare, sound only because
both sides fullmatch TS_RE (whole seconds, `Z`). Never relax TS_RE without
converting both sides to one canonical form first.

Minimum git: 2.42 (needs `patch-id --verbatim` and the global `--attr-source`
option). An older git rejects the option and the verifier exits 3 (git-failure).

Exit contract: 0 authorized, 1 not-authorized, 2 usage, 3 undetermined,
4 audit-failed. Any non-zero exit means "not authorized" for every item not in
`covered` (and see TD-2101 §10.1 R-A2 for the consumer-side split rule).

CLI: cd <repo> && python3 -m scripts.framework.human_authorization <subcommand>
  verify | binding | render-request
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from scripts.framework.requester_trust import (
    bot_baseline_from_env_text,
    load_bot_accounts,
    machine_accounts_file_absent,
    parse_codeowners_humans,
)
from scripts.framework.require_human_approval import is_bot_reviewer

# ---------------------------------------------------------------------------
# Constants (§4.2)
# ---------------------------------------------------------------------------

SCHEMA = "hos-human-authorization/v1"
SOURCE = "issue-comment"
PAGE_SIZE = 100
COMMENT_PAGE_BOUND = 10
DELETION_PAGE_BOUND = 10  # per source, 100 per page: 1,000 events. Not a flag.
GH_TIMEOUT_SECONDS = 30
FETCH_BUDGET_SECONDS = 120
GIT_TIMEOUT_SECONDS = 60
BINDING_BUDGET_SECONDS = 120  # whole compute_binding call; checked before each git call
BINDING_BYTES_MAX = 16 * 1024 * 1024  # per ladder patch, and cumulative old-blob bytes per call
AUDIT_TIMEOUT_SECONDS = 30
CODEOWNERS_PATH = ".github/CODEOWNERS"
MACHINE_ACCOUNTS_PATH = "scripts/framework/machine-accounts.env"
WEB_ROOT = "https://github.com"
CONSUMERS = ("evaluator", "pr-readiness", "overseer")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # pragma: allowlist secret
HOS_ROOT = Path(__file__).resolve().parents[2]
AUDIT_ON_CHANGE_RELPATH = Path(".claudetmp") / "human-authorization" / "audit-on-change.json"

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
NUM_RE = re.compile(r"^[1-9][0-9]{0,9}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REF_RE = re.compile(r"^[A-Za-z0-9._/@{}~^-]{1,255}$")
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
CURSOR_RE = re.compile(r"^[A-Za-z0-9+/=_-]{1,256}$")
KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ITEM_RE = re.compile(rf"^(?:C7|RA-FALLBACK|C10:{KEBAB}|BF:{KEBAB})$")
ITEM_MAX_LEN = 80
BINDING_RE = re.compile(r"^patch:[0-9a-f]{40}$")
FENCE_OPEN_RE = re.compile(r"^```[A-Za-z0-9_-]*$")
_HTTP_STATUS_RE = re.compile(r"HTTP (\d{3})")
_KV_RE = re.compile(r"^([a-z_]+)=(\S*)$")
_LIST_ITEM_RE = re.compile(r"^[ \t]*-[ \t]+(.*)$")
_BARE_DASH_RE = re.compile(r"^[ \t]*-[ \t]*$")
_KEYLIKE_RE = re.compile(r"^[A-Za-z_]+:")

REFUSAL_REASONS = frozenset(
    {
        "bot-actor",
        "not-codeowner",
        "edited",
        "stale",
        "wrong-step",
        "no-overlap",
        "malformed",
        "malformed-latest",
        "declined",
        "deleted-later",
        "superseded",
        "api-failure",
    }
)
PARSE_ERRORS = frozenset(
    {
        "marker-line",
        "unknown-key",
        "duplicate-key",
        "missing-field",
        "bad-step",
        "bad-binding",
        "empty-covers",
        "bad-item",
        "duplicate-item",
        "duplicate-field",
        "second-marker",
        "unexpected-line",
        "bad-path",
        "decline-extra-line",
        "unterminated-fence",
        "text-after-fence",
    }
)
ERROR_CODES = frozenset(
    {
        "api-error",
        "timeout",
        "budget-exhausted",
        "pagination-bound",
        "payload-shape",
        "default-branch-unreadable",
        "codeowners-unreadable",
        "codeowners-empty",
        "machine-accounts-unreadable",
        "bot-accounts-empty",
        "git-failure",
        "ambiguous-merge-base",
        "empty-diff",
        "patch-too-large",
        "unrepresentable-path",
        "unsupported-object-format",
    }
)

# R-A6: context widths tried in order; the last is whole-file context.
CONTEXT_LADDER = (3, 10, 30, 100, 2147483647)

GIT_PIN = [
    "-c",
    "core.quotePath=true",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "diff.algorithm=myers",
    "-c",
    "diff.noprefix=false",
    "-c",
    "diff.mnemonicPrefix=false",
    "-c",
    "diff.suppressBlankEmpty=false",
    "-c",
    "diff.relative=false",
    "-c",
    "diff.indentHeuristic=true",
]

# ADR-1928 AD-9 strings, plus the two path markers render_request must never carry.
_FORBIDDEN_RENDER = (
    "Authorization required:",
    "Release candidate SHA:",
    "hos-escalation",
    "hos-recommendation",
    "hos-proxy-decision",
    ".claudetmp/",
    "-human-authorization.md",
)

# ---------------------------------------------------------------------------
# Types (§4.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Comment:
    id: int
    url: str
    login: str
    user_type: str
    created_at: str
    updated_at: str
    body: str
    issue_number: int


@dataclass(frozen=True)
class Deletion:
    event_id: int
    deleted_at: str
    author_login: Optional[str]
    issue_number: int


@dataclass(frozen=True)
class Act:
    verb: Literal["authorize", "decline"]
    step: int
    binding: Optional[str]
    items: tuple[str, ...]
    reviewed_files: tuple[str, ...]


@dataclass(frozen=True)
class ParseError:
    code: str
    line: Optional[int] = None
    key: Optional[str] = None

    def detail_text(self) -> str:
        if self.line is not None:
            return f"{self.code}@L{self.line}"
        if self.key is not None:
            return f"{self.code}:{self.key}"
        return self.code


@dataclass(frozen=True)
class Refusal:
    comment_id: int
    url: str
    login: str
    actor_type: str
    issue_number: int
    created_at: str
    content_sha256: str
    reason: str
    detail: Optional[str]


@dataclass(frozen=True)
class Governing:
    comment_id: int
    url: str
    login: str
    actor_type: str
    issue_number: int
    created_at: str
    content_sha256: str
    decision: Literal["authorize", "decline", "malformed", "edited"]


@dataclass(frozen=True)
class Accepted:
    governing: Governing
    act: Act
    overlap: tuple[str, ...]


@dataclass(frozen=True)
class Verdict:
    authorized: bool
    covered: tuple[str, ...]
    unmet: tuple[str, ...]
    governing: Optional[Governing]
    accepted: Optional[Accepted]
    refusals: tuple[Refusal, ...]


@dataclass(frozen=True)
class Binding:
    binding: str
    base_sha: str
    head_sha: str
    merge_base: str
    diff_files: tuple[str, ...]


@dataclass(frozen=True)
class Fetched:
    default_branch: str
    codeowners_text: str
    machine_env_text: str
    comments: tuple[Comment, ...]
    deletions: tuple[Deletion, ...]


class VerifierError(Exception):
    """A fail-closed condition. `detail` is fixed-template text, never comment text."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(code, detail)
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}" if self.detail else self.code


# ---------------------------------------------------------------------------
# Paths (§4.5)
# ---------------------------------------------------------------------------

_ASCII_WS = " \t\n\r\f\v"


def canonicalize_path(raw: str) -> str:
    """TD-267 §3.1: strip ASCII whitespace, drop matching wrapping quotes, drop one leading './'."""
    p = raw.strip(_ASCII_WS)
    if len(p) >= 2 and p[0] == p[-1] and p[0] in ("'", '"'):
        p = p[1:-1]
    if p.startswith("./"):
        p = p[2:]
    return p


def is_representable_path(p: Any) -> bool:
    """True iff render-then-parse is lossless for `p` (canonicalize_path(p) == p)."""
    if not isinstance(p, str) or not p:
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in p):
        return False
    if p != p.strip():
        return False
    if len(p) >= 2 and p[0] == p[-1] and p[0] in ("'", '"'):
        return False
    if p.startswith("./"):
        return False
    return canonicalize_path(p) == p  # the contract, enforced by construction


def _valid_item(item: Any) -> bool:
    return (
        isinstance(item, str) and len(item) <= ITEM_MAX_LEN and ITEM_RE.fullmatch(item) is not None
    )


# ---------------------------------------------------------------------------
# The form: parse_act / render_form / render_request (§4.4)
# ---------------------------------------------------------------------------


def parse_act(body: str) -> "Act | ParseError | None":
    """Parse a comment body. None = not a candidate. Pure and total."""
    lines = body.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0][1:]

    def blank(ln: str) -> bool:
        return ln.strip(" \t") == ""

    n = len(lines)
    i = 0
    while i < n and blank(lines[i]):
        i += 1
    if i >= n:
        return None

    fenced = False
    if FENCE_OPEN_RE.match(lines[i].strip(" \t")):
        fenced = True
        i += 1
        while i < n and blank(lines[i]):
            i += 1
        if i >= n:
            return None

    head = lines[i].strip(" \t")
    folded = head.casefold()
    if not (folded.startswith("/hos authorize") or folded.startswith("/hos decline")):
        return None

    # Form region [i+1, k)
    k = n
    if fenced:
        k = -1
        for j in range(i + 1, n):
            if lines[j].strip(" \t") == "```":
                k = j
                break
        if k < 0:
            return ParseError("unterminated-fence", line=i + 1)
        for j in range(k + 1, n):
            if blank(lines[j]):
                continue
            if lines[j].rstrip(" \t") != "---":
                return ParseError("text-after-fence", line=j + 1)
            break
    else:
        for j in range(i + 1, n):
            if lines[j].rstrip(" \t") == "---":
                k = j
                break
    region = lines[i + 1 : k]
    region_start = i + 1  # 0-based index of region[0]

    # Marker line.
    toks = head.split()
    if len(toks) < 2 or toks[0] != "/hos" or toks[1] not in ("authorize", "decline"):
        return ParseError("marker-line")
    verb = toks[1]
    pairs: list[tuple[str, str]] = []
    for tok in toks[2:]:
        m = _KV_RE.match(tok)
        if m is None:
            return ParseError("marker-line")
        pairs.append((m.group(1), m.group(2)))
    allowed = ("step", "binding") if verb == "authorize" else ("step",)
    for key, _ in pairs:
        if key not in allowed:
            return ParseError("unknown-key")  # key text is human text: never carried
    seen: dict[str, str] = {}
    for key, val in pairs:
        if key in seen:
            return ParseError("duplicate-key", key=key)
        seen[key] = val
    for key in allowed:
        if key not in seen:
            return ParseError("missing-field", key=key)
    if NUM_RE.fullmatch(seen["step"]) is None:
        return ParseError("bad-step")
    step = int(seen["step"])
    binding: Optional[str] = None
    if verb == "authorize":
        if BINDING_RE.fullmatch(seen["binding"]) is None:
            return ParseError("bad-binding")
        binding = seen["binding"]

    if verb == "decline":
        for off, ln in enumerate(region):
            if not blank(ln):
                return ParseError("decline-extra-line", line=region_start + off + 1)
        return Act("decline", step, None, (), ())

    items: list[str] = []
    paths: list[str] = []
    have_covers = False
    have_files = False
    in_list = False
    for off, raw in enumerate(region):
        lineno = region_start + off + 1
        if blank(raw):
            continue
        s = raw.strip(" \t")
        low = s.casefold()
        if low == "/hos" or low.startswith("/hos "):
            return ParseError("second-marker", line=lineno)
        if s.startswith("covers:"):
            if have_covers:
                return ParseError("duplicate-field", key="covers")
            have_covers = True
            new_items = s[len("covers:") :].split()
            if not new_items:
                return ParseError("empty-covers", line=lineno)
            for it in new_items:
                if not _valid_item(it):
                    return ParseError("bad-item", line=lineno)
                if it in items:
                    return ParseError("duplicate-item", line=lineno)
                items.append(it)
            in_list = False
            continue
        if s.startswith("reviewed_files:"):
            if s[len("reviewed_files:") :].strip(" \t") != "":
                return ParseError("unexpected-line", line=lineno)
            if have_files:
                return ParseError("duplicate-field", key="reviewed_files")
            have_files = True
            in_list = True
            continue
        if in_list:
            m = _LIST_ITEM_RE.match(raw)
            if m is not None:
                p = canonicalize_path(m.group(1))
                if not p:
                    return ParseError("bad-path", line=lineno)
                if p not in paths:
                    paths.append(p)
                continue
            if _BARE_DASH_RE.match(raw):
                return ParseError("bad-path", line=lineno)
        if _KEYLIKE_RE.match(s):
            return ParseError("unknown-key", line=lineno)
        return ParseError("unexpected-line", line=lineno)
    if not have_covers:
        return ParseError("missing-field", key="covers")
    return Act("authorize", step, binding, tuple(items), tuple(paths))


def _check_form_inputs(step: Any, binding: Any, items: Any, diff_files: Any) -> None:
    if isinstance(step, bool) or not isinstance(step, int) or NUM_RE.fullmatch(str(step)) is None:
        raise ValueError("invalid step")
    if not isinstance(binding, str) or BINDING_RE.fullmatch(binding) is None:
        raise ValueError("invalid binding")
    items = tuple(items)
    diff_files = tuple(diff_files)
    if not items:
        raise ValueError("items must not be empty")
    if not all(_valid_item(it) for it in items):
        raise ValueError("invalid item")
    if len(set(items)) != len(items):
        raise ValueError("duplicate item")
    if not diff_files:
        raise ValueError("diff_files must not be empty")
    if not all(is_representable_path(p) for p in diff_files):
        raise ValueError("unrepresentable path")
    if len(set(diff_files)) != len(diff_files):
        raise ValueError("duplicate path")


def render_form(step: int, binding: str, items: Any, diff_files: Any) -> str:
    """The canonical authorize form (no trailing newline)."""
    _check_form_inputs(step, binding, items, diff_files)
    out = [
        f"/hos authorize step={step} binding={binding}",
        "covers: " + " ".join(items),
        "reviewed_files:",
    ]
    out.extend(f"  - {p}" for p in diff_files)
    return "\n".join(out)


def _scrub_render(text: Any) -> str:
    """Single-line the text and replace every AD-9 forbidden string."""
    one = " ".join(str(text).split("\n")).replace("\r", " ")
    for bad in _FORBIDDEN_RENDER:
        one = one.replace(bad, "[removed]")
    return one


def _sanitize_render(text: Any) -> str:
    return _scrub_render(text)[:200]


def render_request(
    step: int,
    binding: str,
    items: Any,
    diff_files: Any,
    *,
    issue_url: str,
    pr_url: Optional[str] = None,
    findings: Any = (),
    parse_error: Optional[tuple[str, str]] = None,
) -> str:
    """The human-facing action request (AD-9). Pure."""
    items = tuple(items)
    form = render_form(step, binding, items, diff_files)
    out: list[str] = [
        "### Action needed",
        "",
        "**Action:** copy only the text inside the first box below into a new comment, "
        "from your own GitHub account. Its first line must be the /hos line. Delete any "
        "reviewed_files line for a file you did not review, but keep at least one.",
        "",
        "```text",
        form,
        "```",
        "",
        "To decline instead, post:",
        "",
        "```text",
        f"/hos decline step={step}",
        "```",
    ]
    bf_items = [it for it in items if it.startswith("BF:")]
    if bf_items:
        by_id: dict[str, tuple[str, str]] = {}
        for fid, source, description in findings:
            by_id[str(fid)] = (source, description)
        out += ["", "Blocking findings this covers:"]
        for it in bf_items:
            hit = by_id.get(it) or by_id.get(it[3:])
            if hit is None:
                out.append(f"- {it} — (no description supplied)")
            else:
                out.append(f"- {it} — {_sanitize_render(hit[0])}: {_sanitize_render(hit[1])}")
    if parse_error is not None:
        url, detail = _scrub_render(parse_error[0]), _scrub_render(parse_error[1])
        out += [
            "",
            f"Your latest /hos comment ({url}) could not be read ({detail}). "
            "Post a corrected comment; the newest one counts.",
        ]
    where = f"**Where:** {_scrub_render(issue_url)}"
    if pr_url:
        where += f" (or the PR: {_scrub_render(pr_url)})"
    out += [
        "",
        "Do not edit this comment, or any later comment of yours on this issue or PR. "
        "If anything needs to change, post a new comment.",
        "",
        where,
        "",
        "**Who:** the human CODEOWNER, from your own GitHub account. "
        "The human-proxy session cannot do this.",
        "",
        "**Done when:** the next evaluator run reports the items covered.",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# decide (§4.6) — pure
# ---------------------------------------------------------------------------


def _sha(c: Comment) -> str:
    return hashlib.sha256(c.body.encode("utf-8", errors="surrogatepass")).hexdigest()


def _refusal(c: Comment, reason: str, detail: Optional[str]) -> Refusal:
    return Refusal(
        comment_id=c.id,
        url=c.url,
        login=c.login,
        actor_type=c.user_type,
        issue_number=c.issue_number,
        created_at=c.created_at,
        content_sha256=_sha(c),
        reason=reason,
        detail=detail,
    )


def _governing(c: Comment, decision: str) -> Governing:
    return Governing(
        comment_id=c.id,
        url=c.url,
        login=c.login,
        actor_type=c.user_type,
        issue_number=c.issue_number,
        created_at=c.created_at,
        content_sha256=_sha(c),
        decision=decision,  # type: ignore[arg-type]
    )


def _sorted_refusals(refusals: list[Refusal]) -> tuple[Refusal, ...]:
    return tuple(sorted(refusals, key=lambda r: (r.created_at, r.comment_id)))


def decide(
    comments: Any,
    codeowners: Any,
    bots: Any,
    step: int,
    binding: str,
    required_items: Any,
    diff_files: Any,
    *,
    deletions: Any,
) -> Verdict:
    """Decide authorization from fully-fetched inputs. Performs no I/O.

    `deletions` is required (no default) so a caller cannot silently skip the
    deleted-later check. A deletion qualifies iff its author is a CODEOWNER or
    unknown and it is at or after the governing act's created_at (string compare;
    sound because both fullmatch TS_RE). It deliberately omits the bot exclusion
    so it errs toward refusing. Residuals R-S1b-1 and R-S1b-2: see module docstring."""
    required = tuple(required_items)
    deletions = tuple(deletions)
    if not all(isinstance(d, Deletion) for d in deletions):
        raise ValueError("deletions must be Deletion records")
    # The deleted-later string compare is sound only if both sides fullmatch TS_RE.
    if not all(TS_RE.fullmatch(d.deleted_at or "") for d in deletions):
        raise ValueError("deletion timestamps must match TS_RE")
    comments = tuple(comments)
    if not all(TS_RE.fullmatch(c.created_at or "") for c in comments):
        raise ValueError("comment created_at must match TS_RE")
    if not codeowners or not all(isinstance(x, str) and x == x.lower() for x in codeowners):
        raise ValueError("codeowners must be a non-empty set of lowercased logins")
    if not bots:
        raise ValueError("bots must be non-empty")
    if (
        not required
        or len(set(required)) != len(required)
        or not all(_valid_item(i) for i in required)
    ):
        raise ValueError("required_items must be non-empty, unique and valid")
    if not isinstance(binding, str) or BINDING_RE.fullmatch(binding) is None:
        raise ValueError("invalid binding")

    def is_bot(c: Comment) -> bool:
        return bool(c.login) and is_bot_reviewer(c.login, c.user_type, bots)

    def verified(c: Comment) -> bool:
        # Exclusion first, then positive CODEOWNERS membership: never one alone.
        if c.login == "" or is_bot(c):
            return False
        return c.login.lower() in codeowners

    ordered = sorted(comments, key=lambda c: (c.created_at, c.id))
    refusals: list[Refusal] = []
    participants: list[tuple[Comment, Any, str]] = []
    for c in ordered:
        parsed = parse_act(c.body)
        cand = parsed is not None
        if not verified(c):
            if cand:
                refusals.append(_refusal(c, "bot-actor" if is_bot(c) else "not-codeowner", None))
            continue
        if c.updated_at != c.created_at:
            participants.append((c, parsed, "edited"))
            continue
        if parsed is None:
            continue
        if isinstance(parsed, ParseError):
            participants.append((c, parsed, "malformed"))
            continue
        if parsed.step != step:
            refusals.append(_refusal(c, "wrong-step", None))
            continue
        participants.append((c, parsed, "act"))

    if not participants:
        return Verdict(False, (), required, None, None, _sorted_refusals(refusals))

    for c, parsed, kind in participants[:-1]:
        if kind == "edited":
            if parsed is not None:
                refusals.append(_refusal(c, "edited", None))
        elif kind == "malformed":
            refusals.append(_refusal(c, "malformed", parsed.detail_text()))
        else:
            refusals.append(_refusal(c, "superseded", None))

    c, parsed, kind = participants[-1]
    if kind == "edited":
        refusals.append(_refusal(c, "edited", None if parsed is not None else "non-candidate"))
        gov = _governing(c, "edited")
    elif kind == "malformed":
        refusals.append(_refusal(c, "malformed-latest", parsed.detail_text()))
        gov = _governing(c, "malformed")
    elif parsed.verb == "decline":
        refusals.append(_refusal(c, "declined", None))
        gov = _governing(c, "decline")
    elif parsed.binding != binding:
        refusals.append(_refusal(c, "stale", None))
        gov = _governing(c, "authorize")
    else:
        overlap = set(parsed.reviewed_files) & set(diff_files)
        if not overlap:
            refusals.append(_refusal(c, "no-overlap", None))
            gov = _governing(c, "authorize")
        else:
            gov = _governing(c, "authorize")
            hits = sorted(
                (
                    d
                    for d in deletions
                    if (d.author_login is None or d.author_login.lower() in codeowners)
                    and d.deleted_at >= c.created_at
                ),
                key=lambda d: (d.deleted_at, d.event_id),
            )
            if hits:
                refusals.append(_refusal(c, "deleted-later", f"event:{hits[0].event_id}"))
                return Verdict(False, (), required, gov, None, _sorted_refusals(refusals))
            accepted = Accepted(gov, parsed, tuple(sorted(overlap)))
            covered = tuple(i for i in required if i in parsed.items)
            unmet = tuple(i for i in required if i not in parsed.items)
            return Verdict(not unmet, covered, unmet, gov, accepted, _sorted_refusals(refusals))
    return Verdict(False, (), required, gov, None, _sorted_refusals(refusals))


# ---------------------------------------------------------------------------
# Binding (§4.7)
# ---------------------------------------------------------------------------


def _run_git(
    repo_root: Any,
    args: list[str],
    *,
    stdin: Optional[bytes] = None,
    timeout: float = GIT_TIMEOUT_SECONDS,
) -> bytes:
    """THE git seam. Pinned argv and environment; any failure is git-failure."""
    # --no-replace-objects: refs/replace in the clone must not substitute objects for
    # the supplied head/base (CWE-345). --attr-source: see TD-2101 R-A3.
    argv = [
        "git",
        "-C",
        str(repo_root),
        "--no-replace-objects",
        f"--attr-source={EMPTY_TREE}",
        *GIT_PIN,
        *args,
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_ATTR_NOSYSTEM"] = "1"
    sub = args[0] if args else "?"
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
            input=stdin,
            stdin=None if stdin is not None else subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerifierError("git-failure", f"git {sub}") from exc
    if result.returncode != 0:
        raise VerifierError("git-failure", f"git {sub}")
    return result.stdout


def _git_budgeted(
    repo_root: Any, args: list[str], deadline: float, *, stdin: Optional[bytes] = None
) -> bytes:
    """The only caller of `_run_git`: refuses once the per-call binding deadline
    passed, and caps the call's timeout at the budget remaining (so the binding
    wall time cannot overrun BINDING_BUDGET_SECONDS by a whole call)."""
    remaining = deadline - time.monotonic()
    if remaining < 0:
        raise VerifierError("budget-exhausted", "binding budget exceeded")
    return _run_git(repo_root, args, stdin=stdin, timeout=min(GIT_TIMEOUT_SECONDS, remaining))


def _hex_or_fail(token: str) -> str:
    if SHA_RE.fullmatch(token):
        return token
    if SHA256_RE.fullmatch(token):
        raise VerifierError("unsupported-object-format", "sha256 repository")
    raise VerifierError("git-failure", "unexpected object name")


_HUNK_RE = re.compile(rb"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_ZERO_BLOB = "0" * 40


def _diff_argv(merge_base: str, head: str, context: int) -> list[str]:
    return [
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--no-renames",
        "--full-index",
        "--binary",
        "--diff-algorithm=myers",
        f"--unified={context}",
        "--inter-hunk-context=0",
        "--indent-heuristic",
        "--no-relative",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--ignore-submodules=none",
        "--submodule=short",
        "-O/dev/null",
        merge_base,
        head,
        "--",
    ]


def _occurrences(blob: bytes, pre: list[bytes]) -> int:
    """Line-aligned occurrences of `pre` in `blob`, capped at 2 (overlaps count)."""
    if not pre:
        return 1 if blob == b"" else 2
    hay = b"\n" + blob + (b"\n" if blob and not blob.endswith(b"\n") else b"")
    needle = b"\n" + b"\n".join(pre) + b"\n"
    count, pos = 0, hay.find(needle)
    while pos != -1 and count < 2:
        count += 1
        pos = hay.find(needle, pos + 1)
    return count


def _hunks_anchored(
    repo_root: Any,
    patch: bytes,
    *,
    blobs: Optional[dict[str, bytes]] = None,
    deadline: Optional[float] = None,
) -> bool:
    """True iff every text hunk's pre-image occurs exactly once in its old blob (R-A6).

    `git patch-id` drops hunk positions; a unique pre-image restores them, since
    the hunk text alone then fixes where it applies. Malformed input or a
    pre-image absent from its own old blob is git-failure (closed). `blobs` is
    the old-blob cache, shared across ladder rungs; the cumulative bytes read
    are capped at BINDING_BYTES_MAX (patch-too-large)."""

    def fail() -> VerifierError:
        return VerifierError("git-failure", "unparseable patch")

    lines = patch.split(b"\n")
    if blobs is None:
        blobs = {}
    limit = deadline if deadline is not None else float("inf")
    blob_bytes = sum(len(b) for b in blobs.values())
    n = len(lines)
    i = 0
    while i < n:
        if not lines[i].startswith(b"diff --git "):
            i += 1
            continue
        j = i + 1
        while j < n and not lines[j].startswith(b"diff --git "):
            j += 1
        section = lines[i:j]
        i = j
        header: list[bytes] = []
        for ln in section[1:]:
            if _HUNK_RE.match(ln) or ln.startswith(b"GIT binary patch"):
                break
            header.append(ln)
        if any(ln.endswith(b" 160000") for ln in header):
            continue  # gitlink: one "Subproject commit" line, no position
        old_id = None
        for ln in header:
            if ln.startswith(b"index "):
                toks = ln.split()
                old_id = (
                    toks[1].split(b"..")[0].decode("ascii", errors="replace")
                    if len(toks) > 1
                    else ""
                )
                break
        k = 1 + len(header)
        while k < len(section):
            m = _HUNK_RE.match(section[k])
            if section[k].startswith(b"GIT binary patch"):
                break
            if not m:
                k += 1
                continue
            if old_id is None or not SHA_RE.fullmatch(old_id):
                raise fail()
            want_pre = int(m.group(1)) if m.group(1) is not None else 1
            want_post = int(m.group(2)) if m.group(2) is not None else 1
            pre: list[bytes] = []
            seen_pre = seen_post = 0
            k += 1
            while seen_pre < want_pre or seen_post < want_post:
                if k >= len(section):
                    raise fail()
                body = section[k]
                k += 1
                tag = body[:1]
                if tag in (b" ", b"-"):
                    pre.append(body[1:])
                    seen_pre += 1
                    if tag == b" ":
                        seen_post += 1
                elif tag == b"+":
                    seen_post += 1
                elif tag == b"\\":
                    continue
                else:
                    raise fail()
            if old_id not in blobs:
                blobs[old_id] = (
                    b""
                    if old_id == _ZERO_BLOB
                    else _git_budgeted(repo_root, ["cat-file", "blob", old_id], limit)
                )
                blob_bytes += len(blobs[old_id])
                if blob_bytes > BINDING_BYTES_MAX:
                    raise VerifierError("patch-too-large", "old blobs exceed size cap")
            count = _occurrences(blobs[old_id], pre)
            if count == 0:
                raise fail()
            if count > 1:
                return False
    return True


def _anchored_patch(repo_root: Any, merge_base: str, head: str, *, deadline: float) -> bytes:
    """The step's patch at the smallest context rung whose hunks are all anchored."""
    blobs: dict[str, bytes] = {}  # one cache for every rung: a blob is read at most once
    for context in CONTEXT_LADDER:
        patch = _git_budgeted(repo_root, _diff_argv(merge_base, head, context), deadline)
        if patch == b"":
            raise VerifierError("empty-diff", "step diff is empty")
        if len(patch) > BINDING_BYTES_MAX:
            raise VerifierError("patch-too-large", "ladder patch exceeds size cap")
        if _hunks_anchored(repo_root, patch, blobs=blobs, deadline=deadline):
            return patch
    raise VerifierError("git-failure", "no context rung anchors every hunk")


def compute_binding(repo_root: Any, base: str, head: str) -> Binding:
    """patch-id of the step's diff (merge-base..head), plus its sorted file list."""
    deadline = time.monotonic() + BINDING_BUDGET_SECONDS
    if not isinstance(head, str) or SHA_RE.fullmatch(head) is None:
        raise ValueError("head must be 40 lowercase hex")
    if not isinstance(base, str) or REF_RE.fullmatch(base) is None or base.startswith("-"):
        raise ValueError("invalid base ref")
    base_sha = _hex_or_fail(
        _git_budgeted(
            repo_root,
            ["rev-parse", "--verify", "--quiet", "--end-of-options", base + "^{commit}"],
            deadline,
        )
        .decode("utf-8", errors="replace")
        .strip()
    )
    _git_budgeted(repo_root, ["cat-file", "-e", "--end-of-options", head + "^{commit}"], deadline)
    mbs = _git_budgeted(repo_root, ["merge-base", "--all", base_sha, head], deadline).split()
    if not mbs:
        raise VerifierError("git-failure", "git merge-base")
    if len(mbs) > 1:
        raise VerifierError("ambiguous-merge-base", "multiple merge bases")
    merge_base = _hex_or_fail(mbs[0].decode("ascii", errors="replace"))
    patch = _anchored_patch(repo_root, merge_base, head, deadline=deadline)
    out = _git_budgeted(repo_root, ["patch-id", "--verbatim"], deadline, stdin=patch).split()
    if not out:
        raise VerifierError("git-failure", "git patch-id")
    token = _hex_or_fail(out[0].decode("ascii", errors="replace"))
    names = _git_budgeted(
        repo_root,
        [
            "diff",
            "--no-ext-diff",
            "--no-renames",
            "--name-only",
            "-z",
            "--no-relative",
            "--ignore-submodules=none",
            merge_base,
            head,
            "--",
        ],
        deadline,
    ).split(b"\0")
    paths: set[str] = set()
    for raw in names:
        if raw == b"":
            continue
        try:
            p = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise VerifierError("unrepresentable-path", "non-UTF-8 path") from exc
        if not is_representable_path(p):
            raise VerifierError("unrepresentable-path", "path cannot be represented in the form")
        paths.add(p)
    if not paths:
        raise VerifierError("empty-diff", "step diff lists no files")
    return Binding("patch:" + token, base_sha, head, merge_base, tuple(sorted(paths)))


# ---------------------------------------------------------------------------
# Fetcher (§4.8)
# ---------------------------------------------------------------------------


def _diag(message: str) -> None:
    print(f"human_authorization: {message}", file=sys.stderr)


def _run_gh_get(endpoint: str, timeout: float = GH_TIMEOUT_SECONDS) -> Any:
    """THE GitHub seam: exactly one `gh api <endpoint>` GET, parsed JSON.

    No --paginate, no -f/-F/--method/--input. The return code is checked before
    any parse (a 404 prints error JSON to stdout AND exits 1)."""
    try:
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise VerifierError("timeout", "gh api timed out") from exc
    except UnicodeDecodeError as exc:
        raise VerifierError("payload-shape", "gh api output is not valid text") from exc
    except OSError as exc:
        raise VerifierError("api-error", "gh could not be run") from exc
    if result.returncode != 0:
        # Never echo gh's stderr: it can carry repo or account text. Status only.
        http = _HTTP_STATUS_RE.search(result.stderr or "")
        _diag(f"gh api exit={result.returncode}" + (f" HTTP {http.group(1)}" if http else ""))
        raise VerifierError("api-error", f"gh api exit {result.returncode}")
    try:
        return json.loads(result.stdout)
    except (ValueError, RecursionError) as exc:
        raise VerifierError("payload-shape", "gh api returned invalid JSON") from exc


# TD-2101 §10.4.3: the one fixed, read-only query. Use filteredCount, never
# totalCount (totalCount ignores itemTypes). Byte-pinned by T-F-21.
DELETIONS_QUERY = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {
        number
        timelineItems(itemTypes: [COMMENT_DELETED_EVENT], first: 100, after: $after) {
          filteredCount
          pageInfo { hasNextPage endCursor }
          nodes { __typename ... on CommentDeletedEvent { databaseId createdAt deletedCommentAuthor { login } } }
        }
      }
      ... on PullRequest {
        number
        timelineItems(itemTypes: [COMMENT_DELETED_EVENT], first: 100, after: $after) {
          filteredCount
          pageInfo { hasNextPage endCursor }
          nodes { __typename ... on CommentDeletedEvent { databaseId createdAt deletedCommentAuthor { login } } }
        }
      }
    }
  }
}"""


def _run_gh_graphql(
    owner: str,
    name: str,
    number: int,
    after: Optional[str],
    timeout: float = GH_TIMEOUT_SECONDS,
) -> Any:
    """THE GraphQL seam: exactly one `gh api graphql` call running DELETIONS_QUERY.

    Every string goes through -f (raw string); `number` is the only -F value and
    is already NUM_RE-valid. Same timeout, stdin, return-code-before-parse and
    no-stderr-echo rules as `_run_gh_get`; a GraphQL error makes gh exit 1."""
    argv = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={DELETIONS_QUERY}",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={number}",
    ]
    if after is not None:
        argv += ["-f", f"after={after}"]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise VerifierError("timeout", "gh api timed out") from exc
    except UnicodeDecodeError as exc:
        raise VerifierError("payload-shape", "gh api output is not valid text") from exc
    except OSError as exc:
        raise VerifierError("api-error", "gh could not be run") from exc
    if result.returncode != 0:
        http = _HTTP_STATUS_RE.search(result.stderr or "")
        _diag(f"gh api exit={result.returncode}" + (f" HTTP {http.group(1)}" if http else ""))
        raise VerifierError("api-error", f"gh api exit {result.returncode}")
    try:
        return json.loads(result.stdout)
    except (ValueError, RecursionError) as exc:
        raise VerifierError("payload-shape", "gh api returned invalid JSON") from exc


def _deletion_page(
    resp: Any, number: int
) -> tuple[int, bool, Optional[str], list[tuple[int, str, Optional[str]]]]:
    """Validate one DELETIONS_QUERY page: (filteredCount, hasNextPage, endCursor, nodes)."""

    def bad(detail: str) -> VerifierError:
        return VerifierError("payload-shape", detail)

    if not isinstance(resp, dict) or "errors" in resp:
        raise bad("deletion response is not a clean object")
    node: Any = resp
    for key in ("data", "repository", "issueOrPullRequest"):
        node = node.get(key) if isinstance(node, dict) else None
    if not isinstance(node, dict):
        raise bad("deletion target missing")
    if node.get("__typename") not in ("Issue", "PullRequest"):
        raise bad("deletion target type")
    num = node.get("number")
    if isinstance(num, bool) or not isinstance(num, int) or num != number:
        raise bad("deletion target number")
    conn = node.get("timelineItems")
    if not isinstance(conn, dict):
        raise bad("deletion connection missing")
    count = conn.get("filteredCount")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise bad("deletion filteredCount")
    info = conn.get("pageInfo")
    if not isinstance(info, dict):
        raise bad("deletion pageInfo")
    has_next, cursor = info.get("hasNextPage"), info.get("endCursor")
    if not isinstance(has_next, bool) or not (cursor is None or isinstance(cursor, str)):
        raise bad("deletion pageInfo")
    if has_next and (cursor is None or CURSOR_RE.fullmatch(cursor) is None):
        raise bad("deletion cursor")
    raw_nodes = conn.get("nodes")
    if not isinstance(raw_nodes, list):
        raise bad("deletion nodes")
    nodes: list[tuple[int, str, Optional[str]]] = []
    for n in raw_nodes:
        if not isinstance(n, dict) or n.get("__typename") != "CommentDeletedEvent":
            raise bad("deletion node")
        did, created = n.get("databaseId"), n.get("createdAt")
        if isinstance(did, bool) or not isinstance(did, int) or did <= 0:
            raise bad("deletion id")
        if not isinstance(created, str) or TS_RE.fullmatch(created) is None:
            raise bad("deletion time")
        author = n.get("deletedCommentAuthor")
        login: Optional[str]
        if author is None:
            login = None
        elif isinstance(author, dict) and isinstance(author.get("login"), str) and author["login"]:
            login = author["login"]
        else:
            raise bad("deletion author")
        nodes.append((did, created, login))
    return count, has_next, cursor, nodes


def _comment_from(obj: Any, issue_number: int) -> Comment:
    def bad() -> VerifierError:
        return VerifierError("payload-shape", "malformed comment record")

    if not isinstance(obj, dict):
        raise bad()
    cid = obj.get("id")
    if isinstance(cid, bool) or not isinstance(cid, int) or cid <= 0:
        raise bad()
    url, body = obj.get("html_url"), obj.get("body")
    created, updated = obj.get("created_at"), obj.get("updated_at")
    if not isinstance(url, str) or not isinstance(body, str):
        raise bad()
    if not (
        isinstance(created, str)
        and TS_RE.fullmatch(created)
        and isinstance(updated, str)
        and TS_RE.fullmatch(updated)
    ):
        raise bad()
    user = obj.get("user")
    login, utype = "", ""
    if user is not None:
        if not isinstance(user, dict):
            raise bad()
        login = user.get("login", "")
        utype = user.get("type", "")
        if not isinstance(login, str) or not isinstance(utype, str):
            raise bad()
    return Comment(cid, url, login, utype, created, updated, body, issue_number)


def _file_text(raw: Any) -> str:
    if not isinstance(raw, dict) or raw.get("type") != "file" or raw.get("encoding") != "base64":
        raise ValueError("not a base64 file")
    content = raw.get("content")
    if not isinstance(content, str):
        raise ValueError("no content")
    try:
        return base64.b64decode(content.replace("\n", ""), validate=False).decode(
            "utf-8", errors="strict"
        )
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("undecodable") from exc


def fetch(repo: str, issue: int, pr: Optional[int]) -> Fetched:
    """Read every input the decision needs; raise VerifierError on any gap."""
    deadline = time.monotonic() + FETCH_BUDGET_SECONDS

    def check_deadline() -> None:
        if time.monotonic() > deadline:
            raise VerifierError("budget-exhausted", "fetch budget exceeded")

    def call_timeout() -> float:
        """Per-gh-call timeout: GH_TIMEOUT_SECONDS capped at the budget left."""
        return min(GH_TIMEOUT_SECONDS, max(0.0, deadline - time.monotonic()))

    def get(endpoint: str) -> Any:
        check_deadline()
        return _run_gh_get(endpoint, timeout=call_timeout())

    meta = get(f"repos/{repo}")
    branch = meta.get("default_branch") if isinstance(meta, dict) else None
    if not isinstance(branch, str) or not branch:
        raise VerifierError("default-branch-unreadable", "no default branch in repository metadata")
    # refs/heads/ so a same-named tag cannot shadow the default branch (CWE-345).
    ref = urllib.parse.quote(f"refs/heads/{branch}", safe="")

    def read_file(contents_path: str, code: str) -> str:
        try:
            return _file_text(get(f"repos/{repo}/{contents_path}?ref={ref}"))
        except VerifierError as exc:
            if exc.code in ("timeout", "budget-exhausted"):
                raise
            raise VerifierError(code, "default-branch file unreadable") from exc
        except ValueError as exc:
            raise VerifierError(code, "default-branch file undecodable") from exc

    codeowners_text = read_file(f"contents/{CODEOWNERS_PATH}", "codeowners-unreadable")
    machine_env_text = read_file(f"contents/{MACHINE_ACCOUNTS_PATH}", "machine-accounts-unreadable")

    comments: list[Comment] = []
    seen: set[int] = set()
    for number in (issue,) if pr is None else (issue, pr):
        for page in range(1, COMMENT_PAGE_BOUND + 1):
            batch = get(f"repos/{repo}/issues/{number}/comments?per_page={PAGE_SIZE}&page={page}")
            if not isinstance(batch, list):
                raise VerifierError("payload-shape", "comment page is not a list")
            for obj in batch:
                c = _comment_from(obj, number)
                if c.id in seen:
                    raise VerifierError("payload-shape", "duplicate comment id")
                seen.add(c.id)
                comments.append(c)
            if len(batch) < PAGE_SIZE:
                break
        else:
            raise VerifierError("pagination-bound", "comment pages exceed the bound")

    # Read 6 runs AFTER every comment read (load-bearing): a comment absent from
    # the comment read was deleted before the deletion read began, so its event
    # is in the deletion read. Do not reorder or parallelize.
    owner, name = repo.split("/", 1)
    deletions: list[Deletion] = []
    seen_events: set[int] = set()
    for number in (issue,) if pr is None else (issue, pr):
        after: Optional[str] = None
        collected = 0
        first_count: Optional[int] = None
        for _page in range(1, DELETION_PAGE_BOUND + 1):
            check_deadline()
            count, has_next, cursor, nodes = _deletion_page(
                _run_gh_graphql(owner, name, number, after, timeout=call_timeout()), number
            )
            if first_count is None:
                first_count = count
            elif count != first_count:
                raise VerifierError("payload-shape", "deletion count moved during the read")
            for did, created, login in nodes:
                if did in seen_events:
                    raise VerifierError("payload-shape", "duplicate deletion event id")
                seen_events.add(did)
                deletions.append(Deletion(did, created, login, number))
            collected += len(nodes)
            if not has_next:
                break
            after = cursor
        else:
            raise VerifierError("pagination-bound", "deletion pages exceed the bound")
        if collected != first_count:
            raise VerifierError("payload-shape", "deletion count does not match filteredCount")
    return Fetched(branch, codeowners_text, machine_env_text, tuple(comments), tuple(deletions))


# ---------------------------------------------------------------------------
# Audit (§4.10, §4.11)
# ---------------------------------------------------------------------------


def _audit_write(event: dict, audit_root: Path) -> bool:
    """THE audit seam: one write via the audit_log CLI (never imported)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.oversight.lib.audit_log", "write", str(audit_root)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            cwd=str(HOS_ROOT),
            timeout=AUDIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def fingerprint(
    exit_code_before_audit: int,
    covered: Any,
    unmet: Any,
    act_id: Optional[int],
    act_decision: Optional[str],
    refusals: Any,
    error_code: Optional[str],
) -> str:
    """sha256 of the canonical JSON of the verdict's audit-relevant shape. Pure."""
    obj = {
        "exit_code_before_audit": exit_code_before_audit,
        "covered": list(covered),
        "unmet": list(unmet),
        "act_id": act_id,
        "act_decision": act_decision,
        "refusals": [list(r) for r in refusals],
        "error_code": error_code,
    }
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_record(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(data, dict)
        or data.get("v") != 1
        or not isinstance(data.get("entries"), dict)
    ):
        return {}
    return {k: v for k, v in data["entries"].items() if isinstance(k, str) and isinstance(v, str)}


def _store_record(path: Path, entries: dict[str, str]) -> bool:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"v": 1, "entries": entries}, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # noqa: D102 - argparse hook
        raise _Usage("bad arguments")


def _build_parser() -> _Parser:
    p = _Parser(prog="human_authorization", add_help=False)
    sub = p.add_subparsers(dest="cmd", parser_class=_Parser)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--repo-root", default=".")

    v = sub.add_parser("verify", add_help=False)
    common(v)
    v.add_argument("--repo", required=True)
    v.add_argument("--step", required=True)
    v.add_argument("--issue", required=True)
    v.add_argument("--pr")
    v.add_argument("--base", required=True)
    v.add_argument("--head", required=True)
    v.add_argument("--require", action="append", required=True)
    v.add_argument("--consumer", required=True)
    v.add_argument("--audit-on-change", action="store_true")
    v.add_argument("--audit-root")
    v.add_argument("--json", action="store_true")

    b = sub.add_parser("binding", add_help=False)
    common(b)
    b.add_argument("--base", required=True)
    b.add_argument("--head", required=True)
    b.add_argument("--json", action="store_true")

    r = sub.add_parser("render-request", add_help=False)
    common(r)
    r.add_argument("--repo", required=True)
    r.add_argument("--step", required=True)
    r.add_argument("--issue", required=True)
    r.add_argument("--pr")
    r.add_argument("--base", required=True)
    r.add_argument("--head", required=True)
    r.add_argument("--require", action="append", required=True)
    r.add_argument("--findings-file")
    r.add_argument("--verdict-file")
    return p


def _check_common(ns: argparse.Namespace) -> None:
    if not SHA_RE.fullmatch(ns.head):
        raise _Usage("head must be 40 lowercase hex")
    if not REF_RE.fullmatch(ns.base) or ns.base.startswith("-"):
        raise _Usage("invalid base ref")
    if getattr(ns, "repo", None) is not None and not REPO_RE.fullmatch(ns.repo):
        raise _Usage("invalid repo")
    for attr in ("step", "issue", "pr"):
        val = getattr(ns, attr, None)
        if val is not None and not NUM_RE.fullmatch(val):
            raise _Usage(f"invalid {attr}")


def _parse_required(raw: list[str]) -> tuple[str, ...]:
    items: list[str] = []
    for chunk in raw:
        for it in chunk.split(","):
            if not _valid_item(it):
                raise _Usage("invalid --require item")
            if it not in items:
                items.append(it)
    if not items:
        raise _Usage("--require must not be empty")
    return tuple(items)


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _act_json(g: Optional[Governing]) -> Optional[dict]:
    if g is None:
        return None
    return {
        "id": g.comment_id,
        "url": g.url,
        "login": g.login,
        "type": g.actor_type,
        "created_at": g.created_at,
        "content_sha256": g.content_sha256,
        "decision": g.decision,
        "issue_number": g.issue_number,
    }


def _refusal_json(r: Refusal) -> dict:
    return {
        "id": r.comment_id,
        "url": r.url,
        "login": r.login,
        "actor_type": r.actor_type,
        "issue_number": r.issue_number,
        "reason": r.reason,
        "detail": r.detail,
    }


def _verify(ns: argparse.Namespace) -> int:
    required = _parse_required(ns.require)
    if ns.consumer not in CONSUMERS:
        raise _Usage("invalid --consumer")
    if ns.audit_on_change and ns.consumer != "overseer":
        raise _Usage("--audit-on-change requires --consumer overseer")
    if ns.pr is not None and ns.pr == ns.issue:
        raise _Usage("--pr must differ from --issue")
    step, issue = int(ns.step), int(ns.issue)
    pr = int(ns.pr) if ns.pr is not None else None
    repo_root = Path(ns.repo_root).resolve()
    audit_root = Path(ns.audit_root).resolve() if ns.audit_root else repo_root

    verification_id = uuid.uuid4().hex
    verified_at = _now_utc()

    b: Optional[Binding] = None
    verdict: Optional[Verdict] = None
    error: Optional[VerifierError] = None
    try:
        b = compute_binding(repo_root, ns.base, ns.head)
        f = fetch(ns.repo, issue, pr)
        if machine_accounts_file_absent(str(repo_root)):
            raise VerifierError(
                "machine-accounts-unreadable", "local machine-accounts.env is absent"
            )
        try:
            local = load_bot_accounts(str(repo_root))
        except (OSError, UnicodeDecodeError) as exc:
            raise VerifierError(
                "machine-accounts-unreadable", "local machine-accounts.env is unreadable"
            ) from exc
        bots = set(local) | bot_baseline_from_env_text(f.machine_env_text)
        if not bots:
            raise VerifierError("bot-accounts-empty", "bot set is empty")
        codeowners = parse_codeowners_humans(f.codeowners_text)
        if not codeowners:
            raise VerifierError("codeowners-empty", "no individual human code owners")
        verdict = decide(
            f.comments,
            frozenset(codeowners),
            frozenset(bots),
            step,
            b.binding,
            required,
            b.diff_files,
            deletions=f.deletions,
        )
    except VerifierError as exc:
        error = exc
    except Exception as exc:  # noqa: BLE001 - fail closed: never let a bug read as exit 1
        _diag(f"internal-error type={type(exc).__name__}")
        error = VerifierError("api-error", "unexpected internal error")

    common = {
        "timestamp": verified_at,
        "verified_at": verified_at,
        "verification_id": verification_id,
        "consumer": ns.consumer,
        "repo": ns.repo,
        "step": step,
        "issue": issue,
        "pr": pr,
        "source": SOURCE,
        "binding": b.binding if b else None,
        "head_sha": ns.head,
        "base_sha": b.base_sha if b else None,
        "merge_base": b.merge_base if b else None,
    }

    events: list[tuple[str, int, dict, bool]] = []
    if error is not None:
        pre_exit = 3
        events.append(
            (
                verified_at,
                0,
                {
                    "event": "human-authorization-refused",
                    **common,
                    "reason": "api-failure",
                    "detail": error.code,
                },
                False,
            )
        )
        fp = fingerprint(3, (), required, None, None, (), error.code)
    else:
        assert verdict is not None
        pre_exit = 0 if verdict.authorized else 1
        for r in verdict.refusals:
            events.append(
                (
                    r.created_at,
                    r.comment_id,
                    {
                        "event": "human-authorization-refused",
                        **common,
                        "comment_id": r.comment_id,
                        "url": r.url,
                        "comment_issue": r.issue_number,
                        "login": r.login,
                        "actor_type": r.actor_type,
                        "content_sha256": r.content_sha256,
                        "reason": r.reason,
                        "detail": r.detail,
                    },
                    False,
                )
            )
        if verdict.accepted is not None:
            g, act = verdict.accepted.governing, verdict.accepted.act
            events.append(
                (
                    g.created_at,
                    g.comment_id,
                    {
                        "event": "human-authorization",
                        **common,
                        "artifact": g.url,
                        "authorized_by": g.login,
                        "content_sha256": g.content_sha256,
                        "decision": "authorize",
                        "comment_id": g.comment_id,
                        "url": g.url,
                        "comment_issue": g.issue_number,
                        "actor_type": g.actor_type,
                        "covered": list(verdict.covered),
                        "unmet": list(verdict.unmet),
                        "reviewed_files": list(act.reviewed_files),
                        "overlap": list(verdict.accepted.overlap),
                    },
                    True,
                )
            )
        fp = fingerprint(
            pre_exit,
            verdict.covered,
            verdict.unmet,
            verdict.governing.comment_id if verdict.governing else None,
            verdict.governing.decision if verdict.governing else None,
            [(r.comment_id, r.reason, r.detail) for r in verdict.refusals],
            None,
        )
    events.sort(key=lambda e: (e[0], e[1]))

    record_path = repo_root / AUDIT_ON_CHANGE_RELPATH
    record_key = f"{ns.repo}#{step}#{b.binding if b else 'none'}"
    suppressed = False
    entries: dict[str, str] = {}
    if ns.audit_on_change:
        entries = _load_record(record_path)
        suppressed = entries.get(record_key) == fp

    written = failed = 0
    acceptance_failed = False
    refusal_writes_abandoned = False
    if not suppressed:
        for _, _, event, is_acceptance in events:
            if refusal_writes_abandoned and not is_acceptance:
                failed += 1  # not written: counted so the on-change record is not updated
                continue
            if _audit_write(event, audit_root):
                written += 1
            else:
                failed += 1
                acceptance_failed = acceptance_failed or is_acceptance
                refusal_writes_abandoned = refusal_writes_abandoned or not is_acceptance
                cid = event.get("comment_id")
                _diag(
                    f"WARN audit-write-failed event={event['event']} comment_id={cid if cid is not None else 'none'}"
                )
        if ns.audit_on_change and failed == 0:
            entries[record_key] = fp
            if not _store_record(record_path, entries):
                _diag("WARN audit-on-change-record-not-updated")

    if error is not None:
        exit_code, name = 3, "undetermined"
        covered: tuple[str, ...] = ()
        unmet = required
        _diag(f"error code={error.code} detail={error.detail}")
    else:
        assert verdict is not None
        if acceptance_failed:
            exit_code, name = 4, "audit-failed"
            covered, unmet = (), required
        else:
            exit_code = pre_exit
            name = "authorized" if exit_code == 0 else "not-authorized"
            covered, unmet = verdict.covered, verdict.unmet

    refusal_list = list(verdict.refusals) if (verdict is not None and error is None) else []
    out = {
        "schema": SCHEMA,
        "verdict": name,
        "exit_code": exit_code,
        "verification_id": verification_id,
        "verified_at": verified_at,
        "consumer": ns.consumer,
        "repo": ns.repo,
        "step": step,
        "issue": issue,
        "pr": pr,
        "base": ns.base,
        "base_sha": b.base_sha if b else None,
        "head": ns.head,
        "merge_base": b.merge_base if b else None,
        "binding": b.binding if b else None,
        "required": list(required),
        "covered": list(covered),
        "unmet": list(unmet),
        "act": _act_json(verdict.governing) if (verdict is not None and error is None) else None,
        "overlap": (
            list(verdict.accepted.overlap) if (verdict is not None and verdict.accepted) else []
        ),
        "refusals": [_refusal_json(r) for r in refusal_list],
        "error": {"code": error.code, "detail": error.detail} if error is not None else None,
        "audit": {"written": written, "failed": failed, "suppressed": suppressed},
    }
    if ns.json:
        print(json.dumps(out, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"human_authorization: verdict={name} step={step} binding={out['binding'] or 'none'} "
            f"covered={','.join(covered) or '-'} unmet={','.join(unmet) or '-'} "
            f"refusals={len(refusal_list)} error={error.code if error else 'none'}"
        )
    return exit_code


def _binding_cmd(ns: argparse.Namespace) -> int:
    _check_common(ns)
    try:
        b = compute_binding(Path(ns.repo_root).resolve(), ns.base, ns.head)
    except VerifierError as exc:
        _diag(f"error code={exc.code} detail={exc.detail}")
        return 3
    if ns.json:
        print(
            json.dumps(
                {
                    "binding": b.binding,
                    "base_sha": b.base_sha,
                    "head": b.head_sha,
                    "merge_base": b.merge_base,
                    "diff_files": list(b.diff_files),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(b.binding)
    return 0


def _load_json_file(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Usage("unreadable input file") from exc


def _render_cmd(ns: argparse.Namespace) -> int:
    required = _parse_required(ns.require)
    if ns.pr is not None and ns.pr == ns.issue:
        raise _Usage("--pr must differ from --issue")
    findings: list[tuple[str, str, str]] = []
    if ns.findings_file:
        data = _load_json_file(ns.findings_file)
        if not isinstance(data, list):
            raise _Usage("findings file must be a list")
        for obj in data:
            if not isinstance(obj, dict) or not all(
                isinstance(obj.get(k), str) for k in ("id", "source", "description")
            ):
                raise _Usage("findings entries must carry string id, source, description")
            findings.append((obj["id"], obj["source"], obj["description"]))
    parse_error: Optional[tuple[str, str]] = None
    if ns.verdict_file:
        data = _load_json_file(ns.verdict_file)
        if not isinstance(data, dict) or not isinstance(data.get("refusals"), list):
            raise _Usage("verdict file must be a verify --json object")
        for r in data["refusals"]:
            if not isinstance(r, dict):
                raise _Usage("verdict refusals must be objects")
            if r.get("reason") == "malformed-latest":
                url, detail = r.get("url"), r.get("detail")
                if not isinstance(url, str) or not isinstance(detail, str):
                    raise _Usage("malformed-latest entry needs string url and detail")
                parse_error = (url, detail)
    try:
        b = compute_binding(Path(ns.repo_root).resolve(), ns.base, ns.head)
    except VerifierError as exc:
        _diag(f"error code={exc.code} detail={exc.detail}")
        return 3
    issue_url = f"{WEB_ROOT}/{ns.repo}/issues/{ns.issue}"
    pr_url = f"{WEB_ROOT}/{ns.repo}/pull/{ns.pr}" if ns.pr is not None else None
    try:
        text = render_request(
            int(ns.step),
            b.binding,
            required,
            b.diff_files,
            issue_url=issue_url,
            pr_url=pr_url,
            findings=tuple(findings),
            parse_error=parse_error,
        )
    except ValueError as exc:
        raise _Usage("cannot render") from exc
    print(text)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        ns = _build_parser().parse_args(args)
        if ns.cmd is None:
            raise _Usage("missing subcommand")
        _check_common(ns)
        if ns.cmd == "verify":
            return _verify(ns)
        if ns.cmd == "binding":
            return _binding_cmd(ns)
        return _render_cmd(ns)
    except _Usage as exc:
        print(f"human_authorization: usage: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - last resort: undetermined, never a decision
        _diag(f"internal-error type={type(exc).__name__}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
