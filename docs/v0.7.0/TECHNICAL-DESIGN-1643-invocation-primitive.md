# TECHNICAL DESIGN — #1643 slices W1–W5: the invocation primitive, the result document, observability, the migrations, and the registry

**Status:** **DRAFT — iteration 1 of 5 (CORE cap). REQUESTING ARCHITECT REVIEW.**
Three findings contradict or cannot implement the ADR as written and are raised rather than resolved:
**TD-F1** (AD-4's `subagent_stats.refused` row is unimplementable against the shipped envelope shape),
**TD-F2** (AD-4's "any envelope field the classifier does not recognise" clause makes every CLI version
bump a merge stopper), **TD-F3** (REQ-A4's pre-invocation auth check cannot be performed — auth is not
observable before launch when it comes from the keychain). Each is an **ESC** in §12. Everything else
below is designed to be implementable without further design questions.
**Date:** 2026-09-14
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
- `validation_logic.py` reads only: block-level `verdict` (`:268`), `findings[]` and `attacks[]`
  (`:273`), per-finding `severity` (`:274`), `files` **or** singular `file` (`_files_of:148-154`), and
  `category` **or** `type` (`_class_of_finding:156-160`). `compute_verdict` takes
  `(findings: list[dict], ledger_path: str, *, strict_empty: bool)`. A block whose `verdict` is `"error"`
  adds **+1 `blocking_count` and +1 `new_blocking_count`, never dedup-silenced** (`:266-272`) — this is
  the #670 path AD-4's `invocation_failed ⟹ verdict:"error"` rule rides on, verified at source.
- `panel_logic.py` reads `reviewer` and `lens` (`count_corroboration:194-220`), and in its fallback path
  reads singular **`file`** and **`line`** (`reconcile_membership:222-258`). It counts **distinct
  `reviewer` values as distinct vendors.**
- **Consequence:** a conforming per-finding object must carry **both** `files: [...]` (for
  `validation_logic.fingerprint`) **and** `file` + `line` (for `panel_logic.reconcile_membership`), and
  `reviewer` must be the **vendor** (`"claude"`), not the lens — or twelve same-vendor dimensions would
  read to `panel_logic` as twelve corroborating vendors. §4.2 binds both.

**TD-VF-4 — `load_ledger` cannot be avoided by not calling it: `compute_verdict` calls it
unconditionally.** `compute_verdict:259` is `seen = load_ledger(ledger_path)` with no branch. AD-6's
"`fingerprint()` is reused; `load_ledger()` is not" therefore cannot be honoured by the callee; it must be
honoured by **what the caller passes**. `load_ledger` tolerates a missing file (`:218-220`,
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
| **1** | Operational failure of the primitive itself: it could not emit a document. Only these causes: repo root unresolvable (`.claude/agents/` absent under the computed root); `--output-file` unwritable; a `json.dumps` failure; an unhandled exception caught at the top level. One machine-stable single line on **stderr**, prefixed `agent_invoke: `. | No. |
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
| P1 | Repo root = `Path(__file__).resolve().parents[2]` (or the injected `repo_root`); `<root>/.claude/agents/` is a directory | exit **1** |
| P2 | `--agent` matches `^[a-z][a-z0-9-]*$` | exit **2** |
| P3 | `<root>/.claude/agents/<agent>.md` exists, is a regular file, and is non-empty | document, `agent_unavailable` |
| P4 | That file's YAML frontmatter parses and its `name:` equals `--agent` (**TD-D3**, mine) | document, `agent_unavailable` |
| P5 | `--posture` is in the code-side posture table **and** both of its files exist and validate (§3.6) | table miss ⟹ exit **2**; file miss/invalid ⟹ document, `posture_invalid` |
| P6 | `--input-file` exists, is a regular file, is non-empty, decodes as UTF-8 | exit **2** |
| P7 | `--require-env-auth` given ⟹ `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` is set and non-empty | document, `not_authenticated` |
| P8 | `shutil.which("claude")` resolves | document, `cli_unavailable` |

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
  "allowed_tools": ["Read", "Grep", "Glob", "Bash"],
  "disallowed_tools": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"]
}
```
`review-read-only-gh-read` is the same pair with `Bash(bash bootstrap/query_issues.sh *)` added to
`permissions.allow` and removed from nothing. **TD-D11: the id is spelled `review-read-only-gh-read`**;
AD-7 writes it `review-read-only+gh-read`, and `+` is not in the `^[a-z][a-z0-9-]*$` id grammar the
registry and filenames share. Same posture, different spelling of the name.

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

**Two properties worth stating positively.**
- *No `additionalDirectories` is needed.* Probe J: the CLI confines file tools to the working directory.
  L2 launches with `cwd = repo root` and delivers the prompt on **stdin**, so a reviewer needs nothing
  outside the repo. An empty list is the tightest correct value, not an oversight.
- *The agent frontmatter `tools:` list is a real second layer.* Probe M: it **narrowed** a posture that
  would otherwise have permitted the call. AD-7's "defence in depth, not a substitute" is accurate.

**Stated limit of the mechanism (probes D–G).** The CLI auto-approves a class of commands it judges safe,
regardless of `permissions.allow` and regardless of `--permission-mode manual`. An empty `allow` list
therefore does **not** mean "nothing runs". A posture's security value comes from its `deny` list and its
tool lists (both proven effective, probes C and M), not from the narrowness of its `allow` list. This must
be stated in each posture file's `description` so nobody reads the allow list as exhaustive.

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

Plus the three pre-flight details that never reach `classify` because no process is launched:
**`agent_unavailable`** (P3/P4), **`posture_invalid`** (P5/V2–V11), **`not_authenticated`** (P7),
**`cli_unavailable`** (P8).

**The one rule that is not negotiable (AD-4, AD-6):**
> `outcome == "invocation_failed"` ⟹ `verdict == "error"` in the emitted document, **always**, whatever
> the agent said.

That single rule makes every existing `validation_logic.compute_verdict` consumer fail closed on a broken
invocation for free, via the #670 error-block path (`:266-272` — an `error` verdict counts as one NEW
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

**Behaviour, exactly four steps, no logic beyond them:**
1. `set -euo pipefail`; resolve `SCRIPT_DIR` / `REPO_ROOT` from `BASH_SOURCE`.
2. Verify `python3` is on `PATH`; if not, exit 1 with one stderr line.
3. `exec python3 "$REPO_ROOT/scripts/automation/agent_invoke_cli.py" "$@"`.
4. There is no step 4.

**What it must never do:** mint or revoke a token (this surface performs no GitHub I/O — AD-1); compose or
emit any JSON; print anything to stdout; suppress stderr (#1523); re-derive, default, or validate any
flag; add a flag of its own; grow a `case` statement. **Its header must state, as
`merge_authority.sh`'s does, that it must never grow a JSON literal, a `printf`/`echo` to stdout, or any
re-derivation of a field** — adding a document field is a change to `agent_invoke_cli.py` alone.

Because every flag is `--name value`, the argv shape is fixed and statically allowlistable as
`Bash(bash bootstrap/invoke_agent.sh *)`. That is the reason L3 exists at all (AD-1); it is ~40 lines and
must not grow.

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
| `findings[]` | Per-finding: `severity` from the canonical 7-rank ordering (`validation_logic.SEVERITIES`, `:52`), `category`, `type` (**same value as `category`**, so codex-shaped readers and agy-shaped readers agree), `files[]` **and** `file` (the first element) **and** `line`, `description`, `fix`. Both file keys are mandatory: `validation_logic._files_of` prefers `files`, `panel_logic.reconcile_membership` reads `file` + `line`. |
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

`validation_logic.extract_json_objects` is deliberately prose-tolerant (`:105-152` — it scans braces and
tolerates commentary because agy and codex both prepend it). **L2 must not use it and must not import
it.** Our own agent is instructed by our own prompt template and can be held to a contract.

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
# pass os.devnull as ledger_path -- compute_verdict calls load_ledger()
# unconditionally (validation_logic.py:259), so the only way to honour the
# prohibition is at the call site. See §4.4 of the technical design.
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
- When `usage` is absent (an `unparseable` or `timeout` outcome), fall back to the existing char
  estimate: pass `--prompt-chars <len(input bytes)> --output-chars 0` instead. `token_tracker` already
  marks these `"estimated": true` (`:104`).
- Never called for a `--not-applicable` document (nothing was spent).
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
| `python3` absent | L3 | 1 | no | — |

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
T3.3 A missing `usage` falls back to `--prompt-chars`.
T3.4 A `token_tracker` non-zero exit sets `observability.token_tracker_recorded=false` and **does not**
change `outcome`, `verdict`, or the exit code.
T3.5 One `audit_log.write_event` call per invocation, with `root=repo_root` and a `timestamp` field.
T3.6 The audit record contains **no** prompt text, no finding `description`, and no file contents
(assert by scanning the serialized record for a canary string planted in the input file and in a finding).
T3.7 `write_event` raising sets `observability.audit_record=None` and does not change the exit code.
T3.8 A `not_applicable` document still writes an audit record and does **not** call `token_tracker`.
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
- **Nothing else.** W1–W5 are all new build. **No code has been approved against any contract this
  document changes, so no prior sign-off is invalidated by anything in it.** That will stop being true
  the moment W1 lands, which is why ESC-A and ESC-B are raised now rather than after.

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
