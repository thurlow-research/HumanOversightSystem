# TECHNICAL DESIGN — #1643 slices W1–W5: the invocation primitive, the result document, observability, the migrations, and the registry

**Status:** **DRAFT — iteration 1 of 5 (CORE cap). REQUESTING ARCHITECT REVIEW.**
Three findings contradict or cannot implement the ADR as written and are raised rather than resolved:
**TD-F1** (AD-4's `subagent_stats.refused` row is unimplementable against the shipped envelope shape),
**TD-F2** (AD-4's "any envelope field the classifier does not recognise" clause makes every CLI version
bump a merge stopper), **TD-F3** (REQ-A4's pre-invocation auth check cannot be performed — auth is not
observable before launch when it comes from the keychain). Each is an **ESC** in §12. Everything else
below is designed to be implementable without further design questions.

> **AMENDED 2026-09-16 — Amendment A (interpreter fitness). Binding on W1.** PR #1720 was bounced with a
> red `tests` check: `bootstrap/invoke_agent.sh` ended in a bare-PATH `exec python3 …`, and
> `agent_invoke_cli.py` imports `yaml` at module scope, so every wrapper test that shells out died with
> `ModuleNotFoundError: No module named 'yaml'` under CI's `setup-python` 3.12 (PyYAML is declared only in
> `scripts/oversight/requirements.txt` and lives only in `scripts/oversight/.venv`). The same bare
> `python3` breaks this canonical entry point on **any** host whose system interpreter lacks PyYAML —
> including a consumer project after `bootstrap/hos_install.sh`, which ships `scripts/oversight/` but
> deliberately builds **no** venv. **This design said the wrong thing**: §3.9 step 2 required the
> *presence* of an interpreter, never its *fitness* to run L2. The ruling is **TD-D22** (§3.9, L3 resolves
> the interpreter) + **TD-D23** (§3.4 P0, L2 fails closed on its own missing runtime dependency), with
> §3.3, §8, §9.1 and §13 amended to match. A coder implementing §3.9 without Amendment A will reproduce
> the defect.

> **AMENDED 2026-09-18 — Amendment B (the `token_tracker` call rule). Binding on W3.** §5.1 named exactly
> one case in which `token_tracker.py record` is not called (`--not-applicable`, "nothing was spent") and
> said nothing about the four preflight-failure outcomes — `agent_unavailable`, `posture_invalid`,
> `not_authenticated` (P7), `cli_unavailable` — which also launch no process. The coder read the silence
> as a deliberate single exemption and recorded a char-estimate entry for all four; `code-reviewer` read
> it as an omission. **This design said too little**: one named exemption plus four outcome classes left
> to inference is not a contract. The ruling is **TD-D24** (§5.1): *`token_tracker` is called if and only if
> the `claude` subprocess was launched*, with an exhaustive per-outcome-class table, so no outcome is
> decided by inference again. The four preflight failures therefore do **not** record — a fallback entry
> there is proportional to the real input file (`_emit_preflight_document` reads and hashes it), so it is
> a phantom non-zero spend flagged `"estimated": true`, not a harmless zero. §9.3 (T3.8 amended, T3.10
> added) and §13 are amended to match. Post-launch failures — `timeout`, `unparseable`, `crash`, and
> `not_authenticated` reached via the §3.7 classifier — are **unchanged** and still record. **One
> consequential correction rides along:** §3.7's enumeration of the pre-flight details said "three" over
> a list of four — the exact set TD-D24 keys on — and is corrected to "four" under this amendment rather
> than a new one.

> **AMENDED 2026-10-02 — Amendment C (W5 schema-parametric loader, ADR-1644 SEAM-1). Binding on W5 once
> the architect approves; W5 is unbuilt.** ADR-1644 SEAM-1 requires W5's loader to be one loader and one
> ownership model for every registry kind. Each document says which kind it is through its `schema:`
> field. §7 assumed a dimensions-only loader. Amendment C (end of document) adds the dispatch seam and
> the extension point T3.1 uses (§C.2.4, §C.2.9). It also corrects seven §7 claims that the current tree
> contradicts (TD-VF-15…TD-VF-21) and re-confirms two that still hold (TD-VF-13, TD-VF-14). §7.3, §7.4,
> §7.7 and §7.9 carry pointer notes.

> **AMENDED 2026-10-02 — Amendment D (W5b: registry data, prompt-file contract, T5.28). Binding on W5b; architect-approved with edits, round 1 (§D.10). Where it and §4.1/§7/§9.5 or Amendment C disagree, Amendment D governs.**

**Date:** 2026-09-14 (original), amended 2026-09-16 (Amendment A), 2026-09-18 (Amendment B), 2026-10-02 (Amendment C)
**Iteration:** 1 of 5
**Author:** technical-design
**Binding inputs:** `docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md` (AD-1…AD-16 BINDING);
`docs/v0.7.0/REQUIREMENTS-1643-1644-deterministic-agent-invocation.md` (REQ-A/REQ-B, VF-1…VF-12); the
human's Q1–Q8 rulings and the ESC-5 ruling, both quoted in full inside the ADR.
**Scope:** ADR §5 build slices **W1, W2, W3, W4, W5** only.
**Out of scope, not designed here:** W6 (measurement), W7 (the sweep — blocked on ESC-2), W8 (REQ-B6 /
AD-15 — blocked on ESC-4), W9–W13, and all of #1644 / REQ-C / Track 3. §1.2 names the seam to each.
**Probe obligation discharged:** ADR §0 ("Verification gaps I could not close") required this document to
probe `--settings` survival and `--agent` frontmatter enforcement before binding AD-7. Both were probed
live against the installed CLI. **Verbatim results in §0.2.** AD-7's mechanism is **viable**, with one
new fail-open the probe found and this design closes (§0.2.6).

> This document specifies **contracts, not code**. Every "must" is a requirement on the implementation.
> Where the ADR is explicit I restate it in implementable terms and add nothing. Where the ADR left a
> choice to `technical-design` the choice is made here and labelled **TD-D\<n\>** with its reason. Where
> I found something that contradicts the ADR or the requirements it is **TD-F\<n\>** and is escalated
> in §12, not silently resolved.

---

## 0. Verification findings — what I checked in the tree, and what I probed

Citations are this worktree at branch `worker-1643-technical-design-invocation-primitive-…`, whose
content for every file cited matches `origin/main` at `627773b2`.

### 0.1 Re-verification of the ADR's structural claims (not assumed — re-derived)

**TD-VF-1 — VF-2/AF-1's four `claude -p` sites: CONFIRMED, exactly four, none uses `--agent`.**
A fresh recursive grep of `scripts/`, `bootstrap/`, `bin/` for `claude -p` / `claude --print` returns:

| File:line | Shape |
|---|---|
| `scripts/run_panel.sh:146` | `claude -p --model haiku  "$prompt" 2>>"$RUN_DIR/errors.log"` |
| `scripts/run_panel.sh:147` | `claude -p --model sonnet "$prompt" 2>>"$RUN_DIR/errors.log"` |
| `scripts/framework/validate_scripts.sh:182` | `printf '%s' "$prompt" \| run_capped "$AI_REVIEW_TIMEOUT" "$out" claude -p --model "$MODEL"` |
| `scripts/framework/validate_self.sh:236` | `result=$(printf '%s' "$prompt" \| claude -p --model "$MODEL" --exclude-dynamic-system-prompt-sections --no-session-persistence 2>/dev/null)` |
| `bootstrap/setup_clis.sh:148` | `claude -p "Reply with exactly: OK"` (smoke test — AD-16 EXEMPT) |

**Two corrections to AD-16 that change W4's size** (§6, TD-F4):
1. `run_panel.sh` is **two seats**, not one — `haiku` and `sonnet` are separate panel members in the same
   `case`. AD-16's "the panel's Claude seat" (singular) understates the work by a factor of two, and each
   promoted seat is a **new `.claude/agents/*.md` file**, i.e. a protected-surface, human-gated addition.
2. `run_panel.sh` passes the prompt as **argv**, so migrating it also changes its `ARG_MAX` posture, and
   its output is consumed by `panel_logic.extract-json`'s prose-tolerant reader — so migrating it changes
   the **panel's input contract**, a cross-vendor decorrelation surface (ADR non-goal 3).
   AD-16 explicitly permits this document to say the promotion is too large for W4 and split it.
   **It does, and it is split as W4b** (§6.4).

**TD-VF-2 — VF-3/AF-3's timeout helpers: CONFIRMED, and AD-5.3's migration story does not fit one of
the two files.**
- `scripts/oversight/run_with_retry.sh:56-63` — `with_timeout` is exactly
  `"$_TIMEOUT_BIN" "$timeout_sec" "$@"`, no `--kill-after`, no `--foreground`, no process-group kill, and
  `TIMEOUT_SEC=0` **disables the timeout entirely** (a fail-open the header documents as intentional).
  Line `:52` sources `lib/audit_log.sh` at file scope, so `with_timeout` cannot be taken without the audit
  dependency. **AF-3 confirmed in full.**
- `scripts/framework/validate_scripts.sh:96-101` — private `_TIMEOUT_BIN` + `run_capped`. Its three call
  sites are `:182` (**claude**), `:183` (agy), `:184` (codex).
- `scripts/framework/validate_agents.sh:151-160` — private `_TIMEOUT_BIN` + `run_capped`. Its two call
  sites are `:301` (agy) and `:381` (codex). **It has no `claude` call site at all.**
  So AD-5.3's "when `validate_agents.sh` and `validate_scripts.sh` migrate (AD-16)" does not describe
  `validate_agents.sh`: AD-16 gives it nothing to migrate. Its `run_capped` deletion is a **pure refactor
  with no migration driver**, and it is not free — `run_capped` redirects stdout to a file and discards
  stderr, which `with_timeout` does not do, so each of the four agy/codex call sites needs its own
  redirection added. §6.3 designs it; §12 ESC-D asks whether it belongs in W4 at all.
- A **third** `_TIMEOUT_BIN` exists at `bin/hos-cron:1754-1756`. It is the cron wall-clock cap, not an
  AI-review cap, and is **out of scope** — naming it so nobody "consolidates" it.

**TD-VF-3 — AF-7's two-reader claim: CONFIRMED, and sharper. The two readers disagree about the
per-finding file key, and a conforming document must satisfy both.**
- `validation_logic.py` reads only: block-level `verdict` (read in `compute_verdict`), `findings[]` and `attacks[]`
  (iterated together in `compute_verdict`), per-finding `severity`, `files` **or** singular `file`
  (`_files_of`), and `category` **or** `type` (`_class_of_finding`). `compute_verdict` takes
  `(findings: list[dict], ledger_path: str, *, strict_empty: bool)`. A block whose `verdict` is `"error"`
  adds **+1 `blocking_count` and +1 `new_blocking_count`, never dedup-silenced** (the `ERROR_VERDICT`
  branch of `compute_verdict`) — this is
  the #670 path AD-4's `invocation_failed ⟹ verdict:"error"` rule rides on, verified at source.
- `panel_logic.py` reads `reviewer` and `lens` (`count_corroboration:194-220`), and in its fallback path
  reads singular **`file`** and **`line`** (`reconcile_membership:222-258`). It counts **distinct
  `reviewer` values as distinct vendors.**
- **Consequence:** a conforming per-finding object must carry **both** `files: [...]` (for
  `validation_logic.fingerprint`) **and** `file` + `line` (for `panel_logic.reconcile_membership`), and
  `reviewer` must be the **vendor** (`"claude"`), not the lens — or twelve same-vendor dimensions would
  read to `panel_logic` as twelve corroborating vendors. §4.2 binds both.

**TD-VF-4 — `load_ledger` cannot be avoided by not calling it: `compute_verdict` calls it
unconditionally.** `compute_verdict` opens with `seen = load_ledger(ledger_path)`, with no branch. AD-6's
"`fingerprint()` is reused; `load_ledger()` is not" therefore cannot be honoured by the callee; it must be
honoured by **what the caller passes**. `load_ledger` tolerates a missing file (its
`except FileNotFoundError`) and a zero-line file. §4.4 binds `os.devnull` as the mandatory argument and
§9 adds a source-level test that the primitive never imports `load_ledger`.

**TD-VF-5 — AF-9 CONFIRMED and sharpened: the installer has exactly two file dispositions and no data
merge of any kind.**
- `hos_install.sh:591` `cp_file` — copy **only if absent** (consumer-owned; `--force` overrides).
- `hos_install.sh:615` `cp_framework_file` — **always overwrite** (HOS-owned). Its own comment:
  *"Consumer PROJECT files (step-manifest.yaml, config.sh) must NEVER use this helper."*
- The only merge machinery in the installer is the **agent-region** merge: `hos_install.sh:1489-1519`
  iterates `_resolved_packs`, looks for `packs/<pack>/<agent>.md`, and calls
  `python3 regions.py inject-pack` on a staged **agent markdown template**. It is keyed on
  `<agent>.md` and reaches nothing else. **There is no pack→data, pack→gate, or pack→config path.**
- `contract/` is installed by its own hand-written section (`:2105-2122`): `OVERSIGHT-CONTRACT.md` via
  `cp_framework_file`; `step-manifest.yaml` via an `if [[ ! -f ]]` guard + `cp_file`.
- `scripts/framework/framework_consumer_files.txt` drives **both** the copy loop (`:1906-1917`, using
  `cp_framework_file`) **and** `.hos-manifest` enumeration (`:2206-2225`). Adding a path there gets
  overwrite-on-upgrade *and* manifest tracking with **zero new installer code**.
- `.hos-manifest` (`:2191-2229`) detects framework files present in the prior manifest and absent now, and
  `--prune` **archives** them. Prune is opt-in, so detection alone leaves a stale file on disk.
  **This is the mechanism that partially covers, and the reason the loader must fully cover, the
  "project dropped `--pack django` but `pack-django.yaml` is still on disk" case** (§7.4 rule L20).

**TD-VF-6 — `scripts/automation/**` is not in the consumer ship-set.** `grep automation
framework_consumer_files.txt` returns nothing. So `agent_invoke_cli.py`, `dimension_registry.py` and
`dimension_registry_cli.py` **do not reach a consumer install** as designed. This is the same gap
`TECHNICAL-DESIGN-1357` recorded as TD-VF-3 for `merge_authority_cli.py`, and the same answer applies:
the HOS repo is the only consumer of this surface in v0.7.0. Recorded, routed to W7's ship-set decision
(§12 ESC-E), **not** worked around by relocating the modules against AD-9's binding.

**TD-VF-7 — AF-6 CONFIRMED verbatim, plus two routing gaps AF-6 does not name.** Read in full at
`scripts/framework/run_post_change_sweep.sh`: `categorize():63-115` is 8 regex domains; `:159-201` prints
the plan as prose; `:172` routes `framework-validator`; `:181-184` is the discretionary privacy `||`
branch; `:200-201` hands execution to an agent. All as AF-6 states. **Additionally:**
1. **`reliability-reviewer` and `ops-reviewer` are never routed by this script, at all.** They appear in
   no branch. So two of the eight lenses have no predicate to migrate, and AD-11's migration table has no
   row for them. §7.6 (TD-D12) supplies predicates and marks them as mine.
2. Tracks 3/4/5 route `unit-test`, `ux-designer` → `ui-reviewer`, and `pm-agent`. These are **build-side
   roles**, not gating review dimensions (AD-10's `kind: judgment` entries). §7.6 (TD-D13) excludes them
   from the registry and states where they go.

**TD-VF-8 — `token_tracker.py`'s log path is relative and lives under `.claudetmp/`.**
`token_tracker.py:42` is `USAGE_LOG = Path(".claudetmp/oversight/token-usage.jsonl")` — cwd-relative, and
under the directory VF-5 established is gitignored and ephemeral. Its `record()` also **prints to
stdout** (`:113-118`). Both facts constrain AD-8's wiring: L2 must invoke it as a **subprocess with an
explicit `cwd=repo_root` and its stdout captured**, never in-process, or the record lands in the wrong
place and its chatter corrupts L2's single-JSON-object stdout contract. §5.1.

**TD-VF-9 — the canonical per-entry audit writer is importable and takes an explicit root.**
`scripts/oversight/lib/audit_log.py:126` is `write_event(event: dict, *, root: str = ".", ts: str |
None = None) -> str`; write-once, idempotent on identical bytes, hard error on a hash collision with
different bytes. Filename timestamp precedence is `explicit ts > event["timestamp"] > now()`
(`_resolve_ts:99`). §5.2 uses it with an explicit `timestamp` (AF-10 notes the existing
`subagent-model-resolved` records omit one; the new record will not repeat that).

**TD-VF-10 — PyYAML is declared and available, and the repo's existing import idiom is tolerant.**
`scripts/oversight/requirements.txt` declares `PyYAML>=6.0` with a note that the gate *"must not depend on
that luck"*; `python3 -c "import yaml"` succeeds (6.0.1). But `scripts/automation/lib/config_resolver.py:27-29`
uses `try: import yaml / except ImportError: yaml = None`. **The registry loader must not copy that
idiom** — AD-9 binds a fail-closed loader, so an unavailable `yaml` is a hard load error (§7.4 rule L2).

**TD-VF-11 — the #1446 usage-limit breaker is commented out.** `bin/hos-cron:2005-2060` — the block is
disabled, deliberately and with a recorded reason. Its grep, when live, is
`grep -qiE 'usage limit reached|hit your (session|weekly|opus) limit' "$_CLAUDE_OUTPUT_CAPTURE"` over the
**parent model session's tee'd stdout** (`:1770`). AD-8 assigns "surfacing a nested usage-limit stop
toward #1446" to W3; **W3 can only build the surfacing half**, because the consumer is disabled. §5.3
builds the surfacing and §12 ESC-F routes the wiring.

**TD-VF-12 — `contract/**` is protected surface; `scripts/automation/**` is not.**
`scripts/framework/protected_surfaces.txt` lists (in order) `.claude/agents/**`, `contract/**`,
`AGENTS.md`, `CLAUDE.md`, …, `bin/**`, `bootstrap/**`, `scripts/framework/**`,
`scripts/oversight/gates/**`, `scripts/oversight/run_validators.sh`,
`scripts/oversight/validators/schema.py`, `.github/CODEOWNERS`, `.github/workflows/**`, … — and **not**
`scripts/automation/**`. AF-11's premise holds: a posture file under `contract/` is human-gated for free.
**The corollary is load-bearing and AD-7 does not state it: any part of the posture that lives in
`scripts/automation/` is *not* human-gated.** §3.6 therefore keeps the entire posture — settings *and*
tool lists — under `contract/`, and §12 ESC-G routes the question of adding `scripts/automation/**` to
the protected list (I may not change that list; it is itself a protected surface and an architecture/
human decision).

### 0.2 The AD-7 probe — run live, reported verbatim

**Environment.** `claude` = `$HOME/.local/bin/claude`, **version `2.1.270 (Claude Code)`**. Probes
ran from a throwaway nested workspace `/tmp/claude/probe1643/nested/` containing its own
`.claude/settings.json` (5 `permissions.allow` entries) and `.claude/agents/probe-agent.md`
(`tools: [Read, Grep]`, `model: sonnet`, body: *"Reply with exactly: PROBE-OK"*). Nothing produced by the
probes is committed. `env | grep -c CLAUDE_CODE_OAUTH_TOKEN` → `0`: **no OAuth env token was present, and
the probes still authenticated** (keychain). That single fact is TD-F3 (§12 ESC-C).

Each probe's full command is given; outputs are the real bytes, trimmed only where marked `…`, with the operator's home directory rendered portably (`$HOME` / `~`) so the design reads the same on any machine.

---

**Probe A — baseline, reproduces VF-1.2's discard and gives the shipped envelope shape.**

```
timeout 90 env -C /tmp/claude/probe1643/nested claude --print --output-format json \
  'Reply with exactly: PROBE-OK' 2>&1; echo "RC=$?"
```
stderr:
```
Ignoring 5 permissions.allow entries from .claude/settings.json: this workspace has not been trusted.
Run Claude Code interactively here once and accept the trust dialog, or set
projects["/tmp/claude/probe1643/nested"].hasTrustDialogAccepted: true in ~/.claude.json.
```
stdout (one line, `RC=0`), field-complete:
```json
{"duration_api_ms":2009,"stop_reason":"end_turn","session_id":"5063fa1e-…","total_cost_usd":0.125521,
 "usage":{"input_tokens":2,"cache_creation_input_tokens":11956,"cache_read_input_tokens":9542,
 "output_tokens":9,"output_tokens_details":{"thinking_tokens":0},"server_tool_use":{…},
 "service_tier":"standard","cache_creation":{…},"inference_geo":"not_available","iterations":[…],
 "speed":"standard"},
 "modelUsage":{"claude-haiku-4-5-20251001":{…,"costUSD":0.000955,…},
               "claude-opus-5":{…,"costUSD":0.124566,…}},
 "permission_denials":[],"terminal_reason":"completed","fast_mode_state":"off",
 "fast_mode_disabled_reason":"sdk_opt_in_required",
 "subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},
   "started_in_background":0,"max_depth":0,"spawned_by_subagents":0,"completed":0,"failed":0,
   "killed":{"parent":0,"user":0,"system":0},
   "refused":{"depth_limit":0,"concurrency_limit":0,"budget":0},"by_type":{}},
 "is_error":false,"num_turns":1,"subtype":"success","api_error_status":null,"result":"PROBE-OK",
 "ttft_ms":1281,"type":"result","duration_ms":1303,"uuid":"d7ee8986-…","ttft_stream_ms":718,
 "time_to_request_ms":53,"first_content_frame_ms":718,"queued_turn_count":0,"result_index":0}
```
Findings: (i) the trust warning is on **stderr**; stdout is clean, parseable JSON — so L2 must capture the
two streams **separately**, never `2>&1`. (ii) `terminal_reason` on a good run is **`"completed"`**.
(iii) **`subagent_stats.refused` is present and is an OBJECT, not an integer** → **TD-F1**.
(iv) `modelUsage` carries **two** models (a helper `claude-haiku-4-5` plus the real one), so "the model"
cannot be read as the sole key. (v) `total_cost_usd` is present.

---

**Probe B — does `--settings` get named in the discard warning?**

```
timeout 90 env -C /tmp/claude/probe1643/nested claude --print --output-format json \
  --settings /tmp/claude/probe1643/posture-review-read-only.json 'Reply with exactly: PROBE-OK' \
  2>/tmp/claude/probe1643/B.err >/tmp/claude/probe1643/B.out
```
`RC=0`; stderr is **byte-identical to probe A's** — still `Ignoring 5 … from .claude/settings.json`, with
no mention of the 3 `allow` entries in the `--settings` file. Suggestive but not proof; C/K/L settle it.

---

**Probe C — is `--settings`' `deny` honoured in the untrusted nested workspace? YES.**
Posture: `{"permissions":{"defaultMode":"auto","disableBypassPermissionsMode":"disable",
"allow":["Read","Grep","Glob"],"deny":["Bash","Write","Edit","WebFetch"]}}`
```
timeout 120 env -C /tmp/claude/probe1643/nested claude --print --output-format json \
  --permission-prompts none --settings /tmp/claude/probe1643/posture-deny-bash.json \
  'Run the shell command: echo PROBE-C-RAN . Then reply with exactly what it printed, or say DENIED …'
```
`RC=0`; envelope fields:
```
is_error = false      subtype = "success"     terminal_reason = "completed"    num_turns = 2
permission_denials = []
refused = {"depth_limit": 0, "concurrency_limit": 0, "budget": 0}
result = "DENIED\n\nNo Bash/shell tool is available in this session — I searched the deferred tool list
          and only `TaskOutput`/`TaskStop` came back, with no `Bash` tool to load — so I couldn't
          execute `echo PROBE-C-RAN`."
```
The `deny` list from the `--settings` file **removed the Bash tool entirely**. Note `permission_denials`
is `[]` here: a tool removed up front produces **no denial event**. That is a second reason `rc`+`is_error`
+`permission_denials` are jointly insufficient, and it is why §4.2 records the posture in the document.

---

**Probes K and L — the decisive pair. `--settings`' `allow` IS honoured in the untrusted nested
workspace.** Identical in every respect except the posture's `allow` list, and using a target *inside*
the workspace (probe J, below, shows why that matters).

K, `allow: []`:
```
timeout 120 env -C /tmp/claude/probe1643/nested claude --print --output-format json \
  --permission-mode manual --permission-prompts none \
  --settings /tmp/claude/probe1643/posture-no-allow.json \
  'Run the shell command: touch canary-K.txt . Then reply with exactly DONE, or DENIED …'
```
```
result = "DENIED"
denials = [{"tool_name":"Bash","tool_use_id":"toolu_01JYMB…",
            "tool_input":{"command":"touch canary-K.txt","description":"Create empty file canary-K.txt"}}]
ls: cannot access '/tmp/claude/probe1643/nested/canary-K.txt': No such file or directory
```
L, `allow: ["Bash(touch *)"]`:
```
timeout 120 env -C /tmp/claude/probe1643/nested claude --print --output-format json \
  --permission-mode manual --permission-prompts none \
  --settings /tmp/claude/probe1643/posture-allow-touch-glob.json \
  'Run the shell command: touch canary-L.txt . Then reply with exactly DONE, or DENIED …'
```
```
result = "DONE"
denials = []
-rw-rw-r-- 1 scott scott 0 Sep 14 21:49 /tmp/claude/probe1643/nested/canary-L.txt
```

> **ANSWER TO THE ADR'S FIRST OPEN QUESTION: `--settings <file>` SURVIVES the untrusted-workspace
> discard.** The project's `.claude/settings.json` `permissions.allow` is discarded (the warning names it
> and counts its 5 entries); the `--settings` file's `allow` and `deny` both apply. **AD-7's mechanism is
> viable and needs no replacement.** Q3's interim rule is satisfiable exactly as AD-7 reads.

Probe K also records a **live reproduction of the class AD-4's `permission_denials` row exists for**: a
denied tool call returned `rc=0`, `is_error:false`, `subtype:"success"`, `terminal_reason:"completed"` —
every one of the other signals says "clean" — and only `permission_denials` says otherwise.

---

**Probe M — does `--agent` enforce the agent file's frontmatter `tools:` in the untrusted nested
workspace? YES.** Same posture as probe L (which permitted `touch`), plus `--agent probe-agent` whose
frontmatter is `tools: [Read, Grep]`:
```
timeout 120 env -C /tmp/claude/probe1643/nested claude --print --output-format json \
  --agent probe-agent --permission-mode manual --permission-prompts none \
  --settings /tmp/claude/probe1643/posture-allow-touch-glob.json \
  'Run the shell command: touch canary-M.txt . Then reply with exactly DONE, or DENIED …'
```
```
result = "DENIED"      denials = []      num_turns = 1
ls: cannot access '/tmp/claude/probe1643/nested/canary-M.txt': No such file or directory
```
`num_turns: 1` and an empty `permission_denials` mean the Bash tool was **never offered**, exactly as in
probe C. The frontmatter list is enforced, and it **narrows** a posture that would otherwise have allowed
the call.

**Probe O — confirms the agent file is genuinely loaded, body and frontmatter both.** Same invocation,
prompt `'Who are you? Follow your instructions exactly.'`:
```
result = "PROBE-OK"
modelUsage keys = ['claude-haiku-4-5-20251001', 'claude-sonnet-5']
```
The agent's body governed the answer, and its `model: sonnet` frontmatter governed the model (probe A,
with no `--agent`, used `claude-opus-5`). **AD-3's "the agent file's own `model:` frontmatter governs" is
confirmed behaviourally.**

> **ANSWER TO THE ADR'S SECOND OPEN QUESTION: `--agent <name>` DOES enforce the agent file's frontmatter
> `tools:` list in a nested, untrusted workspace, and the agent's body and `model:` are in effect.**
> AD-7's "defence in depth, not a substitute" second layer is real.

---

**Probe N — an unknown agent name fails closed, with no fallback.**
```
timeout 90 env -C … claude --print --output-format json --agent no-such-agent-xyz 'Reply with exactly: PROBE-N'
```
`RC=1`; **stdout empty**; stderr:
```
--agent 'no-such-agent-xyz' not found. Available agents: claude, Explore, general-purpose, Plan,
probe-agent, statusline-setup
```
Two consequences. (i) The CLI does not silently substitute — good. (ii) **`general-purpose` and `Plan`
are real, invocable built-in agent names**, so a caller *could* name one and get a non-shipped,
non-region-layered, non-CODEOWNERS-protected reviewer. AD-3's "resolve `.claude/agents/<name>.md` and
verify it exists" is therefore not belt-and-braces; it is the only thing standing between this surface and
the #608 specialist-substitution violation. (iii) The failure is `rc=1` + **empty stdout**, which is
indistinguishable from a crash — so `agent_unavailable` must come from L2's own pre-flight, as AD-3 says,
not from parsing stderr.

---

**Probe R — a live reproduction of VF-1.3's exact shape on this CLI version.** Forced with an invalid
model:
```
timeout 90 env -C … claude --print --output-format json --model no-such-model-xyz 'Reply with exactly: PROBE-R'
```
`RC=1`, and **stdout is still a complete envelope**:
```json
{…,"permission_denials":[],"terminal_reason":"api_error",…,"is_error":true,"num_turns":1,
 "subtype":"success","api_error_status":404,
 "result":"There's an issue with the selected model (no-such-model-xyz). It may not exist or you may not
           have access to it. Run --model to pick a different model.",…}
```
stderr also carried `[claude-code:unrecognized_model] {"model":"no-such-model-xyz","query_source":"sdk"}`.
**`subtype:"success"` alongside `is_error:true` is reproduced verbatim on 2.1.270.** This envelope is
test fixture **F-VF1** in §9.1. It also drives **TD-D6**: because a non-zero rc can carry a *more precise*
envelope reason, the `outcome_detail` precedence puts envelope inspection ahead of the bare rc.

---

**Probe P — NEW FAIL-OPEN, not in the ADR: a malformed `--settings` file is SILENTLY IGNORED.**
Posture file truncated to invalid JSON (`…"deny":["Bash","Write","Edit"` — no closing brackets), otherwise
the same deny-Bash posture as probe C:
```
timeout 90 env -C … claude --print --output-format json --permission-mode manual \
  --permission-prompts none --settings /tmp/claude/probe1643/posture-malformed.json \
  'Run the shell command: echo PROBE-P-RAN …'
```
```
RC=0     result = "PROBE-P-RAN"     denials = []
stderr:  (only the .claude/settings.json trust warning — nothing about the settings file)
```
Where the **valid** version of the same posture removed the Bash tool entirely (probe C), the malformed
one left it fully available, with **no warning, no error, and rc 0**. `claude --help`'s `-p` entry
documents this: *"Settings files that fail validation are silently ignored in this mode (no error dialog
is shown)."*

> **This is a first-class fail-open in AD-7's mechanism and the ADR does not know about it.** A corrupted,
> half-edited, or wrongly-schema'd posture file degrades the invocation to *no posture at all* and the
> envelope carries no signal. §3.6 closes it: **L2 parses and validates the posture file itself before
> launch and refuses to launch if it does not conform** (TD-D8). This is the single most important thing
> the probe bought.

**Probe Q — a *missing* `--settings` path fails closed.** `RC=1`, stdout empty, stderr
`Error: Settings file not found: /tmp/claude/probe1643/does-not-exist.json`. Only *malformed* is silent.

---

**Probe J — the CLI confines file tools to the working directory, independently of the allow list.**
With `allow: ["Bash(touch *)"]`, a target *outside* the cwd was denied:
```
result = "DENIED\n\nThe `touch` was blocked: `/tmp/claude/probe1643/canary-J.txt` is outside this
          session's allowed working directory (`/tmp/claude/probe1643/nested`), and there's no approval
          surface in this non-interactive session."
```
Useful: because L2 launches with `cwd = repo root` and delivers the prompt on **stdin**, a read-only
reviewer posture needs **no** `additionalDirectories` at all. §3.6 states that as a positive property.

**Probes D/E/F/G — a negative control that failed, reported because it changes what a posture can
claim.** With `allow: []`, `--permission-mode manual` and `--permission-prompts none`, `echo` **still
ran** — including with `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CODE_ENTRYPOINT` and the messaging vars all unset (probe G). Probes K/H show the same
configuration *does* deny `touch`. So the CLI auto-approves a class of commands it judges safe,
regardless of the allow list. **Consequence: an empty `allow` list does not mean "nothing runs", and a
posture must never be documented as if it did.** §3.6 records this as a stated limit of the mechanism.

**Probe S — an unknown top-level key in a `--settings` file is tolerated** (an `hos:` block alongside
`permissions:` did not prevent the `allow` entry from applying). **Deliberately NOT relied upon**
(TD-D9): probe P shows that a file this CLI decides is invalid is dropped *in silence*, and "unknown keys
are tolerated" is undocumented behaviour one version bump from being the thing that silently drops the
whole posture. §3.6 uses a **separate sidecar file** instead.

**One documented flag the ADR's AF-2 did not see: `--max-budget-usd <amount>` ("only works with
--print").** AF-2's conclusion that there is no `--max-turns` is **confirmed** (it is absent from
`--help` on 2.1.270), but a *cost* bound does exist. Not designed in here — recorded in §12 ESC-H as a
cheap second bound worth considering once W6 has a measurement.

### 0.3 Verification gaps I could not close

- **How long one `claude --print --agent <reviewer>` takes over a real diff.** Unchanged from the ADR:
  no such invocation has run. My probes were trivial prompts (1–2 turns, ~1–3 s) and say nothing about a
  review. **No number in this document is calibrated from them, and W6 remains the only source.**
- **Whether `terminal_reason` has good values other than `"completed"`.** I observed `completed` and
  `api_error` only. §3.7's allowlist is `{absent, "completed"}` and is deliberately the tightest reading
  of AD-4; if a legitimate second good value exists, W6 will surface it as a spurious
  `invocation_failed` — which is the correct direction to be wrong in, and is why W6 is observation-only.
- **`--json-schema`'s effect on the envelope.** Not probed. Named in §12 ESC-I as a possible future
  strengthening of §4.3's payload extraction, not designed in.
- **Live branch-protection / required-check list.** Not queried (same wrapper gap ADR-1357 recorded).

---

## 1. What W1–W5 deliver, and what they deliberately do not

### 1.1 Delivers

| Slice | Deliverable |
|---|---|
| **W1** | `scripts/automation/agent_invoke_cli.py` (L2) + `bootstrap/invoke_agent.sh` (L3); the AD-4 classifier; AD-5's Python timeout with process-group reaping; AD-3's agent resolution; AD-7's posture loading **and validation**; four posture files under `contract/dimensions/postures/`. |
| **W2** | The AD-6 result document: its schema, its literal form, its emission rules, and its proven round-trip through `validation_logic.compute_verdict` and `panel_logic`'s readers. Designed here in parallel with W1 and implemented **inside** `agent_invoke_cli.py` — it is that module's owned schema, exactly as `merge_authority_cli.py` owns its record schema (ADR-1357 ARCH-3a). |
| **W3** | `token_tracker.py` wiring, the per-invocation audit record, and the usage-limit **surfacing** half. |
| **W4** | `validate_self.sh` and `validate_scripts.sh` migrated; both `run_capped` copies deleted; `setup_clis.sh` exemption comment; the CLAUDE.md canonical-entry-point row. **`run_panel.sh` splits out as W4b** (§6.4, TD-F4). |
| **W5** | `contract/dimensions/` — the registry schema, the fail-closed loader, the three-layer merge, `core.yaml`, `packs/django/dimensions.yaml`, `packs/astro/dimensions.yaml`, the installer changes AF-9 says are genuinely new, and `run_post_change_sweep.sh` reduced to `--explain`. |

### 1.2 Does not deliver — named so the coder does not drift into them

