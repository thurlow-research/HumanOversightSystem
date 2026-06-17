# SPEC-54 — Prompt Capture Auto-Hooking in install.sh

**Status:** Draft
**Issue:** #54
**Date:** 2026-06-17

---

## Problem Statement

`capture_prompt.sh` and `capture_session.sh` must be invoked manually by engineers before MEDIUM+ commits. Engineers routinely forget this step. The gate (`scripts/oversight/gates/`) detects the absence of prompt artifacts only after the fact — at review time — rather than preventing the gap at authoring time. There is no mechanism today that reminds or prompts the engineer to capture during a coding session, nor any install-time opt-in that wires such reminders automatically.

This creates a systematic compliance gap: the gate enforces the requirement, but the tooling does not help engineers satisfy it proactively.

---

## Scope

This spec covers three concrete behaviors introduced at **install time** (`bootstrap/hos_install.sh`):

1. **Interactive prompt** — during project setup, `hos_install.sh` asks the operator whether to enable prompt artifact capture hooks for MEDIUM+ changes.
2. **Settings.json hook wiring (yes path)** — if the operator opts in, the installer writes Claude Code hooks to `{target_project}/.claude/settings.json` that fire during coding sessions.
3. **Gate-suspension opt-out path (no path)** — if the operator opts out, the installer appends a `SUSPENDED: prompt-capture` entry to `contract/gate-suspension.md` with a dated install-time note, so the gate knows capture is intentionally disabled.

This spec does **not** cover:
- Changes to `capture_prompt.sh` or `capture_session.sh` internals.
- Gate logic changes (the gate already reads `contract/gate-suspension.md`).
- Requiring hooks to be present — gate-suspension covers the opt-out and is a valid installed state.
- Any changes to `.claude/agents/` files.

---

## Requirements

### R1 — Interactive prompt in `hos_install.sh`

During project setup, after the existing `.claude/settings.json` merge section, `hos_install.sh` MUST present the following prompt to the operator when running interactively (i.e., when stdin is a terminal, `[[ -t 0 ]]`):

```
Enable prompt artifact capture for MEDIUM+ changes? [Y/n]:
```

- A blank response or `Y`/`y` is treated as yes (opt-in by default).
- An explicit `n`/`N` response is treated as no (opt-out).
- When the installer is running non-interactively (stdin is not a terminal, e.g., CI) or the `--yes` flag is passed, the prompt is skipped and the **yes path** (R2) is taken silently as the default.
- The `--yes` flag MUST be accepted as a new installer flag that suppresses all interactive prompts and accepts defaults. It applies globally (including this prompt).

### R2 — `settings.json` hooks written on yes

When the operator selects yes (or the default is taken non-interactively), the installer MUST write the following two Claude Code hooks into `{target_project}/.claude/settings.json`, merging with any existing content rather than overwriting:

**Hook 1 — `PostToolUse` session logger**

Fires after every `Edit`, `Write`, or `Bash` tool use. Invokes `capture_session.sh` with `--log`, passing the tool's file parameter and description.

Hook specification:
```json
{
  "type": "command",
  "command": "bash scripts/capture_session.sh --log \"$CLAUDE_TOOL_INPUT_FILE\" \"$CLAUDE_TOOL_NAME tool use\""
}
```

Registered under `hooks.PostToolUse` with a matcher on tool names `Edit`, `Write`, and `Bash`.

**Hook 2 — `Stop` reminder**

Fires when the agent session ends (the `Stop` event). Prints a reminder message to the operator to run `capture_prompt.sh` if MEDIUM+ files were changed in the session.

Hook specification:
```json
{
  "type": "command",
  "command": "echo 'HOS: If MEDIUM+ files were changed this session, run: bash scripts/capture_prompt.sh <file> \"<description>\"'"
}
```

Registered under `hooks.Stop`.

**Merge rules:**
- If `hooks.PostToolUse` already exists in `settings.json`, the new entry is appended to the array (not overwriting existing entries).
- If `hooks.Stop` already exists, the new entry is appended to the array.
- Hook paths are relative to the project root (not absolute), so they work for any engineer checking out the project.
- The merge is performed using `python3` (already a required prerequisite), consistent with the existing settings merge pattern in the installer.
- Dry-run mode (`--dry-run`) MUST skip the write and print what would be done.

### R3 — Gate-suspension opt-out on no

When the operator selects no, the installer MUST append the following entry to `{target_project}/contract/gate-suspension.md`, creating the file if it does not exist:

```
SUSPENDED: prompt-capture
Reason: Opted out at install time (hos_install.sh, {ISO-8601 date})
Scope: all steps
```

Where `{ISO-8601 date}` is the UTC timestamp at the moment of install (e.g., `2026-06-17T14:23:00Z`).

**Rules:**
- If `contract/gate-suspension.md` already exists and already contains `SUSPENDED: prompt-capture`, the installer MUST skip the append and print a skip message (idempotent).
- Dry-run mode MUST skip the write and print what would be done.
- The installer MUST print a `warn` message informing the operator that the prompt-capture gate is suspended and how to re-enable it (re-run the installer, or manually remove the line from `gate-suspension.md`).

---

## Non-Requirements

The following are explicitly out of scope for this spec:

- **No changes to `capture_prompt.sh` or `capture_session.sh`** — their invocation signature, artifact format, and output are unchanged.
- **Hooks are not mandatory** — the opt-out path via `gate-suspension.md` is a valid installed state. The gate must still pass when `SUSPENDED: prompt-capture` is present.
- **No enforcement that hooks are present** — the gate does not check `settings.json` for hook presence; it only checks for prompt artifacts or a suspension entry.
- **No retrospective enforcement** — existing installs without this feature are not affected; the behavior is introduced only on a fresh install run that reaches this prompt.
- **No UI for toggling post-install** — operators who want to change their choice re-run `hos_install.sh`. The installer is idempotent.

---

## Acceptance Criteria

1. Running `hos_install.sh` interactively presents the prompt defined in R1 after the settings.json merge section.
2. Answering yes (or defaulting) writes the two hooks to `settings.json` per R2; the file remains valid JSON; existing permissions and hooks are preserved.
3. Answering no writes the suspension entry per R3; the file is created if absent; the entry is not duplicated on a second run.
4. Running with `--yes` takes the yes path without prompting.
5. Running non-interactively (piped stdin) takes the yes path without prompting.
6. `bash -n bootstrap/hos_install.sh` passes (syntax check).
7. Dry-run mode prints the intended operations without writing any files.
