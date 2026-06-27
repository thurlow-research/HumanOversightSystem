#!/usr/bin/env bash
# migrate_audit_log_to_dir.sh — THROWAWAY one-time migration (#888 P4 / TD-888 §7).
#
# Lands a legacy single-file audit log (the append-only oversight-log.jsonl) into
# the per-entry directory layout audit/log/<YYYY>/<MM>/ used since #888. Each
# legacy event is re-emitted through the SAME canonical writer
# (scripts/oversight/lib/audit_log.py :: write_event — the seam the
# `python3 -m scripts.oversight.lib.audit_log write` CLI wraps), so migrated
# records are byte-identical to freshly-written ones and idempotent on re-run.
#
# Properties (TD-888 §7):
#   - Historical time preserved: each record's filename/shard come from the
#     event's OWN `timestamp` field, never migration time. A line with no
#     parseable timestamp is a HARD ERROR naming the line — no silent fabrication.
#   - Idempotent: re-running writes nothing new (write-once, content-addressed).
#   - Round-trip checked: every migrated event is read back from the directory
#     and asserted byte-identical to its canonical source form.
#   - Does NOT delete the source log (workaround retirement / R6 owns deletion).
#   - Portable: no hard-coded repo path; --log / --root drive it. Run against a
#     CPS checkout by pointing --root at the CPS repo.
#
# Disposable: delete once HOS and CPS have both completed the #888 upgrade
# (close-out follow-up).
#
# Usage:
#   scripts/migrate_audit_log_to_dir.sh --log <path/to/oversight-log.jsonl> [--root <repo-root>]
set -euo pipefail

LOG=""
ROOT=""

usage() {
    echo "Usage: $0 --log <path/to/oversight-log.jsonl> [--root <repo-root>]" >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --log)
            [ $# -ge 2 ] || { usage; exit 2; }
            LOG="$2"; shift 2 ;;
        --root)
            [ $# -ge 2 ] || { usage; exit 2; }
            ROOT="$2"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "$0: unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$LOG" ]; then
    echo "$0: --log is required" >&2; usage; exit 2
fi
if [ ! -f "$LOG" ]; then
    echo "$0: source log not found: $LOG" >&2; exit 1
fi

# Resolve this repo (the one that contains the canonical helper) so `python3 -m`
# can import the package. This is the SCRIPT's repo, distinct from --root (the
# repo whose audit/log/ the records land in — they coincide for HOS itself).
_self_repo_root() {
    local d
    d="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [ "$d" != "/" ]; do
        if [ -f "$d/scripts/oversight/lib/audit_log.py" ]; then
            printf '%s' "$d"; return 0
        fi
        d="$(dirname "$d")"
    done
    echo "$0: could not locate scripts/oversight/lib/audit_log.py above this script" >&2
    exit 1
}
REPO="$(_self_repo_root)"

# --root defaults to the script's repo; resolve both to absolute paths.
[ -n "$ROOT" ] || ROOT="$REPO"
if [ ! -d "$ROOT" ]; then
    echo "$0: --root is not a directory: $ROOT" >&2; exit 1
fi
ROOT="$(cd "$ROOT" && pwd)"
LOG="$(cd "$(dirname "$LOG")" && pwd)/$(basename "$LOG")"

# The whole migration runs in one Python pass that reuses the canonical module
# (write_event / canonical_bytes / record_relpath — the seam the `write` CLI
# wraps): preflight (parse + require a real timestamp on every line, fail loud
# naming the offending line), then write_event() per event, then a round-trip
# read-back. One process makes preflight atomic — a bad line aborts before any
# record is written — while still going through exactly one serializer.
#
# argv: <source-log> <dest-root> <self-repo> (passed positionally to avoid any
# shell interpolation inside the quoted heredoc).
python3 - "$LOG" "$ROOT" "$REPO" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

src_log, dest_root, self_repo = sys.argv[1], sys.argv[2], sys.argv[3]

# Load the canonical helper by path — same module the live writers and the
# `python3 -m scripts.oversight.lib.audit_log write` CLI use.
_mod_path = Path(self_repo) / "scripts" / "oversight" / "lib" / "audit_log.py"
_spec = importlib.util.spec_from_file_location("audit_log_migration", _mod_path)
al = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(al)


def _fail(msg):
    sys.stderr.write("migrate_audit_log_to_dir: %s\n" % msg)
    sys.exit(1)


# ----- Parse + preflight: every line must be a JSON object with a parseable
# timestamp. Fail loud naming the line; never fabricate (TD-888 §7). -----
events = []  # (lineno, event_dict, normalized_ts)
for lineno, raw in enumerate(Path(src_log).read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        _fail("line %d: not valid JSON (%s)" % (lineno, exc))
    if not isinstance(event, dict):
        _fail("line %d: event is not a JSON object" % lineno)
    ts_raw = event.get("timestamp")
    if not (isinstance(ts_raw, str) and ts_raw.strip()):
        _fail("line %d: no parseable `timestamp` field — refusing to fabricate one" % lineno)
    try:
        ts = al.normalize_ts(ts_raw)
    except ValueError as exc:
        _fail("line %d: unparseable timestamp %r (%s)" % (lineno, ts_raw, exc))
    events.append((lineno, event, ts))

if not events:
    _fail("source log %s contained no events" % src_log)

# ----- Write each event through the canonical writer, threading its own ts so
# the record keeps its real time. Write-once + content-addressed => idempotent. -----
want = {}  # relpath -> canonical bytes (deduped; identical legacy lines collapse)
for lineno, event, ts in events:
    relpath = al.write_event(event, root=dest_root, ts=ts)
    want[relpath] = al.canonical_bytes(event)

# ----- Round-trip: read each migrated record back from disk and assert it is
# byte-identical to its canonical source form. This checks exactly the migrated
# events, so unrelated records already in audit/log/ (written natively by the
# migrated live writers) neither mask a loss nor cause a false failure. -----
log_dir = Path(dest_root) / "audit" / "log"
missing, mismatch = [], []
for relpath, data in want.items():
    rec = log_dir / relpath
    if not rec.is_file():
        missing.append(relpath)
    elif rec.read_bytes() != data:
        mismatch.append(relpath)

if missing or mismatch:
    for m in missing:
        sys.stderr.write("  missing after migration: %s\n" % m)
    for m in mismatch:
        sys.stderr.write("  byte mismatch after migration: %s\n" % m)
    _fail("round-trip FAILED (%d missing, %d mismatched)" % (len(missing), len(mismatch)))

print("OK: %d records migrated (%d unique), round-trip clean"
      % (len(events), len(want)))
PY