| Not in W1–W5 | Owner | Seam |
|---|---|---|
| Any sweep, fan-out, per-cycle budget, resumability, or `input_digest`-keyed reuse | **W6/W7** (AD-13) | §4.2 defines `input_digest` and `input.*` and §7.5 defines `resolve_for_diff`; nothing calls them in a loop. |
| Any PR comment, envelope post, or durable result storage | **W7** (AD-14) | L2 writes to stdout and optionally one file. It performs **no GitHub I/O** and mints no token (AD-1). |
| Any change to `decide_merge_authority`'s signature or to merge eligibility | **W8** (AD-15) | Nothing here is read by any merge decision. |
| Any new `bin/hos-cron` execution stage | **W7** (ESC-2) | `bin/hos-cron` is not edited by W1–W5. |
| `scope-conformance`, `semantic-duplication` | **W11/W12** | `core.yaml` declares **no** entry for them; adding one before the agent exists would violate loader rule L10. |
| `#1536` / framework-validation via the primitive | **W10** | W4 migrates `validate_self.sh`'s *invocation*; it does not change who runs framework validation. |
| Anything in #1644 / REQ-C | **`pm-agent`, re-scoping** | AD-2 is honoured exactly: the primitive has no `--round`, no resume token, no parent-session awareness, and no state between invocations. §3.8 makes that a prohibition, not an omission. |
| Promoting `run_panel.sh`'s two Claude seats to named agents | **W4b** | §6.4. |

---

## 2. Layer map — concrete file paths

```
L1  scripts/oversight/validation_logic.py        UNCHANGED — fingerprint() imported; load_ledger() never
    scripts/oversight/lib/audit_log.py           UNCHANGED — write_event() imported
    scripts/oversight/token_tracker.py           UNCHANGED — invoked as a subprocess
    scripts/automation/lib/dimension_registry.py NEW (W5) — pure loader/resolver, no argparse, no __main__
      ^ imported by
L2  scripts/automation/agent_invoke_cli.py       NEW (W1+W2+W3) — owns the result schema and the exit codes
    scripts/automation/dimension_registry_cli.py NEW (W5) — argparse over the loader
      ^ invoked by
L3  bootstrap/invoke_agent.sh                    NEW (W1) — fixed argv, no JSON literal, byte-for-byte passthrough
    scripts/framework/run_post_change_sweep.sh   REWRITTEN (W5) — --explain over the resolved registry

    contract/dimensions/core.yaml                NEW (W5) — CORE entries + CORE bindings
    contract/dimensions/project.yaml             NEW (W5) — HOS's OWN project layer (not shipped)
    contract/dimensions/project.yaml.template    NEW (W5) — shipped; consumers copy it themselves
    contract/dimensions/postures/
      review-read-only.settings.json             NEW (W1) — CLI-native settings document
      review-read-only.hos.json                  NEW (W1) — HOS sidecar: mode + tool lists
      review-read-only-gh-read.settings.json     NEW (W1)
      review-read-only-gh-read.hos.json          NEW (W1)
    packs/django/dimensions.yaml                 NEW (W5) — pack binding source
    packs/astro/dimensions.yaml                  NEW (W5)
```

**Import bootstrap (both L2 modules).** Insert `Path(__file__).resolve().parents[2]` at `sys.path[0]`
before importing `scripts.*`, so the CLI is **cwd-immune**. Do not rely on being invoked from the repo
root; do not rely on `PYTHONPATH`. Rationale is `merge_authority_cli.py`'s, verbatim: a cwd-relative
import silently disables the guard the moment someone invokes it from elsewhere.

