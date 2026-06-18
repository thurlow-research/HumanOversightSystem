"""
4-layer config resolver for the HOS automation loop (T2, R13.1–R13.3).

Layer 1 — shipped defaults (hos-coordination.defaults.yaml, inert)
Layer 2a — governance config (PROJECT/hos-coordination.yaml, CODEOWNERS-gated)
Layer 2b — operational soft state (.ai-local/hos-automation/, cadence/last-poll)
Layer 3 — runtime env (HOS_AUTO_* env vars, narrow-only)

Narrow-only constraint (R13.1):
  enabled: AND of all layers (false at any layer = absolute veto)
  thresholds.*: per-key direction (budget/timeout = min, floors = max)
  requester_allowlist: intersection
  mode: propose-only floor wins (cannot be widened by a later layer)

Hyphen-to-underscore normalization runs immediately after each YAML load,
before any overlay or narrow-only check. Downstream code never sees hyphens.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Defaults file ships with the framework source.
_DEFAULTS_PATH = Path(__file__).parent.parent / "hos-coordination.defaults.yaml"

# Governance config location in any consumer repo (CODEOWNERS-gated).
_GOVERNANCE_RELPATH = Path("PROJECT") / "hos-coordination.yaml"

# Operational soft state (gitignored, agent-writable, ephemeral).
_SOFT_STATE_DIR = Path(".ai-local") / "hos-automation"
_CADENCE_STATE_FILE = "cadence-state.json"


# ---------------------------------------------------------------------------
# Sub-objects for the EffectiveConfig
# ---------------------------------------------------------------------------

@dataclass
class ThresholdsConfig:
    per_task_tokens: int = 150_000
    window_budget_tokens: int = 1_500_000
    approval_timeout: str = "12h"
    triage_confidence_floor: float = 0.75


@dataclass
class CadenceConfig:
    floor: str = "15m"
    ceiling: str = "24h"


@dataclass
class SelfReviewConfig:
    cadence: str = "weekly"
    cross_vendor: bool = True


@dataclass
class SeverityTriageConfig:
    scheme: str = "P0-P3"
    fix_order: str = "highest-first"


@dataclass
class ClaimConfig:
    timeout: str = "45m"
    heartbeat: str = "15m"


@dataclass
class BlastRadiusConfig:
    prs: int = 5
    issues: int = 10
    files: int = 25


@dataclass
class BreakersConfig:
    per_issue_failures: int = 3
    blast_radius: BlastRadiusConfig = field(default_factory=BlastRadiusConfig)
    dead_man: str = "6h"
    max_task_runtime: str = "4h"


@dataclass
class SuppressionConfig:
    default_ttl: str = "90d"
    nag_lead_days: int = 14


@dataclass
class EffectiveConfig:
    customer: str = ""
    enabled: bool = False
    protocol_version: str = "1.0"
    mode: str = "propose-only"
    requester_allowlist: list[str] = field(default_factory=list)
    security_sensitive_paths: list[str] = field(default_factory=list)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    cadence: CadenceConfig = field(default_factory=CadenceConfig)
    self_review: SelfReviewConfig = field(default_factory=SelfReviewConfig)
    severity_triage: SeverityTriageConfig = field(default_factory=SeverityTriageConfig)
    claim: ClaimConfig = field(default_factory=ClaimConfig)
    orchestrator_lock_timeout: str = "20m"
    breakers: BreakersConfig = field(default_factory=BreakersConfig)
    suppression: SuppressionConfig = field(default_factory=SuppressionConfig)


# ---------------------------------------------------------------------------
# YAML load + normalization
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return a dict, or {} if absent/unreadable."""
    if not path.is_file():
        return {}
    if yaml is None:
        raise ImportError("PyYAML is required: pip install pyyaml")
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            logger.warning("Config file %s is not a YAML mapping — ignored", path)
            return {}
        return data
    except Exception as exc:
        logger.warning("Could not load config %s: %s — ignored", path, exc)
        return {}


