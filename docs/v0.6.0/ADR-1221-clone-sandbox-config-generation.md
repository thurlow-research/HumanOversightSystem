# ADR-1221 — Clone sandbox config generation: a pure function of (template, values), with the union performed once in the tracked template and never at runtime

**Status:** **ACCEPTED — GO, with eight binding refinements and one required spec correction.** `technical-design` is cleared to proceed immediately. Nothing here is held for a human before design or build. Two consequences are routed as non-blocking notes (§4); one is an operator-facing precondition on the *first* `--force` run, not a design gate.
**Date:** 2026-08-04
**Author:** architect
**Issue:** #1221 · **Milestone:** v0.6.0 · **Risk tier: MEDIUM** (confirmed — §5)
**Inputs:** `docs/v0.6.0/SPEC-1221-clone-sandbox-config-generation.md` (pm-agent, 2026-08-04) read in full; `contract/sandbox-policy.template.json`; `docs/SANDBOX-POLICY.md`; `scripts/framework/gen_codeowners.sh`; `scripts/framework/check_validation_current.sh`; `bootstrap/validate_setup.sh`; `scripts/framework/protected_surfaces.txt`; the four call sites of `validate_setup.sh` (`bin/hos-human`, `bin/hos-worker`, `bin/hos-overseer`, `bin/hos-cron`); `scripts/framework/run_tests_inner_loop.sh`; `tests/framework/`; `.gitignore`.
**Consumers:** `technical-design` (next), then `coder` → the standard review chain. This PR is HUMAN_REQUIRED by construction (`scripts/framework/**`, `contract/**`, `bootstrap/**` are all protected surfaces).

---

## 0. Verification findings — I read the code the spec reasons about

**VF-1 — `scripts/framework/**` and `contract/**` are both in `protected_surfaces.txt` (lines 28 and 17).** §2's claim is confirmed. `bootstrap/**` (line 27) is too, so the FR-9 hook is also protected. No new protected-surface entry is needed.

**VF-2 — `validate_setup.sh` is not a Human-clone script. It is shared by all three roles and by cron.** Call sites: `bin/hos-human:25`, `bin/hos-worker:13`, `bin/hos-overseer:10`, `bin/hos-cron:471`, plus `bootstrap/hos_setup_partner.sh:192-198` which runs it against Worker/ and Overseer/. It accepts only `--quiet` and `--repo`; **it has no notion of role.** FR-9 as written therefore lands a role-requiring check inside a role-blind script — a direct collision with FR-2. Resolved in AD-6.

**VF-3 — the cron call site would silently swallow FR-9 and turn "non-blocking" into "cycle aborted".** `bin/hos-cron:471` is `if ! bash …validate_setup.sh --repo … --quiet 2>/dev/null; then … exit 0`. Two consequences: stderr is discarded (so "loud on stderr" is *invisible* in the autonomous path), and any non-zero exit kills the cycle at preflight. An FR-9 hook that is merely "usually non-blocking" fails closed in the worst place. AD-6 makes it structurally impossible to reach that path in this PR.

**VF-4 — the §5 union cannot be a runtime behavior, and if implemented as one the currency check silently always passes.** If generation reads the live file to union its denies, then generate(live=L) → O ⊇ L, and `--check` regenerates from the *new* live O → O' ⊇ O, so any hand-added live deny is absorbed into the "expected" output and can never be reported as divergence. FR-8 would be a check that can only pass. FR-14 already says the reconciled set becomes the tracked template; §5's prose ("emit all three spellings", "the generator must carry an inline comment") reads as generator behavior and will be implemented that way unless bound otherwise. AD-1 binds it.

**VF-5 — FR-12's enumeration drops a deny the template already has.** `contract/sandbox-policy.template.json:122-125` denies four force-push spellings, the fourth being **`Bash(git push* +*)`** (the `+refspec` form). FR-12's "union of all five forms" does not include it. A literal implementation removes a tracked deny in the PR whose organizing principle is *denies are only ever unioned, never subtracted*. Required correction, AD-8.

**VF-6 — two of the seven placeholders have no derivation anywhere in this repo.** `grep` for `HANDOFF_DIR`, `HOS_HANDOFF`, `CLAUDE_PROJECT_STATE`, `claude/projects` across `bin/`, `bootstrap/`, `scripts/`, `docs/` returns **only** the `docs/SANDBOX-POLICY.md` §5 glossary row and the spec itself. There is no config key, no script, no convention. FR-4 says "the role selects the values" but there is no source of truth for `__HANDOFF_DIR__` or `__CLAUDE_PROJECT_STATE__`. AD-4 and AD-5.

