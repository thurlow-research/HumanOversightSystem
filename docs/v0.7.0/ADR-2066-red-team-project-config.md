# ADR-2066: Each project configures its own checkpoint red-team. Milestones go in a strict JSON file that is parsed by a stdlib Python module and never sourced. Repo files are read through one validated bash helper in `scripts/oversight/lib/repo_context.sh`, which `run_second_review.sh` also uses with byte-identical results. Only tracked files can be selected, and a denylist that no config can relax filters them

**Status:** APPROVED WITH AMENDMENTS. AD-1 to AD-9 bind `technical-design`. AR-1 to AR-9 (§5) amend `REQUIREMENTS-2066-red-team-project-config.md`. They are recorded here and **not** applied in place: this cycle's task limits the architect to writing this one file. TD must treat each AR as overriding the requirement it names. One decision is **PROVISIONAL**: AD-5's selection universe and extended denylist depend on ARCH-ESC-1, which is a data-egress question for the human.

No ESC answer and no agent-side waiver can relax these parts:
- AD-2: the milestone file is data and is never `source`d or `eval`ed;
- AD-3: second-review prompt bytes stay identical, proven by a golden fixture committed **before** the extraction;
- AD-5: the denylist has no project override, and symlinks are always excluded;
- AD-6: the #911 and #1000 fail-closed guards stay in place unchanged.

**Date:** 2026-10-18
**Author:** architect (autonomous worker cycle). No human was present, so open decisions appear as ESC or ARCH-ESC items, each with a recommended default.
**Issue:** #2066 (follow-up to #1853 and #2057) · **Milestone:** v0.7.0
**Risk tier:**
- Build overall: **HIGH**.
- S1a (shared loader extraction): **MEDIUM**. `security-reviewer` is mandatory.
- S1b (red-team rework): **HIGH**. `security-reviewer` and `privacy-reviewer` are mandatory, and second review runs at HIGH+. This slice decides which source content leaves the machine, and it parses project-controlled input in a shipped script.
- S2 (protected docs and comments): **LOW** computed, but **HUMAN_REQUIRED** because it touches protected surfaces.

**Inputs:** `docs/v0.7.0/REQUIREMENTS-2066-red-team-project-config.md` (VF-1 to VF-10, REQ-1 to REQ-9, NFR-1 to NFR-4, ESC-1, ESC-2), read in full. Files read for this ADR at `a7894ba0f`:
- `scripts/run_red_team.sh` (whole);
- `scripts/run_second_review.sh:1-67,360-430,835-870` (plus a grep of every `THREAT_MODEL`, `SPEC_CONTEXT`, `PROJECT_*` site);
- `scripts/framework/config.sh` (whole);
- `scripts/framework/protected_surfaces.txt` (whole);
- `scripts/oversight/lib/` (listing), and `vendor_invoke.sh:86-216` (temp-dir and trap contract);
- `scripts/oversight/validation_logic.py:113-124` (`loads_strict`);
- `tests/oversight/test_red_team_fail_closed.py` (whole);
- `tests/oversight/test_second_review_codex_prompt.py` (whole);
- `tests/oversight/test_second_review_envelope_gate.py:35-123` (`_REQUIRED_BINS`, `_minimal_stub_path`);
- `bootstrap/hos_install.sh:1858-1895,2296-2300,2596-2602`;
- `bootstrap/hos_bootstrap.sh:151-177,349-352` (Python floor);
- `docs/OVERSIGHT-RUNBOOK.md:745-770`;
- `contract/OVERSIGHT-CONTRACT.md:119-120,411`;
- `SCRIPTS-INDEX.md:181-190`;
- the `scripts/oversight/.venv` site-packages listing.

**Consumers:** `technical-design`, then `coder`, then the review chain.

**Explicitly does NOT re-litigate:**
- ADR-1683, including D-2 (every agy/codex call goes through `vendor_invoke`) and its ceilings (NFR-2);
- the #911 and #1000 fail-closed semantics;
- the #1853/#2057 threat-model validation rules: their reason strings, the 16384 B cap, and the warn-and-fallback behaviour;
- ADR-1935 N3, which says the checkpoint's exit code is read by a human and consumed by nothing.

---

## 0. Verification findings (tree at `a7894ba0f`)

### 0.1 Confirming pm-agent

I re-read every pm-agent claim at the cited lines.

- **VF-1, VF-2, VF-3, VF-5 and VF-10 are CONFIRMED** as written:
  - `run_red_team.sh:62`, `:71-100`, `:76/82/88/94`, `:298-301`, `:9-12/25-26`, `:140-141`;
  - unknown flags are dropped at `:57`;
  - the milestone name is interpolated into `OUTFILE` at `:68` and into the issue title at `:172`.
- **VF-4 is CONFIRMED** (`:117`). `run_second_review.sh:381-387` reads `SPEC_FILE`, but it uses plain `cat` with **no** path validation. See AF-4.
- **VF-6 is CONFIRMED.** The loader is at `run_second_review.sh:388-430` and the default text at `:847-852`. `tests/oversight/test_second_review_codex_prompt.py` is the only test that touches it. A grep of `tests/` and `scripts/` for `THREAT_MODEL`, `_tm_reason` and `realpath not available` finds only that test, the script and `config.sh`.
- **VF-7 is CONFIRMED.**
  - The explicit copy loop is at `hos_install.sh:1858`.
  - `scripts/oversight/` is rsynced wholesale at `:1866-1895`, so a new file under `scripts/oversight/` or `scripts/oversight/lib/` ships with no installer change.
  - The hint is at `:2602`.
  - The runbook lists the CPS milestones at `:750-762`.
  - A repo-wide grep finds no **live operator doc** other than the runbook, the installer hint and the script header that tells anyone to run a CPS milestone name. The only other hits are historical design records.
