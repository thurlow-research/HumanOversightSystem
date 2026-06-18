# Requirements Spec — Issue #336: Move Escalation-Target Extraction and Path-Reference Validation from check_agents_static.sh to Python

**Document type:** Requirements specification
**Status:** Draft — for architect review
**Issue:** #336
**Milestone:** v0.5.0 — Quality
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

`scripts/framework/check_agents_static.sh` contains two categories of logic that violate the
#314 policy ("prefer Python for logic, shell for launch — establish testability as a code
review criterion"):

**1. Escalation-target extraction — already Python but not a named module (lines 178–184):**
The script already calls `python3 -c` for each agent file to extract escalation targets via
regex. This inline Python cannot be imported, mocked, or unit-tested. Pattern boundary cases
(a complex multi-clause sentence before the backtick, an unusual escalation verb form, a
backtick-quoted name in a code block that should not be treated as an agent target) cannot be
verified without running the full script against hand-crafted fixture files. Because this is
inline Python with a shell-interpolated file path (`open('$f')`), any quoting edge case in
the path is also untested.

**2. Token classification — shell grep chains (lines 143–173):**
After extraction, the shell decides whether a token is a genuine agent name by running it
through three sequential `grep -qE` exclusion checks:
- `NON_AGENT_TOKENS` (generic terms like `human`, `main`, `ci`)
- `KNOWN_LABELS` (HOS workflow labels like `needs-human`, `hos-claimed`)
- `KNOWN_SHORT_AGENTS` (single-word agent names like `architect`)
- A hyphen-presence heuristic as a final fallthrough

Each list is a pipe-separated string assembled by the shell. Adding a new label, or moving a
token between lists, requires knowing which guard applies and which list it must go into.
Testing the classifier for a new token requires running the full script. False-positive or
false-negative agent-resolution findings that result from a misclassified token are hard to
reproduce deterministically.

**3. Path-reference validation — section 3, bash grep pipeline (lines 108–132):**
For each agent file, the script uses a `grep -oE` regex to extract backtick-quoted path
references, then applies a cascade of shell filters to decide which references should be
existence-checked. The cascade combines `continue` guards for URLs, empty strings, bare
filenames (no `/`), template placeholders, consumer-project paths, and output-doc exemptions.
This branching filter logic is not independently testable and is easy to mis-anchor (e.g.,
changing the `[[ "$ref_clean" != */* ]]` guard would silently suppress all path findings).

All three blocks involve deterministic, pure classification logic (regex extraction, set
membership, filter chains) that are directly unit-testable as Python functions. The shell
script's remaining work — iterating over agent files with `find … -print0`, invoking `git`
for staleness detection, writing the validation stamp, printing pass/fail summaries — is
genuinely shell work and stays in shell.

---

## 2. Scope

### In scope

- Extract the **escalation-target regex extraction** (lines 178–184) into a named Python
  function in a new module at `scripts/oversight/agents_static_logic.py`.
- Extract the **token classification logic** (lines 143–173) into a named Python function
  in that same module. This includes the `NON_AGENT_TOKENS`, `KNOWN_LABELS`,
  `KNOWN_SHORT_AGENTS` lists and the hyphen heuristic.
- Extract the **path-reference filter logic** (lines 108–132, the per-reference classification
  logic inside the loop) into a named Python function in that same module.
- Update `check_agents_static.sh` to call the Python module for each of these three decisions;
  the shell script must not re-implement the logic.
- All three functions must be unit-testable with synthetic inputs (strings) without running
  `check_agents_static.sh`.

### Out of scope

- The agent-file inventory (section 1: `find` + `grep -m1 '^name:'`) — iterating files and
  extracting frontmatter stays in shell.
- The docs/AGENTS.md coverage check (section 2) — the grep-based name extraction from the
  docs file stays in shell.
- The project-start doc path consistency check (section 5: `DOC_CANONICALS` loop) — see
  note below. The issue body groups this with the extractions, but the logic is a two-stage
  `grep -rl` / `grep -n` pipeline that checks for bare-basename usage without the canonical
  prefix. The architect should rule (OQ-3 below) on whether this section is in scope for this
  issue or deferred.