**VF-7 — `--check` has no way to reproduce the substitution used at generate time.** If values come from flags, `--check` invoked from `validate_setup.sh` (which knows only `--repo`) cannot reproduce them, and will report permanent spurious divergence. This is the piece the spec is missing and it is what makes FR-8/FR-9 implementable or not. AD-5.

**VF-8 — `.gitignore:40` covers `.claude/settings.local.json` and nothing adjacent.** Any new sidecar this PR introduces under `.claude/` is untracked-by-nobody: it will appear in `git status` and can be committed by accident. AD-5 requires the ignore entry in the same PR.

**VF-9 — Python is already first-class in `scripts/framework/`; `jq` is not a guaranteed dependency anywhere.** `scripts/framework/` holds `require_human_approval.py`, `require_overseer_approval.py`, `require_tier_ceiling.py`, each with a pytest test that loads it via `importlib` (`tests/framework/test_require_human_approval.py:12-18`). `run_tests_inner_loop.sh` runs **pytest only** — a bash script is testable there only through `subprocess`. Meanwhile exactly one script in the tree checks for `jq` and it dies if absent (`scripts/oversight/audit_conditional_proceed.sh:72`); `python3` is a hard prerequisite installed by `hos_bootstrap.sh`. AD-2.

**VF-10 — the atomic-write idiom already exists in repo code:** `scripts/automation/lib/overseer_state.py:57` (`os.replace(tmp, path)`). AD-3 adopts it rather than inventing one.

**VF-11 — `--force-with-lease` appears nowhere in this repo's scripts or docs** (only in the spec sentence that accepts denying it). FR-12's accepted consequence costs nothing operationally. Confirmed as written.

---

## 1. The organizing principle I bind

> **The generator is a pure function of (template, values). It never reads the live file in order to produce output.**
> `--check` is the *only* mode that reads the live file, and only to compare against a freshly computed generation. Every reconciliation decision — the deny union of §5, FR-11's three `bin/**` spellings, FR-12's force-push forms — is a **one-time, human-reviewed edit to the tracked template (FR-14)**, not runtime behavior.

Everything below follows from this. It is also the single thing that, got wrong, produces a build that looks complete, passes its own tests, and ships a currency check that can never fail (VF-4).

---

## 2. Decisions

### AD-1 — §5's union is a **reconciliation instruction to this PR's author**, not generator behavior. (BINDING.)

The generator MUST NOT read `.claude/settings.local.json` in generate mode. The FR-11/FR-12 spellings, and every live-only deny, land in `contract/sandbox-policy.template.json` as a tracked edit (FR-14) reviewed in this PR's diff. Determinism (AC5) then falls out for free — output depends only on committed inputs and explicit values.

Corollary I bind because it is where this gets fudged: **there is no "merge" mode, no `--preserve-live-denies` flag, and no "union in on first run".** A live deny the operator wants kept is kept by adding it to the template, in a reviewable diff. That is the entire point of #1221.

### AD-2 — **Python**, single entry point: `scripts/framework/gen_sandbox_config.py`. No bash wrapper. (BINDING.)

I depart from the `gen_codeowners.sh` precedent, deliberately, on four grounds:

1. **The precedent does not transfer.** `gen_codeowners.sh` maps a line-oriented text source to a line-oriented text artifact. Bash is right there. Here both source and target are JSON documents requiring structural substitution, order-insensitive array comparison, and rule-level diffing (FR-8). A byte-diff in bash reports divergence on key reordering — a check that cries wolf gets ignored, which for a security boundary is worse than no check.
2. **`jq` is not a guaranteed dependency; `python3` is** (VF-9). Making a security-boundary generator depend on a tool `hos_bootstrap.sh` does not install is how a fresh machine gets a silently un-run check.
3. **Testability is the deciding factor.** `run_tests_inner_loop.sh` is pytest, and `scripts/framework/` already has three Python modules tested by direct `importlib` import (VF-9). The §6 acceptance criteria are unit assertions over data structures; in Python they are direct, in bash they are `subprocess` + string scraping.
4. **`scripts/framework/` is already mixed-language.** This is not a new pattern in the directory.

