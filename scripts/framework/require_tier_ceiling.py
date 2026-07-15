#!/usr/bin/env python3
"""require_tier_ceiling.py — server-side overseer ceiling gate.

The load-bearing half of the autonomous-merge safety model: a check that runs
in GitHub Actions (outside the overseer's session), verifying that when the
overseer approves a PR the computed risk tier does not exceed OVERSEER_CEILING.

If the overseer has NOT approved, the gate trivially passes (ceiling is N/A).
If the overseer HAS approved, the tier is computed and compared to the ceiling.
A tier above the ceiling exits 1 (FAIL) — a human approval is required instead.

Usage (CI):
  python3 require_tier_ceiling.py --pr <number> [--repo owner/repo]

Exit codes:
  0 — ceiling not exceeded (safe to merge with overseer)
  1 — ceiling exceeded (overseer approved above its ceiling — human required)
  2 — error (missing data or tooling failure — fail-closed)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ENV_FILE = Path(__file__).with_name("machine-accounts.env")

TIER_ORDER = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


# ---------------------------------------------------------------------------
# machine-accounts.env loader
# ---------------------------------------------------------------------------

def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        print(
            f"require_tier_ceiling: machine-accounts.env not found at {path}",
            file=sys.stderr,
        )
        sys.exit(2)
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Strip inline bash comments before unquoting (e.g. KEY="val"  # comment)
        val = re.sub(r'\s+#.*$', '', val.strip())
        val = val.strip('"').strip("'")
        # Expand simple variable references (e.g. BOT_ACCOUNTS="${VAR1} ${VAR2}")
        val = re.sub(r"\$\{?(\w+)\}?", lambda m: result.get(m.group(1), ""), val)
        result[key] = val
    return result


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def _gh(*args: str) -> str:
    """Run `gh` with the given args, return stdout. Exit 2 on failure."""
    try:
        out = subprocess.run(
            ["gh"] + list(args),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError:
        print("require_tier_ceiling: `gh` not found on PATH", file=sys.stderr)
        sys.exit(2)
    except subprocess.CalledProcessError as exc:
        print(
            f"require_tier_ceiling: gh command failed: {exc.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    return out


def get_reviews(repo: str, pr: str) -> list[dict]:
    raw = _gh("api", "--paginate", f"repos/{repo}/pulls/{pr}/reviews")
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        # --paginate may concatenate arrays: "]\n[" → ","
        return json.loads(re.sub(r"\]\s*\[", ",", raw))


def overseer_has_approved(reviews: list[dict], overseer_login: str) -> bool:
    for review in reviews:
        if str(review.get("state", "")).upper() != "APPROVED":
            continue
        login = (review.get("user") or {}).get("login", "")
        if login.lower() == overseer_login.lower():
            return True
    return False


def get_changed_files(pr: str) -> list[str]:
    raw = _gh("pr", "diff", pr, "--name-only")
    return [line for line in raw.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tier computation
#
# The gate runs in CI on the TRUSTED BASE checkout (pull_request_target), so the
# working tree is the base branch — NOT the PR. To judge the PR's risk the gate
# must score the PR *head* content, which is untrusted. Per the workflow's
# security model that head content is fetched as DATA via the `gh` API and only
# ever *parsed* (ast) by the trusted-base validator, never executed.
#
# When a real Python risk surface exists but cannot be scored (validator error
# or head-content fetch failure), the gate fails closed (compute_tier → None →
# exit 2) rather than falling back to a MEDIUM-capped estimate that could never
# exceed the HIGH ceiling — the fail-open that let an overseer-approved
# CRITICAL PR pass unchecked (#973).
# ---------------------------------------------------------------------------


class _HeadFetchError(RuntimeError):
    """A changed file's head content could not be fetched (non-404 failure)."""


def _score_to_tier(score: float) -> str:
    """Map a 0..1 risk score to a tier.

    Local mirror of scripts/oversight/validators/schema.py:score_to_tier
    (TIER_THRESHOLDS) — duplicated deliberately so this trusted-base gate imports
    nothing from scripts/oversight/validators/ (whose modules mutate sys.path on
    import). Keep the boundaries in sync with schema.py.
    """
    if score < 0.30:
        return "LOW"
    if score < 0.55:
        return "MEDIUM"
    if score < 0.78:
        return "HIGH"
    return "CRITICAL"