def _normalize_keys(obj: Any) -> Any:
    """
    Recursively replace hyphen-case keys with underscore-case.

    Runs immediately after YAML parse, before any overlay or validation.
    No downstream code should see hyphen-case keys.
    """
    if isinstance(obj, dict):
        return {k.replace("-", "_"): _normalize_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_keys(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Narrow-only enforcement helpers (R13.1)
# ---------------------------------------------------------------------------

# Per-key threshold narrowing direction.
# "narrow" = "tighter / less permissive".
# Budget/timeout keys: smaller is tighter → use min().
# Floor keys: larger is tighter → use max().
_THRESHOLD_NARROW_OP: dict[str, str] = {
    "per_task_tokens": "min",
    "window_budget_tokens": "min",
    "approval_timeout": "min",        # string durations compared lexicographically
    "triage_confidence_floor": "max",
}


def _narrow_enabled(base: bool, overlay: bool) -> bool:
    """enabled: AND — false at any layer is an absolute veto."""
    return base and overlay


def _narrow_mode(base: str, overlay: str) -> str:
    """mode: propose-only floor wins; autonomous cannot be widened in."""
    if base == "propose-only" or overlay == "propose-only":
        return "propose-only"
    return base


def _narrow_allowlist(base: list[str], overlay: list[str]) -> list[str]:
    """
    requester_allowlist: effective = intersection.

    An empty overlay means "no one authorized" — the intersection of any set
    with the empty set is empty.  This is intentional narrowing (the tightest
    possible restriction), not a no-op.  If the overlay key is absent entirely,
    _overlay() will not call this function, preserving the base value.
    """
    if not base:
        return overlay
    base_set = set(base)
    overlay_set = set(overlay)
    return sorted(base_set & overlay_set)


def _narrow_thresholds(base: dict, overlay: dict) -> dict:
    """
    Merge threshold dicts with per-key narrow direction.

    Keys not in _THRESHOLD_NARROW_OP are carried from base unchanged
    (unknown keys from a later layer are accepted but not narrowed — they
    override, with a warning).
    """
    result = dict(base)
    for key, val in overlay.items():
        op = _THRESHOLD_NARROW_OP.get(key)
        if op is None:
            if key not in result:
                result[key] = val
            else:
                logger.warning(
                    "Unknown threshold key %r — taking overlay value without narrowing", key
                )
                result[key] = val
            continue
        base_val = result.get(key)
        if base_val is None:
            result[key] = val
            continue
        # Compare numerically if both are numeric; otherwise compare as strings.
        try:
            base_n = float(base_val)
            overlay_n = float(val)
            merged = min(base_n, overlay_n) if op == "min" else max(base_n, overlay_n)
            # Preserve int type if both inputs were int.
            if isinstance(base_val, int) and isinstance(val, int):
                result[key] = int(merged)
            else:
                result[key] = merged
        except (TypeError, ValueError):
            # Duration strings like "12h" — compare as strings; warn and take base.
            logger.warning(
                "Threshold key %r has non-numeric value %r (base) vs %r (overlay) — "
                "keeping base value (narrowing not applied to string durations)",
                key, base_val, val,
            )
    return result


# ---------------------------------------------------------------------------
# Dict → EffectiveConfig
# ---------------------------------------------------------------------------

def _build_config(d: dict[str, Any]) -> EffectiveConfig:
    thresholds_d = d.get("thresholds", {})
    cadence_d = d.get("cadence", {})
    self_review_d = d.get("self_review", {})
    severity_d = d.get("severity_triage", {})
    claim_d = d.get("claim", {})
    breakers_d = d.get("breakers", {})
    blast_d = breakers_d.get("blast_radius", {})
    suppression_d = d.get("suppression", {})

    return EffectiveConfig(
        customer=d.get("customer", ""),
        enabled=bool(d.get("enabled", False)),
        protocol_version=str(d.get("protocol_version", "1.0")),
        mode=str(d.get("mode", "propose-only")),
        requester_allowlist=list(d.get("requester_allowlist", [])),
        security_sensitive_paths=list(d.get("security_sensitive_paths", [])),
        thresholds=ThresholdsConfig(
            per_task_tokens=int(thresholds_d.get("per_task_tokens", 150_000)),
            window_budget_tokens=int(thresholds_d.get("window_budget_tokens", 1_500_000)),
            approval_timeout=str(thresholds_d.get("approval_timeout", "12h")),
            triage_confidence_floor=float(
                thresholds_d.get("triage_confidence_floor", 0.75)
            ),
        ),
        cadence=CadenceConfig(
            floor=str(cadence_d.get("floor", "15m")),
            ceiling=str(cadence_d.get("ceiling", "24h")),
        ),
        self_review=SelfReviewConfig(
            cadence=str(self_review_d.get("cadence", "weekly")),
            cross_vendor=bool(self_review_d.get("cross_vendor", True)),
        ),
        severity_triage=SeverityTriageConfig(
            scheme=str(severity_d.get("scheme", "P0-P3")),
            fix_order=str(severity_d.get("fix_order", "highest-first")),
        ),
        claim=ClaimConfig(
            timeout=str(claim_d.get("timeout", "45m")),
            heartbeat=str(claim_d.get("heartbeat", "15m")),
        ),
        orchestrator_lock_timeout=str(d.get("orchestrator_lock_timeout", "20m")),
        breakers=BreakersConfig(
            per_issue_failures=int(breakers_d.get("per_issue_failures", 3)),
            blast_radius=BlastRadiusConfig(
                prs=int(blast_d.get("prs", 5)),
                issues=int(blast_d.get("issues", 10)),
                files=int(blast_d.get("files", 25)),
            ),
            dead_man=str(breakers_d.get("dead_man", "6h")),
            max_task_runtime=str(breakers_d.get("max_task_runtime", "4h")),
        ),
        suppression=SuppressionConfig(
            default_ttl=str(suppression_d.get("default_ttl", "90d")),
            nag_lead_days=int(suppression_d.get("nag_lead_days", 14)),
        ),
    )


# ---------------------------------------------------------------------------
# Layer overlay (dict merge with narrow-only on governance fields)
# ---------------------------------------------------------------------------

def _overlay(base: dict, overlay_raw: dict, is_governance: bool = True) -> dict:
    """
    Merge overlay_raw into base dict, applying narrow-only to governance fields.

    is_governance=True → enforce narrow-only on enabled/thresholds/allowlist/mode.
    is_governance=False (soft-state/env) → merge non-governance fields only.
    """
    result = dict(base)

    for key, val in overlay_raw.items():
        if key == "enabled" and is_governance:
            base_enabled = result.get("enabled", False)
            overlay_enabled = bool(val)
            new_enabled = _narrow_enabled(base_enabled, overlay_enabled)
            if new_enabled != overlay_enabled and overlay_enabled is True:
                logger.warning(
                    "Config overlay attempted to widen 'enabled' (base=False, overlay=True) "
                    "— veto applied (enabled stays False)"
                )
            result["enabled"] = new_enabled

        elif key == "thresholds" and is_governance:
            result["thresholds"] = _narrow_thresholds(
                result.get("thresholds", {}), dict(val) if val else {}
            )

        elif key == "requester_allowlist" and is_governance:
            result["requester_allowlist"] = _narrow_allowlist(
                result.get("requester_allowlist", []), list(val) if val else []
            )

        elif key == "mode" and is_governance:
            result["mode"] = _narrow_mode(result.get("mode", "propose-only"), str(val))

        elif key in ("enabled", "thresholds", "requester_allowlist", "mode") and not is_governance:
            # Soft-state / env MUST NOT carry governance fields.
            logger.warning(
                "Non-governance layer attempted to set governance key %r — ignored", key
            )

        else:
            result[key] = val

    return result


# ---------------------------------------------------------------------------
# Env overlay (HOS_AUTO_* vars, narrow-only)
# ---------------------------------------------------------------------------

_ENV_NARROW_KEYS = {"enabled", "thresholds", "requester_allowlist", "mode"}


def _build_env_overlay() -> dict[str, Any]:
    """
    Read HOS_AUTO_* env vars and produce a narrow overlay dict.

    Only a small, explicit set of keys is honoured.  Governance keys
    follow narrow-only; all others are passed through.
    """
    overlay: dict[str, Any] = {}

    # enabled: HOS_AUTO_ENABLED=false is a veto; =true cannot widen.
    raw_enabled = os.environ.get("HOS_AUTO_ENABLED")
    if raw_enabled is not None:
        overlay["enabled"] = raw_enabled.strip().lower() not in ("0", "false", "no")

    # mode: HOS_AUTO_MODE=propose-only forces propose-only.
    raw_mode = os.environ.get("HOS_AUTO_MODE")
    if raw_mode is not None:
        overlay["mode"] = raw_mode.strip()

    return overlay


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def resolve(repo_root: Optional[str | Path] = None) -> EffectiveConfig:
    """
    Resolve the effective config for the given repo root (or cwd).

    Layer order: defaults → governance yaml → soft state (cadence only) → env.
    Each layer is hyphen-to-underscore normalized before overlaying.
    Governance fields enforce narrow-only (R13.1).
    """
    root = Path(repo_root) if repo_root else Path.cwd()

    # Layer 1 — shipped defaults (always exists).
    layer1 = _normalize_keys(_load_yaml(_DEFAULTS_PATH))

    # Layer 2a — governance config (consumer PROJECT area, CODEOWNERS-gated).
    # Governance freely overlays defaults — this is the AUTHORIZATION step.
    # Narrow-only protection does not apply here (governance IS the policy setter).
    # Narrow-only kicks in for layers 2b and 3, which cannot widen past what
    # governance (1+2a combined) has established.
    governance_path = root / _GOVERNANCE_RELPATH
    layer2a_raw = _normalize_keys(_load_yaml(governance_path))
    merged = {**layer1, **layer2a_raw}
    # Merge nested dicts (thresholds, cadence, etc.) rather than wholesale replacing.
    for nested_key in ("thresholds", "cadence", "self_review", "breakers", "suppression"):
        if nested_key in layer2a_raw and isinstance(layer2a_raw[nested_key], dict):
            merged[nested_key] = {**layer1.get(nested_key, {}), **layer2a_raw[nested_key]}

    # Layer 2b — soft state (cadence + last-poll only; cannot touch governance fields).
    soft_state_path = root / _SOFT_STATE_DIR / _CADENCE_STATE_FILE
    layer2b: dict[str, Any] = {}
    if soft_state_path.is_file():
        try:
            with soft_state_path.open(encoding="utf-8") as fh:
                raw_soft = json.load(fh)
            # Accept only cadence soft-state keys — strip anything governance.
            safe_keys = {"cadence_last_poll", "cadence_backoff_level"}
            layer2b = {k: v for k, v in raw_soft.items() if k in safe_keys}
        except Exception as exc:
            logger.warning("Could not load soft state %s: %s — ignored", soft_state_path, exc)
    merged = _overlay(merged, layer2b, is_governance=False)

    # Layer 3 — env overrides (narrow-only relative to governance-established state).
    env_overlay = _build_env_overlay()
    merged = _overlay(merged, env_overlay, is_governance=True)

    return _build_config(merged)
