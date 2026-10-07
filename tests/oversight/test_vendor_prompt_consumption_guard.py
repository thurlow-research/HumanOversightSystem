"""#1718 — vendor prompt consumption guard.

agy was measured silently truncating an oversized prompt while reporting
`status: SUCCESS`. Two defences are pinned here:

1. `vendor_invoke` refuses (class `harness`, detail `prompt_too_large`) any prompt
   over a per-vendor byte ceiling BEFORE launching the binary.
2. `run_second_review.sh` checks agy's own envelope `usage` against the bytes it
   sent (`second_review_logic.py consumption`) and fails closed on a material
   shortfall — including when a fake agy keeps only a prefix of stdin and still
   reports SUCCESS (the sentinel regression).

All hermetic: fake `agy`/`codex` stubs on PATH, no network, no real vendor. The
full-script tests use a minimal stub PATH that excludes `gh` (see
test_second_review_envelope_gate.py for why).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_second_review.sh"
_VENDOR_INVOKE_SH = _REPO_ROOT / "scripts" / "oversight" / "lib" / "vendor_invoke.sh"
_LOGIC = _REPO_ROOT / "scripts" / "oversight" / "second_review_logic.py"
_VALIDATION = _REPO_ROOT / "scripts" / "oversight" / "validation_logic.py"

_REQUIRED_BINS = [
    "bash", "python3", "git", "cat", "grep", "awk", "sed", "mkdir", "date", "head",
    "wc", "tr", "cut", "dirname", "mktemp", "rm", "env", "tail", "find", "timeout",
]

_APPROVE = {
    "reviewer": "agy",
    "lens": "correctness+spec",
    "findings": [],
    "verdict": "approve",
    "summary": "STUB-APPROVE-REVIEW",
}
_CODEX_APPROVE = {**_APPROVE, "reviewer": "codex", "lens": "security-adversarial"}


# ── helpers ───────────────────────────────────────────────────────────────────


def _stub_path(tmp_path: Path) -> Path:
    stub = tmp_path / "stub_bin"
    stub.mkdir(exist_ok=True)
    for b in _REQUIRED_BINS:
        real = shutil.which(b)
        assert real, f"required binary {b} unavailable"
        if not (stub / b).exists():
            (stub / b).symlink_to(real)
    return stub


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _agy_stub(
    stub: Path,
    tmp_path: Path,
    *,
    keep: int | None = None,
    usage: bool = True,
    cache_read: int | None = None,
) -> tuple[Path, Path, Path]:
    """A fake agy: reads stdin, keeps only the first `keep` bytes (all if None),
    records whether the sentinels survived and how often it ran, then emits an
    agy envelope with status SUCCESS and a valid approve review. When `usage`,
    input_tokens is proportionate to what it KEPT (4 bytes/token)."""
    side = tmp_path / "agy_side.json"
    counter = tmp_path / "agy_count.txt"
    marker = tmp_path / "agy_ran"
    _write_stub(
        stub / "agy",
        f"""#!/usr/bin/env python3
import json, sys
data = sys.stdin.buffer.read()
keep = {keep!r}
kept = data if keep is None else data[:keep]
open({str(marker)!r}, "w").write("ran")
with open({str(counter)!r}, "a") as fh:
    fh.write("x\\n")