Invocation is direct (`python3 scripts/framework/gen_sandbox_config.py …`, shebang + executable bit), matching `require_human_approval.py`. **No `.sh` wrapper** — a wrapper adds a second invocation site with no behavior, which is exactly what D41 forbids. Standard library only: `json`, `argparse`, `pathlib`, `os`, `subprocess` for the one `git` call in AD-7. No new `requirements.txt` entry.

### AD-3 — FR-6 is satisfied by **validate-before-touching-the-filesystem**, with temp+`os.replace` as defense in depth. (BINDING.)

The natural implementation the task asks me to confirm — temp file, validate, atomic rename — is *sufficient but weaker than necessary*. Bind both layers, in this order:

1. **Primary:** build the complete document in memory, serialize it, and run the surviving-`__` scan on the serialized string. On any surviving placeholder, on a malformed template, or on any missing value: **exit non-zero having performed no filesystem write of any kind.** "No partial file" is then true by construction, not by cleanup. There is no `finally: unlink` to get wrong, and no window in which a partial file exists.
2. **Defense in depth:** write via `tempfile.mkstemp` **in the target's own directory** (never `/tmp` — `os.replace` is not atomic across filesystems and `/tmp` is frequently a separate mount), `flush` + `os.fsync`, then `os.replace`. Precedent: `scripts/automation/lib/overseer_state.py:57` (VF-10).
3. The FR-7 backup is taken **before** the replace and is a copy of the *pre-existing* live file. A backup that could ever contain generator output is not a backup. Backup naming carries a UTC timestamp; the generator prints the exact restore command on success.

The surviving-`__` scan runs on the **serialized output**, not on a per-value check, so it catches placeholders anywhere — including inside the `SessionStart` hook command string (template line 9), which a naive per-key walk would miss.

### AD-4 — CLI shape. (BINDING on the interface and the exit-code classes; wording is `technical-design`'s.)

```
scripts/framework/gen_sandbox_config.py
    --role {human|worker|overseer}      REQUIRED. No default, no inference.
    --clone-dir <path>                  REQUIRED. No default, no cwd fallback.
    [--check]                           Compare only; write nothing, ever.
    [--force]                           Permit overwriting an existing live file.
    [--<placeholder> <value> …]         One override flag per placeholder (AD-5).
```

