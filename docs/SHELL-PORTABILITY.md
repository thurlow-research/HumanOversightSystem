# Shell Portability Rules

Canonical reference for portability constraints on HOS framework scripts.
Enforced by `scripts/oversight/gates/bash_check.sh` and the `shellcheck` CI workflow (#768).

---

## Target environments

| Environment | Shell | Version notes |
|---|---|---|
| macOS (default) | Bash | 3.2.57 (Apple ships Bash 3.2 due to GPLv3) |
| macOS (Homebrew) | Bash | 5.x (common on dev machines) |
| Linux (CI / prod) | Bash | 5.x (Ubuntu 22.04+) |
| GitHub Actions | Bash | 5.x |

**Rule:** every framework `.sh` file must run correctly on Bash 3.2 and later.

---

## Required shebang

```bash
#!/usr/bin/env bash    # preferred — PATH-resolved, portable
#!/bin/bash            # acceptable — explicit path
```

**Reject:** `#!/bin/sh` (POSIX sh, not bash), `#!/bin/zsh`, any other shell.

Scripts that are *sourced* rather than executed may use `# shellcheck shell=bash` as their first line in place of a shebang.

---

## Bash-4+ constructs to avoid

These constructs are present in Bash 4+ but absent (or broken) in Bash 3.2.

### Associative arrays (`declare -A`)

**Problem:** `declare -A foo` aborts on Bash 3.2.

**Portable replacements:**
- For dedup (is-item-in-set): iterate the existing array, or pipe through `sort -u`.
- For key→value lookup with small N: use a `case` statement or a positional-array pair.
- For large N: write to a temp file and use `grep -qF` for lookups.

```bash
# BAD
declare -A SEEN
[[ "${SEEN[$key]+x}" ]] && continue
SEEN["$key"]=1

# GOOD — linear search over existing array (fine for small N)
_in_array() {
    local _v
    for _v in ${1_ARRAY[@]+"${1_ARRAY[@]}"}; do
        [[ "$_v" == "$2" ]] && return 0
    done
    return 1
}
_in_array SAMPLE "$sha" && continue
```

### `mapfile` / `readarray`

**Problem:** `mapfile` and its alias `readarray` do not exist in Bash 3.2.

**Portable replacement:** `while IFS= read -r` loop.

```bash
# BAD
mapfile -t LINES < file.txt

# GOOD
LINES=()
while IFS= read -r _line; do
    [[ -n "$_line" ]] && LINES+=("$_line")
done < file.txt
```

### Case modification: `${var^^}` and `${var,,}`

**Problem:** `${var^^}` (uppercase) and `${var,,}` (lowercase) require Bash 4+.

**Portable replacement:** `tr` or `awk`.

```bash
# BAD
echo "${var^^}"
echo "${var,,}"

# GOOD
echo "$var" | tr '[:lower:]' '[:upper:]'
echo "$var" | tr '[:upper:]' '[:lower:]'
```

---

## Empty-array expansion under `set -u`

**Problem:** on Bash 3.2 with `set -u`, expanding an empty array aborts:
```bash
set -u
arr=()
echo "${arr[@]}"   # abort: arr: unbound variable
```

**Portable guard:**
```bash
for item in ${arr[@]+"${arr[@]}"}; do
    ...
done
```

The `+` operator returns the expansion only when `arr` is set and non-empty —
harmless on Bash 4+, essential on Bash 3.2.

---

## `mktemp` suffix portability

**Problem:** BSD `mktemp` (macOS) only randomises a *trailing* run of `X`s. A
suffix like `XXXXXX.md` is treated as a literal suffix and `X`s are not randomised,
producing a predictable temp name.

**Rule:** never append a suffix to a `mktemp` template. Use the randomised name
as-is, or rename after creation.

```bash
# BAD (predictable name on macOS)
tmp="$(mktemp "${TMPDIR:-/tmp}/hos.XXXXXX.md")"

# GOOD
tmp="$(mktemp "${TMPDIR:-/tmp}/hos.XXXXXX")"
```

---

## CI enforcement

- **`scripts/oversight/gates/bash_check.sh`** — local gate: shebang + Bash-4-unsafe constructs. Runs in the pre-PR inner loop.
- **`.github/workflows/shellcheck.yml`** — CI: `shellcheck --shell=bash --severity=warning` on all `*.sh` files. Blocks the PR.

Inline suppression for false-positives: `# shellcheck disable=SCxxxx` on the relevant line.
