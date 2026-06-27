"""Tests for scripts/migrate_audit_log_to_dir.sh — SPEC-888 / TD-888 P4 (T6).

The one-time migration lands a legacy single-file audit log
(oversight-log.jsonl) into the per-entry directory layout audit/log/<YYYY>/<MM>/
via the canonical writer. T6 pins the load-bearing properties:

  - round-trip clean: every migrated event is read back byte-identical, and the
    read-shim stream reconstructs the migrated history;
  - no loss / equal accounting, with identical legacy lines collapsing to one
    content-addressed record (deduped) — reported separately from line count;
  - idempotent: a second run writes nothing new and still succeeds;
  - historical time preserved: a record's shard/filename come from the event's
    OWN timestamp, never migration time;
  - coexistence: records already present under audit/log/ (written natively by
    the migrated live writers) survive and are neither lost nor miscounted;
  - fail-loud on a line with no parseable timestamp — no fabrication;
  - the source log is never deleted (workaround retirement owns that).
"""
import importlib.util
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "migrate_audit_log_to_dir.sh"
MODULE_PATH = REPO_ROOT / "scripts" / "oversight" / "lib" / "audit_log.py"

_spec = importlib.util.spec_from_file_location("audit_log_under_test", MODULE_PATH)
al = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(al)


# A small legacy-shaped fixture spanning two month shards, with a duplicate line.
LEGACY_EVENTS = [
    {"event": "cycle-start", "role": "worker", "timestamp": "2026-05-31T23:59:01Z"},
    {"event": "human-authorized-merge", "pr": 700, "timestamp": "2026-06-01T00:00:05Z"},
    {"event": "human-authorized-merge", "pr": 700, "timestamp": "2026-06-01T00:00:05Z"},  # dup
    {"event": "gate-suspended", "reason": "x", "timestamp": "2026-06-02T14:30:00Z"},
]


def _write_legacy(path: Path, events) -> None:
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )


def _run(log: Path, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), "--log", str(log), "--root", str(root)],
        capture_output=True, text=True,
    )


def _records(root: Path):
    return sorted((root / "audit" / "log").rglob("*.json"), key=lambda p: p.as_posix())


def test_migration_round_trips_clean_and_preserves_history(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    log = tmp_path / "oversight-log.jsonl"
    _write_legacy(log, LEGACY_EVENTS)

    res = _run(log, root)
    assert res.returncode == 0, res.stderr
    # 4 source lines, 3 unique records (the duplicate human-authorized-merge
    # collapses to one content-addressed file).
    assert "OK: 4 records migrated (3 unique), round-trip clean" in res.stdout

    recs = _records(root)
    assert len(recs) == 3

    # Historical time preserved: shard + filename come from each event's own
    # timestamp, including the May record that lands under a different month.
    rel = {p.relative_to(root / "audit" / "log").as_posix() for p in recs}
    assert any(r.startswith("2026/05/2026-05-31T235901Z-cycle-start-") for r in rel)
    assert any(r.startswith("2026/06/2026-06-01T000005Z-human-authorized-merge-") for r in rel)
    assert any(r.startswith("2026/06/2026-06-02T143000Z-gate-suspended-") for r in rel)

    # Read-shim stream reconstructs every distinct migrated event, byte-identical.
    stream = list(al.read_stream(str(root)))
    want = {al.canonical_bytes(e) for e in LEGACY_EVENTS}
    assert set(stream) == want

    # Source log is never deleted.
    assert log.exists()


def test_migration_is_idempotent(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    log = tmp_path / "oversight-log.jsonl"
    _write_legacy(log, LEGACY_EVENTS)

    assert _run(log, root).returncode == 0
    first = {p.read_bytes() for p in _records(root)}

    res2 = _run(log, root)
    assert res2.returncode == 0, res2.stderr
    second = {p.read_bytes() for p in _records(root)}
    assert second == first  # no new or changed records on re-run


def test_migration_coexists_with_native_records(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    # A record written natively by a live writer BEFORE migration runs.
    native = {"event": "cycle-wakeup", "timestamp": "2026-06-27T18:50:41Z"}
    al.write_event(native, root=str(root))
    native_bytes = al.canonical_bytes(native)

    log = tmp_path / "oversight-log.jsonl"
    _write_legacy(log, LEGACY_EVENTS)
    res = _run(log, root)
    assert res.returncode == 0, res.stderr
    # The native record is NOT counted among the migrated records.
    assert "OK: 4 records migrated (3 unique)" in res.stdout
    # ...and it still exists alongside the migrated history.
    assert native_bytes in set(al.read_stream(str(root)))
    assert len(_records(root)) == 4  # 3 migrated + 1 native


def test_migration_fails_loud_on_missing_timestamp(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    log = tmp_path / "oversight-log.jsonl"
    _write_legacy(log, [
        {"event": "cycle-start", "timestamp": "2026-06-01T00:00:00Z"},
        {"event": "no-time-here"},  # line 2: no timestamp
    ])

    res = _run(log, root)
    assert res.returncode == 1
    assert "line 2" in res.stderr
    # Atomic preflight: nothing was written before the bad line aborted the run.
    assert not (root / "audit" / "log").exists()


def test_missing_source_log_errors(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    res = _run(tmp_path / "does-not-exist.jsonl", root)
    assert res.returncode == 1
    assert "not found" in res.stderr