- **No default for `--role` and no default for `--clone-dir`.** FR-2's rationale is exactly right and I reinforce it: a generator that can guess is a generator that can hand `worker` `human`'s policy. `--clone-dir` is `realpath`-resolved and must be an existing directory containing `.claude/`.
- **Role validation lives in one function in the generator, at the top of `main()`, before any I/O.** Not in `argparse` `choices=` alone — `choices=` conflates "unknown role" (usage error) with "known but unsupported role" (#1146 refusal), and AC2 requires the second to be distinguishable. `argparse` accepts the three known roles; the explicit gate rejects `worker`/`overseer` with a message naming **#1146** and exits with the reserved unsupported-role code. **This gate runs before the template is read, before `--clone-dir` is touched, and before any temp file exists**, so AC2's "neither writes any file" is structural rather than incidental.
- **Distinct, documented exit codes are a requirement, not a nicety.** At minimum: `0` success/current · `1` divergence (`--check`) · `2` usage error · `3` unsupported role (#1146) · `4` refusal to overwrite without `--force` · `5` hard failure (surviving placeholder, malformed template, missing values). Exact numbers are `technical-design`'s; **distinctness and header documentation are mine.** AC2/AC3/AC6 assert on them, and the FR-9 hook must distinguish "divergent" from "never generated" from "the tool is broken" — three situations that demand three different operator messages.
- **`--check` implies no-write absolutely.** `--check --force` is a usage error, not a silent precedence rule.
- **Echo-back is mandatory.** Before writing (and in `--check`), print every resolved placeholder → value pair. Silent substitution of a wrong path is precisely the #1114 failure class this feature exists to end; the operator must be able to see the wrong value rather than infer it from later tool failures.

### AD-5 — Placeholder values: derived where a convention exists, **required-explicit where none does**, and **persisted so `--check` is reproducible**. (BINDING.)

FR-4 has no source of truth for two of its seven placeholders (VF-6) and no mechanism by which `--check` can reproduce a generate-time substitution (VF-7). Both are closed here.

**Defaults (each overridable by flag, each echoed back):**

| Placeholder | Source |
|---|---|
| `__ROLE__` | `--role` |
| `__PROJECT_ROOT__` | `realpath(--clone-dir)` |
| `__HOS_ROOT__` | parent of `--clone-dir` (the established `HOS_ROOT/{Human,Worker,Overseer}` layout) |
| `__CONFIG_DIR__` | `${HOS_CONFIG_DIR:-$HOME/.config/hos}` — **reuse `validate_setup.sh:58`'s precedence exactly; do not invent a second one** |
| `__HOME__` | `$HOME` |
| `__HANDOFF_DIR__` | **no default — required explicit value** |
| `__CLAUDE_PROJECT_STATE__` | **no default — required explicit value** |

Deriving `__HOS_ROOT__` and `__PROJECT_ROOT__` from an explicitly supplied `--clone-dir` is not the inference FR-2 forbids: FR-2 forbids guessing *which role and which clone*, and both are stated on the command line. The two with no default fail closed twice over — no value means the placeholder survives, and FR-6/AD-3 hard-fails on it before any write.

**`technical-design` MUST recover the ground-truth `__HANDOFF_DIR__` and `__CLAUDE_PROJECT_STATE__` values from the live Human `.claude/settings.local.json` (operator-assisted; that file is not readable from this clone) and record them in the design.** Do not derive `__CLAUDE_PROJECT_STATE__` from a guessed path-mangling rule for `~/.claude/projects/<mangled>` — that is an undocumented Claude Code internal, and a wrong value produces exactly the silent under-blocking §1 of `docs/SANDBOX-POLICY.md` exists to end. If the mangling is confirmed against the live directory, a derived default may be added; until then it is explicit.

**The values file (this is the load-bearing addition):**

Generation writes an untracked, machine-local values sidecar into the clone (working name `<clone>/.claude/hos-sandbox.values`, `KEY=VALUE`), written under the same AD-3 atomic discipline. `--check` reads it and needs no value flags at all. Therefore:

- `--check` becomes `--role human --clone-dir <path> --check` — which is all `validate_setup.sh` can supply (VF-2), so AD-6 is implementable.
- **Absence of the values file is a distinct non-zero `--check` result with its own message** ("this clone's policy was never generated — it is hand-maintained"), never conflated with divergence. That distinction is the difference between "you have drifted" and "you were never enrolled."
- **The `.gitignore` entry ships in this PR** (VF-8). A generated machine-local file that shows up in `git status` will eventually be committed.
- **The values file is a new self-modification surface and must be denied in the same PR.** `contract/sandbox-policy.template.json` already denies `Edit(./.claude/settings.json)` and `Edit(./.claude/settings.local.json)`; FR-14's template reconciliation MUST add the values file to that deny family. Introducing a file that steers the generation of the policy while leaving it agent-editable would mean this PR *widens* the self-modification surface it exists to protect. This is inside FR-14's remit — it is not scope creep, it is FR-14 applied to what this PR creates.

### AD-6 — FR-9: the hook is **opt-in via an explicit `--role` argument to `validate_setup.sh`, defaulting to skip**, and only `bin/hos-human` passes it. (BINDING.)

VF-2 and VF-3 make the naive reading of FR-9 unsafe. Bound shape:

1. `validate_setup.sh` gains an optional `--role <role>` argument. **If absent, the sandbox check does not run at all** — `bin/hos-worker`, `bin/hos-overseer`, `bin/hos-cron` and `hos_setup_partner.sh` are **not modified in this PR** and their behavior is byte-identical to today. This keeps the cron path (VF-3) structurally out of reach, avoids a per-cycle #1146 error on clones the generator refuses by design, and keeps the diff to `bootstrap/**` and `bin/**` (both protected) minimal.
2. `bin/hos-human:25` passes `--role human`. That is a **declaration** by the one launcher that is definitionally the Human launcher — not an inference, so FR-2 holds.
3. The check is a single function invoked so that **its failure can never reach the script's exit code**: run it under `if ! sandbox_config_check; then …report…; fi`, and let the function itself return non-zero rather than calling `fail()`. `validate_setup.sh` runs under `set -euo pipefail`; the function must contain no bare failing command outside a conditional, and must not use the existing `fail()` helper (`:27`), which exits 1.
4. **Different exit classes get different messages** (AD-4): divergence → loud stderr WARN naming the diverging rules and the regeneration command; values file absent → a one-line "not enrolled" note; generator missing or crashed → a WARN that says the *check* failed, never one that implies the *policy* is fine. Silence on a broken checker is how a control becomes decorative.
5. **The preflight's `=== Preflight PASSED ===` line and `exit 0` are unchanged.** E-2 stays deferred, correctly.

I confirm this is a clean fit and does not widen scope: it is one new optional argument, one new function, one line changed in one launcher.

### AD-7 — Provenance is **reported, never embedded**; a dirty template is a loud warning. (BINDING.)

`.claude/settings.local.json` is consumed by Claude Code. **Do not inject provenance keys, comments, or a `_generated_by` field into it** — unknown keys in a settings file are a compatibility gamble taken for a cosmetic gain, and any such key also has to be excluded from the `--check` comparison, adding a special case to the one code path that must be trustworthy.

Instead: on both generate and `--check`, print to stdout the template's git blob SHA (`git rev-parse HEAD:contract/sandbox-policy.template.json`) and **whether the working-tree template is dirty** (`git status --porcelain`), with a loud warning when it is. Rationale, and it is a real finding rather than tidiness: a sandboxed agent may edit `contract/sandbox-policy.template.json` (no deny covers it) and then run the generator with `--force`, rewriting the very policy that constrains it — a new link in the #1183 escalation chain. The dirty-template warning is the cheap tell. The structural fix (a `denyWrite` covering `.claude/` and `contract/`) belongs to #1146; routed as N2.

### AD-8 — Required correction to FR-12, and confirmation of the rest of §5. (BINDING.)

**FR-12's enumeration MUST additionally retain `Bash(git push* +*)`** (VF-5) — the `+refspec` force-push form present in the template today at line 125 and absent from the spec's list of five. Under §5's own principle a deny is only ever added, so the reconciled template carries **six** force-push spellings, not five. `technical-design` must state the final list explicitly and the PR's delta table must show it as retained.

Confirmed as written, with reasons rather than assent:
- **The deny-union / allow-template-only asymmetry (§5) is correct and is the best judgment in the spec.** Monotonicity of denies under unverified glob semantics is exactly the right reason, and it is why AD-1's "one-time reconciliation" is safe: over-denying costs friction that is visible, under-denying costs a control that is not.
- **FR-11's three `bin/**` spellings**, with the redundancy commented **in the generator source** (not in the JSON — see AD-7). Correct at zero capability cost.
- **FR-13** — `Bash(claude *)` is an allow, and allows are template-only; consistent. And per `docs/SANDBOX-POLICY.md` §3, `autoAllowBashIfSandboxed: true` makes the allow list advisory anyway.
- **FR-12's `--force-with-lease` consequence** — accepted, and VF-11 confirms it costs nothing: the string appears nowhere in this repo's scripts.
- **FR-10 (no CI workflow)** — correct and correctly characterized as unachievable rather than deferred. CI has no live file to compare against and never will.
- **§7's E-1 and E-2 deferrals, and the §6 replacement of "byte-for-byte" with semantic-superset** — all three are right, and the byte-for-byte substitution is right *because* §5 chose union, which pm-agent states explicitly.

### AD-9 — Acceptance criteria: three of the seven are not automatable as written and are **re-specified here**. (BINDING on the test strategy.)

`run_tests_inner_loop.sh` (pytest, `not slow and not integration`) must pass before any PR. Against that:

- **AC1 is not automatable as written** — "against the live Human clone" is machine-specific, gitignored, and unreadable from this clone. **Split it:** *(1a, automated)* a pytest using `tmp_path` with a fixture "stale live" file + fixture template: `--check` exits with the divergence code; run generate; `--check` exits 0. This is the criterion that actually matters — it proves the check detects divergence rather than always passing (VF-4). *(1b, manual)* the operator runs `--check` on the real Human clone before and after, and the **transcript is pasted into the PR body as evidence.** Manual evidence in the PR body, not a test that silently skips in CI.
- **AC4 requires a committed fixture or it is unverifiable by any reviewer.** "Semantic superset of the pre-existing live file" names a file no reviewer can see. Land a **sanitized, path-templated snapshot of the pre-existing live Human file as a test fixture** under `tests/framework/fixtures/`, and compute the delta table from it in a test. Sanitize with the existing idiom (`scripts/framework/strip_internal_paths.sh` / `installer-internal-paths.txt`) so no absolute home path is committed. Without the snapshot, AC4's delta table is an assertion by the author about a file only the author has read — which is the exact property #1221 exists to remove.
- **AC7 must run against a fixture clone dir**, not a real divergent clone: `validate_setup.sh --repo <tmp_path> --role human` on a prepared tree, asserting stderr contains the divergence report **and** `$? == 0`. Both halves asserted; asserting only the exit code would pass on a hook that prints nothing.
- **AC2, AC3, AC5, AC6 are automatable as written** and become direct pytest assertions on the AD-4 exit codes. AC3 must additionally assert **no file exists** afterwards (not merely that the target is unchanged) — including no stray temp file in the target directory, which is the AD-3 property under test. AC5 should assert byte-identity across two runs *and* stability under a shuffled template key order, since determinism is the property AC4's comparison rests on.
- **One test the spec does not require and I do:** assert that generate mode **never opens the live file for reading** (monkeypatch/`unittest.mock` on `open`, or a fixture whose live file is mode `000`). That is AD-1's invariant, it is invisible in output, and it is the failure that makes the whole feature decorative (VF-4).

---

## 3. Where pm-agent was right, and where I differ

**Right, and materially so:** the §2 installer analysis is the best-argued section and I adopt it wholesale — the consumer-installer vs. HOS-operational-layout distinction, and the "a config that must be regenerated on every template change cannot live in a one-shot setup path" argument, are both decisive. FR-2's no-inference rule and its one-sentence justification. FR-5's fail-closed-with-a-named-blocker, which converts an unresolved design question into an enforced refusal — that is the right shape for #1146. The §5 asymmetry (AD-8). Correcting the "there is a CI currency check for `gen_codeowners.sh`" assumption instead of inheriting it. FR-10's "not a deferral — not achievable." And the §6 deferrals of #1221's own stated criteria, each with the reason attached.

**Differed / sharpened, five places:**
1. **§5 reads as runtime behavior and must not be** (AD-1, VF-4). This is the one that silently guts the feature.
2. **FR-12 drops a tracked deny** (AD-8, VF-5) — a subtraction inside a never-subtract principle.
3. **FR-9 collides with FR-2 and with the cron call site** (AD-6, VF-2/VF-3); resolved by an opt-in `--role` that leaves worker/overseer/cron untouched.
4. **FR-4 has no value source for two placeholders and no reproducibility path for `--check`** (AD-5, VF-6/VF-7). The values sidecar is the missing piece; without it FR-8 and FR-9 cannot both be true.
5. **§6's AC1/AC4/AC7 are not automatable as written** (AD-9), and AC4 in particular is unreviewable without a committed sanitized fixture.

None of these is a scope or requirements defect. All are architecture and all are decided here — **no return to `pm-agent`.**

---

## 4. Notes and obligations — routed, none blocking

**N1 — First `--force` run on the live Human clone needs the operator present (to the human; NOT a design gate).** The generator overwrites a hand-tuned production security config on the operator's own interactive clone. FR-7's backup plus AD-3's printed restore command make it recoverable, and the risk is entirely in the visible direction (over-blocking → friction at session start). Design and build proceed now; the *first* live `--force` invocation is an operator action taken knowingly, with the AC1b transcript captured. Nothing about this gates `technical-design`.

**N2 — The generator is a new link in the #1183 escalation chain (to #1146 / the human; NOT a gate).** `contract/sandbox-policy.template.json` is agent-writable at the OS layer (`allowWrite` covers the whole clone; only `__PROJECT_ROOT__/bin` is `denyWrite`), so an agent could edit the template and regenerate. AD-5 closes the values-file half of this inside this PR; AD-7 adds the dirty-template tell. The structural fix — extending `sandbox.filesystem.denyWrite` to `.claude/` and `contract/` — is **#1146's**, not this PR's, and I am explicitly declining to absorb it. Record it on #1146.

**Product-boundary checkpoint (CORE discipline).** Applied and cleared. AD-6 is the only decision touching user-visible behavior: it adds one stderr warning to the human operator's session start and changes nothing else, on nobody's cost model, retention surface, or deployment topology. The two decisions that *would* have crossed the boundary — blocking session start (E-2) and generating `settings.json` (E-1) — pm-agent already routed to the human and I am not reopening either. The one operational obligation created (re-run the generator when the template changes) is routed as N1.

**Startup-gap analysis (CORE discipline).** This is the **initial** architecture review for #1221. No prior ADR covers this surface and no design or code sign-off exists against any superseded decision — **no sign-off is orphaned and none requires re-review.** The adjacent artifact is `docs/SANDBOX-POLICY.md` §4 items 6 and 7, whose open questions this ADR narrows (item 6 is discharged by AD-3; item 7's glob-semantics uncertainty is left open by design and made harmless by the union). `docs/SANDBOX-POLICY.md`'s status section must be updated in this PR to say the template is now *generatable for `human`* — it currently reads "not yet installed by `hos_install.sh`", which remains true and must stay, since AD-1 does not touch the installer.

---

## 5. Cleared-to-build

**`technical-design` MAY proceed NOW**, against AD-1 … AD-9. The four things it must not get wrong, in order of damage:

1. **Generate mode must never read the live file** (AD-1). Get this wrong and the currency check can only pass — a control that reports green forever, which is worse than no control.
2. **Retain `Bash(git push* +*)`** (AD-8). A silent deny removal in a deny-union PR.
3. **The FR-9 hook must be opt-in and must never reach an exit code** (AD-6). The cron path discards stderr and aborts the cycle on non-zero (VF-3).
4. **`--check` must reproduce the generate-time substitution without flags** (AD-5), or FR-8 and FR-9 cannot both be satisfied.

**Two empirical obligations on `technical-design`, to be discharged in the design document, not assumed:** recover the live `__HANDOFF_DIR__` and `__CLAUDE_PROJECT_STATE__` values (AD-5), and capture the sanitized pre-existing live-file snapshot that AC4 rests on (AD-9).

**Acceptance for this ADR** is SPEC-1221 §6 as amended by AD-9, plus: a test asserting generate mode does not read the live file (AD-9); a test asserting `--role worker` and `--role overseer` exit before any filesystem access (AD-4); a test asserting the values file's absence is reported distinctly from divergence (AD-5); and the PR's delta table showing six force-push denies (AD-8).

---

## Human Review Required

**RISK: MEDIUM** (confirmed — pm-agent's tiering and its reasoning are right). The artifact under generation is a security boundary, and the residual risk after this ADR is concentrated in the under-blocking direction: a check that always passes (AD-1) or a hook that reports nothing (AD-6) both present as a healthy system. AD-9's "never reads the live file" test is the proof obligation for the first; AC7's stderr assertion is the proof obligation for the second.

**CONFIDENCE: HIGH** on everything read against this working tree: `contract/sandbox-policy.template.json` in full, `docs/SANDBOX-POLICY.md` in full, `bootstrap/validate_setup.sh` in full, all five `validate_setup.sh` call sites, `scripts/framework/gen_codeowners.sh`, `check_validation_current.sh`, `protected_surfaces.txt`, `run_tests_inner_loop.sh`, the `tests/framework/` import idiom, and `.gitignore`. **LOWER** on the two placeholder values with no in-repo derivation (VF-6) — which is why AD-5 makes them required-explicit and makes recovering them an obligation on `technical-design` rather than a guess here. Glob-matching semantics remain unverified (`docs/SANDBOX-POLICY.md` §4 item 7) and every decision above is chosen to be safe under that uncertainty rather than to depend on resolving it.

**BLAST RADIUS:** the Human clone's live sandbox config, plus one new stderr line at Human session start. No consumer project, no autonomous role, no cron path. Rollback is the FR-7 backup plus reverting one line in `bin/hos-human`.

**Change classification: ADDITIVE.** A new generator, a new optional argument on an existing preflight, and a reconciliation of an already-tracked template. Nothing existing changes behavior except `bin/hos-human`, which gains one argument. The two structural questions (E-1 `settings.json` generation, E-2 blocking session start) remain deferred to the human exactly as pm-agent left them; nothing here pre-empts either.

---

## 6. Ruling on `technical-design`'s flagged extensions

**Date:** 2026-08-04 · **Input:** `docs/v0.6.0/TECHNICAL-DESIGN-1221-clone-sandbox-config-generation.md` DRAFT 1, read in full · **Design round:** 1 of 5.

`technical-design` flagged three decisions that extend AD-4/AD-5 rather than restate them. **All three are ACCEPTED as consistent refinements within this ADR's intent.** None touches AD-1's purity invariant, none subtracts a deny, and each is stricter or narrower than the alternative it replaced.

### 6.1 — Exit code `6 = NOT_ENROLLED`. **ACCEPTED.**

AD-4 bound distinctness and header documentation, not the cardinality, and said "at minimum" precisely because AD-5 demands a *seventh* distinguishable outcome. Folding "never enrolled" into exit `1` with different stderr text would have made the `validate_setup.sh` hook's message selection depend on parsing the checker's prose — a string-match where an integer belongs, and one that breaks silently the first time a message is reworded. Seven codes is the correct reading. Two consequences I bind alongside it: §4's rule that `main()` never leaks a bare `1` from an unhandled exception is **not optional** — it is what keeps a crashed checker from being reported as divergence — and §9.2's class-D catch-all must include `6`'s absence from the divergence arm as a tested property (tests 21, 40, 41 do this). I also accept that `--check` returns `6` at §6.6 step 6, **before** echo-back: with no sidecar and no flags there are no resolved values to echo, so AD-4's echo-back mandate is not weakened, only inapplicable.

### 6.2 — Three deny spellings for `<clone>/.claude/hos-sandbox.values`. **ACCEPTED.**

AD-5 bound *that* the values sidecar joins the deny family and left the spelling open. Applying FR-11's reasoning to it is exactly right, and for a stronger reason than FR-11 had: the sidecar is a **new** entry landing under the same unverified glob semantics (`docs/SANDBOX-POLICY.md` §4 item 7), and it steers the generation of the policy itself, so a single-spelling miss is a miss on the file with the highest leverage in the whole feature. Three spellings costs zero capability and is monotone with §5's deny-union principle. Two boundaries, recorded so no reviewer reads them as gaps: the denies are `Edit(...)`-only, at parity with the existing `settings.json` / `settings.local.json` family — a `Bash`-mediated write is **not** covered, and that residual is `sandbox.filesystem.denyWrite`'s job under §4 **N2** / #1146, which this PR still declines to absorb. And §8.1's decision *not* to backfill absolute spellings for the two existing `settings*.json` denies is correct scope discipline; routing that observation to #1146 in `docs/SANDBOX-POLICY.md` §4 is the right disposal.

### 6.3 — Generate mode does not read the values sidecar. **ACCEPTED — no conflict with AD-5.**

Confirmed explicitly, since this is the item most likely to be misread later: AD-1's rule is *"never reads live state in order to produce output."* It constrains **inputs to `render()`**, not filesystem contact in general. Generate **writing** the sidecar (AD-5) is an output, sequenced after `os.replace` so a sidecar never describes a generation that did not land; generate **not reading** it is a strengthening of AD-1, not a violation of AD-5. AD-5's requirement was only that `--check` be reproducible without flags, which §5.3 satisfies. The design's formulation — *generate mode opens exactly one file for reading, the template* — is a crisper invariant than AD-1's own wording and I adopt it as the binding statement of AD-1 going forward; tests 18–20 are its proof obligation. Two residuals, both in the safe direction: the operator re-supplies `--handoff-dir` / `--claude-project-state` on every regenerate (mitigated by the sidecar being plain-text readable and by the printed `regenerate_command`), and a crash between the policy write and the sidecar write leaves a stale sidecar, which makes the next `--check` report **divergence** rather than falsely report current. Fail-visible is the correct direction.

### 6.4 — Startup-gap and sign-off analysis

None of the three is a `startup-artifact-gap`: all three are decisions AD-4 and AD-5 **explicitly delegated** to `technical-design`, not decisions that should have been settled before design began. No ADR revision is required, no prior sign-off is superseded, and **no design or code approval is orphaned** — no code exists against any earlier reading of AD-4/AD-5. §5's four "must not get wrong" items and the acceptance list stand unchanged.

**Verdict: `technical-design` is cleared to hand off to `coder`.** No changes required. The two deviations it recorded on the record — the required-explicit placeholder values (§0.1) and the synthetic AC4 fixture (§0.2) — are accepted as designed-around rather than guessed, and both remain visible to the human reviewer in the PR body, which is where AD-9 put them.
