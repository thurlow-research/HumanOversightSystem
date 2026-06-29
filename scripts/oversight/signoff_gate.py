#!/usr/bin/env python3
"""signoff_gate.py — validation-suite sign-off gate (HOS framework script).

Blocks a change from merging (CI / PR mode) or deploying (deploy mode) unless
every agent in the validation suite has a *committed* sign-off stamp that is no
older than every changed source file.

The authoritative clock is the **git commit timestamp**, not the file's mtime on
disk. The commit timestamp is set when `git commit` runs, so the supported
workflow is:

  1. Make changes (not yet committed).
  2. Run the validation suite → each agent writes signoffs/<namespace>/<role>.stamp.
  3. git add -A && git commit        ← changed files AND stamps share commit time T.
  4. Push.
  5. Gate: max(changed-file commit time) <= min(stamp commit time)  → PASS.

Two-commit variant (commit code at T1, then commit stamps at T2 > T1) also
passes. The only case that fails is committing *new* changes after a stamp
without re-signing — exactly what the gate exists to catch.

Stamps live under a per-branch namespace, signoffs/<namespace>/<role>.stamp, so
two concurrent PRs never share a stamp path and disjoint changes never collide
on the register (#968 — the same shape as the per-entry audit-log migration,
#888). PR mode reads only the current branch's namespace; a pre-#968 flat
signoffs/<role>.stamp is still accepted as a migration fallback.

Required roles are read from contract/step-manifest.yaml: the union of every
step's `required_signoffs`, mapped to agent names via `role_mappings`. That
manifest is the single source of truth for who is in the validation suite.

Modes:
  --base <ref>   PR/CI mode. Compared file set = files changed vs. merge-base(ref).
                 Reads the current branch's namespace (override: --namespace /
                 $HOS_SIGNOFF_NAMESPACE).
  --all          Deploy mode. Compared file set = every tracked file; sign-offs
                 are aggregated across every namespace on the tree.

A stamp's status must be APPROVED, CONDITIONAL, or NOT_APPLICABLE. NOT_APPLICABLE
still has to be re-affirmed (re-committed) after later changes, so a role can
never silently fall behind.

Exit 0 = gate passes. Exit 1 = gate fails. Exit 2 = usage / environment error.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced as an env error
    # Auto-detect the oversight venv before giving up.  On macOS Homebrew Python
    # 3.14+ and Ubuntu 24.04+ (PEP 668), the system Python has no user packages,
    # so bare `python3 signoff_gate.py` fails.  The oversight venv has PyYAML
    # (a declared dependency in requirements.txt); os.execv replaces this process
    # with the venv Python running the same script — argv, cwd, and exit code all
    # propagate naturally.
    import os

    _venv_py = (Path(__file__).parent / ".venv" / "bin" / "python3").resolve()
    # Loop guard: only re-exec if we are NOT already running as the venv Python.
    # If we are (venv exists but somehow lacks PyYAML — a partial install), a
    # naive `if _venv_py.exists(): execv` would re-exec into ourselves forever.
    # Fall through to the explicit error instead of spinning.
    _already_venv = False
    try:
        _already_venv = _venv_py.exists() and _venv_py.samefile(sys.executable)
    except OSError:
        _already_venv = False
    if _venv_py.exists() and not _already_venv:
        os.execv(str(_venv_py), [str(_venv_py)] + sys.argv)
    sys.stderr.write(
        "signoff_gate: PyYAML is required but missing from the oversight venv.\n"
        "  Repair the venv:  ./scripts/oversight/ensure_venv.sh\n"
        "  Or install:       pip install pyyaml\n"
        f"  Or run via:       {_venv_py} {__file__}\n"
    )
    sys.exit(2)

SIGNOFFS_DIR = "signoffs"
# Oversight-generated, append-only artifacts. The system writes these *about* a
# step — sign-off stamps, the committed audit trail, ephemeral agent state — and
# often does so AFTER reviewers have signed (suspension-census, second-review,
# and the orchestrator all append to audit/oversight-log.jsonl). They are not
# source changes, so a stamp need not be newer than them. Excluding them is what
# stops the oversight tooling's own bookkeeping from perpetually invalidating the
# sign-offs it records. (HOS#112)
OVERSIGHT_ARTIFACT_PREFIXES = (
    f"{SIGNOFFS_DIR}/",
    "audit/",
    ".claudetmp/",
)
# A stamp records a *satisfied* role: APPROVED, CONDITIONAL (human verifies the
# conditional item before merge), or NOT_APPLICABLE (role explicitly out of
# scope for the change — the stamp-level equivalent of the N/A register entry,
# HOS#58). ESCALATED is intentionally NOT a stamp state: an unresolved
# escalation is by definition not satisfied, so it has no passing stamp and the
# gate fails (missing stamp) until the escalation is resolved and the role is
# re-signed. A human-authorized waiver is handled by gate suspension (HOS#22),
# not by a stamp. See signoffs/README.md.
VALID_STATUSES = {"APPROVED", "CONDITIONAL", "NOT_APPLICABLE", "NA"}
STAMP_SUFFIX = ".stamp"
# Environment override for the per-branch stamp namespace (#968). Lets a detached
# CI checkout pin the logical branch, e.g. HOS_SIGNOFF_NAMESPACE="$GITHUB_HEAD_REF".
NAMESPACE_ENV = "HOS_SIGNOFF_NAMESPACE"
# Reserved subdirectory of signoffs/ that holds committed validator artifacts
# (signoffs/validators/step{N}/summary.json, #555) — never a stamp namespace.
RESERVED_SIGNOFF_SUBDIRS = {"validators"}


def run_git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stripped stdout (empty string on failure)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def repo_root(start: Path) -> Path:
    root = run_git(["rev-parse", "--show-toplevel"], start)
    if not root:
        sys.stderr.write("signoff_gate: not inside a git repository.\n")
        sys.exit(2)
    return Path(root)


def commit_time(root: Path, path: str) -> int:
    """Commit timestamp (epoch seconds) of the last commit to touch `path`.

    Returns 0 when the path has no committed history (e.g. written but not yet
    committed) — callers treat 0 as 'not committed'.
    """
    out = run_git(["log", "-1", "--format=%ct", "--", path], root)
    return int(out) if out.isdigit() else 0


def load_required_roles(manifest_path: Path) -> tuple[list[str], dict[str, str]]:
    """Return (sorted required role keys, role -> agent-name map) from the manifest."""
    try:
        manifest = yaml.safe_load(manifest_path.read_text())
    except FileNotFoundError:
        sys.stderr.write(f"signoff_gate: manifest not found: {manifest_path}\n")
        sys.exit(2)
    except yaml.YAMLError as exc:
        sys.stderr.write(f"signoff_gate: cannot parse manifest: {exc}\n")
        sys.exit(2)

    role_map = manifest.get("role_mappings", {}) or {}
    roles: set[str] = set()
    for step in manifest.get("steps", []) or []:
        for role in step.get("required_signoffs", []) or []:
            roles.add(role)
    return sorted(roles), role_map


def parse_stamp_status(path: Path) -> str | None:
    """Read the `status:` field from a stamp file. None if unreadable/absent."""
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("status:"):
            return stripped.split(":", 1)[1].strip().upper()
    return None


def signoff_namespace(root: Path, override: str | None = None) -> str:
    """Per-branch stamp namespace slug. Mirrors sign_off.sh:signoff_namespace.

    Precedence: explicit override / $HOS_SIGNOFF_NAMESPACE, then the current
    branch name, then the short HEAD sha (detached HEAD). Sanitized to
    [A-Za-z0-9._-], collapsing other runs to a single '-'. Never empty.
    """
    raw = override or os.environ.get(NAMESPACE_ENV, "") or ""
    if not raw:
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        if branch and branch != "HEAD":
            raw = branch
    if not raw:
        raw = run_git(["rev-parse", "--short", "HEAD"], root) or "detached"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return slug or "detached"


def legacy_stamp_rel(role: str) -> str:
    """Pre-#968 flat stamp path, kept as a migration fallback."""
    return f"{SIGNOFFS_DIR}/{role}{STAMP_SUFFIX}"


