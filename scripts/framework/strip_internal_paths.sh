#!/usr/bin/env bash
# strip_internal_paths.sh — strip HOS-internal-path lines from CORE regions of
# agent files before they are shipped to consumers.
#
# Reads the prefix list from scripts/framework/installer-internal-paths.txt.
# For each .claude/agents/*.md file passed as an argument (or all in TARGET_DIR),
# strips lines that (a) are inside a CORE region and (b) contain any listed
# prefix as a substring.  Collapses adjacent blank lines within CORE regions
# to a single blank line.  Idempotent: a second pass on an already-stripped file
# produces identical output.
#
# Usage:
#   strip_internal_paths.sh <file> [<file> ...]
#   strip_internal_paths.sh --dir <dir>   # strip all *.md files under <dir>
#
# Also callable from cut_release.sh before SHA256SUMS generation so the
# recorded CORE hash matches the stripped installed CORE (§1 OQ-1 option a).
#
# Exit 0 always (informational only — stripping a line is never fatal).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIXES_FILE="${SCRIPT_DIR}/installer-internal-paths.txt"

if [[ ! -f "$PREFIXES_FILE" ]]; then
  echo "[path-cleanup] WARNING: prefixes file not found: $PREFIXES_FILE — skipping strip" >&2
  exit 0
fi

# Collect files to process.
_files=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      _dir="${2:?--dir requires a directory path}"
      shift 2
      while IFS= read -r -d '' _f; do
        _files+=("$_f")
      done < <(find "$_dir" -name "*.md" -type f -print0 2>/dev/null)
      ;;
    *)
      _files+=("$1")
      shift
      ;;
  esac
done

if [[ ${#_files[@]} -eq 0 ]]; then
  echo "[path-cleanup] No files to process." >&2
  exit 0
fi

# The strip logic is implemented in Python (stdlib only) to handle the three
# requirements cleanly: region-state tracking, substring-contains test, and
# adjacent-blank-line collapse within CORE — impossible to do safely in one sed.
python3 - "$PREFIXES_FILE" "${_files[@]}" <<'PYEOF'
import sys
import re
from pathlib import Path

prefixes_file = sys.argv[1]
files = sys.argv[2:]

# Load prefixes (skip blank lines and # comments).
prefixes = []
for line in Path(prefixes_file).read_text().splitlines():
    stripped = line.strip()
    if stripped and not stripped.startswith("#"):
        prefixes.append(stripped)

if not prefixes:
    sys.exit(0)

CORE_START = "<!-- HOS:CORE:START -->"
CORE_END   = "<!-- HOS:CORE:END -->"

def strip_file(path: Path) -> int:
    """Strip internal-path lines from CORE regions.  Returns count of removed lines."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    out = []
    in_core = False
    removed = 0
    prev_blank = False   # for adjacent-blank-line collapse within CORE

    for line in lines:
        stripped = line.rstrip("\n").rstrip("\r")

        # Region-transition detection (markers are ALWAYS kept, never stripped).
        if CORE_START in stripped:
            in_core = True
            out.append(line)
            prev_blank = False
            continue
        if CORE_END in stripped:
            in_core = False
            out.append(line)
            prev_blank = False
            continue

        if in_core:
            # Check whether this line contains any internal-path prefix.
            if any(p in stripped for p in prefixes):
                removed += 1
                continue  # drop the line

            # Collapse adjacent blank lines within CORE (REQ-P-02, CORE-scoped).
            is_blank = stripped == ""
            if is_blank and prev_blank:
                # Skip this blank — it would create a run of >1 consecutive blanks.
                continue
            prev_blank = is_blank
        else:
            # Outside CORE: pass through unchanged (REQ-P-03).
            prev_blank = False

        out.append(line)

    new_text = "".join(out)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return removed

for f in files:
    p = Path(f)
    if not p.is_file():
        continue
    n = strip_file(p)
    if n > 0:
        print(f"[path-cleanup] {p.name}: removed {n} internal-path line(s)")
PYEOF
