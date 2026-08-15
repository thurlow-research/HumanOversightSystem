# ADDENDUM-1221 — Never-overwrite reconciliation

**Status:** BINDING. Amends SPEC-1221, ADR-1221 and TECHNICAL-DESIGN-1221 in place.
**Date:** 2026-08-15 · **Author:** technical-design · **Issue:** #1221 · **Milestone:** v0.6.0 · **Risk tier: MEDIUM** (unchanged)
**Authority for the change:** the human ruling posted on issue #1221 on 2026-08-15 (Decision 1, Decision 2, the revised acceptance list, and the edge case bearing on #1389).
**Consumer:** `coder`. Read this document **second**, immediately after TECHNICAL-DESIGN-1221, and implement **TD-as-amended**. Where this document and the TD disagree, this document wins. Where it is silent, the TD stands verbatim.

**Scope:** one product decision changed — what `generate` does when it finds a file already present. Nothing else in the design chain is reopened. This is a reconciliation note, not a redesign.

---

## 1. Provenance of the design chain — read this before anything else

The three binding documents are **not on `main`**. They exist only in commit `1cb59413` on the unpushed local branch `worker-1221-gen-sandbox-config-260805020001`:

```
git show 1cb59413:docs/v0.6.0/SPEC-1221-clone-sandbox-config-generation.md
git show 1cb59413:docs/v0.6.0/ADR-1221-clone-sandbox-config-generation.md
git show 1cb59413:docs/v0.6.0/TECHNICAL-DESIGN-1221-clone-sandbox-config-generation.md
```

**The `coder` must land all three of those files unchanged, plus this addendum, as part of the implementation PR.** They are the reviewed record; a PR that ships the generator without them ships unreviewable code. They are not to be edited to absorb this addendum — supersession is recorded here, in one place, so the review history stays legible.

### 1.1 An older, abandoned implementation exists. Do not mine it for structure.

Commits `765821b3` (`scripts/framework/sandbox_config.py` + `sandbox_policy.py`) and `671a0308` (`contract/sandbox-policy-roles.json` + a template diff) predate this SPEC/ADR/TD and implement a **different, since-abandoned architecture** (two modules, `generate`/`check` subcommands, a merged `settings.json`, a roles-overlay layer). They are reference-only, for idioms at most. **Five things from them are explicitly excluded scope and must not appear in this build:**

| Excluded | Where it came from | Why excluded |
|---|---|---|
| `"Bash(gh repo:*)"`, `"Bash(gh pr:*)"`, `"Bash(gh issue:*)"` in `permissions.allow` | `671a0308` template diff | Backed by **no** FR in SPEC/ADR/TD. FR-13 and TD §8.3 bind `permissions.allow` to **no edit at all**. An allow is not monotonic — this would grant capability no reviewer approved. |
| The "D1 leading-slash" rewrite (`__HANDOFF_DIR__` → `/__HANDOFF_DIR__`, and the same for `__HOS_ROOT__`, `__CONFIG_DIR__` across allow and deny) | `671a0308` template diff | TD §8.3: "Everything else in the template is unchanged." The only deliberate leading-slash spellings in this build are the two new `bin/**` and three new sidecar denies in TD §8.1. |
| `contract/sandbox-policy-roles.json` (the roles-overlay layer with `"status": "resolved"｜"unresolved"`) | `671a0308` | TD-1221 achieves the same #1146 gating with `SUPPORTED_ROLES = ("human",)` + `gate_role()` + exit `3` (TD §2.4, §6 fn 2). It is not in TD §1's file manifest. Do not create it. |
| Splitting the generator across two modules | `765821b3` | AD-2 / TD §1: **one** file, `scripts/framework/gen_sandbox_config.py`. |
| `settings.json` merge behaviour, `--dry-run`, `--out-dir`, `--strict`, `--allow-missing-paths` | `765821b3` | E-1 (deferred to a human); the CLI is exactly TD §3 as amended by §4 below. |

The **one** substantive fact worth taking from that older work is recorded in §6 of this document.

---

## 2. What is superseded, precisely

