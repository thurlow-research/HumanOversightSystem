"""
Machine-readable HOS coordination envelope — parse, emit, threading, idempotency.

The envelope is a YAML frontmatter block embedded in GitHub issue/comment bodies.
It gives the loop reliable threading and at-least-once idempotency — the fix for
the "have I already answered this?" problem from the CPS field test.

Envelope format (v1.0):
  ---hos-envelope
  type: <string>              # required: question | answer | report | release-notification
                              #           feature-request | suppression | heartbeat | ack
  from: <string>              # routing only — NOT used for auth (see allowlist check)
  correlation-id: <cid>       # deterministic 12-char hex (correlation.py)
  in-reply-to: <cid>          # optional: cid of the envelope being replied to
  priority: <P0|P1|P2|P3>    # optional
  protocol-version: "1.0"
  ---

Auth is done via the GitHub-API-verified comment/issue author (NOT the from: field).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

# Envelope sentinel
_OPEN = "---hos-envelope"
_CLOSE = "---"

CURRENT_VERSION = "1.0"

VALID_TYPES = frozenset({
    "question", "answer", "report", "release-notification",
    "feature-request", "suppression", "heartbeat", "ack",
    "permission-request", "claim", "claim-release",
})

VALID_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})

# ---------------------------------------------------------------------------
# Ack patterns — O14 resolution: phrases that indicate a prior answer exists.
# Loaded from fixtures/ack_patterns.jsonl at runtime; hardcoded v1 defaults here.
# ---------------------------------------------------------------------------
DEFAULT_ACK_PATTERNS = [
    re.compile(r"decision:\s*(approve|deny|proceed|reject)", re.IGNORECASE),
    re.compile(r"---hos-envelope", re.IGNORECASE),
    re.compile(r"correlation-id:\s*[0-9a-f]{12}", re.IGNORECASE),
    re.compile(r"\bhos[-_]?(worker|overseer)\b.*responded", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Envelope:
    type: str
    correlation_id: str
    from_: str = ""
    in_reply_to: Optional[str] = None
    priority: Optional[str] = None
    protocol_version: str = CURRENT_VERSION
    raw_body: str = ""          # text after the envelope block
    extra: dict = field(default_factory=dict)

    def is_reply_to(self, cid: str) -> bool:
        return self.in_reply_to == cid

    def to_yaml_block(self) -> str:
        """Emit the envelope as a YAML frontmatter block for embedding in a comment."""
        lines = [_OPEN]
        lines.append(f"type: {self.type}")
        lines.append(f"correlation-id: {self.correlation_id}")
        if self.from_:
            lines.append(f"from: {self.from_}")
        if self.in_reply_to:
            lines.append(f"in-reply-to: {self.in_reply_to}")
        if self.priority:
            lines.append(f"priority: {self.priority}")
        lines.append(f"protocol-version: \"{self.protocol_version}\"")
        for k, v in self.extra.items():
            lines.append(f"{k}: {v}")
        lines.append(_CLOSE)
        return "\n".join(lines)

    def to_comment_body(self, body_text: str = "") -> str:
        """Emit a full comment body: envelope block + optional human-readable text."""
        parts = [self.to_yaml_block()]
        if body_text:
            parts.append("")
            parts.append(body_text)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_envelope(text: str) -> Optional[Envelope]:
    """
    Extract and parse the first hos-envelope block from a comment/issue body.

    Returns None if no valid envelope is found.
    Auth is the caller's responsibility — the from: field is NOT validated here.
    """
    if yaml is None:
        raise ImportError("PyYAML required: pip install pyyaml")

    # Find the envelope block
    pattern = re.compile(
        r"---hos-envelope\s*\n(.*?)\n---(?:\s|$)",
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return None

    block_text = m.group(1)
    try:
        data = yaml.safe_load(block_text) or {}
    except yaml.YAMLError:
        return None

    if not isinstance(data, dict):
        return None

    # Normalize hyphen-case keys
    data = {k.replace("-", "_"): v for k, v in data.items()}

    env_type = data.get("type", "")
    cid = data.get("correlation_id", "")

    if not env_type or not cid:
        return None

    # Body text follows the envelope block
    raw_body = text[m.end():].strip()

    known_keys = {"type", "correlation_id", "from_", "in_reply_to", "priority", "protocol_version"}
    extra = {k: v for k, v in data.items() if k not in known_keys and k != "from"}

    in_reply_to = data.get("in_reply_to")
    return Envelope(
        type=env_type,
        correlation_id=str(cid),
        from_=str(data.get("from", "")),
        in_reply_to=str(in_reply_to) if in_reply_to is not None else None,
        priority=data.get("priority"),
        protocol_version=str(data.get("protocol_version", CURRENT_VERSION)),
        raw_body=raw_body,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Idempotency — has this item already been answered?
# ---------------------------------------------------------------------------

def already_answered(
    comment_bodies: list[str],
    cid: str,
    ack_patterns: Optional[list[re.Pattern]] = None,
) -> bool:
    """
    Check whether any comment in the thread already contains a reply to cid.

    Two-layer check:
      1. Structural: look for an envelope with in-reply-to: <cid> or correlation-id: <cid>
      2. Pattern: look for ack patterns (O14) as a fallback for pre-envelope responses
    """
    patterns = ack_patterns or DEFAULT_ACK_PATTERNS

    for body in comment_bodies:
        # Layer 1: structural envelope check
        env = parse_envelope(body)
        if env and (env.correlation_id == cid or env.in_reply_to == cid):
            return True

        # Layer 2: O14 ack pattern fallback
        if cid in body:
            for pat in patterns:
                if pat.search(body):
                    return True

    return False


# ---------------------------------------------------------------------------
# Allowlist authentication (R4.1.4 — GitHub-author, NOT from: field)
# ---------------------------------------------------------------------------

def author_is_allowed(
    github_login: str,
    requester_allowlist: list[str],
) -> bool:
    """
    Verify the GitHub-API-reported comment author is in the requester allowlist.

    The from: field in the envelope is for routing only and is never used for auth.
    github_login must come from the GitHub REST API (e.g. comment.user.login),
    not from the envelope body itself.
    """
    if not requester_allowlist:
        return False
    return github_login.lower() in {a.lower() for a in requester_allowlist}


# ---------------------------------------------------------------------------
# Version negotiation
# ---------------------------------------------------------------------------

def negotiate_version(their_version: str) -> Optional[str]:
    """
    Negotiate protocol version. Returns the agreed version or None if incompatible.

    v1: only "1.0" is supported. A future v2 would add backward-compat logic here.
    """
    if their_version == CURRENT_VERSION:
        return CURRENT_VERSION
    # Accept minor version differences within major version 1
    try:
        their_major = int(their_version.split(".")[0])
        our_major = int(CURRENT_VERSION.split(".")[0])
        if their_major == our_major:
            # Use the lower version for compatibility
            parts_theirs = [int(x) for x in their_version.split(".")]
            parts_ours = [int(x) for x in CURRENT_VERSION.split(".")]
            if parts_theirs <= parts_ours:
                return their_version
            return CURRENT_VERSION
    except (ValueError, IndexError):
        pass
    return None  # Incompatible


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_claim_envelope(cid: str, who: str, instance_id: str) -> Envelope:
    return Envelope(
        type="claim",
        correlation_id=cid,
        from_=who,
        extra={"instance-id": instance_id},
    )


def make_answer_envelope(cid: str, in_reply_to: str, who: str) -> Envelope:
    return Envelope(
        type="answer",
        correlation_id=cid,
        in_reply_to=in_reply_to,
        from_=who,
    )


def make_heartbeat_envelope(cid: str, who: str, status: str = "in-progress") -> Envelope:
    return Envelope(
        type="heartbeat",
        correlation_id=cid,
        from_=who,
        extra={"status": status},
    )


def make_permission_request(
    cid: str,
    who: str,
    token_estimate: int,
    blast_radius_summary: str,
    deadline_iso: str,
) -> Envelope:
    return Envelope(
        type="permission-request",
        correlation_id=cid,
        from_=who,
        priority="P1",
        extra={
            "token-estimate": token_estimate,
            "blast-radius": blast_radius_summary,
            "default-deny-deadline": deadline_iso,
        },
    )
