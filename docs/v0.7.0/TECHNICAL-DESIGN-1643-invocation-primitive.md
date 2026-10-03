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

> **AMENDED 2026-10-03 — Amendment E (registry loader hardening before W5c: #1932 tool trust, #1931
> regex bounds, #1937 duplicate keys / core integrity). Architect-approved with edits, round 1 (§E.12).
> Binding on the hardening slice; W5c may not execute a binding until it has merged. W7 may not merge
> until ARCH-ESC-E1 and ARCH-ESC-E2 (§E.12) are cleared by the human.** Adds rules
> L29–L33 and plan rule PL1, a CORE `tools:` allowlist, and a `.hos-manifest` drift check, and
> supersedes TD-D28's order lists (§E.5). Where it and Amendment C or D disagree, Amendment E governs.

> **AMENDED 2026-10-03 — Amendment F (W5c: the explain-only sweep, the installer's registry-data step, the ship-list, #1930(b), #1951). Architect-approved with edits, round 1 (§F.8). Binding on W5c.** Places TD-D43 (i)–(iii) on AD-13's runner, the first component that executes a deterministic `Binding.tool`, not on the W5c sweep (TD-D50). Where it and §7.7/§7.9, §C.2.10/§C.2.11, §E.2 (TD-D43's "W5c obligations" label) or §E.8 ("W5c inherits") disagree, Amendment F governs. *(architect, round 1)*

> **AMENDED 2026-10-03 — Amendment G (W6: the observation-only measurement slice). DRAFT, round 1 of 5 — requesting architect review; not for the coder until approved. Binding on W6 once approved.** Designs the "Out of scope" line's W6. W6 lands AD-13's runner as L2 only (`scripts/automation/dimension_sweep_cli.py`, `measure` + `report`) over exactly one binding, `core:code-review/code`. A human runs it from their own terminal; it is never run from `bin/hos-cron` or from a model session. It writes durable `audit/log/` records and gates nothing. W6 executes no deterministic `Binding.tool`, so TD-D43 (i)–(iii) pass to W7 unchanged (TD-D61). W6 is the first component to render a prompt template, so it takes TD-D35 (a)/(b)/(c1)/(c2) (TD-D62). One human escalation, ESC-G1, covers the measurement campaign. Where it and §1.2's W6/W7 rows or TD-D35's "W7 obligations" label disagree, Amendment G governs.

**Date:** 2026-09-14 (original), amended 2026-09-16 (Amendment A), 2026-09-18 (Amendment B), 2026-10-02 (Amendments C, D), 2026-10-03 (Amendments E, F, G)
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

---

## Amendment E (2026-10-03) — registry loader hardening before W5c: tool trust (#1932), regex bounds (#1931), duplicate keys / core integrity (#1937)

**Status:** **Amendment E — architect-approved with edits, round 1 (§E.12).** W5a (#1933) and W5b (#1943) have
merged (`main` at `ba1e67b97`). W5c (the sweep that **executes** resolved deterministic bindings, the
installer, and the ship-list) is not designed here. It may not merge until this amendment's slice has
merged, because #1932 has to be closed before any binding is executed. Where this amendment and
Amendment C or D disagree, this amendment governs. Everything it does not name stands.

**Numbering.** TD-VF-28…TD-VF-32, TD-D42…TD-D49, rules **L29–L33**, plan rule **PL1**, tests
**T5.54…T5.64**.

### E.1 Verification findings — TD-VF-28…TD-VF-32 (tree at `ba1e67b97`)

**TD-VF-28 — L11 trusts every executable, and a CORE tool is not on a protected surface.**
- L11 checks only `is_file()` and `os.access(X_OK)` (`dimension_registry.py:577-587`). The digest covers
  the `tool` **string** (`_body`, `:694`), not the bytes behind it.
- The shipped data names **11 distinct tools**: nine in `core.yaml:151-199`, plus
  `packs/django/dimensions.yaml:57` and `packs/astro/dimensions.yaml:46`. Ten of them sit under
  `scripts/oversight/gates/`, which is protected (`protected_surfaces.txt:29`).
  `scripts/run_second_review.sh` (`core.yaml:199`) matches **no** protected glob (`:16-47`).
- `scripts/oversight/gates/expensive_gates_stub.sh` is `100755` in a protected directory but is a stub
  (TD-VF-25). It is not a control.
- `scripts/automation/**` is **not** protected. In HOS's own repo, engine code is less protected than
  `contract/**` (`:17`).
- No deterministic binding exists in HOS `project.yaml` or in the template example (grep of `tool:`).

**TD-VF-29 — predicate cost is polynomial in the number of quantifiers, not only exponential under
nesting.**
- L14 only compiles each pattern (`:537-545`). `resolve_for_diff` recompiles every pattern and calls
  `search` on every changed path (`:724-729`).
- Measured on CPython 3.14.4 against `"a"*n`. With **one** quantifier, `.*x` takes 0.4 ms at n=1024 and
  5.4 ms at n=4096. With **two**, `a*a*b`, `.*.*x` and `[^/]*[^/]*x` each take 0.12 s at n=1024 and
  **7.4 s** at n=4096. With **three**, `a*a*a*b` exceeds 20 s at n=1024. None of these has a nested
  group, so a denylist of "nested quantifiers" would miss all of them.
- I probed all 96 shipped and template patterns (`core.yaml`, HOS `project.yaml`, both pack files, and
  the template example). **Each has at most one quantifier.** All of them use only: literals, `\` plus
  punctuation, `\b`, `.`, `[…]`/`[^…]` classes, a leading `^`, a trailing `$`, and a leading `(?i)`.

**TD-VF-30 — PyYAML can detect duplicates exactly, but only after the parse.** Probed on PyYAML 6.0.3,
the version in the venv.
- `safe_load` composes the **whole** node graph before it constructs anything. As a result, a syntax
  error anywhere in the file is raised before any duplicate key can be seen.
- A `SafeLoader` subclass whose mapping constructor first calls `flatten_mapping` and then checks the
  constructed keys rejects a duplicated top-level key, a duplicated nested key (`{p: 1, p: 2}`), and a
  key supplied both by a `<<:` merge and explicitly.
- TD-D41's placement "before L3a" is therefore not literally achievable. §E.5 corrects it.

**TD-VF-31 — `.hos-manifest` carries content hashes; `.hos-release` marks an installed tree.**
- `enumerate_framework_files` emits `<path>\tWHOLE\t<sha256>` from the **source** bytes
  (`hos_install.sh:2205-2225`). `cp_framework_file` is a plain `cp` (`:615-626`), so a verbatim copy's
  installed bytes hash to its row.
- TD-D32 rows (W5c) carry the **target** sha for `pack-<n>.yaml` and `resolved-packs.txt`.
- `.hos-release` is written last, after the manifest, as the commit point (`:2186-2189`, `:2408-2416`).
- Neither file exists in HOS's own repo, and neither is tracked there.
- `.hos-release` is protected (`protected_surfaces.txt:47`). `.hos-manifest` is not.
- The canonical row parser is `regions.parse_manifest_line` (`regions.py:1103-1119`). `regions.py`
  imports `argparse` at module scope (`:47`), so the L1 loader may not import it (§C.2.7, TD-VF-20).

**TD-VF-32 — no consumer has a manifest row for registry data yet.**
- `framework_consumer_files.txt` has no `contract/dimensions/` line. W5c item 1 adds it (§C.2.11).
- Pack-file rows arrive with W5c's TD-D32.
- The loader does not reach consumers until W7 (ESC-E). The drift rule (TD-D48) can therefore land now
  without breaking any consumer.

### E.2 Tool trust — #1932 (TD-D42, TD-D43)

**TD-D42 — a deterministic binding in any layer may name only a tool listed in CORE's `tools:`.**
`core.yaml` gains a **core-only** top-level key, `tools:`. It is a list of repo-relative paths, and it
is the complete set of control entry points. `KINDS[DIMENSIONS_SCHEMA]` adds `"tools"` to
`top_level_keys["core"]` and to `core_only_keys`, so a `tools:` in a pack or project file fails L5
(`core_only_key`). The `KindSpec` shape is unchanged. The literal goes between `entries:` and
`bindings:`, sorted in codepoint order:

```yaml
# Trusted control entry points (ADR-1643 TD-D42). A deterministic binding in ANY layer may
# name only a path listed here. Listing a path is a CORE (contract/**) change.
tools:
  - scripts/oversight/gates/astro_check.sh
  - scripts/oversight/gates/bash_check.sh
  - scripts/oversight/gates/collection_integrity.sh
  - scripts/oversight/gates/django_check.sh
  - scripts/oversight/gates/lint_check.sh
  - scripts/oversight/gates/portability_check.sh
  - scripts/oversight/gates/secret_scan.sh
  - scripts/oversight/gates/security_scan.sh
  - scripts/oversight/gates/template_refs_check.sh
  - scripts/oversight/gates/type_check.sh
  - scripts/run_second_review.sh
```

CORE lists `django_check` and `astro_check` even though only packs bind them. That is correct: every
gate ships in `scripts/oversight/` to every consumer (TD-VF-25), so the list describes what is
shipped, not which pack is installed.

**Rules (exact):**
- **L32 `tool_untrusted` (new, dim-specific).** A `deterministic` binding whose `tool` is a string,
  where that string is **not exactly equal** to an entry of `tools:`.
  - The comparison is exact string equality. There is no normalisation, so `./scripts/…` or
    `scripts//…` fails.
  - An absent `tools:` key means an empty list.
  - Suppressed bindings are checked too, as every rule already does.
  - A non-string or absent `tool` remains L11.
- **L28 (extended).** `tools:` must be a list. Each item must be a non-empty string in POSIX normal form
  (`PurePosixPath(p).as_posix() == p`, and no `.` segment). Otherwise the error is `unknown_item_key`.
- **L6 (extended).** A repeated `tools:` path is `duplicate_id`.
- **L27 (extended).** Each `tools:` entry gets the same path-escape check as `tool`.
- **L11 (extended).** Each `tools:` entry must be a regular, executable file **even if no binding
  names it**. The loop runs over bindings first, as today, then over the remaining entries.

**Rejected alternatives:**
- **(1) A protected-directory prefix rule in the engine.**
  - It hardcodes HOS's layout into engine code, and that code lives on the *unprotected*
    `scripts/automation/**` (TD-VF-28).
  - It admits every executable in the directory, including `expensive_gates_stub.sh`.
  - It turns "add a script to `gates/`" into "add a control" implicitly.
- **(3) Requiring every `tool` to match `protected_surfaces.txt`.**
  - It rejects CORE's own `run_second_review.sh` today.
  - "Protected" does not mean "control". `bootstrap/**` and `bin/**` are protected (`:26-27`), so
    `bootstrap/submit_pr.sh` would load as a review control. That is #1932's threat at a smaller scale.
  - It ties load results to a file #1935 is reclassifying, so a reclassification would silently change
    which bindings load.
  - It would add a third glob matcher, where two already disagree: `require_human_approval.glob_to_regex`
    and `merge_authority`'s `fnmatch`.
- **A pack/project tool must equal some CORE binding's tool.** This fails for `django_check` and
  `astro_check`, which no CORE binding names.

**Why it holds under each #1939 answer.** The allowlist lives in `contract/dimensions/core.yaml`. That
file is protected in HOS (`contract/**`), and it is protected in consumers through the shipped
CODEOWNERS and through L31 (TD-D48). Its protection therefore never depends on `packs/**`.
- **(a)** `packs/**` protected, or **(b)** `packs/*/dimensions.yaml` protected: pack binding edits
  become human-gated as well. Amendment E is unchanged.
- **(c)** No change: a HOS-source pack edit can still merge without a human. But it can only bind a
  CORE-listed tool (L32), only with bounded predicates (L33), and it can still never suppress or remove
  a CORE binding (L16). What remains is a pack narrowing or widening its *own* routing. That is #1939's
  actual question, and Amendment E does not touch it.
- **Every answer:** in consumers, L31 also detects any post-install edit to `pack-*.yaml`.

**The protected status of each tool's code is test-pinned, not a load rule.** T5.63 asserts that every
`tools:` entry under `scripts/oversight/gates/` matches `protected_surfaces.txt`, using
`require_human_approval.py`'s own matcher. It also asserts that the set of unprotected entries is
**exactly** `{scripts/run_second_review.sh}`. That is a ratchet: the test fails once #1935 protects the
script, which forces the exemption to be deleted. Protecting the script is a `protected_surfaces.txt`
change, so it is #1935's decision and not this amendment's (§E.10 Q2).

**TD-D43 — the digest covers the allowlist, and W5c records what it ran (#1932 option 4).**
- `ResolvedRegistry` gains `tools: tuple[str, ...]`, sorted, from `core.yaml`.
- `_body` gains `"tools": [...]`, so `digest` and `to_json` cover it. This is an additive JSON key.
- After L32, `Binding.tool` is byte-equal to an allowlist entry, so the path string already in the
  digest is canonical.
- **W5c obligations (recorded, not designed):**
  - (i) Execute only `Binding.tool` from a `ResolvedRegistry` that was loaded in the same process.
  - (ii) Pass `[root / tool, …]` as an argv list, never a shell string.
  - (iii) For each executed binding, emit `tool` and `tool_sha256`. The sha256 is over the bytes read
    immediately before exec, so the audit names the code that ran and not only its path. The residual
    TOCTOU window is accepted and named.

### E.3 Predicate bounds — #1931 (TD-D44, TD-D45)

**TD-D44 — L33 `unsafe_pattern` (new, dim-specific): every predicate pattern must be in a closed,
single-quantifier subset.** Patterns are checked after L14 has compiled them:

```
pattern  := ["(?i)"] ["^"] piece* ["$"]        ; ≤ 256 characters in total
piece    := "\b" | atom [quant]                ; "\b" is never quantified
atom     := literal | escape | "." | class
literal  := any char except  . ^ $ * + ? { } [ ] \ | ( )
escape   := "\" (ASCII punctuation | "d" | "w" | "s")
class    := "[" ["^"] citem+ "]"               ; no nested "[", "]" never first
citem    := any char except \ [ ]  |  "\" ASCII punctuation
quant    := "*" | "+" | "?"                    ; AT MOST ONE quant in the whole pattern
tail     := the pieces after the quantified atom, excluding a trailing "$"   ; AT MOST 16 pieces
                                                ; ("\b" counts as a piece) (architect, round 1)
```

- The subset has no groups other than the leading flag, no alternation, no `{m,n}`, no lazy or
  possessive forms, no backreferences, and no lookarounds.
- `^` may appear only at the start, after an optional flag. `$` may appear only at the end.
- The scanner is hand-written in the standard library. It must **not** use `re._parser`/`sre_parse`,
  which are private and version-sensitive (3.11 renamed one, deprecated the other).
- **Cost bound (architect, round 1 — the draft's figure was wrong):** with one quantified atom, one
  `search` costs O(L²·t), where L is the path length and t is the length of the **tail**, the fixed
  remainder after the quantified atom. The prefix before the atom does not change the shape (measured).
  The draft's "about 5 ms per pair at L=4096" was `.*x`, which has t=1. It was **not** the worst
  admissible shape. Under the draft's grammar, `(?i).*` followed by 250 literals is 256 characters with
  one quantifier, and it measured **4.5 s per pair** at L=4096 (CPython 3.14.4, `"a"*4096`). Even plain
  `(?i).*x` measured 33 ms, because `(?i)` costs about 6× here. Two bounds therefore bind together:
  - **tail ≤ 16 pieces** (the grammar's `tail` line). The longest shipped tail is `\.html`, at 5
    pieces.
  - **PL1 at 1024 bytes**, not 4096 (TD-D45).

  The measured worst admissible shape, `(?i).*` + 15×`a` + `b` against `"a"*1024`, takes **about
  20 ms per pair**. Total plan cost is linear in files × patterns, with that per-pair ceiling. The
  bound still describes cost, not a timeout: it removes the unbounded case, and it does not make a
  10⁴-file adversarial diff free.
- All 96 shipped and template patterns are in the subset (TD-VF-29). The real-data loads T5.49, T5.50
  and T5.53 keep that true, with no new data test.
- Consumers lose alternation and multi-quantifier forms. `^src/.*\.tsx?$` must become two patterns,
  `^src/.*\.ts$` and `^src/.*\.tsx$`. That is an accepted cost.

**TD-D45 — PL1 `bad_changed_file` (plan-time, not a load rule).** `resolve_for_diff` raises
`RegistryError("bad_changed_file", …)` for a changed path that is empty, longer than **1024 UTF-8
bytes**, or contains `\n` or `\x00`. *(architect, round 1: the draft said 4096 (PATH_MAX). 1024 cuts the
L² term by 16×. No realistic repository path reaches it, and a path that does fails closed with the
path named. The bound is a consumer-visible failure mode, so it is part of ARCH-ESC-E1.)* Paths are checked in input order and the first bad one
wins. The CLI's existing `RegistryError` handler turns this into exit 1 with its standard stderr line.
Without PL1, the bound L depends on the attacker.

**Rejected alternatives:**
- **(1) A glob grammar.** It would re-pin all 96 patterns and T5.28. `\b` and `(?i)` have no glob
  equivalent. A closed regex subset is just as safe for far less churn.
- **(2-as-denylist).** Rejecting "known exponential constructs" misses the polynomial cases (TD-VF-29).
  A positive grammar is closed by construction.
- **(3) re2.** A native consumer dependency on hosts with no venv (Amendment A).
- **(4) A wall-clock timeout.** The loader is pure: no subprocess (§C.2.7), and `signal.alarm` is
  main-thread-only and POSIX-only. A timeout would also make a data defect's outcome depend on machine
  speed, which TD-D28's determinism argument forbids. Its path-length half is adopted as PL1.
- **A length bound alone.** `(a+)+$` is 6 characters.

### E.4 Duplicate keys and core integrity — #1937 (TD-D46, TD-D47, TD-D48)

**TD-D46 — L29 `duplicate_key` (new, generic).** `_parse_layer` uses a strict `SafeLoader` subclass,
built lazily inside `load_registry` (PyYAML stays a lazy import, §C.2.4).
- Its mapping constructor calls `flatten_mapping(node)` and then constructs each key. A key equal to
  an earlier key in the same mapping raises a module-private exception that does **not** derive from
  `yaml.YAMLError`. `_parse_layer` catches it **before** the `YAMLError` clause and turns it into
  `duplicate_key`.
- The message names the key and its 1-based line (`key_node.start_mark.line + 1`). It then delegates to
  `SafeLoader.construct_mapping`.
- **Merge keys:** a key supplied by `<<:` and also explicitly is a duplicate. Merge-override is exactly
  the "hide an earlier value" behaviour L29 exists to forbid. No shipped file uses anchors.
- It applies at every nesting depth and to every kind. #1644 T3.1 therefore inherits it, which
  discharges TD-D41's third deadline condition.
- **Unhashable keys (architect, round 1).** A complex key, such as `? [a, b]`, constructs to an
  unhashable value. The duplicate check must not raise a bare `TypeError`, which L26 would turn into
  `kind_handler_failed`. When the constructed key is unhashable, skip the membership test and let the
  delegated `SafeLoader.construct_mapping` raise its own `ConstructorError`. That is a `YAMLError`, so
  it surfaces as L3a `bad_schema`. T5.54 adds this case.
- **Which "parse" precedes L29 (architect, round 1).** PyYAML has two phases. *Compose-phase* errors,
  from the scanner, parser or composer (syntax errors), are raised for the whole file before any
  construction, so they always precede L29. *Construct-phase* `YAMLError`s, such as an unhashable key
  or an unknown tag under `SafeLoader`, are raised during the same document-order walk as L29. Between a
  duplicate key and a construct-phase error, the one that occurs **earlier in the document** therefore
  wins. That is still deterministic per input, so TD-D28's argument holds. §E.5 step 2's
  "L3a (YAML unparseable)" means compose-phase errors only. T5.64's (L3a-parse, L29) fixture must use a
  syntax error.

**TD-D47 — L30 `core_empty` (new, dim-specific), kept as a floor, not as the closure.** It fires when
`core.yaml`'s `entries` is absent, `null`, or `[]`. It runs first in handler step 3. A non-list value
falls through to L28, so L30 never hides a shape error. Per the architect's scope note (§D.10 Q7), L30
does **not** close the empty-core class: a core trimmed to one entry passes it. The class is closed by
T5.49 in HOS's own tree, and by L31 in installed trees.

**TD-D48 — L31 `installed_drift` (new, generic): in an installed tree, every HOS-owned registry input
must match its `.hos-manifest` row.**
- **Applies when** anything exists at `<root>/.hos-release`, tested with `os.path.lexists`, so a
  dangling symlink counts.
  - It is otherwise skipped. That covers HOS's own repo and every W5a/W5b tmp-tree test (TD-VF-31).
  - Deleting `.hos-release` to evade the check is a protected-surface edit (`protected_surfaces.txt:47`).
- **Checked set, in order:**
  1. `contract/resolved-packs.txt`, only when `packs=None`;
  2. `<directory>/core.yaml`;
  3. for each slug in the pack set, in closure order, `<directory>/pack-<slug>.yaml` **when the file
     exists or `.hos-manifest` has a row for it** *(architect, round 1)*.

  *(architect, round 1)* The draft checked only files "that will be loaded". The engine loads a pack
  file only if it exists (`dimension_registry.py:271`), so **deleting** an installed `pack-django.yaml`
  silently dropped that pack's bindings and passed L31. A row with no file is now `installed_drift`,
  with the message "listed in `.hos-manifest` but absent". A pack that ships no dimensions file, such as
  `node`, has neither a file nor a row, so it is skipped. That is still TD-D37's designed non-error.

  `project.yaml` is consumer-owned and is never checked.
- **Per path, first failure wins.** Each of these is `installed_drift`, carrying that path:
  - `.hos-manifest` absent, unreadable, or not UTF-8;
  - no row for the path;
  - more than one row for the path;
  - a row that is not WHOLE;
  - a sha that does not match `^[0-9a-f]{64}$`;
  - a sha that differs from sha256 of the file's raw bytes.
- **Message:** names the path and says *re-run `bootstrap/hos_install.sh`; put local changes in
  `contract/dimensions/project.yaml`*.
- **Row lookup** is a private, about 15-line reader in the engine, because `regions.py` is not
  importable from L1 (TD-VF-31).
  - It splits on `\n`, and skips blank **and whitespace-only** lines, and lines whose `lstrip()` starts
    with `#`. *(architect, round 1: whitespace-only is what `parse_manifest_line` treats as blank, at
    `regions.py:1112`. T5.57 adds a whitespace-only line.)*
  - It considers only lines whose first tab field equals the path. A 3-field row must have field 2 equal
    to `WHOLE`. A 2-field row is v1 WHOLE.
  - Malformed rows for *other* paths are ignored.
  - T5.57 pins parity with `regions.parse_manifest_line` (D41: one meaning, pinned, not a second
    definition left to drift).
- **What it is and is not.** It is an **integrity** control. It catches hand edits, a half-applied
  upgrade (core copied, `.hos-release` from the prior run), and a trimmed core. It is **not**
  tamper-proof: `.hos-manifest` is unprotected (TD-VF-31), so an actor who can merge to `contract/**`
  can also rewrite the row. Tamper resistance still rests on CODEOWNERS over `contract/**`. Whether to
  protect `.hos-manifest` is routed to #1935 (§E.10 Q2).
- **Rejected:**
  - **An engine-pinned hash of the release's `core.yaml`.** It is circular: the engine ships in the same
    release and sits on an unprotected path.
  - **Warn-only on drift.** A loader that gates review must not run on a core that differs from the
    release, silently or not. `core.yaml` is declared HOS-owned and overwritten on upgrade
    (`core.yaml:1`), so drift has no legitimate use.

### E.5 Rule table delta and the amended order (supersedes TD-D28's three lists)

| # | Class | Condition | `RegistryError.code` |
|---|---|---|---|
| L6 | dim-specific | **+ a repeated `tools:` path** | `duplicate_id` |
| L11 | dim-specific | **+ any `tools:` entry not a regular executable file** | `tool_missing` |
| L27 | dim-specific | **+ applied to every `tools:` entry** | `path_escape` |
| L28 | dim-specific | **+ `tools:` not a list of non-empty normal-form strings** | `unknown_item_key` |
| **L29** | generic | A repeated mapping key at any depth, including via `<<:` merge | `duplicate_key` |
| **L30** | dim-specific | `core.yaml` `entries` absent, `null`, or `[]` | `core_empty` |
| **L31** | generic | Installed tree (`.hos-release` present) and a checked file disagrees with `.hos-manifest` (TD-D48) | `installed_drift` |
| **L32** | dim-specific | A deterministic binding's string `tool` is not exactly a `tools:` entry | `tool_untrusted` |
| **L33** | dim-specific | A predicate pattern outside TD-D44's subset (one quantifier, tail ≤ 16 pieces, ≤ 256 chars) | `unsafe_pattern` |
| **PL1** | plan-time | A `resolve_for_diff` path that is empty, longer than **1024** bytes, or contains `\n`/`\x00` (architect, round 1) | `bad_changed_file` |

**Order (supersedes TD-D28 steps 1–3; step 4 is unchanged):**
1. **Engine, before any parse:** L22 → L2 → L26 → L24 → L1 → L25 → **L31** → L20 *(architect,
   round 1: the draft put L31 after L20)*. L31 needs the pack set, which **L24** produces, and it needs
   nothing from L20's directory scan. In the draft position, the commonest resolved-packs drift
   (deleting a slug while its `pack-<slug>.yaml` remains) reported L20 `stale_pack_file`. That
   contradicted the stated purpose: "a drifted file is reported as drift and not as whatever defect the
   drift introduced". Running before L20 and before any parse makes that true for every checked file.
   Relative order among the W5a rules is unchanged, and L31 is skipped without `.hos-release`, so no
   W5a test moves.
2. **Engine, per file:** L3a *(YAML unparseable)* → **L29** → L3a *(not a mapping, or wrong `schema`)*
   → L3b → L4 → L5 → L18 → L23. This corrects TD-D41's "before L3a" (TD-VF-30). L3a's code and
   condition are unchanged. Only its position relative to L29 is now explicit.
3. **Handler:** **L30** → L28 → L6 → L7 → L8 → L9 → L13 → L14 → **L33** → L27 → L10 → L11 → **L32** →
   L12 → L21 → L15 → L16 → L17 → L19.
   - L33 follows L14, so an uncompilable pattern stays `bad_predicate`.
   - L32 follows L11, so W5a's T5.11 assertions stand unchanged. An unlisted path that is also absent
     reports `tool_missing`, and an unlisted, existing executable (the #1932 case) reports
     `tool_untrusted`.

### E.6 API delta (to §C.2.7)

- `ResolvedRegistry` gains `tools: tuple[str, ...]` (TD-D43).
- `resolve_for_diff` may now raise `RegistryError` (PL1).
- No signature changes. The purity constraints still hold: L31 reads two files under `repo_root`, and
  reads no environment, runs no subprocess, and imports no `regions`.

### E.7 Tests — T5.54…T5.64

Everything except T5.63 goes in a **new** file, `tests/automation/test_dimension_registry_hardening.py`.
It reuses `write_repo`/`default_docs` by import, as the CLI test already does. W5a's
`default_docs()["core"]` gains `"tools": ["scripts/gates/lint.sh"]`, and that is the **only** change to
`test_dimension_registry.py`.

- **T5.54 L29:**
  - A duplicated `bindings:` in a pack file gives `duplicate_key`.
  - So do a duplicated `predicate` inside a binding, and a `<<:`-merged key repeated explicitly.
  - The message names the key and its line.
  - *(architect, round 1)* A complex unhashable key (`? [a, b]: 1`) gives `bad_schema`, never
    `kind_handler_failed`.
- **T5.55 L30:**
  - Absent, `null` and `[]` each give `core_empty`.
  - `entries: "x"` gives `unknown_item_key`.
- **T5.56 L31:**
  - **Skipped:** without `.hos-release` the load is green, even next to a garbage `.hos-manifest`.
  - **With `.hos-release`, each case below gives `installed_drift` carrying the named path:**
    - no manifest;
    - no core row;
    - two core rows;
    - a non-WHOLE core row;
    - `core.yaml` trimmed to one entry (the architect's case);
    - an edited `pack-django.yaml`;
    - an edited `resolved-packs.txt` with `packs=None`;
    - *(architect, round 1)* `resolved-packs.txt` edited to drop `django` while `pack-django.yaml`
      remains. This gives `installed_drift`, **not** `stale_pack_file`, and pins the L31-before-L20
      order;
    - *(architect, round 1)* `pack-django.yaml` deleted while its manifest row and the `django` slug
      remain. This gives `installed_drift` with "absent".
  - **Green cases:**
    - an explicit `packs=` skips the `resolved-packs.txt` check;
    - all rows matching, in both v2 and v1 row forms, loads green;
    - a malformed row for an unrelated path is ignored.
- **T5.57 parity:** for each row form (v2, v1, comment, blank, whitespace-only *(architect, round 1)*,
  the schema marker, and a 4-field row),
  the loader's lookup agrees with `regions.parse_manifest_line`. Where the parser raises `ValueError`,
  the loader reports `installed_drift`.
- **T5.58 L32 and the `tools:` extensions:**
  - An executable, unlisted `scripts/gates/stub.sh` in a pack binding gives `tool_untrusted`, and the
    same tool in a project binding does too. So does `./scripts/gates/lint.sh`. A listed tool loads
    green.
  - `tools:` in a pack file gives `core_only_key`.
  - A non-list, a non-string, `""` and `scripts//gates/lint.sh` each give `unknown_item_key`.
  - A duplicate entry gives `duplicate_id`.
  - A listed but absent or non-executable unbound tool gives `tool_missing`. A listed `../x.sh` gives
    `path_escape`.
- **T5.59 digest:** adding an entry to `tools:` changes `digest`, and `to_json()["tools"]` is sorted.
- **T5.60 L33:**
  - Each of `(a+)+$`, `a*a*b`, `a|b`, `x{2}`, `.*?`, `\1`, `a^`, `$a`, `[[:alpha:]]`, `\b*`,
    `(?s)x` and a 257-character literal gives `unsafe_pattern`.
  - Each of `\bsecret`, `(?i)pii`, `/test_[^/]*\.py$`, `.*` and `\d+` loads green.
  - An uncompilable `(` gives `bad_predicate`.
  - *(architect, round 1)* `.*` followed by a 16-piece tail loads green. `.*` followed by a 17-piece
    tail gives `unsafe_pattern`. So does `(?i).*` + 250×`a` + `b` (256 characters, one quantifier):
    the draft's grammar admitted it, at 4.5 s per pair.
- **T5.61 ReDoS regression (#1931 acceptance):**
  - A project binding with `(a+)+$` fails `load()` with `unsafe_pattern`. It is never planned.
  - *(architect, round 1)* The worst admissible shape, `(?i).*` + 15×`a` + `b` (a 16-piece tail), runs
    through `resolve_for_diff` against a 1024-byte `"a"*1024` path and finishes in under 2 s. The
    measured time is about 20 ms, so the bound has about 100× headroom. The draft named `.*x` at
    L=4096, which is neither the worst shape nor the PL1 bound.
- **T5.62 PL1:**
  - *(architect, round 1: the bound is 1024)* A 1025-byte path, `""`, a path with `\n` and a path with
    `\x00` each give `bad_changed_file`. So does a 342-character path of 3-byte UTF-8 characters
    (1026 bytes), which pins that the bound is in bytes, not characters.
  - A 1024-byte path is accepted.
  - `cli.main(["plan", "--changed-file", "a"*1025], repo_root=…)` returns 1, and stderr carries
    `bad_changed_file`.
- **T5.63 (in `test_dimension_registry_data.py`, real tree):**
  - `core.yaml`'s `tools:` is sorted. It equals **exactly** the set of deterministic `tool` values across
    `core.yaml`, both `packs/*/dimensions.yaml` and HOS `project.yaml`, which is 11 paths.
  - Every entry under `scripts/oversight/gates/` matches `protected_surfaces.txt`, through
    `require_human_approval.py`'s `load_globs`/`matched_surfaces`, loaded by `importlib`, as in
    `tests/framework/test_require_overseer_approval.py`.
  - The unprotected set equals exactly `{"scripts/run_second_review.sh"}` (the ratchet).
- **T5.64 order:** one two-defect fixture per new boundary. In each pair, the first-named rule's code
  wins:
  - (L25, L31), (L31, L20) and (L31, L3a-shape) *(architect, round 1: the draft's (L20, L31) is
    reversed)*;
  - (L3a-parse, L29): a duplicate before a syntax error gives `bad_schema`;
  - (L29, L3a-shape);
  - (L30, L28);
  - (L14, L33) and (L33, L27);
  - (L11, L32) and (L27, L32).

### E.8 Scope boundaries

- **#1939 (needs-human):** no dependency. §E.2 gives the degradation under each answer.
- **#1942 (governance paths have no security-lens binding): OUT.** It is a routing-**data** and
  lens-choice question: CORE vs HOS-PROJECT, and whether the lens is `security-reviewer`'s
  application-security lens or a `self-reviewer`-style governance lens. That is a product/architecture
  question for `pm-agent`/`architect`, not engine hardening.
  - It re-pins T5.28, as #1938 does, and it should land with #1938.
  - Its deadline is W7, not W5c: no reviewer is invoked from the registry before W7.
  - Folding it in would add `privacy-reviewer`/`pm-agent` to this slice's review set and mix a routing
    widening into a security-control change.
- **Not touched:** postures (L12 validates them semantically) and prompt bytes (TD-D34 hashes them at
  W7). Neither is in L31's checked set. If the architect wants them there, the change is additive.
- **W5c inherits:**
  - TD-D43 (i)–(iii);
  - **T5.47 gains** "after a real `--pack django` install, `load(target)` is green". That proves the
    installer emits every row L31 checks (core via item 1, pack and resolved-packs via TD-D32);
  - `core.yaml` stays on the item-1 ship-list, which L31 requires.
  - *(architect, round 1)* **TD-D43 (iv):** the W5c sweep loads the registry with `packs=None`, and it
    never forwards an explicit pack set (`dimension_registry_cli.py --pack`) in an installed tree. An
    explicit set skips L31's `resolved-packs.txt` check by design. That is correct for the CLI's
    diagnostic use. It is not acceptable on the path that decides which controls run.
- *(architect, round 1)* **§D.10 Q4's follow-up** (`.mjs`/`.cjs`/`.jsx`/`.tsx` and the
  dependency-manifest security binding) must express its predicates inside L33's subset. In
  particular, `(^|/)package\.json$` is inadmissible (it has a group and an alternation). Write it as the
  two patterns `^package\.json$` and `/package\.json$`.
- **#1644 T3.1 inherits** L29 and L31 unchanged. Its `contract/stages/core.yaml` must therefore ship
  through the ship-list, so that it has a WHOLE row.

### E.9 File budget and review set

| # | Path | New/Mod | Protected? |
|---|---|---|---|
| 1 | `scripts/automation/lib/dimension_registry.py` | mod (L29–L33, PL1, `tools`, the `KINDS` row) | no |
| 2 | `contract/dimensions/core.yaml` | mod (`tools:` block, TD-D42) | yes (`contract/**`) |
| 3 | `tests/automation/test_dimension_registry.py` | mod (fixture `tools:` only) | no |
| 4 | `tests/automation/test_dimension_registry_hardening.py` | new (T5.54–T5.62, T5.64) | no |
| 5 | `tests/automation/test_dimension_registry_data.py` | mod (T5.63) | no |

- That is **5 files, one coding PR**, with 10 files of headroom.
- No script is added, so there is no `SCRIPTS-INDEX.md` regeneration.
- The CLI, `posture.py`, the installer, the sweep and `CLAUDE.md` are untouched.
- This amendment ships in its own TD PR (the §D.7 Q6 precedent).
- The code PR is CODEOWNERS-gated through `contract/**`.

**Review set:**
- `code-reviewer`;
- `security-reviewer` (the engine, and the `tools:` allowlist as a trust boundary);
- `reliability-reviewer` (L31 fail-closed on half-applied upgrades, and the PL1/L33 cost bound);
- `infra-reviewer` (L31's reliance on installer artifacts).

### E.10 Open questions — to `architect` (none blocks the coder except Q1)

- **Q1 (confirm, BLOCKING):** L31 fails **closed** on drift in installed trees, keyed on `.hos-release`.
  This is fail-closed behaviour for consumers, and it becomes visible to them at W7.
- **Q2 (route, non-blocking):** two observations belong to #1935's protected-surface reclassification,
  not to this slice. They are why T5.63 is a ratchet.
  - `scripts/run_second_review.sh` is a CORE control entry point that no protected glob covers.
  - `.hos-manifest` is unprotected (TD-VF-31).
- **Q3 (confirm):** the narrowing of AD-9's "CORE, PACK, and PROJECT may all contribute bindings"
  (`ADR-1643:505-506`) for **deterministic** bindings. A PROJECT or PACK layer may bind only CORE-listed tools. No shipped or template project
  binding is deterministic, so nothing regresses. A PROJECT-extensible allowlist would need its own TD,
  because it re-opens #1932 for consumer-owned code. My recommendation is to defer it until a consumer
  needs it.
- **Q4 (confirm):** the single-quantifier limit in TD-D44, over a limit of two. Two is measured at 7.4 s
  per pair at L=4096.

**ESC: none.** No question needs a human. #1939 and the Q2 items already have owners.
*(architect, round 1: superseded. Q1 and Q3 each carry a consumer-visible product consequence that
takes effect at W7. They are routed as ARCH-ESC-E1 and ARCH-ESC-E2 in §E.12. Neither blocks this
slice's coding. Both block W7.)*

### E.11 Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design?*
- **#1932 and #1931: yes.** §7 already knew that W5c/W7 would execute bindings and that §7.5 runs
  arbitrary `re.search` over a diff. Tool trust and predicate cost were both determinable then. This is
  a `startup-artifact-gap`, and the orchestrating session should annotate the §C.3 issue. I file
  nothing (task constraint).
- **#1937: no.** It is TD-D41's recorded, architect-approved deferral, delivered here. TD-VF-30
  corrects only its placement wording.

**Affected sign-offs:**
- **W5a (#1933) stands.** No existing rule changes its condition, code or relative order. T5.11 and
  T5.39 are unchanged, by the L11-before-L32 and L27-before-L32 placement. The only W5a test edit is the
  fixture's `tools:` key, which is required for the default fixture to keep loading green. The new rules
  are new code, and they get fresh review in this slice.
- **W5b (#1943) stands** for its existing content. The new `tools:` block in `core.yaml` is new data,
  reviewed in this slice. T5.49–T5.53 are unchanged.
- **W1–W4/W4b:** untouched.
- **W5c and #1644 T3.1:** unbuilt, so there are no orphaned approvals. They inherit §E.8.

### E.12 Architect rulings — Amendment E round 1 (2026-10-03)

**Verdict: APPROVED_WITH_EDITS.** The round-1 edits are applied in place and marked
"architect, round 1":
- TD-D44 (the tail bound, and the cost bound corrected);
- TD-D45 (PL1 lowered to 1024 bytes);
- TD-D46 (unhashable keys, and the compose-phase vs construct-phase order);
- TD-D48 (pack-file deletion closed, and whitespace-only manifest lines);
- §E.5 (L31 moved ahead of L20, and the table rows);
- T5.54, T5.56, T5.57, T5.60, T5.61, T5.62 and T5.64;
- §E.8 (TD-D43 (iv), and the §D.10 Q4 follow-up constraint);
- §E.10's ESC line;
- the human-review confidence line;
- the top-of-document pointer.

The coder may start the hardening slice once this amendment's TD PR merges. ARCH-ESC-E1 and
ARCH-ESC-E2, below, block **W7**, not this slice.

**Verified against the tree at `ba1e67b97` (not taken from the draft):**
- **TD-VF-28 holds.**
  - L11 is `is_file` + `X_OK` only (`dimension_registry.py:577-587`), and `_body` hashes the `tool`
    string (`:694`).
  - Eleven tools: nine in `core.yaml:151-199`, `packs/django/dimensions.yaml:57` and
    `packs/astro/dimensions.yaml:46`. All eleven are `100755` in the index.
  - `protected_surfaces.txt:29` covers ten of them. No glob covers `scripts/run_second_review.sh`.
  - No `tool:` appears in HOS `project.yaml` or in the template.
- **TD-VF-29 holds for the data.**
  - An independent probe found 96 patterns, none with alternation, a group, or more than one
    quantifier. The longest tail is `\.html`.
  - The **cost claim built on it did not hold**: see Q4.
- **TD-VF-30 is consistent with PyYAML's two-phase design.** It is refined in TD-D46 (construct-phase
  errors are interleaved with L29).
- **TD-VF-31 holds.**
  - `cp_framework_file` is a plain `cp` (`hos_install.sh:615-626`).
  - `enumerate_framework_files` hashes the source bytes (`:2205-2225`), and it covers all of
    `scripts/oversight/` and `run_second_review.sh`, so every `tools:` entry ships to every consumer.
    L11's new check on unbound entries therefore cannot fail a correct install.
  - `.hos-release` is written last (`:2408-2416`).
  - `regions.py:47` imports argparse, and `parse_manifest_line` is at `:1103-1119`.
  - Neither `.hos-release` nor `.hos-manifest` exists in HOS's tree.
- **TD-VF-32 holds.** The CLI forwards `--pack` as an explicit `packs=` argument
  (`dimension_registry_cli.py:100`), hence TD-D43 (iv).
- **The W5a/W5b claims hold.**
  - T5.11's three cases still report `tool_missing` under L11-before-L32. T5.39's symlink case still
    reports `path_escape` under L27-before-L32.
  - T5.29 pins no digest literal, and the CLI tests pin no 64-hex value, so `_body`'s new `tools` key
    breaks nothing.
  - W5b's `stage()` copies `scripts/oversight/gates/` and `run_second_review.sh` with their modes, so
    T5.50 and T5.53 stay green under the extended L11. T5.49 asserts the entry ids, binding ids and
    source files, and none of them changes.

**Rulings on §E.10:**

- **Q1 — CONFIRMED (technical): L31 fails closed. Warn-only stays rejected.** Its consumer-facing
  effect is provisional until **ARCH-ESC-E1** clears.
  - **Why it is right.** AD-9's "the loader fails closed, always" was human-cleared through the ADR.
    `core.yaml:1` already declares the file HOS-owned and overwritten on upgrade. The installer
    already treats HOS-owned drift as a hard stop at install time (the CORE/PACK region rule). L31
    moves that same posture to load time. A warn-only L31 would recreate AF-5: a review gate running
    on a core that differs from the one that was reviewed.
  - **What can still go wrong:**
    1. **A line-ending rewrite.** A consumer clone with `core.autocrlf=true`, or an `eol=crlf`
       `.gitattributes`, changes the working-tree bytes. Every load then fails closed on that clone.
       This is the same byte-hash semantics `--prune` already uses, so it is not a new class of
       defect. It is a new place where the defect becomes *visible*, and the infra-reviewer must
       check it explicitly.
    2. **Install via PR.** An install-via-PR branch is consistent: core, manifest and `.hos-release`
       move in one commit. Any process that cherry-picks only part of an upgrade commit fails closed,
       which is intended.
  - **Is it structural before coding? No.** No consumer receives the loader before W7 (ESC-E), and
    HOS's own tree skips L31 because it has no `.hos-release`. This slice therefore changes nothing a
    user can observe.
  - **It is a new consumer-visible failure mode and recovery obligation from W7**, so it goes through
    the product/policy checkpoint first (ARCH-ESC-E1). W7 may not merge until it clears. If the human
    rejects fail-closed, the rework is confined to L31's raise site and T5.56.
- **Q2 — ROUTED to #1935, confirmed.** The orchestrating session annotates #1935 with both items;
  this round posts nothing.
  - **(a) `scripts/run_second_review.sh` is a CORE control entry point outside every protected
    glob.** This is pre-existing (the pipeline calls it today), and L32 does not worsen it. It is now
    *named* as a control, which makes the gap legible. T5.63's exact-set ratchet is the right forcing
    function. Do not weaken it to a subset check.
  - **(b) `.hos-manifest` is unprotected**, so L31 is an integrity control, not a tamper control,
    exactly as TD-D48 says. Protecting it is #1935's call, because it is a `protected_surfaces.txt`
    edit, which is itself human-gated.
- **Q3 — CONFIRMED (technical): PACK and PROJECT deterministic bindings may name only CORE-listed
  tools.** Its consumer-facing effect is provisional until **ARCH-ESC-E2** clears.
  - **It narrows less of AD-9 than the draft states.** AD-9 (`ADR-1643:505-506`) still holds:
    "CORE, PACK, and PROJECT may all contribute bindings". Every layer may still add a deterministic
    binding, with its own predicate, on any entry. What is narrowed is the *set of executables* a
    binding may name. AD-9 already defines a deterministic `tool` as "a gate/validator script", and
    L32 makes CORE the sole authority on which scripts qualify. ESC-5's ruling concerned suppression
    and layering, and L32 touches neither. Judgment bindings are unaffected.
  - **PACK coupling is intended.** A new pack gate needs a `core.yaml` `tools:` edit (`contract/**`,
    human-gated). Under #1939 answer (c), that coupling is the only thing that human-gates a new pack
    tool.
  - **The draft's rejected alternatives are correctly rejected.** Option (3) would admit
    `bootstrap/submit_pr.sh` as a control, and option (1) would admit `expensive_gates_stub.sh`.
  - **A PROJECT-extensible allowlist stays deferred** to its own TD. Any future design must require
    the listed tool's *code* to sit on a protected path in the consumer, or #1932 re-opens for
    consumer-owned scripts.
  - **Is it structural before coding? No.** No consumer has deterministic bindings today, none is
    shipped or templated, and nothing reaches consumers before W7. From W7, however, consumers cannot
    register their own script as a deterministic control. That is a product capability decision, so
    it goes to pm-agent and the human (ARCH-ESC-E2). If they require the capability at W7, it is
    *additive* to L32 (a protected PROJECT allowlist), so this slice's code stands either way.
- **Q4 — CONFIRMED, one quantifier, with a binding addition: tail ≤ 16 pieces, and PL1 at 1024
  bytes.**
  - **One quantifier, not two, is correct.** Two quantifiers make the cost O(L³), measured at 7.4 s per
    pair. No shipped pattern needs two.
  - **The draft's cost claim was wrong.** The grammar bounded the quantifier count, but not the work
    done per backtrack step. In the architect's measurements (CPython 3.14.4, `"a"*4096`):
    - `(?i).*` + 250 literals: **4.5 s** per pair, admitted by the draft grammar;
    - plain `.*` + 250 literals: 1.7 s;
    - `(?i).*x`: 33 ms.
  - Cost scales as L²·t, and the prefix is immaterial (measured).
  - Bounding the tail at 16 pieces and the path at 1024 bytes gives about 20 ms per pair in the worst
    case, with `(?i)`. Every shipped pattern stays admissible: the longest tail is 5 pieces.
  - The positive-grammar approach, the hand-written scanner, the ban on `sre_parse`, and the rejection
    of a timeout and of `re2` are all correct as drafted.

**Also confirmed without edit:**
- **TD-D42/L32**, with its exact-equality comparison and its placement after L11 and L27. The
  `tools:` normal-form rule under L28 is correct. `//x` falls to L27 as absolute, and `../x` falls to
  L27 as `..`.
- **TD-D43 (i)–(iii)**, including the named TOCTOU residual.
- **TD-D47 (L30) as a floor**, with the closure assigned to T5.49 and L31. This satisfies §D.10 Q7's
  scope note.
- **§E.8's exclusion of #1942** (a routing-data and lens question, which lands with #1938, by W7).
- **§E.9's five-file budget and review set.** Add one point to the review set: `infra-reviewer` must
  explicitly check Q1 risk 1 (line endings).

**Startup-gap and affected sign-offs:** these concur with §E.11.
- #1931 and #1932 are a `startup-artifact-gap`, and the orchestrating session annotates the §C.3
  issue. Q4's cost-bound defect is a drafting error in this round, not a startup gap.
- **W5a stands.** No existing rule's condition, code or relative order changes. L31 moving ahead of
  L20 is invisible without `.hos-release`.
- **W5b stands.** `tools:` is new data, reviewed in this slice.
- W5c, W7 and T3.1 are unbuilt, so they have no orphaned approvals. W5c inherits TD-D43 (i)–(iv).

**ARCH-ESC items.** These are routed by the orchestrating session, through an issue
(`bootstrap/create_issue.sh`) plus `bootstrap/escalate_to_human.sh`, to **pm-agent** (product impact)
and to the **human** (policy). Neither blocks this slice's coding, and **both must clear before #1643
W7 merges.**

1. **ARCH-ESC-E1 — consumer-visible fail-closed conditions on the review sweep (Q1, PL1).**
   > From W7 on, in an installed consumer repository, the review-dimension sweep will refuse to run,
   > blocking review and therefore merge, in either of two cases:
   > - **(a)** `contract/dimensions/core.yaml`, an installed `contract/dimensions/pack-<name>.yaml`, or
   >   `contract/resolved-packs.txt` differs byte-for-byte from the hash recorded in `.hos-manifest` by
   >   the installed HOS release. This includes a hand edit, a deleted pack file, a partially applied
   >   upgrade, or a line-ending conversion on checkout. The recovery is to re-run
   >   `bootstrap/hos_install.sh`; local routing changes belong in `contract/dimensions/project.yaml`.
   > - **(b)** A changed file's path in the diff is longer than 1024 bytes, or contains a newline or NUL.
   >
   > Do you accept fail-closed for both? That is the architect's recommendation: a review gate must not
   > run on routing data that differs from the release that was reviewed. Or do you require (a) to be
   > warn-and-continue?

2. **ARCH-ESC-E2 — consumers cannot register their own scripts as deterministic review controls
   (Q3).**
   > From W7 on, a consumer's `project.yaml` (and any pack) may add deterministic review bindings only
   > for the 11 HOS-shipped gate scripts listed in CORE's `tools:`, each with its own file predicate. A
   > consumer that wants its own script, such as `scripts/my_check.sh`, to run as a review control
   > cannot do so through the registry until a separate design adds a protected, consumer-extensible
   > allowlist.
   >
   > Do you accept this restriction for v0.7.0? That is the architect's recommendation: letting
   > consumer-editable data select consumer-editable code as a "control" is #1932's threat. Or must a
   > protected PROJECT allowlist be designed and land before W7?

**Loop state:** approved in round 1. Per CORE, the round temp file is deleted on approval, so none is
left.

---

## Human Review Required — Amendment E (2026-10-03, registry loader hardening)

**RISK: HIGH.** The amendment defines the trust boundary between registry data and executed code
(CWE-829) just before W5c starts executing bindings. It also adds a fail-closed integrity rule to the
loader that will gate review.
- A wrong L32 would let data select code.
- A wrong L31 would either break every consumer load or pass a trimmed core.
- Mitigations: nothing executes bindings yet, nothing ships to consumers before W7, and the code PR is
  human-gated through `contract/**`.

**CONFIDENCE:**
- **HIGH** on TD-VF-28…TD-VF-32. Each was re-read at the cited lines, and TD-VF-29/-30 were probed in
  `/tmp/claude/tde/` only.
- **HIGH** that L33's subset admits all 96 current patterns (probe) and rejects `(a+)+$` and the
  polynomial forms.
- **HIGH** that L31's inputs exist as described, for the source-copied core. **MEDIUM** for pack and
  resolved-packs rows, which depend on W5c's unbuilt TD-D32. W5c's T5.47 extension pins them.
- **MEDIUM** on the cost bound's constants. They were measured on CPython 3.14.4, while CI runs 3.12.
  The O(L²) shape is structural, and T5.61's 2 s bound leaves wide headroom.
  *(architect, round 1: the draft's constant was wrong by about 900×, because it ignored the tail
  length and `(?i)`. It is corrected in TD-D44, with the tail bound and PL1 at 1024. The re-measured
  worst case is about 20 ms per pair.)*

**BLAST RADIUS:**
- **This document:** the header block, the Date line, and Amendment E.
- **Downstream:** the 5 files in §E.9.
- **Forward:** W5c (TD-D43 (i)–(iii), the T5.47 extension) and T3.1 (L29/L31).
- **Not touched:** W1–W4, `posture.py`, the CLI, the installer, the sweep, and any routing data other
  than the `tools:` block.

**Change classification: ADDITIVE.** All five rules are stricter-only, on a loader that has no
consumer and no executor yet. One new CORE key carries a literal derived from the current data, and no
built contract is reversed. If the architect judges either of the following **structural**, it goes to
a human before the coder starts:
- L31's fail-closed consumer behaviour (Q1);
- the AD-9 narrowing (Q3).

**Architect review is requested.** This amendment is not handed to the coder until the architect
approves. Iteration: Amendment E round 1 of 5. No temp-state file was written, because this dispatch was
constrained to edit this one file only.

**Not done here:** no code, data, test or script was written into the repository. No issue was filed,
no label was created, no comment was posted, nothing was committed, and no register entry was written.

---

## Amendment F (2026-10-03) — W5c: the explain-only sweep, the installer's registry-data step, the ship-list (#1930(b), #1951)

**Status:** **APPROVED WITH EDITS, Amendment F round 1 of 5 (§F.8). The round-1 edits marked
"(architect, round 1)" are binding. It may be handed to the coder; no human ruling is required first.** W5a (#1933), W5b (#1943) and the hardening slice (#1952) have merged
(`main` at `aac066168`). §D.9 and §D.10 recorded that W5c had no design. This is that design. Where it and
§7.7, §7.9, §9.5 (T5.30, T5.31, T5.33), §C.2.10, §C.2.11, §C.2.12 (T5.44, T5.47, T5.48) or §E.8
disagree, Amendment F governs. Everything it does not name stands.

**Numbering.** TD-VF-33…TD-VF-40, TD-D50…TD-D58, tests T5.30, T5.31, T5.33, T5.44, T5.47 and T5.48
(re-specified), and new tests T5.65…T5.72. TD-D49, reserved by Amendment E and never used, stays unused.

**Applied, not reopened:**
- **#1930 option (b)**, confirmed by the human from his own account at 2026-10-02 17:15Z. The sweep
  leaves the consumer ship-set until W7. It returns with the registry modules as one ESC-E decision.
- **#1951.** The installer emits the WHOLE rows that L31 checks, and the autocrlf false `installed_drift`
  is handled.
- **§C.2.10:** TD-D29, TD-D30 and the positional-ref narrowing.
- **§C.2.11:** TD-D31, TD-D32, and items 1, 3 and 5.
- **§D.10:** `project.yaml` and `resolved-packs.txt` stay off the ship-list.
- **§E.8:** TD-D43 (iv), and the T5.47 extension.
- **#1947 (ARCH-ESC-E1/E2)** gates W7. Nothing here designs a W7 consumer effect.

### F.1 Verification findings — TD-VF-33…TD-VF-40 (tree at `aac066168`)

**TD-VF-33 — CONTRADICTION: Amendment E calls W5c "the sweep that executes resolved deterministic
bindings". The binding ADR says the W5 sweep executes nothing.**
- **The executing reading:** Amendment E's status line and §E.2's "W5c obligations" (TD-D43 (i)–(iii))
  assume that W5c runs bindings. #1932's issue text says the same.
- **The ADR:**
  - AD-11 (`ADR-1643:549`) is BINDING: the script *"survives only as `--explain` over the resolved
    registry"*.
  - The §5 W5 row (`:785`) says *"reduced to `--explain`"*.
  - Execution belongs to AD-13's runner, `dimension_sweep_cli.py` + `bootstrap/run_dimensions.sh`
    (`:607-612`). That runner is W7, which is blocked on ESC-2 (`:787`).
  - AD-10 (`:535-542`) says CI-covered deterministic dimensions are *"trusted as already run once"*.
- **This document:** §7.9 (`:2100-2101`) says the script *"no longer hands execution to anyone's
  discretion"*. ESC-K (`:2107`) says *"W7, when the sweep actually executes"*.
- **Resolved by TD-D50.**

**TD-VF-34 — `plan` already satisfies TD-D43 (iv), `resolve` does not, and the CLI's root is its own
location.**
- `plan` calls `dr.load(root)` with no `packs` (`dimension_registry_cli.py:110`), so L31's resolved-packs
  check runs.
- `resolve` forwards `--pack` as `packs=` (`:100`), which skips that check.
- The CLI's repo root is `Path(__file__).resolve().parents[2]` (`:33`). Today's sweep diffs the caller's
  cwd (`run_post_change_sweep.sh:44-50`). Run from another checkout, it would diff one tree and load
  another tree's registry.
- `plan --base` diffs `<base>...HEAD` (`:79`), which is not the sweep's grammar.
- `plan` with neither `--base` nor `--changed-file` is a usage error (`:105-106`).

**TD-VF-35 — today's sweep swallows git failures. That was safe only while an empty set exited 1.**
- Every `git diff` at `:44-50` ends `2>/dev/null || true`.
- A failed diff today prints "No changed files detected" and exits 1 (`:53-56`).
- Under TD-D29, an empty set exits 0. The same failure would then print "no review dimension applies"
  for a diff that was never computed. §C.2.10's positional-ref narrowing exists to forbid exactly that
  answer.
- **Resolved by TD-D51.**

**TD-VF-36 — the installer anchors re-verify, and §C.2.11's citations hold.**
- **R3:** the loop is at `hos_install.sh:1287-1288`. R2c has already replaced `_resolved_packs` with the
  closure (`:1269`).
- **Ship-list copy loop:** `:1905-1917`. It handles literal paths only, and a missing source warns and
  skips (`:1910`).
- **The `contract/` section:** `:2105-2122`.
- **The `.hos-manifest` block:** `:2191-2406`.
  - `_whole_rows` (`:2234`) feeds both `assemble_manifest` (`:2244-2254`) and the regions-absent fallback
    (`:2260`).
  - Orphan detection is at `:2272-2281`, and `.hos-release` is written at `:2408-2418`.
- **`cp_framework_file`** (`:615-626`) is a plain `cp`. It returns 0 even when it warns and skips.
- **`ensure_line`** (`:631-640`) hard-codes the label prefix `.gitignore:`.
- **Nothing in the installer reads or writes `.gitattributes`.**

**TD-VF-37 — GAP in §C.2.11 item 2: a leftover `pack-<slug>.yaml` for a *resolved* pack that ships no
`dimensions.yaml` is never removed, and L31 rejects it.**
- Item 2 prunes only the slugs that are **not** in `_resolved_packs`.
- So a leftover file survives when its pack is still resolved but `<pack_dir>/dimensions.yaml` is gone.
  That happens when a consumer-local pack drops the file, or a release removes it. TD-D32 then emits no
  row for the leftover.
- L31 checks, for each slug in the resolved pack set, `pack-<slug>.yaml` if it exists on disk or has a
  manifest row (`dimension_registry.py:271-276`). *(architect, round 1: corrected from "every pack file
  that exists". An unresolved leftover is L20's `stale_pack_file`, not L31's. The conclusion is
  unchanged, because the leftover here belongs to a resolved slug.)* Every load in that tree therefore
  fails `installed_drift … has no row in .hos-manifest`. It fails closed, but the installer broke the
  install.
- **Resolved by TD-D54 step 1b.**

**TD-VF-38 — GAP: the fresh-install commit hint omits `.hos-manifest`.**
- `hos_install.sh:2500-2501` lists `.claude/ AGENTS.md METHODOLOGY.md audit/ contract/ scripts/ .github/
  prompts/ .gitignore .hos-release`.
- PR mode is unaffected, because it runs `git add -A` (`:2428`).
- A consumer who follows the hint commits `.hos-release` without `.hos-manifest`. From W7 on, every other
  clone of that repository, including CI, then fails L31 with `cannot read .hos-manifest`.
- **Resolved by TD-D56.**

**TD-VF-39 — the autocrlf case (#1951), probed.** The probe ran in `/tmp/claude/w5c/` only.
- **Setup:** a real `--local --pack django` install, with the W5c files simulated and committed.
- **Without `.gitattributes`:** a clean re-checkout with `core.autocrlf=true` rewrote `core.yaml`,
  `resolved-packs.txt` and `.hos-manifest` to CRLF. `load()` then raised
  `installed_drift … differs from its .hos-manifest sha256`.
- **With `.gitattributes`:** the committed file held three lines, `contract/dimensions/** -text`,
  `contract/resolved-packs.txt -text` and `.hos-manifest -text`. The same re-checkout kept LF, and
  `load()` was green.
- **Pattern coverage:** `git check-attr text` shows that `contract/dimensions/**` covers `postures/` and
  `prompts/`, and that `contract/OVERSIGHT-CONTRACT.md` stays `unspecified`.
- **Resolved by TD-D55.**

**TD-VF-40 — the T5.47 extension is satisfiable, and install-driven tests are release-only.**
- **The install probe:** `HOS_NO_CONFIG=1 hos_install.sh --local <tmp> --pack django` took about 5 s.
  - It wrote no `contract/dimensions/`, and it copied the sweep (ship-list `:59`).
  - Simulating the W5c additions made `dr.load(target)` green: 17 entries, 23 bindings (17 core + 6
    django), and `packs == ("django",)`. The additions were the item-1 files, `pack-django.yaml`,
    `resolved-packs.txt`, and target-sha WHOLE rows.
  - L10 and L11 hold, because the shipped agents are present and the gates keep mode 755.
- **The slow marker:** every real-install test in `tests/framework/test_pack_install.py` is
  `@pytest.mark.slow`. `pyproject.toml:19` defines that marker as release-only, and
  `run_tests_inner_loop.sh:86` excludes it.
- **Handled by TD-D58.**

*Re-confirmed (TD-VF-19 holds):*
- **No programmatic caller exists.** The prose references are `CLAUDE.md:351`, `docs/AGENTS.md:929` and
  `:1082`, `docs/OVERSIGHT-RUNBOOK.md:843`, `docs/CUSTOMIZATION.md:387`, `docs/SETUP.md:232` and `:278`,
  and `SCRIPTS-INDEX.md:122`. The last is generated from header line 2 and pinned by
  `tests/framework/test_scripts_index.py`.
- **`framework-setup-validator.md:70`** is HOS-only, and it checks only that the file exists.
- **`.claude/agents/post-change-sweep.md`** does its own categorisation and never names the script, so
  ESC-K stays with W7.
- **#1932, #1931 and #1937:** their engine work merged as `ac3cbf77f` and `aac066168`. What is left for
  W5c is TD-D43 (iv) and the T5.47 extension, both designed below. All three issues are still
  `state=open`. Closing them is the orchestrator's job.

### F.2 The sweep (TD-D50…TD-D53) — supersedes §7.9 and §C.2.10 where they differ

**TD-D50 — the W5c sweep executes no binding (TD-VF-33).**
- **What it may run:** its only subprocesses are `git` and the resolved interpreter. The interpreter runs
  either `scripts/automation/dimension_registry_cli.py` or the TD-D53 renderer. The sweep never executes,
  sources or passes on a `Binding.tool`.
- **Where TD-D43 (i)–(iii) now bind:** their content is unchanged (an in-process `ResolvedRegistry`; an
  argv list `[root / tool, …]`; `tool` and `tool_sha256` for each executed binding). They now bind the
  **first component that executes a binding**, which is AD-13's runner. W7's TD inherits them
  verbatim.
  - *(architect, round 1)* AD-13's runner first lands in **W6** (the ADR §5 measurement slice: "AD-13
    runner, one judgment entry"), not W7. So the obligations bind **whichever of W6 and W7 first
    executes a deterministic `Binding.tool`**. W6's TD must say whether it does. If W6 executes only its
    one judgment entry, (i)–(iii) pass to W7 unchanged.
  - *(architect, round 1)* For W6's TD (forward obligation, not designed here): the judgment-binding
    analogue of (i) and (ii) binds W6. The agent, prompt and posture come only from a
    `ResolvedRegistry` loaded in the same process, and the agent is reached through
    `bootstrap/invoke_agent.sh` as an argv list. The analogue of (iii) is TD-D34's prompt hash.
- **#1932's acceptance line** ("landed before W5c executes bindings") holds trivially.
- **TD-D43 (iv) binds W5c as written.** The sweep loads the registry only through `plan` and through
  `resolve`, and never passes `--pack` to either.
- **Rejected:** an opt-in `--run-deterministic` in W5c. It contradicts AD-11 and pre-empts ESC-2. It
  would also give AD-10's deterministic dimensions, which are trusted as already run, a second runner
  (D41).
- **Pinned by:** T5.65 and T5.66.

**TD-D51 — git failures fail closed (TD-VF-35).** This narrows §C.2.10's "byte-for-byte today's" in one
respect only: errors are no longer discarded. The mapping from input form to git command is unchanged.
- **Any git call that exits non-zero** ends the sweep with exit 1, empty stdout, and one stderr line:
  `run_post_change_sweep.sh: git diff failed (<git args>): <first line of git's stderr>`.
- **The no-argument form** runs `git diff --name-only HEAD`. If that succeeds and prints nothing, the
  sweep runs `git rev-parse --verify --quiet HEAD~1`:
  - if `HEAD~1` exists, it uses `git diff --name-only HEAD~1`, checked in the same way;
  - if it does not (a clean root commit), the set is empty and TD-D29 applies (exit 0).
- **Outside a git work tree:** that is a git failure, so exit 1.
- *(architect, round 1)* **Scope of "any git call".** The rule covers the **diff-computing** calls
  (`git diff …`, and the `rev-parse --verify --quiet HEAD~1` above, where non-zero means "no parent").
  The two §C.2.10 narrowing probes, `ls-files --error-unmatch` and `rev-parse --verify --quiet
  <arg>^{commit}`, are **boolean**. A non-zero exit from either means "no", never "abort". As drafted,
  "any git call that exits non-zero" would make every untracked explicit file argument exit 1. That is a
  defect, because `nosuch.py` must exit 0 (T5.48). Consequence, stated: explicit file arguments still
  work outside a git work tree, because no diff runs. Only the computed forms fail closed there.
- *(architect, round 1)* **A repository with no commits.** `git diff --name-only HEAD` fails because
  `HEAD` is unborn, so the no-argument form exits 1. That is correct: no diff was computed. `--staged`
  still works there.
- *(architect, round 1)* **Paths are read NUL-separated.** Every diff-computing call passes `-z`, and
  the sweep reads its output with a bash-3.2-portable loop, `while IFS= read -r -d '' p; do …; done`
  (no `mapfile`). Without `-z`, git's default `core.quotePath` emits a non-ASCII or control-character
  path as a C-quoted string with surrounding `"`. A predicate such as `\.py$` then fails to match
  `"caf\303\251.py"`, which gives a confident "not applicable" for a file that was changed. That is the
  same false answer §C.2.10's narrowing forbids. The mapping from input form to git command is
  otherwise unchanged. Empty arrays are expanded as `${arr[@]+"${arr[@]}"}` (`set -u` on bash 3.2),
  as `hos_install.sh` does.

**TD-D52 — one tree, one CLI contract (TD-VF-34).**
- **Repo root.** `REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"`. Every git call
  is `git -C "$REPO_ROOT" …`. The diffed tree is therefore the CLI's own root. Explicit file arguments
  pass through unchanged, as repo-relative strings.
- **The §C.2.10 positional-ref narrowing.** "Existing worktree or index path" means
  `[[ -e "$REPO_ROOT/$arg" ]]`, or `git -C "$REPO_ROOT" ls-files --error-unmatch -- "$arg"` succeeding.
- **Non-empty set.** `"$PY" "$REPO_ROOT/scripts/automation/dimension_registry_cli.py" plan` is called
  with one `--changed-file=<p>` per path. The `=` form stops a path that begins with `-` from parsing as
  an option. The argv is a bash array, never a string. The sweep never passes `--base`.
- **Empty set.** The sweep calls `"$PY" "$REPO_ROOT/scripts/automation/dimension_registry_cli.py"
  resolve` with no other argument, and discards stdout.
- **CLI exit codes:**

  | CLI exit | Sweep result |
  |---|---|
  | 0 | continue |
  | 1 | exit 1, passing the CLI's stderr through unchanged |
  | anything else | exit 1, plus `run_post_change_sweep.sh: internal error: dimension_registry_cli.py exited <rc>` |

- **Interpreter ladder and absent-CLI guard:** TD-D30, unchanged.

**TD-D53 — the human rendering is fixed text.**
- **`--json`:** stdout is the CLI's `plan` stdout, byte for byte (T5.30). An empty set gives `[]` and a
  newline.
- **Otherwise:** the sweep pipes the `plan` JSON into `"$PY" -c "$_RENDER_PY"`.
  - `_RENDER_PY` is a single-quoted bash variable holding Python that imports only `json` and `sys`.
  - If the renderer fails, the sweep exits 1.
  - *(architect, round 1)* **Capture, check, then render. Never a live pipe.** The sweep captures the
    CLI's stdout into a variable and its exit code into another, applies the TD-D52 exit table, and only
    on CLI exit 0 feeds the captured JSON to the renderer, through a here-string or `printf '%s'`. With
    `cli | renderer` under `pipefail`, a CLI failure would hand the renderer empty input. The renderer's
    own traceback would then reach stderr beside the CLI's one-line diagnostic, and the TD-D52 table
    (pass-through on 1, internal-error line on anything else) could not be applied. The same capture
    rule applies to `--json`. A failed CLI must leave stdout empty, never partial JSON.
- **Output format** (`<…>` is substituted, and the two-space indents are literal):
  ```
  Changed files (<n>):
    <path>                         one line per changed_files item, in the CLI's order

  Review dimensions (registry <digest[:12]>, packs: <p1, p2> | none):
    <entry>: APPLIES | not applicable
      + <binding-id> [<kind>] matched <k> file(s): <f1>, <f2>, …
      - <binding-id> [<kind>] <reason>

  <a> of <e> dimension(s) apply; <b> of <t> binding(s) fired.
  ```
  - Entries appear in order of first appearance in `plan`, and bindings in `plan` order.
  - An entry is `APPLIES` if any of its bindings applies.
  - `<reason>` is the CLI's string, verbatim.
- **Empty set:** stdout is the single line `No changed files — no review dimension applies.`
- **Header line 2** becomes
  `# run_post_change_sweep.sh — explain which review dimensions apply to a diff (ADR-1643 AD-11).`
  `SCRIPTS-INDEX.md` is regenerated.
- **The header's usage and exit-code blocks** state §C.2.10's grammar and table, plus TD-D51. The header
  also says: *HOS repository only until #1643 W7 (#1930). It is not shipped to consumer installs.*

The rest of §7.9 and §C.2.10 stands. `categorize()`, the domain helpers, the Track block and the two
"To run" lines are deleted. `--framework-only` exits 2 with the named line.

**Behaviour by tree:**
- **HOS itself.** There is no `.hos-release`, so L31 is skipped (TD-D48). `resolved-packs.txt` holds zero
  slugs (TD-D38). The plan is core plus HOS `project.yaml`, which includes
  `project:code-review/framework-validator`.
- **A new consumer install.** No script is installed (TD-D57).
- **An upgraded consumer.** Its pre-W5c copy is reported as an orphan, and `--prune` archives it if it is
  unmodified (`hos_install.sh:2272-2281`, `:2351` ff.).
- **A hand-copied script.** TD-D30's absent-CLI guard exits 1.
- **W7.** It restores the ship-list line together with `scripts/automation/**`, as one ESC-E decision
  (#1930(b)). That is recorded for W7's TD and not designed here.

### F.3 The installer (TD-D54…TD-D57) — supersedes §C.2.11 item 2's behaviour list; items 1, 3, 4 and 5 stand

**TD-D54 — the registry-data step, exactly.**
- **Unchanged from TD-D31:** the placement, the table, and the R3 parallel array.
  - The table is `_REGISTRY_KINDS=( "dimensions.yaml:contract/dimensions" )`.
  - `_resolved_pack_dirs+=("$_pack_dir")` goes in the R3 loop, immediately after `_resolve_pack_dir`
    succeeds (`:1288`).
- **Placement:** one block, after `:2122` and before the `audit/` section, headed
  `# ── contract/dimensions/ + resolved-packs.txt — registry data (ADR-1643 TD-D31/D32/D54) ──`.

The block runs these steps:
1. **Copy or remove each resolved pack's file.** This runs for each kind row, and within it for each
   index `i` of `_resolved_packs`, where `slug=${_resolved_packs[i]}`,
   `src=${_resolved_pack_dirs[i]}/<pack_source>` and `dst=<directory>/pack-<slug>.yaml`:
   - **a. `src` is a regular file:** run `cp_framework_file "$src" "$TARGET_REPO/$dst" "$dst"`. The
     label is the target-relative path, which T5.47 counts. Then, unless this is a dry run and only if
     `[[ -f "$TARGET_REPO/$dst" ]]`, append
     `"$dst"$'\t'WHOLE$'\t'"$(_sha256 "$TARGET_REPO/$dst")"` to `_generated_whole_rows`.
   - **b. `src` is not a regular file** (new, TD-VF-37): if `$TARGET_REPO/$dst` exists, run
     `run rm -f -- "$TARGET_REPO/$dst"`, then
     `warn "$dst removed — pack '$slug' ships no <pack_source>"`.
2. **Prune unresolved packs.** For each `$TARGET_REPO/<directory>/pack-*.yaml` whose slug is not in
   `_resolved_packs`, run `run rm -f -- <path>`, then
   `warn "<rel> removed — pack '<slug>' is no longer resolved"`. Iteration is `nullglob`-safe.
3. **Write `contract/resolved-packs.txt`**, once and not per kind.
   - The bytes are exactly §C.2.5's header line, then one `<slug>\n` for each element of
     `_resolved_packs`, in order.
   - Write with `printf` and the dry-run check inlined, as `ensure_line` does. Never use `run`.
   - Under `--dry-run`, print `dry_run "Would write contract/resolved-packs.txt:"` and then each line,
     indented.
   - Otherwise, append its WHOLE row, with the target's sha, to `_generated_whole_rows`.
4. **Add TD-D55's `.gitattributes` lines.**

**Manifest concatenation (TD-D32), exactly.**
- **Where:** immediately after `_whole_rows="$(enumerate_framework_files "$HOS_SOURCE")"` (`:2234`).
- **What:** if `${#_generated_whole_rows[@]} -gt 0`, append a newline and the rows, joined by newlines,
  to `_whole_rows`. Both the `assemble_manifest` path and the fallback then carry them.
- **`core.yaml`'s row:** item 1 lists the file, so `enumerate_framework_files` already emits its row
  from the source bytes, and `cp` keeps those bytes (TD-VF-31).
- **#1951 obligation 1:** discharged by these rows together with item 1.

**TD-D55 — the consumer's `.gitattributes` marks the HOS-hashed files `-text` (#1951 obligation 2).**
- **The lines:** step 4 appends each of the following to `$TARGET_REPO/.gitattributes` when no identical
  line is present. It creates the file if it is absent, and a dry run prints the append instead:
  - `contract/dimensions/** -text`
  - `contract/resolved-packs.txt -text`
  - `.hos-manifest -text`
- **The `ensure_line` change:**
  - Its two hard-coded `.gitignore:` prefixes become `$(basename "$file"):`. Every existing call passes
    `$GITIGNORE`, so their output is unchanged.
  - ~~Its presence test tightens from `grep -qF` to the whole-line `grep -qxF`.~~ *(architect, round 1:
    struck. Tightening it for every caller is not output-neutral. Consumers whose `.gitignore` holds
    `.claudetmp/*`, `/.claudetmp/`, or a commented-out `#.claudetmp/` currently satisfy the substring
    test. They would get a new line appended on their next upgrade, so the claim "their output is
    unchanged" is false for the eight `.gitignore` call sites (`hos_install.sh:734-749`).)*
  - *(architect, round 1)* **Replacement: an opt-in whole-line mode.** `ensure_line` gains an optional
    fourth argument. When it is the literal `exact`, the presence test is `grep -qxF`. Otherwise it
    stays `grep -qF`, so the `.gitignore` callers keep their behaviour byte for byte. All three
    `.gitattributes` calls pass `exact`. Whole-line matching is required there because a substring
    test would treat a consumer's `contract/resolved-packs.txt -text=…` or
    `#.hos-manifest -text` as already present. Whether the `.gitignore` callers should also be
    whole-line matched is a separate, pre-existing question and is out of W5c's scope.
  - *(architect, round 1)* **Missing-final-newline guard (all callers).** Before appending, if the file
    exists, is non-empty, and its last byte is not `\n`, `ensure_line` writes a `\n` first, within the
    same dry-run check. Today, appending to a file that lacks a final newline joins the new line onto
    the consumer's last line. In `.gitattributes`, that silently corrupts one of the consumer's own
    rules (`*.png binarycontract/dimensions/** -text`). This changes behaviour only in the case where the
    current behaviour corrupts the file, so it applies to the `.gitignore` callers too.
- **Why `-text` and not `eol=lf`:**
  - L31 hashes raw bytes, and #1951 says "do not normalise".
  - `-text` turns off all end-of-line conversion in both directions.
  - `eol=lf` still normalises on commit, so a consumer's CRLF hand edit would be committed as bytes they
    never saw.
- **Why `contract/dimensions/**`:** at W7, TD-D34 hashes the prompt files' bytes. A CRLF checkout would
  give each clone a different template version. The pattern also covers `project.yaml`, which is
  harmless.
- **No manifest row for `.gitattributes`:** it is consumer-owned, like `.gitignore`.
- **Stated limit:** a clone that already checked out CRLF bytes keeps them until it re-checks out the
  files or re-runs the installer. L31's existing message already names the installer as the remedy.

**TD-D56 — the commit hint at `:2500-2501` gains `.hos-manifest .gitattributes`** after `.gitignore`
(TD-VF-38). Nothing else in that text changes.

**TD-D57 — the `framework_consumer_files.txt` edits, exactly.**
- **Delete** line 59, `scripts/framework/run_post_change_sweep.sh` (#1930(b)).
- **Add two lines** to the header's "NOT listed here (deliberately)" block:
  - `#   - scripts/framework/run_post_change_sweep.sh — withheld until #1643 W7 ships the registry modules (#1930 option (b))`
  - `#   - contract/dimensions/project.yaml (consumer-owned, TD-D19) and contract/resolved-packs.txt (installer-generated, TD-D27)`
- **Add a section**, `# ── contract/dimensions/ — review-dimension registry data (#1643 W5, §C.2.11 item 1) ──`.
  It holds the 14 item-1 paths, each a literal path prefixed `contract/dimensions/`, in `LC_ALL=C`
  order: `core.yaml`, the 4 postures, the 8 prompts, and `project.yaml.template`.

**Not changed:**
- `consumer_agents.txt`: the `post-change-sweep` agent still ships, and ESC-K belongs to W7.
- `REQUIRED_SOURCE_PATHS`: listing `core.yaml` there would make any fetch of an older release fatal.
- `--squash`: item 5 stands.

### F.4 File budget — one PR, 12 files

| # | Path | Change | Protected? |
|---|---|---|---|
| 1 | `scripts/framework/run_post_change_sweep.sh` | rewrite (TD-D50–D53) | yes (`scripts/framework/**`) |
| 2 | `scripts/framework/framework_consumer_files.txt` | TD-D57 | yes |
| 3 | `bootstrap/hos_install.sh` | TD-D54–D56, R3 array, `ensure_line` | yes (`bootstrap/**`) |
| 4 | `CLAUDE.md` | `:351` → `\| Explain which review dimensions apply to a diff (HOS repo only until #1643 W7, #1930) \| \`scripts/framework/run_post_change_sweep.sh\` \|` | yes |
| 5 | `SCRIPTS-INDEX.md` | regenerated by `gen_scripts_index.sh` | no |
| 6 | `docs/AGENTS.md` | `:929`, `:1082` | yes (`protected_surfaces.txt:21`) |
| 7 | `docs/OVERSIGHT-RUNBOOK.md` | `:838-848` | no |
| 8 | `docs/CUSTOMIZATION.md` | `:387` | no |
| 9 | `docs/SETUP.md` | `:232`, `:278` | no |
| 10 | `tests/automation/test_post_change_sweep.py` | new: T5.30, T5.31, T5.48, T5.65–T5.68 | no |
| 11 | `tests/framework/test_install_registry_data.py` | new: T5.33, T5.44, T5.47, T5.69–T5.72 | no |
| 12 | `tests/framework/test_consumer_framework_files.py` | T5.47's static half | no |

**Doc edits (rows 6–9).** Each touches only the cited lines.
- Each says the script *explains which review dimensions apply to a diff, from the registry*, and is
  *HOS-repo-only until #1643 W7 (#1930)*.
- Each drops the claims that the script prints an agent plan and that the agent "reads this".
- The agent's own instructions are not touched (ESC-K).
- `SETUP.md:278`: the consumer-tree listing loses its `run_post_change_sweep.sh` line.

**Budget.** That is **12 files, with 3 of headroom.** Any fourth addition means a split, not an
exception:
- **W5c-1** is files 2, 3, 11 and 12, and lands **first**. The rewritten sweep must never be on `main`
  while it is still on the ship-list.
- **W5c-2** is files 1 and 4–10.

**Prerequisites and packaging:**
- The hardening slice has merged (#1952).
- This amendment ships in its own TD PR, following the §D.7 Q6 precedent.
- The code PR is CODEOWNERS-gated through rows 1–4 and 6.

**Review set:**
- `code-reviewer`.
- `security-reviewer`: TD-D50's non-execution, the argv construction, and the `rm -f` targets.
- `infra-reviewer`: TD-D54–D56, including the line-ending check that §E.12 requires.
- `reliability-reviewer`: TD-D51, and whether L31 can be satisfied after a real install.

**The PR body must name:**
- the #1930(b) removal;
- the new consumer `.gitattributes` write, *(architect, round 1)* presented as a **separately
  strikeable decision**. The body says that it writes into a consumer-owned file, gives the three lines,
  and names the fallback if the CODEOWNERS approver strikes it: drop step 4, the `exact` mode and T5.69,
  and rely on L31's existing installer-remedy message (#1951's "documented decision" route). The
  `-text` write lands only with that approver's explicit acceptance;
- the installer-written `contract/resolved-packs.txt` (§C.4.1);
- the `-m slow` evidence (TD-D58).

### F.5 Tests

**TD-D58 — placement and markers.**
- **Sweep tests** shell out to bash in staged trees and are **not** slow.
- **Install-driven tests** run the real installer (about 5 s, TD-VF-40). They are `@pytest.mark.slow`,
  as in `test_pack_install.py`, with one module-scoped fixture per install configuration.
- **Static tests** are not marked.
- **Evidence:** CI and the inner loop skip `slow`. The PR body must therefore show the output of
  `scripts/oversight/.venv/bin/python -m pytest -m slow tests/framework/test_install_registry_data.py`.

**Staging helper (file 10).** `sweep_tree(tmp, packs, project_text)` does the following:
1. Calls W5b's `stage()`, imported from `tests.automation.test_dimension_registry_data`.
2. Copies in `scripts/__init__.py`, `scripts/automation/__init__.py`,
   `scripts/automation/lib/{__init__,dimension_registry,posture}.py`,
   `scripts/automation/dimension_registry_cli.py`, and the sweep with mode 755.
3. Runs `git init` and makes commit 0.

Every run sets `HOS_REGISTRY_PYTHON=sys.executable`, except the interpreter-rung cases.

**Sweep tests (file 10):**
- **T5.30 (re-specified).** Fixture `sweep_tree(["django"])`. With explicit paths `myapp/views.py`,
  `templates/base.html` and `README.md`, `--json` stdout is byte-equal to the captured stdout of
  `cli.main(["plan", "--changed-file=…" ×3], repo_root=tree)`.
- **T5.31 (re-specified).** The text output for the same input contains none of
  `invoke the post-change-sweep agent`, `check if PII-relevant`, `Track `, `To run:` or
  `Agents to invoke`. The script source defines no `categorize`.
- **T5.48 (re-specified; §C.2.12's list plus TD-D51/D52).**
  - **Fixture:** after commit 0, commit 1 adds `a.py` and commit 2 adds `b.py`. Then `c.py` is staged
    and `a.py` is modified but not staged.
  - **Changed-file computation**, checked through `--json`'s `changed_files`:

    | Input | Expected `changed_files` |
    |---|---|
    | `x.py y.py` | `["x.py","y.py"]` |
    | `--staged` | sorted `git diff --cached --name-only` |
    | `HEAD~1` | sorted `git diff --name-only HEAD~1` |
    | no argument | sorted `git diff --name-only HEAD` |
    | no argument, after `git stash -u` | `["b.py"]` |
    | no argument, a clean tree at commit 0 only | exit 0, and stdout is exactly `[]\n` *(architect, round 1: under `--json` the empty set emits the bare array, not the plan object, so this row asserts stdout bytes and not a `changed_files` key)* |
    | *(architect, round 1)* explicit `café.py` | `["café.py"]` (the UTF-8 name, unquoted) |
    | *(architect, round 1)* no argument, after modifying a committed `café.py` | contains `"café.py"` and no element beginning with a double quote (pins TD-D51's `-z`) |

  - **Usage and grammar:**
    - `--framework-only` exits 2 with the §C.2.10 line, and an unknown `-x` exits 2.
    - A branch `feature` that is not a path exits 2 naming the HEAD-relative form.
    - `nosuch.py` is taken as a file and exits 0.
  - **Registry failures, each exit 1:**
    - an empty set with `core.yaml` deleted, with `dimension_registry: core_missing:` on stderr, which
      proves `resolve` ran;
    - a project predicate `(a+)+$`, with `unsafe_pattern` on stderr;
    - the CLI removed, with the TD-VF-21 line.
  - **Interpreter rungs:**
    - `HOS_REGISTRY_PYTHON=/nonexistent` exits 1.
    - With the variable unset, no `.venv`, and no `python3` on `PATH`, the sweep exits 1 with a line
      naming `ensure_venv.sh`.
    - With the variable unset and `scripts/oversight/.venv/bin/python` symlinked to `sys.executable`,
      the sweep exits 0.
    - At source level, the sweep and `invoke_agent.sh` each reference an env override, then
      `scripts/oversight/.venv/bin/python`, then `python3`, in that order.
- **T5.65 (TD-D50, non-execution).**
  - **Setup:** in `sweep_tree(["django"])`, replace `scripts/oversight/gates/lint_check.sh` with an
    executable script that creates `<tmp>/SENTINEL`, and commit. The file is a `tools:` entry, bound by
    `core:lint/all` with predicate `.*` (`core.yaml:163-168`).
  - **Run:** the sweep, in both text and `--json` modes, on `myapp/views.py`.
  - **Assert:** exit 0; `core:lint/all` is applicable; `SENTINEL` does not exist; and the script source
    contains no `eval`.
  - *(architect, round 1)* **Every tool, not one.** Replace **every** path in `core.yaml`'s `tools:`
    allowlist that the staged tree holds, including `scripts/run_second_review.sh`, with an executable
    that creates `<tmp>/SENTINEL-<basename>`. Then assert that no `SENTINEL-*` exists after both runs.
    Swap only `lint_check.sh` and a defect that executes some other binding's tool passes the test. The
    replacements must keep mode 755 so that L11 still loads the registry. The test therefore also proves
    that the sweep loaded the registry, and did not skip the load, before declining to execute.
- **T5.66 (TD-D43 (iv)).**
  - **Setup:** in `sweep_tree(["django"])`, add `.hos-release` and a `.hos-manifest` with correct WHOLE
    rows for `core.yaml`, `pack-django.yaml` and `resolved-packs.txt`.
  - **Baseline:** the sweep on `myapp/views.py` exits 0.
  - **Drift:** append `# edited` to `resolved-packs.txt`, which leaves the pack set unchanged. The sweep
    now exits 1, with `dimension_registry: installed_drift:` and `contract/resolved-packs.txt` on stderr.
    It does the same on the empty-set path. An explicit pack set would have skipped this check.
  - **Source level:** the script contains no `--pack`.
- **T5.67 (TD-D51).**
  - A staged tree **without** `git init`: exit 1, a `git diff failed` line on stderr, empty stdout.
    *(architect, round 1)* The run sets `GIT_CEILING_DIRECTORIES` to the staged tree's parent. Without
    it, a `tmp_path` that sits inside some other work tree makes `git -C` discover that repository, and
    the case passes or fails by accident of where pytest puts its temporary directory.
  - *(architect, round 1)* The same no-git tree with the explicit argument `myapp/views.py` exits 0. The
    narrowing probes are boolean (TD-D51 scope), so explicit files need no repository.
  - `HEAD~5` in a 3-commit fixture: exit 1. Today this reports no changed files.
- **T5.68 (TD-D53).** Input `myapp/views.py` with `{django}`, staged with `project_text=None`.
  *(architect, round 1: the 17/23 totals hold only with no `project.yaml`. A project layer adds
  entries and bindings.)*
  - *(architect, round 1)* **Capture rule:** in a tree where `core.yaml` is deleted, the text mode exits
    1, stdout is empty, and stderr is exactly one line, the CLI's `dimension_registry: core_missing:`
    line. A renderer traceback must not appear.
  - Every binding that `--json` marks applicable appears on a `+` line.
  - Every other binding appears on a `-` line, followed by its exact `reason`.
  - The last line matches `^\d+ of 17 dimension\(s\) apply; \d+ of 23 binding\(s\) fired\.$`.
  - An empty set prints exactly the TD-D53 line.

**Installer tests (file 11, except T5.47's static half):**
- **T5.33 (re-specified, slow).** Install `--pack django`, then re-install `--pack astro`.
  - `pack-django.yaml` is gone, and the "no longer resolved" warn line was printed.
  - `pack-astro.yaml` is byte-equal to `packs/astro/dimensions.yaml`.
  - `dr.load(target)` is green, with `packs == ("node","astro")`.
- **T5.44 (re-specified, static).**
  - The `_REGISTRY_KINDS=( … )` literal parsed from `hos_install.sh` equals
    `{(k.pack_source, k.directory) for k in dr.KINDS.values()}`.
  - `_resolved_pack_dirs+=` occurs exactly once, inside the R3 loop.
  - The TD-D54 block calls no `_resolve_pack_dir`.
- **T5.47 (re-specified, slow).**
  - **`resolved-packs.txt` bytes:**

    | Install | Exact bytes |
    |---|---|
    | `--pack astro` | `<§C.2.5 header>\nnode\nastro\n` |
    | `--no-pack` | `<header>\n` |

  - **One copy per pack:** under `--pack django`, exactly one log line contains
    `contract/dimensions/pack-django.yaml (framework — updated)`.
  - **`.hos-manifest` rows:**
    - exactly one WHOLE row each for `pack-django.yaml` and `resolved-packs.txt`, each with the target
      file's sha;
    - a `core.yaml` row equal to the sha of HOS's source `core.yaml`;
    - no row for `scripts/framework/run_post_change_sweep.sh`.
  - **Absent from the target:** `contract/dimensions/project.yaml` and
    `scripts/framework/run_post_change_sweep.sh`.
  - **Not HOS's copy:** the target's `resolved-packs.txt` starts with the installer header, so it is not
    HOS's file (§D.10).
  - **Extension (§E.8):** `dr.load(target)` is green, with 17 entries, 23 bindings and
    `packs == ("django",)`.
  - **Drift-blocked install:**
    1. After the django install, edit the body of a `PACK:django` region in `code-reviewer.md`.
    2. Delete `pack-django.yaml`.
    3. Re-run `--pack django`.
    4. Expect exit 4, with `pack-django.yaml` still absent: Phase A aborted before the data step.
  - **Static half (file 12):** the ship-list holds all 14 item-1 paths and none of
    `contract/dimensions/project.yaml`, `contract/resolved-packs.txt` or
    `scripts/framework/run_post_change_sweep.sh`.
- **T5.69 (TD-D55, slow).**
  - **Setup:** after a `--pack django` install, `.gitattributes` holds each of the three lines exactly
    once. A re-install leaves each still exactly once.
  - **Run:** commit everything, set `core.autocrlf=true`, delete `contract/` and `.hos-manifest`, then
    run `git checkout -- .`. `dr.load(target)` is green.
  - **Control:** remove the three lines and commit, then repeat the re-checkout. `installed_drift`
    must now be raised, which proves the test discriminates.
  - `git check-attr text -- contract/dimensions/prompts/ui.md` reports `unset`.
  - *(architect, round 1)* **Missing final newline:** a pre-existing consumer `.gitattributes` whose
    last line is `*.png binary`, with no final newline, still holds `*.png binary` as its own whole line
    after install, and `git check-attr binary -- x.png` reports `set`.
  - *(architect, round 1)* **Near-miss line:** a pre-existing `#.hos-manifest -text` comment line does
    not suppress the real `.hos-manifest -text` line (pins `exact` mode).
- **T5.70 (TD-D54 step 1b, slow).** Install `--pack astro`, whose closure includes `node`, a pack that
  ships no `dimensions.yaml`. Plant `contract/dimensions/pack-node.yaml`, then re-install `--pack astro`.
  - The planted file is removed, and the warn line was printed.
  - The manifest has no row for it.
  - `dr.load(target)` is green.
- **T5.71 (TD-D56, static).** The installer's `git add` hint line contains `.hos-manifest` and
  `.gitattributes`.
  - *(architect, round 1)* **TD-D55 scoping, static:** every `ensure_line` call whose first argument is
    `$GITIGNORE` passes no fourth argument. Every call that targets `.gitattributes` passes `exact`.
- **T5.72 (dry run, slow).** `--dry-run --pack django` on a fresh target:
  - it creates no `contract/dimensions/`, no `contract/resolved-packs.txt` and no `.gitattributes`;
  - stdout contains `Would write contract/resolved-packs.txt:`, followed by a `django` line.

### F.6 Open questions — to `architect` (Q1 blocks the handoff to the coder; the others are confirmations)

- **Q1 (confirm, BLOCKING):** TD-D50. The W5c sweep executes nothing. TD-D43 (i)–(iii) move, unchanged,
  to the first executor (AD-13, W7). Only (iv) binds W5c.
  - This reconciles Amendment E's wording with AD-11 and §7.9. It does not change TD-D43's content.
  - If you rule that W5c must execute, this amendment's sweep design is void, and ESC-2 becomes a
    prerequisite of W5c.
- **Q2 (confirm):** TD-D51. Git failures exit 1. This narrows §C.2.10's "byte-for-byte today's".
- **Q3 (confirm):** TD-D55. The attributes are `-text`, not `eol=lf`, scoped to `contract/dimensions/**`
  and not just its `*.yaml`. This also changes `ensure_line`'s label and its whole-line match.
- **Q4 (confirm):** TD-D58. Real-install tests are `slow`, and therefore release-only, with the evidence
  in the PR body. Alternatively, un-mark one consolidated case (about 5 s) so that CI runs the T5.47
  extension.
- **Q5 (confirm):** the doc edits in rows 6–9 are in W5c's scope (Amendment C's human-review CONFIDENCE note: "those docs are
  W5's to update").

**Human escalations: none new.**
- #1930 is ruled.
- #1947 gates W7.
- The consumer-visible additions are the `.gitattributes` lines, the registry data files and
  `resolved-packs.txt`. All three arrive through a `bootstrap/**` and `contract/**` change that is
  already human-gated by CODEOWNERS, which matches the §C.4.1 precedent for `resolved-packs.txt`.
- If the architect judges the `.gitattributes` write structural, it goes to a human before the coder
  starts.

### F.7 Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design?*
- **TD-VF-35, TD-VF-37 and TD-VF-38: yes.** The swallowed git errors, the pack-without-source leftover
  and the commit hint were all in the tree when §7.7, §C.2.10 and §C.2.11 were written. This is a
  `startup-artifact-gap`. The orchestrating session should annotate the §C.3 issue. I file nothing.
- **TD-VF-33: a drafting inconsistency in Amendment E**, caught before any W5c code was written.
- **TD-VF-39: no.** #1951 surfaced it from L31, which postdates §7.

**Affected sign-offs:**
- **W5a, W5b and the hardening slice stand.** No engine, data or test behaviour changes. The only engine
  dependency is TD-D43 (iv), which `plan` already satisfies.
- **W5c is unbuilt**, so there are no orphaned approvals.
- **W7 inherits TD-D43 (i)–(iii)** under TD-D50, and the restoration of the ship-list line (#1930(b)).
- **W1–W4 are untouched.**

### F.8 Architect rulings — Amendment F round 1

**Verdict: APPROVED_WITH_EDITS.** The edits marked *(architect, round 1)* above are binding. With them
applied, W5c may go to the coder. **No human ruling is required before coding.** No ADR erratum is
needed: ADR-1643 is correct as written, and the inconsistency was in this TD (Amendment E). Iteration
1 of 5. The design converged in this round.

**Verified against the tree (`7d65306e8`, whose only delta over `aac066168` is this document):**
- **Re-read and holding:** every TD-VF-34/35/36/38 citation:
  - `dimension_registry_cli.py:33`, `:79`, `:100`, `:105-106`, `:110`;
  - `run_post_change_sweep.sh:44-56`;
  - `hos_install.sh:615-640`, `:1287-1288`, `:1905-1917`, `:2105-2122`, `:2205-2234`, `:2272-2281`,
    `:2408-2418`, `:2428`, `:2500-2501`.
- **Ship-list:** line 59.
- **Item-1 paths:** there are 14 (`find contract/dimensions -type f`, minus `project.yaml`).
- **Slow-marker plumbing:** `pyproject.toml:19` (marker definition), `run_tests_inner_loop.sh:86`
  (`-m "not slow and not integration"`), and `run_tests_release.sh` (runs everything).
- **Copy-loop and `contract/` section role guards:** both run under every role; neither sits inside the
  `! $ROLE_HUMAN` block at `:1988-2103`. So the new block sees the same role set as item 1's copies.
- **The `exit 4` abort precedes both:** `:1634` comes before `:1905` and `:2122`, so T5.47's
  drift-blocked case is sound.
- **One citation corrected:** TD-VF-37's description of L31.
- **File count:** 12 is right.
  - No existing test pins the old sweep. The only test hits are a corpus path at
    `test_dimension_registry_data.py:410` and two docstrings.
  - The validation stamp hashes `.claude/agents/*.md` only (`check_validation_current.sh:4-7`), and W5c
    touches no agent file, so no stamp file joins the PR.
  - The ≤15-file / ≤10-commit limit is `worker.md:191` (`docs/PR-SIZE-POLICY.md`). The split plan
    (W5c-1 before W5c-2) is the correct fallback, and its ordering argument is right.
- **`-text`:** TD-VF-39's probe is accepted. `-text` is the correct attribute because L31 hashes raw
  bytes and `eol=lf` normalises on commit.

**Q1 (BLOCKING) — TD-D50: CONFIRMED. The W5c sweep executes no binding. This is a correction, not a
structural change, and it needs no human.**
- **The ADR decides it, and the ADR is BINDING and human-ratified.**
  - AD-11's title says the script *"survives only as `--explain` over the resolved registry"*. Its body
    says it is *"rewritten to print a human-readable rendering of the resolved registry's plan"*.
  - The §5 W5 row says *"reduced to `--explain`"*.
  - Execution is AD-13's runner, in W6/W7. W7 is blocked on ESC-2, which is a human-gated
    deployment-topology change.
  - A W5c sweep that executed bindings would be a second runner, ahead of the human's ESC-2 ruling and
    in a script AD-10 says must not re-run CI-trusted gates. That would be the structural change. TD-D50
    is the absence of it.
- **Where "W5c executes" came from.** That phrase entered through #1932's issue text ("Once W5c wires
  `run_post_change_sweep.sh` to execute resolved bindings"). That text is worker-authored framing, not a
  human ruling. My own Amendment E round-1 rulings (§E.2 "W5c obligations", §E.8 "W5c inherits") then
  carried it forward unchecked. The error is mine to correct.
  - Every human statement in the chain (#1930's options, the Q1–Q8 rulings in the ADR) describes the
    sweep as reading the registry, never as executing it.
  - Re-homing an obligation that I attached to the wrong slice changes no product behaviour, no cost,
    no topology, no retention surface and no operational burden. The product-boundary checkpoint is not
    triggered.
- **TD-D43's content is unchanged.** Its binding point is corrected to "the first component that
  executes a deterministic `Binding.tool`". That is AD-13's runner, which first lands in **W6**, not W7
  (edit above). The judgment-binding analogue is recorded as a forward obligation on W6's TD.
- **#1932's acceptance line** is satisfied vacuously for W5c. It is in any case already satisfied in
  substance, because L32's allowlist merged in #1952.
- **The rejected `--run-deterministic` alternative stays rejected.**
- **Amendment E's text is not rewritten.** The Amendment F header now names §E.2 and §E.8 in its
  "governs" clause.

**Q2 — TD-D51: CONFIRMED WITH EDITS.**
- Discarding git's exit status was safe only while empty meant exit 1, and §C.2.10's TD-D29 removed
  that. Fail-closed is the only answer consistent with §C.2.10's own narrowing rationale.
- **Edits:**
  - (a) The rule is scoped to diff-computing calls. As drafted it would also abort on the two boolean
    narrowing probes, making every untracked explicit file argument exit 1, which contradicts T5.48's
    `nosuch.py` case.
  - (b) An unborn `HEAD` is stated to exit 1.
  - (c) **`-z`, read NUL-separated with a bash-3.2 loop.** Without it, `core.quotePath` C-quotes
    non-ASCII and control-character paths, and the registry returns a confident "not applicable" for a
    changed file. That is the exact false answer this amendment exists to forbid. It is a second
    narrowing of "byte-for-byte today's": the git command changes by one flag, and the mapping from
    input form to command is otherwise identical.
- Pinned by new T5.48 rows and T5.67 cases.

**Q3 — TD-D55: CONFIRMED WITH EDITS. Not structural, and not a pre-coding human escalation.**
- `-text` over `eol=lf` and the `contract/dimensions/**` scope are both right, for the reasons given.
  Appended lines are last in the file, so they override any earlier consumer `* text=auto` line for
  these paths.
- **Edits:**
  - (a) **The whole-line match is opt-in (`exact`), not global.** The drafted global `-qxF` change
    falsely claimed "output unchanged". It would append duplicate-intent lines to existing consumers'
    `.gitignore` on upgrade.
  - (b) **A missing-final-newline guard for all callers.** The current append corrupts the consumer's
    last line in that case.
- **On the product boundary.** Writing into a consumer-owned file is a consumer-visible change, so I
  considered routing it.
  - **Why it does not need pre-coding clearance:**
    - it touches only HOS-owned paths;
    - it is additive and idempotent;
    - it follows the installer's existing `.gitignore` precedent;
    - #1951 recommended it;
    - it lands only through a `bootstrap/**` PR that CODEOWNERS already human-gates.
  - **The condition:** the PR body presents it as a separately strikeable decision with a named
    fallback (edit in §F.4). The CODEOWNERS approval of that PR is the human clearance, and the approver
    can strike it without reopening this design.

**Q4 — TD-D58: CONFIRMED as drafted (slow, release-only, with `-m slow` output in the PR body).**
- The repository's convention and the marker's own definition (>5 s, real filesystem or subprocess)
  put a real install in `slow`. Breaking that for one ~5 s case sets a precedent the inner loop pays for
  on every PR.
- The cost of release-only coverage is bounded today, because nothing consumes the registry before W7.
- **Forward obligation on W7's TD:** when W7 makes L31 consumer-load-bearing and restores the sweep to
  the ship-list, it must un-mark one consolidated real-install `load(target)`-green case so that the
  inner loop guards it on every installer PR.

**Q5 — doc edits in W5c's scope: CONFIRMED.**
- `docs/CUSTOMIZATION.md:387` and `docs/SETUP.md:232` currently instruct consumers to run a script
  #1930(b) stops shipping. Leaving them unchanged would ship a broken instruction, so they must change
  in the same PR as the ship-list line.
- `docs/AGENTS.md` is a protected surface (`protected_surfaces.txt:21`). Its two rows change wording
  only. The agent's dispatch instructions (ESC-K) stay with W7.

**Other rulings (round 1):**
- **TD-D53 capture rule.** The CLI's output is captured and its exit checked before rendering, never
  piped live under `pipefail`. Otherwise the TD-D52 exit table cannot be applied, and a renderer
  traceback contaminates the one-line diagnostic. Pinned by the new T5.68 case.
- **T5.65 is strengthened to every allowlisted tool.** A one-tool sentinel does not prove
  non-execution.
- **T5.67 sets `GIT_CEILING_DIRECTORIES`.** Without it, the no-git case depends on where pytest places
  `tmp_path`.
- **T5.68 pins `project_text=None`.** The 17/23 totals assume no project layer.
- **T5.48's empty-set `--json` row asserts the bare `[]\n`.** That is §C.2.10's approved shape, and a
  `changed_files` key does not exist in that case.
- **TD-D54 steps 1a, 1b, 2 and 3, the manifest concatenation point, and TD-D56/TD-D57 are approved as
  drafted.**
  - Every `rm -f` target is confined to `contract/dimensions/pack-*.yaml`, with an R2b-validated slug
    on the 1b path.
  - Step 2 removes before the manifest is rebuilt, so a pruned file is never reported as an orphan.
  - `_generated_whole_rows` must be declared `=()` before the block, because of `set -u` on bash 3.2.
- **Review set** as in §F.4. `security-reviewer`'s brief additionally covers the `ensure_line` change:
  `exact` scoping and the newline guard.

**Human escalations: none.**
- #1930 is ruled.
- #1947 (ARCH-ESC-E1/E2) gates W7, not W5c.
- TD-D50 conforms the TD to the human-ratified ADR and does not depart from it.
- The `.gitattributes` write is cleared at the CODEOWNERS gate under the condition above.

**Startup-gap and sign-off analysis.** I agree with §F.7.
- TD-VF-35, TD-VF-37 and TD-VF-38 are a `startup-artifact-gap`. So is the `core.quotePath` defect found
  this round, which was present when §C.2.10 was written. The orchestrating session should annotate the
  §C.3 issue accordingly.
- TD-VF-33 is my own round-1 error in Amendment E (§E.2, §E.8). It was caught before any W5c code
  existed, so it orphans no approval.
- W5a, W5b and the hardening slice stand, because none of their behaviour depends on which slice
  executes bindings.
- W6's and W7's TDs, both unwritten, inherit the forward obligations recorded in TD-D50 and in Q4
  above.

---

## Human Review Required — Amendment F (2026-10-03, W5c sweep + installer)

**RISK: MEDIUM.**
- **The installer runs on every consumer install and upgrade.** It now does three new things:
  - it writes `contract/dimensions/` data and `contract/resolved-packs.txt`;
  - it deletes stale `pack-*.yaml` files;
  - it appends three lines to the consumer's `.gitattributes`.
- **A wrong manifest row** makes every W7 consumer load fail closed (L31).
- **A wrong delete** removes a HOS-owned file, never a consumer file. The targets are confined to
  `contract/dimensions/pack-*.yaml`.
- **The sweep gates nothing.** It explains, it executes nothing (TD-D50), and it is not shipped
  (#1930(b)).
- **Nothing consumes the registry before W7.**

**CONFIDENCE:**
- **HIGH** on TD-VF-33…TD-VF-38. Each was re-read at the cited lines at `aac066168`.
- **HIGH** on TD-VF-39 and TD-VF-40, which were probed in `/tmp/claude/w5c/` with a real install, a
  real autocrlf checkout, and the merged `load()`.
- **MEDIUM** on TD-D53's exact text format. It is a presentation choice, pinned by T5.68 so that any
  change is deliberate.
- **MEDIUM** on TD-D50, until the architect answers Q1. It follows the binding ADR over Amendment E's
  wording, but it re-homes an approved obligation.

**BLAST RADIUS:**
- **This document:** the header block, the Date line, and Amendment F.
- **Downstream:** the 12 files in §F.4.
- **Consumers:** new installs no longer receive the sweep. Every install now receives the registry data,
  `resolved-packs.txt`, the `.gitattributes` lines, and the manifest rows.
- **Forward:** W7, through TD-D43 (i)–(iii) and the ship-list restoration.
- **Not touched:** the engine, the CLI, `posture.py`, the registry data, the agents, and W1–W4.

**Change classification: ADDITIVE.**
- The sweep rewrite, the ship-set removal and the installer step were already designed (§C.2.10,
  §C.2.11) or ruled (#1930).
- This amendment adds what those left open: TD-D51–D56, the TD-VF-37 fix, and the #1951 handling.
- It **clarifies** TD-D43's placement (TD-D50) without changing what TD-D43 requires.
- If the architect judges TD-D50 or TD-D55 **structural**, it goes to a human before the coder starts.

**Architect review is requested.** This amendment is not handed to the coder until the architect
approves. Iteration: Amendment F round 1 of 5. No temp-state file was written, because this dispatch was
constrained to editing this one file.

**Not done here:**
- No code, test, data or script was written into the repository. The probes ran in `/tmp/claude/w5c/`
  only.
- No issue was filed, no label was created, no comment was posted, and nothing was committed.
- No register entry was written.

---

## Amendment G (2026-10-03) — W6: the observation-only measurement slice (AD-13 runner, one judgment entry)

**Status:** **DRAFT. Amendment G round 1 of 5. Architect review is requested. Do not hand it to the
coder until the architect approves.** One human escalation (ESC-G1, §G.8) blocks the measurement
*campaign*. It does not block the code. ADR-1643 §5 row W6 is binding: *"AD-13 runner, **one** judgment
entry, **observation only** — records durations and outcomes, gates nothing. **Do not skip for speed.**"*
Where this amendment and §1.2's W6/W7 rows, or TD-D35's "W7 obligations" label, disagree, Amendment G
governs. Everything else stands.

**Numbering.** TD-VF-41…TD-VF-49, TD-D59…TD-D65, tests T6.01…T6.28, escalation ESC-G1, and
architect questions TD-G-O1…TD-G-O7. ESC-G1 is unrelated to the ADR's historical **ESC-G** (the
protection asymmetry, ADR §9.6); the `<n>` suffix keeps the two apart.

### G.1 Verification findings — TD-VF-41…TD-VF-49 (tree at `09f62a9c0`)

**TD-VF-41 — W1 already produces every per-invocation number W6 needs. W6 reads the W1 document and
does not re-derive anything.**
- `bootstrap/invoke_agent.sh` passes through `agent_invoke_cli.py` (`:105`). Exit 0 means a document was
  produced, whatever it says. Exit 1 is an operational failure with no document. Exit 2 is a usage
  error (`invoke_agent.sh:53-61`).
- The `invocation` block carries `duration_ms`, `timeout_seconds`, `timed_out`, `exit_code`, `model`,
  `model_source`, `cli_version`, `num_turns`, `usage`, `model_usage`, `total_cost_usd` and
  `envelope_unknown_fields` (`agent_invoke_cli.py:1416-1460`).
- `terminal_reason_missing` is a classifier `outcome_detail` (`:639`). The other details are `timeout`,
  `unparseable`, `envelope_shape_violation`, `crash`, `permission_denied`, `refused`, `schema_violation`
  and `usage_limit` (`:581-712`).
- `compute_input_digest` is public and pure (`:740-774`). The matched-files component comes from
  `_matched_files_digest` (`:722-737`), which is **private**. `binding_sha256` is hard-coded `None`
  (`:767`; TD §4.4: "W7 fills this").
- The flags W6 needs already exist (`:1212-1230`): `--dimension`, `--binding`, `--lens`, `--timeout`,
  `--step`, `--head-sha`, `--base-sha`, `--matched-file`, `--prompt-template-version`, `--not-applicable`
  and `--require-env-auth`. The primitive's timeout bounds are 30…1800 s (`:169-170`).

**TD-VF-42 — GAP (W3): the per-invocation audit record does not carry `envelope_unknown_fields`.**
- ADR §9.7 requires §5.2's record to *"add `envelope_unknown_fields` and `cli_version`"* (W3).
  `cli_version` is present (`agent_invoke_cli.py:1086`). `envelope_unknown_fields` is not in the event
  dict at `:1071-1094`, and TD §5.2 was never corrected to require it.
- W6 is not blocked, because it reads the field from the document (TD-VF-41). The gap is routed in
  §G.9. W6 does not fix it, because that would re-open W3's audit schema inside a measurement slice.

**TD-VF-43 — no real `claude --agent` invocation has ever been recorded here, and the
`agent-invocation` event stream is polluted by tests.**
- This clone holds **6,958** `agent-invocation` records under `audit/log/2026/{09,10}/`. **None** is
  tracked by git. All 6,958 match three test signatures:
  - 2,958 × `code-reviewer`/`ad-hoc`/`not_applicable`;
  - 2,000 × `no-such-agent-xyz`/`agent_unavailable`;
  - 2,000 × `code-reviewer`/`security`/`not_applicable`.
- **Zero** records have `duration_ms > 0` and a non-null `cli_version`.
- **Source:** `tests/automation/test_agent_invoke_wrapper.py` runs the real L3 with `cwd=REPO_ROOT`
  (`:35`, `:44-47`; e.g. `:84`), and L3 resolves its root from its own location. So every test run
  writes W3 records into the real `audit/log/`.
- **Consequences for W6:**
  - (a) ADR §3's "unknown — never run" still holds at `09f62a9c0`. W6 is still the only possible source
    of the number.
  - (b) No W6 aggregate may be computed over `agent-invocation` events. W6 writes and reads its own
    event names (TD-D63).
  - (c) W6's own tests must never write into the real tree (T6.22).
- The pollution is routed in §G.9.

**TD-VF-44 — `token_tracker.py` is not a durable record and cannot be W6's source.**
- It appends to `.claudetmp/oversight/token-usage.jsonl` (`token_tracker.py:42`). That path is gitignored
  and local to one clone, which is exactly VF-5's non-durable class.
- W3 calls it for awareness only (§5.1). W6 neither calls it nor reads it. Each launched W1 invocation
  still calls it once, unchanged.

**TD-VF-45 — the W5 engine provides everything W6 needs, in process.**
- `dr.load(root)` with no `packs` runs L31's resolved-packs check (TD-D43 (iv); `dimension_registry.py:1004`).
- `dr.resolve_for_diff(reg, changed)` is the only producer of applicability (`:1009-1045`). It raises
  PL1 `bad_changed_file` before matching.
- `Binding` carries `agent`, `posture`, `timeout_seconds`, `prompt_template` and `predicate`
  (`:458-470`). `ResolvedRegistry.digest` covers all of them (`:966-1001`).
- **HOS's resolved registry has two `code-review` bindings:**
  - `core:code-review/code` (`core.yaml`): agent `code-reviewer`, posture `review-read-only`, 300 s,
    `prompts/code-review.md`, include `\.py$ \.sh$ \.js$ \.ts$ \.jq$`, exclude tests and `.venv`;
  - `project:code-review/framework-validator` (`project.yaml`).
- `contract/resolved-packs.txt` is empty in HOS (TD-D27), so no pack binding exists.

**TD-VF-46 — `dimension_registry_cli.py plan --base` has the `core.quotePath` defect that TD-D51(c)
fixed only in the sweep.**
- `_git_changed_files` runs `git diff --name-only <base>...HEAD` without `-z` (`dimension_registry_cli.py:65-80`).
- A non-ASCII or control-character path is therefore C-quoted, and no predicate matches it. That is the
  confident "not applicable" which Amendment F's Q2(c) ruling forbids.
- W6 does not call `plan`, and it computes its own changed set with `-z` (TD-D60). The CLI defect is
  routed in §G.9.

**TD-VF-47 — AD-13's runner does not exist yet. One of its two named files is a protected surface.**
- Neither `scripts/automation/dimension_sweep_cli.py` nor `bootstrap/run_dimensions.sh` exists.
- `bootstrap/**` is in `protected_surfaces.txt`. `scripts/automation/**` is not.
- Nothing ships either file. ESC-E's binding constraint stands: the coder must not relocate
  `dimension_sweep_cli.py` to make it ship (ADR §9.6).

**TD-VF-48 — the nested-session and cron-cycle signals exist, and one precedent already uses an
environment signal only to refuse.**
- **Probed in this session (Claude Code 2.1.288):** a Bash-tool subprocess inherits `CLAUDECODE` (set,
  along with `CLAUDE_CODE_ENTRYPOINT` and others). No HOS script reads any of them today (repo-wide grep).
- `validate_self.sh:114-160` uses `HOS_CYCLE_ROLE` for one thing only: a veto that makes a run
  **stricter**, refusing `--allow-keychain-auth` inside a cron cycle. That rule is AD-16.7, pinned by
  `test_agent_invocation_migration.py:346`.
- **AD-16.7's principle:** an environment signal may refuse a run. It may never relax one.

**TD-VF-49 — PREDICTION, unprobed: the chosen reviewer will probably fail under its own posture.**
- `code-reviewer.md` instructs the agent to write a register entry to `.claudetmp/signoffs/…`
  (`:113`, `:135`) and loop temp-state to `.claudetmp/reviews/…` (`:103`).
- `review-read-only` denies `Write` and `Edit` (the `review-read-only.settings.json` deny list), and
  TD-D33 rule 5 forbids the prompt from overriding the agent definition.
- An attempted write that is denied shows up in `permission_denials`, and the classifier maps that to
  `invocation_failed`/`permission_denied` (`agent_invoke_cli.py:668`). A prose response in place of one
  JSON object maps to `schema_violation`.
- All eight lens agents share this shape. **No live run has tested the prediction. W6 is that test.**
  A systematic failure here would be a W7 blocker, and it is raised now as TD-G-O4 so that nobody first
  learns it from W8.

*Re-confirmed:* `scripts/oversight/lib/audit_log.write_event` is write-once with exclusive create
(`audit_log.py:126-157`). It does not fsync, so a record survives the process being killed but not a
power loss. `read_stream` yields every record in path order, and it raises on invalid JSON
(`:160-188`). Nothing in `bin/`, `bootstrap/` or `scripts/` commits `audit/log/` records
automatically; the repo-wide grep finds only the installer's `git add` hint. Records become auditable
when someone commits them (TD-D63).

### G.2 Scope

**Delivers:**
- `scripts/automation/dimension_sweep_cli.py`: AD-13's runner as **L2 only**, with exactly two
  subcommands. `measure` runs one observation of one binding against the current checkout. `report`
  aggregates the observations.
- Three public aliases in `agent_invoke_cli.py` (TD-D64).
- Tests T6.01…T6.28, all in the inner loop.
- The `SCRIPTS-INDEX.md` regeneration that a new `scripts/automation/*.py` requires
  (`tests/framework/test_scripts_index.py`).

**Does not deliver:**
- Any `bin/hos-cron` edit or stage, or any cron, systemd or workflow wiring (ESC-2 is unanswered).
- Any PR comment, `envelope.py` post, or other AD-14 storage.
- Any read by `decide_merge_authority()`, the bounce path, the overseer's verdict or a required check.
- `bootstrap/run_dimensions.sh` (L3). This is deferred to W7 (TD-D59).
- Any second binding or entry, a `--binding` flag, a sweep loop or a per-cycle budget.
- Execution of any deterministic `Binding.tool`.
- Any change to the registry data, the postures, the prompts, any agent file, W3's audit schema, or
  `dimension_registry_cli.py`.
- Any per-cycle budget number. W7 calibrates from W6's output (ADR §3), and W6 does not calibrate.

### G.3 Decisions — TD-D59…TD-D65

**TD-D59 — W6 is AD-13's runner, at AD-13's L2 name, with no L3 yet.**
- **Lands:** `scripts/automation/dimension_sweep_cli.py`, the name AD-13 binds, with the subcommands
  `measure` and `report` and no others. W7 adds the sweep subcommand to the same module.
- **Deferred to W7:** `bootstrap/run_dimensions.sh`.
  - **Reason:** L3 exists to give non-interactive callers a statically allowlistable argv (AD-1).
    W6 refuses every non-interactive and in-session caller (TD-D60), so in W6 an L3 has no legitimate
    consumer.
  - Shipping it now would publish exactly the allowlistable entry point that an agent session would
    use to nest a model session.
  - It would also be the third copy of the interpreter ladder (`invoke_agent.sh`,
    `run_post_change_sweep.sh`) and a protected-surface file, which is cost with no W6 benefit.
- **The human invokes L2 with the venv interpreter:**
  `scripts/oversight/.venv/bin/python scripts/automation/dimension_sweep_cli.py measure --base origin/main`.
  If PyYAML is missing, that surfaces as the loader's `yaml_unavailable` and is recorded (§G.6). It is
  never a traceback.
- **The binding is a module constant:** `MEASURED_BINDING = "core:code-review/code"`. There is no
  `--binding` flag. Widening W6 is therefore a code change under review, not a flag (T6.25).

**TD-D60 — who runs it, and when: a human, in their own terminal, by hand. Never cron, and never a model
session.**
- **Why this is the only invoker the constraints allow:**
  - ESC-2 is unanswered, so no `hos-cron` stage is possible.
  - Q4+Q6 rule out nested sessions, so the worker, the overseer and the human-proxy session are all
    excluded, because each is a `claude` session whose Bash tool would be the parent of the agent W6
    launches.
  - What remains is a human at a shell.
- **Refusals.** Both fire before any I/O, exit 2, write one stderr line, and write **no** record. They are
  one-direction refusals in the AD-16.7 sense (TD-VF-48):
  - `HOS_CYCLE_ROLE` is set and non-empty: *"dimension_sweep: refused: HOS_CYCLE_ROLE is set — W6 is
    never run from a cron cycle (ADR-1643 ESC-2)"*.
  - `CLAUDECODE` is set and non-empty: *"dimension_sweep: refused: running inside a Claude Code session
    — W6 must be run from a plain terminal (ADR-1643 Q4+Q6, no nested sessions)"*.
  - Unsetting a variable to evade a refusal is a deliberate act against a named rule, and the review of
    any committed caller would catch it. The refusals are a guard against accident, not a security
    boundary. **TD-G-O3.**
- **Auth follows AD-16.7 exactly.** `--require-env-auth` is passed by default. `--allow-keychain-auth`
  omits it, for a human using keychain auth. No environment signal relaxes it.
- **The checkout is the input.**
  - `head_sha` = `git rev-parse HEAD`.
  - `base_sha` = `git merge-base <base> HEAD`.
  - The changed set = `git diff -z --name-only <base>...HEAD`, read as NUL-separated. That is
    Amendment F's Q2(c) rule (TD-VF-46).
  - The size covariate = `git diff -z --numstat <base>...HEAD`, summed over the matched files. A binary
    file's `-` counts as 0.
  - The tracked tree must be clean (`git status --porcelain --untracked-files=no` is empty), so that
    the matched-file bytes the primitive hashes are HEAD's bytes. Untracked files, including
    `audit/log/` records, are allowed.
  - `<base>` must resolve via `git rev-parse --verify <base>^{commit}`. A value beginning with `-` is a
    usage error.
- **Concurrency is 1 by construction.** One `measure` process launches at most one invocation. Two
  concurrent `measure` processes in one clone are refused through a non-blocking `fcntl.flock` on
  `$(git rev-parse --git-path hos-w6-measure.lock)`. That location is per-clone, and it is never
  `.claudetmp/`.

**TD-D61 — W6 executes no deterministic binding. TD-D43 (i)–(iii) bind W7, unchanged.**
- **The only subprocesses `measure` may start:**
  - `git`;
  - `["bash", "<root>/bootstrap/invoke_agent.sh", …]` as an argv list with `shell=False`.
- It never executes, sources or passes on a `Binding.tool` (T6.27). Under TD-D50's rule ("whichever of
  W6 and W7 first executes a deterministic `Binding.tool`"), (i)–(iii) therefore pass to W7 verbatim.
- **The judgment-binding analogue binds W6, per the architect's round-1 forward obligation (§F.2):**
  - **(i′)** `measure` calls `dr.load(root)` in its own process, with `packs=None`, so the TD-D43 (iv)
    analogue holds and L31 runs. It takes the binding from that `ResolvedRegistry`. The agent,
    posture, `timeout_seconds`, `prompt_template` and predicate all come **only** from that `Binding`
    object, never from a literal, a flag or the environment. A missing or suppressed
    `MEASURED_BINDING` is the `binding_absent` record (§G.6). It never falls back.
  - **(ii′)** The agent is reached only through `bootstrap/invoke_agent.sh`, as an argv list
    (AD-16; T6.02).
  - **(iii′)** `--prompt-template-version` is TD-D34's `sha256:<hex>` over the template file's bytes as
    read once from disk, and the render uses those same bytes (TD-D62).
  - The record carries `registry_digest` (`ResolvedRegistry.digest`), so each observation names the
    exact registry it ran under.

**TD-D62 — W6 is the first renderer, so TD-D35 (a), (b), (c1) and (c2) bind W6. W7 inherits the render.**
TD-D35 assigned the render to W7 on the assumption that W7 rendered first. W6 invokes first. Without
these rules the primitive cannot be called at all, so the obligations move to the first component that
renders. Their content is unchanged; this follows TD-D50's precedent.
- **(a) How the template reaches the agent.** The rendered bytes are written to a private temp file
  (`tempfile.mkstemp`, mode 0600, deleted in `finally`) and passed as `--input-file`. That is the only
  instruction channel (c1).
- **The input file is the concatenation of three parts, in order:**
  1. the template file's bytes, verbatim;
  2. the change block, rendered from this exact text (LF, final newline), with one `- <path>` line per
     matched file in sorted order:
     ```
     
     ## Changes under review
     
     Base commit: <base_sha>
     Head commit: <head_sha>
     Inspect each selected file's change with: git diff <base_sha>...<head_sha> -- <path>
     
     Selected files:
     - <path>
     ```
  3. the payload block (b), a single module constant `PAYLOAD_INSTRUCTION` in `dimension_sweep_cli.py`.
     It is the only copy, never one per dimension. It states:
     - respond with exactly one JSON object and nothing else;
     - `verdict` ∈ {`approve`, `request_changes`};
     - `findings` is a list;
     - each finding has `severity` ∈ the list rendered from `agent_invoke_cli.SEVERITIES` (imported,
       never copied), `file`, `line`, `category` and `description`;
     - `summary` is a string;
     - the keys `applicability`, `outcome`, `input` and `invocation` must not appear.
     
     That is §4.3's contract, expressed as an instruction. `error` is deliberately not offered to the
     agent; it remains reachable only through L2.
- **(c2) Determinism.** The output must be byte-identical for identical (template bytes, base, head,
  matched set). It contains no timestamp, run id, absolute path, hostname or environment value
  (T6.05). A non-deterministic render would quietly break the reuse key, and T6.19 would catch it.
- **W7 inherits this render as its baseline.** Any change to parts 2 or 3 changes every
  `input_digest`, so it needs a TD amendment.

**TD-D63 — where the numbers land: write-once `audit/log/` records, then a commit and an issue
comment. Never a PR comment.**
- **Two event names, owned by W6.** `report` reads only these; it never reads `agent-invocation`
  (TD-VF-43).
  - `dimension-measurement-start` is written **before** launch, after every precondition has passed.
  - `dimension-measurement` is written once per `measure` run, whatever happened.
  - A start record with no matching result is an `abandoned` run, for example one killed by SIGKILL.
    A killed run therefore loses at most its own result and is still counted (AD-13's "lose at most
    one invocation").
- Both events go through `audit_log.write_event(event, root=<repo root>)`, loaded by path in the same
  way as `cycle_log.py:_load_audit_log`. There is no new writer.
- **Why `audit/log/` and not `.claudetmp/`:** VF-5. The records are write-once files in the committed
  audit tree, durable against the process dying the moment `write_event` returns. They are cross-clone
  auditable once committed.
- **Why not AD-14's PR comment under the overseer identity:**
  - AD-14's trust rule is that *a record authored by the overseer App identity is a record*. W8's
    verifying constructor will count exactly those records.
  - An observation-only W6 record posted under that identity would be indistinguishable to W8 from a
    gating result. W6 would be manufacturing the forgery surface AD-14 exists to close.
  - W6 is run by a human, so it would also need a human to mint an overseer token, which is the wrong
    identity for the actor.
  - AD-14's storage design, including comment volume, stays W7's.
- **The durable, auditable path** (the operator procedure in the module docstring):
  1. After the campaign, the human commits exactly the `audit/log/**/*-dimension-measurement*.json`
     files on a branch and opens a PR. These are data only and touch no protected surface.
  2. `report`'s JSON is posted to #1643 through `bootstrap/post_comment.sh --body-file` by whoever
     carries ESC-1. That is the existing entry point.
  3. The committed records are the audit trail. The comment is the pointer.
- **No prose in any record.** No prompt text, agent output, `summary`, finding text, envelope `result`
  or file content (§5.2's constraint 3; T6.22).
  - `--document-out <path>` optionally writes the full W1 document for the human's diagnosis. It is
    never read by `report`, never committed by the procedure, and is not a measurement.

**TD-D64 — W6's reuse key is the primitive's own `input_digest`, computed before launch and checked
after it.**
- **Computed before launch with W1's own functions:**
  - `compute_input_digest(...)`, which is public;
  - `matched_files_digest(...)`, the public alias TD-D64 adds;
  - `posture.load_posture(...).sha256`;
  - sha256 of `.claude/agents/<agent>.md`;
  - sha256 of the rendered input bytes;
  - plus `dimension = binding.entry`, `binding = binding.id`, the base and head SHAs, and
    `prompt_template_version`.
- **The aliases:** `agent_invoke_cli.py` gains three module-level alias lines:
  `matched_files_digest = _matched_files_digest`, `bounded_audit_str = _bounded_audit_str` and
  `bounded_audit_number = _bounded_audit_number`. They are additive, the behaviour is unchanged, and the
  private names stay.
  - **Why aliases and not copies:** a second implementation of the digest would drift, and W7's reuse
    depends on the runner's key equalling L2's. A second copy of the §5.2 bounding rule would drift the
    same way.
- **Reuse (AD-13).** If a `dimension-measurement` record with `runner_outcome ∈ {measured,
  not_applicable}` and the same `input_digest` already exists, `measure` writes a `reused` record that
  points to it and launches nothing.
  - A precondition-failed or no-document record never satisfies reuse.
  - An `invocation_failed` measured record **does** satisfy it. That is AD-13's "current iff digest
    matches", reproduced exactly. This tells the human that the same input was already observed.
  - Repeat measurements need a different head.
- **The check after launch.** The record carries `input_digest_match`, which is whether the
  precomputed digest equals the document's `input.input_digest`.
  - `false` is recorded and counted, never raised. It is W7's reuse key failing.
  - T6.19 pins `true` against the real L2.

**TD-D65 — `report` outputs raw numbers and makes no decision.**
- It aggregates the W6 events in `audit/log/` (optionally `--since <YYYY-MM-DD>`) into one JSON object
  (§G.5).
- **Percentiles** use nearest-rank (`ceil(p·n)`th smallest), over **launched** runs only. A run counts as
  launched iff the document's `invocation.exit_code` is non-null or `invocation.timed_out` is true. That
  excludes the four pre-flight details (TD-D24) and `not_applicable`.
- It computes no budget, no projection to twelve entries and no recommendation. ADR §3 forbids
  calibrating from estimates, and the projection is ESC-1's and the architect's.
- **One stderr line when the count is non-zero.** If `terminal_reason_missing_count > 0`, it prints
  *"dimension_sweep: terminal_reason_missing observed N/M launched — ADR-1643 §9.2: A4 reverts to
  tolerating absence; route to architect"*. It changes no code and no classifier. The consequence is an
  ADR amendment (§G.7, row 1).

### G.4 Files — the code slice is **4 files** (≤ 15; no split)

| # | Path | Change | Protected? |
|---|---|---|---|
| 1 | `scripts/automation/dimension_sweep_cli.py` | new — L2 `measure` + `report` (TD-D59…D65) | no |
| 2 | `scripts/automation/agent_invoke_cli.py` | three alias lines (TD-D64) | no |
| 3 | `tests/automation/test_dimension_sweep_cli.py` | new — T6.01…T6.28 | no |
| 4 | `SCRIPTS-INDEX.md` | regenerated by `scripts/framework/gen_scripts_index.sh` | no |

- **Untouched:** `bin/**`, `bootstrap/**`, `contract/**`, `.claude/agents/**`, `CLAUDE.md`, the ship-list,
  and `dimension_registry*.py`.
- No CLAUDE.md canonical-entry row is added. The tool is human-only and refuses agent sessions, so
  listing it where every agent session reads would only invite the refused call.
- The validation stamp hashes agent files only (§F.8), so no stamp joins the PR.
- With no protected surface touched, CODEOWNERS does not human-gate this PR. The human gate on spend is
  ESC-G1 and the human's own hand on the keyboard (TD-D60).

### G.5 CLI surface, record schema and exit codes

```
dimension_sweep_cli.py measure --base <ref> [--allow-keychain-auth] [--document-out <path>]
dimension_sweep_cli.py report  [--since <YYYY-MM-DD>]
```
Unknown flags and a missing subcommand are usage errors. `main(argv, *, repo_root=None)` is a test-only
root injection, following the idiom of the two sibling CLIs.

**`measure` exit codes.**

| Exit | Meaning | Record? | stdout |
|---|---|---|---|
| 0 | An observation was recorded: `measured` (whatever the document's outcome), `not_applicable` or `reused` | result (and start, if launched) | the result record, one JSON object |
| 1 | A run failure was recorded (§G.6), **or** a record could not be written | yes, if writable | the result record (also on a write failure) |
| 2 | Usage error or refusal (TD-D60) | **no** | empty |

**The result record** (literal example; a launched run whose prediction from TD-VF-49 came true):
```json
{
  "event": "dimension-measurement",
  "schema_version": 1,
  "timestamp": "2026-10-04T14:02:51Z",
  "run_id": "6f1c0d0e-3b7a-4c55-9a51-0b8f6a0f2e11",
  "mode": "observation",
  "runner_outcome": "measured",
  "error_code": null,
  "error_detail": null,
  "binding": "core:code-review/code",
  "entry": "code-review",
  "agent": "code-reviewer",
  "posture": "review-read-only",
  "registry_digest": "3d9e…",
  "prompt_template_version": "sha256:8a41…",
  "base_sha": "09f62a9c0…",
  "head_sha": "4be7d1a2…",
  "changed_files_count": 9,
  "matched_files_count": 4,
  "matched_lines_changed": 312,
  "input_bytes": 1984,
  "input_digest": "e8b0…",
  "input_digest_match": true,
  "reused_from": null,
  "primitive_exit_code": 0,
  "launched": true,
  "outcome": "invocation_failed",
  "outcome_detail": "permission_denied",
  "verdict": "error",
  "terminal_reason_missing": false,
  "findings_count": 0,
  "blocking_findings_count": 0,
  "duration_ms": 141230,
  "runner_wall_ms": 143911,
  "timeout_seconds": 300,
  "timed_out": false,
  "model": "opus",
  "cli_version": "2.1.288",
  "num_turns": 11,
  "total_cost_usd": 0.4120,
  "usage": {"input_tokens": 41210, "cache_creation_input_tokens": 9120,
            "cache_read_input_tokens": 120400, "output_tokens": 3311},
  "envelope_unknown_fields": [],
  "primitive_audit_record": "2026/10/2026-10-04T140051Z-agent-invocation-1a2b3c4d5e6f.json",
  "auth_mode": "require-env-auth"
}
```
- **`runner_outcome`** ∈ {`measured`, `reused`, `not_applicable`, `registry_error`, `binding_absent`,
  `git_error`, `dirty_tree`, `lock_held`, `primitive_no_document`, `primitive_bad_output`,
  `runner_timeout`, `interrupted`}.
- On a non-`measured` outcome, the document-derived fields are `null`. `error_code` carries the
  registry, git or primitive code, and `error_detail` is ≤ 500 chars.
- Every envelope-derived string and number goes through `bounded_audit_str`/`bounded_audit_number`
  (TD-D64's aliases): strings are capped at 500 chars, and numbers are int-or-float, never bool. The
  same rule applies to each `envelope_unknown_fields` element, and the list is capped at 50 elements.
  `usage` keeps only the four keys shown, each bounded as a number.
- `timestamp` drives the shard path (`_resolve_ts`). `run_id` is `uuid4`, and it is the only
  non-deterministic field.
- `role` is omitted: W6 has no role (TD-D60).
- **The start record** is `{"event": "dimension-measurement-start", "schema_version": 1, "timestamp",
  "run_id", "binding", "base_sha", "head_sha", "input_digest", "auth_mode"}`.

**`report` output** (exit 0; exit 1 only when `read_stream` raises on a malformed record, with one
stderr line naming the file):
```json
{
  "schema": "hos.dimension-measurement-report", "schema_version": 1,
  "binding": "core:code-review/code", "since": null,
  "runs": 12, "abandoned": 0,
  "by_runner_outcome": {"measured": 10, "not_applicable": 1, "reused": 1},
  "launched": 10,
  "by_outcome_detail": {"null": 3, "permission_denied": 5, "schema_violation": 2},
  "terminal_reason_missing_count": 0,
  "usage_limit_count": 0,
  "timed_out_count": 0,
  "input_digest_mismatch_count": 0,
  "duration_ms": {"n": 10, "min": 61200, "p50": 128400, "p90": 241000, "max": 262100},
  "duration_ms_completed_only": {"n": 3, "min": 61200, "p50": 98000, "p90": 131500, "max": 131500},
  "total_cost_usd": {"n": 10, "min": 0.11, "p50": 0.29, "p90": 0.52, "max": 0.61, "sum": 3.47},
  "num_turns": {"n": 10, "min": 4, "p50": 9, "p90": 14, "max": 16},
  "matched_lines_changed": {"n": 10, "min": 12, "p50": 140, "p90": 610, "max": 1220},
  "envelope_unknown_fields": [],
  "cli_versions": ["2.1.288"]
}
```
- Each stats object is `{"n": 0}` and nothing else when it has no data.
- **`abandoned`** counts start records with no result record carrying the same `run_id`.

### G.6 Fail-closed behaviour of the runner — observation-only still records every failure

The rule is that **every failure after argument validation produces a result record**. Silence is never
an outcome.

| Failure | `runner_outcome` / `error_code` | Exit | Launch? |
|---|---|---|---|
| Registry load fails (`RegistryError`, including `yaml_unavailable` and L31 drift) | `registry_error` / the loader's `code` | 1 | no |
| `MEASURED_BINDING` absent or suppressed | `binding_absent` | 1 | no |
| Git fails, the base is unresolvable, or PL1 `bad_changed_file` | `git_error` / `git_failed` or `bad_changed_file` | 1 | no |
| The tracked tree is dirty | `dirty_tree` | 1 | no |
| The lock is held | `lock_held` | 1 | no |
| The predicate selects nothing | `not_applicable`: the primitive is called with `--not-applicable "<PlanItem.reason>"` and no `--input-file`, so W1/W3 write their own record | 0 | no model |
| The primitive exits 1 or 2 (no document) | `primitive_no_document` / `exit_<n>`, with `error_detail` = the bounded stderr tail | 1 | maybe |
| The primitive exits 0 but stdout is not exactly one JSON object with `schema` = W1's | `primitive_bad_output` | 1 | yes |
| The primitive exceeds `timeout_seconds + grace + 60` s | `runner_timeout`; the wrapper's process group is killed (`start_new_session=True`, `os.killpg`) | 1 | yes |
| `invocation_failed` in any form (timeout, `usage_limit`, `permission_denied`, `terminal_reason_missing`, preflight) | `measured`, with the detail recorded | **0** | per the document |
| SIGINT, or another exception after the start record | `interrupted` is written best effort, then re-raised | 130 / 1 | yes |
| SIGKILL, or a power loss | none possible; the start record survives, and `report` counts it as `abandoned` | — | yes |
| `write_event` raises | the record still goes to stdout, plus one stderr line *"dimension_sweep: record not written: …"* | 1 | — |

- The primitive's stderr passes through to the runner's stderr unmodified (#1523), including W3's
  `usage limit reached` line.
- The runner never retries. It never relaunches after a failure, and it never maps `invocation_failed`
  to anything other than `measured`, because the failure is the observation.

### G.7 Discharge of forward obligations

| Obligation | Source | How W6 discharges it |
|---|---|---|
| Report the "count of `terminal_reason_missing` observed", and state the consequence if any are seen | ADR §9.2 residual (`ADR:1120-1123`), §9.7 row (`:1308`) | `report.terminal_reason_missing_count`, with `launched` as its denominator (TD-D65; T6.08). A zero means zero over *n* launched runs, nothing more. **Consequence if > 0** (ADR §9.2, verbatim): A4 reverts to tolerating absence, and the rename risk goes back on the record, unmitigated. That needs an **architect ADR amendment** plus a W1 classifier change, routed through `technical-design`. W6 automates neither, and it signals the case with one stderr line. |
| TD-D43 (i)–(iii) bind "whichever of W6 and W7 first executes a deterministic `Binding.tool`" | TD-D50 (§F.2), §F.8 Q1 | **W6 executes none** (TD-D61; pinned by T6.27). (i)–(iii) bind **W7**, verbatim. |
| The judgment-binding analogue of (i) and (ii), plus (iii) as TD-D34's hash | §F.2 architect round 1 (`TD:5156-5160` before this amendment) | (i′) the in-process `dr.load` with `packs=None`, with every agent, posture, prompt, timeout and predicate taken from the `Binding` (T6.03); (ii′) an argv list to `bootstrap/invoke_agent.sh` (T6.02); (iii′) `prompt_template_version` = TD-D34 (T6.04). TD-D61. |
| Q4 "un-slow": un-mark one consolidated real-install `load(target)`-green case | §F.8 Q4 (a forward obligation on **W7's** TD) | **N/A to W6, and it stays with W7 unchanged.** The obligation is triggered when W7 makes L31 consumer-load-bearing and restores the sweep to the ship-list. W6 ships nothing and loads only HOS's own registry. W6 still honours the obligation's principle: **none of its 28 tests is `slow` or `integration`**, and its end-to-end agreement test against the real L2 (T6.19) runs on every PR. |
| AD-13: runs as a script, never in a model session (Q4+Q6) | ADR AD-13, `:612-614` | It is a plain process started by a human (TD-D60). It refuses when `CLAUDECODE` or `HOS_CYCLE_ROLE` is set (T6.16), and no `bin/hos-cron` reference exists (T6.26). |
| AD-13: keyed by `input_digest` | `:615-623` | TD-D64: computed before launch with W1's own functions, reused on a match (T6.18), and checked after launch (T6.19). |
| AD-13: each record written durably as it completes | `:616-618` | TD-D63: a start record and a result record, each write-once, the start written before launch (T6.20). |
| AD-13: concurrency 1 | `:630-632` | One invocation per process, plus the per-clone lock (TD-D60; T6.28). |
| AD-16: every agent invocation goes through `invoke_agent.sh` | ADR AD-16; CLAUDE.md | TD-D61 (T6.02, T6.27). The existing T4.1 also stays green: there is no raw `claude` in the new file. |
| `--require-env-auth` is mandatory for "the sweep runner" | `invoke_agent.sh:44-50`; ADR §9.3; AD-16.7 | It is strict by default, opting out only through `--allow-keychain-auth`, and no environment signal relaxes it (T6.17). |
| `INVOKE_AGENT_PYTHON` must not appear in "the sweep runner (W6)" | ADR §10.3 condition 3 (`:1536`) | The new module never names it. The existing repo-wide grep test (`test_agent_invoke_cli.py:1381-1420`) already fails if it does. |
| TD-D35 (a), (b), (c1), (c2) | §D.2 (labelled W7) | They move to W6 as the first renderer (TD-D62; T6.05). |
| ESC-H "revisit after W6": a cost bound set *from* a measured distribution | ADR §9.6 | `report.total_cost_usd` is the input to that revisit. W6 adopts no `--max-budget-usd`. |
| ADR §3: calibrate from this slice's output, never from estimates | ADR §3, `:738-742` | W6 reports raw distributions and calibrates nothing (TD-D65). |

### G.8 Escalations — ESC-G1 (human)

**ESC-G1 — authorise the W6 measurement campaign: who runs it, on what, and how much quota it spends.**
(Cost model and operational obligation, at the product-boundary checkpoint.)

By construction (TD-D60), W6 can be run **only by a human, by hand, from a plain terminal**. No agent
session can run it, and no cron cycle can. That is a new, recurring manual obligation, and each run
spends one real `code-reviewer` session (≤ 300 s, `total_cost_usd` per run unknown; that is the thing
being measured).

**The decisions that are yours:**
- (a) Do you accept running it yourself, or do you prefer to wait until ESC-2 is answered and let W7
  measure from a cron stage? Waiting means ESC-1 has no number until W7.
- (b) The sample: how many launched runs, and which heads.
- (c) Keychain auth (`--allow-keychain-auth`) or env-token auth.

**Recommendation:**
- (a) Yes, run it yourself. W7 is blocked on ESC-2, and ESC-1 needs the number first (ADR §5).
- (b) At least 10 launched runs on **open or recent code-touching PR heads that contain W6**. Spread
  them across diff sizes, including at least one with more than 500 matched changed lines, and run them
  sequentially. That is about 10 sessions, and at most 50 minutes of your wall-clock at the 300 s cap.
- (c) Whichever you use day to day. `auth_mode` is recorded, so the two can be separated afterwards.

The procedure is short. For each head:

```
git checkout --detach <head>
…/.venv/bin/python scripts/automation/dimension_sweep_cli.py measure --base origin/main
```

Then run `report`, commit the measurement records, and post the report (TD-D63).

**Unaffected and still yours:** ESC-1…ESC-4. W6 answers none of them; it supplies ESC-1's input.

### G.9 Open questions — to `architect` (TD-G-O1 blocks the handoff; the rest are confirmations or routings)

- **TD-G-O1 (confirm, BLOCKING): TD-D62 and TD-D59.**
  - TD-D62 moves TD-D35 (a), (b), (c1) and (c2) from W7 to W6, with the literal change block and payload
    instruction that W7 inherits.
  - TD-D59 lands AD-13 as L2 only and defers `bootstrap/run_dimensions.sh` to W7. AD-13 binds both
    names, so if you read the AD-13 bullet as requiring L3 in the first slice that lands the runner, say
    so. L3 then becomes file 5, a protected-surface file that needs a CODEOWNERS gate.
- **TD-G-O2 (confirm): the measured binding is `core:code-review/code`.**
  - **Representativeness:** it is the broadest judgment predicate (`.py .sh .js .ts .jq`, non-test), so
    it applies to almost every code PR and yields the most samples per head. Its agent is the
    general-purpose lens, so its duration is a reasonable stand-in for the eight-lens median. If
    anything it errs long, and long is the safe direction for a budget.
  - **Measurement cost:** one session per head, and nothing that W8 would not spend anyway.
  - **Rejected:**
    - `security`: a similar predicate, but a narrower lens, and it would under-estimate.
    - `infra`, `ui`, `a11y`, `privacy`: too rarely applicable to sample.
    - `project:code-review/framework-validator`: HOS-only, so it does not represent a consumer.
- **TD-G-O3 (confirm): TD-D60's two environment refusals.** They are one-direction refusals in the
  AD-16.7 sense. `CLAUDECODE` is a vendor variable that the CLI could rename, and if that happens the
  refusal quietly stops firing. T6.16 pins the name, not the vendor's behaviour. Is that acceptable for
  a guard against accident?
- **TD-G-O4 (routing; W7 blocker if confirmed): TD-VF-49.**
  - All eight lens agents' CORE text instructs `Write` to `.claudetmp/`. `review-read-only` denies it,
    and TD-D33 forbids the prompt from overriding the agent. That predicts systematic `permission_denied`
    or `schema_violation`.
  - W6 measures it and does not fix it. If W6 confirms it, W7 cannot proceed until the architect rules
    on the agent/posture contract (an "invoked-as-dimension" mode, a posture change, or an agent-text
    change, each with its own protected-surface gate).
  - Separately: are durations from failed runs admissible as ESC-1's input? `report` splits the
    `completed`-only distribution out for that reason.
- **TD-G-O5 (routing, W3 follow-up): TD-VF-42.** `envelope_unknown_fields` is missing from the §5.2
  audit record that ADR §9.7 required. This is a small additive W3 fix, with a §5.2 text correction and
  one test. It is not folded into W6.
- **TD-G-O6 (routing, W1 test hygiene): TD-VF-43.** The wrapper tests write W3 records into the real
  `audit/log/` (6,958 here), and that pollutes the event stream W7 and any future reader would
  aggregate. The fix is to have those tests point L3 at a temp copy or strip the audit write, which is
  W1's call. W6 is immune by event name.
- **TD-G-O7 (routing, W5 CLI): TD-VF-46.** `dimension_registry_cli.py plan --base` has no `-z`. That is
  the same `core.quotePath` false-not-applicable defect that §F.8 Q2(c) fixed in the sweep.

I file nothing. The orchestrating session files issues for TD-G-O4…O7 if the architect agrees.

### G.10 Tests — T6.01…T6.28 (all inner-loop; **none** `slow` or `integration`)

Every test drives `main(argv, repo_root=tmp_root)` in process, against a `tmp_path` git repository. That
repository holds a copied `contract/dimensions/` tree, `.claude/agents/code-reviewer.md` and the postures,
so **no test writes into the real `audit/log/`** (TD-VF-43). The primitive is reached through one seam,
`_run_primitive(argv, *, timeout_s) -> (rc, stdout_bytes, stderr_bytes)`. Tests monkeypatch it to return
canned W1 documents, built with `agent_invoke_cli.build_document`, unless the test says otherwise.

| Test | Asserts |
|---|---|
| **T6.01** | Happy path: a `completed` document produces exactly one start record and one result record under `tmp_root/audit/log/`, with every §G.5 field present. Exit 0. stdout is one JSON object equal to the result record. |
| **T6.02** | The argv is a `list`, starting `["bash", "<tmp_root>/bootstrap/invoke_agent.sh"]`, and it carries `--agent`, `--posture`, `--input-file`, `--timeout`, `--dimension code-review`, `--binding core:code-review/code`, `--lens code-review`, one `--matched-file` per match, `--base-sha`, `--head-sha`, `--prompt-template-version` and `--require-env-auth`. `shell=False`. |
| **T6.03** | (i′) The registry is the only source. With the tmp `core.yaml` edited to `agent: security-reviewer`, `posture: review-read-only-gh-read` and `timeout_seconds: 120`, the argv carries all three. A PROJECT suppression of the binding gives `binding_absent`, exit 1, and no seam call. |
| **T6.04** | `--prompt-template-version` equals `"sha256:" + sha256(template bytes)`, and the input file begins with exactly those bytes. |
| **T6.05** | (c2) Two renders of the same inputs are byte-identical. The input contains no `run_id`, no `tmp_root` absolute path and no ISO timestamp. The payload block appears once, and it lists exactly `agent_invoke_cli.SEVERITIES`. |
| **T6.06** | Not applicable: with only `docs/x.md` changed, the seam receives `--not-applicable "<reason>"` and no `--input-file`, and the record is `not_applicable`. Exit 0. |
| **T6.07** | An `invocation_failed`/`timeout` document is recorded as `measured`, with `timed_out: true`. Exit 0. |
| **T6.08** | A `terminal_reason_missing` document gives `terminal_reason_missing: true`. `report` then shows a count of 1 with `launched` 1, and prints the TD-D65 stderr line verbatim. A zero count prints no line. |
| **T6.09** | A `usage_limit` document is recorded, `report.usage_limit_count` is 1, and the seam's stderr appears unmodified in the runner's stderr. |
| **T6.10** | The seam returns rc 1 with an empty stdout. The record is `primitive_no_document`, `error_code` `exit_1`, and the stderr tail is bounded to ≤ 500. Exit 1. |
| **T6.11** | The seam returns rc 0 with two JSON objects or non-JSON. The record is `primitive_bad_output`. Exit 1. |
| **T6.12** | Runner timeout: the real seam runs a stub script that sleeps, with the timeout lowered through a test-only module constant. The record is `runner_timeout`, and the process group is gone afterwards. Wall time < 5 s. |
| **T6.13** | A corrupt tmp `core.yaml` gives `registry_error` with the loader's `code`. Exit 1, no seam call. |
| **T6.14** | An unknown `--base` gives `git_error`. A changed path `src/é.py` matches the predicate, because `-z` is used, and is passed through verbatim. |
| **T6.15** | A modified tracked file gives `dirty_tree`, exit 1. An untracked `audit/log` file is allowed. |
| **T6.16** | With `HOS_CYCLE_ROLE=worker`, and separately with `CLAUDECODE=1`, the run exits 2, prints one stderr line naming the variable, makes no seam call and no git call, and writes zero records. |
| **T6.17** | By default the argv contains `--require-env-auth` exactly once. With `--allow-keychain-auth` it does not, and `auth_mode` is `keychain`. No environment variable changes either. |
| **T6.18** | Reuse: a prior `measured` record with the same precomputed digest gives `reused` and `reused_from` set, and the seam is never called. A prior `dirty_tree` record does not satisfy reuse. |
| **T6.19** | Digest agreement against the **real** L2: the seam calls `agent_invoke_cli.main(argv_tail, repo_root=tmp_root)` in process, with `run_capped` spied (as T1.x does) to return a canned envelope. The test satisfies P1…P8 the way W1's own in-process tests do, including a dummy `CLAUDE_CODE_OAUTH_TOKEN` for P7, and captures stdout. Then `input_digest_match` is `true`, and the runner's precomputed digest equals the document's `input.input_digest`. |
| **T6.20** | Durability: inside the seam, the start record already exists on disk. If the seam raises `KeyboardInterrupt`, an `interrupted` result record is written and the exception propagates. With the start record planted alone, `report.abandoned` is 1. |
| **T6.21** | When `write_event` raises, the record is still on stdout, one stderr line is printed, and the exit is 1. |
| **T6.22** | No prose: with sentinel strings in the document's `summary`, its finding descriptions, `envelope.result` and the template body, none appears in the bytes of any record. Also, after the whole module runs, the **real** repository's `audit/log/` file count is unchanged. |
| **T6.23** | `report` over fixture records gives exact JSON: counts, nearest-rank p50/p90, `abandoned`, the reuse count, `input_digest_mismatch_count`, and the union of `envelope_unknown_fields`. 500 interleaved `agent-invocation` fixture records change nothing. |
| **T6.24** | `report` on an empty or absent `audit/log` gives `runs: 0` and stats `{"n": 0}`, exit 0. A malformed record gives exit 1 with one stderr line naming the file. |
| **T6.25** | Single entry: the parser rejects `--binding`. `MEASURED_BINDING == "core:code-review/code"`. The subcommands are exactly `{measure, report}`. |
| **T6.26** | Observation only (static): the module imports nothing from `merge_authority`, `merge_config`, `pr_readiness`, `envelope`, `correlation` or `overseer_state`. It does not name `post_comment.sh`, `pr_review.sh`, `submit_pr.sh` or `hos-cron`. `bin/hos-cron` contains neither `dimension_sweep` nor `run_dimensions`. |
| **T6.27** | No deterministic execution: with a subprocess spy over the whole `measure` run, every argv is `git …` or `["bash", "<root>/bootstrap/invoke_agent.sh", …]`. No argv contains any `ResolvedRegistry.tools` entry. |
| **T6.28** | Lock: while the lock is held, the record is `lock_held`, exit 1, with no seam call. Each of TD-D64's three public names `is` its private original. |

### G.11 Startup-gap analysis and affected sign-offs

*Should this have been settled in the initial technical design, before code was written against it?*

**Yes, a `startup-artifact-gap` for the orchestrator to annotate. I file nothing.**
- **TD-VF-42:** ADR §9.7's row for §5.2 was never applied, so W3 was built and approved against a §5.2
  that omitted `envelope_unknown_fields`.
- **TD-VF-43:** §9.1's wrapper-test plan never said the tests must not write into the real audit tree.
- **TD-VF-46:** §7.10's `plan --base` predates TD-D51(c). This is the same class that §F.8 already
  recorded for the sweep.
- **TD-VF-49:** whether an agent's own write instructions survive a read-only posture should have been
  asked when AD-7's postures (§3.6) and TD-D33's prompt rule were set. It is still unprobed.

**No:**
- **TD-D62's re-homing** is the same class as TD-D50, an obligation attached to a slice on an ordering
  assumption. W6 had no design, so nothing was built against it.

**Affected sign-offs:**
- **W1 stands.** TD-D64 adds three alias lines and changes no behaviour, so a `code-reviewer` pass on
  those lines is enough. TD-VF-43's test-hygiene fix, if it is done, is new work under its own review. It does
  not invalidate W1's behavioural sign-offs.
- **W3 stands** for what it was reviewed against. TD-G-O5's additive field is new work. The prior
  approvals are not orphaned, because no decision reads the audit record (ADR-1604 AD-4).
- **W5a, W5b, the hardening slice and W5c stand.** W6 consumes `load` and `resolve_for_diff` unchanged.
  TD-VF-46's CLI fix, if it is done, re-opens only `plan --base` and its tests.
- **W6 and W7 are unbuilt.** W7 inherits TD-D43 (i)–(iii), the Q4 un-slow obligation, the TD-D62
  render baseline, the L3 file, and AD-14.

---

## Human Review Required — Amendment G (2026-10-03, W6 measurement slice)

**RISK: MEDIUM.**
- W6 launches **real model sessions** that spend subscription quota, and it writes committed-tree audit
  records.
- It gates nothing.
- It cannot run unattended: it refuses cron and in-session callers, and no cron path names it.
- It touches no protected surface, no merge-decision code and no agent file.
- **The worst realistic failure is a wrong number:**
  - (a) a sample that does not represent PR traffic;
  - (b) a render that differs from W7's, so W7 is calibrated on a different input shape (TD-D62 binds
    W7 to W6's render, which mitigates this);
  - (c) TD-VF-49's predicted failures being read as cost data.

  All three surface in `report`, not in a merge.

**CONFIDENCE:**
- **HIGH** on TD-VF-41…TD-VF-48. Each was re-read at the cited lines at `09f62a9c0`. TD-VF-43's counts
  and signatures were computed from the records in this clone, and TD-VF-48's environment variable was
  probed live.
- **MEDIUM** on TD-VF-49. It is a prediction from the agent text and the posture, and it is unprobed by
  design, because W6 is the probe.
- **MEDIUM-HIGH** on TD-D59, TD-D62 and TD-D64, which need the architect's confirmation (TD-G-O1).
- **LOW**, deliberately, on any implication for ESC-1. W6 produces none until it runs.

**BLAST RADIUS:**
- **This document:** the header banner, the Date line and Amendment G.
- **Downstream:** the 4 files in §G.4.
- **Runtime:** only when a human runs it.
- **Forward:** W7 (TD-D43 (i)–(iii), the Q4 un-slow obligation, the render baseline, L3, AD-14). Also
  W1, W3 and W5's follow-ups (TD-G-O5…O7).
- **Not touched:** `bin/hos-cron`, the overseer, merge authority, the registry data, postures, agents, and
  W1/W3 behaviour.

**Change classification: ADDITIVE** (a slice the ADR orders but this TD never designed).
- TD-D61 and TD-D62 **clarify** where existing obligations bind, and change none of their content.
- **TD-D59 (deferring L3) is the one point the architect could judge STRUCTURAL**, because it departs
  from AD-13's two-file shape for the first slice. If so ruled, it goes to a human before the coder
  starts.
- ESC-G1 is held for the human regardless.

**Architect review is requested.** Iteration: Amendment G, round 1 of 5. Temp-state:
`.claudetmp/design/technical-design-W6-<timestamp>.md`.

**Not done here:** no code, test, data or script was written. No issue was filed, no label was created,
no comment was posted, nothing was committed, and no register entry was written. The only probes were
read-only: `env` names in this session, `claude --version`, and a count of the existing audit records.
