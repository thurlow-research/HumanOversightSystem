"""Static check: every role the risk-assessor can emit is writable by its mapped agent (#2276).

The risk-assessor writes role keys to ``required-reviewers.md``; the
oversight-evaluator requires a sign-off register entry for each and cannot
waive one. If a role's mapped agent is forbidden to write a register entry (or
the role has no mapping at all) that step can never pass Phase 1. #2276 was
exactly this: the risk-assessor required ``architect`` while architect.md
forbade any register entry.

Checks (all deterministic, no AI):
  1. Every role the risk-assessor Phase 6 section says it adds is a key in the
     contract section 5 or template ``role_mappings`` block (the template's
     commented-out optional mappings count).
  2. Contract and step-manifest template mappings agree on the agent per role.
  3. Every mapped agent has ``.claude/agents/<agent>.md``.
  4. No mapped agent file carries an unscoped register-write prohibition.
     Matching is single-line: a prohibition split across lines is not seen.
  5. Every emitted role and every role_mappings key is a backticked key in the
     contract section 3 ``**Roles**`` table.

Exit codes: 0 clean, 1 findings, 2 usage error or a required file/block missing
(fail closed: an empty role set is never a pass).

Usage: python3 -m scripts.framework.check_role_writability [--repo-root PATH] [--quiet]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CONTRACT = Path("contract/OVERSIGHT-CONTRACT.md")
TEMPLATE = Path("contract/step-manifest.template.yaml")
RISK_ASSESSOR = Path(".claude/agents/risk-assessor.md")
AGENTS_DIR = Path(".claude/agents")
PHASE6_HEADING = "## Phase 6: Required reviewers"

# A mapping line inside a role_mappings block. The template ships optional
# mappings commented out and they are still valid, but a commented line counts
# only when it is exactly `# <role-key>: <agent>` followed by end-of-line or a
# `#` comment, so prose such as `# Note: this is ...` is not a mapping.
MAPPING_RE = re.compile(r"^\s*([a-z][a-z0-9-]*):\s+([a-z][a-z0-9-]*)\b")
COMMENTED_MAPPING_RE = re.compile(r"^\s*#\s*([a-z][a-z0-9-]*):\s+([a-z][a-z0-9-]*)\s*(?:#.*)?$")
ROLES_TABLE_HEADING = "**Roles**"
ROLE_ROW_RE = re.compile(r"^\|\s*`([a-z][a-z0-9-]*)`\s*\|")

# "adds `a`, `b`" on a Phase 6 bullet. Only backticks directly after "adds" count,
# so prose mentions like "never the agent name `architect`" are not role keys.
ADDS_RE = re.compile(r"\badds\s+((?:`[a-z][a-z0-9-]*`(?:\s*,\s*|\s+and\s+)?)+)")
KEY_RE = re.compile(r"`([a-z][a-z0-9-]*)`")

# An UNSCOPED register-write prohibition: a negation ("do not", "does not",
# "never", "must not", "may not", "cannot", "shall not", contractions) that
# directly governs "write(s)/writing" (at most two words between,
# so "do not attempt a 6th round ... write a ESCALATED register entry" does not
# match) and is followed within the same sentence by "register entr(y|ies)".
# Such a line is allowed only if it also carries a scoping qualifier
# (SCOPE_RE), as architect.md's does.
PROHIBITION_RE = re.compile(
    r"\b(?:(?:do(?:es)?|must|may|shall) not|never|don't|cannot|can't)\s+"
    r"(?:\w+\s+){0,2}(?:writes?|writing)\b[^.;]*\bregister entr",
    re.IGNORECASE,
)
SCOPE_RE = re.compile(r"\b(?:only when|except when|unless)\b", re.IGNORECASE)


def _parse_mappings(lines: list[str]) -> dict[str, str]:
    """Parse the lines following a ``role_mappings:`` key until the block ends."""
    out: dict[str, str] = {}
    for ln in lines:
        if not ln.strip():
            break
        m = COMMENTED_MAPPING_RE.match(ln) if ln.lstrip().startswith("#") else None
        m = m or MAPPING_RE.match(ln)
        if m:
            out[m.group(1)] = m.group(2)
        elif not ln.lstrip().startswith("#"):
            break
    return out


def read_mappings(path: Path) -> dict[str, str]:
    """Return the role->agent map of the first ``role_mappings:`` block, or {}."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "role_mappings:":
            return _parse_mappings(lines[i + 1 :])
    return {}


