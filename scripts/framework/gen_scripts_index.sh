#!/usr/bin/env bash
# gen_scripts_index.sh — generate SCRIPTS-INDEX.md, a directory-grouped index of
# every script and library module under bin/ (top-level), bootstrap/ (top-level),
# and scripts/ (recursive, including scripts/automation/lib/*.py), with a
# one-line description pulled from each file's header comment (.sh) or module
# docstring (.py).
#
# Precedent: scripts/framework/gen_codeowners.sh (generated-file convention —
# same header style, same "do not edit by hand" contract). This index exists so
# an agent can search for existing tooling before proposing new tooling (#1214,
# CLAUDE.md "Shell usage under the sandbox" → "What to do instead").
#
# Usage:
#   ./scripts/framework/gen_scripts_index.sh [OUTPUT_PATH]
#   OUTPUT_PATH defaults to SCRIPTS-INDEX.md at the repo root. An explicit path
#   (e.g. a temp file) lets a freshness test diff generator output against the
#   committed file without touching the working tree.
set -euo pipefail

# Force byte-order collation for every `sort` below, regardless of the caller's
# locale (#1494): under en_US.UTF-8, `sort` treats punctuation as low-weight
# (e.g. "run_redteam_sample.sh" collates before "run_red_team.sh"), but under
# C/POSIX (GitHub's hosted-runner default) the same input sorts the other way.
# A generator whose output order depends on the invoking machine's locale
# makes the freshness test (tests/framework/test_scripts_index.py) fail
# non-deterministically on content that hasn't actually changed.
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

OUT="${1:-SCRIPTS-INDEX.md}"

# ── Collect candidate files ───────────────────────────────────────────────────
# bin/ and bootstrap/ are scanned top-level only (their lib/ subdirs are internal
# helpers sourced by the top-level entry points, not separate invocation sites).
# scripts/ is scanned recursively, which covers scripts/automation/lib/*.py.
mapfile -t FILES < <(
  {
    find bin -maxdepth 1 -type f
    find bootstrap -maxdepth 1 -type f -name '*.sh'
    find scripts \( -path '*/.venv' -o -path '*/__pycache__' \) -prune -o \
      -type f \( -name '*.sh' -o -name '*.py' \) -print
  } | sed "s|^\./||" | sort -u
)

is_excluded() {
  local rel="$1" base
  base="$(basename "$rel")"
  case "$base" in
    # smoke_test.sh is an operational health-check script (cited by name in
    # CLAUDE.md's own examples), not a unit test file — carve it out before the
    # *_test.sh guard below, which exists to catch actual test scripts.
    smoke_test.sh) return 1 ;;
    test_*.py|*_test.sh|__init__.py) return 0 ;;
  esac
  case "$rel" in
    *__pycache__*|*.pyc) return 0 ;;
  esac
  return 1
}

# ── Description extraction ────────────────────────────────────────────────────
# .sh: the first paragraph of the "#" header comment block after the shebang —
# consecutive non-blank "#" lines, joined with spaces, terminated by a blank
# comment line ("#" alone) or the end of the comment block. Many headers in
# this repo wrap their description sentence across multiple physical comment
# lines; joining the whole paragraph avoids mid-sentence truncation (#1214).
# .py: the first paragraph of the module docstring — lines up to the first
# blank line, joined with spaces.
# Either way, a leading "<basename-or-relpath> —/--" repeat of the file's own
# path is stripped so the index doesn't say the path twice per entry.
describe() {
  python3 - "$1" <<'PYEOF'
import ast
import os
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()


def strip_prefix(line, path):
    base = os.path.basename(path)
    for prefix in (path, base):
        if line.startswith(prefix):
            rest = line[len(prefix):].lstrip()
            for sep in ("—", "--", "-"):
                if rest.startswith(sep):
                    return rest[len(sep):].strip()
    return line


line = ""
if path.endswith(".py"):
    try:
        doc = ast.get_docstring(ast.parse(text))
    except SyntaxError:
        doc = None
    if doc:
        paragraph = []
        for raw in doc.strip("\n").splitlines():
            s = raw.strip()
            if not s:
                break  # blank line ends the first paragraph
            paragraph.append(s)
        line = " ".join(paragraph)
else:
    lines = text.splitlines()
    start = 1 if lines and lines[0].startswith("#!") else 0
    paragraph = []
    in_header = False
    for raw in lines[start:start + 20]:
        s = raw.strip()
        if not in_header:
            if not s:
                continue  # skip blank lines before the header comment begins
            if not s.startswith("#"):
                break  # first non-comment, non-blank line — no header comment
            in_header = True
        elif not s.startswith("#"):
            break  # comment block ended
        content = s.lstrip("#").strip()
        if not content:
            break  # blank comment line ends the paragraph
        paragraph.append(content)
    line = " ".join(paragraph)

print(strip_prefix(line, path) if line else "")
PYEOF
}

# ── Group by directory, build the doc ─────────────────────────────────────────
declare -A GROUPED
for f in "${FILES[@]}"; do
  is_excluded "$f" && continue
  dir="$(dirname "$f")/"
  desc="$(describe "$f")"
  [[ -z "$desc" ]] && desc="(no description)"
  GROUPED["$dir"]+="${f}"$'\t'"${desc}"$'\n'
done

mapfile -t DIRS < <(printf '%s\n' "${!GROUPED[@]}" | sort)

{
  echo "# SCRIPTS-INDEX.md"
  echo ""
  echo "GENERATED — do not edit by hand. Run \`scripts/framework/gen_scripts_index.sh\`"
  echo "to regenerate."
  echo ""
  echo "A script's absence from this index means **verify it doesn't exist**"
  echo "(search \`scripts/\`, \`bootstrap/\`, \`bin/\`), not that it doesn't exist —"
  echo "this index can lag; regenerate with \`scripts/framework/gen_scripts_index.sh\`"
  echo "if in doubt."
  echo ""
  echo "Scope: \`bin/\` (top-level), \`bootstrap/\` (top-level), \`scripts/\` (recursive,"
  echo "including \`scripts/automation/lib/*.py\`). Test files, \`__pycache__\`, and"
  echo "non-executable data files (\`.txt\`, \`.jq\`, \`.md\`, \`.env*\`, \`.template\`) are"
  echo "excluded."
  for dir in "${DIRS[@]}"; do
    echo ""
    echo "## ${dir}"
    echo ""
    while IFS=$'\t' read -r path desc; do
      [[ -z "$path" ]] && continue
      echo "- \`${path}\` — ${desc}"
    done < <(printf '%s' "${GROUPED[$dir]}" | sort)
  done
} > "$OUT"

echo "Generated $OUT (${#FILES[@]} candidate files scanned)"
