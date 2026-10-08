# Prompt Artifact — panel_logic.py (chunk-diff) + run_panel.sh chunk wiring

| Field | Value |
|---|---|
| **Generated file** | `scripts/oversight/panel_logic.py` (`chunk-diff`), `scripts/run_panel.sh` (ADR-1340 carve-out c), `tests/oversight/test_panel_logic.py` |
| **Description** | Split oversize per-file panel chunks on hunk/line boundaries instead of silently cutting them at the 60 KB cap (#2016) |
| **Date** | 2026-10-08 |
| **Model** | claude-opus-5-5 (coder subagent and orchestrating worker session) |
| **Risk level** | HIGH (validated by risk-assessor via diff_size floor; composite MEDIUM; coder self-declared MEDIUM) |
| **Human review status** | ⬜ Pending |

---

## Prompt

Provenance: autonomous HOS worker cron cycle, 2026-10-08. Step 2 selected
issue #2016 (`priority:high`, `needs-ai`, v0.7.0) after skipping #1944
(interactive-only). The fix touches the ADR-1340 AD-1 frozen engine span, so
the worker first dispatched `architect` for a ruling; the architect appended
"AMENDED 2026-10-08 (#2016) — carve-out (c)" to
`docs/v0.7.0/ADR-1340-release-panel.md` and returned an implementation spec.

The operative prompt given to the `coder` subagent (excerpt, the bound design):

```
Bug: scripts/run_panel.sh caps each reviewer prompt's diff with
head -c "$CAP" (CAP=60000). A single file whose diff exceeds the cap is cut
silently while the run reports full coverage.

Touch ONLY: scripts/oversight/panel_logic.py, scripts/run_panel.sh,
tests/oversight/test_panel_logic.py.

1. New subcommand panel_logic.py chunk-diff --diff <path> --cap <int>
   --out-dir <dir>. Binary input, all sizes in bytes. Sections start at
   b"diff --git ". Header = lines before the first "@@". Whole input <= cap
   -> one byte-identical chunk. Otherwise a section <= cap is one chunk; a
   larger section is filled greedily into header+whole-hunk parts <= cap; a
   hunk too big for header+hunk falls back to header+lines parts;
   header+one line > cap (or header alone) -> exit 3. Exit 2 on
   usage/IO. Nothing written on non-zero exit. Atomic chunk-manifest.json
   (schema panel-chunk-manifest/1: cap, input_bytes, input_sha256, chunks[],
   files[] with whole flag, all_whole). Exact UNSPLITTABLE stderr texts.
   Pure function chunk_diff(data, cap); stdlib only.
2. run_panel.sh (carve-out c only): replace the awk chunker with chunk-diff
   (die on non-zero, capturing the exit code), build CHUNKS from the
   manifest, copy the manifest into RUN_DIR, warn per split file; a
   top-level pre-flight loop dies if any chunk exceeds CAP; build_review_prompt
   uses $(cat "$2") instead of head -c. Leave the triage head -c alone.
   Update carve-out comment counts to "of 3".
3. Tests T1-T9: 100 KB single-file acceptance with byte-exact coverage
   reconstruction, single-hunk line split, unsplittable exit 3 with nothing
   written, fast path, small/large/small ordering, UTF-8 bytes-vs-chars,
   header-only + preamble, CLI exit 2, run_panel.sh source pins.
```

## Refinement iterations

1. Coder replaced `mapfile -t` with a `while read` loop because the
   `bash_check` gate rejects Bash-4-only builtins. Black reformatted the
   pre-existing code in both Python files, and three pre-existing mypy errors
   were fixed, so the touched files pass the gates.
2. code-review round 1 (APPROVED, one SHOULD_FIX): a `jq` failure inside the
   process substitution could leave `CHUNKS` empty and the fan-out would
   review nothing. Added `(( ${#CHUNKS[@]} > 0 )) || die "...refusing to
   review nothing (#2016)"`. The T9 pins were also tightened so the pre-flight
   must sit before `build_review_prompt() {`.
3. code-review round 2 and security-reviewer: APPROVED (two NITs: the split
   warn loop's jq failure is silent; there is no ceiling on chunk count).
4. Second review (full range): codex raised a medium CWE-400 finding (no
   bound on header-repetition amplification) and agy a low one (`_file_name`
   records git's quoted-path form verbatim). The architect added carve-out
   (c5). Follow-up prompt to the coder:

   ```
   Implement ADR-1340 (c5) in panel_logic.py: _split_section raises
   UnsplittableError when a file it must split has a header > cap // 2;
   chunk_diff fails closed when total chunk bytes exceed 4*len(data)+cap
   (backstop only, never fires on admissible input). No chunk-count limit.
   _file_name strips git's quoted-path form (names only; grouping and
   splitting must not depend on it). Hermetic tests for each.
   ```
5. The first c5 version used `2*len(data)+cap`, and the coder measured 2.16×
   on an ordinary 20-line-hunk layout with the header at `cap // 2`. The
   architect revised the backstop to `4*len(data)+cap`. code-review round 3
   and security-reviewer round 2: APPROVED.
6. Prompt-fidelity measured 3.71×, and the architect then reproduced 4.87× at
   cap 60000: the splitter flushed before and after each line-split hunk, so
   the backstop rejected admissible input. (c5) revised again: packing must
   be strictly greedy (line-split a too-large hunk starting in the current
   part, and keep the tail part open). Follow-up prompt to the coder: make
   `_split_section` strictly greedy; add regression tests for the
   architect's pattern at cap 60000 and 1000, the 3.71× alternating case,
   and a seeded fuzz (lossless, each chunk <= cap, ratio <= 3).