def _max_tier(*tiers: str) -> str:
    """Return the highest tier among the arguments (by TIER_ORDER)."""
    return max(tiers, key=tier_to_int)


def _try_validator_summary() -> str | None:
    """Read tier from .claudetmp/oversight/validators/summary.json if present."""
    summary = Path(".claudetmp/oversight/validators/summary.json")
    if not summary.is_file():
        return None
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
        tier = data.get("tier") or data.get("risk_tier") or data.get("Tier")
        if isinstance(tier, str) and tier.upper() in TIER_ORDER:
            return tier.upper()
    except Exception:
        return None
    return None


def _pr_head_sha(repo: str, pr: str) -> str:
    """Resolve the PR's head commit SHA (via the gh API). Fail-closed on error."""
    sha = _gh("api", f"repos/{repo}/pulls/{pr}", "--jq", ".head.sha").strip()
    if not sha:
        raise _HeadFetchError("could not resolve PR head SHA")
    return sha


def _fetch_head_python(
    repo: str, pr: str, py_files: list[str], dest: Path
) -> list[str]:
    """Fetch the PR *head* content of each changed .py file into `dest` as DATA.

    The content is written to disk and later parsed (never executed) by the
    trusted-base validator — matching the workflow's "read PR files as DATA via
    the gh API" security model. Files that 404 at head (deleted by the PR) are
    skipped. Any other fetch failure raises _HeadFetchError so the caller fails
    closed rather than scoring an incomplete tree. Returns the written temp paths
    (extension preserved so the validator treats them as Python).
    """
    head_sha = _pr_head_sha(repo, pr)
    written: list[str] = []
    for rel in py_files:
        # Defensive: git tree paths are repo-relative and cannot escape, but
        # never let an unexpected path write outside the temp dir.
        if rel.startswith("/") or ".." in Path(rel).parts:
            continue
        proc = subprocess.run(
            [
                "gh", "api",
                "-H", "Accept: application/vnd.github.raw",
                f"repos/{repo}/contents/{rel}?ref={head_sha}",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.lower()
            if "404" in err or "not found" in err:
                continue  # deleted at head — nothing to score
            raise _HeadFetchError(f"failed to fetch {rel}: {proc.stderr.strip()}")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(proc.stdout, encoding="utf-8")
        written.append(str(target))
    return written


def _try_rn_calculator(py_paths: list[str]) -> str | None:
    """Score already-fetched head-content .py files with rn_calculator and derive
    the tier from the result.

    rn_calculator emits the shared schema envelope — a numeric `score` and a
    discrete `tier_floor` (#377), but **no** `tier`/`risk_tier` key — so the tier
    is derived here via _score_to_tier(score), then floored by tier_floor.
    Returns the derived tier, or None if rn_calculator is missing, errors, or
    yields no usable score (→ caller fails closed).
    """
    if not py_paths:
        return None
    rn_script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "oversight"
        / "validators"
        / "rn_calculator.py"
    )
    if not rn_script.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(rn_script)] + py_paths,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    score = data.get("score")
    if not isinstance(score, (int, float)):
        return None
    tier = _score_to_tier(float(score))
    floor = data.get("tier_floor")
    if isinstance(floor, str) and floor.upper() in TIER_ORDER:
        tier = _max_tier(tier, floor.upper())
    return tier


def _simplified_tier(changed_files: list[str]) -> str:
    """
    Structural risk estimate from the changed-file list alone (no code parsing).
    Used as a *floor* that can only raise a real tier, and as the standalone
    estimate when the PR changes no Python (no code-risk surface to score).
    Intentionally conservative:
      MEDIUM if >10 Python/shell files changed or any agent definition changed.
      LOW otherwise.
    """
    agent_paths = [f for f in changed_files if ".claude/agents/" in f]
    if agent_paths:
        return "MEDIUM"
    code_files = [
        f for f in changed_files
        if f.endswith((".py", ".sh"))
    ]
    if len(code_files) > 10:
        return "MEDIUM"
    return "LOW"


