"""
review_events.py — the single PR-review event vocabulary (#1699).

Shared by the READER (scripts/oversight/check_pr_reviewed.sh, the #1524
idempotency precheck) and the WRITER (scripts/oversight/write_pr_review_event.sh).
Before this module overseer cycles hand-composed `audit_write_event` JSON, so the
event name was free text and drifted (`pr-reviewed`, `pr-review-skipped-idempotent`)
out of the reader's closed set: a review record existed yet the precheck said
`already_reviewed: false`.

  - WRITABLE_REVIEW_EVENTS: the only names the writer emits.
  - CANONICAL_REVIEW_EVENTS: every canonical name the reader recognizes. It adds
    `human-required`, which carries SPEC-378 fields (`reason_category`,
    `summary`) this writer does not model; it stays on `audit_write_event`, so
    the writer refuses it rather than offer a second write path.
  - LEGACY_ALIASES: historical spellings written before this writer existed.
    READ-ONLY: the reader matches them, the writer refuses them.
  - REVIEWED_EVENTS: canonical plus legacy names, used by the reader.

`propose-only-review-skipped` is deliberately EXCLUDED: it records a skip, not a
review of that head SHA. The precheck is corroborating evidence only (the
overseer's comment-based precheck stays authoritative), so a miss costs a
re-check, never a silent suppression.

CLI:
    python3 -m scripts.oversight.lib.review_events write --pr N --head-sha SHA
        --event NAME [--decision S] [--tier S] [--comment-url URL] [--reason S]
        [--root DIR]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone

from scripts.oversight.lib.audit_log import write_event

WRITABLE_REVIEW_EVENTS = frozenset({"pr-review", "idempotent-skip"})

CANONICAL_REVIEW_EVENTS = WRITABLE_REVIEW_EVENTS | {"human-required"}

LEGACY_ALIASES = {
    "pr-reviewed": "pr-review",
    "pr-review-skipped-idempotent": "idempotent-skip",
}

REVIEWED_EVENTS = CANONICAL_REVIEW_EVENTS | frozenset(LEGACY_ALIASES)

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_OPTIONAL_FIELDS = ("decision", "tier", "comment_url", "reason")


def _fail(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review_events")
    sub = parser.add_subparsers(dest="cmd")
    w = sub.add_parser("write", help="write one PR-review audit record")
    w.add_argument("--pr", required=True)
    w.add_argument("--head-sha", required=True)
    w.add_argument("--event", required=True)
    w.add_argument("--decision")
    w.add_argument("--tier")
    w.add_argument("--comment-url")
    w.add_argument("--reason")
    w.add_argument("--root", default=".")
    return parser


def _main(argv: list[str]) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed its message
        return 2 if exc.code else 0
    if args.cmd != "write":
        return _fail("usage: review_events write --pr N --head-sha SHA --event NAME [...]")

    if args.event in LEGACY_ALIASES:
        return _fail(f"legacy alias '{args.event}'; write '{LEGACY_ALIASES[args.event]}' instead")
    if args.event == "human-required":
        return _fail(
            "'human-required' carries SPEC-378 fields; write it with "
            "audit_write_event (see overseer.md § Halt-on-failure ordering)"
        )
    if args.event not in WRITABLE_REVIEW_EVENTS:
        return _fail(
            f"unknown event '{args.event}'; allowed: " + ", ".join(sorted(WRITABLE_REVIEW_EVENTS))
        )
    if not (args.pr.isascii() and args.pr.isdigit() and int(args.pr) > 0):
        return _fail(f"--pr must be a positive integer, got: {args.pr}")
    if not _SHA_RE.fullmatch(args.head_sha):
        return _fail("--head-sha must be 40 lowercase hex characters")

    event: dict = {
        "event": args.event,
        "pr": int(args.pr),
        "head_sha": args.head_sha,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for field in _OPTIONAL_FIELDS:
        value = getattr(args, field)
        if value is not None:
            event[field] = value
    print(write_event(event, root=args.root))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