- **VF-8 and VF-9 are CONFIRMED.** `test_both_reviewers_absent_fails_closed` (`:238-255`) never creates a target, so it exits through the `:135-143` guard.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): the requirements' "same text" demand cannot be met by a naive extraction.**
- `run_codex_review` does `threat_model="$THREAT_MODEL_CONTEXT"`, which keeps the configured file's trailing newlines byte for byte.
- If the shared helper returns the text on stdout and the caller captures it with `threat_model=$(hos_…)`, bash strips every trailing newline. The second-review codex prompt then changes for any threat-model file that ends in `\n`, which is nearly all of them.
- `test_second_review_codex_prompt.py` would **not** catch this, because it asserts substrings only.
- AD-3 therefore bans command-substitution capture of the text and adds a byte-exact golden test.

**AF-2 (HIGH): today's target sample is malformed on every run, not only on non-CPS layouts.**
- `CODEBASE_SAMPLE+="=== $f ===\n$(cat "$f")\n\n"` (`:122`) puts a literal backslash-n into the string, because bash double quotes do not interpret `\n`. `printf '%s'` then writes those two characters into the prompt unchanged.
- `for f in $CODEX_FILES` (`:121`) word-splits, so a path containing a space becomes two non-files, which are silently dropped.
- AD-5 moves sample rendering into Python, with real newlines and a NUL-safe path list.

**AF-3 (HIGH): a filesystem `find` or `glob.glob` selection reaches untracked and gitignored content and follows symlinks.**
- A project-written glob such as `src/**` would sweep in untracked local files: gitignored `secrets.yaml`, `*.local.json`, scratch dumps. Those are exactly what a project chose never to commit, and the red-team would send them to two vendors.
- `glob.glob` also follows symlinked directories.
- REQ-6's denylist names six directories and two file classes. It is a floor, not a model of "what must not leave the machine".
- AD-5 selects from the git index only. Product consequence: ARCH-ESC-1.

**AF-4 (MEDIUM): `SPEC_FILE` is read without validation, so REQ-3's "same read" would copy a defect.**
- `run_second_review.sh:385-386` runs `cat "$SPEC_FILE"`. It does not check whether the path is a symlink, outside the repo root, or a dot-path, and it has no size cap. A `SPEC_FILE` symlinked to `~/.ssh/config` is sent to agy.
- For the red-team I rule that the spec goes through the same validated read as everything else (AR-1).
- I do **not** fix the second-review read here. That would move second-review behaviour, which REQ-2 AC(a) forbids. It is follow-up FU-1.

**AF-5 (MEDIUM): `vendor_invoke.sh` owns the process's EXIT/INT/TERM trap.**
- See `:141-210`. Its handler chains onto any existing trap, but a `trap … EXIT` installed **after** it replaces it and leaks the vendor temp dir.
- The red-team's new scratch outputs must therefore use `vendor_invoke_tmpfile` and must not add a trap (AD-4).

**AF-6 (MEDIUM): the format choice is constrained by which interpreter runs, not by the venv.**
- `scripts/oversight/.venv` has PyYAML, ruamel.yaml and tomli. However, `run_red_team.sh` and `run_second_review.sh` call bare `python3`, which is the system interpreter (the floor is 3.10, `hos_bootstrap.sh:151-177`). The venv is not on that path.
- `tomllib` arrived in 3.11 and YAML is not in the stdlib. JSON is the only data format that is both stdlib on 3.10 and already the repo's machine-readable lingua franca. Strict parsing with duplicate-key rejection has a precedent in `validation_logic.loads_strict` (`:113-124`).

**AF-7 (LOW): issue creation bypasses `bootstrap/create_issue.sh`.**
- `create_redteam_issues` calls `gh issue create` directly (`:189`), against CLAUDE.md item 5.
- This is out of scope for #2066 and is untouched here. It is follow-up FU-2.

**AF-8 (LOW, startup gap): #685 removed CPS text from `run_second_review.sh` but never audited its sibling.** See §6.

**Reuse search (CLAUDE.md item 1).** I searched `scripts/` (recursively), `scripts/oversight/lib/`, `scripts/automation/lib/`, `bootstrap/` and `bin/` for five things:
- **A validated repo-file reader.** None exists as a reusable unit. The only implementation is inline at `run_second_review.sh:395-430`, and AD-1 extracts it.
- **A glob-to-path matcher with `**` semantics.** None exists. `fnmatch`'s `*` crosses `/`, and `glob.glob` touches the filesystem (AF-3). AD-5 specifies a small segment-wise matcher.
- **A strict JSON loader.** `validation_logic.loads_strict` exists. It is not imported, because that module is the second-review validation core and importing it would couple the two. Instead, its 4-line `object_pairs_hook` idiom is reused verbatim in the new module.
- **A tracked-file lister.** Nothing exists in Python. `git ls-files -z` is called directly.
- **A temp-file primitive.** `vendor_invoke_tmpfile` exists and is reused (AF-5).

---

## 1. Organizing principle

**Configuration is data, selection is closed by default, and the shared gate does not move.**
- A project describes what to attack in a file that HOS **parses** and never **executes**.
- What leaves the machine is the intersection of three sets: what the project asked for, what git tracks, and what passes a denylist that the project cannot shorten.
- The one piece of code shared with the mandatory pre-PR gate is extracted so that the gate's prompt bytes are provably unchanged.

---

## 2. Decisions

### AD-1: One shared bash library, `scripts/oversight/lib/repo_context.sh`, owns validated repo-file reads, the threat-model load and the default threat-model text. (BINDING. REQ-2, AF-1, AF-4.)

