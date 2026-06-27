"""Tests for scripts/oversight/lib/audit_log.{py,sh} — SPEC-888 / TD-888 P1.

Covers the load-bearing properties of the per-entry audit-log helper:
  - T1  read-shim equivalence: write_event -> read_stream round-trips the event
        stream chronologically, and legacy-shaped events survive canonicalization
        with identical JSON semantics (the no-regression guarantee for readers).
  - T3  conflict-free merge: two branches each writing a distinct record merge
        with zero conflicts and both records present.
  - T4  cross-month-shard ordering: a plain path sort is chronological across a
        month boundary, independent of write order.
  - T5  Bash/Python writer parity: both facades produce a byte-identical record
        (same path, same content) for the same event.
plus idempotency, the empty-directory contract, and timestamp normalization.
"""
import importlib.util
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "oversight" / "lib" / "audit_log.py"
BASH_LIB = REPO_ROOT / "scripts" / "oversight" / "lib" / "audit_log.sh"

_spec = importlib.util.spec_from_file_location("audit_log_under_test", MODULE_PATH)
al = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(al)


def _records(root: Path) -> list[Path]:
    return sorted((root / "audit" / "log").rglob("*.json"), key=lambda p: p.as_posix())


# --------------------------------------------------------------------------- #
# Canonical serialization
# --------------------------------------------------------------------------- #

def test_canonical_bytes_is_sorted_compact_and_newline_terminated():
    out = al.canonical_bytes({"event": "x", "b": 2, "a": 1})
    assert out == b'{"a":1,"b":2,"event":"x"}\n'


def test_canonical_bytes_is_reader_compatible_compact_json():
    # step_range.sh greps for `"event":"..."`, `"step":N[,}]`, `"head_sha":"..."`
    # against compact (no-space) JSON. sort_keys may place `step` last, so the
    # `[,}]` field-delimiter (comma OR closing brace) is what makes the grep
    # portable — assert against that contract, not a literal trailing comma.
    import re

    out = al.canonical_bytes(
        {"event": "step-head-final", "step": 2, "head_sha": "abc"}
    ).decode()
    assert '"event":"step-head-final"' in out
    assert re.search(r'"step":2[,}]', out)
    assert '"head_sha":"abc"' in out


# --------------------------------------------------------------------------- #
# Timestamp grammar (SPEC §6)
# --------------------------------------------------------------------------- #

def test_normalize_ts_accepts_grammar_and_colon_forms():
    assert al.normalize_ts("2026-06-26T143000Z") == "2026-06-26T143000Z"
    assert al.normalize_ts("2026-06-26T14:30:00Z") == "2026-06-26T143000Z"
    assert al.normalize_ts("2026-06-26T14:30:00+00:00") == "2026-06-26T143000Z"
    # non-UTC offset is converted to UTC
    assert al.normalize_ts("2026-06-26T16:30:00+02:00") == "2026-06-26T143000Z"


def test_relpath_derives_shards_from_timestamp_not_a_clock():
    event = {"event": "gate suspended!", "timestamp": "2026-05-30T23:59:59Z"}
    rel = al.record_relpath(event, "2026-05-30T235959Z")
    assert rel.startswith("2026/05/2026-05-30T235959Z-gate-suspended-")
    assert rel.endswith(".json")
    # 12-hex disambiguator
    assert len(rel.rsplit("-", 1)[1][: -len(".json")]) == 12


def test_filename_ts_defaults_to_event_timestamp():
    event = {"event": "e", "timestamp": "2026-05-30T23:59:59Z"}
    rel = al.record_relpath(event, al._resolve_ts(event, None))
    assert rel.startswith("2026/05/2026-05-30T235959Z-")


# --------------------------------------------------------------------------- #
# T1 — read-shim equivalence
# --------------------------------------------------------------------------- #

def test_read_stream_roundtrips_in_chronological_order(tmp_path):
    events = [
        {"event": "cycle-start", "role": "worker", "timestamp": "2026-06-23T20:05:55Z"},
        {"event": "step-head", "step": 1, "head_sha": "a", "timestamp": "2026-06-23T20:06:00Z"},
        {"event": "step-head-final", "step": 1, "head_sha": "b", "timestamp": "2026-06-23T20:07:00Z"},
    ]
    # write out of order to prove ordering comes from the path, not write order
    for e in (events[2], events[0], events[1]):
        al.write_event(e, root=str(tmp_path))
    stream = b"".join(al.read_stream(str(tmp_path)))
    expected = b"".join(al.canonical_bytes(e) for e in events)
    assert stream == expected