def read_contract_roles(path: Path) -> set[str]:
    """Backticked role keys in the table rows after the ``**Roles**`` line."""
    roles: set[str] = set()
    seen_heading = in_table = False
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not seen_heading:
            seen_heading = ln.startswith(ROLES_TABLE_HEADING)
            continue
        if ln.startswith("|"):
            in_table = True
            m = ROLE_ROW_RE.match(ln)
            if m:
                roles.add(m.group(1))
        elif in_table:
            break
    return roles


def read_phase6_roles(path: Path) -> list[str]:
    """Role keys the risk-assessor adds, from its Phase 6 section only."""
    roles: list[str] = []
    in_section = False
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## "):
            in_section = ln.strip() == PHASE6_HEADING
            continue
        if in_section and ln.lstrip().startswith("- "):
            for m in ADDS_RE.finditer(ln):
                roles.extend(KEY_RE.findall(m.group(1)))
    return roles


def find_unscoped_prohibitions(path: Path) -> list[tuple[int, str]]:
    """(line number, text) of every unscoped register-write prohibition."""
    hits = []
    for n, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        plain = ln.replace("*", "").replace("_", "")
        if PROHIBITION_RE.search(plain) and not SCOPE_RE.search(plain):
            hits.append((n, ln.strip()))
    return hits


def check(root: Path) -> tuple[list[str], list[str]]:
    """Return (findings, fatal errors)."""
    fatal = []
    for rel in (CONTRACT, TEMPLATE, RISK_ASSESSOR):
        if not (root / rel).is_file():
            fatal.append(f"required file missing: {rel}")
    if fatal:
        return [], fatal
    contract = read_mappings(root / CONTRACT)
    template = read_mappings(root / TEMPLATE)
    if not contract:
        fatal.append(f"no role_mappings block found in {CONTRACT}")
    if not template:
        fatal.append(f"no role_mappings block found in {TEMPLATE}")
    emitted = read_phase6_roles(root / RISK_ASSESSOR)
    if not emitted:
        fatal.append(f"no roles found in '{PHASE6_HEADING}' of {RISK_ASSESSOR}")
    table = read_contract_roles(root / CONTRACT)
    if not table:
        fatal.append(f"no '{ROLES_TABLE_HEADING}' role table found in {CONTRACT}")
    if fatal:
        return [], fatal

    findings: list[str] = []
    known = {**template, **contract}
    for role in sorted(set(emitted) - set(known)):
        findings.append(f"role `{role}` emitted by risk-assessor has no role_mappings entry")
    for role in sorted((set(emitted) | set(known)) - table):
        findings.append(f"role `{role}` is not in the {CONTRACT} {ROLES_TABLE_HEADING} table")
    for role in sorted(set(contract) & set(template)):
        if contract[role] != template[role]:
            findings.append(
                f"role `{role}` maps to `{contract[role]}` in {CONTRACT} "
                f"but `{template[role]}` in {TEMPLATE}"
            )
    for agent in sorted(set(known.values())):
        agent_file = root / AGENTS_DIR / f"{agent}.md"
        if not agent_file.is_file():
            findings.append(f"mapped agent `{agent}` has no {AGENTS_DIR / (agent + '.md')}")
            continue
        for n, text in find_unscoped_prohibitions(agent_file):
            findings.append(
                f"{AGENTS_DIR / (agent + '.md')}:{n}: unscoped register-write prohibition "
                f"on mapped agent `{agent}`: {text[:100]}"
            )
    return findings, []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    findings, fatal = check(Path(args.repo_root))
    for msg in fatal:
        print(f"ERROR: {msg}", file=sys.stderr)
    if fatal:
        return 2
    for msg in findings:
        print(f"FAIL: {msg}")
    if not findings and not args.quiet:
        print("OK: every risk-assessor-emittable role is writable by its mapped agent")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