- The CORE carve-out check (section 6) — stays in shell (simple `grep -q` membership test).
- The agent-to-doc staleness check (section 7) — involves `git diff` output parsing; stays
  in shell.
- The `PROJECT_NON_AGENT_TOKENS` and `EXTERNAL_AGENTS` configuration values — these remain
  sourced from `scripts/framework/config.sh` by the shell script, then passed as arguments to
  the Python module; the module does not source `config.sh` directly.
- The validation stamp write (`scripts/framework/validation-stamps/phase1.stamp`) — stays
  in shell.

---

## 3. Requirements

### R1 — Escalation-target extraction function

The module must expose a function that, given the full text content of an agent file, returns
the list of backtick-quoted names that follow escalation-like verbs. The function must accept:

- `agent_text: str` — the full text of the agent file

The function must return a list of strings: the candidate agent names extracted by the
escalation regex.

The extraction pattern must match the current inline Python behavior exactly. The pattern is:
```
(?i:escalat\w+\s+to|invok\w+|receives?\s+from|notif\w+)[^`]*`([a-z][a-z0-9_-]+)`
```
The function must return all matches found by `re.findall` across the full text (not just
the first match). An agent file with no matching phrases returns an empty list.

### R2 — Token classification function

The module must expose a function that, given a candidate token string and the set of known
agents, determines whether the token is a genuine agent reference that should be
existence-checked. The function must accept:

- `token: str` — the candidate name string
- `known_agents: set[str]` — the set of agent names resolved from the agents directory
- `non_agent_tokens: set[str]` — generic non-agent terms (default: the current
  `NON_AGENT_TOKENS` set: `human`, `you`, `main`, `build`, `prod`, `staging`, `ci`,
  `github`, `pr`)
- `known_labels: set[str]` — HOS workflow label names (default: the current `KNOWN_LABELS`
  set: `needs-human`, `needs-ai`, `needs-coordination`, `hos-claimed`, `hos-halt`,
  `hos-budget-gated`, `hos-embargo`, `hos-autowork-authorized`, `release-request`,
  `release-authorized`)
- `known_short_agents: set[str]` — single-word agent names without a hyphen (default: the
  current set: `architect`, `coder`, `human`)
- `external_agents: set[str]` — agent names declared as external in `config.sh` (default:
  empty set)

The function must return one of three values (or a named enum):
- `SKIP` — the token is a known non-agent term, label, or fails the hyphen heuristic; do
  not existence-check it
- `EXTERNAL` — the token is in `external_agents`; it is valid but has no local file
- `CHECK` — the token should be existence-checked against `known_agents`

The classification must match the current shell behavior exactly:
- If the token matches `non_agent_tokens` exactly: `SKIP`
- If the token matches `known_labels` exactly: `SKIP`
- If the token does not match `known_short_agents` and does not contain a hyphen: `SKIP`
- If the token is in `external_agents`: `EXTERNAL`
- Otherwise: `CHECK`

### R3 — Path-reference filter function

The module must expose a function that, given a raw path reference string extracted from an
agent file, determines whether the reference should be existence-checked on disk. The function
must accept:

- `ref: str` — the raw reference string (may contain backticks, quotes, anchor fragments)
- `output_docs: set[str]` — the set of output-doc paths that are exempt from existence
  checking (default: the current `OUTPUT_DOCS` set from lines 98–106 of the script)

The function must return one of two values (or a named enum):
- `SKIP` — do not check this reference
- `CHECK` — check whether `ref` exists on disk

The filter must match the current shell cascade exactly. A reference is `SKIP` if any of the
following is true after stripping backticks, double-quotes, and anchor fragments (`#…`):
- The cleaned string is empty
- The cleaned string starts with `http`
- The cleaned string contains no `/` (bare filename)
- The cleaned string starts with `{` (template placeholder)
- The cleaned string starts with `PROJECT/` (consumer-project-scoped path)
- The cleaned string (after above cleaning) is present in `output_docs`

Otherwise the result is `CHECK`.

### R4 — Shell calls Python for all three decisions

`check_agents_static.sh` must be updated to invoke the Python module for:

1. Escalation-target extraction (replacing lines 178–184): call the R1 function per agent
   file and iterate the returned list in the shell loop.
2. Token classification (replacing lines 153–166): call the R2 function per token and branch
   on the returned classification value.
3. Path-reference filtering (replacing the per-reference guard cascade in lines 113–121):
   call the R3 function per reference and skip or check based on the returned value.

The shell script must not duplicate the logic. Configuration values
(`PROJECT_NON_AGENT_TOKENS`, `EXTERNAL_AGENTS`) are sourced by the shell from `config.sh`
and passed to the Python module as arguments; the module does not source `config.sh`.

### R5 — Unit-testable without a live script run

The functions introduced by R1, R2, and R3 must perform no subprocess calls, no file I/O
(other than accepting content as string arguments), and no network calls. They must be
importable and callable in a Python unit test with synthetic string inputs.

A CLI shim (`if __name__ == "__main__"`) may be provided for the shell integration, but the
underlying logic functions must be pure.

---

## 4. Acceptance Criteria

**AC1 — Escalation extraction — standard case:** Given an agent file body containing the text
`` "escalates to `architect`" ``, the R1 function returns `["architect"]`.

**AC2 — Escalation extraction — multiple matches:** Given a body containing
`` "invokes `risk-assessor`" `` and `` "notifies `oversight-orchestrator`" ``, R1 returns
a list containing both `"risk-assessor"` and `"oversight-orchestrator"` (order matches
document order).

**AC3 — Escalation extraction — verb variants:** Given a body containing
`` "escalated to `coder`" `` and `` "invoked by `pm-agent`" ``, R1 returns both names (the
`\w+` suffix on verbs must match past-tense and past-participle forms).

**AC4 — Escalation extraction — no false positives from code blocks:** Given a body
containing a fenced code block with `` `coder` `` not preceded by an escalation verb, R1
does not include `"coder"` in the result. (Note: the current regex does not filter code
blocks; AC4 verifies that the Python function matches the current behavior — if the current
inline Python includes such names, the function must also include them. No behavior change.)

**AC5 — Token classification — non-agent tokens:** `classify_token("human", …)` returns
`SKIP`. `classify_token("ci", …)` returns `SKIP`.

**AC6 — Token classification — labels:** `classify_token("needs-human", …)` returns `SKIP`.
`classify_token("hos-claimed", …)` returns `SKIP`.

**AC7 — Token classification — hyphen heuristic:** `classify_token("architect", known_short_agents={"architect"}, …)`
returns `CHECK`. `classify_token("mylib", …)` (not in `known_short_agents`, no hyphen)
returns `SKIP`. `classify_token("code-reviewer", …)` returns `CHECK`.

**AC8 — Token classification — external:** Given `external_agents={"pm-agent"}`,
`classify_token("pm-agent", …)` returns `EXTERNAL`.

**AC9 — Path filter — skip cases:** `filter_path_ref("http://example.com/foo.md", …)`
returns `SKIP`. `filter_path_ref("AGENTS.md", …)` (no slash) returns `SKIP`.
`filter_path_ref("{SPEC_FILE}", …)` returns `SKIP`.
`filter_path_ref("PROJECT/docs/design.md", …)` returns `SKIP`.
`filter_path_ref("docs/pm/CONFIRMED-REQUIREMENTS.md", output_docs={…})` (in output_docs)
returns `SKIP`.

**AC10 — Path filter — check case:** `filter_path_ref("scripts/oversight/panel_logic.py", …)`
returns `CHECK`. `filter_path_ref("contract/OVERSIGHT-CONTRACT.md", …)` returns `CHECK`.

**AC11 — Shell integration — escalation finding:** Running `check_agents_static.sh` against
a fixture agent file that references a non-existent agent produces the same `FAIL:` line as
the current script.

**AC12 — Shell integration — no logic duplication:** `check_agents_static.sh` contains no
inline `python3 -c` escalation-extraction fragments after this change.

---

## 5. Non-Requirements

- **No behavior change.** The refactored script must exit with the same codes and produce the
  same `OK:` / `FAIL:` / `WARN:` lines as the current script for all inputs within the
  existing contract.
