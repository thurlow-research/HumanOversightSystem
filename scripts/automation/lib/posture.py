"""
posture.py — shared posture validation, rules V1-V14 (ADR-1643 AD-7, TD-D26).

L1 module. Extracted from `agent_invoke_cli.load_posture` so that both the L2
invocation primitive and the L1 dimension-registry loader (rule L12) enforce
one copy of a security control. The rule semantics are those of the original
`agent_invoke_cli.py` implementation, byte for byte; the only change is that a
failure raises `PostureError(rule=...)` instead of an L2-private exception.

Standard library only: no `yaml`, no `argparse`, no subprocess, no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# V14 — matches the command token of a `Bash(<command> ...)` permissions.allow
# entry, e.g. captures "bootstrap/query_issues.sh" from
# "Bash(bootstrap/query_issues.sh *)" and "git" from "Bash(git diff *)". Only
# entries whose captured token contains a path separator are treated as script
# paths (see load_posture V14).
_BASH_SCRIPT_ALLOW_RE = re.compile(r"^Bash\(([^\s)]+)")

KNOWN_POSTURES = frozenset({"review-read-only", "review-read-only-gh-read"})


class PostureError(Exception):
    """A posture failed validation. `rule` is the failing rule, "V1".."V14"."""

    def __init__(self, rule: str, message: str = ""):
        super().__init__(rule, message)
        self.rule = rule
        self._text = f"{rule}: {message}" if message else rule

    def __str__(self) -> str:
        return self._text


@dataclass
class Posture:
    id: str
    settings_path: Path
    sidecar_path: Path
    settings_bytes: bytes
    sidecar_bytes: bytes
    permission_mode: str
    allowed_tools: list[str]
    disallowed_tools: list[str]
    sha256: str


def load_posture(repo_root: Path, name: str) -> Posture:
    """AD-7's posture load and validation (§3.6 V1-V14). Raises
    `PostureError` carrying the failing rule id."""
    if name not in KNOWN_POSTURES:
        raise PostureError("V1", f"unknown posture: {name!r}")

    postures_dir = repo_root / "contract" / "dimensions" / "postures"
    settings_path = postures_dir / f"{name}.settings.json"
    sidecar_path = postures_dir / f"{name}.hos.json"

    if not settings_path.is_file() or not sidecar_path.is_file():
        raise PostureError("V2")

    settings_bytes = settings_path.read_bytes()
    sidecar_bytes = sidecar_path.read_bytes()

    try:
        settings = json.loads(settings_bytes)
        sidecar = json.loads(sidecar_bytes)
    except json.JSONDecodeError:
        raise PostureError("V3")
    if not isinstance(settings, dict) or not isinstance(sidecar, dict):
        raise PostureError("V3")

    if sidecar.get("schema") != "hos.invocation-posture" or sidecar.get("schema_version") != 1:
        raise PostureError("V4")
    if sidecar.get("id") != name or settings_path.stem.split(".")[0] != name:
        raise PostureError("V5")

    permission_mode = sidecar.get("permission_mode")
    if permission_mode not in ("manual", "dontAsk"):
        raise PostureError("V6")

    permissions = settings.get("permissions")
    if (
        not isinstance(permissions, dict)
        or permissions.get("disableBypassPermissionsMode") != "disable"
    ):
        raise PostureError("V7")

    allow = permissions.get("allow")
    deny = permissions.get("deny")
    if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
        raise PostureError("V8")
    if not isinstance(deny, list) or not all(isinstance(x, str) for x in deny):
        raise PostureError("V8")

    allowed_tools = sidecar.get("allowed_tools")
    disallowed_tools = sidecar.get("disallowed_tools")
    if not isinstance(allowed_tools, list) or not all(isinstance(x, str) for x in allowed_tools):
        raise PostureError("V8")
    if not isinstance(disallowed_tools, list) or not all(
        isinstance(x, str) for x in disallowed_tools
    ):
        raise PostureError("V8")

    if set(allowed_tools) & set(disallowed_tools):
        raise PostureError("V9")
    if not set(disallowed_tools) <= set(deny):
        raise PostureError("V10")

    if permissions.get("defaultMode") == "bypassPermissions":
        raise PostureError("V11")
    if b"dangerously" in settings_bytes.lower():
        raise PostureError("V11")

    # V12/V13 (ADR-1643 Amendment 5, AD-7.1 — #1678) — a bare tool name in
    # `allowed_tools` is passed through `--allowed-tools` as an UNCONDITIONAL
    # grant of that tool, which supersedes every rule-scoped entry for it in
    # `permissions.allow` (probe arms K/L/M/N; live CLI 2.1.272). V12 catches
    # a bare grant sitting alongside a rule-scoped entry for the same tool,
    # which makes the rule-scoped entry's narrowness meaningless. V13 is
    # unconditional (not contingent on a matching rule-scoped entry existing
    # today) so a future edit that deletes the last `Bash(...)` allow entry
    # cannot reintroduce the blanket grant without tripping anything.
    for tool in allowed_tools:
        rule_prefix = f"{tool}("
        if any(entry.startswith(rule_prefix) for entry in allow):
            raise PostureError("V12")
    if "Bash" in allowed_tools:
        raise PostureError("V13")

    # V14 (ADR-1643 Amendment 5 §10.7) — a `Bash(<script-path> *)` allow
    # entry delegates the boundary to the script's own argument handling
    # (AD-7.2), which is void if the executable bit was lost on install.
    # That must fail loudly, not degrade silently to "capability not
    # available". Only entries whose command token contains a path separator
    # are script-path entries; a bare command name (`git`, `cat`, ...) is not
    # a script this repo ships and is not checked here. An absolute token is
    # rejected outright rather than resolved: `Path(repo_root) / "/abs"`
    # discards `repo_root` entirely (`PurePath.__truediv__`'s documented
    # absolute-operand behaviour), which would validate the entry against
    # the HOST filesystem instead of the repo.
    for entry in allow:
        match = _BASH_SCRIPT_ALLOW_RE.match(entry)
        if match is None:
            continue
        command_token = match.group(1)
        if "/" not in command_token:
            continue
        if command_token.startswith("/"):
            raise PostureError("V14")
        script_path = repo_root / command_token
        if not script_path.is_file() or not os.access(script_path, os.X_OK):
            raise PostureError("V14")

    posture_sha256 = hashlib.sha256(settings_bytes + b"\0" + sidecar_bytes).hexdigest()
    return Posture(
        id=name,
        settings_path=settings_path,
        sidecar_path=sidecar_path,
        settings_bytes=settings_bytes,
        sidecar_bytes=sidecar_bytes,
        permission_mode=permission_mode,
        allowed_tools=list(allowed_tools),
        disallowed_tools=list(disallowed_tools),
        sha256=posture_sha256,
    )