def test_legacy_shaped_events_survive_canonicalization(tmp_path):
    # Legacy lines have spaces and insertion-order keys; the read-shim must
    # preserve JSON semantics (every field, same values) for readers.
    legacy = [
        {"event": "human-authorized-merge", "pr": 866, "merged_by": "ScottThurlow",
         "timestamp": "2026-06-23T20:14:25Z"},
        {"event": "cycle-start", "role": "worker", "timestamp": "2026-06-23T20:05:55Z",
         "bot": "hos-overseer-hos[bot] project=hos"},
    ]
    for e in legacy:
        al.write_event(e, root=str(tmp_path))
    recovered = [json.loads(b) for b in al.read_stream(str(tmp_path))]
    # same set of events, semantics intact (order is chronological)
    assert sorted(recovered, key=lambda d: d["timestamp"]) == \
        sorted(legacy, key=lambda d: d["timestamp"])


# --------------------------------------------------------------------------- #
# Write-once / idempotency
# --------------------------------------------------------------------------- #

def test_write_is_idempotent(tmp_path):
    event = {"event": "e", "n": 1, "timestamp": "2026-06-26T14:30:00Z"}
    r1 = al.write_event(event, root=str(tmp_path))
    r2 = al.write_event(event, root=str(tmp_path))
    assert r1 == r2
    assert len(_records(tmp_path)) == 1


def test_empty_directory_yields_empty_stream(tmp_path):
    assert list(al.read_stream(str(tmp_path))) == []


# --------------------------------------------------------------------------- #
# T4 — cross-month-shard ordering
# --------------------------------------------------------------------------- #

def test_cross_month_shard_ordering(tmp_path):
    june = {"event": "e", "n": 2, "timestamp": "2026-06-01T00:00:00Z"}
    may = {"event": "e", "n": 1, "timestamp": "2026-05-31T23:59:59Z"}
    al.write_event(june, root=str(tmp_path))  # written first
    al.write_event(may, root=str(tmp_path))
    order = [json.loads(b)["n"] for b in al.read_stream(str(tmp_path))]
    assert order == [1, 2]  # May sorts before June despite write order
    paths = [p.as_posix() for p in _records(tmp_path)]
    assert "/2026/05/" in paths[0]
    assert "/2026/06/" in paths[1]


# --------------------------------------------------------------------------- #
# T5 — Bash/Python writer parity
# --------------------------------------------------------------------------- #

def test_bash_python_writer_parity(tmp_path):
    event = {"event": "gate suspended!", "reason": "x", "timestamp": "2026-05-30T23:59:59Z"}
    py_root = tmp_path / "py"
    sh_root = tmp_path / "sh"
    py_root.mkdir()
    sh_root.mkdir()

    py_rel = al.write_event(event, root=str(py_root))

    script = f'. "{BASH_LIB}"; audit_write_event \'{json.dumps(event)}\' "{sh_root}"'
    res = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, cwd=str(REPO_ROOT)
    )
    assert res.returncode == 0, res.stderr
    sh_rel = res.stdout.strip()

    assert py_rel == sh_rel, "Bash and Python writers disagree on the record path"
    py_bytes = (py_root / "audit" / "log" / py_rel).read_bytes()
    sh_bytes = (sh_root / "audit" / "log" / sh_rel).read_bytes()
    assert py_bytes == sh_bytes, "Bash and Python writers disagree on record content"


def test_cli_write_then_read(tmp_path):
    event = {"event": "e", "step": 3, "timestamp": "2026-06-26T14:30:00Z"}
    w = subprocess.run(
        ["python3", "-m", "scripts.oversight.lib.audit_log", "write", str(tmp_path)],
        input=json.dumps(event), capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert w.returncode == 0, w.stderr
    r = subprocess.run(
        ["python3", "-m", "scripts.oversight.lib.audit_log", "read", str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == event


# --------------------------------------------------------------------------- #
# T3 — conflict-free merge property
# --------------------------------------------------------------------------- #

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        cwd=str(repo), capture_output=True, text=True,
    )


def test_two_branches_merge_without_conflict(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    (repo / "README").write_text("base\n")
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-q", "-m", "base").returncode == 0
    assert _git(repo, "branch", "base").returncode == 0

    # Branch A writes one record.
    _git(repo, "checkout", "-q", "-b", "branch-a", "base")
    al.write_event({"event": "e", "who": "a", "timestamp": "2026-06-26T14:30:00Z"},
                   root=str(repo))
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-q", "-m", "a").returncode == 0

    # Branch B (from base) writes a different record.
    _git(repo, "checkout", "-q", "-b", "branch-b", "base")
    al.write_event({"event": "e", "who": "b", "timestamp": "2026-06-26T14:30:01Z"},
                   root=str(repo))
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-q", "-m", "b").returncode == 0

    # Merge B into A — must be conflict-free.
    _git(repo, "checkout", "-q", "branch-a")
    merge = _git(repo, "merge", "--no-edit", "branch-b")
    assert merge.returncode == 0, f"merge conflicted:\n{merge.stdout}\n{merge.stderr}"
    assert len(_records(repo)) == 2  # both records present after merge