| Artifact | Section | Status |
|---|---|---|
| SPEC-1221 | **FR-7** ("refuses to overwrite … without an explicit force flag, and writes a timestamped backup") | **SUPERSEDED in full** by §3 below. |
| SPEC-1221 | **AC6** ("without the force flag exits non-zero … with the flag, a backup exists") | **SUPERSEDED in full** by §5's revised acceptance. |
| SPEC-1221 | **AC1** | **AMENDED**: the "after the generator has written it" step must move the stale live file aside first (there is no `--force` to overwrite it with). Everything else about AC1 stands. |
| ADR-1221 | **AD-3.3** (backup taken before the replace; printed restore command) | **SUPERSEDED** — no backup is taken because nothing is ever overwritten. AD-3.1 and AD-3.2 (validate-before-write; temp + `os.replace`) **stand unchanged**. |
| ADR-1221 | **AD-4**, the `[--force]` line and the `4 = refuse-to-overwrite` code | **AMENDED** — see §4. |
| ADR-1221 | **§4 N1** ("first `--force` run needs the operator present") | **MOOT** — there is no `--force` run. Replaced by the §3.4 enrollment procedure, which is likewise an operator action, likewise not a design gate. |
| TD-1221 | **§3.4** (`--force`, `--check --force`) | **SUPERSEDED** by §4. |
| TD-1221 | **§6.6 `run_generate` steps 2–3 and step 6** | **SUPERSEDED** by §3.5. |
| TD-1221 | **§6.8 `backup_live`** | **SUPERSEDED** — the function is not built. Its **naming convention survives** as the aside-name the tool *prints* (§3.4). |
| TD-1221 | **§6 function table** rows 16 (`backup_live`) and 19 (`regenerate_command`'s `force` parameter) | **AMENDED** — see §4.4. |
| TD-1221 | **§2.1 rule 3** (the enumeration of generate mode's contact with the live file) | **RESTATED** in §3.6. The substantive AD-1 invariant is unchanged. |
| TD-1221 | **§10** tests 1, 15, 16, 17, 19, 20 | **AMENDED / REPLACED** — see §5.2. |
| TD-1221 | **§4** exit-code table, row `4` | **REPURPOSED** — see §4.2. |

Everything not listed above **stands verbatim**. §7 enumerates the load-bearing parts that a reader might wrongly assume this ruling touched.

---

## 3. What replaces it — the three-way branch

`generate` (i.e. no `--check`) classifies the live file **once**, before deciding anything, and takes exactly one of three branches. There is no fourth branch and no flag that adds one.

### 3.1 Classification — exact definition

Let `live = <clone-dir>/.claude/settings.local.json`.

| Class | Condition |
|---|---|
| **ABSENT** | `live` does not exist. |
| **UNUSABLE** | `live` exists **and** any of: it is a directory; it is not readable; its size is 0; its content is whitespace-only; `json.loads` raises; the parsed top level is not a JSON object. |
| **USABLE** | `live` exists and parses to a JSON object. **Content and age are irrelevant** — a hand-written file that shares nothing with the template is USABLE. |

The classifier reads `live` at most once and returns `(class, reason, live_text｜None)`. `reason` is a short human phrase (`"zero-length"`, `"not valid JSON: <detail>"`, `"top level is not a JSON object"`, `"is a directory"`, `"not readable: <detail>"`) that is printed verbatim in the UNUSABLE message.

### 3.2 ABSENT → write

Write `live` (TD §6.7 `write_atomic`, unchanged), then write the sidecar (TD §5.1, unchanged ordering: sidecar strictly after the policy file). Exit **0**.

Print: the output path, the sidecar path, the `regenerate_command(...)` line, and "restart the session for the new policy to take effect."

### 3.3 USABLE → leave alone, exit success, print an advisory

**The file is not opened for writing, not renamed, not backed up, not touched in any way.** Byte-identical and mtime-identical before and after.

Exit **0**. This is the normal steady state on every re-run, not an error.

**No sidecar is written.** This is derived and load-bearing: the sidecar records the values that produced *this* live file, and this run produced nothing. Writing one here would make `--check` compare a freshly-rendered document against a file the generator never wrote, and report permanent, unfixable divergence. If a sidecar already exists (the clone was previously enrolled), it is **left exactly as found** — not rewritten, not timestamp-bumped.

The success message must say, unambiguously, that the file **already existed and was left unchanged — nothing was written by this run**, and must not read as though generation succeeded.

**Advisory diff (required by the ruling; read-only).**

- Computed from `rendered` (already final) against the parsed live document, reusing `compare()` (TD §6.5). No new comparison code.
- **Reports only `MISSING` and `MISSING_KEY`** — entries/keys present in the generated document and absent from the live one. That is exactly the ruling's "HOS-owned/managed entries the existing file lacks."
- **Does not report** `EXTRA`, `EXTRA_KEY` or `CHANGED`. Operator additions are legitimate by construction under this ruling, and listing them turns an advisory into pressure to clobber. The advisory's last line must point at `--check` for the full, symmetric comparison.
- Printed under a heading that says **ADVISORY** and states it is informational and that **nothing was changed**.
- If there is nothing missing, print one line saying the existing file already carries every managed entry.
- **It must not affect the exit code, ever.** Bind this structurally: the whole advisory block runs inside a `try`/`except Exception` that prints `advisory unavailable (<reason>)` and continues. This is a deliberate, narrow exception to TD §4's "top-level `except Exception` → exit 5" rule; without it a bug in advisory formatting converts a correct success into a hard failure. The exception handler must be scoped to the advisory block alone and carry a comment saying why.

### 3.4 UNUSABLE → report loudly, change nothing, exit non-zero

Exit **4** (§4.2). **Never clobber, never silently skip.** Neither the policy file nor the sidecar is written.

The message goes to **stderr** and must contain, at minimum:

1. The absolute path of the offending file.
2. The `reason` from §3.1, verbatim.
3. The explicit statement that **nothing was written and the existing file was not modified**.
4. A copy-pasteable remedy — move it aside, then re-run:
   ```
   mv <live> <live>.bak-<UTC compact ISO>
   <the exact regenerate command>
   ```
   The aside suffix is `.bak-<%Y%m%dT%H%M%SZ>` — deliberately the same convention TD §6.8 gave the (now-dropped) automatic backup, so the printed instruction and the `.gitignore` entry `.claude/settings.local.json.bak-*` (TD §5.4, unchanged) agree. The *operator's* hand performs the move; the tool never does.

This branch is the direct answer to **#1389** (Human clone has a `settings.local.json` that is not a usable generated config). Note the split it introduces, which the original single "differs → refuse" path could not express: a Human clone whose file is present and merely *hand-maintained* is USABLE → exit 0, untouched, advisory printed. Only a genuinely corrupt file reaches this branch.

### 3.5 `run_generate` — replacement sequence (supersedes TD §6.6's `run_generate`)

Everything in TD §6.6 steps 1–10 (`main()` up to and including `render()`) is **unchanged**. Only the dispatch body changes:

1. `live = clone_dir / LIVE_RELPATH`.
2. `state, reason, live_text = classify_live(live)` — the only read of `live` in generate mode, and it happens **after** `rendered` is already final.
3. `state == UNUSABLE` → print the §3.4 report to stderr → return **4**. Nothing written.
4. `state == USABLE` → print the §3.3 success line, then the advisory (guarded per §3.3) → return **0**. Nothing written — no policy file, no sidecar, no temp file.
5. `state == ABSENT` → `write_atomic(live, rendered)`; then `write_values_file(...)`; then print §3.2's block → return **0**.

`run_check` is **unchanged** (TD §6.6, §6.5).

### 3.6 AD-1 restated (supersedes TD §2.1 rule 3; substantive invariant unchanged)

The binding invariant is, and remains:

> **No byte that generate mode writes may depend on the content of the live file or of the values sidecar.**

Its two structural guarantees are unchanged and are what the tests assert:
1. `render(template_text, values)` takes **no path parameter of any kind** (TD §2.1 rule 1; test 18).
2. Generate mode does not read the values sidecar (TD §5.3; unchanged).

TD §2.1 rule 3 previously enumerated generate mode's contact with the live file as "an existence test, and a backup copy taken after the output content is already fully determined." **Replace that enumeration with:** *generate mode's only contact with the live file is `classify_live()`, which runs after `rendered` is final, and whose result may influence only (a) whether the write happens at all and (b) what is printed — never the bytes.*

**This is a wording change, not a loosening.** The old design already read the live file in generate mode (`shutil.copy2` in `backup_live`); the advisory read is the same class of post-render contact, substituted for it. The one casualty is the crisper phrasing ADR §6.3 adopted — *"generate mode opens exactly one file for reading, the template"* — which was already inconsistent with TD §2.1 rule 3(b) in the same document. **Routed to `architect` as a notification** (§9). If the architect rejects the restatement, the clean fallback is to drop the §3.3 advisory diff entirely: it is the ruling's *"mitigate with"* clause, not its operative decision, and dropping it restores "exactly one file" literally while leaving §3.1–§3.5 intact. Do not block the build on this.

---

## 4. CLI, exit codes, functions

### 4.1 `--force` is REMOVED. Decision and reasoning.

**`--force` does not exist. No flag reinstates overwriting. `generate` never modifies an existing `settings.local.json`, full stop.**

Reasoning, since the ruling left the call here:

1. **The ruling's own rationale forecloses it.** "Never overwrite … there is no merge logic to build … operator edits are safe by construction." A `--force` that clobbers reintroduces exactly the hazard the ruling removes, and reintroduces it behind a flag whose whole purpose is to be passed when someone is in a hurry.
2. **It closes a link in the #1183 escalation chain.** ADR AD-7 named the attack explicitly: `contract/sandbox-policy.template.json` is agent-writable at the OS layer, so an agent can edit the template *and then regenerate with `--force`*, rewriting the policy that constrains it. With no `--force`, that path requires an agent to first delete or corrupt the live policy file — a far louder act, and one the sandbox's own `Edit(./.claude/settings.local.json)` denies already cover. This is a **security improvement**, not merely a simplification.
3. **It deletes code from a security boundary.** `backup_live`, the same-second `-1`/`-2` collision suffixing, the restore-command printing, and the "a backup that could ever contain generator output is not a backup" invariant all disappear. AD-3.3 existed only to make overwriting survivable.
4. **Keeping it would leave the ruling ambiguous.** `--force` on an UNUSABLE file would have to mean "clobber", which the ruling forbids in terms ("never clobber"). A flag that is refused in the one case an operator would reach for it is worse than no flag.

The escape hatch the operator loses is one `mv`, printed by the tool, performed knowingly — which produces exactly the backup FR-7 wanted, taken by a human hand rather than by the tool at 3am.

**Bind a test that the flag does not exist** (§5.2, test 17R), so a future reader cannot reason it back in.

### 4.2 Exit codes — replacement table

Seven codes, still `0`–`6`, still pairwise distinct. **One meaning changes: `4`.**

| Code | Constant | Meaning | Mode |
|---|---|---|---|
| `0` | `EXIT_OK` | generate: file written **or** an existing usable file left untouched. `--check`: live file matches a fresh generation. | both |
| `1` | `EXIT_DIVERGENT` | `--check` only: divergence (incl. live file missing, unparseable, or containing a surviving `__NAME__`). | check |
| `2` | `EXIT_USAGE` | usage error: bad/missing/unrecognized flags, bad `--clone-dir`, invalid value. | both |
| `3` | `EXIT_UNSUPPORTED_ROLE` | `--role worker` / `--role overseer` — message names **#1146** (FR-5). | both |
| `4` | **`EXIT_UNUSABLE_EXISTING`** | **generate only: the existing live file is present but unparseable/empty/unreadable (§3.1 UNUSABLE). Nothing written, nothing clobbered.** *(Was `EXIT_REFUSE_OVERWRITE`; that meaning is retired — nothing was ever built against it.)* | generate |
| `5` | `EXIT_HARD_FAIL` | surviving placeholder, malformed template, malformed/incomplete/wrong-version sidecar, any unexpected internal error. | both |
| `6` | `EXIT_NOT_ENROLLED` | `--check` only: no values sidecar — this clone was never generated. | check |

TD §4's three guarantees stand unchanged: all seven distinct; `1` reserved for divergence alone (so `main()` must never leak a bare `1` from an unhandled exception); exit `3` occurs before any filesystem access.

**Deliberate asymmetry, recorded so no reviewer reads it as a bug:** an unparseable live file is exit `4` in generate mode (act now, the policy is not in effect) and exit `1` in `--check` mode (TD §6.5 special case 2, unchanged — divergence, which the `validate_setup.sh` hook already renders as a loud non-blocking WARN). Both are non-zero and both are loud; they differ because the operator's next action differs.

### 4.3 CLI surface — replacement for TD §3's block

```
scripts/framework/gen_sandbox_config.py
    --role {human|worker|overseer}          REQUIRED
    --clone-dir PATH                        REQUIRED
    [--check]
    [--project-root PATH]
    [--hos-root PATH]
    [--config-dir PATH]
    [--home PATH]
    [--handoff-dir PATH]                    REQUIRED in generate mode
    [--claude-project-state PATH]           REQUIRED in generate mode
```

Only `[--force]` is removed. TD §3.1, §3.2 (the seven-placeholder flag table), §3.3 (normalization/validation), §3.5 (echo-back) and §3.6 (provenance) are **unchanged**. TD §3.4's `--check --force` usage error disappears with the flag.

### 4.4 TD §6 function-table amendments

| TD row | Change |
|---|---|
| 16 `backup_live` | **Removed.** Not built. |
| **new** `classify_live(live)` | `(Path) -> tuple[str, str, str｜None]` — §3.1. Returns `(state, reason, live_text)`. Never raises for a bad file; a bad file is data, not an error. Reads `live` at most once. |
| **new** `format_advisory(findings, live_path)` | `(list[Divergence], Path) -> str` — §3.3. Filters to `MISSING` / `MISSING_KEY` only. |
| 19 `regenerate_command(values, clone_dir, force)` | Drop the `force` parameter → `regenerate_command(values, clone_dir)`. It no longer emits a `--force` tail. |
| 20 `run_generate(...)` | Body replaced per §3.5. Signature shape unchanged. |
| 2.2 module docstring | Must document the §4.2 table (all seven codes, with `4`'s new meaning) and state the never-overwrite rule in one sentence. `--force` must not appear in either usage form. |

---

## 5. Acceptance and tests

### 5.1 Revised acceptance (replaces SPEC AC6; amends AC1)

1. **ABSENT** `settings.local.json` in a clone → the generator writes it, all seven placeholders resolved, **no `__PLACEHOLDER__` remaining**, exit `0`.
2. **USABLE** `settings.local.json` → **untouched, byte-identical and mtime-identical** before and after; exit **`0`**; advisory printed; **no sidecar written**.
3. **UNUSABLE** `settings.local.json` → exit `4`; file byte-identical afterwards; stderr names the path, the reason, and the `mv`-aside remedy; no sidecar written.
4. Per-clone, not per-project (three clones would need three files, since `__ROLE__`, `__PROJECT_ROOT__`, `__HANDOFF_DIR__` and `__CLAUDE_PROJECT_STATE__` all vary). **This restates the *nature* of the artifact; it does not authorize generating for `worker`/`overseer`.** FR-5 stands: those two exit `3` naming #1146 (§7).
5. `--check` keeps its existing behaviour in full — non-zero on divergence, exit `6` when not enrolled, wired into `validate_setup.sh` as a non-blocking stderr warning.

SPEC AC2, AC3, AC4, AC5, AC7 are unchanged.

### 5.2 TD §10 test-table amendments

All other tests (2–14, 18, 21–41) are **unchanged**.

| TD test | Change |
|---|---|
| 1 `test_check_detects_divergence_then_passes_after_generate` | **Amended**: between the two `--check` calls, the test must **move the stale live file aside** and then run generate with no `--force`. The asserted property (check fails, then passes) is unchanged. |
| 15 | **Replaced** → `test_present_usable_file_is_left_untouched_and_exits_zero`: pre-existing parseable live file whose content differs from the template → exit `0`; bytes **and** mtime unchanged; **no sidecar created**; stdout says the file already existed and was left unchanged. |
| 16 | **Replaced** → `test_present_unusable_file_is_reported_and_never_clobbered`: parametrized over zero-length, whitespace-only, invalid JSON, and a JSON array top level → exit `4` in every case; bytes unchanged; stderr contains the path, the reason, and the `mv` remedy; no sidecar. |
| 17 | **Replaced** → `test_force_flag_is_not_accepted`: `--force` → exit `2` (unrecognized argument). A named guard against reintroduction. |
| 19 | **Amended** → the written bytes must be identical between (a) a clone with no live file and (b) a clone that had a divergent live file which the test moves aside first. Same property (output independent of live-file content), expressed under never-overwrite. |
| 20 | **Re-aimed** → `test_live_file_content_never_reaches_render`: `render`'s output for the fixture values is byte-identical regardless of the live file's presence or content, and `classify_live` is only ever called after `render` has returned (assert by call-order instrumentation). |
| **new** | `test_absent_file_written_with_no_surviving_placeholders`: acceptance 1 asserted end-to-end. |
| **new** | `test_advisory_lists_only_missing_managed_entries`: live file missing two managed denies and carrying one extra allow → advisory names the two missing denies and **does not** name the extra allow; exit `0`. |
| **new** | `test_advisory_failure_does_not_change_exit_code`: monkeypatch `compare` (or `format_advisory`) to raise → exit is still `0`, and stdout contains `advisory unavailable`. |
| **new** | `test_untouched_run_leaves_existing_sidecar_byte_identical`: enrolled clone, re-run generate → sidecar bytes unchanged (in particular `META_GENERATED_AT` is not bumped). |
| 29 `test_exit_codes_are_distinct` | Unchanged as a property; update the constant name to `EXIT_UNUSABLE_EXISTING`. |

TD §10's conventions are unchanged: one file `tests/framework/test_gen_sandbox_config.py`, `importlib` module loading, `tmp_path` everywhere, `mod.main([...])` for exit codes, **no `slow`/`integration` markers**.

---

## 6. Template verification against the CURRENT tree — TD §8's anchors re-checked

I read `contract/sandbox-policy.template.json` fresh on 2026-08-15. Findings, which are **not** what one would assume:

- **The file is now 207 lines, not the 205 the TD's header cites.** PR #1405 added `"__HOME__/.nvm"` and `"__HOME__/.config/hos/claude-auth.env"` to `sandbox.filesystem.allowRead`. That is the only change since the TD was written, it is **downstream of every TD §8 anchor**, and it is correct as-is — leave it alone.
- **Consequently TD §8's cited line numbers happen to still be accurate** (deny block at 103–110; force-push at 122–125). **Do not rely on that.** Locate every anchor by **content match**, not line number — the two are only coincidentally in agreement, and any further merge from `main` breaks it.
- TD §5.4's `.gitignore` anchor (`.claude/settings.local.json` at line 40, block 39–48), TD §9.1's `validate_setup.sh` anchors (`QUIET`/`REPO_ROOT` at 14–15, parse loop 17–23, usage at 21, `fail()` 27, `ok()` 28, insertion point after line 80 and before `=== Preflight PASSED ===` at 82), and TD §9.4's `bin/hos-human:25` are all **verified accurate today**. Same instruction: match by content.

**Content anchors for TD §8 (use these):**

- **TD §8.1** sidecar denies → insert the three `hos-sandbox.values` entries immediately after the line `"Edit(./.claude/settings.local.json)",`.
- **TD §8.1** `bin` denies → insert `"Edit(__PROJECT_ROOT__/bin/**)"` and `"Edit(/__PROJECT_ROOT__/bin/**)"` immediately after the line `"Edit(./bin/**)",`.
- **TD §8.2** force-push → insert `"Bash(git push* -f*)"` and `"Bash(git push*--force*)"` immediately after the line `"Bash(sudo *)",`, leaving the existing four (`git push * --force*`, `git push * -f`, `git push -f *`, `git push* +*`) in their present order. Result: a pure two-line insertion, six spellings total, **`Bash(git push* +*)` retained** (AD-8/VF-5 — the named regression guard, test 32).
- **TD §8.3** `permissions.allow` → **no edit whatsoever** (FR-13). See §1.1 for the two things that must not sneak in here.

### 6.1 `__CLAUDE_PROJECT_STATE__` — evidence recovered, but the design does not change

TD §0.1 and AD-5 left `__CLAUDE_PROJECT_STATE__` **required-explicit** because the `~/.claude/projects/<mangled>` mangling rule was an unconfirmed Claude Code internal, and AD-5 permitted (`may`, not `must`) a derived default *if* the mangling were confirmed against a live directory.

It is now confirmed. A listing of `~/.claude/projects/` on this machine contains entries that exercise **both** halves of the transform `project_root.replace("/", "-").replace(".", "-")` — including one directory whose source path contains a `.`-prefixed segment, rendering as a doubled `-`. The superseded `sandbox_policy.py` (`765821b3`, near line 433) used exactly this transform.

**The design is unchanged: `--claude-project-state` stays required-explicit with no default.** Adding a derived default is additive scope the 2026-08-15 ruling did not ask for, the confirmation is from one machine and one Claude Code version, and the required-explicit flag plus the AD-4 echo-back already fails closed and visibly. The evidence is recorded here so that (a) the operator can *verify* the value they supply rather than guess it, and (b) a follow-on (#1146, or a successor issue) can adopt the derived default on evidence rather than reopening the question from zero. **The `coder` must not implement a default.**

---

## 7. Confirmed unchanged — do not re-derive these

Each of the following stands exactly as written in SPEC/ADR/TD-1221. Listed because a reader of the ruling could plausibly think it reopened them. It did not.

- **One file: `scripts/framework/gen_sandbox_config.py`.** Python 3.10+, stdlib only, shebang + executable bit, **no `.sh` wrapper**, no new `requirements.txt` entry (AD-2, TD §2).
- **Standalone entry point.** **Not** wired into `bootstrap/hos_install.sh`, **not** into `bootstrap/hos_setup_partner.sh` (SPEC FR-3, TD §1 "not touched"). Today's ruling does not reopen this.
- **FR-5 fail-closed roles.** `--role human` generates; `--role worker` and `--role overseer` exit `3` with a message naming **#1146**, before any filesystem access. The ruling's "three files" line describes why the artifact is per-clone; it is not authorization to generate the other two.
- **The `.claude/hos-sandbox.values` sidecar** exactly per TD §5: path, `KEY=VALUE` format, `META_*` namespace, the ten strict parse rules, "never sourced by a shell", written strictly *after* the policy file, read by `--check` only, never read by generate mode (TD §5.3). §3.3's "no sidecar on an untouched run" is a refinement of §5.1's lifecycle, not a contradiction of it.
- **`.gitignore`**: both TD §5.4 entries ship — `.claude/hos-sandbox.values` and `.claude/settings.local.json.bak-*`. The second still earns its place: the tool no longer *creates* `.bak-*` files, but it now *instructs the operator to* (§3.4).
- **The `validate_setup.sh` hook** exactly per TD §9 / AD-6: opt-in `--role`, **default-skip**, `bin/hos-worker` / `bin/hos-overseer` / `bin/hos-cron` / `hos_setup_partner.sh` **unmodified**, the four message classes, `local out rc` declared-then-assigned, never `fail()`, never reaching the script's exit code, `=== Preflight PASSED ===` and `exit 0` untouched. One line changes in `bin/hos-human` (`--role human`).
- **AD-1 purity** (as restated in §3.6), **AD-3.1/AD-3.2** (validate-before-write, `mkstemp` in the target directory + `fsync` + `os.replace`, mode `0o600`), **AD-7 provenance** (blob SHA + dirty warning printed, **never embedded** in the output JSON), **TD §6.4** determinism (`sort_keys=True`, arrays never reordered on output, `canonicalize()` comparison-only), **TD §6.5** rule-level `compare()`.
- **TD §7 fixtures** (`tests/framework/fixtures/sandbox/pre-existing-live-human.json` + its `README.md`), synthetic provenance stated in both.
- **TD §11** documentation edits (`docs/SANDBOX-POLICY.md` status + §4 items 6/7 + §5 table; PR body carrying the §8.4 delta table; `DECISIONS.md` append). Two amendments: the `SANDBOX-POLICY.md` status wording must say the policy is generated **only into a clone that does not already have one**; and the `DECISIONS.md` entry must additionally record the never-overwrite ruling and the removal of `--force`.
- **E-1** (`settings.json` generation) and **E-2** (blocking session start) remain **deferred to a human**. Nothing here pre-empts either.

---

## 8. Ordered implementation manifest

Build in this order. Each row names the section the `coder` pulls content from **verbatim** — implement TD-as-amended; do not re-derive. "TD" = TECHNICAL-DESIGN-1221 at `1cb59413`; "A" = this addendum.

| # | Path | Action | Pull content from | Notes |
|---|---|---|---|---|
| 1 | `docs/v0.6.0/SPEC-1221-…md`, `ADR-1221-…md`, `TECHNICAL-DESIGN-1221-…md` | **add, unmodified** | `git show 1cb59413:<path>` | §1. Land the reviewed record first, in its own commit. Do not edit them. |
| 2 | `docs/v0.6.0/ADDENDUM-1221-…md` | already written | — | This file. Commit alongside #1. |
| 3 | `contract/sandbox-policy.template.json` | **edit** | TD §8.1, §8.2, §8.3 | Anchors by **content match** per A §6. Five deny insertions total (3 sidecar + 2 `bin`) plus 2 force-push. `permissions.allow` **untouched**. Nothing removed. Excluded scope: A §1.1. |
| 4 | `.gitignore` | **edit** | TD §5.4 | Both entries, appended to the existing "Claude Code machine-local settings" block. |
| 5 | `scripts/framework/gen_sandbox_config.py` | **new** | TD §2–§6, **as amended by A §3, §4** | See the sub-order below. |
| 6 | `tests/framework/fixtures/sandbox/pre-existing-live-human.json` | **new** | TD §7.2 | Synthetic. Fixture values table in TD §7.2. No operator path anywhere. |
| 7 | `tests/framework/fixtures/sandbox/README.md` | **new** | TD §7.3 | Provenance statement — required, not optional. |
| 8 | `tests/framework/test_gen_sandbox_config.py` | **new** | TD §10, **as amended by A §5.2** | 41 amended tests + 4 new. No `slow`/`integration` markers. |
| 9 | `bootstrap/validate_setup.sh` | **edit** | TD §9.1, §9.2, §9.3 | Opt-in `--role`, default-skip. The `local out rc` hazard in §9.2 is the single most likely bug — declare first, assign second. |
| 10 | `bin/hos-human` | **edit** | TD §9.4 | One argument (`--role human`) appended to the existing `validate_setup.sh` call, plus a one-line comment. |
| 11 | `docs/SANDBOX-POLICY.md` | **edit** | TD §11.1, amended by A §7 | Status wording must say generation happens **only into a clone that has no existing policy file**. |
| 12 | `DECISIONS.md` | **append** | TD §11.3, amended by A §7 | One dated entry at the bottom (append-only). Must record: the seven exit codes; the sidecar as `--check`'s reproducibility mechanism; generate not reading the sidecar; **and** the 2026-08-15 never-overwrite ruling + `--force` removal. |
| 13 | PR body | — | TD §8.4, §9.5, §11.2 | The delta table (computed by test 10, showing **six** force-push denies), the rollback line, the synthetic-fixture statement. The AC1b live-clone transcript is operator-supplied. |

**Sub-order within item 5** (`gen_sandbox_config.py`), so the invariants land before the code that could violate them:

1. Module docstring — TD §2.2, with A §4.2's exit table verbatim and the never-overwrite sentence. No `--force` in either usage form.
2. Reconciliation comment block — TD §2.3 (three `bin` spellings, six force-push spellings, three sidecar spellings, and why each redundancy is deliberate).
3. Constants — TD §2.4. `PLACEHOLDERS` is the single source of truth. Exit-code constants per A §4.2 (`EXIT_UNUSABLE_EXISTING`, not `EXIT_REFUSE_OVERWRITE`).
4. Exceptions — TD §2.5.
5. `build_parser` — TD §6 row 1 + A §4.3. **No `--force`.**
6. `gate_role`, `validate_clone_dir`, `normalize_path`, `resolve_values` — TD §6 rows 2–5, §3.1–§3.3.
7. `load_template`, `substitute`, `find_surviving_placeholders`, `render` — TD §6 rows 6–9. `render` takes **no path parameter**.
8. `canonicalize`, `compare`, `format_divergences` — TD §6 rows 10–12, §6.4, §6.5.
9. `read_values_file`, `write_values_file`, `write_atomic` — TD §6 rows 13–15, §5.2, §6.7.
10. `classify_live`, `format_advisory` — **A §3.1, §3.3** (new).
11. `template_provenance`, `echo_values`, `regenerate_command` — TD §6 rows 17–19; `regenerate_command` drops its `force` parameter.
12. `run_generate` — **A §3.5** (replaces TD §6.6's `run_generate`).
13. `run_check` — TD §6.6, unchanged.
14. `main` — TD §6.6 steps 1–11 unchanged, plus TD §4's top-level `except Exception → 5`. The one narrow carve-out is A §3.3's advisory guard.

---

## 9. Startup-gap analysis, routing, and sign-offs

**Was this a startup-artifact gap?** Two parts, different answers.

- **The never-overwrite decision itself is not a gap.** FR-7 *was* settled in the initial design; a human has now reversed the product decision. That is a requirements change, correctly routed and correctly authored by the human.
- **The USABLE-vs-UNUSABLE distinction IS a gap, and it should have been settled before any code was written.** The original design had a single "exists → refuse" path that conflated "legitimately hand-customized" with "corrupt/empty", so it could not have produced the right behaviour for #1389 under any flag setting. **Open or annotate a `startup-artifact-gap` issue** recording this, cross-referenced to #1221 and #1389.

**Affected-sign-offs analysis.** **No sign-off is orphaned and none requires re-review.** No implementation code for #1221 exists on `main`; the two older commits (`765821b3`, `671a0308`) are on an abandoned branch, superseded before this SPEC/ADR/TD existed, and are not being carried forward. The SPEC and ADR were authored by `pm-agent` and `architect` respectively and are amended here on explicit human authority, not silently. No reviewer has approved code against the old contract, so there is nothing to re-audit.

**Routing.**
- → **`architect`**: notification, non-blocking. Two items: (1) the §3.6 restatement of the AD-1 wording adopted in ADR §6.3, with the §3.6 fallback if rejected; (2) AD-3.3 and §4 N1 are superseded by human ruling, and exit code `4` is repurposed. No architecture decision is being made here without you — say so if you read either differently.
- → **`pm-agent`**: informational. SPEC FR-7/AC6 superseded and AC1 amended by the 2026-08-15 ruling; §5.1 is the replacement acceptance list.
- → **human**: nothing outstanding. E-1 and E-2 remain where pm-agent left them.

---

## Human Review Required

**RISK: MEDIUM** — unchanged from SPEC/ADR/TD-1221. The artifact is a security boundary. This ruling moves risk in the **safe** direction on the write path (the tool can no longer modify an existing policy at all) and introduces exactly one new failure mode: an operator on a clone with a pre-existing usable file may believe they are enrolled when they are not. That is closed by §3.3's mandatory "already existed, nothing was written" wording, by not writing a sidecar (so `--check` truthfully reports exit `6`, not enrolled), and by the `validate_setup.sh` hook's distinct not-enrolled message (TD §9.2, unchanged).

**CONFIDENCE: HIGH** on everything read fresh against this working tree: `contract/sandbox-policy.template.json` in full (207 lines), `bootstrap/validate_setup.sh` in full, `bin/hos-human`, `.gitignore`, `bootstrap/hos_install.sh:1814-1815`, `docs/v0.6.0/` naming conventions, and all three design documents at `1cb59413` in full, plus the superseded `765821b3` / `671a0308` for exclusion scope. **MEDIUM** on the §3.6 AD-1 restatement, which is a wording change to a formulation the architect adopted and is therefore routed to `architect` with a concrete fallback rather than asserted.

**BLAST RADIUS:** unchanged — the Human clone's live sandbox config, one new stderr path at Human session start, a reconciled tracked template. No consumer project, no autonomous role, no cron path. Rollback is unchanged (revert `--role human` on `bin/hos-human`), and is now strictly cheaper because no clone's existing policy file can have been modified by this tool.

**Change classification: STRUCTURAL.** It reverses a decided requirement (FR-7), removes a CLI flag, repurposes an exit code, and inverts the exit status of the present-file case. Per CORE, a structural design change is escalated to a human before writing — **that escalation is the origin of this document**: the 2026-08-15 human ruling on #1221 is the authorization, not a post-hoc justification. Nothing in this addendum extends beyond that ruling except the `--force` removal (§4.1, reasoned and stated as required) and the derived consequences in §3.3 (no sidecar on an untouched run) and §4.2 (exit-code table), each flagged as derived at the point of use.