json.dump({{
    "start": b"SENTINEL-START" in kept,
    "end": b"SENTINEL-END" in kept,
    "received": len(data),
    "kept": len(kept),
}}, open({str(side)!r}, "w"))
env = {{"status": "SUCCESS", "conversation_id": "c", "response": json.dumps({_APPROVE!r})}}
if {usage!r}:
    u = {{"input_tokens": max(len(kept) // 4, 1), "output_tokens": 50}}
    if {cache_read!r} is not None:
        u["cache_read_tokens"] = {cache_read!r}
    env["usage"] = u
sys.stdout.write(json.dumps(env))
""",
    )
    return side, counter, marker


def _codex_stub(stub: Path) -> None:
    _write_stub(
        stub / "codex",
        f"#!/usr/bin/env python3\nimport sys, json\nsys.stdin.buffer.read()\n"
        f"sys.stdout.write(json.dumps({_CODEX_APPROVE!r}))\n",
    )


def _make_target(tmp_path: Path, size: int) -> None:
    body = "SENTINEL-START\n" + "x = 1\n" * (size // 6) + "SENTINEL-END\n"
    (tmp_path / "target.py").write_text(body)


def _run(
    tmp_path: Path,
    stub: Path,
    *,
    tier: str = "MEDIUM",
    score: str = "0.5",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = {"PATH": str(stub), "HOME": str(tmp_path)}
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(_SCRIPT), "--files", "target.py", "--step", "1718",
         "--tier", tier, "--score", score],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=120, env=env,
    )


def _artifact(tmp_path: Path) -> str:
    matches = sorted((tmp_path / ".claudetmp" / "second-review").glob("step1718-*.md"))
    assert matches, "no second-review artifact written"
    return matches[-1].read_text()


def _agy_record(content: str) -> dict:
    m = re.search(r"## agy.*?```json\n(.*?)\n```", content, re.S)
    assert m, content
    return json.loads(m.group(1))


def _lib(tmp_path: Path, body: str, *, env: dict[str, str] | None = None,
         fake_bin: Path | None = None) -> subprocess.CompletedProcess:
    snippet = tmp_path / "snippet.sh"
    snippet.write_text(f'source "{_VENDOR_INVOKE_SH}"\n{body}\n')
    e = dict(os.environ)
    e.pop("VENDOR_INVOKE_MAX_BYTES_AGY", None)
    e.pop("VENDOR_INVOKE_MAX_BYTES_CODEX", None)
    e["TMPDIR"] = str(tmp_path)
    if fake_bin is not None:
        e["PATH"] = f"{fake_bin}:{e['PATH']}"
    e.update(env or {})
    return subprocess.run(["bash", str(snippet)], capture_output=True, text=True,
                          timeout=60, env=e)


def _invoke_snippet(vendor: str, nbytes: int) -> str:
    return f"""
f=$(vendor_invoke_tmpfile); o=$(vendor_invoke_tmpfile)
head -c {nbytes} /dev/zero | tr '\\0' x > "$f"
vendor_invoke {vendor} 10 "$f" "$o"
echo "rc=$? class=$VENDOR_INVOKE_CLASS detail=$VENDOR_INVOKE_DETAIL RC=[$VENDOR_INVOKE_RC] MAX=$VENDOR_INVOKE_MAX_BYTES BYTES=$VENDOR_INVOKE_BYTES"
"""


def _touch_stub(tmp_path: Path, name: str) -> tuple[Path, Path]:
    fake = tmp_path / "fake_bin"
    fake.mkdir(exist_ok=True)
    marker = tmp_path / f"{name}_marker"
    _write_stub(fake / name, f"#!/bin/sh\ncat > /dev/null\ntouch {marker}\necho launched\n")
    return fake, marker


# ── vendor_invoke ceiling ─────────────────────────────────────────────────────


def test_ceiling_refusal_never_launches_binary(tmp_path):
    fake, marker = _touch_stub(tmp_path, "agy")
    r = _lib(tmp_path, _invoke_snippet("agy", 180_001), fake_bin=fake)
    assert "rc=1 class=harness detail=prompt_too_large RC=[] MAX=180000" in r.stdout, (r.stdout, r.stderr)
    assert not marker.exists()
    assert "over the 180000-byte agy ceiling" in r.stderr


def test_ceiling_boundary_equal_passes(tmp_path):
    fake, marker = _touch_stub(tmp_path, "agy")
    r = _lib(tmp_path, _invoke_snippet("agy", 180_000), fake_bin=fake)
    assert "rc=0 class=ok" in r.stdout, (r.stdout, r.stderr)
    assert marker.exists()


def test_ceiling_applies_to_codex(tmp_path):
    fake, marker = _touch_stub(tmp_path, "codex")
    r = _lib(tmp_path, _invoke_snippet("codex", 1_048_577), fake_bin=fake)
    assert "rc=1 class=harness detail=prompt_too_large RC=[] MAX=1048576" in r.stdout, (r.stdout, r.stderr)
    assert not marker.exists()


def test_codex_400kb_prompt_is_launched(tmp_path):
    """Pins AR-1: codex must not regress to the 180,000-byte agy ceiling."""
    fake, marker = _touch_stub(tmp_path, "codex")
    r = _lib(tmp_path, _invoke_snippet("codex", 400_000), fake_bin=fake)
    assert "rc=0 class=ok" in r.stdout and "MAX=1048576" in r.stdout, (r.stdout, r.stderr)
    assert marker.exists()


def test_max_bytes_helper_is_single_source(tmp_path):
    r = _lib(tmp_path, 'vendor_invoke_max_bytes agy; vendor_invoke_max_bytes codex; '
                       'vendor_invoke_max_bytes bogus; echo "rc=$?"')
    assert r.stdout.split() == ["180000", "1048576", "rc=1"], (r.stdout, r.stderr)


def test_unknown_vendor_has_empty_max_bytes(tmp_path):
    r = _lib(tmp_path, _invoke_snippet("bogus", 10))
    assert "detail=unknown_vendor" in r.stdout and "MAX=" in r.stdout
    assert re.search(r"MAX= ", r.stdout), r.stdout


def test_env_may_lower_ceiling(tmp_path):
    fake, marker = _touch_stub(tmp_path, "agy")
    r = _lib(tmp_path, _invoke_snippet("agy", 1_001),
             env={"VENDOR_INVOKE_MAX_BYTES_AGY": "1000"}, fake_bin=fake)
    assert "detail=prompt_too_large" in r.stdout and "MAX=1000" in r.stdout, (r.stdout, r.stderr)
    assert not marker.exists()


def test_env_cannot_raise_ceiling(tmp_path):
    r = _lib(tmp_path, "vendor_invoke_max_bytes agy",
             env={"VENDOR_INVOKE_MAX_BYTES_AGY": "10000000"})
    assert r.stdout.strip() == "180000"
    assert "ignoring VENDOR_INVOKE_MAX_BYTES_AGY=10000000" in r.stderr


def test_env_malformed_ceiling_keeps_default(tmp_path):
    for bad in ("abc", "0", "-5", "1.5", "99999999999999999999999"):
        r = _lib(tmp_path, "vendor_invoke_max_bytes codex",
                 env={"VENDOR_INVOKE_MAX_BYTES_CODEX": bad})
        assert r.stdout.strip() == "1048576", (bad, r.stdout, r.stderr)
        assert "ignoring VENDOR_INVOKE_MAX_BYTES_CODEX" in r.stderr, bad


def test_lowered_ceiling_named_in_refusal(tmp_path):
    fake, _ = _touch_stub(tmp_path, "agy")
    r = _lib(tmp_path, _invoke_snippet("agy", 1_001),
             env={"VENDOR_INVOKE_MAX_BYTES_AGY": "1000"}, fake_bin=fake)
    assert "(lowered by VENDOR_INVOKE_MAX_BYTES_AGY)" in r.stderr, r.stderr
    r = _lib(tmp_path, _invoke_snippet("agy", 180_001), fake_bin=fake)
    assert "lowered by" not in r.stderr, r.stderr


# ── run_second_review.sh end to end ──────────────────────────────────────────


def test_second_review_oversized_diff_fails_closed(tmp_path):
    _make_target(tmp_path, 200_000)
    stub = _stub_path(tmp_path)
    _, _, marker = _agy_stub(stub, tmp_path)
    r = _run(tmp_path, stub)
    assert r.returncode == 1, (r.stdout, r.stderr)
    rec = _agy_record(_artifact(tmp_path))
    assert rec["outcome_detail"] == "prompt_too_large"
    assert rec["failure_class"] == "harness"
    assert rec["prompt_ceiling_bytes"] == 180000
    assert "Input-size failure (#1718)" in r.stderr
    assert "--files" in rec["summary"] and "Do NOT narrow" in rec["summary"]
    assert not marker.exists(), "agy must never be launched"


def test_truncating_stub_fails_closed(tmp_path):
    """The sentinel regression: agy keeps a prefix, drops the end sentinel, and
    still reports SUCCESS with input_tokens proportionate to what it kept."""
    _make_target(tmp_path, 150_000)
    stub = _stub_path(tmp_path)
    side, _, _ = _agy_stub(stub, tmp_path, keep=50_000)
    r = _run(tmp_path, stub)
    seen = json.loads(side.read_text())
    assert seen["start"] is True and seen["end"] is False, seen
    assert r.returncode == 1, (r.stdout, r.stderr)
    content = _artifact(tmp_path)
    rec = _agy_record(content)
    assert rec["outcome_detail"] == "prompt_not_consumed"
    assert rec["failure_class"] == "vendor"
    assert rec["verdict"] == "error"
    assert "STUB-APPROVE-REVIEW" not in content
    assert "verdict: error" in content


def test_not_consumed_is_not_retried(tmp_path):
    _make_target(tmp_path, 150_000)
    stub = _stub_path(tmp_path)
    _, counter, _ = _agy_stub(stub, tmp_path, keep=50_000)
    _run(tmp_path, stub)
    assert len(counter.read_text().split()) == 1


def test_not_consumed_record_carries_consumption(tmp_path):
    _make_target(tmp_path, 150_000)
    stub = _stub_path(tmp_path)
    _agy_stub(stub, tmp_path, keep=50_000)
    _run(tmp_path, stub)
    rec = _agy_record(_artifact(tmp_path))
    assert rec["consumption"]["status"] == "not_consumed"
    assert rec["consumption"]["input_tokens"] == 12_500
    assert rec["consumption"]["bytes_per_token"] > 6.0


def test_full_consumption_passes(tmp_path):
    _make_target(tmp_path, 150_000)
    stub = _stub_path(tmp_path)
    side, _, _ = _agy_stub(stub, tmp_path)
    r = _run(tmp_path, stub)
    seen = json.loads(side.read_text())
    assert seen["start"] and seen["end"]
    assert r.returncode == 0, (r.stdout, r.stderr)
    content = _artifact(tmp_path)
    assert "verdict: approve" in content
    assert "Prompt consumption unverified" not in content


def test_missing_usage_is_unverified_not_failed(tmp_path):
    _make_target(tmp_path, 1_000)
    stub = _stub_path(tmp_path)
    _agy_stub(stub, tmp_path, usage=False)
    r = _run(tmp_path, stub)
    assert r.returncode == 0, (r.stdout, r.stderr)
    content = _artifact(tmp_path)
    assert "Prompt consumption unverified" in content
    assert "verdict: approve" in content
    assert '"status": "verified"' not in content


def test_codex_fallback_records_unverified_advisory(tmp_path):
    """HIGH tier, agy absent: codex runs as the fallback."""
    _make_target(tmp_path, 1_000)
    stub = _stub_path(tmp_path)
    _codex_stub(stub)
    r = _run(tmp_path, stub, tier="HIGH", score="0.9")
    assert r.returncode == 0, (r.stdout, r.stderr)
    content = _artifact(tmp_path)
    assert "codex_no_usage_envelope" in content
    assert '"prompt_ceiling_bytes": 1048576' in content
    assert '"status": "verified"' not in content


def test_codex_advisory_never_verified_primary_and_fallback(tmp_path):
    for name, with_agy in (("fallback", False), ("primary", True)):
        run_dir = tmp_path / name
        run_dir.mkdir()
        _make_target(run_dir, 1_000)
        stub = _stub_path(run_dir)
        _codex_stub(stub)
        if with_agy:
            _agy_stub(stub, run_dir)
        r = _run(run_dir, stub, tier="HIGH", score="0.9")
        assert r.returncode == 0, (name, r.stdout, r.stderr)
        content = _artifact(run_dir)
        assert "codex_no_usage_envelope" in content, name
        assert '"status": "verified"' not in content, name


def _header(text: str) -> dict[str, str]:
    out = {}
    for line in text.split("## ", 1)[0].splitlines():
        if ": " in line:
            k, _, v = line.partition(": ")
            out[k.strip()] = v.strip()
    return out


def test_advisory_block_is_verdict_inert(tmp_path):
    """AR-5: appending the advisory changes neither the aggregate nor the
    validation_logic verdict/severity/counts, and its fence is not ```json."""
    _make_target(tmp_path, 1_000)
    stub = _stub_path(tmp_path)
    _agy_stub(stub, tmp_path, usage=False)
    r = _run(tmp_path, stub)
    assert r.returncode == 0, (r.stdout, r.stderr)
    with_block = _artifact(tmp_path)
    m = re.search(r"## \[ADVISORY\] Prompt consumption unverified \(#1718\)\n(.*?)\n\n?$", with_block, re.S)
    assert m, with_block
    block = m.group(0)
    assert block.splitlines()[1] == "```", block
    assert "```json" not in block
    payload = json.loads(block.splitlines()[2])
    assert not {"verdict", "findings", "attacks", "error"} & set(payload)
    without_block = with_block.replace(block, "")
    assert "Prompt consumption unverified" not in without_block

    results = []
    for i, text in enumerate((with_block, without_block)):
        f = tmp_path / f"copy{i}.md"
        f.write_text(text)
        subprocess.run(["python3", str(_LOGIC), "aggregate", "--file", str(f)], check=True,
                       capture_output=True)
        subprocess.run(["python3", str(_VALIDATION), "process", "--file", str(f),
                        "--ledger", str(tmp_path / f"ledger{i}.json"), "--strict-empty"],
                       check=True, capture_output=True)
        results.append(_header(f.read_text()))
    assert results[0] == results[1], results
    assert results[0].get("verdict") == "approve"
