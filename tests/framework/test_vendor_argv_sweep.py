"""Mechanical reintroduction check for #1364 — the content-into-argv (E2BIG)
bug class, and the durable-prevention half of that issue's acceptance criteria.

#1364's core insight is that this bug class **arms itself through unrelated
growth**: no code change is needed to break a working script, because the
trigger is the assembled content crossing Linux's per-argument
`MAX_ARG_STRLEN` (131,072 bytes). `getconf ARG_MAX` reports 2,097,152 here and
is falsely reassuring — that limit covers the whole argv+env block, not one
argument. Past the per-argument cap, `execve` fails with `E2BIG` *before* the
target binary starts, so the failure precedes auth, model resolution and the
network — everything an operator would think to check first.

`scripts/oversight/lib/vendor_invoke.sh` makes reintroduction impossible
*through that function* (its D-2 runtime guard rejects any prompt content
reaching argv). This file closes the complementary gap: a **new** call site
that bypasses `vendor_invoke` entirely and writes `agy -p "$PROMPT"` again.
That is exactly how #1362 happened, and a one-time sweep cannot prevent it.

Style and exemption-ledger convention follow
`tests/framework/test_agent_invocation_migration.py` T4.1: scan CODE lines only
(comments and docs legitimately name the old constructs for explanatory
context), and keep exemptions in an explicit set asserted for equality — so a
landing slice shrinks the set and tightens the assertion automatically, rather
than letting a stale allowlist silently widen it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "node_modules"}


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDED_PARTS for part in path.parts)


def _code_lines(path: Path):
    """Yield (lineno, line) for every non-comment-only line in `path`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        yield lineno, line


def _iter_shell_files(*root_dirs):
    for root_dir in root_dirs:
        base = ROOT / root_dir
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_dir() or _is_excluded(path):
                continue
            if path.suffix == ".sh" or (path.suffix == "" and path.is_file()):
                yield path


# ── The bug-class patterns ────────────────────────────────────────────────────
# A vendor CLI, AT COMMAND POSITION, receiving a shell variable or a command
# substitution as its prompt argument. `"$(cat ...)"` is the canonical form (it
# defeats the very tmpfile the script just wrote), but a bare `"$PROMPT"`
# holding accumulated content is equally at risk and is what every site fixed
# under #1364 actually looked like.
#
# The command-position prefix is what keeps this honest. Without it the pattern
# also matches `vendor_invoke agy "$TIMEOUT" ...` — the CORRECT, migrated form,
# where `agy` is an argument naming the vendor rather than the binary being
# launched — and the check would block the migration it exists to enforce.
# `test_the_sweep_would_actually_catch_a_reintroduction` pins both directions.
_VENDOR_ARGV_PATTERN = re.compile(
    r"""
    (?:^|\$\(|[|&;`(]|\bthen\s|\bdo\s|\belse\s)  # command position only
    \s*
    (?:agy|codex)\b                          # the vendor CLI being launched
    (?:\s+(?:exec|-p|--print|--prompt))+     # its subcommand / prompt flag
    \s+
    "?\$(?:\(|\{|[A-Za-z_])                 # an argv element expanded at runtime
    """,
    re.VERBOSE,
)

# Any CLI handed the CONTENTS of a file through an argv element. This is the
# form #1364 calls out as "a one-line change": the script already has the file,
# then `cat`s it back into an argument and defeats it. Anchored to a preceding
# flag/subcommand token so it means "passed as an argument" — a plain
# `VAR="$(cat f)"` assignment is ordinary, ubiquitous shell and not this bug.
_CAT_INTO_ARGV_PATTERN = re.compile(
    r"""(?:^|\s)(?:-\w|--[\w-]+|exec)\s+"\$\(\s*cat\b""",
    re.VERBOSE,
)

# `vendor_invoke.sh` is the primitive that REPLACES these constructs; it names
# and defends against them (its D-2 argv guard), so it may legitimately contain
# the vocabulary this scan looks for.
_VENDOR_ARGV_EXEMPTIONS = {
    "scripts/oversight/lib/vendor_invoke.sh",
}


def test_no_vendor_cli_receives_content_through_argv():
    """#1364 acceptance: every agy/codex call site passes content via stdin or a
    file path — never a single argv element."""
    hits = {}
    for path in _iter_shell_files("scripts", "bootstrap", "bin"):
        for lineno, line in _code_lines(path):
            if _VENDOR_ARGV_PATTERN.search(line):
                hits.setdefault(str(path.relative_to(ROOT)), []).append(
                    f"{lineno}: {line.strip()}"
                )
    offenders = set(hits) - _VENDOR_ARGV_EXEMPTIONS
    assert not offenders, (
        "vendor CLI invocation(s) passing content through argv (#1364 E2BIG "
        f"class): { {k: hits[k] for k in sorted(offenders)} }. Route the call "
        "through vendor_invoke() in scripts/oversight/lib/vendor_invoke.sh — "
        "content goes on stdin, never argv."
    )


def test_no_file_contents_are_cat_into_argv():
    """#1364 acceptance, the `-p \"$(cat ...)\"` form specifically: a script that
    already wrote a tmpfile must pass the PATH, not the contents."""
    hits = {}
    for path in _iter_shell_files("scripts", "bootstrap", "bin"):
        for lineno, line in _code_lines(path):
            if _CAT_INTO_ARGV_PATTERN.search(line):
                hits.setdefault(str(path.relative_to(ROOT)), []).append(
                    f"{lineno}: {line.strip()}"
                )
    assert not hits, (
        "file contents interpolated into an argv element via `\"$(cat ...)\"` "
        f"(#1364 E2BIG class): { {k: hits[k] for k in sorted(hits)} }. Pass the "
        "file PATH and let the callee read it, or feed it on stdin."
    )


def test_the_sweep_would_actually_catch_a_reintroduction(tmp_path):
    """Guard the guard: a scan that silently matches nothing is worse than no
    scan, because it reports PASS forever. Assert the patterns fire on the exact
    constructs #1364 removed."""
    reintroductions = [
        'result=$(agy -p "$PROMPT" 2>/dev/null)',
        'CODEX_OUT=$(codex exec "$CODEX_PROMPT")',
        'result=$(agy -p "$(cat "$tmpfile")" 2>/dev/null)',
        'AGY_OUT=$(agy -p "${AGY_PROMPT}")',
    ]
    for line in reintroductions:
        assert _VENDOR_ARGV_PATTERN.search(line), (
            f"the #1364 sweep pattern no longer matches {line!r} — it would let "
            "a reintroduction through while still reporting PASS."
        )

    assert _CAT_INTO_ARGV_PATTERN.search('agy -p "$(cat "$tmpfile")"')

    # And must NOT fire on the migrated form, or the sweep is unusable.
    migrated = [
        'vendor_invoke agy "$AI_REVIEW_TIMEOUT" "$prompt_file" "$stdout_file"',
        'printf \'%s\' "$prompt" | run_capped "$T" "$out" claude -p',
        'codex exec < "$tmpfile"',
    ]
    for line in migrated:
        assert not _VENDOR_ARGV_PATTERN.search(line), (
            f"the #1364 sweep pattern false-positives on the CORRECT form "
            f"{line!r} — it would block the very migration it exists to enforce."
        )