- **Why bash, not Python.** The existing loader's behaviour is defined in bash terms: `realpath`, the `pwd -P` root, `head -c` with the `printf x` sentinel, and `LC_ALL=C` byte length. Its six reason strings are asserted verbatim. A Python port would bring its own failure modes, such as a missing `realpath` versus `os.path.realpath`, and a different empty-versus-unreadable split. Proving equivalence would then take a new test matrix instead of a move. The extraction must be a **move**, not a rewrite.
- **Interface.** The file is sourced, defines functions and one constant, and has no side effects at source time: no `set` changes, no traps, no I/O.
  - `THREAT_MODEL_MAX_BYTES=16384`.
  - `hos_read_repo_file <path> <max_bytes>`
    - Returns 0 on acceptance and sets `HOS_REPO_FILE_CONTENT`, a byte-exact copy including trailing newlines.
    - Returns 1 on rejection and sets `HOS_REPO_FILE_REASON` to **exactly** one of today's strings: `realpath not available`, `not a regular file`, `resolves outside the repo root`, `resolves into a dot-path (hidden file or directory)`, `empty or unreadable`, `larger than <N> bytes`.
    - The root is `pwd -P` at call time. It prints nothing.
    - Callers must invoke it as `if hos_read_repo_file …; then`, because a bare call aborts under `set -e` on rejection.
  - `hos_load_threat_model`
    - Reads `${THREAT_MODEL_FILE:-}` and sets `THREAT_MODEL_CONTEXT` (empty when unset or rejected).
    - On rejection it prints today's `WARNING: THREAT_MODEL_FILE '<value>' ignored (<reason>); using the generic default threat model.` line to stderr, verbatim.
    - It also sets `THREAT_MODEL_SOURCE`, which is `<value>` on acceptance and `generic default` otherwise. This is new and is used only by the red-team (REQ-7).
  - `hos_threat_model_text`
    - Sets `HOS_THREAT_MODEL_TEXT` to `THREAT_MODEL_CONTEXT` when that is non-empty. Otherwise it sets it to today's 4-line default (`:850-852`), byte for byte, with the `PROJECT_NAME` / `PROJECT_STACK` expansions done at call time.
    - **It writes nothing to stdout** (AF-1). Callers read the variable. Capturing the text with `$(…)` is forbidden. The TD must name this rule in the function's header comment.
- **Name.** The library holds more than the threat model, so it is not called `threat_model.sh`. It is the place for any future "project file that goes into a vendor prompt".
- **Rejected alternatives:**
  - *A Python module with a bash shim.* It changes failure semantics, as described above.
  - *Copying the block into `run_red_team.sh`.* REQ-2 forbids two copies.
  - *Sourcing the helper from `config.sh`.* `config.sh` is consumer-owned in installed projects, and HOS logic must not depend on a consumer file to load.

### AD-2: The milestone file is strict JSON (`hos-red-team-milestones/1`), parsed by `scripts/oversight/red_team_logic.py` using the stdlib only. The file is never `source`d or `eval`ed. (BINDING, not waivable on the never-executed point. REQ-4, AF-6.)

- **Location and read.**
  - The `config.sh` key `RED_TEAM_MILESTONES_FILE` holds a repo-relative path.
  - Bash reads it with `hos_read_repo_file "$RED_TEAM_MILESTONES_FILE" 65536`.
  - **Rejection is an error, not a fallback.** The script prints `run_red_team: CONFIG-ERROR — RED_TEAM_MILESTONES_FILE '<value>' rejected (<reason>)` and exits 2 before any vendor call.
  - The file is validated whenever the key is set, including in `--paths`-only runs. A broken checkpoint config is never tolerated silently.
  - The accepted content goes to Python on **stdin**. Python never re-opens the path, which removes the race between validating the file and reading it.
- **Schema** (every key is checked; an unknown key is an error, which catches typos such as `"path"`):

  ```json
  {
    "schema": "hos-red-team-milestones/1",
    "milestones": {
      "<name>": {
        "scope": "required, 1..4096 chars after strip",
        "paths": ["required, 1..64 globs, each 1..256 chars (AD-5 grammar)"],
        "attack_focus": "optional, 1..4096 chars",
        "spec_focus": "optional, 1..4096 chars",
        "max_files": 30
      }
    }
  }
  ```

  - `schema` must equal the literal shown.
  - `milestones` must be a non-empty object with at most 32 entries.
  - Each `<name>` must match `^[a-z0-9][a-z0-9_-]{0,31}$`. The name `custom` is **reserved** (AD-6) and is an error if defined.
  - `max_files` is optional. If present, it must be an integer from 1 to 100 inclusive, and a JSON boolean is rejected.
  - The parse uses `json.loads` with a duplicate-key-rejecting `object_pairs_hook`, applied at every nesting level.
  - Every error message names the file and the JSON path of the problem, for example `milestones.auth.paths[2]: '..' segment not allowed`.
