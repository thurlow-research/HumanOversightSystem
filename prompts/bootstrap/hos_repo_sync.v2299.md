# Prompt Artifact — hos_repo_sync.sh prune hardening (#2299)

| Field | Value |
|---|---|
| **Generated file** | `bootstrap/hos_repo_sync.sh` (+ `tests/automation/test_hos_repo_sync.py`, `CLAUDE.md`, `templates/CLAUDE.human.md`, `SCRIPTS-INDEX.md`) |
| **Description** | #2299 items 1-4 + 6: import-path hardening, fail-closed registry gate P4b, no re-mint inside the prune, per-local-deletion audit event, doc rows. Item 5 split out. |
| **Date** | 2026-11-10 |
| **Model** | claude-opus-5-5 |
| **Risk level** | MEDIUM (worker-declared; risk-assessor may raise) |
| **Human review status** | ⬜ Pending |

---

## Worker design decisions (bind the coder)

1. **Item 1 — `-E -s`, not `-P`.** The issue suggests `-P`. With `python3 -m scripts.automation.readopt`, `-P` removes the cwd entry from `sys.path`, and the cwd (the script's own clone, gate P4) is exactly what makes `scripts.automation.readopt` importable — so `-P` would break the prune. `-E` (ignore all `PYTHON*` env vars, including `PYTHONPATH`/`PYTHONHOME`/`PYTHONSTARTUP`-class influence) plus `-s` (no user site-packages) removes the caller-controlled import paths while keeping the clone root, and works on every Python 3, so no version fallback is needed.
2. **Item 2 — canonical semantics are literal; the prune fails closed.** `bin/hos-cron` (`_conf_val`: `cut -d= -f2-`), `bin/hos-human`, `bootstrap/lib/role_clone_check.sh` and `bootstrap/lib/hos_tmp_root.py` all read the value literally; a quoted value would already break `bin/hos-cron` (`REPO_ROOT` would contain the quotes). So quotes are not stripped. Instead gate P4b fails closed: any `*_(worker|overseer)_root=` line whose (trimmed, slash-stripped) value is non-empty but does not resolve to an existing directory makes the prune skip with a message naming the key (never the value's contents beyond the key name). Other readers are unchanged.
3. **Item 3 — no re-mint inside the prune.** The prune child runs with `HOS_TOKEN_APP_ROLE` unset, so `scripts/automation/lib/github.py` never spawns its 90 s re-mint; a 401 fails fast and the prune deletes nothing (best-effort step, sync result unaffected). The script-level gate P2 still requires `HOS_TOKEN_APP_ROLE=human` in the parent. `github.py` is not changed.
4. **Item 4 — audit like `bin/hos-cron`'s overseer reap.** Each output line that fully matches hos-cron's anchored `_RB_EVENT_RE` with `where=local` emits a best-effort `audit_write_event` (via `scripts/oversight/lib/audit_log.sh`, same guarded-source pattern as `bootstrap/delete_branch.sh` `_audit_branch_delete`): event `repo-sync-branch-reap` (REAPED) or `repo-sync-branch-reap-failed` (REAP-FAILED), fields `role=human`, `branch`, `reason`, `where`, `pr`, `tip`. Lines are still streamed to the terminal as now. Audit never changes exit status.
5. **Item 5** (project TELEMETRY-SPEC.md via ops-designer) is split into a separate issue.

## Prompt

Dispatched by the autonomous worker to the `coder` subagent (exact text below).

```
Implement HOS issue #2299 (follow-up of #2288 S3) in /home/scott/Code/HumanOversightSystem/Worker on branch worker-2299-repo-sync-prune-hardening-261110082001-2984900 (already checked out — do not create or switch branches; do not git stash or git checkout other refs). Read first: bootstrap/hos_repo_sync.sh, docs/v0.7.0/TECHNICAL-DESIGN-2288-S3-repo-sync-prune.md, tests/automation/test_hos_repo_sync.py, bootstrap/delete_branch.sh (_audit_branch_delete), bin/hos-cron lines ~1760-1790 (_RB_EVENT_RE + _audit), scripts/oversight/lib/audit_log.sh, and the worker design decisions in prompts/bootstrap/hos_repo_sync.v2299.md (they bind you).

Changes, all in bootstrap/hos_repo_sync.sh unless noted:
1. Prune invocation: run `env -u PYTHONPATH -u HOS_TOKEN_APP_ROLE python3 -E -s -u -m scripts.automation.readopt ...` (keep all existing args, the timeout wrapper, </dev/null). Do NOT use -P (it drops the cwd that makes -m scripts.* importable). Comment why, briefly.
2. _is_registered_cron_root / gate P4b: literal values (no quote stripping). If any *_(worker|overseer)_root= line has a non-empty value that is not an existing directory, the prune must skip (fail closed) with `prune skipped — registry entry <key> does not resolve to a directory` (print the key only). Matching an existing directory against the clone stays as now.
3. Item 4: replace the awk post-processor with a bash `while IFS= read -r` loop (or equivalent) that keeps printing `hos-repo-sync: prune: <line>` unbuffered and the recovery hint after any REAPED line, and for each line fully matching
   '^(REAPED|REAP-FAILED) branch=([A-Za-z0-9._/@+-]+) reason=([a-z-]+) where=(local|remote)( pr=(#[0-9]+|-))? tip=([0-9a-f]{40})$'
   with where=local emits a best-effort audit event (repo-sync-branch-reap / repo-sync-branch-reap-failed; role=human, branch, reason, where, pr, tip) via scripts/oversight/lib/audit_log.sh audit_write_event, guarded exactly like delete_branch.sh (missing lib or function → silently skip; never affects exit status). Build JSON safely (the regex already restricts characters; still escape nothing unvalidated). The readopt exit status must still be captured correctly (PIPESTATUS or equivalent) and the timeout WARN path kept.
4. Update the header comment block to describe the hardening (one or two lines each).
5. Docs (item 6): CLAUDE.md "Repo sync" canonical-entry-point row and session-start step 4 text, and templates/CLAUDE.human.md (around line 61) — add that bootstrap/hos_repo_sync.sh also runs an opt-in local-branch prune (HOS_REPO_SYNC_PRUNE=1, which bin/hos-human turns on; Human clone only). Keep edits minimal, plain English, short sentences. Then regenerate SCRIPTS-INDEX.md with scripts/framework/gen_scripts_index.sh (or scripts/framework/regen_all.sh) if the header first line changed.
6. Tests in tests/automation/test_hos_repo_sync.py (extend existing fixtures/style; no network; clean temp via tmp_path): (a) prune child env has no PYTHONPATH/HOS_TOKEN_APP_ROLE and python gets -E -s (e.g. stub python3 on PATH recording argv/env); (b) quoted registry value `x_worker_root="/path"` → prune skipped with the key named, nothing deleted; (c) a registry value pointing at a nonexistent dir → skipped; (d) an unquoted existing non-matching root → prune still runs (no regression); (e) REAPED where=local line → one audit event file written with the right fields; REAP-FAILED → -failed event; a forged/non-matching line (e.g. trailing junk, where=remote) → no event; (f) missing audit lib → prune output and exit status unchanged. No change to the prune's default deletion set (do not touch readopt.py or github.py).

Run: scripts/oversight/.venv/bin/python -m pytest tests/automation/test_hos_repo_sync.py tests/automation/test_hos_human_launcher.py tests/framework/test_hos_human_launcher.py -q ; shellcheck bootstrap/hos_repo_sync.sh ; bash scripts/oversight/run_gates.sh on the changed files. All must pass.

Commit (one or two commits) with exactly this contiguous trailer block at the end of each message (no blank lines inside it):
Prompt-Artifact: prompts/bootstrap/hos_repo_sync.v2299.md
AI-Model: claude-opus-5-5
AI-Risk: MEDIUM
Supervised-by: ScottThurlow
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>

Do NOT write closes/fixes/resolves followed by an issue number anywhere. Do not push, file issues, edit labels, or post comments. If you will not edit CLAUDE.md or templates/CLAUDE.human.md, say so and leave them; the worker will. End with your AGENTS.md self-flag (RISK/CONFIDENCE/BLAST RADIUS) and the test output summary.
```