- **No new static checks.** This spec does not add new checks (e.g., checking the PACK region
  structure, validating frontmatter fields beyond `name:`).
- **No change to `NON_AGENT_TOKENS` or `KNOWN_LABELS` content.** The lists are extracted
  as-is; additions or removals are out of scope.
- **No change to the validation stamp.** The `scripts/framework/validation-stamps/phase1.stamp`
  write stays in shell and is not affected by this extraction.
- **No change to `--quiet` or `--agents-dir` / `--docs` flag behavior.** Those are shell
  concerns and stay in shell.
- **Shell still performs the file iteration.** The `find … -print0` loop and per-file name
  extraction stay in shell; the Python module receives per-file text content, not directory
  paths.

---

## 6. Open Questions

**OQ-1 — Module placement**
The issue body suggested `scripts/framework/agent_checker.py`. This spec names the module
`scripts/oversight/agents_static_logic.py` for consistency with the `scripts/oversight/` home
of other extracted Python logic (SPEC-331, SPEC-334, etc.). The architect should confirm the
correct home, noting that `check_agents_static.sh` itself lives in `scripts/framework/` and
the module's natural consumer is that script. A module in `scripts/framework/` is equally
reasonable; the architect should rule on the convention.

**OQ-2 — Section 3 path-reference extraction (the grep itself)**
This spec extracts the per-reference filter logic (the classification cascade) but leaves the
`grep -oE` that extracts the raw references in shell (line 128). The architect should rule
on whether the `grep -oE` pattern extraction itself should also move to Python (as a fourth
function that returns all path references from agent text), or whether extracting just the
filter logic is sufficient for this issue.

**OQ-3 — Section 5 doc-path consistency check**
The issue body lists the project-start doc path consistency check (section 5, lines 199–218)
as a candidate for Python extraction alongside sections 3 and 4. This spec does not include
it in scope because the logic is a grep-based file search (`grep -rl` then `grep -n` per
file) that is harder to isolate as a pure string function. The architect should rule on
whether section 5 is in scope for this issue or should be a separate issue.

**OQ-4 — Shell integration interface**
For R1 (escalation extraction), the shell script currently calls `python3 -c` once per agent
file in a loop, receiving one name per output line. The Python module could be called as:
(a) a CLI that accepts the agent file path as an argument and prints one name per line (same
interface as current, one subprocess per file), or (b) a CLI that accepts the agent file
content on stdin (avoids any shell quoting concerns with the path). The architect should rule
on the preferred interface for the shell integration.

---

## 7. Context for Architect

- The three logic blocks being extracted are at:
  - Lines 178–184: inline `python3 -c` escalation extraction (per agent file, in a loop)
  - Lines 143–173: token classification shell cascade (per extracted token, in an inner loop)
  - Lines 108–132: path-reference filter cascade (per path reference, in an inner loop)
  `check_agents_static.sh` is at `scripts/framework/check_agents_static.sh`.
- The `scripts/oversight/` directory already contains `panel_logic.py`,
  `suspension_manager.py`, `signoff_gate.py`, and others — the extraction pattern for Python
  logic modules is well established. `scripts/framework/` contains the shell scripts that
  consume those modules.
- The current inline `python3 -c` for escalation extraction (lines 178–184) already has the
  correct regex; the R1 requirement is to promote it to a named, importable function, not to
  change its behavior.
- The token classification shell cascade (lines 143–173) sets `NON_AGENT_TOKENS` and
  `PROJECT_NON_AGENT_TOKENS` at the top of section 4. `PROJECT_NON_AGENT_TOKENS` comes from
  `config.sh`; the Python module must accept it as a parameter (not by sourcing `config.sh`)
  so the function remains testable in isolation.
- Issue #314 is the policy driver. Issues #331 through #335 and #337–#338 are sibling
  refactors applying the same pattern to other scripts.
- The R2 classification result has three values (`SKIP`, `EXTERNAL`, `CHECK`) not two,
  because the shell currently emits a distinct `ok "… (external — lives in consumer
  projects)"` message for external agents (line 170–171). The Python function must return
  the three-way distinction so the shell can emit the correct message.