**`scripts/oversight` is not an importable package** (no `__init__.py`; `tests/conftest.py` injects the
path). `validation_logic`, `audit_log` and `token_tracker` all live there. **TD-D1: load them by file
path**, using the idiom `merge_authority._load_audit_log` (`merge_authority.py:1056-1071`) already
establishes for exactly this reason, rather than adding `__init__.py` files to `scripts/oversight/`
(which would change that tree's import surface for every existing consumer — out of scope and not ours).

---

## 3. W1 — the invocation primitive

### 3.1 L2 module structure — `scripts/automation/agent_invoke_cli.py`

Exactly six kinds of member; nothing else belongs in the module.

1. **`main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int`** — builds the
   parser, validates, invokes, prints **exactly one JSON object to stdout**, returns the exit code.
   `if __name__ == "__main__": sys.exit(main())`. Callable in-process from tests with an explicit `argv`;
   must **never** call `sys.exit` itself except through that final line. `repo_root` is a **test-only
   injection point**: `argparse` must not define it and the `__main__` block must not populate it.
2. **`resolve_agent(repo_root, name) -> AgentRef`** — AD-3's resolution and existence check (§3.4).
3. **`load_posture(repo_root, name) -> Posture`** — AD-7's posture load **and validation** (§3.6).
4. **`run_capped(argv, *, stdin_bytes, cwd, timeout_s, grace_s) -> ProcResult`** — AD-5's launch, cap and
   process-group reap (§3.5). One implementation, in Python, with no bash twin.
5. **`classify(proc: ProcResult) -> Classification`** — AD-4's allowlist (§3.7). **Pure**: value in, value
   out, no I/O. This is the function the synthetic-envelope tests drive.
6. **`build_document(...) -> dict`** — the AD-6 document assembler (§4), and module constants
   (`SCHEMA`, `SCHEMA_VERSION`, `GOOD_TERMINAL_REASONS`, `VERDICTS`, `SEVERITIES` re-exported from
   `validation_logic`, `DEFAULT_TIMEOUT_S`, `MIN_TIMEOUT_S`, `MAX_TIMEOUT_S`, `DEFAULT_GRACE_S`).

**No module-level side effect.** Importing the module must perform no I/O, no config read, no subprocess,
no clock read beyond constant definition.

### 3.2 CLI surface (L2)

```
python3 scripts/automation/agent_invoke_cli.py
    --agent <name>              REQUIRED  shipped agent name; ^[a-z][a-z0-9-]*$
    --input-file <path>         REQUIRED unless --not-applicable; prompt/context, delivered on stdin
    --posture <name>            REQUIRED unless --not-applicable; ^[a-z][a-z0-9-]*$
    --dimension <entry-id>      optional, default "ad-hoc"
    --binding <binding-id>      optional, default null
    --lens <name>               optional, default = --dimension
    --timeout <seconds>         optional, default 300, floor 30, ceiling 1800
    --grace <seconds>           optional, default 10, floor 1, ceiling 60
    --model <alias>             optional; ABSENT means the agent file's frontmatter governs (AD-3)
    --step <string>             optional; passed to token_tracker --step
    --head-sha <sha> / --base-sha <sha>        optional; recorded in input{} only
    --matched-file <path>       optional, repeatable; recorded in input{} and digested
    --prompt-template-version <str>            optional; recorded and digested
    --output-file <path>        optional; the same bytes as stdout are also written here
    --not-applicable <reason>   optional; emits a not_applicable document and LAUNCHES NOTHING (§4.5)
    --require-env-auth          optional; pre-flight env-token check (§3.4 P7, TD-F3)
```

**Refused outright, exit 2, no document** (AD-3, AD-7): any `--agents`; any `--permission-mode`
(the mode is the posture's, never the caller's); `--permission-mode bypassPermissions` in any spelling;
any `--output-format` (AD-4: L2 sets `json` and a caller may not override); any `--allowed-tools` /
`--disallowed-tools` / `--tools` (they come from the posture); any `--dangerously-skip-permissions` or
`--allow-dangerously-skip-permissions`; any `--settings`; any unrecognised flag. **argparse must not
define these flags at all**, so they land in `parse_known_args`' unknown list and are rejected by name in
the error message — a caller who tries gets told *which* forbidden flag they passed.

**TD-D2 — stdout is the document; `--output-file` is a convenience.** AD-1/AD-6 say "one JSON object" and
L3 passes stdout through byte-for-byte; AD-2 says "all state out is a file path plus an exit code". These
read differently. Binding resolution: **stdout is authoritative**; `--output-file`, when given, receives
the **byte-identical** content. There is one producer and one serialization; the file is a copy, never a
second rendering. AD-13/AD-14 own durable storage and are out of scope.

### 3.3 Exit codes — the complete decision table

Vocabulary is #1641's, unchanged (AD-1). **The pass/fail of the review is never an exit code.**

| Code | Meaning | Emits a document? |
|---|---|---|
| **0** | The invocation was attempted and a conforming AD-6 document was produced — whatever it says. Includes every `outcome: invocation_failed` case and every `verdict: request_changes`. | **Yes**, on stdout. |
| **1** | Operational failure of the primitive itself: it could not emit a document. Only these causes: **a declared module-level third-party runtime dependency of L2 is not importable by the interpreter that started it (P0, §3.4 — Amendment A)**; repo root unresolvable (`.claude/agents/` absent under the computed root); `--output-file` unwritable; a `json.dumps` failure; an unhandled exception caught at the top level. One machine-stable single line on **stderr**, prefixed `agent_invoke: ` — a traceback is never an acceptable rendering of any of these. **L3 owns two further exit-1 causes of its own** (no interpreter resolvable; `INVOKE_AGENT_PYTHON` set to a non-executable path), prefixed `invoke_agent.sh: ` (§3.9). | No. |
| **2** | Usage error: unknown/forbidden flag, missing required flag, `--agent`/`--posture` failing the name grammar, `--timeout`/`--grace` out of range, `--input-file` missing/empty/not-UTF-8, `--not-applicable` combined with `--input-file`, a `--posture` that has no code-side counterpart (§3.6). One line on stderr, prefixed `agent_invoke: `. | No. |
| **3** | **Never produced by this surface.** Reserved, as in `merge_authority.sh`. | — |

**Why a missing agent file is exit 0 and not exit 2.** AD-3 binds it to `outcome: invocation_failed`,
`outcome_detail: agent_unavailable`, `verdict: error` — i.e. a *record*, so the fail-closed chain into
`compute_verdict` works and a caller that only reads documents still blocks. An exit code with no document
would be a silence, and §7.4/REQ-B3's rule is that a silence is never a result. The same reasoning makes
a malformed **posture file** a document (`posture_invalid`) rather than an exit 2, while an **unknown
posture name** is exit 2 (that is a caller programming error, not an environment state).

### 3.4 Preconditions — ordered, all before launch

| # | Check | Failure |
|---|---|---|
| **P0** | **(Amendment A, TD-D23)** Every module-level third-party import of L2 succeeded — today exactly one, `yaml`. Checked **first, before `argparse` runs**, so exit 1 dominates exit 2 | exit **1** |
| P1 | Repo root = `Path(__file__).resolve().parents[2]` (or the injected `repo_root`); `<root>/.claude/agents/` is a directory | exit **1** |
| P2 | `--agent` matches `^[a-z][a-z0-9-]*$` | exit **2** |
| P3 | `<root>/.claude/agents/<agent>.md` exists, is a regular file, and is non-empty | document, `agent_unavailable` |
| P4 | That file's YAML frontmatter parses and its `name:` equals `--agent` (**TD-D3**, mine) | document, `agent_unavailable` |
| P5 | `--posture` is in the code-side posture table **and** both of its files exist and validate (§3.6) | table miss ⟹ exit **2**; file miss/invalid ⟹ document, `posture_invalid` |
| P6 | `--input-file` exists, is a regular file, is non-empty, decodes as UTF-8 | exit **2** |
| P7 | `--require-env-auth` given ⟹ `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` is set and non-empty | document, `not_authenticated` |
| P8 | `shutil.which("claude")` resolves | document, `cli_unavailable` |

**TD-D23 (Amendment A, mine) — P0: a missing runtime dependency is the primitive failing to run, not an
invocation outcome.** `yaml` is used in exactly one place — `_parse_frontmatter`, feeding P4's `name:`
equality check, i.e. the #608 anti-confusion check on a governance surface. An interpreter that cannot
perform that check cannot be trusted to have performed anything else this module claims, so it must not
emit a document at all. Binding rules:

1. **The import is guarded, and the guard's only consumer is P0.** Module scope becomes
   `try: import yaml / except ImportError as exc: yaml = None; _YAML_IMPORT_ERROR = exc / else:
   _YAML_IMPORT_ERROR = None`. This preserves §3.1's "importing this module performs no I/O" and it is
   the *fail-closed* inverse of `config_resolver.py`'s tolerant idiom TD-VF-10 forbids copying: the
   sentinel exists so the failure can be **reported precisely**, never so a code path can continue
   without it.
2. **`main()` checks `_YAML_IMPORT_ERROR is not None` as its first statement**, before `argparse`,
   before P1, and returns **1** after writing exactly one line to stderr:
   `agent_invoke: error: PyYAML is required to verify agent frontmatter but is not importable by
   <sys.executable> — run: bash scripts/oversight/ensure_venv.sh`. The interpreter path is in the message
   because *which interpreter got chosen* is the whole diagnosis for this defect class. One line; never a
   traceback; nothing on stdout.
3. **Prohibited, and pinned by a source test (§9.1 T1.53):** no other code path may test the sentinel.
   `_parse_frontmatter` must not gain an `if yaml is None` branch, and a missing PyYAML must **never**
   produce `agent_unavailable`, `posture_invalid`, `schema_violation`, an exit-0 document, or an exit 2.
   Those would each be a *different defect's* label attached to a deployment fault — the silent-wrong-
   answer failure mode this whole design exists to prevent.
4. **Why exit 1 and not a document** (the `cli_unavailable` analogy is the wrong one): a missing `claude`
   binary is a property of the environment the primitive *drives*, so a record saying "the check did not
   happen" is exactly right. A missing PyYAML is a property of the interpreter running the primitive
   *itself* — the same class as §3.9's long-standing "no `python3` ⟹ exit 1" — and a `verdict: error`
   document would assert that a review was attempted when none was. Exit 1 is already defined as
   "operational failure of the primitive itself"; this is one, and it routes to the operator (Q1's
   `HUMAN_REQUIRED` path for operational failure) rather than into the review record.
5. **This generalises.** The rule is stated over *every* module-level third-party import, not over
   `yaml` specifically, so the next such import inherits the precondition instead of re-learning it
   (§9.1 T1.54 makes that mechanical).

**TD-D3 rationale (P4).** AD-3 requires only existence. A file that exists but declares a different
`name:` is a governance hole of the same family as #608 — the caller believes it invoked
`security-reviewer` and the CLI resolved something else. The check is one YAML parse of a file already
being hashed for `input_digest`, so it is free.

**P7 and TD-F3.** REQ-A4 requires authentication to be "verified **before** invocation". **It cannot be,
in general**: probe A authenticated with `CLAUDE_CODE_OAUTH_TOKEN` absent from the environment (keychain),
so an unconditional pre-flight env check would return a **false** `not_authenticated` for every
interactive caller — the loudest possible false fail-closed. Resolution: the pre-flight is **opt-in**
(`--require-env-auth`, which `bin/hos-cron`-launched callers should pass, since VF-1.1 establishes the
env token *is* exported there and failing fast saves a wasted session), and the **post-hoc** classifier
recognises the failure unconditionally: `terminal_reason == "api_error"` with an envelope `result` matching
`/not logged in/i` ⟹ `outcome_detail: not_authenticated`. Both paths are distinguishable outcomes, as
REQ-A4 asks; only the *timing* of one of them departs from the requirement's wording. **Escalated as
ESC-C.**

### 3.5 Launch contract and the AD-5 timeout

**The argv L2 builds, in this fixed order:**
```
claude --print
       --output-format json
       --agent <agent>
       --settings <abs path to contract/dimensions/postures/<posture>.settings.json>
       --permission-mode <posture.permission_mode>          # from the sidecar; {manual, dontAsk} only
       --permission-prompts none
       --allowed-tools <posture.allowed_tools joined by space>
       --disallowed-tools <posture.disallowed_tools joined by space>
       --exclude-dynamic-system-prompt-sections
       --no-session-persistence
       [--model <alias>]                                    # ONLY when --model was given
```
- No prompt on argv. The `--input-file` bytes go to the child's **stdin**, which is then closed
  (AD-1, REQ-A3, #1368).
- `--permission-prompts none` is **TD-D4** (mine, additive to AD-7): `--help` defines it as *"nobody:
  anything that would prompt is denied automatically; the permission mode still decides everything else"*.
  It converts "there is no one to approve, so behaviour is whatever the CLI decides" into a stated
  contract. Probe H/K confirm the pair denies; probes D–G confirm it does not deny the CLI's
  auto-approved safe-command class.
- **`--allowed-tools` is a GRANT list, not a narrowing list (ADR-1643 Amendment 5, AD-7.1 — #1678).** A
  bare tool name passed through it is an **unconditional grant** of that tool that supersedes the
  settings file's rule-scoped `Bash(...)` entries for it, leaving `permissions.deny` as the only
  remaining boundary (128-invocation live probe, CLI 2.1.272, arms K/L/M/N and Q/R). `posture.allowed_tools`
  therefore never contains the bare string `"Bash"` (`load_posture`'s V13, §3.6) — Bash remains an
  *available, rule-governed* tool through the settings file's rule-scoped allow entries, never a blanket
  grant. `--disallowed-tools` is unaffected by this finding and remains restrictive (arms E/H): omitting a
  tool from it does not remove the tool, but including it does.
- `--exclude-dynamic-system-prompt-sections` and `--no-session-persistence` are copied from
  `validate_self.sh:230-234`'s reasoning: the invocation is self-contained and must leave no session
  state.

**Process control (AD-5, TD-D5).**
1. `subprocess.Popen(argv, stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=<repo root>, start_new_session=True,
   env=<inherited>)`. `start_new_session=True` puts the child in its own process **group**, which is the
   whole point — `timeout(1)` signals only the direct child and `claude` spawns tool subprocesses.
2. Write the input bytes, close stdin, then read both pipes to completion under the cap. Use threads or
   `selectors` for the two pipes — **never** `communicate()` without a timeout, and never a single merged
   stream (probe A: the trust warning is on stderr and would corrupt stdout).
3. On expiry: `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`; wait `--grace` seconds; then
   `os.killpg(..., signal.SIGKILL)`; then `proc.wait()`. Both signals target the **group**, never the pid.
4. `timed_out = True` is recorded on the `ProcResult` and is the **highest-precedence** classifier input
   (§3.7). `outcome_detail: timeout`, never folded into `crash`.
5. Partial stdout captured before the kill is **discarded for classification purposes** (it cannot be a
   complete envelope) but is recorded, truncated to 4 KiB, in `invocation.stdout_partial` for diagnosis.
6. **Zero/unbounded is not an accepted value.** `MIN_TIMEOUT_S = 30`, `DEFAULT_TIMEOUT_S = 300` (the repo's
   own `AI_REVIEW_TIMEOUT` calibration, `validate_agents.sh:141` / `validate_scripts.sh:54` — **not** a
   number derived from my probes), `MAX_TIMEOUT_S = 1800` (`HOS_CRON_MAX_SECONDS`' default: a single
   invocation may never be permitted to outlast a whole cron cycle). Out of range ⟹ exit 2.
7. **AF-2 stands:** there is no `--max-turns` on 2.1.270, so wall-clock is the only bound on a runaway
   session. `num_turns` is recorded as a post-hoc signal and gates nothing.

**W1 deletes nothing.** The two `run_capped` copies are deleted in **W4** (§6.3), when their `claude`
consumer is gone.

### 3.6 Posture files (AD-7) — two files per posture, both under `contract/`

**TD-D8 — L2 validates the posture file itself before launch.** Probe P: a malformed `--settings` file is
silently ignored and the invocation runs with no posture. The CLI will not tell us. Therefore L2 must.

**TD-D9 — the posture is two files, not one with an `hos:` key.** Probe S shows an unknown top-level key
is tolerated today, but probe P shows a file this CLI judges invalid is dropped **in silence**, and
key tolerance is undocumented. A sidecar L2 parses itself depends on nothing undocumented.

**TD-D10 — the sidecar lives under `contract/`, not in L2's code.** TD-VF-12: `contract/**` is protected
surface and `scripts/automation/**` is not. Putting the tool lists in code would move the security
decision off the human-gated surface, which is the opposite of AF-11's whole argument.

**File pair, per posture `<p>`:**
- `contract/dimensions/postures/<p>.settings.json` — a **pure CLI settings document**, the shape of
  `contract/sandbox-policy.template.json`. No HOS keys. No `__PLACEHOLDER__` tokens (these are static and
  are **not** processed by `gen_sandbox_config.py`).
- `contract/dimensions/postures/<p>.hos.json` — the HOS sidecar.

`review-read-only.settings.json` (literal, complete):
```json
{
  "permissions": {
    "defaultMode": "manual",
    "disableBypassPermissionsMode": "disable",
    "additionalDirectories": [],
    "allow": [
      "Read", "Grep", "Glob",
      "Bash(git diff *)", "Bash(git show *)", "Bash(git log *)", "Bash(git status)",
      "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(wc *)", "Bash(ls *)",
      "Bash(grep *)", "Bash(rg *)", "Bash(find *)", "Bash(sed -n *)"
    ],
    "deny": [
      "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task",
      "Bash(gh *)", "Bash(git push *)", "Bash(git commit *)", "Bash(curl *)",
      "Bash(wget *)", "Bash(rm *)", "Bash(mv *)", "Bash(cp *)", "Bash(chmod *)",
      "Bash(pip *)", "Bash(npm *)", "Bash(python *)", "Bash(python3 *)", "Bash(bash *)", "Bash(sh *)"
    ]
  }
}
```
`review-read-only.hos.json` (literal, complete):
```json
{
  "schema": "hos.invocation-posture",
  "schema_version": 1,
  "id": "review-read-only",
  "description": "Filesystem read + local read-only shell. No network, no write tools, no gh.",
  "permission_mode": "manual",
  "allowed_tools": ["Read", "Grep", "Glob"],
  "disallowed_tools": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"]
}
```
**`allowed_tools` carries no `"Bash"` (ADR-1643 Amendment 5, AD-7.1 — #1678).** Bash remains available
through the settings file's rule-scoped `Bash(...)` allow entries above; it is never granted as a bare,
unconditional tool grant. This is a correction from this document's original W1 shape, which listed
`"Bash"` in `allowed_tools` — see §3.5 and Amendment 5 §10 for the probe that found it exploitable.

`review-read-only-gh-read` is the same pair with `Bash(bootstrap/query_issues.sh *)` (direct execution,
not routed through the `bash` interpreter) added to `permissions.allow` and removed from nothing —
**not** `Bash(bash bootstrap/query_issues.sh *)`, which the amendment rejects: that spelling requires
deleting `Bash(bash *)` from the deny list to be reachable, and doing so reopens a live command-
substitution bypass. The direct-execution spelling needs no deny-list change; `Bash(bash *)` and
`Bash(sh *)` both stay, unchanged. **TD-D11: the id is spelled `review-read-only-gh-read`**; AD-7 writes
it `review-read-only+gh-read`, and `+` is not in the `^[a-z][a-z0-9-]*$` id grammar the registry and
filenames share. Same posture, different spelling of the name.

**`coder` gets no posture here** (AD-7, Q7): nothing in W1–W5 invokes a code-writing agent, and inventing
its posture ahead of #1644's re-derivation would be exactly the premature binding Q7 warns against. A
future posture is a new file pair; no code change.

**`load_posture` validation — every one of these is a hard failure:**

| # | Rule | On failure |
|---|---|---|
| V1 | `<p>` is in L2's `KNOWN_POSTURES` frozenset (`{"review-read-only", "review-read-only-gh-read"}`) | exit **2** |
| V2 | Both files exist and are regular files | document, `posture_invalid` |
| V3 | Both parse as JSON objects | document, `posture_invalid` |
| V4 | Sidecar `schema == "hos.invocation-posture"` and `schema_version == 1` | document, `posture_invalid` |
| V5 | Sidecar `id == <p>` and matches the filename stem | document, `posture_invalid` |
| V6 | Sidecar `permission_mode ∈ {"manual", "dontAsk"}` | document, `posture_invalid` |
| V7 | Settings has a `permissions` object with `disableBypassPermissionsMode == "disable"` | document, `posture_invalid` |
| V8 | Settings `permissions.allow` and `permissions.deny` are both lists of strings | document, `posture_invalid` |
| V9 | `allowed_tools ∩ disallowed_tools == ∅` | document, `posture_invalid` |
| V10 | Every entry in `disallowed_tools` appears in `permissions.deny` (the two layers agree) | document, `posture_invalid` |
| V11 | `permissions` contains no `defaultMode` of `"bypassPermissions"` and the settings file contains no `dangerously` substring anywhere | document, `posture_invalid` |
| V12 | For every tool `T` in `allowed_tools`: `permissions.allow` contains no entry matching `^T\(` (ADR-1643 Amendment 5, AD-7.1 — #1678: a bare tool name in `allowed_tools` is an unconditional grant that supersedes a rule-scoped `T(...)` entry for the same tool) | document, `posture_invalid` |
| V13 | `"Bash"` is never a member of `allowed_tools`, unconditionally (Amendment 5 AD-7.1 — stated non-contingently so deleting the last `Bash(...)` allow entry can't silently reintroduce the blanket grant without tripping V12) | document, `posture_invalid` |
| V14 | Every `permissions.allow` entry of the form `Bash(<script-path> *)`, where `<script-path>` contains a path separator, resolves (relative to repo root) to an existing file with the executable bit set (Amendment 5 §10.7 — the portability precondition for a rule-scoped script grant, made to fail loudly rather than degrade to a missing capability) | document, `posture_invalid` |

**Two properties worth stating positively.**
- *No `additionalDirectories` is needed — conditional on AD-7.1 (Amendment 5 §10.5).* Probe J (CLI
  2.1.270) found the CLI confines file tools to the working directory; a later probe on CLI 2.1.272
  (Amendment 5 §10.0/§10.4) found markers written *outside* the launch directory under the shipped
  (pre-amendment) launch contract — the bare-`Bash` grant bypassed containment along with every other
  rule. **Restated, not withdrawn:** cwd containment holds for tools evaluated through the rule-based
  path, and AD-7.1 (no bare tool grant) is what keeps Bash on that path. `additionalDirectories: []`
  remains the tightest correct value; the *reason* it holds changed. Nothing in this design may pin a CLI
  version, and no posture property may be inherited from a probe of an older build (Amendment 5 AD-7.9).
- *The agent frontmatter `tools:` list is a real second layer.* Probe M: it **narrowed** a posture that
  would otherwise have permitted the call. AD-7's "defence in depth, not a substitute" is accurate.

**Stated limit of the mechanism (probes D–G).** The CLI auto-approves a class of commands it judges safe,
regardless of `permissions.allow` and regardless of `--permission-mode manual`. An empty `allow` list
therefore does **not** mean "nothing runs". **A posture's security value comes from its `deny` list, its
`disallowed_tools`, and — only under AD-7.1 (no bare tool grant in `allowed_tools`) — its rule-scoped
`allow` entries** (corrected per ADR-1643 Amendment 5 §10.6 rule 3: this document's original statement,
"not from the narrowness of its `allow` list", was half of the picture — a bare tool grant makes the
allow list's rule-scoped entries for that tool count for nothing, which is the converse nobody had drawn
until the amendment's probe). This must be stated in each posture file's `description` so nobody reads
the allow list as exhaustive, and so nobody reads a rule-scoped allow entry as meaningful in the presence
of a bare grant for the same tool.

### 3.7 The AD-4 classifier — complete, with precedence

`classify(proc) -> Classification` is **pure**. `proc` carries `rc`, `timed_out`, `stdout_bytes`,
`stderr_bytes`, `duration_ms`.

**`outcome == "completed"` is produced only when every one of these holds.** Any miss ⟹
`outcome == "invocation_failed"`.

| # | Condition for `completed` |
|---|---|
| C1 | our own cap did not fire (`timed_out is False`) |
| C2 | stdout parses as **exactly one** JSON object (leading/trailing whitespace tolerated; nothing else) |
| C3 | `is_error` is absent or falsy |
| C4 | `terminal_reason` is absent **or** in the closed allowlist `GOOD_TERMINAL_REASONS = {"completed"}` |
| C5 | `permission_denials` is absent or an empty list |
| C6 | `subagent_stats.refused` is absent, or is `0`, or is a mapping every one of whose values is the integer `0` (**TD-F1**, §12 ESC-A) |
| C7 | the process exit code is `0` |
| C8 | the agent payload extracted from `result` parses **strictly** as a conforming AD-6 body (§4.3) |

**`subtype` is not an input.** It is recorded verbatim in `invocation.envelope` and read by nothing. Probe
R reproduces `subtype:"success"` with `is_error:true` on 2.1.270; the field's presence is harmless here
precisely because it is never consulted. **Do not add it "for completeness."**

**`outcome_detail` precedence (TD-D6, mine).** AD-4's table lists rc first. Probe R shows a non-zero rc
can carry a *more precise* envelope reason (`api_error` + `api_error_status: 404`). The **outcome** is
`invocation_failed` either way, so this changes only the label; the precedence is therefore mine to set
and is set for diagnosability:

1. `timed_out` ⟹ **`timeout`**
2. stdout empty or not exactly one JSON object ⟹ **`unparseable`**
3. envelope decision fields shape-violating (e.g. `permission_denials` not a list, `is_error` not a bool,
   `subagent_stats.refused` neither int nor a flat int mapping) ⟹ **`envelope_shape_violation`**
4. `terminal_reason` present and not in `GOOD_TERMINAL_REASONS`:
   - `"api_error"` and the envelope `result` matches `/not logged in/i` ⟹ **`not_authenticated`**
   - value ∈ `{"api_error","usage_limit","refusal","max_turns"}` ⟹ that value verbatim
   - any other value ⟹ **`terminal_reason:<value>`** (fails closed by construction — this is the row
     that makes #669 and #1362 unrepeatable rather than re-fixed)
5. `is_error` truthy ⟹ **`crash`**
6. `permission_denials` non-empty ⟹ **`permission_denied`**
7. `subagent_stats.refused` non-zero ⟹ **`refused`**
8. rc != 0 ⟹ **`crash`**
9. payload fails the strict AD-6 body parse ⟹ **`schema_violation`**
10. otherwise ⟹ `outcome: completed`, `outcome_detail: null`

Plus the **four** pre-flight details that never reach `classify` because no process is launched:
**`agent_unavailable`** (P3/P4), **`posture_invalid`** (P5/V2–V14), **`not_authenticated`** (P7),
**`cli_unavailable`** (P8). (**Amendment B, 2026-09-18:** this sentence read "three" while listing four —
a count error corrected here because **§5.1 TD-D24 keys on exactly this set**, and because a clause that
says "three" over a list of four invites a reader to treat one of them as not really belonging, which is
a plausible contributing cause of the §5.1 omission Amendment B exists to close. The parenthetical
`V2–V11` is widened to `V2–V14` on the same line to match §3.6's table, which ADR-1643 Amendment 5
extended with V12–V14 — all three also produce `posture_invalid`.) **The four are exactly the rows
§5.1's table marks "Not called", together with `--not-applicable`; there is no fifth.**

**The one rule that is not negotiable (AD-4, AD-6):**
> `outcome == "invocation_failed"` ⟹ `verdict == "error"` in the emitted document, **always**, whatever
> the agent said.

That single rule makes every existing `validation_logic.compute_verdict` consumer fail closed on a broken
invocation for free, via the #670 error-block path (the `ERROR_VERDICT` branch of `compute_verdict` — an `error` verdict counts as one NEW
blocking finding and is never dedup-silenced). It is verified by test **T2.6** (§9.2), not asserted.

**Unknown envelope fields.** AD-4 says *"any envelope field the classifier does not recognise"* produces
`invocation_failed`. Taken literally that makes every CLI telemetry addition a merge stopper — 2.1.270
already ships `fast_mode_state`, `fast_mode_disabled_reason`, `queued_turn_count`, `result_index`,
`ttft_stream_ms`, `time_to_request_ms`, `first_content_frame_ms`, `inference_geo`, none of which any
ADR-era reader knows. **TD-F2**, escalated as **ESC-B**. **Interim implementable contract, pending the
architect's ruling:** an unrecognised **top-level field** is recorded in
`invocation.envelope_unknown_fields[]` and does **not** block; an unrecognised **value or shape in a
decision field** (rows C3–C7) **does** block, via details 3 and 4 above. The safety property AD-4 exists
for is preserved exactly — #669 and #1362 were both *value*-level fail-opens, not field-level ones.

### 3.8 Boundaries L2 must honour

1. **No state between invocations.** No `--round`, no resume token, no counter file, no parent-session
   read, no `--session-id` reuse. AD-2 is bound as a *prohibition*: adding any of these makes the
   primitive unusable as the cron-driven one-shot step Q4+Q6 ruled #1644 into, and §4 of the ADR rests
   on it.
2. **No GitHub I/O.** No token mint, no `gh`, no `curl`, no comment, no label. AD-1.
3. **No merge, no bounce, no escalation.** L2 emits a document; dispositions are AD-13/AD-15's.
4. **Never imports `validation_logic.load_ledger`.** Enforced by test T2.8 (§9.2).
5. **Never writes to `.claudetmp/`** except transitively through `token_tracker.py`, whose path is its own.
6. **Never prints anything to stdout but the one JSON object.** Every diagnostic goes to stderr.
7. **Never re-derives a registry decision.** Applicability comes from `--not-applicable` or from the
   caller; L2 owns no predicate.

### 3.9 L3 — `bootstrap/invoke_agent.sh`

Copies `bootstrap/merge_authority.sh`'s proven shape (AF-1) and its header conventions verbatim.

**Behaviour, exactly four steps, no logic beyond them** (step 2 rewritten by **Amendment A / TD-D22**):
1. `set -euo pipefail`; resolve `SCRIPT_DIR` / `REPO_ROOT` from `BASH_SOURCE`.
2. **Resolve the interpreter** with this fixed three-rung ladder, in this order, and no other rung:
   1. `$INVOKE_AGENT_PYTHON`, when set and non-empty. If it is set but not executable ⟹ exit **1**, one
      stderr line naming the variable and the path. (Diagnostic/test override only; §9.1 uses it as the
      only seam that can reach rung 3 inside a checkout that has a venv. **L2 must never read it.**)
   2. `$REPO_ROOT/scripts/oversight/.venv/bin/python`, when executable — the venv
      `scripts/oversight/requirements.txt` (which declares `PyYAML>=6.0`) is installed into by
      `scripts/oversight/ensure_venv.sh`. This is the repo's established idiom
      (`run_gates.sh:36-42`, `prompt_audit.sh:22`, `cut_release.sh:35`, `django_check.sh`).
   3. `python3` from `PATH`, when `command -v` finds it. Safe as a last rung **only because** L2's P0
      (§3.4) fails closed on it — it is not a silent degradation path.
   4. None of the three ⟹ exit **1**, one stderr line containing the substring `python3`, naming all
      three rungs and pointing at `bash scripts/oversight/ensure_venv.sh`.
3. `exec "$PYTHON" "$REPO_ROOT/scripts/automation/agent_invoke_cli.py" "$@"`.
4. There is no step 4.

**TD-D22 (Amendment A, mine) — interpreter resolution belongs in L3, and AD-1 does not prohibit it.**
AD-1's prohibition, quoted in this script's own header, has two clauses and interpreter resolution is
outside both: it is not *"a JSON literal, a `printf`/`echo` to stdout, or any re-derivation of a field"*
(it produces no field and writes nothing to stdout), and it is not *"a `case` statement, a flag of its
own, or any validation/default/re-derivation of a caller-supplied flag"* (it never reads `$@`, never
branches on a caller argument, and adds no flag). It is **launch**, which under #314's standing policy —
*"prefer Python for logic, shell for launch"*, the very policy AD-1 cites to justify the L2/L3 split — is
precisely and only what L3 is for. §3.9 step 2 has always contained an interpreter `if`; TD-D22 corrects
*which* interpreter it selects, and does not widen its category. **L2 structurally cannot make this
choice: by the time L2 runs, the interpreter has already been chosen.** The ladder is the maximum L3 may
grow: three rungs over interpreter paths, plus the two error lines. Anything else is still forbidden.

*Rejected alternatives, recorded so they are not re-proposed.* **(a) Declare PyYAML in the CI test
environment.** Fixes the `tests` check and nothing else: the consumer host still breaks, and — decisively
— it would make the bare-`python3` path **green in CI**, masking this exact defect class from the only
place that would catch it. `.github/workflows/tests.yml` must therefore **not** gain a PyYAML install
(§9.1 T1.55 pins that). **(b) Drop the `yaml` dependency and parse the frontmatter by hand.** Rejected on
AGENTS.md's *"Use the Code, Don't Roll It Yourself"* and, more sharply, on the security posture of the
check itself: P4 is an anti-confusion check, so a parser that disagrees with PyYAML on *any* input
(quoting, block scalars, tags, duplicate keys, BOM, tabs) yields an agent file that the `claude` CLI's own
reader and our governance check resolve **differently** — the #608 hole reopened from a new direction, in
exchange for saving two lines. **(c) Hard-code the venv interpreter with no ladder** (the
`prompt_audit.sh` idiom). Still needs an `-x` guard (a bare `exec` on an absent path exits **127**, a code
outside this surface's 0/1/2/3-reserved vocabulary), so it is not actually simpler, and it fails on a host
whose system interpreter legitimately carries PyYAML.

**What it must never do:** mint or revoke a token (this surface performs no GitHub I/O — AD-1); compose or
emit any JSON; print anything to stdout; suppress stderr (#1523); re-derive, default, or validate any
flag; add a flag of its own; grow a `case` statement; **build, repair, or `pip install` into the venv**
(a review invocation must never mutate its own environment as a side effect — `ensure_venv.sh` is the
operator's call, *named* in the error message and never *invoked* here); **consult
`$INVOKE_AGENT_PYTHON` for any purpose other than ladder rung 1**; **branch on any element of `$@`**.
**Its header must state, as
`merge_authority.sh`'s does, that it must never grow a JSON literal, a `printf`/`echo` to stdout, or any
re-derivation of a field** — adding a document field is a change to `agent_invoke_cli.py` alone.

Because every flag is `--name value`, the argv shape is fixed and statically allowlistable as
`Bash(bash bootstrap/invoke_agent.sh *)`. That is the reason L3 exists at all (AD-1); it is ~40 lines and
must not grow. **TD-D22's ladder does not change that shape** — it branches only on interpreter paths, so
the allowlistable argv is byte-for-byte what it was. Note the corollary for `$INVOKE_AGENT_PYTHON`: an
`VAR=… bash bootstrap/invoke_agent.sh …` command string does **not** match that allowlist rule, so the
override is not reachable through the allowlisted surface; it is an operator/test seam, and it widens no
trust boundary (anyone who can set it can already invoke `agent_invoke_cli.py` directly).

**The consumer-host contract (Amendment A), stated once so it is not re-derived.** After
`bootstrap/hos_install.sh`, a consumer has `scripts/oversight/` (including `ensure_venv.sh` and
`requirements.txt`) but **no `.venv`** — the installer excludes it deliberately, because a venv is
absolute-path-bound to the source tree. On such a host the ladder therefore lands on rung 3, and if that
interpreter lacks PyYAML the invocation **must** produce: exit **1**; **empty stdout** (no document, no
partial JSON); **one** stderr line, P0's, naming the interpreter and `bash scripts/oversight/ensure_venv.sh`;
no traceback; and no side effect of any kind. Exit `3` stays reserved and unused, exit `0` and exit `2`
are unreachable on this path, and a caller that reads only the exit code fails closed. (Today the reach is
narrower than it will be: TD-VF-6 records that `scripts/automation/**` is not in the consumer ship-set, and
`bootstrap/invoke_agent.sh` is not in `framework_consumer_files.txt` either, so no consumer receives this
surface yet. §12 ESC-E owns that decision; this contract is what must already be true when it is made.)

---

## 4. W2 — the result document (AD-6)

### 4.1 Literal example — a completed review with one finding

This is the exact shape. Field order is `json.dumps(..., sort_keys=False)` in the order below; it is
stable so diffs of two documents are readable.

```json
{
  "schema": "hos.agent-invocation-result",
  "schema_version": 1,

  "reviewer": "claude",
  "lens": "security",
  "verdict": "request_changes",
  "summary": "One high-severity finding: the posture loader trusts an unvalidated JSON file.",
  "findings": [
    {
      "severity": "high",
      "category": "input-validation",
      "type": "input-validation",
      "files": ["scripts/automation/agent_invoke_cli.py"],
      "file": "scripts/automation/agent_invoke_cli.py",
      "line": 214,
      "description": "load_posture() parses the settings file but does not assert disableBypassPermissionsMode.",
      "fix": "Add validation rule V7 before returning the Posture."
    }
  ],
  "attacks": [],

  "outcome": "completed",
  "outcome_detail": null,
  "applicability": "applicable",
  "applicability_reason": "binding core:security/code matched 3 changed files",

  "dimension": "security",
  "binding": "core:security/code",
  "agent": "security-reviewer",
  "posture": "review-read-only",

  "input": {
    "head_sha": "627773b…",
    "base_sha": "4f973c4…",
    "predicate_matched_files": [
      "scripts/automation/agent_invoke_cli.py",
      "bootstrap/invoke_agent.sh",
      "contract/dimensions/postures/review-read-only.settings.json"
    ],
    "input_file_sha256": "a3f1…",
    "agent_file_sha256": "b7c2…",
    "posture_sha256": "c9d4…",
    "prompt_template_version": "security/v1",
    "matched_files_sha256": "d1e5…",
    "input_digest": "e8b0…"
  },

  "invocation": {
    "started_at": "2026-09-14T21:47:03Z",
    "ended_at": "2026-09-14T21:49:11Z",
    "duration_ms": 128412,
    "timeout_seconds": 300,
    "timed_out": false,
    "exit_code": 0,
    "model": "sonnet",
    "model_source": "agent_frontmatter",
    "cli_version": "2.1.270",
    "num_turns": 7,
    "session_id": "5063fa1e-71d9-450c-b025-a0c8bcef9c24",
    "usage": { "input_tokens": 2, "output_tokens": 9, "cache_read_input_tokens": 9542, "cache_creation_input_tokens": 11956 },
    "model_usage": { "claude-sonnet-5": { "inputTokens": 2, "outputTokens": 9, "costUSD": 0.1246 } },
    "total_cost_usd": 0.1246,
    "envelope": { "…": "the CLI's result object, verbatim and unmodified" },
    "envelope_unknown_fields": ["queued_turn_count", "result_index"],
    "stdout_partial": null,
    "stderr_tail": "Ignoring 5 permissions.allow entries from .claude/settings.json: …"
  },

  "observability": {
    "token_tracker_recorded": true,
    "audit_record": "2026/09/2026-09-14T214911Z-agent-invocation-4b1c9de07a22.json"
  }
}
```

### 4.2 Field contract

**Legacy-compatible core — semantics unchanged (AD-6, TD-VF-3).**

| Field | Rule |
|---|---|
| `reviewer` | Always the literal `"claude"` — the **vendor**. `panel_logic.count_corroboration` counts distinct `reviewer` values as distinct vendors (`:207-218`); if twelve dimensions each wrote their own name they would read as twelve corroborating vendors, silently inflating corroboration in the one module that computes it. **TD-D14**, and it is the one place AF-7's "two readers" distinction has teeth. |
| `lens` | The dimension entry id (`--lens`, defaulting to `--dimension`). This is `panel_logic`'s second read. |
| `verdict` | `∈ {approve, request_changes, error}` — the existing three-value domain, **not** extended. |
| `summary` | Free text. **No caller may determine pass/fail from it** (REQ-A8). |
| `findings[]` | Per-finding: `severity` from the canonical 7-rank ordering (`validation_logic.SEVERITIES`), `category`, `type` (**same value as `category`**, so codex-shaped readers and agy-shaped readers agree), `files[]` **and** `file` (the first element) **and** `line`, `description`, `fix`. Both file keys are mandatory: `validation_logic._files_of` prefers `files`, `panel_logic.reconcile_membership` reads `file` + `line`. |
| `attacks[]` | Always present, normally `[]`. `compute_verdict` iterates `findings + attacks`; omitting the key is harmless but present-and-empty keeps one shape. |

**New, additive, and where the real information lives.**

| Field | Rule |
|---|---|
| `outcome` | `∈ {completed, invocation_failed}` — §3.7. |
| `outcome_detail` | `null` when `completed`; otherwise one of §3.7's detail strings. |
| `applicability` | `∈ {applicable, not_applicable}`. **Decided by the registry's predicate (AD-9), never by the agent.** L2 sets `applicable` whenever it launches and `not_applicable` only under `--not-applicable`. If the agent's payload contains an `applicability` key it is **ignored and its presence is a `schema_violation`** — there is no path by which an agent declares itself exempt (`worker.md:373-378`: *"v0.4.0 #556: workers repeatedly self-exempted on this basis"*). |
| `applicability_reason` | **Mandatory and non-empty in both states.** For `applicable` the caller supplies it (or L2 writes `"invoked directly (no binding)"` for an ad-hoc call); for `not_applicable` it is `--not-applicable`'s argument. |
| `dimension`, `binding`, `agent`, `posture` | Identity. `binding` is `null` for an ad-hoc invocation. |
| `input.*` | §4.4. |
| `invocation.*` | Timestamps (UTC, `%Y-%m-%dT%H:%M:%SZ`, matching `record_pr_bounce`'s format), duration, the resolved `model` and `model_source ∈ {agent_frontmatter, cli_override}`, `cli_version` (from `claude --version`, cached per process), `num_turns`, `usage`, `model_usage`, `total_cost_usd`, the **verbatim CLI envelope**, and the process exit code. AF-10's lost `SubagentStop` provenance, recovered. `stderr_tail` is the last 4 KiB of the child's stderr; `stdout_partial` is non-null only on a timeout. |
| `observability.*` | §5. Recorded for diagnosis; **no decision may read it** (AD-8). |

**`model` derivation (TD-D15).** `modelUsage` carries more than one key (probe A and probe O both show a
`claude-haiku-4-5` helper alongside the real model), so "the model" cannot be read from it. `model` is
therefore `--model` when given (`model_source: cli_override`), else the agent file's frontmatter `model:`
value (`model_source: agent_frontmatter`), else `null`. `model_usage` is recorded verbatim beside it so
the derivation is auditable and the helper-model cost is not lost.

### 4.3 Strict payload extraction (AD-6, REQ-A9)

`validation_logic.extract_json_objects` is deliberately prose-tolerant — it delegates to
`validation_logic._brace_objects`, which scans braces and tolerates commentary because agy and codex
both prepend it. **L2 must not use it and must not import it.** Our own agent is instructed by our own prompt template and can be held to a contract.

The rule, exactly:
1. Take `envelope["result"]`. It must be a `str`. Otherwise ⟹ `schema_violation`.
2. Strip leading/trailing whitespace. If it begins with ```` ```json ```` (or ```` ``` ````) and ends with
   ```` ``` ````, strip **exactly one** such fence pair. No other stripping. No brace scanning.
3. `json.loads` the remainder. It must yield a `dict`. Anything else ⟹ `schema_violation`.
4. The dict must contain `verdict` with a value in `{approve, request_changes, error}`, and `findings`
   as a list. `summary` must be a string if present. Each finding must be a dict with a `severity` in
   `validation_logic.SEVERITIES` and at least one of `files` (list of str) or `file` (str).
   Any miss ⟹ `schema_violation`.
5. The dict must **not** contain `applicability`, `outcome`, `input`, or `invocation` — those are L2's
   fields and an agent supplying one is asserting something it has no authority over ⟹ `schema_violation`.
6. L2 normalises: fills `type` from `category` (and vice versa), fills `file`/`files` from whichever is
   present, defaults `line` to `null`, `attacks` to `[]`.

`schema_violation` ⟹ `invocation_failed` ⟹ `verdict: "error"`. This is `--strict-empty`'s #669 fix
carried forward, not regressed.

### 4.4 `input_digest` (AD-6) — one function, two populations

AD-13 keys record reuse on `input_digest`; W1 has no registry, so the digest must be computable **now**
and identical **later** for the same inputs. **TD-D16 — the digest is taken over a named component
manifest, with absent components explicitly `null`**, so a W1-era ad-hoc digest can never accidentally
equal a W7-era binding digest:

```python
manifest = {
  "v": 1,
  "agent": <agent name>,
  "agent_file_sha256": <sha256 of .claude/agents/<agent>.md bytes>,
  "posture": <posture id or None>,
  "posture_sha256": <sha256 of settings-bytes + b"\0" + sidecar-bytes, or None>,
  "input_file_sha256": <sha256 of --input-file bytes>,
  "prompt_template_version": <str or None>,
  "dimension": <entry id or "ad-hoc">,
  "binding": <binding id or None>,
  "binding_sha256": <sha256 of the binding's canonical resolved JSON, or None>,   # W7 fills this
  "matched_files_sha256": <sha256 over the sorted (path, sha256-of-bytes) pairs, or None>,
  "base_sha": <str or None>,
  "head_sha": <str or None>,
}
input_digest = sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

Computing it **forces AD-3's agent-existence check as a side effect** (the agent file must be readable to
be hashed), which is the property AD-6 wanted. `matched_files_sha256` is over file *bytes*, not paths, so
a rename that does not change content does not invalidate a record and a content change with no rename
does — which is what "a push that changes only files no predicate selects does not invalidate that
binding's record" (AD-13) requires.

**`load_ledger` prohibition, made textually obvious (AD-6, Q5, REQ-C4).** The module imports exactly one
name from `validation_logic` — `fingerprint` — and does so with this comment, verbatim, immediately above
the import:

```python
# Import fingerprint() and NOTHING ELSE from validation_logic. load_ledger()'s
# dedup semantics (a recurring fingerprint with a resolving disposition is
# SILENCED so a one-shot gate can converge) are the exact inverse of what a
# convergence context needs, where recurrence means the fix failed. ADR-1643
# AD-6 + Q5 + REQ-C4 forbid applying them to any result produced through this
# primitive. When a caller feeds this document to compute_verdict(), it MUST
# pass os.devnull as ledger_path -- compute_verdict (in
# scripts/oversight/validation_logic.py) calls load_ledger() unconditionally,
# so the only way to honour the prohibition is at the call site.
# See §4.4 of the technical design.
```

Test **T2.8** greps the module source for `load_ledger` and fails if it appears outside that comment.

### 4.5 `--not-applicable` (AD-6, REQ-B3, AF-8)

A `not_applicable` record is written and stored **like any other record**. Absence of a record is never
`not_applicable`; it is a missing dimension, which is blocking. That closes AF-8's SKIP-as-exit-0
fail-open by construction — `run_gates.sh:113-134` today emits a byte-identical record for "skipped
because inapplicable" and "ran and passed", and this schema cannot.

`--not-applicable "<reason>"` emits, **launching no process at all**:
`applicability: "not_applicable"`, `applicability_reason: <reason>`, `outcome: "completed"`,
`outcome_detail: null`, `verdict: "approve"`, `findings: []`, `attacks: []`,
`invocation.model: null`, `invocation.exit_code: null`, `invocation.envelope: null`,
`invocation.duration_ms: 0`, and a full `input` block (the digest is still computed, minus
`input_file_sha256` which is `null`). Exit code **0**.

`verdict: "approve"` is correct and not a fail-open: `applicability` is the mandatory field that
distinguishes the two, and it is exactly the distinction REQ-B3 asks for and AF-8 found missing.
`--not-applicable` with `--input-file` is exit 2 (contradictory).

### 4.6 Round-trip obligations (the W2 gate)

These are **requirements on the implementation**, verified by tests T2.1–T2.7 (§9.2):

1. `compute_verdict([doc], os.devnull, strict_empty=True)` on a `completed` / `approve` / no-findings
   document ⟹ `{"verdict": "approve", "new_blocking_count": 0}`.
2. The same on a `completed` / `request_changes` document with one `high` finding ⟹
   `verdict == "request_changes"`, `blocking_count == 1`, `new_blocking_count == 1`.
3. The same on **any** `invocation_failed` document ⟹ `blocking_count >= 1`,
   `new_blocking_count >= 1`, `verdict == "request_changes"`. **This is AD-4's compatibility bridge and
   the test that proves it.**
4. `compute_verdict([], os.devnull, strict_empty=True)` ⟹ `verdict == "error"` — the #669 behaviour a
   caller gets if it loses the document entirely.
5. `fingerprint(doc["findings"][0])` is stable across two independently-produced documents with the same
   files and category, and **differs** when either changes.
6. `panel_logic.count_corroboration(doc["findings"][0])` returns `(1, ["claude"])` for a single-document
   finding — i.e. twelve dimensions do not inflate to twelve vendors.
7. `panel_logic.reconcile_membership([doc["findings"][0]], doc["findings"][0])` returns a non-empty
   membership list, proving `file` + `line` are present and typed as that reader expects.

---

## 5. W3 — observability (AD-8)

**Governing rule, carried forward verbatim from ADR-1604 AD-4: no decision in this design may read an
audit event or a token record.** If either write is silently lost, this mechanism degrades to *less
observable*, never to *not gating*. Both writes are therefore **non-fatal**: a failure is recorded in
`observability` and in `stderr`, and never changes `outcome`, `verdict`, or the exit code.

### 5.1 `token_tracker.py` wiring

**TD-D17 — invoked as a subprocess, never in-process.** TD-VF-8: `record()` writes to a **cwd-relative**
path and **prints to stdout**. In-process it would land the record wherever L2 happens to be and would
corrupt L2's one-JSON-object stdout contract.

```
[sys.executable, "<repo_root>/scripts/oversight/token_tracker.py", "record",
 "--vendor", "claude",
 "--stage", f"dimension:{dimension}",
 "--step", step or "",
 "--actual-prompt-tokens", str(prompt_tokens),
 "--actual-output-tokens", str(output_tokens)]
cwd=<repo_root>, stdout=PIPE, stderr=PIPE, timeout=15
```
- `claude` is already an accepted `--vendor` value (`token_tracker.py:249`). **No new mechanism**
  (REQ-A10, CLAUDE.md search-first).
- Token derivation from the envelope's `usage`, when present:
  `prompt_tokens = input_tokens + cache_creation_input_tokens + cache_read_input_tokens`;
  `output_tokens = output_tokens`. All four keys default to 0 if absent.
- When `usage` is absent **on a post-launch outcome** (`unparseable`, `timeout`, `crash` — a call that
  happened whose counts cannot be read), fall back to the existing char estimate: pass
  `--prompt-chars <len(input bytes)> --output-chars 0` instead. `token_tracker` already marks these
  `"estimated": true` (`:104`). **The fallback is post-launch-only** — it is never the representation of
  a call that did not happen (TD-D24).
- **When it is called, and when it is not: see TD-D24 below.** (This bullet previously read only
  "Never called for a `--not-applicable` document (nothing was spent)" — that wording named one exemption
  and left the **four** pre-flight classes of §3.7 to inference. Amendment B replaces it. The post-launch
  classes were never in doubt: the two bullets above already cover them.)

**TD-D24 — AMENDED 2026-09-18, Amendment B. The call rule, stated for every outcome class. Binding on
W3.** The original text named exactly one exemption and was silent on the four preflight-failure details
(`agent_unavailable`, `posture_invalid`, `not_authenticated`, `cli_unavailable`), none of which launches a
process either. The coder read the silence as *deliberate* — one named exemption, everything else records.
`code-reviewer` read it as an *omission* — the stated rationale ("nothing was spent") applies to all five
with equal force. **Both readings are supportable from the text, which is the defect.** The rule is:

> **`token_tracker.py record` is called if and only if the `claude` subprocess was launched** — that is,
> only on a path that reaches `run_capped` (§3.5). *Launching is the entire test.* Whether the launched
> process then succeeded, timed out, crashed, or emitted unparseable stdout is irrelevant — all of those
> spent tokens and all of them record. Whether the invocation was "attempted" in some looser sense is
> equally irrelevant — if no process was launched, there is no spend to record.

| Emission path | `outcome` / `outcome_detail` | Launched? | `token_tracker` | Audit record (§5.2) |
|---|---|---|---|---|
| `--not-applicable` (§4.5) | `not_applicable` | No | **Not called** | **Written** |
| P3/P4 | `invocation_failed` / `agent_unavailable` | No | **Not called** | **Written** |
| P5, V2–V14 (§3.6) | `invocation_failed` / `posture_invalid` | No | **Not called** | **Written** |
| P7 (pre-launch auth) | `invocation_failed` / `not_authenticated` | No | **Not called** | **Written** |
| P8 | `invocation_failed` / `cli_unavailable` | No | **Not called** | **Written** |
| post-launch | `completed` | Yes | **Called** — actual counts from `usage` | **Written** |
| post-launch | `invocation_failed` / any §3.7 detail: `timeout`, `unparseable`, `envelope_shape_violation`, `crash`, `permission_denied`, `refused`, `schema_violation`, `usage_limit`, `api_error`, `max_turns`, `refusal`, `terminal_reason:<value>`, **and `not_authenticated` reached via §3.7 step 4** | Yes | **Called** — `usage` when present, else the char-estimate fallback | **Written** |

The table is exhaustive over the emission paths this design defines. **A path that emits no document
(exit 1, exit 2 — §3.3) calls neither writer**, because there is no `observability` block to report the
result in; this includes `Popen` itself raising after P8 passed, which reaches `main()`'s top-level
handler as exit 1 and emits nothing. Any outcome class added to §3.7 later is classified by the
iff-rule above, not by extending this table — the table is the rule's current expansion, not its source.

**The two `not_authenticated` rows are different events and are decided by the test, not by the label.**
The P7 row is a pre-launch environment check that never contacts the API; the §3.7 step-4 row means the
CLI *ran*, reached the API and came back "not logged in" — that one spent tokens and must be recorded.
An implementation that keys on `outcome_detail` alone will get this pair wrong; key on "did we reach
`run_capped`".

**Why not-called, and not a nominal-zero record, for the five non-launching paths:**
1. **The char-estimate fallback is not a zero.** `token_tracker.estimate_tokens` is
   `max(1, round(chars / 4))`, and `_emit_preflight_document` independently reads and hashes
   `--input-file` for its `input_file_sha256` — so the byte length is in hand and a fallback record would
   be *proportional to the real input*. For the P7 and P8 rows this is guaranteed non-trivial, because
   P6 has already validated that the input file exists and is non-empty: a 48 KB review input records
   ~12,000 prompt tokens for a call that never happened. This is the concrete consequence the "one named
   exemption" reading did not account for, and it is the reason the ambiguity is not harmless.
2. **It would be recorded as `"estimated": true`, which is a claim about a real spend.** That flag means
   *"a call happened and we could not get exact counts"* — it is not a null marker. Such records count
   in `by_vendor["claude"]["calls"]`, add to the vendor total, add to the `dimension:<dimension>` stage
   bar (which is **normalised against the largest stage**, so one dimension failing preflight repeatedly
   can dominate the ranking of where tokens actually go), and raise the report's
   "⚠ Some counts are estimated" notice. `token_tracker.py`'s stated purpose is usage tracking and
   subscription impact; a phantom entry degrades exactly that.
3. **The design already implied this reading and should have said it.** The fallback bullet above
   introduces the char estimate for "an `unparseable` or `timeout` outcome" — both **post-launch**. The
   fallback was specified for *a call that happened whose counts we cannot read*, never for *a call that
   did not happen*.
4. **The diagnostic signal is not lost — it has a better home.** "This dimension keeps failing preflight"
   is a real thing to want to see, and §5.2 already delivers it: **one audit record per invocation,
   including every `invocation_failed` one**, carrying `outcome`, `outcome_detail`, `agent`, `dimension`,
   `binding`, `posture` and `input_digest`. That log is committed and durable; `token-usage.jsonl` lives
   under `.claudetmp/` and is ephemeral. Counting failures in the *spend* report would put a weaker copy
   of the signal in the wrong ledger — and would put it there in a unit (tokens) that is false.
5. **No zero-cost record form is available without a new mechanism.** `token_tracker.py`'s only
   zero-token path is `--review-event`, whose semantics are REQ-255-25/26/27 (a *review* outcome,
   excluded from token totals). Overloading it for preflight failures would need a new `--outcome` value
   and would redefine an existing contract — outside W3 and against REQ-A10 / CLAUDE.md search-first.

**Implementation note (contract, not code):** the existing `skip_token_tracker` parameter on the shared
observability writer is the correct seam and needs no new one — it must be **true on all five
non-launching emission paths** and false only on the post-launch path. The audit record is written on
every one of the seven rows regardless; `skip_token_tracker` must never gate it.

- **`observability.token_tracker_recorded` on a non-calling path is `false`.** It is a record of whether
  a record was written, not a claim that one was owed; `outcome`/`applicability` in the same document
  distinguish "not owed" from "owed and failed", so no third state is added. **No new field** (§4.2's
  schema is unchanged by Amendment B).
- Non-zero rc, timeout, or exception ⟹ `observability.token_tracker_recorded = false`, one stderr line,
  and nothing else.

### 5.2 The per-invocation audit record

Written through `audit_log.write_event(event, root=<repo_root>)` (TD-VF-9). One record per invocation,
including `--not-applicable` ones and including every `invocation_failed` one.

```json
{
  "event": "agent-invocation",
  "timestamp": "2026-09-14T21:49:11Z",
  "role": "worker",
  "agent": "security-reviewer",
  "dimension": "security",
  "binding": "core:security/code",
  "posture": "review-read-only",
  "outcome": "completed",
  "outcome_detail": null,
  "applicability": "applicable",
  "verdict": "request_changes",
  "findings_count": 1,
  "blocking_findings_count": 1,
  "model": "sonnet",
  "cli_version": "2.1.270",
  "duration_ms": 128412,
  "timed_out": false,
  "exit_code": 0,
  "num_turns": 7,
  "total_cost_usd": 0.1246,
  "input_digest": "e8b0…",
  "session_id": "5063fa1e-71d9-450c-b025-a0c8bcef9c24"
}
```
- **`timestamp` is present.** AF-10 records that the existing `subagent-model-resolved` hook records omit
  one; this record does not repeat that, and `write_event`'s `_resolve_ts` uses it for the shard path so
  the filename and the content derive from one instant.
- `role` is read from `os.environ.get("HOS_ROLE")` if set, else `null`. No new mechanism.
- **The record carries no prompt text, no agent output, no finding descriptions, and no file contents** —
  only counts and identity. The audit log is committed; review prose and diff excerpts are not audit data.
- `write_event` raising (a hash collision on differing bytes) is caught: `observability.audit_record` is
  set to `null`, one stderr line, and the document is still emitted.

### 5.3 Usage-limit surfacing toward #1446

TD-VF-11: the breaker at `bin/hos-cron:2023-2060` is **commented out**, and when live it greps the
**parent model session's** tee'd stdout. A script-launched L2 does not write to that stream, so W3 cannot
complete the wiring.

**What W3 builds:** on `outcome_detail == "usage_limit"`, L2 writes to **stderr**, as its own line:
```
agent_invoke: usage limit reached — nested invocation of agent '<agent>' stopped (terminal_reason=usage_limit)
```
The phrase `usage limit reached` is chosen to match the breaker's live grep verbatim, so a caller that
tees L2's stderr into `$_CLAUDE_OUTPUT_CAPTURE` gets the detection for free the day the breaker is
re-enabled. Additionally the audit record's `outcome_detail` carries `usage_limit`, and under Q1 the
`invocation_failed` outcome stops the merge — the correct conservative behaviour, independent of any
breaker.

**What W3 does not build:** any edit to `bin/hos-cron`, any re-enabling of the breaker, any new capture
file. **Routed as ESC-F.**

---

## 6. W4 — migrating the `claude -p` sites (AD-16)

### 6.1 `scripts/framework/validate_self.sh:236` — migrate first, highest value

Today (`:230-247`): prompt over stdin, `claude -p --model "$MODEL"
--exclude-dynamic-system-prompt-sections --no-session-persistence 2>/dev/null`, **no timeout at all**, and
on `rc != 0` or whitespace-only output it synthesizes
`{"reviewer":"opus-self","error":"claude invocation failed","findings":[],"verdict":"error","summary":"claude failed"}`.

After migration, `run_opus()` becomes:
```
bash bootstrap/invoke_agent.sh \
  --agent <self-review agent> \
  --posture review-read-only \
  --input-file "$prompt_file" \
  --dimension self-review \
  --lens self-review \
  --timeout "$AI_REVIEW_TIMEOUT" \
  --model "$MODEL"
```
- **The prompt moves from a shell variable to a file** — `--input-file` is the only input path
  (REQ-A3). Write it with `printf '%s' "$prompt" > "$tmp"`, which the script already does for
  `validate_scripts.sh`'s sibling path.
- **The synthesized error block is deleted.** Its job is now structural: an `invocation_failed` document
  carries `verdict: "error"` by AD-4's rule, and the downstream finalize step already inspects each
  block's own `verdict` (that is #1362's fix, `:240-247`). The document is a **superset** of the
  synthesized block, so the consumer needs no change. **This is the migration's proof.**
- The `sed`-based fence stripping at `:250` is deleted: L2's stdout is a bare JSON object.
- **AD-3 admits no bare-model path**, so `--model "$MODEL"` is an explicit override of a **named agent**,
  not a bare-model invocation. **TD-O1 (open, routed):** which shipped agent fills the `opus-self`
  adversarial self-review seat is not decided here — no agent file today describes that lens. Options are
  (a) a new `self-reviewer` agent file (protected surface, human-gated) or (b) reusing `code-reviewer`
  with the existing prompt. This is an architecture question about what the self-review lens *is*, and it
  is routed to `architect` as **ESC-J**, not chosen here.
- **Net effect independent of TD-O1:** the unbounded timeout on the framework-validation critical path
  (VF-3: *"a hang here hangs all of framework validation"*) is gone.

### 6.2 `scripts/framework/validate_scripts.sh:182` — migrate

Today: `printf '%s' "$prompt" | run_capped "$AI_REVIEW_TIMEOUT" "$out" claude -p --model "$MODEL"`.
After: the same `invoke_agent.sh` call as §6.1, writing to `$out` via `--output-file "$out"` so the
existing `rc`/tiered-lane logic at `:186-200` reads a file exactly as it does now. The tiered
required-vs-optional-lane behaviour (#669) is **unchanged** — it keys on the block's `verdict`, which the
document supplies.

### 6.3 Deleting the two `run_capped` copies (AD-5.3)

| File | `run_capped` call sites | After |
|---|---|---|
| `validate_scripts.sh:99-102` | `:182` claude, `:183` agy, `:184` codex | `:182` migrates to L3 (§6.2). `:183`/`:184` switch to `source scripts/oversight/run_with_retry.sh` + `with_timeout "$AI_REVIEW_TIMEOUT" agy … > "$out" 2>/dev/null`. `run_capped` + `_TIMEOUT_BIN` **deleted**. |
| `validate_agents.sh:151-160` | `:301` agy, `:381` codex — **no claude site** | Both switch to `with_timeout` with explicit `> "$out" 2>/dev/null` added at each call site. `run_capped` + `_TIMEOUT_BIN` **deleted**. |

**TD-F5 / ESC-D.** AD-5.3 frames `validate_agents.sh`'s deletion as happening *"when [it] migrate[s]
(AD-16)"*, but AD-16 gives that file nothing to migrate (TD-VF-2). Its `run_capped` deletion is a pure
refactor of two agy/codex call sites, it is **not free** (`run_capped` redirects stdout to a file and
discards stderr; `with_timeout` does neither, so each call site grows its own redirection), and it touches
the cross-vendor validation path that W4 otherwise leaves alone. I have designed it as above because AD-5
binds "the two private `run_capped` copies are deleted", but I am flagging that it belongs in its own
commit inside W4 with its own review, and asking the architect to confirm it belongs in W4 at all rather
than in a follow-up. Note that after both deletions the repo still has a third `_TIMEOUT_BIN` at
`bin/hos-cron:1754` — deliberately untouched, and named here so nobody "finishes the job".

### 6.4 `scripts/run_panel.sh:146-147` — **SPLIT OUT as W4b** (TD-F4, exercising AD-16's escape clause)

AD-16 says: *"If `technical-design` finds promoting the lens to an agent too large for W4, it must say so
and split it — **not** add a bare-model escape hatch to the primitive."* **I find it too large, and I am
splitting it. No escape hatch is added: AD-3's prohibition on bare-model invocation stands untouched.**

Grounds, all verified in §0.1 TD-VF-1:
1. It is **two** seats (`haiku` and `sonnet`), so it is two new `.claude/agents/*.md` files, each a
   protected-surface addition requiring human approval and each needing a lens definition that does not
   exist today. AD-16 describes it as one.
2. The panel's Claude seats are deliberately **different models** for decorrelation within the vendor;
   collapsing them onto one agent file, or giving each its own, is a panel-design question (`run_panel.sh`
   is the outer loop, non-goal 3 territory) and not an invocation-plumbing question.
3. The panel's output is consumed by `panel_logic`'s **prose-tolerant** `extract-json`. An AD-6 document
   is strictly better input, but changing what a panel seat emits changes the panel's input contract, and
   the panel is the mechanism the whole oversight system uses for cross-vendor decorrelation. That is a
   change that deserves its own slice and its own review, not a line in a migration.

**W4b's scope, stated so the split is actionable:** define the panel's Claude lens(es) as shipped agent
file(s); migrate `call_model`'s two `claude` branches to `invoke_agent.sh`; decide whether
`panel_logic.extract-json` keeps its prose tolerance for the (still prose-emitting) agy/codex seats while
the Claude seats go strict. Depends on W1. **Blocked on nothing except a decision on point 1.**

### 6.5 `bootstrap/setup_clis.sh:148` — EXEMPT, recorded in the file

Add exactly one comment line above it, citing the ADR so the exemption is visible where someone would
otherwise "fix" it:
```
# EXEMPT from ADR-1643 AD-16 / the bootstrap/invoke_agent.sh rule: this is the machine-bootstrap smoke
# test. It runs BEFORE the primitive's preconditions can hold — possibly with no HOS project checked out
# and certainly before any agent file is installed. Routing it through the primitive would make the smoke
# test depend on the thing it exists to prove works.
```

### 6.6 The CLAUDE.md row and the standing rule

Add one row to CLAUDE.md's "Canonical entry points by task" table:

| Task | Entry point |
|---|---|
| Invoking a shipped Claude agent as a subprocess and getting a machine-readable verdict | `bootstrap/invoke_agent.sh` |

and one sentence to the surrounding prose: **nothing else in the repository invokes `claude --agent`
directly** (the `setup_clis.sh` smoke test is the one recorded exemption, ADR-1643 AD-16).
`CLAUDE.md` is a protected surface — this edit is human-gated, which is correct.

---

## 7. W5 — the registry (AD-9, AD-11)

### 7.1 File layout

| Path | Owner | Installer disposition |
|---|---|---|
| `contract/dimensions/core.yaml` | CORE | `cp_framework_file` — always overwritten on upgrade |
| `contract/dimensions/pack-<name>.yaml` | PACK | copied from `packs/<name>/dimensions.yaml` for each **resolved** pack; always overwritten |
| `contract/dimensions/project.yaml` | PROJECT | **never written by the installer** (§7.7) |
| `contract/dimensions/project.yaml.template` | CORE | `cp_framework_file` — a commented example the consumer copies |
| `contract/dimensions/postures/*.{settings,hos}.json` | CORE | `cp_framework_file` |
| `packs/<name>/dimensions.yaml` | pack source | the pack's own file, mirroring `packs/<name>/<agent>.md` |

Merge order is **core → pack-\* (in the installer's resolved dependency-closure order) → project**,
mirroring the agent-file region order, but as **data**, not text.

### 7.2 Schema — `core.yaml`, literal and abridged only where marked `…`

```yaml
# contract/dimensions/core.yaml — CORE review dimensions. HOS-owned; overwritten on upgrade.
# ONLY this file may declare `entries:`. A PACK or PROJECT file containing an `entries:`
# key is a LOAD ERROR, not a merge (ADR-1643 AD-9).
schema: hos.dimension-registry
schema_version: 1
owner: core

entries:
  - id: code-review
    kind: judgment
    title: General code quality, design conformance, and idioms
  - id: security
    kind: judgment
    title: Security lens
  - id: privacy
    kind: judgment
    title: Privacy and data-handling lens
  - id: reliability
    kind: judgment
    title: Resilience to external-dependency failure
  - id: ops
    kind: judgment
    title: Telemetry-spec conformance
  - id: ui
    kind: judgment
    title: UI/UX conformance
  - id: a11y
    kind: judgment
    title: Accessibility
  - id: infra
    kind: judgment
    title: Infrastructure and deployment
  - id: lint
    kind: deterministic
    title: Linting
  - id: type-check
    kind: deterministic
    title: Static type checking
  - id: secret-scan
    kind: deterministic
    title: Secret detection
  - id: security-scan
    kind: deterministic
    title: Static security analysis
  - id: bash-check
    kind: deterministic
    title: Shell script checks
  - id: portability
    kind: deterministic
    title: Portability signals
  - id: template-refs
    kind: deterministic
    title: Template reference integrity
  - id: collection-integrity
    kind: deterministic
    title: Collection integrity
  - id: cross-vendor-review
    kind: deterministic
    title: Cross-vendor second review

bindings:
  # ── judgment bindings ─────────────────────────────────────────────────────
  - id: core:code-review/code
    entry: code-review
    kind: judgment
    agent: code-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/code-review.md
    predicate:
      include: ['\.py$', '\.sh$', '\.js$', '\.ts$', '\.jq$']
      exclude: ['^tests/', '/test_[^/]*\.py$', 'conftest\.py$', '/\.venv/']

  - id: core:security/code
    entry: security
    kind: judgment
    agent: security-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/security.md
    predicate:
      include: ['\.py$', '\.sh$', '\.js$', '\.ts$', '^\.github/workflows/']
      exclude: ['/\.venv/']

  - id: core:reliability/code          # TD-D12 — no predicate existed to migrate
    entry: reliability
    kind: judgment
    agent: reliability-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/reliability.md
    predicate:
      include: ['\.py$', '\.sh$', '\.js$', '\.ts$']
      exclude: ['^tests/', '/\.venv/']

  - id: core:ops/code                  # TD-D12 — no predicate existed to migrate
    entry: ops
    kind: judgment
    agent: ops-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/ops.md
    predicate:
      include: ['\.py$', '\.sh$', '\.js$', '\.ts$']
      exclude: ['^tests/', '/\.venv/']

  - id: core:privacy/governance
    entry: privacy
    kind: judgment
    agent: privacy-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/privacy.md
    predicate:
      include: ['^audit/', '^scripts/automation/lib/github\.py$', '\bsecret', '\btoken\b']

  - id: core:infra/deploy
    entry: infra
    kind: judgment
    agent: infra-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/infra.md
    predicate:
      include: ['^\.github/workflows/', '^bin/', '\.env\.example$']

  # `ui` and `a11y` have NO CORE binding — their surfaces are stack idioms.
  # They are declared as entries (CORE owns existence) and bound by packs.
  # A project with no UI pack installed gets a LOAD ERROR (rule L19) until it
  # either installs a pack that binds them or adds a project binding. See §7.8.

  # ── deterministic bindings ────────────────────────────────────────────────
  - id: core:lint/all
    entry: lint
    kind: deterministic
    tool: scripts/oversight/gates/lint_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }

  - id: core:type-check/all
    entry: type-check
    kind: deterministic
    tool: scripts/oversight/gates/type_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }

  # … secret-scan → gates/secret_scan.sh, security-scan → gates/security_scan.sh,
  #   bash-check → gates/bash_check.sh, portability → gates/portability_check.sh,
  #   template-refs → gates/template_refs_check.sh,
  #   collection-integrity → gates/collection_integrity.sh — same shape.

  - id: core:cross-vendor-review/all
    entry: cross-vendor-review
    kind: deterministic
    tool: scripts/run_second_review.sh
    timeout_seconds: 1800
    predicate: { include: ['.*'] }
```

`packs/django/dimensions.yaml` (literal, complete for the AD-11 rows assigned to it):
```yaml
schema: hos.dimension-registry
schema_version: 1
owner: pack
pack: django

bindings:
  - id: pack-django:code-review/app
    entry: code-review
    kind: judgment
    agent: code-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/code-review.md
    predicate:
      include: ['\.py$', 'manage\.py$']
      exclude: ['^tests/', '/test_[^/]*\.py$', '/migrations/', 'conftest\.py$', '^scripts/']

  - id: pack-django:code-review/migrations
    entry: code-review
    kind: judgment
    agent: code-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/code-review.md
    predicate: { include: ['/migrations/.*\.py$'] }

  - id: pack-django:ui/templates
    entry: ui
    kind: judgment
    agent: ui-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/ui.md
    predicate: { include: ['/templates/.*\.html$'] }

  - id: pack-django:a11y/templates
    entry: a11y
    kind: judgment
    agent: a11y-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/a11y.md
    predicate: { include: ['/templates/.*\.html$'] }

  - id: pack-django:privacy/pii-words
    entry: privacy
    kind: judgment
    agent: privacy-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/privacy.md
    predicate: { include: ['erasure', 'pii'] }

  - id: pack-django:deterministic/django-check
    entry: lint
    kind: deterministic
    tool: scripts/oversight/gates/django_check.sh
    timeout_seconds: 300
    predicate: { include: ['manage\.py$', '\.py$'] }
```

`packs/astro/dimensions.yaml` is the same shape with `\.astro$`, `^src/pages/`, `astro\.config\.`
predicates on `code-review`, `ui`, `a11y`, plus `astro_check.sh` on `lint`.

`contract/dimensions/project.yaml.template` (shipped, entirely commented, showing AD-11's PROJECT rows):
```yaml
schema: hos.dimension-registry
schema_version: 1
owner: project

# This file is YOURS. The installer never overwrites it and never creates it.
# It may declare bindings and suppressions. It may NOT declare `entries:` —
# only contract/dimensions/core.yaml may, and that is what stops a compliant
# configuration from being able to require nothing at all.
#
# bindings:
#   - id: project:privacy/app-modules      # AD-11: one application's module names
#     entry: privacy
#     kind: judgment
#     agent: privacy-reviewer
#     posture: review-read-only
#     timeout_seconds: 300
#     prompt_template: contract/dimensions/prompts/privacy.md
#     predicate: { include: ['accounts', 'booking'] }
#
#   - id: project:infra/deploy             # AD-11: one project's repo layout
#     entry: infra
#     kind: judgment
#     agent: infra-reviewer
#     posture: review-read-only
#     timeout_seconds: 300
#     prompt_template: contract/dimensions/prompts/infra.md
#     predicate:
#       include: ['^docker-compose\.yml$', '^Caddyfile$', '^scripts/backup\.sh$']
#
# suppress:
#   - binding: pack-django:privacy/pii-words
#     reason: >
#       This project stores no personal data; the pack's PII word list matches
#       our `pii_policy.md` docs and produces only false positives. Privacy is
#       still enforced through project:privacy/app-modules.
#
# You may suppress a PACK or PROJECT binding. You may NOT suppress a `core:`
# binding and you may NOT remove an entry — the entry keeps running and keeps
# blocking through its remaining bindings.
```

HOS's own `contract/dimensions/project.yaml` (not shipped) carries the one row AD-11 removes from the
consumer registry:
```yaml
schema: hos.dimension-registry
schema_version: 1
owner: project
bindings:
  - id: project:code-review/framework-validator
    entry: code-review
    kind: judgment
    agent: framework-validator
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/code-review.md
    predicate:
      include: ['^\.claude/agents/', '^scripts/framework/', '^bin/', '^bootstrap/',
                '^contract/', '^AGENTS\.md$', '^CLAUDE\.md$']
```
**AD-11's `framework-validator` row is honoured exactly**: it is removed from the consumer registry
(`core.yaml` does not name it) and lives only in the HOS repo's own PROJECT layer, because
`scripts/framework/consumer_agents.txt` does not ship it. If and when `hos-dev-pack` exists, the binding
moves to `pack-hos-dev.yaml` with no schema change.

### 7.3 Loader API — `scripts/automation/lib/dimension_registry.py`

> **Amended by Amendment C (2026-10-02, ADR-1644 SEAM-1).** The loader is schema-parametric: `load()` below
> keeps its signature but becomes the dimensions-kind wrapper over `load_registry(repo_root, schema, …)`;
> `packs=None` reads `contract/resolved-packs.txt`, **not** `config.sh`'s `PACK=` (TD-VF-16). See §C.2.7
> for the full amended API. Do not implement this section without Amendment C.

Pure module: **no `argparse`, no `__main__`, no `sys.argv` read, no network, no subprocess.**
AD-9 binds this path; the CLI is a separate L2 module (**TD-D18**), matching the
`merge_authority.py` (L1) / `merge_authority_cli.py` (L2) split the repo already uses.

```python
@dataclass(frozen=True)
class Entry:      id: str; kind: str; title: str; source: str

@dataclass(frozen=True)
class Predicate:  include: tuple[str, ...]; exclude: tuple[str, ...]

@dataclass(frozen=True)
class Binding:
    id: str; entry: str; kind: str; owner: str; source: str
    agent: str | None; tool: str | None; posture: str | None
    timeout_seconds: int; prompt_template: str | None; predicate: Predicate

@dataclass(frozen=True)
class ResolvedRegistry:
    entries: Mapping[str, Entry]
    bindings: Mapping[str, Binding]          # suppressed bindings are ABSENT
    suppressions: Mapping[str, str]          # binding id -> reason
    source_files: tuple[str, ...]
    digest: str                              # sha256 over to_json()'s canonical form

@dataclass(frozen=True)
class PlanItem:
    binding: Binding
    applicable: bool
    matched_files: tuple[str, ...]
    reason: str                              # ALWAYS non-empty, in both states

class RegistryError(Exception):
    code: str                                # machine-stable, e.g. "entries_outside_core"
    path: str | None

def load(repo_root: str | Path, *, packs: Sequence[str] | None = None) -> ResolvedRegistry: ...
def resolve_for_diff(reg: ResolvedRegistry, changed_files: Sequence[str]) -> list[PlanItem]: ...
def to_json(reg: ResolvedRegistry) -> dict: ...
```
`packs=None` means "read the resolved pack set from `scripts/framework/config.sh`'s `PACK=`"; an empty
sequence means "no packs". The loader **never** infers the pack set from which `pack-*.yaml` files happen
to be on disk — that inference is precisely what rule L20 exists to catch.

### 7.4 Loader failure rules — **every one of these exits non-zero and the sweep does not run**

AD-9: *"The loader fails closed, always."* Compare AF-5: a permissive loader would reproduce
`check_register_completeness`'s "nothing required, therefore nothing incomplete" exactly.

> **Amended by Amendment C (2026-10-02, ADR-1644 SEAM-1).** Each rule below is now classified kind-generic
> (enforced by the engine for every registered schema) or dimension-specific (enforced by the
> dimensions-kind handler). L3 is split, L12 is re-pointed at V1–V14 through a shared L1 module, and rules
> L22–L28 are added. See §C.2.6 for the table and the check order.

| # | Condition | `RegistryError.code` |
|---|---|---|
| L1 | `contract/dimensions/core.yaml` absent or unreadable | `core_missing` |
| L2 | `import yaml` fails (**must not** copy `config_resolver.py`'s tolerant idiom — TD-VF-10) | `yaml_unavailable` |
| L3 | Any file is not a YAML mapping, or `schema != "hos.dimension-registry"`, or `schema_version != 1` | `bad_schema` |
| L4 | `owner` absent, or not matching the filename (`core.yaml`→`core`; `pack-<n>.yaml`→`pack` **and** `pack == <n>`; `project.yaml`→`project`) | `owner_mismatch` |
| L5 | An `entries:` key appears in any file other than `core.yaml` | `entries_outside_core` |
| L6 | Duplicate entry id, or duplicate binding id, across all files | `duplicate_id` |
| L7 | A binding id whose namespace prefix ≠ its owner (`core:`, `pack-<n>:`, `project:`) | `binding_namespace` |
| L8 | A binding referencing an unknown entry | `unknown_entry` |
| L9 | A binding whose `kind` ≠ its entry's `kind` | `kind_mismatch` |
| L10 | `kind: judgment` and `<root>/.claude/agents/<agent>.md` is absent | `agent_missing` |
| L11 | `kind: deterministic` and `tool` is absent, or the path does not exist, or is not executable | `tool_missing` |
| L12 | `kind: judgment` and `posture` is absent, or either posture file is absent, or the sidecar fails §3.6's V4–V11 | `posture_missing` |
| L13 | `timeout_seconds` absent, not an int, `< 30`, or `> 1800` | `bad_timeout` |
| L14 | `predicate` absent, `include` absent/empty, or any pattern fails `re.compile` | `bad_predicate` |
| L15 | `suppress` entry naming an unknown binding id | `suppress_unknown` |
| L16 | `suppress` entry naming a binding whose id starts with `core:` | `suppress_core` |
| L17 | `suppress` entry with an absent, empty, or whitespace-only `reason` | `suppress_no_reason` |
| L18 | A `suppress:` key in any file other than `project.yaml` | `suppress_outside_project` |
| L19 | An entry with **zero unsuppressed bindings** after the merge | `entry_unbound` |
| L20 | A `pack-<n>.yaml` on disk whose `<n>` is not in the resolved pack set (a **stale** pack file left behind by an upgrade that dropped a pack — TD-VF-5: `--prune` is opt-in, so this WILL happen) | `stale_pack_file` |
| L21 | `kind: judgment` and `prompt_template` is absent, or the referenced file does not exist | `prompt_missing` |

**Not an error:** a pack in the resolved set with no `pack-<n>.yaml` (a pack may legitimately contribute
no bindings — most do not); an absent `project.yaml` (the PROJECT layer is optional and its absence means
"no project bindings, no suppressions", which cannot loosen anything).

**The ownership ratchet, stated as it must be implemented.** Only CORE declares entries (L5). A PROJECT may
suppress a **binding**, never an entry (L16, and there is no `suppress_entry` key in the grammar at all).
Suppression requires the binding id and a non-empty reason (L17). `contract/**` is already the first-class
protected surface (`protected_surfaces.txt` line 2 → CODEOWNERS), so ESC-5's *"that suppression is a
protected-surface edit under `contract/**` with a recorded reason"* is enforced by an **existing human
gate with no new mechanism** — the `reason` field *is* the recorded reason. The entry keeps running and
keeps blocking through its remaining bindings, so the required-to-do-nothing trap stays closed.

### 7.5 `resolve_for_diff` — the applicability decision (AD-6, AD-11)

For each unsuppressed binding, over the changed-file list:
1. `matched = [f for f in changed_files if any(re.search(p, f) for p in include)
              and not any(re.search(p, f) for p in exclude)]` — `re.search`, not `re.match`, because the
   migrated patterns are the script's `grep -E` semantics (`categorize():63-115`).
2. `matched` non-empty ⟹ `PlanItem(applicable=True, matched_files=tuple(sorted(matched)),
   reason=f"binding {id} matched {len(matched)} changed file(s)")`.
3. `matched` empty ⟹ `PlanItem(applicable=False, matched_files=(),
   reason=f"binding {id} matched no changed file")`.

**There is no third output.** AF-6.3's discretionary
`|| echo "privacy-reviewer (check if PII-relevant)"` does not survive the migration: the predicate either
matches, in which case the dimension runs, or it does not, in which case a `not_applicable` record with a
stated reason is written (§4.5). Nothing is left for a reader to decide. **`reason` is never empty in
either branch** — that is what makes AD-6's "mandatory machine-readable reason" real rather than
aspirational.

**The agent has no authority here.** `resolve_for_diff` is the only producer of `applicability`, and §4.3
rule 5 makes an agent supplying the field a `schema_violation`.

### 7.6 The AD-11 CORE/PACK/PROJECT split, and two rows the ADR's table does not have

AD-11's table is implemented exactly as written (§7.2's three files are its three columns). Two additions
are mine because TD-VF-7 found them missing from the migration source:

**TD-D12 — `reliability` and `ops` get CORE bindings I wrote.** `run_post_change_sweep.sh` routes neither
reviewer in any branch, so there was no predicate to migrate. I bind both to "any non-test source file",
which is the honest reading of what those lenses look at (an external-dependency failure path and a
telemetry emission can both live in any code file). This is a **guess about scope, not about the lens**
(ADR non-goal 1 is untouched: I have changed nothing about what either reviewer looks for), and W6's
observation-only slice is where its cost and signal get measured. Flagged as mine so a reviewer can
challenge the predicate rather than assume it was inherited.

**TD-D13 — Tracks 3/4/5 (`unit-test`, `ux-designer`→`ui-reviewer`, `pm-agent`) are excluded from the
registry.** They are **build-side** roles, not gating review dimensions: `unit-test` authors tests,
`ux-designer` produces `UX-DESIGN-READINESS.md`, `pm-agent` owns requirements. AD-10's `kind: judgment`
entries are the ones the overseer reruns over a finished diff, and none of these three produces a verdict
on a diff. They belong to #1644's stage graph, whose keys (`stage_label`, `blocked_by`, `next_stage_on`)
AD-12 explicitly reserves. Recording the exclusion so their disappearance from the sweep's output is a
decision, not an omission.

**`ui` and `a11y` have no CORE binding by design**, and this interacts with rule L19 — see §7.8.

### 7.7 Installer changes (AF-9 — the genuinely new structure)

Verified against `hos_install.sh`'s actual implementation, not by analogy (TD-VF-5).

> **Amended by Amendment C (2026-10-02).** Items 1, 2 and 4 are revised in §C.2.11: the eight prompt files
> also ship, pack-data copying is table-driven per registry kind and runs once outside the per-agent loop,
> the installer writes `contract/resolved-packs.txt`, and manifest rows for generated files are emitted
> explicitly.

1. **`core.yaml`, `project.yaml.template`, and the four posture files** are added to
   `scripts/framework/framework_consumer_files.txt`. That single edit gives overwrite-on-upgrade (the
   copy loop at `:1906-1917` uses `cp_framework_file`) **and** `.hos-manifest` tracking (`:2206-2225`
   reads the same list). **No new installer code.**
2. **`pack-<name>.yaml` requires new code** — the pack mechanism has never copied a non-agent file
   (`:1489-1519` is keyed on `packs/<pack>/<agent>.md` and reaches nothing else). Add, inside the pack
   phase after `_resolved_packs` is computed:
   - for each `_pk` in `_resolved_packs`, if `$(_resolve_pack_dir "$_pk")/dimensions.yaml` exists,
     `cp_framework_file` it to `$TARGET_REPO/contract/dimensions/pack-${_pk}.yaml`;
   - **then delete** every `$TARGET_REPO/contract/dimensions/pack-*.yaml` whose `<name>` is not in
     `_resolved_packs`. This is the upgrade path for a project that drops a pack. `--dry-run` must print
     the deletion rather than perform it, like every other `run`-wrapped action.
   - each copied `pack-<name>.yaml` is appended to the manifest rows so `.hos-manifest`'s
     removed-file detection also sees it.
3. **`project.yaml` is never created by the installer.** Not `cp_file`, not `cp_framework_file`, not a
   guarded copy. Only `project.yaml.template` ships. **TD-D19:** an absent PROJECT layer is unambiguous
   ("no project bindings, no suppressions") and cannot loosen anything; a template *copied into place*
   would be a live, consumer-owned file the consumer never chose to author, and the step-manifest
   precedent (`:2116-2122`) already produces exactly that confusion — `check_register_completeness`
   returns "nothing required" against a manifest nobody wrote (AF-5).
4. **Even with (2), the loader must still enforce L20.** `--prune` is opt-in and the deletion in (2) only
   runs when the installer runs. A hand-copied or branch-switched tree can still carry a stale
   `pack-*.yaml`. Belt and braces, and the loader's is the one that fails closed.
5. **`--squash` interaction:** `contract/dimensions/*.yaml` are **WHOLE** files, not region-composed
   files, so they never appear in the region-drift classification `--squash` exists for. `--squash` has
   no effect on them beyond what `cp_framework_file` already does. Stated because AD-9 asked for it to be
   verified rather than assumed: **verified — there is no interaction.**

### 7.8 `ui`/`a11y` and rule L19 — a designed consequence, stated plainly (TD-D20)

`ui` and `a11y` are CORE **entries** with **no CORE binding** (their surfaces — `templates/*.html`,
`*.astro`, `src/pages/` — are stack idioms, per AD-11). Rule L19 says an entry with zero unsuppressed
bindings is a load error. So a project with **no** UI-bearing pack installed gets `entry_unbound` and
**the sweep does not run**. That is the correct ratchet behaviour (a configuration must not be able to
make a required dimension vanish) but it is a **usability cliff**: HOS itself has no UI pack, so HOS's own
registry would fail to load on day one.

Resolution, and it is mine: **HOS's own `contract/dimensions/project.yaml` carries explicit suppressions
for `ui` and `a11y`'s pack bindings** — except there are none to suppress, which is the point. So instead:
`core.yaml` ships a **CORE fallback binding** for each, with a predicate that matches nothing HOS has and
everything a generic UI project would:

```yaml
  - id: core:ui/markup
    entry: ui
    kind: judgment
    agent: ui-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/ui.md
    predicate: { include: ['\.html$', '\.htm$', '\.css$', '\.scss$', '\.svelte$', '\.vue$', '\.jsx$', '\.tsx$'] }
  - id: core:a11y/markup
    entry: a11y
    kind: judgment
    agent: a11y-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/a11y.md
    predicate: { include: ['\.html$', '\.htm$', '\.svelte$', '\.vue$', '\.jsx$', '\.tsx$'] }
```
L19 is satisfied for every install; a repo with no markup gets `not_applicable` records with a stated
reason (which is exactly what §4.5 exists for); and packs still add their own, more specific bindings
alongside. **AD-9's "every entry ships with at least one CORE binding" is honoured literally**, which is
what the narrow-only rule requires — I had drifted from it in §7.2's first draft of this file and the
correction is recorded here rather than silently applied.

### 7.9 `run_post_change_sweep.sh` reduced to `--explain` (AD-11)

**Rewritten, not deleted** — its human-facing value is real (AD-11), but it is no longer a source of truth.

> **Amended by Amendment C (2026-10-02).** The usage line, the exit-1 meaning, and the interpreter are
> superseded by §C.2.10 (TD-D29/TD-D30). The script keeps today's input grammar and drops
> `--framework-only`.

```
Usage: run_post_change_sweep.sh [--base <ref>] [--json] [--framework-only]
```
- Computes the changed-file list exactly as it does today (`git diff --name-only`).
- Calls `dimension_registry_cli.py plan --base <ref>` and renders **the resolved registry's plan**:
  per entry, which bindings fire, which files each matched, and for each non-firing binding the
  `reason` string. `--json` emits `resolve_for_diff`'s output directly.
- **Exit codes:** `0` explained; `1` loader failure (the `RegistryError.code` and path on stderr);
  `2` usage error.
- **Its last two lines are deleted.** `echo "To run: invoke the post-change-sweep agent…"` does not
  survive: this script no longer hands execution to anyone's discretion.
- `categorize()`, `declare_domain`/`add_to_domain`/`get_domain`, the eight domain variables, and the
  `Track 1..5` printing block are **all deleted**. One invocation site, one source of truth (D41).
- The CLAUDE.md canonical-entry-point row for it changes from *"dispatches the right review agents"* to
  *"explain which review dimensions apply to a diff"*. (Protected surface; human-gated; same PR as §6.6.)
- **`.claude/agents/post-change-sweep.md` is NOT edited in W5.** Agent-definition edits are
  protected-surface and belong with W7, when the sweep actually executes. Routed as ESC-K so the
  now-stale agent is not simply forgotten.

### 7.10 `dimension_registry_cli.py` (L2)

```
python3 scripts/automation/dimension_registry_cli.py resolve [--pack <n> ...]   # resolved registry as JSON
python3 scripts/automation/dimension_registry_cli.py plan --base <ref> [--changed-file <p> ...]
```
Exit vocabulary is #1641's, unchanged: `0` answered / `1` loader or operational failure / `2` usage.
Exactly one JSON object on stdout in all `0` cases. On `1`, one line on stderr of the form
`dimension_registry: <RegistryError.code>: <message> [<path>]` — machine-stable, so a caller can branch
on the code without parsing prose.

**TD-D21 — the resolved registry is NOT committed.** AD-9 asks for a check that resolution is stable and
that every entry resolves at least one binding. Committing `resolved.json` would create a second source of
truth that can drift, and it would land inside `contract/**` where every regeneration becomes a
human-gated edit. Instead: stability is **test T5.9** (two `load()` calls produce byte-identical
`to_json()`), and "every entry resolves at least one binding" is **loader rule L19**, which fails closed
at load time rather than at CI time. The artifact AD-9 wants for a PR is produced on demand by
`resolve`, and W7 attaches it.

---

## 8. Cross-cutting: the complete error contract

One table, so a coder never has to infer which surface owns a failure.

| Failure | Surface | Exit | Document? | `outcome_detail` |
|---|---|---|---|---|
| Unknown/forbidden flag | L2 invoke | 2 | no | — |
| `--agent` name grammar | L2 invoke | 2 | no | — |
| `--posture` not in `KNOWN_POSTURES` | L2 invoke | 2 | no | — |
| `--timeout`/`--grace` out of range | L2 invoke | 2 | no | — |
| `--input-file` missing/empty/not UTF-8 | L2 invoke | 2 | no | — |
| `--not-applicable` + `--input-file` | L2 invoke | 2 | no | — |
| Repo root unresolvable | L2 invoke | 1 | no | — |
| `--output-file` unwritable | L2 invoke | 1 | no | — |
| Agent file absent/empty/name mismatch | L2 invoke | 0 | yes | `agent_unavailable` |
| Posture files absent or failing V2–V11 | L2 invoke | 0 | yes | `posture_invalid` |
| `--require-env-auth` and no env token | L2 invoke | 0 | yes | `not_authenticated` |
| `claude` not on PATH | L2 invoke | 0 | yes | `cli_unavailable` |
| Our cap fired | L2 invoke | 0 | yes | `timeout` |
| stdout empty / not one JSON object | L2 invoke | 0 | yes | `unparseable` |
| Decision field of the wrong type/shape | L2 invoke | 0 | yes | `envelope_shape_violation` |
| Not-logged-in (post hoc) | L2 invoke | 0 | yes | `not_authenticated` |
| `terminal_reason` ∉ allowlist | L2 invoke | 0 | yes | that value, or `terminal_reason:<v>` |
| `is_error` truthy | L2 invoke | 0 | yes | `crash` |
| `permission_denials` non-empty | L2 invoke | 0 | yes | `permission_denied` |
| `subagent_stats.refused` non-zero | L2 invoke | 0 | yes | `refused` |
| rc != 0, nothing more specific | L2 invoke | 0 | yes | `crash` |
| Agent payload fails strict parse | L2 invoke | 0 | yes | `schema_violation` |
| `token_tracker` / audit write failed | L2 invoke | unchanged | yes | unchanged; `observability.*` records it |
| Any loader rule L1–L21 | L2 registry | 1 | no (one stderr line) | — |
| No interpreter resolvable (all three TD-D22 rungs miss) | L3 | 1 | no (one stderr line, contains `python3`) | — |
| `INVOKE_AGENT_PYTHON` set but not executable | L3 | 1 | no (one stderr line) | — |
| `python3` absent from `PATH` but the oversight venv is present | L3 | **as normal** | **yes** — rung 2 resolves; `PATH` is irrelevant to an absolute interpreter path | — |
| A module-level third-party import of L2 fails (P0 — e.g. PyYAML absent on a consumer host) | L2 invoke | 1 | no (one stderr line naming `sys.executable`; **never a traceback**) | — |

**Never** is a review's pass/fail an exit code. It is the `verdict` field, read by the caller.

---

## 9. Tests — the obligations per slice

Test files: `tests/automation/test_agent_invoke_cli.py`, `tests/automation/test_agent_invoke_wrapper.py`,
`tests/automation/test_dimension_registry.py`, `tests/automation/test_dimension_registry_cli.py`.
All drive `main(argv=[...], repo_root=tmp_path)` in-process except the wrapper tests, which shell out.

### 9.1 W1 — **a failing-closed test for every row of AD-4's table** (the slice gate)

Fixtures are synthetic envelopes built from probe A's real shape, so a CLI field rename breaks a test
rather than a merge. Fixture **F-VF1** is probe R's envelope **verbatim**.

| # | Test | Asserts |
|---|---|---|
| T1.1 | C1 — `timed_out=True`, any stdout | `outcome=invocation_failed`, detail `timeout`, `verdict=error`, exit 0 |
| T1.2 | C2 — stdout `""` | detail `unparseable` |
| T1.3 | C2 — stdout `"{...}{...}"` (two objects) | detail `unparseable` |
| T1.4 | C2 — stdout `"notes\n{...}"` (prose-prefixed) | detail `unparseable` — **the prose-tolerant reader is NOT inherited** |
| T1.5 | **C3/C4 with fixture F-VF1 — probe R verbatim: `is_error:true`, `subtype:"success"`, `terminal_reason:"api_error"`, `api_error_status:404`, rc 1** | `outcome=invocation_failed`, detail `api_error`, `verdict=error`. **This is VF-1's exact shape and it is the single most important test in the slice.** |
| T1.6 | C4 — `terminal_reason:"usage_limit"` | detail `usage_limit`; **and** the `usage limit reached` line appears on stderr (§5.3) |
| T1.7 | C4 — `terminal_reason:"refusal"` | detail `refusal` |
| T1.8 | C4 — `terminal_reason:"max_turns"` | detail `max_turns` |
| T1.9 | C4 — `terminal_reason:"some_future_reason_nobody_wrote"`, everything else clean, rc 0 | `invocation_failed`, detail `terminal_reason:some_future_reason_nobody_wrote`. **This is the allowlist-not-denylist test: a future CLI version fails closed by default.** |
| T1.10 | C4 — `terminal_reason:"api_error"` with `result:"Not logged in · Please run /login"` | detail `not_authenticated`, not `api_error` |
| T1.11 | C5 — `permission_denials:[{...}]`, `rc 0`, `is_error:false`, `terminal_reason:"completed"` (**probe K's real shape**) | `invocation_failed`, detail `permission_denied`. Every other signal says clean. |
| T1.12 | **C6 — `subagent_stats.refused = {"depth_limit":0,"concurrency_limit":0,"budget":0}` (probe A's real shape)** | `outcome=completed`. **A naive `refused != 0` comparison fails this test, which is the point (TD-F1).** |
| T1.13 | C6 — `refused = {"depth_limit":0,"concurrency_limit":2,"budget":0}` | `invocation_failed`, detail `refused` |
| T1.14 | C6 — `refused = 0` (scalar, hypothetical older shape) | `completed` |
| T1.15 | C6 — `refused = "some string"` | detail `envelope_shape_violation` |
| T1.16 | C6 — `subagent_stats` absent entirely | `completed` (AD-4: absence is harmless) |
| T1.17 | C7 — rc 2, envelope otherwise clean | detail `crash` |
| T1.18 | C8 — `result` is valid JSON but `verdict:"maybe"` | detail `schema_violation` |
| T1.19 | C8 — `result` has a finding with no `files` and no `file` | detail `schema_violation` |
| T1.20 | C8 — `result` contains an `applicability` key | detail `schema_violation` (§4.3 rule 5 — no agent self-exemption) |
| T1.21 | C8 — `result` wrapped in exactly one ```` ```json ```` fence | `completed`, fence stripped |
| T1.22 | C8 — `result` wrapped in **two** nested fences | `schema_violation` |
| T1.23 | **`subtype` is never read**: a clean envelope with `subtype:"failure"` | `completed`. Guards against someone "adding it for completeness". |
| T1.24 | An unknown **top-level** envelope field (`"brand_new_telemetry":1`) | `completed`, field listed in `invocation.envelope_unknown_fields` (TD-F2's interim contract; **this test changes if ESC-B is ruled the other way**) |

**Preconditions and posture (T1.25–T1.40):** agent file absent ⟹ `agent_unavailable`; agent file empty
⟹ `agent_unavailable`; frontmatter `name:` mismatch ⟹ `agent_unavailable`; `--agent general-purpose`
(a real CLI built-in, probe N) ⟹ `agent_unavailable`, **proving the built-in cannot be reached**;
`--agents '{...}'` ⟹ exit 2 naming the flag; `--permission-mode bypassPermissions` ⟹ exit 2;
`--output-format text` ⟹ exit 2; `--settings x` ⟹ exit 2; posture settings file **malformed JSON**
⟹ `posture_invalid` **and no subprocess is launched** (assert with a `Popen` spy — this is probe P's
fail-open, closed); posture sidecar missing `disableBypassPermissionsMode` ⟹ `posture_invalid`;
`allowed_tools ∩ disallowed_tools ≠ ∅` ⟹ `posture_invalid`; a `disallowed_tools` entry absent from
`permissions.deny` ⟹ `posture_invalid`; `--posture no-such` ⟹ exit 2; `--timeout 0` ⟹ exit 2;
`--timeout 5` ⟹ exit 2; `--timeout 3600` ⟹ exit 2; `--require-env-auth` with no env token ⟹
`not_authenticated` **and no subprocess**.

**Launch contract (T1.41–T1.46):** with a `Popen` spy, assert the argv contains `--print`,
`--output-format json`, `--agent <name>`, `--settings <abs posture path>`, `--permission-mode <sidecar
value>`, `--permission-prompts none`, `--allowed-tools`, `--disallowed-tools`; assert `--model` is
**absent** when `--model` was not passed (AD-3: frontmatter governs) and present when it was; assert
`cwd == repo_root` (#1126); assert `start_new_session=True`; assert the input bytes were written to stdin
and stdin closed, and that the prompt appears **nowhere** in argv; assert stdout and stderr are separate
pipes.

**Timeout and reaping (T1.47–T1.49):** a fake child that ignores `SIGTERM` is `SIGKILL`ed after the grace
period and `os.killpg` is called with the child's **process group**, not its pid; a child that spawns a
grandchild leaves no live grandchild after the cap fires; `invocation.stdout_partial` is populated and
truncated to 4 KiB on a timeout.

**Interpreter fitness (T1.50–T1.56, Amendment A) — the regression fence for the #1720 defect class.**
The defect was *not* "CI lacked a package"; it was **an entry point that ran under an interpreter unfit
to run it, and said so only by traceback**. Tests must pin the class, not the instance.

| # | Test | Asserts | File |
|---|---|---|---|
| T1.50 | `PATH` contains **no** `python3`, no override, oversight venv present (the real checkout) | exit **0** and one JSON document — rung 2 resolves an absolute path and `PATH` is irrelevant. **This replaces the current `test_python3_missing_is_exit_1_with_stderr_message` expectation**, which becomes wrong under TD-D22 | wrapper |
| T1.51 | `INVOKE_AGENT_PYTHON` = a non-existent / non-executable path | exit **1**, `stdout == ""`, exactly one stderr line naming the variable | wrapper |
| T1.52 | **`INVOKE_AGENT_PYTHON` = an interpreter without PyYAML** — built in `tmp_path` via `python3 -m venv --without-pip` (skip if venv creation is unavailable) | exit **1**; `stdout == ""` (no document, no partial JSON); stderr is **one** line containing `PyYAML`, the interpreter path, and `ensure_venv.sh`; stderr contains **no** `Traceback`; the exit code is neither 0 nor 2 nor 3. **This is the consumer-host contract (§3.9) executed, and the test that would have caught #1720** | wrapper |
| T1.53 | **Source-level:** the yaml-unavailability sentinel (`_YAML_IMPORT_ERROR` / `yaml is None`) appears in `agent_invoke_cli.py` **only** in the module import block and in `main()`'s P0; `_parse_frontmatter` contains no `yaml is None` branch | fails otherwise. Same idiom as T2.8's `load_ledger` fence — it is what stops P0 decaying into a fail-open | cli |
| T1.54 | **Source-level, generalised:** every module-level `import`/`from` in `agent_invoke_cli.py` whose top-level name is not in `sys.stdlib_module_names` and is not a first-party `scripts.*` path is declared in `scripts/oversight/requirements.txt` | fails otherwise — the *next* third-party import inherits the precondition instead of re-learning it | cli |
| T1.55 | `.github/workflows/tests.yml` contains no PyYAML/`requirements.txt` install into the `setup-python` environment (only `ensure_venv.sh`) | fails otherwise — TD-D22 rejected alternative (a): satisfying the dependency in the system interpreter would make the bare-`python3` path green and mask this class | workflow/source |
| T1.56 | `main()` with `_YAML_IMPORT_ERROR` monkeypatched to a fake `ImportError`, run three ways: valid argv, **invalid argv** (a forbidden flag), and `--not-applicable` | all three ⟹ exit **1**, one `agent_invoke: ` stderr line, **no** document on any of them. Proves P0 precedes argparse (1 dominates 2) and that no path emits a record under an unfit interpreter | cli |

Two existing tests change rather than being added, and a reviewer must see both as *expectation* changes:
**T1.50** (above) and the byte-identity test, which currently shells the wrapper *and* a bare `python3`
side by side — two different interpreters, which is why it was a second casualty of #1720. It must pin
**both** sides to one interpreter: the direct side runs `sys.executable`, the wrapper side runs with
`INVOKE_AGENT_PYTHON` set to `sys.executable`. Only then is it testing L3's passthrough rather than the
host's `PATH`.

### 9.2 W2 — the result document

| # | Test | Asserts |
|---|---|---|
| T2.1–T2.4 | §4.6 obligations 1–4, driving the real `validation_logic.compute_verdict` | as stated there |
| T2.5 | §4.6 obligation 5 — `fingerprint` stability | equal for equal (files, category); different when either changes |
| T2.6 | **An `invocation_failed` document raises `new_blocking_count`** | `compute_verdict([doc], os.devnull, strict_empty=True)["new_blocking_count"] >= 1`. **This is the W2 slice gate.** |
| T2.7 | §4.6 obligations 6–7 — `panel_logic.count_corroboration` and `reconcile_membership` | `(1, ["claude"])`; non-empty membership |
| T2.8 | **Source-level:** `agent_invoke_cli.py`'s text contains `load_ledger` only inside the §4.4 comment block | fails otherwise |
| T2.9 | `compute_verdict([doc], <a ledger file that WOULD silence the finding>)` vs `os.devnull` | the two differ — proving the `os.devnull` requirement is load-bearing and not cosmetic |
| T2.10 | `--not-applicable` | exit 0; `applicability=not_applicable`; non-empty `applicability_reason`; `verdict=approve`; `invocation.model is None`; **no subprocess launched** (spy) |
| T2.11 | A `not_applicable` document and a `completed`/`approve` document are **not** byte-equal after removing timestamps | the AF-8 distinction is real in the record |
| T2.12 | `--not-applicable` + `--input-file` | exit 2 |
| T2.13 | Every document, every outcome, validates against the schema | one shared `assert_conforms(doc)` helper used by every test in T1 and T2 |
| T2.14 | `--output-file` content is **byte-identical** to stdout | TD-D2 |
| T2.15 | `input_digest` determinism and sensitivity | identical inputs ⟹ identical digest; changing the agent file's bytes, the posture bytes, the input file's bytes, or any matched file's bytes each ⟹ a different digest; changing only `--head-sha` ⟹ a different digest; a W1-shaped manifest never collides with a W7-shaped one |

### 9.3 W3 — observability

T3.1 `token_tracker` is invoked as a subprocess with `cwd=repo_root` and its stdout captured (spy).
T3.2 `--actual-prompt-tokens`/`--actual-output-tokens` are derived from `usage` per §5.1's formula.
T3.3 A missing `usage` **on a post-launch outcome** (`timeout`, `unparseable`, `crash`) falls back to
`--prompt-chars`. (Amendment B: the fallback is post-launch-only — see T3.10.)
T3.4 A `token_tracker` non-zero exit sets `observability.token_tracker_recorded=false` and **does not**
change `outcome`, `verdict`, or the exit code.
T3.5 One `audit_log.write_event` call per invocation, with `root=repo_root` and a `timestamp` field.
T3.6 The audit record contains **no** prompt text, no finding `description`, and no file contents
(assert by scanning the serialized record for a canary string planted in the input file and in a finding).
T3.7 `write_event` raising sets `observability.audit_record=None` and does not change the exit code.
T3.8 A `not_applicable` document still writes an audit record and does **not** call `token_tracker`.
T3.10 **(Amendment B, TD-D24.)** **One test per preflight-failure outcome** — `agent_unavailable`,
`posture_invalid`, `not_authenticated` (P7), `cli_unavailable` — each asserting, with a real non-empty
`--input-file` present on disk, that **no `token_tracker` subprocess is spawned at all** (spy on the
subprocess seam; asserting "recorded zero tokens" would pass against the defect this closes, since the
char estimate is `max(1, …)` and never zero), **and** that the audit record for the same invocation *is*
written with the matching `outcome_detail`. Paired with T3.11: a **post-launch** `not_authenticated`
(reached via §3.7 step 4, envelope `terminal_reason: "api_error"` + `/not logged in/i`) **does** call
`token_tracker` — the two `not_authenticated` rows must be pinned as different events, or an
implementation keyed on `outcome_detail` alone passes T3.10 and is still wrong.
T3.9 `terminal_reason:"usage_limit"` emits the `usage limit reached` stderr line **matching
`bin/hos-cron`'s grep pattern `usage limit reached|hit your (session|weekly|opus) limit` verbatim** — the
test asserts against the pattern, not against a copy of the phrase, so the two cannot drift.

### 9.4 W4 — the migrations

T4.1 `grep -rn 'claude -p\|claude --print'` over `scripts/` + `bootstrap/` + `bin/` returns **exactly**
`bootstrap/setup_clis.sh` and `scripts/run_panel.sh` (the latter until W4b lands) — a repo-wide
source test, the mechanical form of AD-16's standing rule.
T4.2 `grep -rn 'run_capped'` over the repo returns nothing.
T4.3 `validate_self.sh` contains no synthesized `"verdict":"error"` literal.
T4.4 `validate_scripts.sh`'s tiered required/optional lane behaviour is unchanged (existing tests stay
green; if none exists, one is added asserting a required-lane `error` verdict produces a blocking finding
and an optional-lane one does not).
T4.5 `setup_clis.sh` carries the exemption comment citing ADR-1643.
T4.6 CLAUDE.md contains the `bootstrap/invoke_agent.sh` row.

### 9.5 W5 — the registry

T5.1–T5.21: **one test per loader rule L1–L21**, each asserting the exact `RegistryError.code`.
T5.22 A valid three-layer fixture (core + pack-django + project) resolves to the expected binding set.
T5.23 A project with **both** `django` and `astro` packs gets **both** bindings on the shared `lint` and
`code-review` entries, each with its own predicate (AD-9's worked example, made a test).
T5.24 A project with only `astro` gets that one pack binding.
T5.25 Suppressing a `pack-` binding removes it; **the entry still resolves** through its CORE binding and
still appears in the plan (the required-to-do-nothing trap, made a test).
T5.26 Suppressing a `core:` binding ⟹ `suppress_core`.
T5.27 `resolve_for_diff` returns a non-empty `reason` for **every** PlanItem in **both** states.
T5.28 The migrated CORE predicates reproduce `run_post_change_sweep.sh`'s `categorize()` domains for a
fixed corpus of ~40 representative paths (a **characterization test** written against the old script's
output before it is rewritten, minus the three rows AD-11 deliberately re-layers and the two
`framework-validator`/discretionary-privacy rows it deliberately drops).
T5.29 `load()` is deterministic: two calls produce byte-identical `to_json()` (TD-D21).
T5.30 `run_post_change_sweep.sh --json` output equals `dimension_registry_cli.py plan`'s.
T5.31 `run_post_change_sweep.sh`'s output contains **no** "invoke the post-change-sweep agent" text and
**no** "check if PII-relevant" text.
T5.32 A `pack-<n>.yaml` for a pack not in `PACK=` ⟹ `stale_pack_file` (L20).
T5.33 An installer test (extending `tests/automation/test_phase_b.py`'s style): installing with
`--pack django` then upgrading with `--pack astro` leaves **no** `pack-django.yaml` behind.

---

## 10. File budget

| Slice | New | Modified | Deleted |
|---|---|---|---|
| W1 | `scripts/automation/agent_invoke_cli.py`, `bootstrap/invoke_agent.sh`, 4 files under `contract/dimensions/postures/`, `tests/automation/test_agent_invoke_cli.py`, `tests/automation/test_agent_invoke_wrapper.py` | — | — |
| W2 | — | `agent_invoke_cli.py` (the schema is its own), `test_agent_invoke_cli.py` | — |
| W3 | — | `agent_invoke_cli.py`, `test_agent_invoke_cli.py` | — |
| W4 | — | `scripts/framework/validate_self.sh`, `scripts/framework/validate_scripts.sh`, `scripts/framework/validate_agents.sh`, `bootstrap/setup_clis.sh` (1 comment), `CLAUDE.md` (1 row + 1 sentence) | `run_capped` + `_TIMEOUT_BIN` in two files |
| W5 | `scripts/automation/lib/dimension_registry.py`, `scripts/automation/dimension_registry_cli.py`, `contract/dimensions/core.yaml`, `contract/dimensions/project.yaml`, `contract/dimensions/project.yaml.template`, `contract/dimensions/prompts/*.md` (8), `packs/django/dimensions.yaml`, `packs/astro/dimensions.yaml`, 2 test files | `scripts/framework/run_post_change_sweep.sh` (rewrite), `scripts/framework/framework_consumer_files.txt`, `bootstrap/hos_install.sh` (pack-dimensions copy + stale-file prune), `CLAUDE.md` (1 row reworded) | `categorize()` and the Track 1–5 block in `run_post_change_sweep.sh` |

**Protected-surface edits requiring human approval:** `contract/**` (all of W1's postures and all of W5's
registry files), `CLAUDE.md` (W4, W5), `bootstrap/**` (W1's L3, W4's `setup_clis.sh`, W5's installer),
`scripts/framework/**` (W4's three validators, W5's sweep and ship-list). That is most of this work, and
it is correct: this design's entire subject matter is the surfaces that define the controls.

---

## 11. Acceptance — the slice gates, made checkable

| Slice | ADR gate | Checkable form |
|---|---|---|
| W1 | "Every AD-4 row has a failing-closed test" | T1.1–T1.24 exist, pass, and cover C1–C8 with at least one test each; T1.5 uses probe R's envelope verbatim; T1.12 uses probe A's `refused` object verbatim |
| W1 | "Blocked on AD-7's probe for the posture half" | **Discharged** — §0.2. AD-7 is unblocked and its posture design is bound in §3.6, with probe P's fail-open closed by V2–V11 |
| W2 | "Round-trips through `compute_verdict` and `panel_logic`'s readers unchanged; an `invocation_failed` document is proven to raise `new_blocking_count`" | T2.1–T2.7, with T2.6 as the gate |
| W3 | "`token_tracker` wiring, per-entry audit record, nested usage-limit surfacing" | T3.1–T3.9; the surfacing half only, with ESC-F routing the rest |
| W4 | "Delete both `run_capped` copies; add the CLAUDE.md row" | T4.1–T4.6; `run_panel.sh` excluded by the W4b split (§6.4) |
| W5 | "Verify the data-file merge against `hos_install.sh` (AF-9), do not assume it" | **Done** — TD-VF-5 + §7.7, against the implementation at `:591`, `:615`, `:1489-1519`, `:1906-1917`, `:2105-2122`, `:2191-2229`. T5.33 is its regression test |
| W5 | "A check that the resolved registry is stable and that every entry resolves at least one binding" | T5.29 (stability) + loader rule L19 with test T5.19 (binding coverage, enforced at load, not in CI) |

---

## 12. Findings and escalations — routed, not absorbed

**To `architect` (the ADR's author), blocking the coder on the named slice:**

- **ESC-A / TD-F1 (HIGH, blocks W1's classifier) — AD-4's `subagent_stats.refused` row cannot be
  implemented as written.** AD-4 says *"`subagent_stats.refused` absent or `0`"*. On CLI 2.1.270 the field
  is an **object**: `{"depth_limit":0,"concurrency_limit":0,"budget":0}` (probe A, verbatim). A literal
  `refused == 0` comparison is `False` for every healthy invocation, so a literal implementation fails
  **every** invocation closed and stops every merge. §3.7 C6 implements the only reading that preserves
  the intent (absent, or scalar `0`, or a mapping whose every value is `0`), and T1.12–T1.16 pin it.
  **Requesting the architect confirm that reading and amend AD-4's row.**
- **ESC-B / TD-F2 (HIGH, changes W1's test T1.24) — AD-4's "any envelope field the classifier does not
  recognise" clause makes every CLI version bump a merge stopper.** 2.1.270 already ships
  `fast_mode_state`, `fast_mode_disabled_reason`, `queued_turn_count`, `result_index`, `ttft_stream_ms`,
  `time_to_request_ms`, `first_content_frame_ms`, `inference_geo` — eight fields no ADR-era reader knows,
  and the CLI adds telemetry between patch releases. §3.7 binds an interim contract (unknown *fields*
  recorded, unknown *values in decision fields* blocking) on the grounds that #669 and #1362 were both
  value-level fail-opens, so the safety property is preserved. **The architect's ruling decides T1.24's
  assertion; I have not treated my reading as settled.**
- **ESC-C / TD-F3 (MEDIUM, changes W1's P7) — REQ-A4's pre-invocation auth check cannot be performed.**
  Probe A authenticated with `CLAUDE_CODE_OAUTH_TOKEN` absent from the environment (keychain), so an
  unconditional pre-flight env check would produce a false `not_authenticated` for every interactive
  caller. §3.4 makes the pre-flight opt-in (`--require-env-auth`, which cron callers should pass) and the
  post-hoc detection unconditional. This is a departure from a **requirement**, not an ADR decision, so
  it routes to `architect` **and** to `pm-agent` if the architect judges it a requirements change.
- **ESC-D / TD-F5 (LOW, scopes W4) — AD-5.3's `validate_agents.sh` clause has no migration to attach
  to.** That file has no `claude` call site (TD-VF-2); AD-16 gives it nothing. Its `run_capped` deletion
  is a pure refactor of two agy/codex sites that each grow their own output redirection. §6.3 designs it;
  **asking whether it belongs in W4 or in a follow-up.**
- **ESC-J (MEDIUM, blocks §6.1's completion) — which shipped agent fills `validate_self.sh`'s
  `opus-self` adversarial self-review seat?** AD-3 admits no bare-model path and no agent file describes
  that lens today. Options: a new `self-reviewer.md` (protected surface, human-gated) or reuse
  `code-reviewer` with the existing prompt. This is a question about what the self-review lens *is*, which
  is architecture, not plumbing. **W4 can land §6.2, §6.3, §6.5 and §6.6 without this; §6.1 needs it.**

**To `architect`, non-blocking, for the record:**

- **TD-F4 / §6.4 — `run_panel.sh` is split out as W4b**, exercising AD-16's explicit escape clause. Two
  seats, not one; two new protected-surface agent files; and it changes the panel's input contract. **No
  bare-model escape hatch was added to the primitive**, as AD-16 requires.
- **ESC-E — `scripts/automation/**` is not in the consumer ship-set** (TD-VF-6), so neither L2 module
  reaches a consumer install. Same gap ADR-1357 TD-VF-3 recorded; same answer (HOS is the only consumer in
  v0.7.0). Routed to W7's ship-set decision; **not** worked around by relocating the modules against AD-9.
- **ESC-H — `--max-budget-usd` exists on 2.1.270** and AF-2 did not see it. AF-2's `--max-turns`
  conclusion is confirmed, but a *cost* bound is available and would be a cheap second guard on a runaway
  session. Not designed in; worth considering once W6 has a measurement.
- **ESC-I — `--json-schema <schema>` exists** and could enforce the agent's output shape at the CLI
  rather than after the fact (§4.3). Unprobed; its effect on the envelope is unknown. Recorded as a
  possible strengthening, not designed in.

**To the orchestrating session (actions, no design content):**

- **ESC-F — the #1446 usage-limit breaker is commented out** (`bin/hos-cron:2005-2060`, TD-VF-11), so
  W3 can build only the surfacing half of AD-8's usage-limit item. An issue should carry the wiring, and
  it should be linked from #1643 so W3 is not closed as if it did the whole thing.
- **ESC-G — `scripts/automation/**` is not a protected surface** while `contract/**` is (TD-VF-12). This
  design keeps every security-relevant posture value under `contract/` for exactly that reason (§3.6
  TD-D10), so nothing is currently exposed — but as `scripts/automation/` accumulates decision logic
  (`merge_authority_cli.py` is already there) the asymmetry is worth a deliberate ruling. I may not edit
  `protected_surfaces.txt`; it is itself a protected surface and this is a human/architect decision.
- **ESC-K — `.claude/agents/post-change-sweep.md` becomes stale in W5** (§7.9): the script it reads no
  longer prints an agent plan. The agent edit is protected-surface and belongs with W7, when the sweep
  executes. Needs an issue so it is not simply forgotten.

**Decisions I made that the ADR left open (index):** TD-D1 (path-load `scripts/oversight` modules),
TD-D2 (stdout authoritative, `--output-file` a copy), TD-D3 (frontmatter `name:` check), TD-D4
(`--permission-prompts none`), TD-D5 (process-group reaping details), TD-D6 (`outcome_detail`
precedence), TD-D8 (L2 validates the posture file — probe P), TD-D9 (two-file posture, not an `hos:`
key — probe S deliberately not relied on), TD-D10 (the sidecar lives under `contract/`), TD-D11 (posture
id spelling), TD-D12 (`reliability`/`ops` predicates — mine, no source to migrate), TD-D13 (Tracks 3/4/5
excluded), TD-D14 (`reviewer` is the vendor), TD-D15 (`model` derivation), TD-D16 (`input_digest`
manifest), TD-D17 (`token_tracker` as a subprocess), TD-D18 (loader/CLI split), TD-D19 (`project.yaml`
never installed), TD-D20 (CORE fallback bindings for `ui`/`a11y`), TD-D21 (resolved registry not
committed).

---

## 13. Startup-gap analysis and affected sign-offs

Asked of each item, per the CORE startup-gap rule: *"Should this have been settled in the initial
technical design, before any code was written against it?"*

- **The missing invocation primitive (VF-2).** Yes — but the ADR's §8 already records it, attaches the
  lesson to the design phase, and establishes that **no sign-off is orphaned** because no ADR of mine
  preceded it. Nothing to add; recording that I checked rather than skipped it.
- **The silently-ignored malformed settings file (probe P).** **Yes, and this one is new.** It is a
  fail-open in a mechanism (AD-7) that no code has yet been written against, so **no sign-off is
  orphaned** — W1 is unstarted. But it is exactly the class of thing that would have been discovered only
  after a posture file was mis-edited in production, at which point every invocation since the edit would
  have run unpostured with no signal. It is closed by construction in §3.6 V2–V11 and pinned by a test
  that asserts **no subprocess is launched**. **No `startup-artifact-gap` issue is warranted** (nothing
  was built against the gap); the finding's durable home is §0.2 probe P and §3.6 TD-D8.
- **`run_post_change_sweep.sh`'s consumer-shaped routing in CORE (AF-6.2, AF-6.4).** Yes — the ADR §8
  already calls for a `startup-artifact-gap` issue on the CORE/PACK/PROJECT layering of routing data, and
  §7.2/§7.6 implement the fix. **Affected sign-offs:** HOS's own sign-offs on the script **stand** (the
  code does what it was signed off to do), but AD-11 changes its scope from "print a plan" to "render the
  resolved registry", and §7.9 deletes `categorize()` outright. Those sign-offs **must not be carried
  over**: the rewritten script is new work and needs its own review inside W5. Two of its routing rules
  are additionally being *removed as wrong* (`framework-validator`, which consumers never received; the
  discretionary privacy `||`), so any sign-off whose expectation was "the sweep names the right agents"
  is an expectation about behaviour that is deliberately changing.
- **`reliability` and `ops` never having been routed (TD-VF-7.1).** **Yes, and this is a gap the ADR does
  not name.** Two of the eight lenses have never appeared in the only routing mechanism the repo has, so
  "which files does the reliability lens apply to?" has never been answered anywhere. No sign-off is
  orphaned (nothing was built on an answer, because there was no answer), but the predicates in §7.2 are
  **mine and unvalidated**, and W6's measurement slice is where they get their first evidence.
  **Recommend a `startup-artifact-gap` issue** for the two unrouted lenses, filed by the orchestrating
  session, so the guess is visible as a guess rather than inherited as a fact.
- **`--max-budget-usd` (ESC-H).** No — it is a newly-observed CLI capability, not a gap in a prior
  artifact. Recorded, not escalated as a gap.
- **Interpreter fitness (Amendment A, 2026-09-16).** **Yes — this is a genuine `startup-artifact-gap`,
  and the first one in this design with code already written against it.** §3.9 step 2 required the
  *presence* of an interpreter and never its *fitness* to run L2, even though §0.1 TD-VF-10 had already
  observed that PyYAML is available **on this host** and warned about the wrong import idiom — an
  observation that should have become a precondition and did not. W1 was then built exactly to the
  contract as written, which is why the defect is the design's and not the coder's. **Recommend a
  `startup-artifact-gap` issue** (filed by the orchestrating session, per this section's standing
  practice), citing #1720's red `tests` check and naming the general form: *a canonical entry point must
  state which interpreter satisfies its declared dependencies, and must fail closed in one line when none
  does.* **Affected-sign-offs analysis:**
  - **Stand, unchanged** — nothing in their contract moved: §3.3's exit-0/exit-2 semantics; §3.4 P1–P8;
    §3.5's launch contract and reaping; §3.6's posture validation V1–V11; §3.7's classifier and
    precedence; §4's document schema, `input_digest`, and round-trip obligations. Code approved against
    any of those is **not** orphaned.
  - **Orphaned until re-reviewed against the amended contract** — `bootstrap/invoke_agent.sh` (behaviour
    change: interpreter selection, a new environment-controlled input, two new error lines; it is also
    `bootstrap/**` protected surface, so a human gate re-fires on it regardless) and the import block +
    `main()` entry of `scripts/automation/agent_invoke_cli.py` (new P0, new exit-1 cause). Those hunks
    need `code-reviewer` **and** `security-reviewer`; the security lens specifically on
    `INVOKE_AGENT_PYTHON` as a new operator-settable input to a governance surface (see §3.9 for why it
    is unreachable through the allowlisted argv shape and widens no trust boundary — that argument is to
    be *checked*, not inherited).
  - **Re-read, not merely re-run** — `tests/automation/test_agent_invoke_wrapper.py`: T1.50 *reverses*
    an existing test's expectation (a `PATH` with no `python3` is no longer fatal). Any sign-off that
    read that test as evidence of fail-closed behaviour was reading a property that has moved to P0, and
    must confirm it there.
- **The `token_tracker` call rule (Amendment B, 2026-09-18).** **Yes — this should have been settled
  before W3 was written, and it is a `startup-artifact-gap` of the same family as Amendment A: a clause
  that stated a rule for one case and left the rest to inference.** §5.1 named `--not-applicable` as the
  sole exemption and gave the correct *reason* ("nothing was spent") without noticing that the reason
  covers four further outcome classes. Two agents read the same sentence to opposite conclusions, which
  is the definition of an under-specified contract, not a disagreement about it. **Recommend a
  `startup-artifact-gap` issue** (filed by the orchestrating session, per this section's standing
  practice), naming the general form: *a design clause that names an exemption must enumerate the
  outcome classes it does not exempt, or state the property that decides them* — TD-D24 now states the
  property (was a process launched?) and enumerates the expansion. Severity is lower than Amendment A's:
  this is an **observability-accuracy** defect, not a gating one. §5's governing rule (carried from
  ADR-1604 AD-4) is that **no decision in this design may read a token record**, so no verdict, exit code
  or merge outcome was ever affected by the reading in force. **Affected-sign-offs analysis:**
  - **Stand, unchanged** — everything outside the `token_tracker` call decision: §3.3 exit codes, §3.4
    P1–P8 *ordering and failure details* (the preflight documents themselves are unchanged in content —
    same `outcome`, `outcome_detail`, `verdict`, `input_block`, `input_digest`), §3.6, §3.7, §4's schema
    and round-trip obligations, §5.2's audit record (written on every path before and after), §5.3. No
    sign-off on any of those is orphaned, and the `observability` block gains **no new field**.
  - **Orphaned until re-reviewed against TD-D24** — only the W3 hunks that decide the call: the
    `skip_token_tracker` argument at the preflight-failure emission site, and the input-byte-length plumbed
    into it. That code was written to the *old* clause and does what that clause could be read to say, so
    this is a design correction, not a coder defect. It needs `code-reviewer` only — **no security,
    privacy or reliability re-review is triggered**: the change *removes* a subprocess spawn and a write,
    adds no input, no field and no branch on untrusted data, and touches no protected surface.
  - **Re-read, not merely re-run** — any W3 test asserting that a preflight-failure document records a
    token entry is now asserting the defect and must be **inverted**, not deleted (T3.10 replaces it).
    T3.3's own expectation is narrowed from "a missing `usage` falls back" to "a missing `usage`
    *post-launch* falls back"; a sign-off that read T3.3 as covering the preflight paths was reading
    coverage that never existed.
- **Nothing else.** W1–W5 are all new build. As of the original draft, no code had been approved against
  any contract this document changed, so no prior sign-off was invalidated by it — and the draft noted
  that this *"will stop being true the moment W1 lands"*. **It has: W1 landed as `60360661` / PR #1720,
  and Amendment A is the first change to this document with code already written against the clause it
  corrects.** The bullet above is therefore the live affected-sign-offs analysis, not a hypothetical one;
  every further amendment must carry its own.

---

## Human Review Required

**RISK: HIGH.** This design specifies the surface through which every future AI review in this repository
will be invoked, and the configuration surface that decides which reviews exist. Two failure modes
dominate. The first is a **stalled merge queue**: under Q1 every `invocation_failed` is a hard block, and
§3.7's allowlist is deliberately the tightest reading of AD-4 — a legitimate second `terminal_reason`
value, or ESC-A implemented literally, stops every merge. The second, far worse, is **a mechanism that
looks like it is reviewing and is not**, and the probe found a live instance of it that the ADR did not
know about: a malformed posture file is silently ignored by the CLI (probe P), so an invocation can run
with no permission posture at all, report `rc 0`, `is_error:false`, `terminal_reason:"completed"`, and
look perfect. That is closed positively here (§3.6 V2–V11, plus a test asserting no subprocess launches),
not cautioned about. Three further routes to the same condition are closed the same way: `subtype` is
never read (§3.7); applicability is decided by code and an agent asserting it is a `schema_violation`
(§4.3 rule 5); and absence of a record is never `not_applicable` (§4.5).

**CONFIDENCE:**
- **HIGH on §0.2.** Every claim about `--settings`, `--agent`, the envelope shape, and the malformed-file
  fail-open is a live probe against CLI 2.1.270 with the command and its output recorded verbatim, run
  this session. Probes K/L are a controlled pair differing in one line of one file. The ADR's two open
  questions are answered from behaviour, not documentation.
- **HIGH on §3 (W1) and §4 (W2).** They follow from the probes and from decisions already ruled. The
  classifier is a pure function with a synthetic-envelope test per row, and the two most important
  fixtures are real CLI output rather than my idea of it.
- **HIGH on §0.1's re-verification.** AF-9, the `run_capped` copies, and the `claude -p` sites were each
  re-derived from the tree this session; two of the three found the ADR slightly off (TD-VF-1's two seats,
  TD-VF-2's `validate_agents.sh` having no claude site) and both corrections are escalated rather than
  absorbed.
- **MEDIUM-HIGH on §7 (W5).** The schema, the ownership rules and the twenty-one loader rules are sound
  and the installer story is verified against the implementation rather than by analogy. But `ui`/`a11y`'s
  interaction with rule L19 (§7.8) is a cliff I found while writing and fixed in the draft, which suggests
  the entry/binding model has other sharp edges I have not hit yet — most likely around a consumer with an
  unusual pack combination.
- **MEDIUM on TD-D12 (`reliability` and `ops` predicates).** They are **mine, invented, and unvalidated**,
  because TD-VF-7 found no existing routing for either lens. They may be much too broad. W6 is where they
  get evidence.
- **LOW — read as a warning, not a hedge — on anything resembling a duration.** `DEFAULT_TIMEOUT_S = 300`
  is the repo's own existing `AI_REVIEW_TIMEOUT` calibration, **not** a measurement. My probes were
  one-to-two-turn prompts and tell us nothing about a real review. **No budget, cadence, or cost number
  in W5 or beyond may be calibrated from anything in this document**; W6 remains the only source, exactly
  as the ADR binds.

**BLAST RADIUS:** `contract/**` gains a new protected-surface file family (postures + registry);
`CLAUDE.md` gains a canonical entry point and one reworded row; `scripts/framework/validate_self.sh`,
`validate_scripts.sh`, `validate_agents.sh` and `run_post_change_sweep.sh` all change behaviour;
`bootstrap/hos_install.sh` gains the first pack→data contribution path in HOS's history;
`bootstrap/setup_clis.sh` gains a comment; `scripts/framework/framework_consumer_files.txt` gains five
rows; the subscription quota, which W1 makes it possible to spend from a script for the first time. **Not
touched:** `bin/hos-cron`, `merge_authority.py` and its 157 tests, `overseer.md`, `worker.md`, any human
gate, any merge decision, and `run_panel.sh` (split to W4b).

**Change classification: STRUCTURAL.** It introduces a new class of script-launched model process, a new
configuration surface with its own ownership and suppression rules, and a new permission-posture surface.
Per the CORE rule a structural design change is escalated to a human before writing — it is escalated
**with** this document rather than before it, because the ADR that binds it was itself human-reviewed and
classified STRUCTURAL, and because the four ESCs above (ESC-1…ESC-4) already hold the product-boundary
questions. **Nothing in this document has been applied to any script, agent definition, configuration
file, registry file, or test.** This session wrote exactly one file — this design. The probes wrote only
throwaway files under `/tmp/claude/probe1643/`, none of which is committed.

**Not done here, deliberately:** no sign-off register entry (a technical design is a contract, not a
reviewed build artifact, and `technical-design` writes no register entry); no issue filed and no GitHub
write made (the ESCs in §12 name what the orchestrating session should file); no architect approval — this
is **iteration 1 of 5 and it is requesting architect review now**, with ESC-A, ESC-B, ESC-C, ESC-D and
ESC-J as the blocking items.

---

## Human Review Required — Amendment A (2026-09-16, interpreter fitness)

**RISK: MEDIUM.** Amendment A changes a protected-surface launch script (`bootstrap/**`) on the path every
future AI review will be invoked through, and adds one precondition to L2. It reverses no existing
contract: exit-0 semantics, the classifier, the posture rules and the document schema are untouched. The
failure mode it closes is the one this design is most concerned with — an entry point that is *unfit to
run* announcing itself as a Python traceback on some hosts and as a red CI check on others, rather than as
one machine-readable line. The residual risk it introduces is the ladder's rung 1: a new
environment-controlled input (`INVOKE_AGENT_PYTHON`) on a governance surface, argued in §3.9 to be
unreachable through the allowlisted argv shape and to widen no trust boundary — **an argument for
`security-reviewer` to check, not to inherit.** The second-order risk is scope creep in L3: TD-D22 states
the ladder is the maximum L3 may grow, because "it is only launch logic" is exactly how a wrapper that
must not grow, grows.

**CONFIDENCE:**
- **HIGH on the diagnosis.** The failure is deterministic and was reproduced twice on the same commit;
  the dependency path (`import yaml` at `agent_invoke_cli.py:61` → `_parse_frontmatter` → P4 → the #608
  check), the declaration site (`scripts/oversight/requirements.txt:17`), the CI topology (`setup-python`
  3.12 vs. a venv built in the same job and hard-required by `run_tests.sh:75`), and the installer's
  deliberate venv exclusion (`hos_install.sh:1862`) were each read at source this session.
- **HIGH on TD-D22's AD-1 ruling.** AD-1's two prohibitions are quoted verbatim in the script's own
  header; interpreter resolution falls outside both by their own wording, and §3.9 step 2 already
  contained an interpreter `if` that no review treated as a violation.
- **HIGH on TD-D23's exit-1 ruling.** It follows from §3.3's existing definition and from the distinction
  between the environment the primitive *drives* (`cli_unavailable`, a document) and the interpreter
  running the primitive *itself* (exit 1, no document).
- **MEDIUM on T1.52's mechanism.** `python3 -m venv --without-pip` in `tmp_path` is the cleanest seam I
  can specify without copying the tree, but it depends on `ensurepip`/`venv` being available in the test
  environment; the test must skip cleanly, and a skipped regression test is not a regression test. If it
  skips in CI, that is a finding to raise, not to accept.

**BLAST RADIUS:** `bootstrap/invoke_agent.sh` (behaviour), `scripts/automation/agent_invoke_cli.py`
(import block + `main()` entry only), `tests/automation/test_agent_invoke_wrapper.py` (one expectation
reversed, three tests added), `tests/automation/test_agent_invoke_cli.py` (three tests added). **Not
touched:** `.github/workflows/tests.yml` (and it must stay untouched — T1.55), `scripts/oversight/`,
`requirements.txt`, the result document schema, the classifier, the posture files, and every W2–W5
contract.

**Change classification: ADDITIVE** — a new precondition and a launch-layer resolution ladder; no existing
semantics reversed, no new surface, no new outcome class, no schema field. (One **clarifying** correction
rides along: an existing test's expectation, T1.50.) Not structural, so no pre-write human escalation was
required; this block is the MEDIUM self-flag. **`architect` must be notified** — not for approval of the
mechanism, which is inside AD-1, but because TD-D22 *interprets* AD-1's prohibition and the architect owns
that text. If the architect reads AD-1 more strictly, the stated fallback is rung 2 alone (hard-code the
venv interpreter behind an `-x` guard), which keeps P0 and the consumer contract intact and costs only the
host whose system interpreter legitimately carries PyYAML.

**Not done here:** no application code, no test code, and no script was written by this ruling — only this
document. No sign-off register entry (`technical-design` writes none). No issue filed: §13 **recommends**
a `startup-artifact-gap` issue and the orchestrating session files it.

---

## Self-flag — Amendment B (2026-09-18, the `token_tracker` call rule)

**RISK: LOW.** Amendment B changes no gating behaviour and no schema. §5's governing rule (carried verbatim
from ADR-1604 AD-4) is that **no decision in this design may read a token record**, so neither reading of
the old clause could ever have changed a `verdict`, an `outcome`, or an exit code. What was at stake is
the accuracy of one ephemeral report. The ruling *reduces* what W3 does on the **four** paths it changes
(`--not-applicable`, the fifth non-launching path, already skipped under the old clause): one fewer
subprocess spawn, one fewer write, no new input, no new field, no new branch. It does not touch a
protected surface, and it does not alter the content of any emitted document.

**CONFIDENCE:**
- **HIGH on the factual claim**, verified in the tree this session rather than taken from either agent:
  `_emit_preflight_document` reads and hashes `--input-file` when present and carries the byte length
  into the shared observability writer with `skip_token_tracker=False`, which with `usage=None` passes
  `--prompt-chars <real byte length>`; `token_tracker.estimate_tokens` is `max(1, round(chars / 4))`, so
  the recorded estimate is proportional to the real input and is never zero. For the P7/P8 rows P6 has
  already proven the input file non-empty, so the phantom spend there is guaranteed material, not
  hypothetical. `code-reviewer`'s finding is **confirmed**, and is confirmed one step further than it was
  stated: it holds for all four preflight outcomes, not only the two it named.
- **HIGH on the ruling.** §5.1 records five reasons; **three of them are independent of each other** and
  each would carry the ruling alone (reason 3 — the fallback bullet was already written in terms of
  post-launch outcomes only; reason 2 — `"estimated": true` is a positive claim about a real call, not a
  null marker; reason 4 — §5.2's audit record already carries the failure signal in a committed ledger in
  a unit that is true). Reasons 1 and 5 are corroborating, not load-bearing: reason 1 establishes the
  *magnitude* of the defect rather than its existence, and reason 5 closes the one alternative remedy. The counter-case — "a preflight failure is a legitimate signal worth keeping" — is
  **accepted as a real need and satisfied elsewhere**, not dismissed: §5.2 writes one record per
  invocation including every `invocation_failed` one. The coder's reading was a reasonable construction
  of a bad clause; the clause is what is being corrected.
- **HIGH that the iff-rule closes the ambiguity class.** "Was a process launched?" is decidable at every
  emission site, admits no third answer, and classifies any outcome added to §3.7 later without a further
  ruling — which the enumerated table alone would not do.
- **MEDIUM on T3.10's framing being adopted as written.** The trap it guards (asserting "recorded zero"
  instead of "did not spawn") would pass against the very defect being closed, and the paired T3.11
  (post-launch `not_authenticated` *does* record) is the one an implementer keying on `outcome_detail` is
  most likely to skip. If either is dropped in implementation, the regression is silent.

**BLAST RADIUS:** this document only — §5.1 (TD-D24 + the amended bullet), §9.3 (T3.3 narrowed, T3.8
extended by T3.10/T3.11), §13 (one bullet), §3.7 (**the count correction only** — "three" → "four" over
an unchanged list, and `V2–V11` → `V2–V14` on the same line to match §3.6's post-Amendment-5 table; **no
classifier rule, precedence step, or detail value is touched**), and the header banner. Downstream, the
coder's change is confined to the `skip_token_tracker` argument at the preflight-failure emission site in
`scripts/automation/agent_invoke_cli.py` and the W3 tests. **Not touched:** the document schema, the
classifier's rules C1–C8 and precedence 1–10, the preconditions, the posture rules, §5.2's audit record,
§5.3, and every W4–W8 seam.

**Change classification: CLARIFYING.** No contract is reversed — the clause had no stated rule for the
four outcomes to reverse, which is the defect. No new surface, no new field, no new outcome class, no
new mechanism. Not additive and not structural, so no pre-write human escalation was required and this
block is a LOW self-flag recorded for traceability rather than a MEDIUM-or-above gate. **`architect` is
notified** (a design-contract edit under §5.1's W3 scope), but no architecture decision is implicated:
AD-8 mandates that observability exist and ADR-1604 AD-4 forbids reading it for decisions; *which
non-spending paths write a spend record* is a detail AD-8 left to this document, and it is settled here.

**Not done here:** no application code and no test code was written by this ruling — `agent_invoke_cli.py`
was read, not edited, and the coder implements TD-D24. No sign-off register entry (`technical-design`
writes none). No issue filed: §13 **recommends** a `startup-artifact-gap` issue and the orchestrating
session files it.

---

## Amendment C (2026-10-02) — W5's loader is schema-parametric (ADR-1644 SEAM-1), and seven §7 claims corrected against the tree

**Status:** DRAFT. **Binding on W5 once the architect approves.** W5 is unbuilt, so no code has been
written against the §7 text this amendment supersedes. The one piece of *built* code it touches is W1's
posture validator, and that change preserves its behaviour (§C.2.8). Where this amendment and §7 disagree,
**this amendment governs**. §7 sections it does not name stand as written.

### C.1 Rationale and scope

**Why.** ADR-1644 §4 **SEAM-1** (`ADR-1644-stage-per-cycle.md:867-871`) binds W5's `technical-design` to
build the loader *"schema-parametric: one loader and one ownership model, with each registry document
declaring which schema it is (dimensions or stage graph) … It is not a second loader."* AD-C1 (`:206-242`)
puts the stage graph in `contract/stages/` with the same `core.yaml` / `pack-<name>.yaml` / `project.yaml`
layout, and ends with *"One loader, not two. See §4 SEAM-1"* (`:242`). ADR-1643 **AD-12** (`:574-606`)
already said the same from the other side: the worker's graph shares this registry's *"format, ownership
model, and loader, and nothing else."* §7 as written is a dimensions-only loader. T3.1 (`ADR-1644:899`)
depends on W5, so building §7 as written would force T3.1 either to fork the loader (forbidden) or to
rebuild W5 after it lands.

**Scope.** This is a delta and not a rewrite of §7. It adds:
1. A **dispatch seam**: one engine and a static per-schema table (§C.2.4).
2. A **classification** of every §7.4 rule as kind-generic or dimension-specific, plus seven new rules and
   a fixed check order (§C.2.6).
3. The **extension point** T3.1 uses (§C.2.9).
4. **Corrections** to seven §7 claims that the tree contradicts (§C.2.2, TD-VF-15…TD-VF-21), each with
   a file:line citation, re-verified this session against the `main` checkout at `035c57637`.

It designs **nothing** of the stage graph itself. Stage vocabulary, transitions, caps and the fits-one-cycle
check belong to T3.1's own technical design.

**Numbering.** Amendment C uses TD-VF-13…TD-VF-21 and TD-D25…TD-D32. No earlier section of this document
uses these numbers. (The `TD-VF-15…17` in `TECHNICAL-DESIGN-1538-…` belong to that document.)

### C.2 The amended W5 contract

#### C.2.1 What changes in §7, and what does not

| §7 section | Disposition under Amendment C |
|---|---|
| §7.1 File layout | **Stands**, with one added row: `contract/resolved-packs.txt` is generated by the installer (§C.2.5) |
| §7.2 Schema (`core.yaml`, packs, project) | **Stands.** Dispatch is by the caller's `schema` argument, which selects the `KINDS` row and so the directory. Each document's `schema: hos.dimension-registry` is its **declaration** of kind, and L3a verifies it against the selected row. A document never selects its own handler. (Declaration plus verification is what SEAM-1 requires. Dispatching on document content would let a misplaced file choose its own rules.) |
| §7.3 Loader API | **Superseded by §C.2.7.** `load()` keeps its signature. The `packs=None` sentence is replaced (TD-VF-16) |
| §7.4 Failure rules L1–L21 | **Classified and extended by §C.2.6.** L3 is split, L5/L12 are amended, L22–L28 are added, and the order is fixed |
| §7.5 `resolve_for_diff` | **Stands**, and is dimension-specific |
| §7.6, §7.8 | **Stand** |
| §7.7 Installer items 1, 2, 4 | **Superseded by §C.2.11.** Items 3 and 5 stand |
| §7.9 `run_post_change_sweep.sh` | The usage line, the exit codes and the interpreter are **superseded by §C.2.10**. The other bullets stand |
| §7.10 CLI | **Amended by §C.2.7**: `resolve` gains `--schema`, and the pack set defaults to `contract/resolved-packs.txt` |
| §9.5 Tests | **Extended by §C.2.12**, and T5.32 is re-pointed |
| §10 File budget, W5 row | Adds `scripts/automation/lib/posture.py` (new), `contract/resolved-packs.txt` (new, HOS's own), and `scripts/automation/agent_invoke_cli.py` (modified, §C.2.8) |

#### C.2.2 Verification findings — TD-VF-13…TD-VF-21

All citations are to the working tree at `035c57637`. TD-VF-13 and TD-VF-14 **re-confirm** earlier
claims that §7 still depends on. TD-VF-15…TD-VF-21 are **contradictions**: places where §7, as written,
would produce a defect against the tree as it actually is.

**TD-VF-13 — TD-VF-6 still holds: `scripts/automation/**` is not shipped to consumers.**
`scripts/framework/framework_consumer_files.txt` (85 lines) has no `scripts/automation` entry and no
`contract/` entry. `bootstrap/hos_install.sh` never mentions `automation`, `invoke_agent` or
`contract/dimensions`. `enumerate_framework_files` recurses only `scripts/oversight`
(`hos_install.sh:2207-2208`). CONFIRMED.

**TD-VF-14 — `contract/**` is protected surface, and the W1 posture files exist but are not shipped.**
`contract/**` is the **second entry** of `scripts/framework/protected_surfaces.txt` (file line 17). §7.4's
"line 2" counts entries, not file lines. The four posture files exist under
`contract/dimensions/postures/`, and none of them is in the ship-set. That matches §7.7 item 1, which
adds them in W5. CONFIRMED, with the citation clarified.

**TD-VF-15 — CONTRADICTS §7.7 item 2: no standalone "pack phase" exists. The only per-pack loop is nested
inside the per-agent loop, in the write-nothing Phase A.** The pack loop is
`for _pk in … _resolved_packs` at `hos_install.sh:1499`. It sits inside `for agent in
"${_consumer_agents[@]}"` at `:1461`, and both are part of Phase A, which is *"collecting each file's plan
WITHOUT writing"* (`:1339-1345`). A Phase-A abort exits 4 having written nothing (`:1623-1634`). A coder
who follows "add, inside the pack phase" lands in that loop. The copy then runs once per agent instead
of once per install, and data files get written before the drift gate decides, which breaks the installer's
decide-all-then-act invariant. **Corrected by §C.2.11 item 2 (TD-D31):** the copy runs once, outside the
agent loop, after Phase B. §7.7's citation `:1489-1519` is now `:1461` (outer loop) and `:1488-1519`
(inner).

**TD-VF-16 — CONTRADICTS §7.3: `config.sh`'s `PACK=` is not the resolved pack set.** `PACK=` records the
operator-selected **leaf** only, as a **single value** (`:1176-1178`: *"reads config.sh PACK= as a SINGLE
value … multi-value form is a noted-not-built seam"*). R5 writes it only when exactly one `--pack` was
passed (`:1322`, `-eq 1`), so a two-`--pack` install records nothing at all. The dependency closure *"is
re-derived every run, never persisted to config.sh"* (`:1224-1225`). Re-deriving the closure needs
`pack.toml` `requires` parsing (`_pack_requires`, `:1117`) and consumer-local pack precedence
(`_resolve_pack_dir`, `:1101-1111`), and both are bash-only logic. So a loader that reads `PACK=astro`
sees `{astro}`, while the installer copied files for `{node, astro}` (`:1215-1225`'s own example).
`pack-node.yaml` then trips L20 (`stale_pack_file`) on every load, and an honest install fails closed
for good. **Corrected by §C.2.5 (TD-D27) and §C.2.7:** the installer persists the closure to
`contract/resolved-packs.txt`, and `packs=None` reads that file.

**TD-VF-17 — CONTRADICTS §7.7 item 2, third bullet: there are no "manifest rows" to append a copied pack
file to.** Non-agent `WHOLE` rows are produced by `enumerate_framework_files "$HOS_SOURCE"`. It `cd`s into
the **HOS source** and emits only paths that exist **there** (`:2205-2225`, `[[ -f "$_fc" ]]`), with a
sha256 of the source bytes. `contract/dimensions/pack-<n>.yaml` has no source-tree counterpart at that
path, because its source is `packs/<n>/dimensions.yaml`, so enumeration never emits it. The only row
collection the installer accumulates is the Phase-B `manifest-spec.json`, which is agent-region rows
only (`:1638-1679`). **Corrected by §C.2.11 item 4 (TD-D32):** rows for generated or renamed files are
emitted explicitly.

**TD-VF-18 — CONTRADICTS §7.7 item 1: the shipped set omits the eight prompt files that rule L21 requires,
and the ship-list loop cannot take a directory or a glob.** §7.2's judgment bindings reference
`contract/dimensions/prompts/{code-review,security,privacy,reliability,ops,ui,a11y,infra}.md`, and §10
budgets all eight. L21 makes a missing `prompt_template` a load error. §7.7 item 1 adds only `core.yaml`,
the template and the postures, so a fresh consumer install fails L21 on its first load. Each line of
`framework_consumer_files.txt` is treated as one literal file (`:1906-1916`). A directory or glob line
fails `[[ -f … ]]` at `:1910` and is skipped with a warning, not an error. **Corrected by §C.2.11
item 1:** the eight prompts are listed individually.

**TD-VF-19 — CONTRADICTS §7.9: the usage line drops today's grammar while claiming to keep it, and exit
`1` already has a different meaning.** Today the grammar is a positional ref matching `HEAD*`, or
`--staged`, or explicit file arguments, or `--framework-only` (`run_post_change_sweep.sh:12-17`,
`:30-38`). There is no `--base` and no `--json`. Today's changed-file computation includes the empty-diff
fallback to `HEAD~1` (`:44-53`). §7.9 says *"computes the changed-file list exactly as it does today"*
under a usage line that can express none of those forms. Exit `1` today means *"no changed files
detected"* (`:19-22`, `:55-58`), and §7.9 redefines it as "loader failure" without saying so.
`--framework-only` filters on `categorize()`'s `framework` domain (`:70-72`), and §7.9 deletes
`categorize()`, so the flag would have nothing to filter. A search of `bin/`, `scripts/`, `tests/` and
`.claude/agents/post-change-sweep.md` found **no programmatic caller** of the script. Only docs mention
it, and `framework-setup-validator.md:70` checks that it exists. So redefining exit `1` breaks no caller.
**Corrected by §C.2.10 (TD-D29).**

**TD-VF-20 — CONTRADICTS §7.4 L12: posture validation is V1–V14, and it lives in an L2 module the L1
loader may not import.** L12 cites *"§3.6's V4–V11"*. §3.6 now has V1–V14 (Amendment 5 added
V12–V14), and the built validator implements all fourteen (`agent_invoke_cli.py:302-413`). The block
header at `:298` still reads "V1-V11", and the docstring at `:305` reads "V2-V11". Both are stale comments.
The validator is `agent_invoke_cli.load_posture`, an **L2** function. It raises L2-private
`_UsageError`/`_PreflightFailure`, and the module imports `argparse` (`:38`). §2's layer map has L1
imported by L2, never the reverse, and §7.3 binds the loader to "no argparse". So L12 has no correct
implementation under §7 as written. It could duplicate the rules, which leaves a second copy of a security
control to drift. Or it could import L2, which breaks the layering. **Corrected by §C.2.8 (TD-D26):** the
rules move to a shared L1 module.

**TD-VF-21 — CONTRADICTS §7.9/§7.10: the rewritten sweep is shipped to consumers, but the CLI it calls is
not, and §7.10 invokes it with a bare `python3`.** `run_post_change_sweep.sh` is in the ship-set
(`framework_consumer_files.txt:59`). `dimension_registry_cli.py` and its L1 loader are not (TD-VF-13).
On every consumer install, the §7.9 script would therefore call a file that does not exist. ESC-E
recorded the ship-set gap for the L2 *modules*, but it did not note that W5 rewrites a *shipped* script
to depend on them. Separately, §7.10's `python3 scripts/automation/dimension_registry_cli.py …`
reproduces the exact defect Amendment A fixed. PyYAML is declared in `scripts/oversight/requirements.txt`
(line 17). That file and `ensure_venv.sh` **are** shipped to consumers, because `scripts/oversight/` ships
wholesale. What a consumer lacks after install is the `.venv` itself (Amendment A's consumer-host
contract), not the declared dependency. The fix was `invoke_agent.sh`'s three-rung ladder (`bootstrap/invoke_agent.sh`,
the `INVOKE_AGENT_PYTHON` → `scripts/oversight/.venv/bin/python` → `python3` block). **Corrected by §C.2.10
(TD-D30)**: interpreter ladder plus a fail-closed check that the CLI exists. **The ship-set decision is
escalated (§C.4 Q1)**, not taken here. *(Architect, round 1, verified:* no shipped agent invokes the
script. `.claude/agents/post-change-sweep.md` does not name it, and its only agent reference is the
unshipped `framework-setup-validator.md`. The consumer blast radius is therefore human operators who run
it by hand.*)*

#### C.2.3 Module layout (TD-D25)

```
L1  scripts/automation/lib/dimension_registry.py   NEW (W5) — THE loader engine (kind-agnostic) + the
                                                     dimensions-kind handler + load() wrapper.
                                                     AD-9's bound path; kept.
    scripts/automation/lib/posture.py              NEW (W5) — V1–V14, moved out of L2 (§C.2.8)
    scripts/automation/lib/stage_registry.py       NOT W5 — T3.1's stage-graph handler (§C.2.9)
L2  scripts/automation/dimension_registry_cli.py   NEW (W5) — unchanged role (§7.10), plus --schema
    scripts/automation/agent_invoke_cli.py         MODIFIED (W5) — load_posture becomes an adapter
```

**TD-D25 — the engine stays at AD-9's bound path, and kind handlers are separate modules.** AD-9 names
`scripts/automation/lib/dimension_registry.py` as *the* loader, and SEAM-1 says there is one. Putting the
engine anywhere else would move AD-9's bound path, and that is an architecture decision, not mine. The
module name now undersells what it holds. That is a cosmetic cost, and I record it rather than fix it by
fiat (§C.4 Q3). The dimensions handler shares the module with the engine because it is the
one kind W5 ships. Every other kind is its own module, so T3.1 never edits W5's handler.

#### C.2.4 The dispatch seam

The engine holds **one static, module-level table**, `KINDS: Mapping[str, KindSpec]`, keyed by the
`schema:` string. It is a literal in source. There is **no** runtime `register_kind()` call, because
import-order-dependent registration would make "which kinds exist" depend on which modules some caller
happened to import first. Adding a kind means adding one row in a reviewed diff.

```python
DIMENSIONS_SCHEMA = "hos.dimension-registry"

@dataclass(frozen=True)
class KindSpec:
    schema: str                                   # == the KINDS key
    schema_version: int                           # the one accepted version (L3b)
    directory: str                                # repo-relative, e.g. "contract/dimensions"
    pack_source: str                              # filename under packs/<n>/, e.g. "dimensions.yaml"
    handler_module: str                           # dotted import path of the handler (§C.2.9)
    top_level_keys: Mapping[str, frozenset[str]]  # per owner ∈ {core, pack, project}: the CLOSED grammar (L23)
    core_only_keys: frozenset[str]                # keys only core.yaml may carry (L5)
    project_only_keys: frozenset[str]             # keys only project.yaml may carry (L18)

KINDS: Mapping[str, KindSpec] = MappingProxyType({
    DIMENSIONS_SCHEMA: KindSpec(
        schema=DIMENSIONS_SCHEMA, schema_version=1,
        directory="contract/dimensions", pack_source="dimensions.yaml",
        handler_module="scripts.automation.lib.dimension_registry",
        top_level_keys={
            "core":    frozenset({"schema", "schema_version", "owner", "entries", "bindings"}),
            "pack":    frozenset({"schema", "schema_version", "owner", "pack", "bindings"}),
            "project": frozenset({"schema", "schema_version", "owner", "bindings", "suppress"}),
        },
        core_only_keys=frozenset({"entries"}),
        project_only_keys=frozenset({"suppress"}),
    ),
    # T3.1 adds exactly one row here (§C.2.9). Nothing else in the engine changes.
})
```

**The seam is exactly this:** the engine does everything that is the same for every kind. That covers
locating the files, the pack set, the generic rules in §C.2.6, YAML parsing, and building the ordered
layer tuple. It then makes **one call**, `handler.resolve(docs, ctx)`, which returns the kind's resolved
object. The handler never touches the filesystem layout, the pack set or YAML. It receives parsed
documents and a context, and nothing else.

**Module identity (architect, round 1, binding).** The dimensions row's `handler_module` is the engine's
own module.
- The engine resolves a `handler_module` equal to its own `__name__` to `sys.modules[__name__]` and
  **never re-imports itself**.
- Every other handler is imported by its fully-qualified `scripts.automation.lib.*` name. Each handler
  imports `RegistryError`, `LayerDoc` and `LoadContext` from `scripts.automation.lib.dimension_registry`,
  never from a `sys.path`-relative `lib.*` form.

*Failure mode closed:* a second copy of the engine module carries a second `RegistryError` class. Every
legitimate handler error would then fail the identity check in TD-D28 step 4 and report as
`kind_handler_failed`. That is fail-closed, but it reports the wrong code and hides the real rule.
**PyYAML is imported lazily** inside `load_registry`. It is never imported at module level in
`dimension_registry.py`, `posture.py` or any handler module, so L2 is always reachable as a
`RegistryError`. A module-level import would surface instead as an `ImportError` traceback, or as L26.

#### C.2.5 `contract/resolved-packs.txt` (TD-D27)

**TD-D27 — the installer persists the resolved pack closure as data, and the loader reads only that.**
TD-VF-16 shows that `PACK=` cannot serve. Two alternatives were rejected:
- **(a) Re-derive the closure in Python.** This duplicates `_pack_requires` and `_resolve_pack_dir`'s
  consumer-local precedence, which gives a second implementation of pack resolution that can drift.
  D41 forbids that.
- **(b) Infer the set from which `pack-*.yaml` files exist.** This is exactly what L20 exists to forbid
  (§7.3).

**Format (binding):**
- UTF-8, LF line endings.
- Lines beginning with `#` are comments. Blank lines are ignored.
- Every other line is **exactly one** pack slug matching `^[a-z0-9][a-z0-9-]*$` (the installer's own R2b
  grammar, `hos_install.sh:1277-1282`), with no surrounding whitespace.
- Lines are in the installer's **dependency-closure order**, deps first (`_resolved_packs` after R2c). That
  is also the PACK merge order.
- No slug appears twice.
- **Zero slug lines is valid and means "no packs".** `--no-pack` and HOS's own repo both produce this.
- The installer writes this header, verbatim:
  `# Generated by bootstrap/hos_install.sh — the resolved pack closure, deps first. Do not edit; re-run the installer.`

**Ownership.** The file is **installer-owned**. Every install overwrites it, including `--no-pack`
installs and installs where the pack set is unchanged. It is **never** listed in
`framework_consumer_files.txt`, because HOS's own copy must never overwrite a consumer's. HOS's own repo
commits its own zero-pack file, since HOS is not installed into itself (`scripts/framework/config.sh` has
no `PACK=`). It sits under `contract/**`, so a consumer's pack change surfaces as a CODEOWNERS-gated edit,
just as the `pack-*.yaml` changes that accompany it already do.

**Absent ⟹ load error (L24), not "no packs".** An absent file cannot be told apart from an install that
predates W5, or a hand-copied tree. Reading absence as "no packs" would make every present
`pack-*.yaml` look stale (L20). Worse, it would turn a missing input into a silent default. Fail closed.

#### C.2.6 Rule classification, amended rules, new rules L22–L28, and the check order

**Kind-generic** rules are enforced by the engine for **every** schema in `KINDS`. They are parameterised
only by `KindSpec` fields. **Dimension-specific** rules are enforced by the dimensions handler and do not
apply to other kinds. A future kind declares its own specific rules in its own technical design.

| # | Class | Condition (amended text in **bold**) | `RegistryError.code` |
|---|---|---|---|
| L1 | generic | `<directory>/core.yaml` absent or unreadable | `core_missing` |
| L2 | generic | `import yaml` fails | `yaml_unavailable` |
| **L3a** | generic | **Any loaded file is not a YAML mapping, or its `schema` is absent, or `schema` ≠ the schema being loaded** (catches a stage file dropped into `contract/dimensions/`, and the reverse) | `bad_schema` |
| **L3b** | generic | **`schema_version` ≠ `KindSpec.schema_version`** | `bad_schema_version` |
| L4 | generic | `owner` absent or not matching the filename (unchanged) | `owner_mismatch` |
| **L5** | generic | **A key in `KindSpec.core_only_keys` appears in any file other than `core.yaml`.** For dimensions this is exactly §7.4's `entries:` rule | **`core_only_key`** (renamed from `entries_outside_core`; the message names the key) |
| L6 | dim-specific | Duplicate entry id or binding id | `duplicate_id` |
| L7 | dim-specific | Binding id namespace ≠ owner | `binding_namespace` |
| L8 | dim-specific | Binding references an unknown entry | `unknown_entry` |
| L9 | dim-specific | Binding `kind` ≠ entry `kind` | `kind_mismatch` |
| L10 | dim-specific | Judgment binding's agent file absent | `agent_missing` |
| L11 | dim-specific | Deterministic binding's tool absent or not executable | `tool_missing` |
| **L12** | dim-specific | **`kind: judgment` and `posture` absent, or `posture.load_posture(repo_root, posture)` raises `PostureError` for any of V1–V14** (§C.2.8). The message carries the failing rule id, e.g. `V13`. V1 (unknown posture name) is an ordinary L12 failure here, since the loader has no usage-error class | **`posture_invalid`** (renamed from `posture_missing`, because it now covers invalid as well as absent) |
| L13 | dim-specific | Bad `timeout_seconds` | `bad_timeout` |
| L14 | dim-specific | Bad `predicate` | `bad_predicate` |
| L15 | dim-specific | `suppress` names an unknown binding | `suppress_unknown` |
| L16 | dim-specific | `suppress` names a `core:` binding | `suppress_core` |
| L17 | dim-specific | `suppress` with an empty reason | `suppress_no_reason` |
| **L18** | generic | **A key in `KindSpec.project_only_keys` appears in any file other than `project.yaml`.** For dimensions this is exactly §7.4's `suppress:` rule | `suppress_outside_project` → **`project_only_key`** (renamed; the message names the key) |
| L19 | dim-specific | Entry with zero unsuppressed bindings | `entry_unbound` |
| L20 | generic | A `pack-<n>.yaml` in `<directory>` whose `<n>` is not in the resolved pack set, **which now comes from §C.2.5** | `stale_pack_file` |
| L21 | dim-specific | Judgment binding's `prompt_template` absent or missing | `prompt_missing` |
| **L22** | generic | **The `schema` argument passed to `load_registry` is not a key of `KINDS`** | `unknown_kind` |
| **L23** | generic | **A top-level key outside `KindSpec.top_level_keys[owner]`** (a closed grammar, so a typo such as `binding:` is never ignored silently) | `unknown_key` |
| **L24** | generic | **`packs=None` and `contract/resolved-packs.txt` is absent, unreadable, or violates §C.2.5's format (bad slug, duplicate slug, or whitespace). An explicit `packs` sequence must meet the same slug and no-duplicate rules** | `bad_pack_set` |
| **L25** | generic | **A regular, non-dot file directly in `<directory>` whose name is not `core.yaml`, `project.yaml`, `project.yaml.template`, or `pack-<slug>.yaml`.** Subdirectories (`postures/`, `prompts/`) are not examined. This catches a `project.yml` or `pack-Django.yaml` whose content would otherwise be silently unloaded | `unexpected_file` |
| **L26** | generic | **The `KindSpec.handler_module` fails to import, lacks `resolve`/`to_json`, or `resolve` raises anything other than `RegistryError`.** The original exception's type and message are carried in the error message. A broken handler is never a skip | `kind_handler_failed` |
| **L27** | dim-specific | **A `tool`, `prompt_template` or `agent`-derived path is absolute, or contains a `..` segment, or (if it exists) has a symlink-resolved real path outside `repo_root.resolve()`.** This is the V14 code-reviewer finding applied to the registry: `Path(root) / "/abs"` discards `root` and validates against the host filesystem. A symlink is the same escape without the `..` | `path_escape` |
| **L28** | dim-specific | **An entry, binding, predicate or suppress item carries a key outside its grammar** (§7.2's shapes are closed). This is the item-level twin of L23 | **`unknown_item_key`** (architect, round 1: distinct from L23's `unknown_key`, so that every rule has exactly one code) |

**Not an error (unchanged from §7.4, restated per kind):** a pack in the resolved set with no
`pack-<n>.yaml`, and an absent `project.yaml`. The same holds for every kind.

**TD-D28 — check order is part of the contract. The first failure wins, and exactly one `RegistryError` is
raised.** Order:

1. **Engine, before any file is parsed:** L22 → L2 → L26 (the handler imports and has the required
   attributes) → L24 → L1 → L25 → L20. (Architect, round 1: L2 precedes L26. A missing PyYAML must
   report as `yaml_unavailable`, never as a handler failure.)
2. **Engine, per file, in merge order core → pack-\* (closure order) → project:** L3a → L3b → L4 → L5 →
   L18 → L23. L5 and L18 precede L23 deliberately. Otherwise an `entries:` in `project.yaml` would
   report as the vaguer `unknown_key`.
3. **Handler (dimensions):** L28 → L6 → L7 → L8 → L9 → L13 → L14 → L27 → L10 → L11 → L12 → L21 → L15 →
   L16 → L17 → L19. Shape comes first, then identity and reference, then filesystem existence (L27
   guards the paths before L10/L11/L21 touch them), then suppression, and last the whole-registry
   property L19, which is meaningful only once everything else holds.
4. **Engine, around step 3:** any non-`RegistryError` raised by the handler becomes L26.

Why fix the order? A fixture with two defects must produce the same code on every run and every machine.
Without a fixed order, the tests in §9.5 could pass while asserting the "wrong" one of two true
statements.

#### C.2.7 The amended loader API (supersedes §7.3's code block and its `packs=None` sentence)

§7.3's dataclasses `Entry`, `Predicate`, `Binding`, `PlanItem` and `RegistryError` are **unchanged**,
and so are its purity constraints: no `argparse`, no `__main__`, no `sys.argv`, no network, no
subprocess. **Added:** the engine never reads `os.environ`. Runtime values reach a handler only
through `runtime=` (§C.2.9).

```python
# ── engine (kind-generic) ───────────────────────────────────────────────────
@dataclass(frozen=True)
class LayerDoc:
    path: str                     # repo-relative, e.g. "contract/dimensions/pack-django.yaml"
    owner: str                    # "core" | "pack" | "project"
    pack: str | None              # the slug when owner == "pack"
    data: Mapping[str, object]    # the parsed mapping, already through L3a-L23

@dataclass(frozen=True)
class LoadContext:
    repo_root: Path               # absolute, resolved
    kind: KindSpec
    packs: tuple[str, ...]        # the resolved set, closure order
    runtime: Mapping[str, object] # caller-supplied; empty mapping if None was passed

def load_registry(repo_root: str | Path, schema: str, *,
                  packs: Sequence[str] | None = None,
                  runtime: Mapping[str, object] | None = None) -> object: ...
    # Runs §C.2.6's order. Returns whatever KINDS[schema]'s handler.resolve returns.
    # packs=None  -> read contract/resolved-packs.txt (L24 on absent/malformed).
    # packs=[...] -> use verbatim, after L24's slug/duplicate check. [] means "no packs".
    # NEVER reads scripts/framework/config.sh's PACK= (TD-VF-16).

def read_resolved_packs(repo_root: str | Path) -> tuple[str, ...]: ...   # §C.2.5's parser; raises L24
def registered_schemas() -> tuple[str, ...]: ...                         # sorted(KINDS); used by T5.44 and the CLI
def registry_to_json(schema: str, resolved: object) -> dict: ...         # dispatches to the handler's to_json

# ── dimensions kind (wrapper + handler, same module per TD-D25) ─────────────
@dataclass(frozen=True)
class ResolvedRegistry:
    schema: str                              # ADDED — always DIMENSIONS_SCHEMA
    packs: tuple[str, ...]                   # ADDED — the pack set it was resolved against
    entries: Mapping[str, Entry]
    bindings: Mapping[str, Binding]          # suppressed bindings are ABSENT
    suppressions: Mapping[str, str]
    source_files: tuple[str, ...]
    digest: str                              # sha256 over to_json()'s canonical form, which now covers schema + packs

def load(repo_root: str | Path, *, packs: Sequence[str] | None = None) -> ResolvedRegistry:
    """SIGNATURE UNCHANGED from §7.3. Exactly load_registry(repo_root, DIMENSIONS_SCHEMA, packs=packs)."""
def resolve(docs: tuple[LayerDoc, ...], ctx: LoadContext) -> ResolvedRegistry: ...   # the handler; dim-specific rules
def resolve_for_diff(reg: ResolvedRegistry, changed_files: Sequence[str]) -> list[PlanItem]: ...  # §7.5, unchanged
def to_json(reg: ResolvedRegistry) -> dict: ...                                      # unchanged role
```

**CLI delta (§7.10).** `resolve [--schema <s>] [--pack <n> ...]`: `--schema` defaults to
`hos.dimension-registry`. An unknown value is **exit 1** with code `unknown_kind`, not exit 2, because the
value is checked against data and not against the parser. With no `--pack`, the pack set comes from
`contract/resolved-packs.txt`. `plan` is dimension-only and does not take `--schema`. The exit vocabulary
and the stderr line form are unchanged. **The CLI must convert L2 (`yaml_unavailable`) into exit 1 and
its standard stderr line, never a traceback.** This is the registry CLI's equivalent of TD-D23's P0.

#### C.2.8 Shared posture validation (TD-D26), and how L12 now reaches V1–V14

**TD-D26 — V1–V14 move to `scripts/automation/lib/posture.py`, an L1 module. W1's L2 keeps its exact
behaviour through an adapter.** TD-VF-20 shows that the loader can neither import L2 nor safely copy
fourteen security rules.

`posture.py` contract:
- It exports `KNOWN_POSTURES` (moved; L2 re-exports the same object), `Posture` (the dataclass L2 returns
  today, moved unchanged), `PostureError(Exception)` with attribute `rule: str ∈ {"V1", …, "V14"}`, and
  `load_posture(repo_root: Path, name: str) -> Posture`.
- **Rule semantics are byte-for-byte the current `agent_invoke_cli.py:302-413`.** That includes V14's
  absolute-token rejection and the sha256 over `settings_bytes + b"\0" + sidecar_bytes`. The only change
  is that each failure raises `PostureError(rule=…)` in place of the two L2-private exceptions.
- It imports only the standard library: `json`, `os`, `re`, `hashlib`, `dataclasses`, `pathlib`. **No
  `yaml`**, so TD-D23's "exactly one third-party import in L2" invariant is untouched.

`agent_invoke_cli.load_posture` becomes an adapter. It calls `posture.load_posture`, maps
`PostureError(rule="V1")` to `_UsageError` (exit 2, as today), and maps every other rule to
`_PreflightFailure("posture_invalid")` (as today). The stale "V1-V11" header (`:298`) and the stale
"V2-V11" docstring (`:305`) are corrected in the same edit.

**This is a refactor of built, reviewed W1 code**, so its acceptance is behavioural: the full existing
`tests/automation/test_agent_invoke_cli.py` and `test_agent_invoke_wrapper.py` suites pass **without
modification** (T5.46). Because posture validation is a security control, the W5 PR's review set must
include `security-reviewer` on this hunk specifically.

#### C.2.9 The extension point #1644 T3.1 uses

T3.1 (`contract/stages/core.yaml`, ADR-1644 AD-C1) adds a kind by making **exactly** these changes and no
others to W5's code:

1. **One `KINDS` row** in `dimension_registry.py`: the stage-graph `schema` string (T3.1's TD names it;
   `hos.stage-graph` is illustrative only), `directory="contract/stages"`, `pack_source="stages.yaml"`,
   `handler_module="scripts.automation.lib.stage_registry"`, its closed `top_level_keys` per owner,
   `core_only_keys` (per AD-C1, at least the stage and transition declarations, since only CORE declares
   them), and `project_only_keys` (its own choice; it may be empty).
2. **One handler module**, `scripts/automation/lib/stage_registry.py`, exposing
   `resolve(docs: tuple[LayerDoc, ...], ctx: LoadContext) -> <its resolved type>` and
   `to_json(<resolved>) -> dict`. It implements AD-C1's load checks (unreachable stage, non-terminal stage
   with no outgoing transition, PACK/PROJECT declaring or removing a stage or transition, cap above
   maximum, stage-timeout-plus-margin > budget) as **its own** dim-specific-style rules with their own
   codes and order, raising only `RegistryError`.
3. **One `_REGISTRY_KINDS` row** in the installer (§C.2.11 item 2): `stages.yaml:contract/stages`.

**What the engine guarantees T3.1, so its TD need not re-specify them:**
- File location and the absent-`project.yaml` and absent-`pack-<n>.yaml` semantics.
- The pack set (§C.2.5), and the generic rules L1–L5, L18, L20 and L22–L26 in §C.2.6's order.
- YAML parsing.
- Ordered `LayerDoc`s (core first, packs in closure order, project last).
- Fail-closed wrapping of handler crashes (L26).
- The installer copying `packs/<n>/stages.yaml` to `contract/stages/pack-<n>.yaml`, pruning stale ones,
  and emitting manifest rows (§C.2.11).

**The runtime hook.** ADR-1644 AD-C1 requires the fits-one-cycle check to run **again at executor start
against the live `HOS_CRON_MAX_SECONDS`** (`ADR-1644:236-241`). The engine never reads the environment.
The executor passes `runtime={"cron_max_seconds": <int>}` to `load_registry`, and the handler reads
`ctx.runtime`. The dimensions handler ignores `runtime`. The load-time check uses the default and the
executor-start check uses the live value, with one loader and no environment read in L1.

**What T3.1 must not do:** add a second YAML reader, read `PACK=`, re-derive the pack closure, add a
`register_kind()` call, or put kind-specific behaviour into the engine. If T3.1 finds the generic rule set
wrong for graphs, that comes back to this document as a contract change. It is not patched around in
the handler.

#### C.2.10 `run_post_change_sweep.sh` (TD-D29, TD-D30) — supersedes §7.9's usage line, exit codes, and interpreter

**TD-D29 — the input grammar is today's, unchanged. `--framework-only` is removed. `--json` is added.**

```
Usage: run_post_change_sweep.sh [--json] [HEAD<ref-suffix> | --staged | <file> ...]
```
- Changed-file computation is **byte-for-byte today's** (`:40-53`). An explicit file list wins, then
  `--staged` (`git diff --cached --name-only`), then a positional `HEAD*` ref (`git diff --name-only
  <ref>`). With none of those, it uses `git diff --name-only HEAD`, falling back to `HEAD~1` when that is
  empty. Today's quirk is kept and stated: a non-`HEAD*` ref such as `origin/main` is taken as a *file
  name*. Fixing that quirk is out of scope, because the pointer contract is "keeps today's input grammar".
  **One narrowing (architect, round 1, binding):** a positional argument that is neither an existing
  worktree or index path nor `HEAD*` is rejected with exit 2 when `git rev-parse --verify --quiet
  <arg>^{commit}` succeeds. The stderr line names the HEAD-relative form. Today that input produces
  prose nobody acts on. Under the registry it would produce a confident "no review dimension applies"
  for a diff that was never computed, and an explain tool must not say that. Every other form is
  unchanged. T5.48 adds the case.
- **`--framework-only` is removed.** It filtered on `categorize()`'s `framework` domain, which no longer
  exists. The framework-validator binding it surfaced is HOS-only PROJECT data (§7.2), and it already
  appears in HOS's plan without a flag. Passing it is **exit 2**, with the stderr line
  `run_post_change_sweep.sh: --framework-only was removed by ADR-1643 W5 (AD-11); the plan now comes from the registry`.
  It is never silently ignored.
- `--json` makes stdout exactly the CLI's `plan` JSON (T5.30, unchanged).
- The script passes the computed list to `dimension_registry_cli.py plan --changed-file <p> …`. **When the
  list is empty** it calls `dimension_registry_cli.py resolve` instead, so a broken registry still
  fails. It then prints `No changed files — no review dimension applies.` (or, under `--json`, `[]`) and
  exits 0.

**Exit codes (replace both today's and §7.9's):**

| Exit | Meaning |
|---|---|
| `0` | Explained. This **includes an empty change set**, which used to be exit 1. TD-VF-19 found no caller of the old meaning |
| `1` | The registry could not be explained: any `RegistryError` (the CLI's `dimension_registry: <code>: …` line passed through on stderr), no interpreter resolvable, or `dimension_registry_cli.py` absent (TD-D30) |
| `2` | Usage error, including `--framework-only` and unknown flags |

**TD-D30 — the interpreter is resolved by Amendment A's ladder, and a missing CLI fails closed.** The
script resolves Python with the **same three rungs, in the same order** as `bootstrap/invoke_agent.sh`
(TD-D22):
1. `$HOS_REGISTRY_PYTHON` if set. If it is set but not executable, exit 1.
2. `<repo>/scripts/oversight/.venv/bin/python` if executable.
3. `python3` on `PATH`.

If none resolves, exit 1 with a stderr line naming all three and `bash scripts/oversight/ensure_venv.sh`.
**Before** launching, it checks that `<repo>/scripts/automation/dimension_registry_cli.py` is a regular
file. If it is not, the script exits 1 with:
`run_post_change_sweep.sh: scripts/automation/dimension_registry_cli.py is not installed — the registry is not available in this checkout (ADR-1643 TD-VF-21)`.
That line is the expected outcome on every consumer install until §C.4 Q1 is ruled. It is loud and
non-zero, never a silent empty plan. The ladder is **duplicated** from `invoke_agent.sh`, not sourced
from it. T5.48 pins the two to the same rungs, and extracting a shared helper is §C.4 Q2.

The other §7.9 bullets stand: `categorize()` and the Track block are deleted, the last two lines are
deleted, the CLAUDE.md row is reworded, and the agent edit is deferred to W7 (ESC-K).

#### C.2.11 Installer — supersedes §7.7 items 1, 2 and 4 (TD-D31, TD-D32)

**Item 1 (revised) — fourteen individual lines are added to `framework_consumer_files.txt`.** They are
`contract/dimensions/core.yaml`, `contract/dimensions/project.yaml.template`, the four
`contract/dimensions/postures/*.{settings,hos}.json` files, and **the eight**
`contract/dimensions/prompts/{code-review,security,privacy,reliability,ops,ui,a11y,infra}.md` (TD-VF-18).
Each is one literal path, because the loop is literal-file only (`:1906-1916`). This edit alone gives
overwrite-on-upgrade and `.hos-manifest` tracking, both through the existing list. **Never listed:**
`contract/dimensions/project.yaml` (HOS's own PROJECT layer, TD-D19) and `contract/resolved-packs.txt`
(installer-generated per target, §C.2.5). T5.47 asserts both absences.

**Item 2 (revised) — TD-D31: pack data is copied by one table-driven step that runs once, outside the
per-agent loop, after Phase B.**
- **Table.** One bash array literal, `_REGISTRY_KINDS=( "dimensions.yaml:contract/dimensions" )`, where
  each row is `<pack_source>:<directory>`. T3.1 appends its row. T5.44 asserts that this array equals
  `{(k.pack_source, k.directory) for k in KINDS.values()}`.
- **Pack directories are resolved once.** At R3 (`:1287-1288`), the already-resolved `$_pack_dir` is
  appended to a parallel array `_resolved_pack_dirs`. The new step reads that array and **never calls
  `_resolve_pack_dir` again** (the B-4 rule: it logs).
- **Placement.** The step runs once per install, in the `contract/` section (after `:2122`) and before
  the `.hos-manifest` block (`:2191`). Phase A's abort exits 4 before this point (`:1634`), so a
  drift-blocked install writes no registry data, which preserves decide-all-then-act (TD-VF-15).
- **Behaviour, for each kind row:**
  1. For each pack in `_resolved_packs` order, if `<pack_dir>/<pack_source>` exists, run
     `cp_framework_file` to `<directory>/pack-<slug>.yaml`.
  2. Then, for every `<directory>/pack-*.yaml` on disk whose slug is not in `_resolved_packs`, remove it
     through `run`, so that `--dry-run` prints the deletion and does not perform it. This replaces §7.7
     item 2's second bullet with the same semantics, applied per kind.
- **Then, once and not per kind**, write `contract/resolved-packs.txt` per §C.2.5 from `_resolved_packs`.
  Under `--dry-run`, print the would-be contents instead. Under `--no-pack` the file has zero slug lines.

**Item 4 (revised) — TD-D32: manifest rows for generated files are emitted explicitly.** The installer
keeps an array, `_generated_whole_rows`. After each successful copy in item 2, and after writing
`resolved-packs.txt`, it appends `"<target-relative-path>\tWHOLE\t<sha256 of the TARGET file>"`, computed
with the existing `_sha256`. The array is concatenated with `enumerate_framework_files`' output before
it feeds `assemble-manifest` (`:2232-2253`). Under `--dry-run` nothing is appended, which matches the
existing dry-run manifest branch (`:2230-2231`). The **L20 belt-and-braces point from §7.7 item 4 stands
unchanged**: the loader still enforces L20, because `--prune` is opt-in and a hand-copied tree can still
carry a stale file.

Items 3 (`project.yaml` is never created) and 5 (no `--squash` interaction) **stand**.

#### C.2.12 Tests — additions to §9.5

- **T5.3** splits into **T5.3a** (L3a, including a stage-schema file in `contract/dimensions/`) and
  **T5.3b** (L3b).
- **T5.5, T5.12 and T5.18** assert the renamed codes: `core_only_key`, `posture_invalid` and
  `project_only_key`.
- **T5.32 (re-pointed):** a `pack-<n>.yaml` whose `<n>` is absent from `contract/resolved-packs.txt` gives
  `stale_pack_file`. A companion case has `config.sh` say `PACK="<n>"` while the file omits `<n>`, and
  must still give `stale_pack_file`. That proves `PACK=` is not read.
- **T5.34–T5.40:** one test per new rule, L22–L28, each asserting its exact code. T5.36 covers an absent
  file, a bad slug, a duplicate slug, and an explicit `packs=` with a duplicate.
- **T5.41:** the check order. One two-defect fixture per adjacent pair at the step boundaries of TD-D28
  (L2 with L26, L20 with L3a, L5 with L23, L27 with L10, L17 with L19) asserts the earlier code.
- **T5.42:** a resolved pack closure `{node, astro}` in `resolved-packs.txt`, with `config.sh`
  `PACK="astro"` and both `pack-*.yaml` present, **loads cleanly**. This is the regression test for
  TD-VF-16.
- **T5.43:** `to_json(load(root))` is byte-identical to
  `registry_to_json(DIMENSIONS_SCHEMA, load_registry(root, DIMENSIONS_SCHEMA))`.
- **T5.44:** `_REGISTRY_KINDS` in `hos_install.sh` equals the `KINDS` table's `(pack_source, directory)`
  pairs.
- **T5.45 (the seam, proven without T3.1):** a test-only `KindSpec` and a fixture handler are patched into
  `KINDS`, and the test then checks four things. The generic rules fire for it (L1, L3a, L5, L20, L23).
  The handler receives `LayerDoc`s in closure order. A handler that raises `KeyError` gives
  `kind_handler_failed`. `runtime=` reaches `ctx.runtime` unchanged. A fixture handler that raises the
  engine's `RegistryError` imported by its qualified name surfaces that error's own code, not L26. After
  `load()`, `sys.modules` holds exactly one engine module (architect, round 1: module identity, §C.2.4).
- **T5.46:** (a) the existing W1 suites pass unmodified (TD-D26's gate). (b) `posture.load_posture`
  raises `PostureError` with the right `rule` for one fixture per V1–V14. (c) L12 surfaces each of those
  as `posture_invalid` with the rule id in the message.
- **T5.47 (installer):** `--pack astro` writes `resolved-packs.txt` as `node` then `astro`. `--no-pack`
  writes zero slug lines. Each `pack-<n>.yaml` is copied **once**, asserted by counting the
  `cp_framework_file` log lines per target. `.hos-manifest` holds WHOLE rows for every
  `pack-<n>.yaml` and for `resolved-packs.txt`, with the target's sha256. `framework_consumer_files.txt`
  lists all 14 item-1 paths and lists neither `project.yaml` nor `resolved-packs.txt`. A drift-blocked
  (exit 4) install leaves `contract/dimensions/` untouched.
- **T5.48 (sweep):**
  - Each of today's four input forms produces the same changed-file list as the pre-rewrite script, in a
    characterisation test written before the rewrite.
  - `--framework-only` exits 2 with the named line.
  - An empty change set exits 0, after `resolve` ran.
  - A `RegistryError` exits 1, with the code on stderr.
  - An absent CLI exits 1, with the TD-VF-21 line.
  - The three interpreter rungs behave as T1.50-style cases.
  - The ladder's rungs match `invoke_agent.sh`'s.

### C.3 Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design?*
- **Schema-parametricity: no.** It arises from ADR-1644 SEAM-1, a binding input that postdates §7. This is
  a late requirement, not a missed one.
- **TD-VF-15…TD-VF-21: yes.** Every contradicted fact was in the tree when §7 was written:
  - the leaf-only `PACK=` (#1036 closure);
  - the source-path manifest enumeration;
  - the literal-path ship loop;
  - the sweep's grammar and exit codes;
  - V12–V14, which landed with Amendment 5 after §7 but before this amendment.

  §7.7 claimed to be "verified against `hos_install.sh`'s actual implementation", and in these respects
  it was not. **This is a `startup-artifact-gap`. The orchestrating session should open or annotate
  one.** I file nothing (task constraint).

**Affected sign-offs:**
- **W5:** unbuilt. No code was approved against the old §7, so there are **no orphaned approvals**.
- **W1:** the sign-offs on `agent_invoke_cli.py` **stand**, because W1's behavioural contract (V1–V14
  outcomes and exit codes) is unchanged. TD-D26 adds new code, the extraction itself, and that code
  needs **fresh** review in the W5 PR: `code-reviewer` plus `security-reviewer`. Prior W1 approvals do
  not cover it.
- **W2–W4, W4b:** untouched. Their sign-offs stand.
- **#1644 T3.1:** its future TD now builds on §C.2.9. No T3.1 design has been approved yet, so nothing is
  invalidated.

### C.4 Open questions and escalations

To `architect` (blocking W5's coder only where marked):

- **Q1 (BLOCKING for the consumer half of W5; ESC-E is extended):** TD-VF-21. The W5 sweep is shipped, but
  the registry it calls is not. Option (a): ship `scripts/automation/{__init__.py, lib/__init__.py,
  lib/dimension_registry.py, lib/posture.py, dimension_registry_cli.py}` in W5. That brings the consumer
  PyYAML dependency with it, since consumers have no venv (Amendment A). Option (b): take
  `run_post_change_sweep.sh` out of the consumer ship-set until W7 makes the ESC-E ship-set decision.
  Until a ruling, TD-D30 makes the consumer outcome a loud exit 1, which is correct but not useful. I
  have not chosen, because this is ESC-E's decision and ESC-E was routed to the architect.
- **Q2 (non-blocking):** should the interpreter ladder move into one sourced helper (for example
  `bootstrap/lib/resolve_python.sh`) for `invoke_agent.sh` and the sweep? TD-D30 duplicates it and pins
  the copies with T5.48. A helper would mean editing `invoke_agent.sh`, which is built W1 code, so I
  did not specify it.
- **Q3 (non-blocking):** TD-D25 keeps the engine at AD-9's bound path, `dimension_registry.py`, although
  it now loads the stage graph too. A rename to something like `registry.py`, with a `dimension_registry`
  shim, would be an AD-9 path change and is the architect's call.
- **Q4 (confirm):** L5 and L18 are generalised and their codes renamed (`core_only_key`,
  `project_only_key`), and L12's code becomes `posture_invalid`. W5 is unbuilt, so nothing depends on the
  old codes. Please confirm the renames rather than inherit them.

To a **human** (gated on the protected-surface PR in any case): `contract/resolved-packs.txt` is a new
installer-written file under `contract/**`. In a consumer repo, every pack change therefore becomes a
CODEOWNERS-gated diff in two places, the pack YAML and this file. I judge that correct, since the pack set
is governance data, but it is a new class of generated protected-surface file, and a human should see
it named.

#### C.4.1 Architect rulings — Amendment C round 1 (2026-10-02)

**Verdict: APPROVED_WITH_EDITS.** The round-1 edits are applied in place and marked "architect, round 1"
(§C.2.1, TD-VF-21, §C.2.4, L27, L28, TD-D28, TD-D29, T5.41, T5.45). TD-VF-15, -16 and -18 were re-checked
against `hos_install.sh` at the cited lines, and all three hold.

- **Q1 (technical ruling, then ESCALATED for the product-boundary checkpoint).** The technical answer is
  **option (b)**. Remove `scripts/framework/run_post_change_sweep.sh` from `framework_consumer_files.txt`
  in W5, and return it to the ship-set in W7 together with the registry modules, as one ESC-E ship-set
  decision.
  - Reasons: ESC-E (ADR-1643 §9.6) is already ruled. `scripts/automation/**` reaches consumers at W7 as
    one decision, not piecemeal. Shipping a tool that always exits 1 is dead weight. No shipped agent
    calls the script (TD-VF-21, verified).
  - Option (a) is rejected on sequencing, not merit. PyYAML is already a declared consumer dependency,
    so (a) is cheap. But it would pre-empt W7's ship-set decision with a partial one.
  - The removal changes what consumers receive. Existing installs keep their pre-W5 copy, which the
    `.hos-manifest` orphan check reports and `--prune` archives. New installs get no script. That is a
    consumer-visible change, so it **does not bind until the human clears it**.
  - **W5 coding is not blocked.** Everything except that one ship-list line proceeds. TD-D30's
    fail-closed guard is required under either answer, because HOS's own tree and hand-copied trees
    need it. The W5 PR body must carry the escalation question below, and the ship-list line lands as
    the human answers.
- **Q2 (ruled): no shared helper in W5.** TD-D30's duplicate, pinned by T5.48, stands.
  - The ladder already exists in at least four places (`invoke_agent.sh`, `prompt_audit.sh`,
    `run_tests_inner_loop.sh`, `run_gates.sh`), with differing rungs.
  - A helper extracted for two of the five would standardise nothing.
  - Extracting it is a cross-cutting refactor of built code with its own review set. It is a follow-up
    issue for the orchestrating session to file, covering every ladder site. It is not W5 scope.
- **Q3 (ruled): no rename, and no shim.** `scripts/automation/lib/dimension_registry.py` is AD-9's bound
  path. ADR-1644 §4 explicitly amends nothing in ADR-1643. A shim would create a second import path for
  the module whose identity §C.2.4 now pins. The name undersells the module. That is a documented
  cosmetic cost, and it is final.
- **Q4 (ruled): renames confirmed.** `core_only_key` and `project_only_key` are confirmed. So is
  `posture_invalid`, which also aligns with W1's existing `_PreflightFailure("posture_invalid")`
  vocabulary. **Added:** L28 gets its own code, `unknown_item_key`. One rule, one code, so TD-D28's
  fixed-order tests can tell the two apart.
- **`contract/resolved-packs.txt`: ADDITIVE, not structural.** No separate human gate is needed beyond
  the CODEOWNERS approval the W5 PR already requires.
  - There is precedent for an installer-written file under `contract/**`: `contract/step-manifest.yaml`
    (`hos_install.sh:2116-2122`).
  - The file holds no user data.
  - It changes only in the same install that already changes the `pack-*.yaml` files beside it, so the
    marginal review burden is one extra line in a diff the consumer already reviews.
  - The W5 PR body must still name it, as the TD's paragraph above asks.
- **Exit-code change and `--framework-only` removal (TD-D29).** HOS-internal, these are within this
  amendment. They become consumer-visible only if the human answers Q1 "keep shipping". In that case
  they are part of the same clearance.

**Human escalation (product-boundary checkpoint, routed via `pm-agent` and the human):**
> W5 rewrites `run_post_change_sweep.sh` to read a registry whose Python modules do not ship to consumers
> until W7 (ESC-E). Should W5 (b) **stop shipping the script to consumers until W7**, which is the
> architect's recommendation? Under (b), existing installs keep their old copy, flagged as orphaned. New
> installs get none. No shipped agent calls it. Or should W5 (c) **keep shipping it**, so that on consumer
> installs it fails loudly with exit 1 until W7, and its empty-change exit code moves from 1 to 0?

**Startup-gap:** this concurs with §C.3. TD-VF-15…TD-VF-21 are a `startup-artifact-gap`. The
orchestrating session should open or annotate the issue. No prior sign-off is orphaned, because W5 is
unbuilt and the W1 sign-offs stand under TD-D26's unmodified-suite gate.

---

## Human Review Required — Amendment C (2026-10-02, schema-parametric W5 loader)

**RISK: MEDIUM.** The amendment governs:
- the loader that gates the overseer's review set, so a fail-open there would let a configuration require
  nothing;
- where a security control (posture validation, V1–V14) lives;
- the installer's handling of data files under a protected surface.

Nothing is built against it yet. The one built-code change (TD-D26) has to preserve behaviour, and
the unmodified W1 suites pin that.

**CONFIDENCE:**
- **HIGH on TD-VF-13…TD-VF-21.** Each was re-read in the tree this session at the cited lines. None is
  inferred from a document. TD-VF-16, TD-VF-17 and TD-VF-19 each quote the installer's or the script's
  own comments.
- **HIGH that the dispatch seam satisfies SEAM-1 and AD-12.** There is one engine, one ownership model,
  `schema:` as the declared kind, and handlers that never re-implement file location, pack resolution or
  YAML.
- **MEDIUM on the rule classification at the margin.** L6 and L7 (id uniqueness and namespacing) are
  classified dimension-specific because AD-C1's "exactly one binding per stage" may want different
  semantics. If T3.1 finds it wants them generic, promoting them is additive.
- **MEDIUM on TD-D29's exit-0 for an empty change set.** No programmatic caller exists (verified), but
  `docs/` and operator habit may assume exit 1. Those docs are W5's to update.

**BLAST RADIUS:**
- **This document:** the Amendment A/B/C header block; the pointer notes in §7.3, §7.4, §7.7 and §7.9;
  and this Amendment C body.
- **Downstream (W5's coder):** `scripts/automation/lib/{dimension_registry,posture}.py`,
  `scripts/automation/{dimension_registry_cli,agent_invoke_cli}.py`,
  `scripts/framework/run_post_change_sweep.sh`, `scripts/framework/framework_consumer_files.txt`,
  `bootstrap/hos_install.sh` (the R3 parallel array, the new registry-data step, and the manifest
  concatenation), and `contract/resolved-packs.txt`.
- **Forward:** #1644 T3.1's design surface (§C.2.9).
- **Not touched:** W1–W4/W4b contracts, the AD-6 document, the classifier, and every §7 section that
  §C.2.1 marks "stands".

**Change classification: ADDITIVE.** No built contract is reversed: W5 is unbuilt, and W1's posture
behaviour is preserved. The amendment adds a seam, a generated file, seven rules and three corrections of
unbuilt instructions. I have not classified it STRUCTURAL. If the architect judges either of the
following structural, it goes to a human before the coder starts:
- `resolved-packs.txt`, as a new installer disposition under `contract/**`;
- the change in the shipped sweep's exit-1 meaning.

**Architect review is requested.** This amendment is not handed to the coder until the architect
approves. Iteration: Amendment C round 1. No temp-state file was written, because this dispatch was
constrained to edit this one file only.

**Not done here:** no application code, test code or script was written. No issue was filed and no
label was created. No sign-off register entry was written (`technical-design` writes none).

---

## Amendment D (2026-10-02) — W5b: the registry data, the prompt-file contract, and T5.28

**Status:** **APPROVED_WITH_EDITS (architect, round 1, 2026-10-02 — §D.10). Binding on W5b.** W5 was split for the 15-file limit.
**W5a has merged** (PR #1933, `main` at `7330962bb`): the engine, `posture.py`, the CLI, and the tmp-tree
tests T5.1–T5.27, T5.29, T5.32, T5.34–T5.43, T5.45, T5.46. **W5b** is the real registry *data* plus T5.28.
**W5c** (the sweep rewrite, the installer, the ship-list, CLAUDE.md, T5.30/31/33/44/47/48; gated on
#1930 and #1932) is **not designed here**. W5b changes **no** engine code. Where this amendment and §7 or
Amendment C disagree, this amendment governs. Everything it does not name stands.

**Numbering.** TD-VF-22…TD-VF-27, TD-D33…TD-D41, tests T5.28 (re-specified) and T5.49…T5.53.

### D.1 Verification findings — TD-VF-22…TD-VF-27 (tree at `7330962bb`)

**TD-VF-22 — CONTRADICTS §7.2: the HOS framework-validator predicate silently drops two `categorize()`
paths.** `run_post_change_sweep.sh:68` routes `^docs/AGENTS\.md$` and `^docs/OVERSIGHT-RUNBOOK\.md$` to
the framework track. §7.2's `project:code-review/framework-validator` omits both, and both files exist.
AD-11's row says "(+ add `^bin/`, …)" (`ADR-1643:561`). That is additive, not a licence to narrow.
**Corrected in §D.3.2.**

**TD-VF-23 — CONTRADICTS §7.2: the PII predicates lost their case-insensitivity.** `categorize()`'s privacy
grep runs over the lowercased file list (`run_post_change_sweep.sh:181-182`, `tr '[:upper:]' '[:lower:]'`).
§7.2's `['erasure', 'pii']` and the template's `['accounts', 'booking']` are case-sensitive under
`re.search` (§7.5). The effect is that `myapp/PII_Export.py` loses its privacy route. **Corrected** with
`(?i)` prefixes in §D.3.3 and §D.3.4. A leading global flag is valid per pattern, and L14 compiles each
pattern on its own (`dimension_registry.py`, the L14 block).

**TD-VF-24 — No prompt contract exists, and §4.3 already leans on one.** L21 checks only that the file
exists (`dimension_registry.py:605-613`, `(root / tmpl).is_file()`). The registry digest covers the
prompt **path**, not its bytes (`:697` inside `_body`, digested at `:669`). W1's
`--prompt-template-version` is a free-form string (`agent_invoke_cli.py:1227`), carried into
`compute_input_digest` (`:740-771`). AD-6 says the digest covers "the prompt template version"
(`ADR-1643:428`). §4.3 says "our own agent is instructed by our own prompt template" (TD `:1153`).
Nothing in §7, §C, or the tree says what a template contains, how its version is named, or where the
output contract comes from. **Closed by TD-D33…TD-D35.**

**TD-VF-25 — Every deterministic `tool:` exists, is executable, and ships.** `git ls-files -s` shows
mode `100755` for `lint_check`, `type_check`, `secret_scan`, `security_scan`, `bash_check`,
`portability_check`, `template_refs_check`, `collection_integrity`, `django_check` and `astro_check`
under `scripts/oversight/gates/`, and for `scripts/run_second_review.sh`. That satisfies L11
(`dimension_registry.py:577-587`). Consumers receive `scripts/oversight/` wholesale
(`framework_consumer_files.txt:8`) and `run_second_review.sh` at `hos_install.sh:1842`. Two gate files are
deliberately **unbound**:
- `check_suspension.sh` (`100644`) is a sourced library. `run_gates.sh:158` excludes it.
- `expensive_gates_stub.sh` is a stub.

`run_gates.sh:158` runs every other gate, including `django_check` and `astro_check`, in every project.
The registry moves those two to their packs. That is **not** a narrowing in W5b, because `run_gates.sh` is
unchanged and the registry gates nothing until W8.

**TD-VF-26 — `packs/**` is not a protected surface.** `protected_surfaces.txt:16-33` lists `contract/**`
(`:17`) and `scripts/oversight/gates/**` (`:29`), but has no `packs/` entry. In the HOS source,
`packs/<n>/dimensions.yaml` has no CODEOWNERS gate. It becomes gated only when the installer writes it to
a consumer's `contract/dimensions/pack-<n>.yaml`. The same is already true of every `packs/<n>/<agent>.md`
region body. **Routed (§D.8 Q5), not changed here.**

**TD-VF-27 — Both #1933 carry-overs reproduce on the merged engine (probed).**
- An empty core loads green. A `core.yaml` with only `schema`/`schema_version`/`owner` returns 0 entries
  and 0 bindings. L19 (`:633-639`) iterates over entries, so zero entries means zero failures.
- PyYAML 6.0.3 `safe_load("a: 1\na: 2\n")` returns `{'a': 2}`, and the engine calls `safe_load` at
  `:179`.

**Probe of this amendment's data.** The YAML in §D.3 was staged into tmp trees with the real postures,
the real `.claude/agents/`, the real gates (`copy2`), and stub prompts. It was then loaded through the
merged `load()`, and loads green for:
- zero packs plus HOS `project.yaml`: 17 entries, 18 bindings;
- `{django}`: 24;
- `{node, astro}` (no `pack-node.yaml`): 23;
- `{django, node, astro}`: 29.

The T5.28 table in §D.5 is that probe's output.

### D.2 The prompt-file contract (TD-D33, TD-D34, TD-D35)

**TD-D33 — a prompt scopes a dimension and nothing else. Its shape is fixed and testable.** Each of
`contract/dimensions/prompts/<entry-id>.md`, for `<entry-id>` ∈ {code-review, security, privacy,
reliability, ops, ui, a11y, infra}:
1. UTF-8, LF line endings, a final newline, **≤ 20 lines**.
2. Line 1 is exactly `# Review dimension: <entry-id>`, where `<entry-id>` equals the filename stem and a
   `judgment` entry id in `core.yaml`.
3. There are exactly two `##` sections, in this order: `## Scope`, then `## Boundaries`. Nothing else at
   `##` or deeper.
4. **`## Scope`** says that the review covers the changed files this dimension selected, and contains
   that entry's `core.yaml` `title` **verbatim** (single source, cross-checked by T5.51). It may also say
   that other repository files may be read only to understand the selected ones. It says nothing else.
5. **`## Boundaries`** contains this exact sentence: `This prompt does not add to, remove from, or override
   your agent definition.` It also says that other dimensions run separately and that their findings
   are not to be reported here.
6. **Forbidden content:**
   - any agent name from `scripts/framework/consumer_agents.txt`, or `framework-validator`, because one
     prompt serves several agents (HOS's framework-validator binding uses `code-review.md`);
   - any lens checklist (ADR non-goal 1, `ADR-1643:893-894`: "No lens is widened, narrowed, or
     rewritten");
   - the substrings `{{`, `}}`, `{%`, `${` and triple backticks;
   - the words `verdict` and `applicability`.

   *(architect, round 1 — matching semantics, so T5.51 is deterministic.)* Agent names are matched
   case-insensitively as whole hyphen-aware tokens, `(?i)(?<![a-z0-9-])<name>(?![a-z0-9-])`, so
   `code-review` does not trip on `code-reviewer` and the reverse also holds. The two words are matched as
   `(?i)\bverdict` and `(?i)\bapplicab`, which also catches plurals and `applicable`.
7. *(architect, round 1 — added. Rules 4 and 5's "says nothing else" is not testable as written, and an
   untestable rule in a prompt contract is exactly where a lens checklist creeps back in, against ADR
   non-goal 1.)* **Each file's bytes equal this canonical text**, without this document's three-space list
   indentation and without the fence, with `<entry-id>` and `<title>` substituted from `core.yaml`. Every line ends in LF, and there is a final newline:

   ```
   # Review dimension: <entry-id>

   ## Scope

   Dimension title: <title>

   Review only the changed files that this dimension selected.
   You may read other repository files only to understand the selected files.

   ## Boundaries

   This prompt does not add to, remove from, or override your agent definition.
   Other review dimensions run separately. Do not report their findings here.
   ```

   T5.51 asserts byte equality for each of the eight files, **in addition to** rules 1–6. Rules 1–6 stay,
   because they guard the canonical text itself if it is ever amended. Any per-dimension divergence from
   this text is a W7 design decision, not a W5b coder's.

**Binding rule (test-pinned, not a loader rule).** Every shipped or HOS binding's `prompt_template` is
`contract/dimensions/prompts/<binding.entry>.md`. W5b adds no loader rule for prompt structure. A
consumer PROJECT binding may point anywhere that passes L21 and L27. Whether W7 needs a structural load
rule is W7's call.

**TD-D34 — a template's version is its content hash, never a hand-maintained string.** The
`prompt_template_version` for a binding is `sha256:<64 lowercase hex>` over the template file's exact
bytes. The caller computes it when it invokes the agent (W7) and passes it through W1's existing
`--prompt-template-version`. No W1 change is needed, because the flag is free-form. Templates carry **no**
in-file version field. *Reason:* AD-13 reuses a record when `input_digest` is unchanged. A hand-bumped
version that someone forgot to bump would reuse a verdict produced under different instructions. That is
a fail-open, and a content hash cannot have it. §4.1's `"security/v1"` is illustrative only and does not
override this decision.

*(architect, round 1 — decision confirmed, reason corrected.)* The *Reason* above overstates the hole.
- W1 already digests `input_file_sha256` (§4.4; `agent_invoke_cli.py:740-771`). L2 refuses every
  unrecognised flag (§3.2), so `--input-file` is the only channel for instructions other than the agent
  file, and the agent file is digested too.
- Whatever bytes W7 sends are therefore already in `input_digest`. A forgotten hand bump could not cause
  reuse across different sent bytes.
- What a hand-maintained string actually breaks is **provenance**. A record's `prompt_template_version`
  must identify, checkably, which shipped template file produced it, and `"security/v1"` can be checked
  against nothing. The content hash is that identity, and it is defence in depth if W1 ever gains a second
  instruction channel.

**Rule:** the value is always `sha256:` over the template **file's** bytes as read from disk. W7 reads
the file once and renders from those same bytes. The value is never computed over rendered output; that
is `input_file_sha256`'s job (see TD-D35 (c), as superseded). No conflict with AD-6 or W1: AD-6's
"prompt template version" component now has a defined value, and W1's free-form flag carries it
unchanged.

**TD-D35 — no placeholder grammar in W5b. Rendering and the output contract are W7's.** Nothing renders a
template before W7. Fixing a grammar now would bind W7 to a format that no caller has exercised. Templates
are therefore plain Markdown with no substitution, and rule 6 reserves the obvious delimiters so that W7
can choose one without escaping legacy text. **W7 obligations, recorded here so they are not lost:**
- (a) W7 decides how the template body reaches the agent.
- (b) W7 owns the §4.3 payload instruction (one JSON object; `verdict`/`findings`/`summary`; no
  `applicability`/`outcome`/`input`/`invocation`) as **one** block from one source, never eight copies.
- ~~(c) If W7 renders anything beyond the raw file, TD-D34's hash covers the rendered instruction bytes,
  including (b)'s block, not just the file.~~ *(architect, round 1 — superseded. It would make
  `prompt_template_version` mean two different things depending on whether W7 renders, and it duplicates
  `input_file_sha256`.)* It is replaced by:
  - **(c1)** Every instruction byte, including (b)'s block, reaches the agent **only** through
    `--input-file`, so `input_file_sha256` covers the rendered whole. W7 adds no other instruction channel
    to W1 without an ADR-1643 amendment.
  - **(c2)** Rendering is deterministic for identical inputs: no timestamps, nonces, run ids or absolute
    paths in the input file. A non-deterministic render does not fail open, but it silently defeats
    AD-13 reuse on every cycle and so falsifies W6/W7's cost numbers.

What each prompt says (the entry title is quoted from `core.yaml`; no other per-dimension text):

| File | `## Scope` names (verbatim title) |
|---|---|
| `code-review.md` | General code quality, design conformance, and idioms |
| `security.md` | Security lens |
| `privacy.md` | Privacy and data-handling lens |
| `reliability.md` | Resilience to external-dependency failure |
| `ops.md` | Telemetry-spec conformance |
| `ui.md` | UI/UX conformance |
| `a11y.md` | Accessibility |
| `infra.md` | Infrastructure and deployment |

### D.3 The data files, literal

#### D.3.1 `contract/dimensions/core.yaml` (TD-D36) — supersedes §7.2's `…` and folds in §7.8

The header comment, the 17 `entries`, and the six judgment bindings from `core:code-review/code` through
`core:infra/deploy` are **§7.2 verbatim**. §7.2's `ui`/`a11y` comment block (`:1693-1696`) is replaced
by §7.8's two bindings, verbatim, placed after `core:infra/deploy`. The deterministic section is
**exactly** these nine bindings, in this order:

```yaml
  # ── deterministic bindings ────────────────────────────────────────────────
  # Tool invocation arguments are W7's. W5b binds existence and applicability only.
  - id: core:lint/all
    entry: lint
    kind: deterministic
    tool: scripts/oversight/gates/lint_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:type-check/all
    entry: type-check
    kind: deterministic
    tool: scripts/oversight/gates/type_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:secret-scan/all
    entry: secret-scan
    kind: deterministic
    tool: scripts/oversight/gates/secret_scan.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:security-scan/all
    entry: security-scan
    kind: deterministic
    tool: scripts/oversight/gates/security_scan.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:bash-check/all
    entry: bash-check
    kind: deterministic
    tool: scripts/oversight/gates/bash_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:portability/all
    entry: portability
    kind: deterministic
    tool: scripts/oversight/gates/portability_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:template-refs/all
    entry: template-refs
    kind: deterministic
    tool: scripts/oversight/gates/template_refs_check.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:collection-integrity/all
    entry: collection-integrity
    kind: deterministic
    tool: scripts/oversight/gates/collection_integrity.sh
    timeout_seconds: 300
    predicate: { include: ['.*'] }
  - id: core:cross-vendor-review/all
    entry: cross-vendor-review
    kind: deterministic
    tool: scripts/run_second_review.sh
    timeout_seconds: 1800
    predicate: { include: ['.*'] }
```

**TD-D36:**
- Every gate keeps §7.2's "same shape": `.*`, with a 300 s timeout.
- The gates filter their own inputs today (`run_gates.sh` passes them the change set), so a narrower
  predicate here would be a second, drifting copy of each gate's file filter. W6 measures cost.
- Core totals: 17 entries and 17 bindings (8 judgment, 9 deterministic).

#### D.3.2 `contract/dimensions/project.yaml` (HOS-own, not shipped)

§7.2's file verbatim, **except** that `include` gains two patterns (TD-VF-22):
```yaml
    predicate:
      include: ['^\.claude/agents/', '^scripts/framework/', '^bin/', '^bootstrap/',
                '^contract/', '^AGENTS\.md$', '^CLAUDE\.md$',
                '^docs/AGENTS\.md$', '^docs/OVERSIGHT-RUNBOOK\.md$']
```

#### D.3.3 `packs/django/dimensions.yaml`

§7.2's file verbatim, **except** for `pack-django:privacy/pii-words` (TD-VF-23):
```yaml
    predicate: { include: ['(?i)erasure', '(?i)pii'] }
```

#### D.3.4 `contract/dimensions/project.yaml.template`

The template keeps §7.2's live header (`schema`, `schema_version`, `owner`) and its prose. The commented
example is changed in two ways:
- The example is delimited by the exact marker lines `# --- example: begin ---` and
  `# --- example: end ---`. Every line between them is either `#` alone or `# ` followed by YAML, so
  stripping `^# ?` yields a YAML fragment with `bindings:` and `suppress:` as top-level keys. The
  explanatory prose ("This file is YOURS…", "You may suppress…") sits **outside** the markers.
- `project:privacy/app-modules` reads `predicate: { include: ['(?i)accounts', '(?i)booking'] }`
  (TD-VF-23).

T5.53 makes the example executable, so it cannot rot.

#### D.3.5 `packs/astro/dimensions.yaml` (TD-D37) — replaces §7.2's one sentence

```yaml
schema: hos.dimension-registry
schema_version: 1
owner: pack
pack: astro

bindings:
  - id: pack-astro:code-review/astro
    entry: code-review
    kind: judgment
    agent: code-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/code-review.md
    predicate: { include: ['\.astro$', '^src/pages/', 'astro\.config\.[^/]*$'] }

  - id: pack-astro:security/astro
    entry: security
    kind: judgment
    agent: security-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/security.md
    predicate: { include: ['\.astro$', 'astro\.config\.[^/]*$'] }

  - id: pack-astro:ui/astro
    entry: ui
    kind: judgment
    agent: ui-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/ui.md
    predicate: { include: ['\.astro$'] }

  - id: pack-astro:a11y/astro
    entry: a11y
    kind: judgment
    agent: a11y-reviewer
    posture: review-read-only
    timeout_seconds: 300
    prompt_template: contract/dimensions/prompts/a11y.md
    predicate: { include: ['\.astro$'] }

  - id: pack-astro:deterministic/astro-check
    entry: lint
    kind: deterministic
    tool: scripts/oversight/gates/astro_check.sh
    timeout_seconds: 300
    predicate: { include: ['\.astro$', 'astro\.config\.[^/]*$', '^src/pages/', '^src/content/'] }
```

**TD-D37:**
- **`pack-astro:security/astro` is mine.** §7.2's sentence does not include it. CORE's security
  predicate matches no `.astro` file, yet `.astro` frontmatter is server code, and the astro pack's own
  security depth treats it as a surface (`packs/astro/security-reviewer.md:15`, `:34-35`). Without this
  binding, the pack's security depth would never be invoked on the files it describes. The same holds
  for `astro.config.mjs`, which CORE's `\.js$`/`\.ts$` does not match. It is flagged as challengeable,
  like TD-D12.
- **`^src/content/` on astro-check:** `astro_check.sh:4-6` runs `astro sync` because content-collection
  types depend on it.
- **No `packs/node/dimensions.yaml`.** Astro requires node (`packs/astro/pack.toml:4`). The reasons for
  adding no node file:
  - `categorize()` has no JS rule (`:63-114`), so there is nothing to migrate.
  - CORE's four code predicates already match `.js`/`.ts`, which are node's generic surface.
  - A resolved pack with no `pack-<n>.yaml` is "not an error" (§C.2.6). The probe shows that
    `{node, astro}` loads green.
  - The W5b budget is full (§D.7).
- **Residual gap, recorded and not a regression** (nothing routes these today): `.mjs`, `.cjs`, `.jsx`
  and `.tsx` reach no code-review, security, reliability or ops binding (`.jsx`/`.tsx` reach only
  `core:ui/markup`/`core:a11y/markup`), and `package.json` reaches no security binding. Routed as §D.8 Q4.

#### D.3.6 `contract/resolved-packs.txt` (HOS-own) (TD-D38)

Two comment lines and **zero** slug lines:
```
# HOS source repository: HOS is not installed into itself, so no pack resolves here (ADR-1643 TD-D27).
# Hand-maintained and intentionally empty. Consumer copies are generated by bootstrap/hos_install.sh.
```
**TD-D38:** §C.2.5's verbatim installer header would be false here, because no installer wrote this
file. §C.2.5's format allows any `#` line. T5.49 asserts `read_resolved_packs(REPO) == ()`.

### D.4 New tests — one new file, `tests/automation/test_dimension_registry_data.py` (TD-D39)

**TD-D39:** the data tests live in their own file. W5a's file declares itself tmp-tree-only (its
docstring), and these tests deliberately read the real tree. **No test shells out to
`run_post_change_sweep.sh`** (W5c rewrites it).

**Staging helper (used by T5.28, T5.50, T5.53).** `stage(tmp, packs, project_text|None)` builds a
consumer-shaped tree. It copies:
- the real `contract/dimensions/core.yaml`, `prompts/` and `postures/`;
- the real `.claude/agents/`;
- `scripts/oversight/gates/` and `scripts/run_second_review.sh`, with `shutil.copy2`, which keeps the
  mode bits L11 needs.

It then writes `contract/dimensions/pack-<n>.yaml` as a **byte copy** of `packs/<n>/dimensions.yaml` for
each `<n>` that has one, writes `resolved-packs.txt` from `packs`, and writes `project.yaml` only when
given. **No symlinks:** L27 resolves them and would report `path_escape`.

- **T5.49 — HOS's own committed registry loads green.** It calls `dr.load(REPO_ROOT)`, with no staging
  and with `packs=None`, so it reads the real `resolved-packs.txt`. It asserts:
  - `read_resolved_packs(REPO_ROOT) == ()`;
  - the entry-id set is **exactly** §7.2's 17;
  - the binding-id set is **exactly** the 17 `core:` ids plus `project:code-review/framework-validator`;
  - `source_files == ("contract/dimensions/core.yaml", "contract/dimensions/project.yaml")`.

  This test also closes TD-VF-27's empty-core case **for the shipped file**. It exercises L10 against the
  real `.claude/agents/framework-validator.md`, L11 against the real modes, L12 against the real postures,
  and L25 against the real directory listing.
- **T5.50 — the real pack files load when staged.** For `{django}`, `{node, astro}` and
  `{django, node, astro}`, with no `project.yaml`, it asserts that `load()` is green and the binding-id
  set is exactly core's 17 plus that set's pack ids (6 django, 5 astro). In the three-pack case,
  `lint` resolves `core:lint/all`, `pack-django:deterministic/django-check` and
  `pack-astro:deterministic/astro-check`. That is T5.23 on real data.
- **T5.51 — the prompt contract (TD-D33).** For each of the eight files it checks rules 1–7 (rule 7's
  byte equality was added by the architect in round 1). It also
  checks the binding rule over every binding in `core.yaml`, both pack files and HOS `project.yaml`.
- **T5.52 — shipped YAML has no duplicate keys.** A test-local `yaml.SafeLoader` subclass raises on a
  repeated mapping key. It parses `core.yaml`, `project.yaml`, both pack files, and the template's
  extracted example. This closes TD-VF-27's duplicate-key case **for the shipped data**. The engine rule
  is §D.6.
- **T5.53 — the template example is valid and does what it says.** It extracts the marker block, strips
  `^# ?`, and prepends the template's live header. It stages that as `project.yaml` with `{django}` and
  asserts that `load()` is green. It then asserts that `pack-django:privacy/pii-words` is **absent** from
  `bindings` and present in `suppressions` with the template's reason, and that `privacy` still resolves
  through `core:privacy/governance` and `project:privacy/app-modules`. That is T5.25 on real data.

### D.5 T5.28 — the characterization test, made explicit (TD-D40)

**TD-D40 — the old output is a frozen table committed in the test, captured once from the pre-W5c
script.** Shelling out would break at W5c, and a skip-if-rewritten guard would be a silent skip. The
docstring records the capture command and commit:
`bash scripts/framework/run_post_change_sweep.sh <the 42 corpus paths>` at `7330962bb`, parsing the
`Domain routing:` block (`:147-155`). After W5c the table is history, which is exactly what a
characterization test is.

**§9.5's "minus the three rows … and the two rows …" is replaced by this.** Re-layered rows are
**compared, not excluded**: the fixture loads the layers they moved to. The fixture is
`stage(tmp, ["django"], P)`, where `P` is HOS's real `project.yaml` bindings plus T5.53's extracted
template-example **bindings**, with its `suppress:` dropped so that pii-words stays live. The three
AD-11 re-layered rows (`ADR-1643:563-566`) are therefore all exercised:
- **R1:** the django idioms (`\.py$` app code, `/migrations/`, `/templates/`, `manage.py`) and
  `erasure|pii` → PACK:django.
- **R2:** `accounts|booking` → PROJECT.
- **R3:** `docker-compose.yml`/`Caddyfile`/`scripts/backup.sh` → PROJECT (its `Specs/` half is TD-D13's).

The deliberate drops are the **only** expected narrowings. There are three; X3 was added by the architect in round 1:
- **X1:** `framework-validator` leaves the *consumer* registry (`ADR-1643:567`, `:172` of the script).
  It is still compared here through HOS's PROJECT layer.
- **X2:** the discretionary `privacy-reviewer (check if PII-relevant)` line (`:184`, AF-6.3).
- **X3 (architect, round 1; omitted from §9.5 and from this amendment's draft):** TD-D13's exclusion of
  Tracks 3–5 (`:190-192`).
  - What drops: rows 24–27 lose `unit-test`, rows 34–35 lose `ux-designer → ui-reviewer`, and row 36
    loses `pm-agent`.
  - Track 4's `ui-reviewer` **is a reviewer**, so this is a real narrowing of review routing, not just
    the removal of build-side roles. It is the narrowing TD-D13 decided (§7.6), and the ∅ entries in
    `DOMAIN_AGENTS` encode it.
  - The T5.28 docstring names X1–X3, so that "only expected narrowings" is true.

*(architect, round 1 — verified.)* The `OLD_DOMAINS` column below was re-derived independently. The
current `run_post_change_sweep.sh` was run over all 42 paths at this branch's HEAD, and its
`Domain routing:` block matches the column row for row.

**Comparison.**
- `OLD_DOMAINS[p]` is the frozen domain set.
- `DOMAIN_AGENTS` = {framework: {framework-validator}, application-code: {code-reviewer,
  security-reviewer}, migrations: {code-reviewer, security-reviewer}, templates: {ui-reviewer,
  a11y-reviewer}, infrastructure: {infra-reviewer}, tests: ∅, design-pack: ∅, spec: ∅}.
  - `privacy-reviewer` is absent from application-code and migrations by X2.
  - tests, design-pack and spec are ∅ by TD-D13 (unit-test, ux-designer, pm-agent are build-side).
  - templates and infrastructure map per path. The old Track-2 coupling (`:185-187`, which printed them
    only alongside code) is a dropped quirk.
- `NEW(p) = {i.binding.agent for i in resolve_for_diff(reg, [p]) if i.applicable and
  i.binding.kind == "judgment"}`.
- **(a) No unlisted narrowing:** `⋃ DOMAIN_AGENTS[d] for d in OLD_DOMAINS[p] ⊆ NEW(p)` for every `p`.
- **(b) Exact pin:** `NEW(p) == NEW_EXPECTED[p]` for every `p`, so every widening is a reviewed literal.
- **(c) Coverage:** every one of the 8 domains appears in `OLD_DOMAINS`, and every judgment binding in
  the fixture matches at least one corpus path.

Abbreviations: cr = code-reviewer, sec = security-reviewer, priv = privacy-reviewer,
rel = reliability-reviewer, ops = ops-reviewer, fv = framework-validator, a11y = a11y-reviewer.
`ui` and `infra` are `ui-reviewer` and `infra-reviewer`.

| # | Path | `OLD_DOMAINS` | `NEW_EXPECTED` |
|---|---|---|---|
| 1 | `.claude/agents/coder.md` | framework | fv |
| 2 | `scripts/framework/run_post_change_sweep.sh` | framework | cr fv ops rel sec |
| 3 | `docs/AGENTS.md` | framework | fv |
| 4 | `docs/OVERSIGHT-RUNBOOK.md` | framework | fv |
| 5 | `AGENTS.md` | — | fv |
| 6 | `CLAUDE.md` | — | fv |
| 7 | `bin/hos-cron` | — | fv infra |
| 8 | `bootstrap/hos_install.sh` | — | cr fv ops rel sec |
| 9 | `contract/OVERSIGHT-CONTRACT.md` | — | fv |
| 10 | `myapp/views.py` | application-code | cr ops rel sec |
| 11 | `accounts/models.py` | application-code | cr ops priv rel sec |
| 12 | `booking/services.py` | application-code | cr ops priv rel sec |
| 13 | `manage.py` | application-code | cr ops rel sec |
| 14 | `myapp/pii_export.py` | application-code | cr ops priv rel sec |
| 15 | `myapp/PII_Export.py` | application-code | cr ops priv rel sec |
| 16 | `myapp/erasure.py` | application-code | cr ops priv rel sec |
| 17 | `scripts/oversight/validators/schema.py` | — | cr ops rel sec |
| 18 | `scripts/automation/lib/github.py` | — | cr ops priv rel sec |
| 19 | `myapp/migrations/0001_initial.py` | migrations | cr ops rel sec |
| 20 | `accounts/migrations/0002_erasure.py` | migrations | cr ops priv rel sec |
| 21 | `myapp/templates/myapp/index.html` | templates | a11y ui |
| 22 | `templates/base.html` | — | a11y ui |
| 23 | `static/site.css` | — | ui |
| 24 | `tests/test_views.py` | tests | sec |
| 25 | `myapp/tests/test_models.py` | tests | ops rel sec |
| 26 | `conftest.py` | tests | ops rel sec |
| 27 | `myapp/test_utils.py` | tests | ops rel sec |
| 28 | `docker-compose.yml` | infrastructure | infra |
| 29 | `Caddyfile` | infrastructure | infra |
| 30 | `.env.example` | infrastructure | infra |
| 31 | `deploy/.env.example` | infrastructure | infra |
| 32 | `scripts/backup.sh` | infrastructure | cr infra ops rel sec |
| 33 | `.github/workflows/ci.yml` | — | infra sec |
| 34 | `Specs/v1/design.pack/tokens.json` | design-pack | — |
| 35 | `Specs/v1/design-pack/notes.md` | design-pack | — |
| 36 | `Specs/v1/requirements.md` | spec | — |
| 37 | `README.md` | — | — |
| 38 | `docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md` | — | — |
| 39 | `audit/oversight-log.jsonl` | — | priv |
| 40 | `frontend/src/app.ts` | — | cr ops rel sec |
| 41 | `src/pages/index.astro` | — | — |
| 42 | `astro.config.mjs` | — | — |

Rows 15 and 3–4 are the regression tests for TD-VF-23 and TD-VF-22. Rows 41–42 pin that an uninstalled
pack routes nothing. Row 35 pins the old `design.pack` regex's `.` wildcard. Rows 24–27 show the
TD-D12/§7.2 widening onto test files, which is accepted as more review rather than less.

### D.6 #1933 security carry-overs (TD-D41)

**TD-D41 — W5b closes both carry-overs for the data it ships, by test. The engine rules are a follow-up
issue, not W5b.**
- **Empty core:** T5.49 pins HOS's exact 17-entry set.
- **Duplicate keys:** T5.52 rejects duplicates in every shipped file.

**Why not the engine rules now:**
- Each one adds a rule code and a slot in TD-D28's fixed order, plus its tests, to the merged
  `dimension_registry.py`.
- A duplicate-key loader is a **generic** rule, so it binds #1644 T3.1's kind as well.
- That is a contract change to §C.2.6 with its own review set (security-reviewer on the engine), and
  W5b's budget is full.

The residual exposure is a consumer's hand-edited `contract/dimensions/*.yaml`. That is a CODEOWNERS-gated
edit (`protected_surfaces.txt:17`), and nothing is gated on the registry until W8.

**Follow-up:**
- **Owner:** the orchestrating session files the issue. `technical-design` specifies it, and the
  architect approves.
- **Proposed rules:** `L29 duplicate_key` (generic, engine step 2 before L3a, via a `SafeLoader` subclass
  that rejects a repeated key) and `L30 core_empty` (dimension-specific: `core.yaml` declares zero
  entries, first in handler step 3).
- ~~**Must land before W8.**~~ *(architect, round 1 — tightened.)* **Must land before the earliest of:**
  - W7 merging (the first slice that invokes reviewers from a loaded registry, and whose records W8
    later gates on);
  - W8;
  - #1644 T3.1's first shipped data file. L29 is generic and binds T3.1's kind, unless T3.1 carries its
    own T5.52-equivalent duplicate-key test over its shipped data.
- *(architect, round 1 — scope note for the follow-up TD.)* `core_empty` (zero entries) is a weak check.
  A `core.yaml` trimmed to a single entry passes it. Consumer `core.yaml` integrity actually rests on
  three things: HOS owns the file, the installer overwrites it on upgrade, and it is CODEOWNERS-gated.
  The follow-up TD must assess drift detection of the installed `core.yaml` against the installed
  release, through `.hos-manifest` if it carries content hashes (if not, it must say so), as a
  replacement for L30 or alongside it. It must not ship L30 alone as if it closed the empty-core class.

### D.7 File budget and protected surfaces (W5b)

| # | Path | New/Mod | Protected? |
|---|---|---|---|
| 1 | `contract/dimensions/core.yaml` | new | yes (`contract/**`, `protected_surfaces.txt:17`) |
| 2 | `contract/dimensions/project.yaml` | new | yes |
| 3 | `contract/dimensions/project.yaml.template` | new | yes |
| 4–11 | `contract/dimensions/prompts/{code-review,security,privacy,reliability,ops,ui,a11y,infra}.md` | new | yes |
| 12 | `packs/django/dimensions.yaml` | new | **no** (TD-VF-26) |
| 13 | `packs/astro/dimensions.yaml` | new | **no** |
| 14 | `contract/resolved-packs.txt` | new | yes |
| 15 | `tests/automation/test_dimension_registry_data.py` | new | no |

That is **15 files, at the limit.**
- **Not touched:** `dimension_registry.py`, the CLI, `posture.py`, the W5a tests,
  `framework_consumer_files.txt`, the installer, the sweep and `CLAUDE.md`. No `SCRIPTS-INDEX.md` regen is
  needed, because no script is added.
- If the orchestrator commits **this TD amendment** in the same PR, the count is 16. Land it as its own
  commit on a separate design PR first, or rule that design docs do not count (§D.8 Q6).
  - *(architect, round 1 — Q6 ruled.)* This amendment ships in its **own TD PR**, following the
    #1916/#1919/#1926/#1929 pattern, and does not count toward the W5b code PR. The code PR is exactly
    the 15 files above, at the limit with **zero headroom**. Any 16th file (a fixture file, an index
    regen, a CLAUDE.md touch) means a split, not an exception.
  - "Design docs do not count" is **not** adopted as a general rule.
- The PR is CODEOWNERS-gated through `contract/**` in any case.

**Review set:**
- `code-reviewer`;
- `security-reviewer` (the data decides which security lens runs, and TD-D34 is a reuse-safety rule);
- `privacy-reviewer` (TD-VF-23's PII predicates);
- `infra-reviewer` (gate bindings).

### D.8 Open questions — to `architect` (none blocks W5b's coder except Q6)

*(architect, round 1: all seven are ruled in §D.10. Q5 is routed to the human, and it does not block W5b.)*

- **Q1 (confirm TD-D34):** the content-hash version, and §4.1's `"security/v1"` demoted to illustrative.
- **Q2 (confirm TD-D35):** W5b prompts carry no output contract. §4.3's "instructed by our own prompt
  template" is met at W7 by one W7-owned block that TD-D34's hash covers.
- **Q3 (confirm TD-D37):** `pack-astro:security/astro`, which goes beyond §7.2's sentence.
- **Q4 (follow-up scope):** should `.mjs`/`.cjs`/`.jsx`/`.tsx` (and `package.json` for security) join
  CORE's language-generic code predicates, or go into a future `packs/node/dimensions.yaml`? No route
  exists today, so W5b does not regress anything. My recommendation is CORE extensions, because they are
  language-generic as `.js`/`.ts` already are. It is a separate PR either way, since T5.28's table would
  move.
- **Q5 (→ human via the architect):** should `packs/**` (or `packs/*/dimensions.yaml`) join
  `protected_surfaces.txt`? Today a HOS-source edit that drops a pack binding is not human-gated
  (TD-VF-26). This is pre-existing for agent region bodies, and it is new for routing data.
- **Q6 (BLOCKING only for packaging):** does a design-doc commit count toward the 15-file limit (§D.7)?
- **Q7 (confirm TD-D41):** the engine rules L29/L30 go to a follow-up issue that must land before W8.

### D.9 Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design?*
- **TD-VF-22 and TD-VF-23: yes.** `categorize()` was in the tree when §7.2 was written.
- **TD-VF-24 (no prompt contract): yes.** §7.2 made the files required (L21) and §10 budgeted them,
  with no content contract.

These are a `startup-artifact-gap`. The orchestrating session should annotate the issue opened under
§C.3. I file nothing (task constraint).

**Affected sign-offs:**
- **W5a (#1933):** these **stand**. No engine behaviour changes, and the TD-VF-27 rules are deferred,
  not retrofitted.
- **W5b:** unbuilt, so no orphaned approvals.
- **W1:** TD-D34 uses W1's existing free-form flag unchanged, so its sign-offs stand.
- **W5c/W7:** inherit TD-D35's obligations. Neither has an approved design yet.

### D.10 Architect rulings — Amendment D round 1 (2026-10-02)

**Verdict: APPROVED_WITH_EDITS.** The round-1 edits are applied in place and marked "architect, round 1":
- TD-D33 rule 6 (matching semantics) and new rule 7 (canonical text);
- TD-D34 (reason corrected, rule made explicit);
- TD-D35 (c), superseded by (c1) and (c2);
- T5.51;
- §D.5 X3, plus the `OLD_DOMAINS` verification note;
- TD-D41 (deadline tightened, plus a scope note for the follow-up);
- §D.7 (Q6);
- the top-of-document amendment pointer.

The coder may start W5b once this amendment's TD PR merges.

**Verified against the tree (not taken from the draft):**
- **TD-VF-22 holds.** `run_post_change_sweep.sh:68` routes both docs to the framework track. Both files
  exist, and `docs/AGENTS.md` is itself a protected surface (`protected_surfaces.txt:21`). Dropping them
  from HOS's own framework-validator binding would have narrowed HOS's governance review.
- **TD-VF-23 holds.** The privacy grep runs over `tr '[:upper:]' '[:lower:]'` output (`:181-182`). The
  engine compiles each pattern on its own (`dimension_registry.py:541`, `:724-725`), so a leading `(?i)`
  is legal under Python 3.11+'s global-flag rule.
  - One widening, accepted: the old grep ran only over application-code and migrations paths, and only
    when application code was present. `(?i)erasure`/`(?i)pii` now match **any** path, for example a
    `docs/pii_policy.md`, which is exactly the false positive the template's suppression example
    anticipates. That is more review, not less.
- **TD-VF-26 holds** at the cited lines (`:16-33`, `:17`, `:29`).
- **`OLD_DOMAINS` holds:** the live script was re-run over all 42 paths, and every row matches.
  `NEW_EXPECTED` was hand-checked against §D.3's predicates for every row with a privacy, test-exclusion
  or markup subtlety (rows 11–16, 19–27, 33, 39–42), and all of them match.
- **`contract/` ships per file** (`hos_install.sh:245-246`, `:2112-2119`), not wholesale. HOS's own
  `contract/dimensions/project.yaml` and `contract/resolved-packs.txt` therefore cannot leak to consumers
  in W5b. **W5c obligation:** both stay off the ship-list, and the W5c installer test asserts that
  neither is copied. A leaked `project.yaml` would fail a consumer's load with L10 `agent_missing`
  (`framework-validator` is not shipped). That fails closed, but it is a broken install.

**Rulings on §D.8:**
- **Q1 — TD-D34 confirmed, with a corrected reason.**
  - The content hash is right, but the draft's fail-open argument was wrong: `input_file_sha256` already
    covers every sent byte. The hash is required for provenance, and as defence in depth.
  - The value is over the template **file** bytes, never over rendered output.
  - §4.1's `"security/v1"` is illustrative. When technical-design next touches §4.1 (W7 at the latest),
    it adds a one-line pointer there; this round did not edit outside Amendment D.
  - **No conflict with AD-6's `input_digest`,** which now has a defined component value, and **none with
    W1's `--prompt-template-version`,** which is unchanged and free-form. W1's sign-offs stand.
- **Q2 — TD-D35 confirmed, with (c) superseded by (c1)/(c2).**
  - Deferring the placeholder grammar and the output-contract block to W7 is correct. Binding a grammar
    no caller exercises would pre-empt W7, and the reserved delimiters (rule 6) keep W7's choice free.
  - §4.3's "instructed by our own prompt template" is satisfied at W7 by one W7-owned block delivered
    through `--input-file` (c1). Until W7, no agent is invoked from these files, so no output contract
    is missing at runtime.
- **Q3 — TD-D37 approved: `pack-astro:security/astro` stands.**
  - A pack may only add bindings. Adding one is the narrow-only direction AD-9 permits.
  - The rationale is correct against `packs/astro/security-reviewer.md`. `set:html`, `is:inline`
    scripts, frontmatter and `astro.config.mjs` are named as security surfaces there, and neither CORE's
    security predicate nor any other binding reaches `.astro` or `.mjs`.
  - **No `packs/node/dimensions.yaml`: confirmed.** "Resolved pack with no file" is a designed
    non-error, and node has nothing to migrate.
- **Q4 — ruled: CORE extensions, in a follow-up PR, landing before W7.**
  - **Extensions:** `\.mjs$`, `\.cjs$`, `\.jsx$` and `\.tsx$` join the `include` lists of
    `core:code-review/code`, `core:security/code`, `core:reliability/code` and `core:ops/code`. They are
    language-generic in exactly the sense `.js`/`.ts` already are, and putting them in a node pack would
    leave non-node JSX projects unreviewed.
  - **`package.json` is not a node question.** It is the dependency-manifest question for the security
    lens across ecosystems (`package.json` and lockfiles, `requirements*.txt`, `pyproject.toml`, and
    others). The same follow-up TD scopes it; the architect leans towards one CORE security binding
    over manifests.
  - **Cost:** that PR re-pins T5.28's affected rows. Its review-cost widening is covered by W6/W7's cost
    clearance and needs no separate product gate, because nothing invokes reviewers from the registry
    before W7.
- **Q5 — the human's call. Routed, not ruled.**
  - **How to route it:** the orchestrating session files an issue (`bootstrap/create_issue.sh`) with the
    bounded question below, then records the wait with `bootstrap/escalate_to_human.sh`.
  - **Timing:** it does **not** block W5b, because the W5b PR is CODEOWNERS-gated through `contract/**`
    anyway, so both pack YAMLs get human eyes on first landing. It must be decided **before W8**, the
    first point at which routing data gates a merge.
  - **The change is itself gated:** `protected_surfaces.txt` sits under `scripts/framework/**`.
  - **Architect's technical recommendation:** add `packs/**`. The HOS source is the single upstream of
    both protected consumer surfaces: `.claude/agents/**` for region bodies and `contract/**` for pack
    dimension data. It is therefore the cheapest point at which to slip in a loosening.
  - **Why it is the human's decision:** it adds a standing human-review burden to every pack edit, which
    is an operational obligation.
- **Q6 — confirmed: separate TD PR, not counted.** The W5b code PR is exactly 15 files, with zero
  headroom (§D.7).
- **Q7 — TD-D41 confirmed, with a tightened deadline.**
  - W5b closes both carry-overs for the data it ships, through T5.49 and T5.52. The engine rules go to a
    follow-up issue that must land before the earliest of W7, W8, or T3.1's first data file.
  - The follow-up TD must also assess `core.yaml` drift detection, because a zero-entry `core_empty`
    check alone does not close the empty-core class (TD-D41 scope note).

**Also confirmed without edit:**
- TD-D36: the `.*` gate predicates. A narrower predicate would be a second, drifting copy of each gate's
  own file filter.
- TD-D38: a comment-only `resolved-packs.txt`. `read_resolved_packs` skips `#` lines and returns `()`.
- TD-D39: the separate data-test file.
- The TD-D40 frozen-table design, as amended with X3. It honours and strengthens §9.5's intent:
  re-layered rows R1–R3 are compared through the layers they moved to, not excluded. The capture is
  pinned by command and commit, and a skip-if-rewritten guard would have been a silent skip.

**Startup-gap:** this concurs with §D.9. TD-VF-22, -23 and -24 are a `startup-artifact-gap`. So is
X3's omission from §9.5, a §9.5 drafting gap the original review should have caught. The orchestrating
session annotates the §C.3 issue.

**Affected sign-offs:**
- **W1 (#1720 lineage) stands.** TD-D34 as corrected relies only on W1's existing `input_file_sha256`
  and free-form flag.
- **W5a (#1933) stands.** No engine behaviour changes.
- W5b, W5c and W7 are unbuilt, so they have no orphaned approvals. They inherit TD-D35 (a), (b), (c1)
  and (c2), and the TD-D41 deadline.

**Human escalation (route via an issue plus `escalate_to_human.sh`; non-blocking for W5b, must resolve
before W8):**
> Should `packs/**` (minimum: `packs/*/dimensions.yaml`) be added to
> `scripts/framework/protected_surfaces.txt`, making every HOS-source pack edit human-gated? Today, in the
> HOS repo, a change that drops a pack's review binding or edits a pack's agent region body merges
> without a human, even though the same content is human-gated once installed in a consumer. The
> architect recommends **yes, `packs/**`**. The cost is a standing human-review requirement on every
> pack edit.

**Loop state:** approved in round 1. Per CORE, the round temp file is deleted on approval, so none is
left.

---

## Human Review Required — Amendment D (2026-10-02, W5b registry data)

**RISK: MEDIUM.**
- This data decides which review dimensions are applicable to a diff, once W7/W8 consume it. A missing
  predicate is a silent narrowing, so T5.28's exact pin exists to make every narrowing and widening a
  reviewed literal.
- TD-D34 decides reuse safety for AD-13.
- Nothing is gated on the registry before W8.

**CONFIDENCE:**
- **HIGH** on TD-VF-22…TD-VF-27. Each was re-read in the tree at the cited lines, and TD-VF-27 was probed
  against the merged engine.
- **HIGH** that §D.3's data loads green under the merged `load()` for all four pack sets. This was
  probed with stub prompts. T5.51 is what pins the real prompts.
- **HIGH** on the T5.28 table: it is the probe's output, not a derivation.
- **MEDIUM** on TD-D37's astro predicates. `^src/pages/` and `^src/content/` follow Astro's documented
  layout, not a consumer's tree.
- **MEDIUM** on TD-D33 rule 6's agent-name ban. It is strict, and it is chosen so that one prompt can
  serve several agents.

**BLAST RADIUS:**
- **This document:** Amendment D only. The top-of-document amendment index is **not** updated, because
  this dispatch was constrained to appending. The orchestrator or the next round should add a pointer.
  *(architect, round 1: the pointer has been added to the top-of-document amendment list.)*
- **Downstream:** the 15 W5b files in §D.7.
- **Forward obligations:** W7 (TD-D35 a–c) and the follow-up issue (TD-D41).
- **Not touched:** the W5a engine, W1–W4, and W5c's scope.

**Change classification: ADDITIVE.** It fills elided data, adds a content contract to files that had
none, and makes two clarifying corrections (TD-VF-22, -23) to unbuilt data. No built contract is
reversed. TD-D34 constrains an unbuilt W7 caller and leaves W1's flag as it is.

**Architect review is requested.** This amendment is not handed to the coder until the architect
approves. Iteration: Amendment D round 1. No temp-state file was written, because this dispatch was
constrained to edit this one file only.

**Not done here:** no data file, prompt, test or script was written into the repository. The §D.1 probe
ran in `/tmp/claude/w5b/` only. No issue was filed, no label was created, and no register entry was
written.