def namespaced_stamp_rels(root: Path, role: str) -> list[str]:
    """Every existing stamp relpath for a role across all namespaces + legacy flat.

    Used by deploy mode (--all) and the release gate, which ask whether the tree
    on the integration branch is signed — they aggregate across the per-branch
    directories that accumulate on merge, plus any pre-migration flat stamp.
    """
    rels: list[str] = []
    legacy = legacy_stamp_rel(role)
    if (root / legacy).exists():
        rels.append(legacy)
    signoffs = root / SIGNOFFS_DIR
    if signoffs.is_dir():
        for child in sorted(signoffs.iterdir()):
            if not child.is_dir() or child.name in RESERVED_SIGNOFF_SUBDIRS:
                continue
            rel = f"{SIGNOFFS_DIR}/{child.name}/{role}{STAMP_SUFFIX}"
            if (root / rel).exists():
                rels.append(rel)
    return rels


def changed_files(root: Path, base: str) -> list[str]:
    """Files changed between merge-base(base, HEAD) and HEAD."""
    merge_base = run_git(["merge-base", base, "HEAD"], root)
    if not merge_base:
        # Fall back to a direct diff if the refs do not share history.
        merge_base = base
    out = run_git(["diff", "--name-only", merge_base, "HEAD"], root)
    return [line for line in out.splitlines() if line]


