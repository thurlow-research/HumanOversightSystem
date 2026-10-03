"""Shared helpers for the #1944 usage-pause tests (S1)."""

import hashlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "bin" / "lib" / "usage_pause.py"
POLLER = ROOT / "bin" / "hos-usage-poll"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "usage"


def _load():
    spec = importlib.util.spec_from_file_location("usage_pause", LIB)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["usage_pause"] = module
    spec.loader.exec_module(module)
    return module


up = sys.modules.get("usage_pause") or _load()


def fx(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_fixture(name: str):
    """(EnvelopeResult, ParseResult) for an envelope fixture."""
    env = up.parse_envelope(fx(name))
    assert env.ok, env.reason
    return env, up.parse_usage(env.result_text)


def settings(**overrides):
    """A SettingsResult with defaults plus overrides (status 'valid')."""
    values = dict(up.DEFAULTS)
    values.update(overrides)
    return up.SettingsResult(values, "valid", None, None)


def reading(now=1_000_000, **overrides):
    """A ReadingRead(ok) for a fresh successful reading; None omits a key."""
    fields = {
        "kind": "reading",
        "run_epoch": str(now),
        "outcome": "success",
        "session_pct": "6",
        "weekly_all_pct": "48",
        "weekly_model_fable_name": "Fable",
        "weekly_model_fable_pct": "3",
    }
    for key, value in overrides.items():
        if value is None:
            fields.pop(key, None)
        else:
            fields[key] = str(value)
    return up.ReadingRead("ok", fields)