def compute_tier(repo: str, pr: str, changed_files: list[str]) -> str | None:
    """Best available risk tier for the PR, or None when a real Python risk
    surface exists but could not be scored (→ caller fails closed).

    Precedence:
      1. Pre-computed validator summary.json (inner-loop/local runs only).
      2. rn_calculator over the PR *head* content of changed .py files, floored
         by the structural estimate.
      3. No Python risk surface → structural estimate (conservative, ≤ MEDIUM).
    """
    structural = _simplified_tier(changed_files)

    # 1. Pre-computed summary from the inner-loop validators (absent in CI).
    tier = _try_validator_summary()
    if tier:
        return _max_tier(tier, structural)

    # 2. Score the PR head Python content as DATA.
    py_files = [f for f in changed_files if f.endswith(".py")]
    if py_files:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fetched = _fetch_head_python(repo, pr, py_files, Path(tmp))
                if fetched:
                    rn = _try_rn_calculator(fetched)
                    if rn is None:
                        # Real Python surface we could not score → fail closed.
                        return None
                    return _max_tier(rn, structural)
                # else: every changed .py was deleted at head → no live surface.
        except _HeadFetchError:
            # Could not fetch head content → fail closed (never guess).
            return None

    # 3. No Python risk surface to measure → structural estimate.
    return structural


# ---------------------------------------------------------------------------
# Tier comparison
# ---------------------------------------------------------------------------

def tier_to_int(tier: str) -> int:
    """Map tier name to ordering int. Unknown tiers map to CRITICAL (fail-safe)."""
    return TIER_ORDER.get(tier.upper(), TIER_ORDER["CRITICAL"])


def tier_exceeds_ceiling(tier: str, ceiling: str) -> bool:
    return tier_to_int(tier) > tier_to_int(ceiling)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Overseer tier-ceiling gate")
    ap.add_argument("--pr", required=True, help="PR number")
    ap.add_argument("--repo", default="", help="owner/repo (defaults to GITHUB_REPOSITORY env)")
    args = ap.parse_args()

    # Resolve repo slug
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print(
            "require_tier_ceiling: --repo or GITHUB_REPOSITORY required",
            file=sys.stderr,
        )
        return 2

    # Load identity config
    env = load_env(ENV_FILE)
    overseer_login = env.get("BOT_OVERSEER_USERNAME", "").strip()
    ceiling = env.get("OVERSEER_CEILING", "").strip().upper()

    if not overseer_login:
        print(
            "require_tier_ceiling: BOT_OVERSEER_USERNAME not set in machine-accounts.env",
            file=sys.stderr,
        )
        return 2
    if not ceiling or ceiling not in TIER_ORDER:
        print(
            f"require_tier_ceiling: OVERSEER_CEILING '{ceiling}' is not a valid tier "
            f"(expected one of {list(TIER_ORDER)})",
            file=sys.stderr,
        )
        return 2

    # Fetch reviews; determine if the overseer has approved
    reviews = get_reviews(repo, args.pr)
    if not overseer_has_approved(reviews, overseer_login):
        print(
            f"require_tier_ceiling: overseer ({overseer_login}) has not approved — "
            "ceiling gate N/A (pass)."
        )
        return 0

    # Overseer has approved: compute the tier and compare to ceiling
    changed = get_changed_files(args.pr)
    if not changed:
        # No changed files is unusual but not an error — treat as SAFE
        print(
            "require_tier_ceiling: no changed files reported (treating as SAFE — pass)."
        )
        return 0

    tier = compute_tier(repo, args.pr, changed)
    if tier is None:
        print(
            "require_tier_ceiling: overseer approved, but the PR's changed "
            "Python files could not be scored (validator error or head-content "
            "fetch failure). Failing closed — a human reviewer must approve.",
            file=sys.stderr,
        )
        return 2
    print(
        f"require_tier_ceiling: overseer approved; computed tier={tier}, "
        f"ceiling={ceiling}."
    )

    if tier_exceeds_ceiling(tier, ceiling):
        print(
            f"\nFAIL — overseer ({overseer_login}) approved a PR at tier {tier}, "
            f"which exceeds its ceiling ({ceiling}).",
            file=sys.stderr,
        )
        print(
            "  A human reviewer must approve this PR instead.",
            file=sys.stderr,
        )
        return 1

    print(
        f"PASS — tier {tier} is within the overseer ceiling ({ceiling})."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"require_tier_ceiling: unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)