- **Module interface** (stdlib only, Python 3.10 compatible, no third-party imports; a unit test pins the import set):
  - `parse_milestones(text: str, label: str) -> dict`. It raises `ConfigError`.
  - `compile_glob(pattern: str) -> re.Pattern`. It raises `ConfigError` (AD-5).
  - `select_files(root: Path, globs: list[str], cap: int) -> Selection`, holding `included`, `matched`, `excluded_unsafe`, `skipped_binary` and `empty_globs`.
  - `render_sample(root: Path, files: list[str]) -> str`.
  - `main()`, which provides a `plan` subcommand. It takes `--root`, an optional `--milestone`, an optional `--scope`, repeatable `--path`, `--milestones-label <value-or-empty>`, and one `--out-<field> <file>` per output. Milestone content arrives on stdin, and is empty when the key is unset.
  - Exit codes: 0 on success (including an empty selection; the #1000 guard stays in bash, AD-6); 2 on a config or usage error, with one stderr line; anything else is an internal error, and bash treats it as a config error.
- **Rejected alternatives:**
  - *A bash-sourced `.sh` table.* Executing project files is ruled out by the task constraint and by NG-style trust.
  - *TOML.* `tomllib` needs 3.11 (AF-6).
  - *YAML.* It is not in the stdlib, and the venv is not the interpreter (AF-6).
  - *An INI file via `configparser`.* It has no native lists, has implicit interpolation, and its keys are case-folded.
  - *Fields in `config.sh` itself.* That would mean sourcing more project shell and editing a protected HOS file in this repo.

### AD-3: `run_second_review.sh` changes in exactly two hunks, and a golden fixture captured before the change proves byte identity. (BINDING, not waivable. REQ-2 AC(a), AF-1.)

- **The two hunks.**
  - **Hunk 1.** The inline loader (`:388-430`) becomes `hos_load_threat_model`. It is called at the same point, after `config.sh` is sourced, so the WARNING keeps its stderr position.
  - **Hunk 2.** The `if/else` at `:847-852` becomes `hos_threat_model_text; threat_model="$HOS_THREAT_MODEL_TEXT"`.
  - The `source` line for the library goes next to the existing `vendor_invoke.sh` source (`:67`).
  - **Nothing else in the file changes.** The `SPEC_FILE` read and `PROJECT_*` init stay as they are (AF-4, FU-1).
- **Golden proof** (AR-4). S1a's **first** commit adds `tests/oversight/test_threat_model_shared_loader.py` together with a fixture, `tests/oversight/fixtures/second_review_codex_prompt_golden.json`. The fixture holds the codex prompt bytes captured from the **unmodified** script. It covers three cases:
  - (a) default threat model;
  - (b) a configured threat-model file that **ends in a newline** (the AF-1 case);
  - (c) a rejected file.

  Its capture uses the stdin-recording stub from `test_second_review_codex_prompt.py`.
  - The extraction lands in a **later** commit, and that commit must not modify the fixture. The reviewer checks this with `git diff <c1> <c2> -- tests/oversight/fixtures/`, which must be empty, and records the check in the sign-off.
  - If the prompt contains anything that varies between runs (a timestamp, a temp path, a SHA), the TD names it and the test normalises **only** that token. Normalising anything near the threat model is forbidden.
- `test_second_review_codex_prompt.py` passes **unmodified** (REQ-2 AC(a)).
- **Single-implementation test** (REQ-2 AC(c), AR-5). Each of the six reason strings must appear in exactly one file under `scripts/` (`repo_context.sh`). In addition, neither `run_second_review.sh` nor `run_red_team.sh` may contain `realpath` or `head -c`.
- **Merge-conflict note.** #2017 S2 (the receipt nonce) and #2014 S2 both edit `run_codex_review`. S1a's hunk 2 is three lines. Whichever lands second rebases, and S1a's golden is re-captured **only** if the other change altered the prompt. In that case the re-capture happens in its own commit, cites that change, and is reviewed as such.

### AD-4: `run_red_team.sh` control flow: strict arguments, config sourced as in second review, the plan built in Python, no new trap. (BINDING. REQ-5, REQ-6, REQ-8, AF-5.)

- **Arguments.**
  - `--milestone <name>`, `--scope <text>` (at most 4096 bytes), `--paths <glob>` (repeatable, at most 64), `--dry-run`, and `--help`, which prints usage and exits 0.
  - A missing option value, an unknown flag, or neither `--milestone` nor `--paths` → usage on stderr, exit 2.
  - `--milestone` is matched against AD-2's name regex **before** any other use.
- **Root.** The script requires that `git rev-parse --show-toplevel` equals `pwd -P`. Otherwise it prints `CONFIG-ERROR — run from the repository root` and exits 2. The selection universe is the git index (AD-5), and the loader's root is `pwd -P`, so the two must agree.
- **Config.** It initialises `PROJECT_NAME PROJECT_STACK SPEC_FILE THREAT_MODEL_FILE RED_TEAM_MILESTONES_FILE` to empty, then runs `[[ -f scripts/framework/config.sh ]] && source scripts/framework/config.sh`, using the same idiom and trust as `run_second_review.sh:381-382`. `config.sh` is the project's executable config by contract. The **milestone file** is the thing that is never executed (AD-2).
- **Plan.**
  - Output files are allocated with `vendor_invoke_tmpfile` only. Calling `mktemp` directly, writing under `.claudetmp/`, or adding a `trap` is forbidden (AF-5).
  - `red_team_logic.py plan` fills them.
  - Bash reads each file into a variable. No output of the plan step is ever `source`d or `eval`ed.
- **Exit codes** (AR-6):
  - 0 → the checkpoint is complete;
  - 1 → **FAIL-CLOSED**: the #911 or #1000 guards fired. This is unchanged;
  - 2 → a usage or config error, raised before any vendor call.

  ADR-1935 N3 says nothing consumes this exit code, so splitting 1 and 2 has no downstream effect. It does let a human, and the tests, tell a broken config from a failed checkpoint.
- **Unchanged** (NFR-2, REQ-8):
  - `vendor_invoke` calls, stdin delivery and `RED_TEAM_VENDOR_TIMEOUT`;
  - `salvage_review_json`, `redteam_invoke_failure_json` and `reviewer_state`;
  - both fail-closed blocks;
  - the dry-run exemptions;
  - the issue severity filter;
  - the token-tracker block, with `--step` now given the label.

### AD-5: Target selection: the git index, an anchored segment-wise glob grammar, a denylist the project cannot override, symlinks and binaries excluded, and a deterministic cap with visible truncation. (BINDING on the grammar, determinism, the non-overridable denylist and the symlink exclusion. PROVISIONAL on tracked-only and the extended denylist, pending ARCH-ESC-1. REQ-6, AF-2, AF-3.)

- **Universe.** The candidates are exactly the paths from `git ls-files -z` run at the root. Any path containing a control character (`\x00-\x1f`, `\x7f`) is excluded and counted. A path is then kept only if:
  - it is **not** a symlink (`os.lstat`; tracked symlinks with mode 120000 are excluded and counted);
  - it is a regular file (gitlinks and submodules, plus tracked-but-deleted files, drop out here);
  - `os.path.realpath` of it is inside the root (defence in depth).
- **Glob grammar.** It is implemented by `compile_glob`. `fnmatch` and `glob` are not used.
  - Patterns are repo-relative and anchored at the root. A single leading `./` is stripped. A trailing `/` means `/**`.
  - Each pattern is split on `/`. A segment of exactly `**` matches zero or more whole segments. `*` matches any run of characters except `/`, and `?` matches one character except `/`. Matching is case-sensitive.
  - **Dot rule:** `*`, `?` and `**` never match a segment that begins with `.` unless that pattern segment itself begins with `.`. So `src/**` does not reach `src/.cache/x`, but `.github/workflows/*.yml` works when the project asks for it explicitly.
  - These are **config errors**:
    - a leading `/`;
    - an empty segment (`//`);
    - a `.` or `..` segment;
    - a backslash;
    - any of `[ ] { }`;
    - `**` combined with other characters in one segment;
    - an empty pattern or one over 256 chars.
- **Denylist** (checked against every path segment and the basename; no config key, flag or milestone field can relax it):
  - REQ-6 floor:
    - any segment in {`.git`, `.claudetmp`, `.ai-local`, `.venv`, `node_modules`, `__pycache__`};
    - a basename of `.env` or `.env.*`;
    - a basename matching `*.salt`.
  - Extended (ARCH-ESC-1 (a)):
    - any segment `.tmp`;
    - basenames `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`, `.netrc`, `.npmrc`, `.pypirc`, `.hos-*token*`.
  - Excluded paths are counted, and each excluded path is printed once to stderr as `excluded (safety filter): <path>`. They are never written into a prompt.
- **Content filter.** A file is skipped and counted (`skipped_binary`) if:
  - its first 8192 bytes contain a NUL, or
  - it does not decode as strict UTF-8.

  This filter runs **before** the cap, so the cap counts only usable files.
- **Order and cap.**
  - Results go in glob order. Within one glob they are sorted by byte order of the path. Duplicates are removed, and a file keeps the position of its first glob.
  - The cap comes from the milestone's `max_files` if set, and is 30 otherwise. CLI `--paths` mode always uses 30, and there is no CLI cap flag.
  - When more files match than the cap allows, one stderr line is printed: `run_red_team: NOTICE — <matched> files matched, <included> included (cap <cap>); <excluded> excluded by safety filter, <skipped> skipped as binary/non-UTF-8.` The same line also goes into the report. A glob that matches nothing prints its own `NOTICE — glob '<g>' matched no tracked files` line, which helps catch typos.
- **Sample rendering** (AF-2). For each file, the sample contains `=== <path> ===\n<content>\n\n`, with real newlines and the path as git reports it (no `./` prefix).
- **Byte budget.** No new per-file or total byte cap is added. `vendor_invoke`'s ceilings stay the size control, and refusing an oversize prompt is already loud and fail-closed (NFR-2; chunking is #2014).

### AD-6: Milestone, label and generic mode resolution. (BINDING. REQ-4, REQ-5, ESC-1.)

| Invocation | Label | Fields | Globs | Milestone provenance |
|---|---|---|---|---|
| `--milestone m` (defined in the file) | `m` | the file's `scope`; `attack_focus`/`spec_focus`, or the generic defaults | the file's `paths` | `RED_TEAM_MILESTONES_FILE (<value>)` |
| `--milestone m --scope/--paths` | `m` | the CLI `--scope` replaces `scope`; the focus fields come from the file | CLI `--paths` **replace** the file's globs | `RED_TEAM_MILESTONES_FILE (<value>) + CLI override (scope, paths)` (whichever was overridden) |
| `--paths` only | `custom` | the CLI `--scope`, or the neutral default; focus fields use the generic defaults | CLI | `CLI (--paths)` |
| `--milestone m`, not defined, or key unset | — | exit 2: `milestone '<m>' is not defined in <file>; defined: a, b, c`, or `RED_TEAM_MILESTONES_FILE is not set`, plus a pointer to `--paths` | — | — |

- **Generic defaults** live in `red_team_logic.py` as module constants. A test pins them as free of the REQ-1 terms.
  - Scope: `the code under the selected paths`.
  - Attack focus: REQ-5's list.
  - Spec focus: `Requirements or invariants stated in the spec that the selected code fails to enforce.`
- **The #1000 guard stays in bash, in the same position.** Its message becomes project-neutral: `no target files matched for '<label>'`, which keeps the substring the existing test asserts, followed by a pointer to `RED_TEAM_MILESTONES_FILE` / `--paths`.
- **The #911 guard is unchanged**, both its text and its logic.

### AD-7: The red-team reads the spec through `hos_read_repo_file` with a 131072 B cap. A missing or rejected spec gives a warning plus an explicit statement in the prompt. agy still runs. (BINDING. REQ-3 as amended by AR-1, ESC-2.)

- When `SPEC_FILE` is unset: stderr gets `WARNING: SPEC_FILE not set; the spec lens runs without a spec.`
- When it is rejected: stderr gets `WARNING: SPEC_FILE '<v>' ignored (<reason>); the spec lens runs without a spec.`
- In both cases the `<spec>` block contains exactly `No project spec is configured for this run. Review the implementation against invariants evident from the code itself and state that no spec was available.` The provenance is then `none (unset)` or `none (<reason>)`.
- The 131072 B cap leaves room under agy's 180,000 B ceiling for a modest sample. A spec larger than that is rejected loudly, never truncated silently.

### AD-8: The report header records provenance. The report path is unchanged. (BINDING. REQ-7.)

- The header lines below go directly under today's `Timestamp:` and `Scope:` lines, in this order, as `Key: value` lines:
  - `Milestone source:`
  - `Threat model:` (the path, or `generic default`)
  - `Spec:` (the path, or `none (…)`)
  - `Selection:` (AD-5's counts line)
  - `Files:` followed by one `- <path>` line per included file
- The report path stays `.claudetmp/red-team/checkpoint-{label}-{ts}.md`, matching `contract/OVERSIGHT-CONTRACT.md:120`, where `{milestone}` now means the label.
- Dry-run writes the same header, so tests can check provenance without vendors.

### AD-9: Docs, hints and audit. (BINDING. REQ-9.)

- **S1b** (unprotected) covers:
  - the script header, rewritten for both modes and both keys;
  - `docs/OVERSIGHT-RUNBOOK.md` §Checkpoint Red-Teams, which drops the CPS list and its CPS step numbers, then documents the file schema, the glob grammar, the denylist and the exit codes;
  - `docs/examples/red-team-milestones.json`, a generic example with no REQ-1 terms. A test parses it with `parse_milestones`, so the example can never drift from the schema.
- **S2** (protected) covers:
  - the `scripts/framework/config.sh` comment block, which names both readers of `THREAT_MODEL_FILE` and adds a commented-out `RED_TEAM_MILESTONES_FILE` with the suggested value `docs/red-team-milestones.json`;
  - the `bootstrap/hos_install.sh:2602` hint, which becomes `bash scripts/run_red_team.sh --paths 'src/**'` (see RED_TEAM_MILESTONES_FILE).
- **Release note.** `docs/releases/**` is protected and human-authored. The migration line for CPS-shaped consumers (ESC-1) is given in §7 so the human can paste it.
- **No new audit event.** The report is the record, as it is today.

---

## 3. Threat model and failure modes

**Trust boundaries.**
- These are untrusted: vendor output; the milestone file's content (it is project-controlled but parsed as data); CLI text.
- `config.sh` is trusted executable config, the same as for the second review.
- Everything that goes into a prompt leaves the machine.

| Threat or failure | Control | Status |
|---|---|---|
| The milestone file executes code | JSON parse only; never `source`d or `eval`ed (AD-2) | Closed |
| A hostile milestone name such as `../x` reaches a path or issue title | Regex checked before use; `custom` reserved (AD-2, AD-4) | Closed |
| A glob such as `../**` or `/etc/*` escapes the root | Grammar rejects it; the universe is the index; realpath check (AD-5) | Closed |
| A tracked symlink points at `~/.ssh` | Symlinks excluded (AD-5) | Closed |
| Gitignored local secrets are swept up by `src/**` | Universe is tracked-only (AD-5) | Closed if ARCH-ESC-1 = (a) |
| A tracked `.env` or key file is committed by mistake | Non-overridable denylist (AD-5) | Closed for listed patterns. Secrets in ordinary source files are **not** detected (R-1) |
| Truncation hides coverage gaps | NOTICE line plus a `Selection:` header line (AD-5, AD-8) | Closed |
| A config typo, such as `--path` or `"path"`, silently reduces coverage | Unknown flags and keys are errors; per-glob zero-match notice | Closed |
| An empty target gives a false pass | #1000 guard, unchanged (AD-6) | Closed |
| A spec symlinked outside the repo is sent to agy | Validated read (AD-7) | Closed for the red-team; **open for the second review** (FU-1) |
| Second-review prompt drift from the extraction | Golden captured before the change (AD-3) | Closed |
| The milestone file is changed between validation and parse | Content passed on stdin; never re-opened (AD-2) | Closed |
| An oversize sample | `vendor_invoke` refuses → `error` → #911 fail-closed | Loud |

**Residuals.**
- **R-1.** Secrets inside ordinary tracked source files still leave the machine, as they do today for the second review's diffs. A secret scan of the sample is out of scope; a follow-up could reuse `secret_scan_logic.py`.
- **R-2.** FU-1 (the second review's unvalidated `SPEC_FILE` read).
- **R-3.** The extended denylist is a fixed list. It reduces the risk but does not cover every secret file name.

---

## 4. Slices (each ≤ 15 files including tests, ≤ 10 commits, independently mergeable)

| # | Slice | Files | Tier | Protected? | Depends on | Merge waits on |
|---|---|---|---|---|---|---|
| **S1a** | Extract the shared loader; second review swaps to it (AD-1, AD-3) | `scripts/oversight/lib/repo_context.sh` (new); `scripts/run_second_review.sh` (2 hunks plus the source line); `tests/oversight/test_threat_model_shared_loader.py` (new: golden, single implementation, `hos_read_repo_file` unit cases including trailing-newline preservation); `tests/oversight/fixtures/second_review_codex_prompt_golden.json` (new); `SCRIPTS-INDEX.md` (regenerated); `DECISIONS.md`; prompt artifact: **7** | **MEDIUM**. `security-reviewer` mandatory | **No** | — | Nothing (behaviour-preserving) |
| **S1b** | Red-team rework (REQ-1 to REQ-8; AD-2, AD-4 to AD-8) | `scripts/run_red_team.sh`; `scripts/oversight/red_team_logic.py` (new); `tests/oversight/test_red_team_logic.py` (new: schema, every error path, grammar including the dot rule, denylist, symlink, binary, order and cap, stdlib-only imports, example file parses); `tests/oversight/test_red_team_project_config.py` (new: REQ-1 term scan of the script, logic module and lib, plus rendered prompts through stdin-capture stubs; REQ-2 cases through the red-team; REQ-3; REQ-5 arguments and exit codes; REQ-6 ACs; REQ-7 header fields); `tests/oversight/test_red_team_fail_closed.py` (ported: `git init` plus `git add` target, run with `--paths`; VF-9 fix asserting `no reviewer produced a real review`); `docs/OVERSIGHT-RUNBOOK.md`; `docs/examples/red-team-milestones.json` (new); `SCRIPTS-INDEX.md`; `DECISIONS.md`; prompt artifact: **10** | **HIGH**. `security-reviewer` and `privacy-reviewer` mandatory; second review HIGH+ | **No** | S1a | **ESC-1**, ARCH-ESC-1 (ESC-2 can be accepted with it) |
| **S2** | Protected config comment and installer hint (REQ-9 rest; AD-9) | `scripts/framework/config.sh` (comments only), `bootstrap/hos_install.sh` (1 line), `DECISIONS.md`: **3** | LOW computed → **HUMAN_REQUIRED** | **Yes**: `scripts/framework/**`, `bootstrap/**` | S1b (the hint must describe a shipped interface) | Human CODEOWNER approval |

**Order.** S1a can be coded now. S1b can be designed and coded after S1a merges, but must not merge before ESC-1 is ruled. S2 follows S1b.

**Not touched by any slice:**
- `scripts/oversight/lib/vendor_invoke.sh`;
- `run_second_review.sh` beyond AD-3's hunks, including its `SPEC_FILE` read;
- `scripts/run_redteam_sample.sh`;
- `contract/**`, `CLAUDE.md` and `METHODOLOGY.md` (the step-number text is FU-3);
- `scripts/framework/install.sh`;
- `.claude/**` and `.github/**`.

### Test obligations (all hermetic: stub `codex`/`agy`/`gh` on a minimal PATH; tmp git repos; within the conftest temp budget)

- **S1a:**
  - The golden matches for all three cases. The fixture is untouched by the extraction commit.
  - `test_second_review_codex_prompt.py` passes unmodified.
  - Each reason string appears in exactly one `scripts/` file.
  - `hos_read_repo_file` keeps trailing `\n\n`.
  - The function returns 1, without aborting, when called inside `if` under `set -euo pipefail`.
  - Sourcing the library alters no shell option and installs no trap. Assert this by comparing `set -o` and `trap -p` before and after.
- **S1b:**
  - Every AD-6 table row.
  - Malformed JSON, a duplicate key, an unknown key, a wrong `schema`, `custom` defined, a bad name, a bad glob, and `max_files` set to `true`, 0 or 101 → each exits 2 with **no** stub-vendor invocation. Assert the stub marker file is absent.
  - A milestone file that is outside the root, a dot-path, a symlink or oversize → exit 2.
  - A glob matching `.env`, `.claudetmp/x`, `a.pem` or a tracked symlink → each is excluded and absent from both prompts.
  - Gitignored untracked `src/secret.py` under `src/**` → absent.
  - `src/**` does not match `src/.hidden/x`; `.github/**` matches `.github/x.yml`.
  - 31 matches → NOTICE line, and exactly 30 `=== ` headers in the prompt.
  - A binary file is skipped.
  - A path with a space is included intact (AF-2). The sample contains no literal `\n`.
  - No-spec and rejected-spec → warning plus the AD-7 sentence.
  - Report header: all AD-8 fields present.
  - All existing #911 and #1000 tests pass, with only their target setup ported.

---

## 5. Requirement amendments (recorded here; TD applies them as overriding)

- **AR-1 (REQ-3; AF-4).** The red-team reads `SPEC_FILE` through `hos_read_repo_file` with a 131072 B cap, which is stricter than the second review's `cat`. A rejection is treated as "no spec" with the reason in the warning and in provenance. "The same read" now means the same key, not the same unvalidated `cat`.
- **AR-2 (REQ-4; AF-6).** The format is fixed as strict JSON `hos-red-team-milestones/1` (AD-2):
  - duplicate and unknown keys are errors;
  - limits are 64 KiB per file, 32 milestones, 64 globs, and 4096 chars per text field;
  - `max_files` is optional, from 1 to 100;
  - `custom` is reserved.

  A milestone file that fails path validation is an **error** (exit 2), not a warn-and-fallback. The file is validated whenever its key is set.
- **AR-3 (REQ-6; AF-3).** The selection universe is the git index:
  - symlinks, gitlinks and control-character paths are excluded;
  - wildcards follow the dot rule;
  - binary and non-UTF-8 files are skipped;
  - zero-match globs get a notice;
  - the denylist is extended, with no override.

  Tracked-only and the extension are provisional on ARCH-ESC-1.
- **AR-4 (REQ-2 AC(a); AF-1).** A byte-exact golden is added, committed before the extraction. The threat-model text must never be captured with `$(…)`.
- **AR-5 (REQ-2 AC(c)).** "Validation logic in exactly one file" is tested as follows: each of the six reason strings appears in exactly one `scripts/` file, and neither entry script contains `realpath` or `head -c`.
- **AR-6 (REQ-5, REQ-8).** Exit codes:
  - 2 for usage and config errors, which always happen before any vendor call;
  - 1 for FAIL-CLOSED, unchanged;
  - 0 for `--help`.

  A missing option value is a usage error. The script must be run from the repo top level.
- **AR-7 (REQ-1; AF-2).** The term scan also covers `scripts/oversight/red_team_logic.py` and `scripts/oversight/lib/repo_context.sh`. Sample framing is fixed, with real newlines and no word-splitting.
- **AR-8 (§5 slices).** The slices are re-cut as S1a, S1b and S2 (§4). S1a is behaviour-preserving and can merge on its own. Isolating the mandatory-gate edit keeps its review focused.
- **AR-9 (REQ-9 AC).** "No doc or hint in this repository" is scoped to live operator guidance: the script header, `docs/OVERSIGHT-RUNBOOK.md`, the installer hint and `config.sh` comments. Historical records (`docs/v0.*/**`, `docs/releases/**`, `DECISIONS.md`, `research/**`, `audit/**`) are records and are not rewritten.

I endorse REQ-1, REQ-2 (with AR-4 and AR-5), REQ-5, REQ-7, REQ-8, NFR-1 to NFR-4, and §3 (out of scope) as written.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **Routed to the human. These are not mine to sanction:**
  - **The built-in milestones are removed** (ESC-1). This is user-visible: `--milestone auth` stops working for CPS-shaped consumers on upgrade.
  - **The data-egress surface changes** (ARCH-ESC-1). Which repository content may be sent to OpenAI and Google is a data-handling policy question. My recommendation **narrows** it compared with today, which sends untracked files, `.venv` YAML and symlink targets. A narrowing is still a policy change, and it means untracked work is never red-teamed.
- **No cost, topology or operational change.** There is no new service, credential, scheduled job or dependency. The vendor call count and the ceilings are unchanged.
- **Startup gap: yes** (AF-8). #685 made `run_second_review.sh` project-neutral but never audited the sibling shipped script that carries the same CPS text. Any portability review of shipped scripts at that point should have caught `run_red_team.sh`.
  - **Recommendation to the worker:** open or annotate a `startup-artifact-gap` issue cross-referencing #685 and #2066. I have not filed it, per this task's instructions.
- **Affected sign-offs:**
  - **#1853 and #2057 (threat-model loader).** The behaviour signed off stands. The code moves in S1a, and the S1a reviewers re-check the move against AD-3's golden. Their test file is unmodified, so their test sign-offs stand.
  - **#911 and #1000 (red-team fail-closed).** The logic and messages stand, except that the #1000 message is neutralised; it keeps the substring `no target files matched`. Their tests are re-reviewed in S1b **for the target-setup port only**. The reviewer confirms that no assertion was weakened. The one assertion strengthened is VF-9.
  - **ADR-1683 (D-2, ceilings).** Stands. The vendor path is untouched.
  - **#2017 S2 and #2014 S2.** These are unbuilt, so no approval is orphaned. AD-3's merge-conflict note applies.

---

## 7. Open human escalations

| ESC | Architect | Resolved by architecture? | Gates |
|---|---|---|---|
| ESC-1 | **Concur: (A), no built-ins.** (B)'s "generic presets that still need `--paths`" add a name and nothing else over `--scope`. They would also keep a frozen, HOS-chosen vocabulary in a shipped script. (C) ships consumer text. VF-8 shows the break only affects CPS-shaped projects, which can migrate by copying their table into a JSON file (one file, no code). | **No.** It removes user-visible behaviour | S1b merge |
| ESC-2 | **Concur: warn, state in the prompt, run agy** (AD-7). Failing closed would add a new blocking condition to a checkpoint that some consumers cannot satisfy (no spec), which is a structural gate change. Provenance makes the "no spec" state visible to the human reader. | **No**, but the default is safe and can be accepted with ESC-1 | S1b merge |

**ARCH-ESC-1 (tier `hard-tradeoff`; product-boundary: data egress).** Which repository content may the checkpoint send to the vendors?
- **(a)** Tracked files only, plus the extended denylist (AD-5). Untracked and gitignored files are never sent, and so never red-teamed. *Recommended.* "Committed" is the project's own declaration of what is shareable source, and it closes AF-3 structurally rather than by enumeration.
- **(b)** A filesystem walk with REQ-6's floor denylist only. This reaches untracked work in progress, but also gitignored local secrets.
- Under (b), AD-5's universe becomes a walk that does not follow symlinked directories. Everything else in AD-5 stays.

**Release-note line for the human** (`docs/releases/**` is protected):

> `run_red_team.sh` no longer ships built-in milestones. Define your own in a JSON file named by `RED_TEAM_MILESTONES_FILE` in `scripts/framework/config.sh` (see `docs/examples/red-team-milestones.json`), or run `--paths '<glob>'`. The codex threat model now comes from `THREAT_MODEL_FILE`, and the spec from `SPEC_FILE`. Usage and config errors now exit 2.

```yaml
adr: ADR-2066
issue: 2066
verdict: APPROVED_WITH_AMENDMENTS
codable_now: [S1a]
design_now_merge_after: {S1b: [S1a, ESC-1, ARCH-ESC-1], S2: [S1b, "human CODEOWNER approval"]}
protected_slices: [S2]
risk: {build: HIGH, S1a: MEDIUM, S1b: HIGH, S2: "LOW computed, HUMAN_REQUIRED"}
mandatory_reviewers: {S1a: [code-reviewer, security-reviewer], S1b: [code-reviewer, security-reviewer, privacy-reviewer]}
hard_constraints_not_waivable:
  - "AD-2 milestone file is data: never sourced/eval'd; content via stdin"
  - "AD-3 golden committed before extraction; fixture unchanged by it; no $(...) capture of threat-model text"
  - "AD-5 denylist not overridable; symlinks excluded; anchored segment-wise grammar"
  - "AD-6 #911/#1000 guards unchanged in position and logic"
not_touched: [scripts/oversight/lib/vendor_invoke.sh, scripts/run_redteam_sample.sh, "contract/**", CLAUDE.md, METHODOLOGY.md, scripts/framework/install.sh, ".claude/**", ".github/**"]
escalations:
  - {id: ESC-1, tier: hard-tradeoff, recommended: A-no-builtins, gates: [S1b]}
  - {id: ESC-2, tier: safe-default, recommended: warn-and-run, gates: [S1b]}
  - {id: ARCH-ESC-1, tier: hard-tradeoff, options: {a: tracked-only-plus-extended-denylist, b: fs-walk-floor-denylist}, recommended: a, gates: [S1b]}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **FU-1.** `run_second_review.sh`'s `SPEC_FILE` read should go through `hos_read_repo_file` (AF-4). This is a behaviour change to the mandatory gate and needs its own issue.
- **FU-2.** `create_redteam_issues` should go through `bootstrap/create_issue.sh` (AF-7, CLAUDE.md item 5).
- **FU-3.** The "after steps 3, 6, 10, 11" text in `CLAUDE.md` and `METHODOLOGY.md` is CPS-specific and protected. It needs its own issue (requirements §3).
- **FU-4.** Optional secret scanning of the red-team sample with `secret_scan_logic.py` (R-1).
- **FU-5.** HOS itself could ship a `RED_TEAM_MILESTONES_FILE` for dogfooding. This is not required, because `--paths` works.

## Escalation flag (CORE self-flag)

RISK: HIGH overall. S1b decides which repository bytes are sent to two external vendors, and it parses project-controlled input in a script shipped to every consumer. S1a edits the mandatory pre-PR gate. It is behaviour-preserving by design and proven by a golden.

CONFIDENCE:
- **HIGH** on §0. Every citation was read in this session at `a7894ba0f`.
- **HIGH** on AF-1 and AF-2, which follow from bash quoting and command-substitution semantics.
- **MEDIUM** on whether the second-review codex prompt is fully deterministic across runs. The TD must confirm this, or name the token to normalise (AD-3).

BLAST RADIUS:
- every consumer's checkpoint red-team (S1b);
- every MEDIUM+ second review's codex prompt, if AD-3's proof failed (S1a);
- installer output text (S2).

Change classification: STRUCTURAL.

## Human Review Required

- **ESC-1** and **ARCH-ESC-1** must be ruled before S1b merges. ESC-2's default can be accepted at the same time.
- **S2** touches `scripts/framework/**` and `bootstrap/**`, so it needs a human CODEOWNER approval.
- S1a may be designed, built and merged now.