def all_tracked_files(root: Path) -> list[str]:
    out = run_git(["ls-files"], root)
    return [line for line in out.splitlines() if line]


def dirty_non_signoff_paths(root: Path) -> list[str]:
    """Working-tree changes (modified/staged/untracked) outside oversight artifacts.

    An unsigned working-tree change means files exist that no stamp can be newer
    than, so the gate must fail. Oversight-generated artifacts (sign-off stamps,
    the audit trail, ephemeral agent state) are exempt — signing and the system's
    own bookkeeping are not source changes. (HOS#112)
    """
    out = run_git(["status", "--porcelain"], root)
    dirty: list[str] = []
    for line in out.splitlines():
        if not line:
            continue
        path = line[3:]
        # Handle rename "old -> new"
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if is_oversight_artifact(path):
            continue
        dirty.append(path)
    return dirty


def is_oversight_artifact(path: str) -> bool:
    """True for oversight-generated artifacts excluded from the changed-file set.

    Covers sign-off stamps plus the audit trail and ephemeral agent state — all
    written by the oversight tooling itself, not source the stamps must beat.
    (HOS#112)
    """
    return path.startswith(OVERSIGHT_ARTIFACT_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate validation-suite sign-offs against changed files.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--base",
        metavar="REF",
        help="PR/CI mode: compare files changed vs merge-base(REF, HEAD).",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="Deploy mode: compare against every tracked file.",
    )
    parser.add_argument(
        "--manifest",
        default="contract/step-manifest.yaml",
        help="Path to step-manifest.yaml (default: contract/step-manifest.yaml).",
    )
    parser.add_argument(
        "--namespace",
        metavar="NS",
        help=(
            "PR-mode stamp namespace (default: a slug of the current branch, or "
            f"${NAMESPACE_ENV}). Ignored in --all mode, which aggregates across "
            "every namespace."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the final PASS/FAIL line.",
    )
    args = parser.parse_args()

    if not args.all and not args.base:
        parser.error("one of --base REF or --all is required")

    root = repo_root(Path.cwd())
    manifest_path = (root / args.manifest).resolve()
    required_roles, role_map = load_required_roles(manifest_path)

    if not required_roles:
        sys.stderr.write(
            "signoff_gate: no required_signoffs found in manifest — refusing to "
            "pass an empty validation suite.\n"
        )
        return 2

    def log(msg: str = "") -> None:
        if not args.quiet:
            print(msg)

    # PR mode reads only the current branch's namespace (a stamp from another
    # branch signed different code, so it must not satisfy this PR). Deploy mode
    # aggregates across every namespace that has accumulated on the tree.
    namespace = None if args.all else signoff_namespace(root, args.namespace)

    log("=== sign-off gate ===")
    log(f"manifest: {args.manifest}")
    log(f"mode:     {'deploy (--all)' if args.all else f'pr (--base {args.base})'}")
    if namespace is not None:
        log(f"namespace: {namespace}")
    log("")

    # ── 1. Working tree must be clean of unsigned changes ────────────────────
    dirty = dirty_non_signoff_paths(root)
    failures: list[str] = []
    if dirty:
        failures.append(
            "uncommitted changes outside signoffs/ are not covered by any "
            "sign-off:\n    " + "\n    ".join(sorted(dirty))
        )

    # ── 2. Build the file set whose recency the stamps must beat ─────────────
    if args.all:
        files = all_tracked_files(root)
    else:
        files = changed_files(root, args.base)
    files = [f for f in files if not is_oversight_artifact(f)]

    newest_file = ""
    newest_file_time = 0
    for f in files:
        # Only consider files that still exist with committed history.
        if not (root / f).exists():
            continue
        t = commit_time(root, f)
        if t > newest_file_time:
            newest_file_time, newest_file = t, f

    if files:
        if newest_file_time:
            log(f"newest changed file: {newest_file} " f"@ commit {newest_file_time}")
        else:
            log("changed files have no committed history yet.")
    else:
        log("no non-sign-off files in scope.")
    log("")

    # ── 3. Every required role needs a fresh, approved, committed stamp ──────
    log(f"required validation suite ({len(required_roles)} roles):")
    for role in required_roles:
        agent = role_map.get(role, "?")
        agent_label = f"{role} ({agent})"

        # Candidate stamp paths. PR mode: the branch namespace, then the legacy
        # flat path as a migration fallback. Deploy mode: every namespace + legacy.
        if args.all:
            candidates = namespaced_stamp_rels(root, role)
            missing_label = f"{SIGNOFFS_DIR}/*/{role}{STAMP_SUFFIX}"
        else:
            primary = f"{SIGNOFFS_DIR}/{namespace}/{role}{STAMP_SUFFIX}"
            candidates = [
                c for c in (primary, legacy_stamp_rel(role)) if (root / c).exists()
            ]
            missing_label = primary

        if not candidates:
            log(f"  ✗ {agent_label}: MISSING stamp {missing_label}")
            failures.append(f"{agent_label}: no stamp at {missing_label}")
            continue

        # Among the candidates, pick the newest stamp that is both valid-status
        # and committed. In PR mode that is normally the single namespace stamp;
        # in deploy mode it is the freshest sign-off across all merged branches.
        best_rel = None
        best_time = -1
        best_status = None
        for rel in candidates:
            status = parse_stamp_status(root / rel)
            if status not in VALID_STATUSES:
                continue
            t = commit_time(root, rel)
            if t == 0:
                continue
            if t > best_time:
                best_rel, best_time, best_status = rel, t, status

        if best_rel is None:
            # Nothing usable — surface the most actionable diagnostic from the
            # first candidate (invalid status, else uncommitted).
            first = candidates[0]
            status = parse_stamp_status(root / first)
            if status not in VALID_STATUSES:
                log(f"  ✗ {agent_label}: invalid status {status!r}")
                failures.append(
                    f"{agent_label}: status must be one of "
                    f"{sorted(VALID_STATUSES)}, got {status!r}"
                )
            else:
                log(f"  ✗ {agent_label}: stamp not committed yet")
                failures.append(
                    f"{agent_label}: stamp {first} exists but has no commit — "
                    f"commit it so it gets an authoritative timestamp"
                )
            continue

        if best_time < newest_file_time:
            delta = newest_file_time - best_time
            log(f"  ✗ {agent_label}: STALE — signed {delta}s before " f"{newest_file} changed")
            failures.append(
                f"{agent_label}: stamp ({best_time}) is older than changed file "
                f"{newest_file} ({newest_file_time}) — re-sign after changes"
            )
            continue

        log(f"  ✓ {agent_label}: {best_status} @ commit {best_time} [{best_rel}]")

    log("")
    if failures:
        log(f"FAIL — {len(failures)} problem(s):")
        for i, f in enumerate(failures, 1):
            log(f"  {i}. {f}")
        if args.quiet:
            print("sign-off gate: FAIL")
        return 1

    print("sign-off gate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
