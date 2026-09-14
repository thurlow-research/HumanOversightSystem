# TECHNICAL DESIGN — #1357 slice 1: merge-authority primitives

**Status:** **ACCEPTED — CLEARED FOR THE CODER** (architect, 2026-09-14, iteration 2 of 5).
ARCH-1, ARCH-2 and ARCH-3 are **resolved**; the architect's verification of each is in **§14**.
**Two binding conditions attach to this clearance — ARCH-4 and ARCH-5 (§14.5).** They are mechanical
applications of rules this design already owns, they are requirements on the coder's implementation,
and `code-reviewer` must verify both before sign-off. No further technical-design iteration is
required. The architect's iteration-1 ruling is preserved verbatim in **§13**; TD-O1, TD-O2 and TD-O3
remain closed and are not re-opened.
**Date:** 2026-09-14 (iteration 1) · revised 2026-09-14 (iteration 2)
**Iteration:** 2 of 5 (CORE cap)
**Author:** technical-design

**Iteration-2 change log** (every edit, so the architect can diff by section):

| § | Change | Driver |
|---|---|---|
| §3.2 | Envelope gains `repo_root` (absolute) and `app_role` | ARCH-1.4 |
| §3.4.0 | **New.** Flag classification (subject vs policy-source selector) + the unevaluable-gate disclosure rule | ARCH-1.1, ARCH-2 (generalised) |
| §3.4 globals | `--repo-root` **removed from argv** (replaced by a test-only injection parameter); the false "cannot widen any answer" sentence **deleted** | ARCH-1.3 |
| §3.4 `register` | `--manifest` **removed**; payload gains `required_signoffs`, `required_roles_resolved`, `gate_evaluable` | ARCH-1.2, ARCH-2.1, ARCH-2.2 |
| §3.4 `protected-surface` / `security-surface` / `codeowners` | Unevaluable-gate `not_verified[]` disclosure applied | ARCH-2 (same class) |
| §3.6 | **New.** Forward constraints binding slice 2 | ARCH-1.4, ARCH-2.3 |
| §6.1 | `bot_accounts` boundary conversion pinned (mypy) | ARCH-3b |
| §7.2 / §7.3 / §7.4 | Bash no longer composes JSON — **one envelope producer** | ARCH-3a |
| §9 | TD-F1 recorded (AF-3 class, `register` variant); TD-O1/O2/O3 marked closed-by-ruling; §13.1 action 1 carried forward | ARCH-2.4, §13.1 |
| §10 | T1.7 extended; T4.8, T6, TW.2 revised/added | ARCH-1.2, ARCH-2, ARCH-3a |
| §12 | Acceptance checks 7–8 added | ARCH-1, ARCH-3a |

No other section is modified. §0, §1, §2, §3.1, §3.3, §3.5, §4, §5, §6.2, §7.1, §8, §11 and §13 are
byte-unchanged from iteration 1.

**Disclosure — three touches to text §13.8 lists as accepted, each made under an explicit
instruction in §13.5–§13.7, none reversing any accepted decision.** Flagged rather than left for the
architect to find in a diff:

1. **§3.2 (accepted as "§3.1–§3.3")** — ARCH-1.4 requires the envelope to carry the absolute repo
   root, which is §3.2's table. Added `repo_root` and `app_role`; no existing field was changed or
   removed.
2. **§7.3 step 3 (accepted)** — ARCH-3a's shape means bash mints only when it successfully extracted
   a role, so step 3's condition gains the clause "and a valid `--app` role was extracted". The
   mint/revoke mechanism itself (`query_issues.sh:140-146` pattern) is untouched.
3. **§7.2 and §7.4 (accepted)** — one appended sentence and one appended paragraph recording that
   the wrapper now owns no JSON. Nothing existing was altered.

If the architect regards any of the three as out of bounds, they revert independently without
affecting ARCH-1 or ARCH-2.
**Binding input:** `docs/v0.7.0/ADR-1357-merge-authority-execution.md` (ACCEPTED; ESC-1/2/3 resolved by human ruling in #1357's comment thread).
**Scope:** ADR §4 build slice **1 of 6** only — "Primitives".
**Slice gate (from ADR §4):** every primitive invocable from a fixed argv line; the 157 existing library tests still green.

> This document specifies **contracts, not code**. Every "must" below is a requirement on the
> implementation, not a suggestion about how to write it. Where the ADR is explicit, this document
> restates it in implementable terms and adds nothing; where the ADR left a choice to
> `technical-design`, the choice is made here and labelled **TD-D<n>** with its reason.

---

## 0. Verification findings — what I checked in the tree before writing this

All citations are the working tree at branch `worker-1357-merge-authority-primitives-…`, which matches
`origin/main` for every file named.

- **TD-VF-1 — the promotion is a clean rename; no compatibility shim is needed.**
  `_touches_security_surface` is referenced in exactly three places in code:
  its definition (`merge_authority.py:414`) and its one call site (`:623`), plus prose in
  `DECISIONS.md:606` and a historical prompt artifact
  (`prompts/scripts/automation/lib/merge_authority.v2.md:27`). **No test imports it.** The same
  holds for `_find_human_approval` (definition `:43`; call sites `:81, :539, :625, :645, :682`; no
  test importer). So AD-13's "157 existing tests stay untouched" survives a plain rename — an alias
  would be a second name for one authority and must **not** be added (TD-D1).
- **TD-VF-2 — `github.py` cannot yet fetch what four of the eight primitives need.** Its public
  surface is `get_ref`, `get_branch`, `list_pulls`, `list_issue_comments`,
  `list_check_runs_for_ref`, `get_branch_protection`, `get_repo`, `post_comment`. There is **no**
  single-PR read, **no** review list, **no** changed-files list, **no** commit read. Its own
  docstring says *"All correctness-path reads MUST go through this module"*, so the four missing
  reads are additive changes to `github.py`, not private helpers in the CLI (TD-D3).
- **TD-VF-3 — AD-9's config file does not exist on a consumer install.** `hos_setup_partner.sh:168-176`
  writes `OVERSEER_CEILING`, `HUMAN_REVIEWER`, `BOT_*_USERNAME`, `BOT_ACCOUNTS` and
  `TIER_CEILING_CHECK_NAME` into `~/.config/hos/apps.env` (0600), **not** into
  `scripts/framework/machine-accounts.env`; and `framework_consumer_files.txt` ships neither that
  env file nor any of `scripts/automation/**`. AD-9 binds the HOS-repo path, which is correct for
  slice 1 (the HOS repo is the only consumer until slice 6 ships the surface). The consumer-install
  config location is a real, verified gap and is **routed, not resolved, here** — see §9 / TD-O1.
- **TD-VF-4 — `check_pr_files` lives in `scripts/oversight/codeowners.py`, which is not an
  importable package.** There is no `scripts/oversight/__init__.py`; `tests/oversight/` imports it
  only because `tests/conftest.py` injects `scripts/oversight` onto `sys.path`. Production code
  must therefore load it **by file path**, which is exactly the idiom `merge_authority._load_audit_log`
  (`:1056-1071`) already uses for `scripts/oversight/lib/audit_log.py`, for the same
  trust-direction reason. `scripts/automation/{,lib/}__init__.py` and `scripts/__init__.py` all
  exist and are empty, so `scripts.automation.lib.*` imports work with the repo root on `sys.path`.
- **TD-VF-5 — the bounce cap `2` currently has no named home.** It appears as prose inside
  `_bounce_comment_body`'s f-string (`"(cap: 2 before human escalation)"`, `:1113`) and as a literal
  in `overseer.md` step 4a. `bounce-count`'s `cap` field (AD-3) needs a value; inventing a second
  `2` in the CLI would be the #1135 duplicate-authority class. See TD-D2.
  `tests/automation/test_bounce_gate.py` contains **no** assertion on the string `"cap: 2"`, so
  naming the constant cannot break it (the rendered text stays byte-identical regardless).

---

## 1. What slice 1 delivers, and what it deliberately does not

**Delivers:** the L2 primitive CLI module, the L3 bash wrapper, the AD-9 config resolver, the
`touches_security_surface` promotion, the four `github.py` read helpers those primitives need, and
AD-13 tests 1–4 scoped to the primitive surface.

**Does not deliver** (named so the coder does not drift into them):

| Not in slice 1 | Owner |
|---|---|
| `compute_decision`, the decision record, `next_action`, `disposition` | slice 2 |
| Any mutation, any GitHub write, any audit-event write, any refusal path (exit 3) | slice 4 |
| `_dep_ceiling_check_present` / `_verify_overseer_review_accepted` implementation | slice 5 |
| Any edit to `overseer.md`, `overseer-cron-prompt.md`, or `contract/**` | slice 6 |
| Any edit to `framework_consumer_files.txt` | slice 6 (decision recorded here, §8) |
| A wrapper for `open_draft_pr` | never (ADR AD-12) |
| Changes to `decide_merge_authority`'s behaviour or signature | never (ADR AD-1) |

**Hard prohibition, restated from AD-1:** `scripts/automation/lib/merge_authority.py` gains **no**
`argparse`, **no** `__main__`, **no** `sys.argv` read, and **no** signature change. The only edits it
receives in this slice are the two named in §4.

---

## 2. Layer map for slice 1 (concrete file paths)

```
L1  scripts/automation/lib/merge_authority.py     pure logic — 2 surgical edits only (§4)
    scripts/automation/lib/github.py              4 additive read helpers (§5)
    scripts/oversight/codeowners.py               UNCHANGED (loaded by path)
      ^ imported by
L2  scripts/automation/lib/merge_config.py        NEW — AD-9 config + repo identity (§6)
    scripts/automation/merge_authority_cli.py     NEW — fetch, marshal, serialize (§3)
      ^ invoked by
L3  bootstrap/merge_authority.sh                  NEW — token, invoke, pass through (§7)
```

**Why `merge_config.py` is its own module and not a function inside the CLI (TD-D4).** Three future
consumers need it inside this ADR: `overseer_decide.compute_decision` (AD-9 names it explicitly,
slice 2), the mutation wrappers (slice 4, via `compute_decision`), and
`_dep_ceiling_check_present`'s `TIER_CEILING_CHECK_NAME` lookup (slice 5, which is an **L1** change
and must not import an L2 CLI module). Putting the resolver in `lib/` keeps the dependency arrow
pointing the right way for all three. It costs one file.

**Import bootstrap.** `merge_authority_cli.py` must insert its own repo root —
`Path(__file__).resolve().parents[2]` — at `sys.path[0]` before importing `scripts.automation.lib.*`,
so the CLI is **cwd-immune**. It must not rely on being invoked from the repo root and must not
rely on `PYTHONPATH`. Rationale is `commit_onto_base.sh:114-118` verbatim: a cwd-relative import
silently disables the thing it is guarding the moment someone invokes it from elsewhere — the exact
fail-open shape this ADR exists to remove.

---

## 3. `merge_authority_cli.py` — structure and contract

### 3.1 Module structure

The module has exactly four kinds of member. Nothing else belongs in it.

1. **`main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int`** — builds
   the parser, dispatches, prints exactly one JSON object to stdout, returns the exit code.
   `if __name__ == "__main__": sys.exit(main())`. `main` must be callable in-process from tests with
   an explicit `argv` list and must **never** call `sys.exit` itself except through that final line.
   *(Signature corrected by the architect at acceptance: the keyword-only `repo_root` is §3.4.0's
   test-only injection point, added in iteration 2. `argparse` must not define it and the `__main__`
   block must not populate it — see §3.4.0 and T1.8.)*
2. **One handler per subcommand**, `_cmd_<name>(args, ctx) -> tuple[dict, int]` — returns the record
   payload and the exit code. A handler performs, in this order and no other: fetch → call the L1
   function → assemble evidence → return. A handler must contain **no** matching, globbing,
   counting, regex or comparison logic that duplicates an L1 function (§3.5).
3. **A small evidence-filter helper set**, each with a docstring stating *"evidence only — never a
   decision"* (only two are permitted in this slice: §3.4 `human-approval`, §3.4 `hold-directive`).
4. **Module constants** — the subcommand name set, the record `SCHEMA_VERSION = 1`, and the set of
   subcommands that touch the network (mirrored by L3, §7.3).

There is **no** module-level side effect: importing `merge_authority_cli` must perform no I/O, no
config read, no `gh` call, no token mint.

### 3.2 The record envelope — present on every emitted record, every subcommand, every exit code

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | Always `1` (AD-2 rule 4). |
| `subcommand` | str \| null | The subcommand that ran; `null` only for an exit-2 record emitted before dispatch. |
| `computed_at` | str | UTC ISO-8601 `%Y-%m-%dT%H:%M:%SZ`, matching `record_pr_bounce`'s existing timestamp format. |
| `repo` | str \| null | `owner/repo`; `null` for a subcommand that performs no network read and was not given `--repo`. |
| `repo_root` | str \| null | **Absolute** path of the checkout every filesystem-derived answer was computed against (ARCH-1.4). `null` only on a pre-dispatch exit-2 record. |
| `pr` | int \| null | The PR number, or `null` for `gate` / `register` / `bounce-count`. |
| `config_source` | str \| null | Absolute path of the `machine-accounts.env` actually read (AD-9). |
| `app_role` | str \| null | The `--app` identity the reads were performed under. A token's visibility affects what a read can see (an inaccessible resource 404s), so the identity is part of interpreting the answer. It is the one subject selector §3.4 did not already echo. |
| `not_verified` | list[str] | **Always present, possibly empty, never omitted.** One `"<what>: <why>"` string per datum the run could not establish. |
| `error` | str \| null | `null` on exit 0; a single-line machine-stable reason on exit 1 and exit 2. |

*(Iteration 2, per ARCH-1.4: `repo_root` and `app_role` are the only two envelope additions. The other
subject selectors are already echoed by the payloads — `repo`, `pr`, `branch`/`branch_source`, `cid`,
`step` — and are deliberately **not** duplicated into a second envelope block, which would be two
representations of one value.)*

Subcommand payload keys (§3.4) are merged at the **top level** of the same object — the record is
flat, not nested under a `result` key, so AD-3's "Emits" column reads directly as top-level keys and
a caller can use `jq -r '.autonomous_capable'` without an accessor path. Payload keys never collide
with envelope keys.

### 3.3 Exit codes — the complete decision table (AD-2 rule 3)

| Condition | Exit | stdout |
|---|---|---|
| The subcommand's question was answered — **whatever the answer** | `0` | full record, `error: null` |
| A fail-closed answer produced *by an L1 function* (e.g. `detect_server_side_gate` converting a protection-read failure into `autonomous_capable: false`) | `0` | full record, plus a `not_verified[]` entry naming what could not be read |
| An *evidence* fetch failed but the decision still stands (e.g. `checked_contexts` unreadable) | `0` | full record, evidence field `null`, `not_verified[]` entry |
| A *required* input could not be obtained: auth failure, `gh` missing, `GitHubError`/`RateLimitError` escaping a required fetch, PR not found, `head.sha` absent or empty, config file or required config key missing, unparseable API payload | `1` | envelope only, `error` populated |
| Usage error: unknown subcommand, unknown flag, missing required flag, non-numeric `--pr`, malformed `--step`/`--cid`, invalid `--app` | `2` | envelope only, `error` populated |
| — | `3` | **Never.** A read-only primitive must never exit 3; exit 3 is reserved for AD-5 mutation refusals (slice 4). |

Two clarifications the coder must implement literally:

- **stdout is one JSON object even on exit 2.** AD-2 rule 2 says "Always", so `argparse`'s default
  behaviour (bare usage text to stderr) is not acceptable. Use an `ArgumentParser` subclass whose
  `error()` emits the envelope with `error: "usage: <message>"` to stdout and the human-readable
  usage text to stderr, then exits 2. *(Architect correction at acceptance: iteration 1 continued
  here "the bash layer does the same for the two checks it makes before Python is reached." That is
  **no longer true and is deleted** — under ARCH-3a the wrapper emits no JSON on any path and rejects
  nothing; Python is the sole author of the record schema. See §7.3 step 2 and TW.2b.)*
- **`head.sha` is never allowed to be `None` or empty** anywhere this module reaches (AD-9, AF-4).
  A PR object without a usable `head.sha` is exit 1, not a `None` passed downstream. There is no
  `--head-sha` flag: the SHA is always freshly fetched.

### 3.4 Subcommands — the complete slice-1 surface (AD-3)

#### 3.4.0 The flag rule, and the unevaluable-gate rule (iteration 2 — ARCH-1.1, ARCH-2)

Two rules govern everything in §3.4. They are stated once here rather than repeated per subcommand.

**Rule A — subject selectors are permitted; policy-source selectors are prohibited.**

- A **subject selector** identifies *what is being asked about*. Substituting it asks about a
  different thing, and the record discloses which thing it asked about. Permitted, and **must be
  echoed in the record**.
- A **policy-source selector** changes *what counts as a pass* — it substitutes the rule rather than
  the subject. **Prohibited outright under AD-2 rule 5**, with no exception, on every surface in this
  ADR. There is no auditable form of it: a record that faithfully echoes the substituted policy file
  still reports a pass computed under a rule the caller chose.

Classification of every flag on the slice-1 surface:

| Flag | Class | Disposition | Echoed as |
|---|---|---|---|
| `--app <worker\|overseer\|human>` | subject (read identity) | **permitted, required on every invocation** | `app_role` |
| `--repo <owner/repo>` | subject | permitted, optional | `repo` |
| `--pr <N>` | subject | permitted, required on the five PR subcommands | `pr` |
| `--branch <name>` (`gate`) | subject | permitted, optional — a consumer can check it against the PR's `base.ref` | `branch`, `branch_source` |
| `--cid <cid>` (`bounce-count`) | subject | permitted, required | `cid` |
| `--step <N>` (`register`) | subject | permitted, required | `step` |
| `--config <path>` | **policy source** | **prohibited** — substitutes the ceiling, the reviewer identity and the bot set | — |
| `--manifest <path>` (`register`) | **policy source** | **prohibited — removed in iteration 2** (ARCH-1.2); see below | — |
| `--repo-root <path>` | **both** | **removed from the argv surface in iteration 2** (ARCH-1.3, option (a)) | resolved value echoed as `repo_root` |
| `--force`, `--skip-*`, `--no-verify`, `--head-sha` | widening | prohibited (unchanged from iteration 1) | — |

**Why `--manifest` is removed.** It is `--config` wearing a different name, and the tree makes it
worse than a symmetry argument: `_required_signoffs_for_step` (`merge_authority.py:838-876`) returns
`[]` for **any** unreadable or unparseable manifest, and `check_register_completeness:906-910` then
returns `bounce_required=False` — so `register --step N --manifest <anything-that-does-not-parse>`
is a single-flag, statically-allowlistable, agent-reachable **fail-open bypass of the
register-completeness gate**, exposed on the merge-decision surface. The manifest path is now
**derived**, never supplied: `<repo_root>/contract/step-manifest.yaml`.

**Why `--repo-root` is removed rather than bounded.** Iteration 1 claimed it "cannot widen any
answer". **That claim was false and is deleted.** Every filesystem-derived gate on this surface is
permissive when its policy file is absent: an empty or missing `protected_surfaces.txt` yields
`touches: false` (`merge_authority.py:391-392`); a missing `security_surfaces.txt` yields `false`
(`:433-434`); a missing `.github/CODEOWNERS` yields `required: False` (`codeowners.py:200-202`); an
empty `audit/log/` yields `count: 0` → `at_cap: false`; a missing manifest yields
`bounce_required: false`. A caller-supplied root therefore selects the policy source for five of the
eight subcommands, which is Rule A's prohibited class. The architect's option (a) is adopted: the
flag does not exist, no operational need for it is visible (the overseer's checkout *is* the clone
the wrapper lives in — `check_register_completeness`'s own docstring relies on that), and L3 forwards
nothing.

**Resolution and the test injection point.** The repo root is always
`Path(__file__).resolve().parents[2]` (§2). Tests reach a fixture tree through a **keyword-only
parameter on `main`** — `main(argv=None, *, repo_root=None)` — which `argparse` must **not** define
and which the `__main__` block must **not** populate from `sys.argv`. It is unreachable from any
command line, and T1.7 pins that mechanically by asserting `--repo-root` exits 2. The resolved
absolute root is echoed as `repo_root` (§3.2) so every filesystem-derived answer is interpretable
against the tree it was computed in.

**Rule B — an unevaluable gate is never a passed gate (AD-4, applied to the primitive surface).**

Four subcommands wrap an L1 function that returns the **permissive** value when its policy input is
absent. In every such case the record must make the condition **machine-readable** — never leaving a
"nothing to check" outcome byte-identical to a "checked and clean" outcome — and must add a
`not_verified[]` entry naming the file that was read and why nothing was resolved. It stays **exit 0**:
it is an answer, not an operational failure.

| Subcommand | Permissive-on-absence condition | Machine-readable discriminator |
|---|---|---|
| `register` | no required roles resolved from the manifest | `gate_evaluable`, `required_roles_resolved`, `required_signoffs` |
| `protected-surface` | `protected_surfaces.txt` absent | `surfaces_file_present: false` |
| `security-surface` | `security_surfaces.txt` absent | `surfaces_file_present: false` |
| `codeowners` | `.github/CODEOWNERS` absent | `codeowners_present: false` |

ARCH-2 required this for `register`. Applying it to the other three is the same hazard in the same
class (ADR §0 AF-3: a permissive branch that is invisible only because nothing invokes the function,
and that becomes load-bearing the moment this surface makes it invocable) and costs one boolean and
one `not_verified[]` entry each. The `bounce-count` case — an empty `audit/log/` giving `count: 0` —
is **not** in this table: zero prior bounces is a genuine, correct answer and is not distinguishable
from "no trail" by any signal the library exposes. It is recorded as part of TD-F1 (§9) rather than
papered over here.

**Global flags accepted by every subcommand (post-iteration-2):**

- `--app <worker|overseer|human>` — **required on every invocation**, including the two that make no
  network call, so the argv shape is uniform and therefore allowlistable (AD-2 rule 1). L3 uses it
  to decide whether to mint a token; Python validates it and echoes it as `app_role`.
- `--repo <owner/repo>` — optional; default resolved from the `origin` remote (§6.2).

**There are no other global flags.** No `--repo-root`, no `--config`, no `--manifest`, no `--force`,
no `--skip-*`, no `--head-sha`, no `--no-verify`. **No environment variable of any kind may change
any answer** — the module must not read `os.environ` at all, and `merge_config` reads none either
(§6.1).

---

#### `gate` — `bash bootstrap/merge_authority.sh gate --app <role> [--repo <o/r>] [--branch <name>]`

- **Fetches:** `github.get_repo` (for the default branch, unless `--branch` given) and
  `github.get_branch_protection` (evidence only).
- **Calls:** `merge_authority.detect_server_side_gate(owner, repo, branch, overseer_handle)` where
  `overseer_handle` is the **resolved** `BOT_OVERSEER_USERNAME` (never
  `merge_authority.DEFAULT_OVERSEER_HANDLE`).
- **Payload:**

| Key | Type | Source |
|---|---|---|
| `autonomous_capable` | bool | `GateDetectionResult.autonomous_capable` |
| `reason` | str | `GateDetectionResult.reason`, **verbatim**, never reworded |
| `branch` | str | the branch inspected |
| `branch_source` | str | `"flag"` \| `"repo.default_branch"` \| `"fallback-main"` |
| `checked_contexts` | list[str] \| null | sorted, deduped union of `required_status_checks.contexts[]` and `required_status_checks.checks[].context`; `null` if protection is absent or unreadable |
| `tier_ceiling_check_name` | str | resolved `TIER_CEILING_CHECK_NAME` (AD-9) |
| `tier_ceiling_check_required` | bool \| null | whether `tier_ceiling_check_name` appears in `checked_contexts`; `null` when `checked_contexts` is `null` |
| `overseer_handle` | str | resolved `BOT_OVERSEER_USERNAME` |

- **`tier_ceiling_check_required` is observational only in slice 1.** It must **not** influence
  `autonomous_capable`, which comes solely from the L1 function. It exists because ADR §0 records
  "live branch-protection state — could not read" as an open verification gap and ESC-2(i) asks the
  human to confirm exactly this fact; after slice 1 that question is answered by running a command
  instead of by inference. Slice 5 is where the value starts to *matter*.
- `branch_source: "fallback-main"` must add a `not_verified[]` entry.

#### `register` — `… register --app <role> --step <N>`

- **Fetches:** nothing. Local worktree only, no token, no network.
- **`--step`** accepts any token matching `^[A-Za-z0-9._-]+$` — steps are not always integers
  (`3b` is a real step id and `check_register_completeness` takes `Union[str, int]`). A value
  outside that character set is exit 2.
- **Manifest path is derived, never supplied** (§3.4.0): `<repo_root>/contract/step-manifest.yaml`.
  The CLI computes it **once** and passes that same absolute path to *both* calls below, so the two
  can never read different files. The library's own internal default is therefore never exercised,
  which is strictly more explicit than relying on it.
- **Calls (decision):** `merge_authority.check_register_completeness(step, repo_root=…, manifest_path=…)`.
- **Calls (evidence):** `merge_authority._required_signoffs_for_step(manifest_path, step)` — the same
  private-for-evidence pattern as `_find_human_approval` (§3.4 `human-approval`), and for the same
  reason: it is the *identical* authority the library itself consults, so there is zero
  re-implementation. The CLI must **not** parse `step-manifest.yaml` itself.
- **Payload:** `step` (str), `bounce_required` (bool), `failures` (list[str], verbatim),
  `reason_category` (str \| null — closed enum `REGISTER_GAP|COMPLIANCE_FAILURE|SPEC_AMBIGUITY|OTHER`),
  `summary` (str \| null), `register_path` (str, repo-relative), `manifest_path` (str, **absolute**),
  and the three Rule B discriminators:

| Key | Type | Meaning |
|---|---|---|
| `required_signoffs` | list[str] | The roles the manifest requires for this step, verbatim from the library's own parser. |
| `required_roles_resolved` | int | `len(required_signoffs)`. |
| `gate_evaluable` | bool | `required_roles_resolved > 0`. **`false` means the gate had nothing to check** — not that it passed. |

- **The ARCH-2 condition, stated as a requirement.** When `gate_evaluable` is `false`, the record
  must carry a `not_verified[]` entry naming the absolute manifest path and the step, e.g.
  `"register gate not evaluable: no required_signoffs resolved for step <N> from <abs manifest path> (missing, malformed, or no entry for this step)"`.
  Exit stays **0**. Without this, a missing or malformed `contract/step-manifest.yaml` produces
  `bounce_required: false, failures: [], reason_category: null` — **byte-identical to a genuinely
  complete register** — which is the fail-open ARCH-2 identified.
- **The L1 behaviour is not changed here.** `check_register_completeness` keeps its signature and its
  behaviour (AD-1; §4's two-edit budget is binding). This slice *surfaces* the condition and
  *routes* the fix — see TD-F1 (§9) and the forward constraint in §3.6.
- A missing register file is an **answer** (`bounce_required: true`), not an error → exit 0.

#### `bounce-count` — `… bounce-count --app <role> --cid <cid>`

- **Fetches:** nothing over the network. **The CLI must not open, glob, or read `audit/log/**`
  itself under any circumstance** — the single call site is `merge_authority.bounce_count(...)`
  (AD-10). Any audit-trail reading in the CLI is a design violation, because CR-1 must be able to
  change the implementation by editing one function.
- **`--cid`** must match `^[A-Za-z0-9._:-]+$` and be non-empty; otherwise exit 2.
- **Calls:** `merge_authority.bounce_count(cid, repo_root=…)`.
- **Payload:** `cid`, `count` (int), `cap` (int — `merge_authority.BOUNCE_CAP`, §4.2),
  `at_cap` (bool — `count >= cap`), `cap_source` (`"merge_authority.BOUNCE_CAP"`),
  `query` (`{"event": "pr-bounced", "cid": "<cid>"}` — the declarative statement of what was
  counted, required by AD-10 so the record names its own query).

#### `human-approval` — `… human-approval --app <role> --pr <N> [--repo <o/r>]`

- **Fetches:** `github.get_pull` → `head.sha` (exit 1 if absent/empty), `github.list_pull_reviews`.
- **Calls (decision):** `merge_authority.has_human_approval(reviews, human_reviewer, head_sha)`.
- **Calls (evidence):** `merge_authority._find_human_approval(reviews, human_reviewer, head_sha)`
  for `approver` / `approved_sha` / `approved_at`.
  **Invariant, implemented as an assertion:** if `has_approval` is `true` and the evidence lookup
  returns `None` (or vice versa), that is an internal inconsistency → exit 1 with
  `error: "approval decision and evidence disagree"`. It must never be papered over.
- **Evidence filter:** `stale_approvals[]` is built by a helper that selects reviews with
  `state == "APPROVED"` and `user.login` case-insensitively equal to `human_reviewer` whose
  `commit_id != head_sha`. This helper is **evidence only**; the `has_approval` field must come
  from `has_human_approval` and from nothing else (guarded by a test, §7 T2.3).
- **Payload:** `pr`, `head_sha`, `human_reviewer`, `has_approval` (bool), `approver` (str \| null),
  `approved_sha` (str \| null), `approved_at` (str \| null),
  `stale_approvals` (list of `{commit_id, submitted_at, html_url}`), `reviews_scanned` (int).

#### `hold-directive` — `… hold-directive --app <role> --pr <N> [--repo <o/r>]`

- **Fetches:** `github.get_pull` → `head.sha`; `github.get_commit(owner, repo, head_sha)` →
  `commit.committer.date`; `github.list_issue_comments`.
- If the head commit's date cannot be read, pass `head_committed_at=None` — the library's documented
  fail-safe (every matching directive then counts) — **and** add a `not_verified[]` entry saying so.
  This is the stricter direction, so it satisfies AD-2 rule 5. It is exit 0, not exit 1.
- **Calls:** `merge_authority.detect_human_hold_directive(comments, human_reviewer, head_committed_at)`.
- **`matched_phrase`** is extracted by running `merge_authority._HOLD_DIRECTIVE_RE` — **that exact
  module-level object** — against the body of the comment the library returned, and taking
  `.group(0)`. The CLI must **not** define, copy, or approximate that pattern. If the search returns
  no match (only possible on a library/CLI divergence), emit `matched_phrase: null` plus a
  `not_verified[]` entry.
- **Payload:** `pr`, `head_sha`, `head_committed_at` (str \| null), `hold_active` (bool),
  `comment_url` (str \| null), `created_at` (str \| null), `matched_phrase` (str \| null),
  `human_reviewer`, `comments_scanned` (int).

#### `protected-surface` — `… protected-surface --app <role> --pr <N> [--repo <o/r>]`

- **Fetches:** `github.list_pull_files` → `[f["filename"] for f in files]`.
- **Calls (decision):** `merge_authority.touches_protected_surface(changed_files, repo_root)` — one
  call with the whole list. That result **is** `touches`.
- **Calls (evidence):** `touches_protected_surface([one_file], repo_root)` per file to build
  `matched_paths[]`. The library remains the only matcher; the CLI must not read
  `protected_surfaces.txt` or run `fnmatch` itself.
- **Divergence rule:** if `touches` is `true` and `matched_paths` is empty, emit `matched_paths: []`
  with a `not_verified[]` entry — **never flip `touches`**.
- **Payload:** `pr`, `touches` (bool), `matched_paths` (list[str]), `changed_file_count` (int),
  `surfaces_file` (str, the repo-relative path), `surfaces_file_present` (bool — a plain `is_file()`
  stat for diagnosis, which is not a decision).
- **Rule B (§3.4.0):** when `surfaces_file_present` is `false`, add a `not_verified[]` entry —
  `"protected-surface gate not evaluable: <abs path> absent; touches=false is the library's
  permissive default, not a clean result"`. Exit stays 0 and `touches` is **not** altered.

#### `security-surface` — `… security-surface --app <role> --pr <N> [--repo <o/r>]`

Identical in every respect to `protected-surface`, substituting
`merge_authority.touches_security_surface` (the newly-public name, §4.1) and
`scripts/framework/security_surfaces.txt`. Same per-file evidence rule, same divergence rule, same
payload keys, and the same Rule B `not_verified[]` disclosure when the surfaces file is absent.

#### `codeowners` — `… codeowners --app <role> --pr <N> [--repo <o/r>]`

- **Fetches:** `github.list_pull_files`.
- **Calls:** `check_pr_files(file_list, repo_root, bot_accounts)` from
  `scripts/oversight/codeowners.py`, loaded **by file path** via
  `importlib.util.spec_from_file_location` (TD-VF-4), mirroring
  `merge_authority._load_audit_log`. The loader must be a module-level function but the actual load
  must happen lazily inside the handler, so importing the CLI stays side-effect-free (§3.1).
- **`bot_accounts` must always be passed explicitly** as the resolved `BOT_ACCOUNTS` set (AD-9).
  Passing `None` is prohibited: `check_pr_files` would then fall back to `_bot_accounts_from_env()`,
  which is exactly the silent-default failure AF-4 describes. An empty or missing `BOT_ACCOUNTS` is
  exit 1, not an empty set.
- **Type at the boundary (iteration 2, ARCH-3b).** `MergeConfig.bot_accounts` is a `frozenset[str]`
  (§6.1) and `check_pr_files`'s parameter is typed `set[str] | None` (`codeowners.py:187-191`).
  `frozenset` is not assignable to `set` under `mypy`, which is a **blocking gate**
  (`gates/type_check.sh:89`), so the conversion is pinned here rather than discovered in the coder's
  gate run: the handler passes **`set(config.bot_accounts)`**. The config field stays `frozenset` —
  immutability is the right property for a frozen dataclass, and the copy is per-invocation and
  trivial.
- **Payload:** `pr`, `required` (bool), `matched_paths` (list[str]), `reason` (str, verbatim),
  `changed_file_count` (int), `codeowners_path` (str), `codeowners_present` (bool — plain `is_file()`
  stat), `bot_accounts` (sorted list[str] — public logins, safe to echo, and the evidence that the
  AD-9 value was used).
- **Rule B (§3.4.0):** when `codeowners_present` is `false`, add a `not_verified[]` entry —
  `"codeowners gate not evaluable: <abs path> absent; required=false is 'no CODEOWNERS file', not a
  cleared gate"`. Exit stays 0 and `required` is **not** altered. (`check_pr_files` already discloses
  this in its `reason` string; the boolean makes it machine-readable rather than prose a consumer
  must pattern-match.)

### 3.5 Boundaries the CLI must honour

- **It decides nothing.** Every boolean in every payload traces to an L1 function call. The CLI may
  compute only: derived-but-trivial fields (`at_cap = count >= cap`, `changed_file_count`), evidence
  listings built from an L1 primitive or an L1 regex object, and the envelope.
- **It writes nothing.** No file writes, no audit events, no GitHub writes, no labels, no comments.
  (Read-only-wrapper audit events are AD-10's requirement, but the audit-write seam lands with the
  mutation wrappers in slice 4; a read-only primitive that wrote events in slice 1 would create a
  second, unreviewed audit producer ahead of that design. Recorded as TD-O2, §9.)
- **It never caches.** No memoization across invocations, no on-disk state, no reading a prior
  record. Each process answers from a fresh fetch (R9.1.1's spirit, and the precondition AD-5 relies
  on in slice 4).
- **It never re-fetches a datum twice in one invocation.** Each primitive fetches each datum once.
- **It must not import `overseer_decide`, `overseer_act`, or anything from `scripts/framework/`
  other than through `merge_config`.**

### 3.6 Forward constraints on slice 2 (iteration 2 — ARCH-1.4, ARCH-2.3)

These bind slice 2's technical design. They are recorded here because slice 1 is where the
conditions become visible, and an unrecorded constraint is one slice 2 would have to rediscover.

1. **`compute_decision` resolves the repo root itself and must never accept it from an
   agent-supplied argument** — no `--repo-root` flag, no positional, no env var, on
   `overseer_decide.py` or `bootstrap/overseer_decide.sh` or any mutation wrapper. The §3.4.0 Rule A
   analysis applies unchanged one layer up, and with more force: at L2 the root selects the policy
   source for the *composed* decision, so a caller-supplied root would substitute the rule for the
   whole matrix in one flag.
2. **A `gate_evaluable: false` register result must not read as a passed gate.** Per AD-4, an
   unevaluable gate is never a passed gate. Whether slice 2 routes it to `not_verified[]` alone or
   to `next_action: ESCALATE_HUMAN` is slice 2's design call and the architect's to rule on; what is
   **not** permitted is consuming `bounce_required: false` as "clear" without inspecting
   `gate_evaluable`.
3. **The same applies to the other three Rule B discriminators** — `surfaces_file_present` and
   `codeowners_present`. A `checks[]` entry in the decision record whose underlying policy file was
   absent must carry `result: "error"` or an explicit `not_verified[]` entry, not `result: "clear"`.
4. **Slice 2 must not re-derive any primitive's answer.** It calls the same L1 functions through the
   same marshalling; it does not re-read `protected_surfaces.txt`, `CODEOWNERS`, the manifest, or the
   audit trail itself.

---

## 4. "Promote `touches_security_surface`" — the exact change (ADR AD-3 note 2)

Two edits to `scripts/automation/lib/merge_authority.py`. Nothing else in that file changes.

### 4.1 The rename (the promotion proper)

1. Rename the definition at `:414` from `_touches_security_surface` to `touches_security_surface`.
   The signature `(changed_files: list[str], repo_root: str = ".") -> bool` and the entire body are
   **unchanged**.
2. Update the single internal call site at `:623`
   (`security_relevant = security_relevant or _touches_security_surface(changed_files, repo_root)`)
   to the new name.
3. Add one sentence to the docstring, mirroring `touches_protected_surface`'s existing
   "Public (#1325)" paragraph in shape: state that it is public because it is a documented matrix
   input (`overseer.md:538-542`) and because `bootstrap/merge_authority.sh security-surface`
   reports it as evidence (#1357). Behaviour is explicitly unchanged.
4. **No alias, no shim, no re-export.** `_touches_security_surface` must not survive in any form
   (TD-D1, justified by TD-VF-1: nothing imports it). One name, one authority.
5. `DECISIONS.md:606` and `prompts/**` mention the old name in historical prose. `DECISIONS.md` is
   append-only and `prompts/**` is an immutable artifact record — **do not edit either.**

### 4.2 `BOUNCE_CAP` (TD-D2)

`bounce-count` must report `cap`, and the value `2` currently exists only as prose inside
`_bounce_comment_body` (TD-VF-5). Add a module-level constant to `merge_authority.py`:

- Name: `BOUNCE_CAP`, value `2`, with a comment citing `overseer.md` step 4a as the governing rule.
- `_bounce_comment_body`'s f-string must read the constant instead of the literal, producing
  **byte-identical** output (`"(cap: 2 before human escalation)"`). The coder must confirm that
  identity, not assume it.
- The CLI reads `merge_authority.BOUNCE_CAP`; it must not define a `2` of its own.

This is signature-preserving and adds no `argparse`/`__main__`, so it is inside AD-1's constraint.
It is the minimum that avoids coining a second authority for the cap, which is the #1135 class the
ADR explicitly forbids elsewhere (AD-9). Slice 4 will consume the same constant when
`overseer_bounce.sh` wraps `record_pr_bounce`.

---

## 5. `github.py` — four additive read helpers (TD-VF-2, TD-D3)

All four are additive; no existing function changes. Each follows the module's established shape:
`_run_gh` for the call, REST-by-id only (never Search), pagination in the same
`per_page=100` / `page=N` loop as `list_issue_comments`, `None` for 404, `GitHubError` on failure.

| New function | Endpoint | Returns |
|---|---|---|
| `get_pull(owner, repo, pr_number)` | `GET /repos/{o}/{r}/pulls/{n}` | PR object \| `None` |
| `list_pull_reviews(owner, repo, pr_number)` | `GET /repos/{o}/{r}/pulls/{n}/reviews` (paginated) | list (may be empty) |
| `list_pull_files(owner, repo, pr_number)` | `GET /repos/{o}/{r}/pulls/{n}/files` (paginated) | list (may be empty) |
| `get_commit(owner, repo, ref)` | `GET /repos/{o}/{r}/commits/{ref}` | commit object \| `None` |

Each gains a docstring naming its caller (`merge_authority_cli.<subcommand>`), matching the
convention `list_check_runs_for_ref` already uses. `list_pull_files` must paginate: a PR near the
15-file budget fits in one page, but the function is on a correctness path and a silently-truncated
file list would under-report a protected-surface match — the exact fail-open direction.

---

## 6. `merge_config.py` — AD-9 configuration and repo identity

### 6.1 `resolve_config(repo_root) -> MergeConfig`

- **Source of truth:** `<repo_root>/scripts/framework/machine-accounts.env` (AD-9, verbatim).
- **Parsing is delegated, never re-implemented (AD-9's explicit "do not coin a third env parser").**
  `merge_config.py` contains **zero** `=`-splitting, quote-stripping or `${VAR}`-expansion code. It
  loads `scripts/framework/require_tier_ceiling.py` by file path (the `audit_predicate.py`
  `_load_sibling_module` idiom; `scripts/framework` is not a package — TD-VF-4) and calls that
  module's `load_env(path)`, which already handles inline comments, quotes and `${VAR}` expansion
  and is already covered by `tests/framework/test_require_tier_ceiling.py:244-249`.
- **`load_env` calls `sys.exit(2)` when the file is missing.** That is the wrong exit code for this
  surface (exit 2 means usage error here, and a missing config is an operational failure). So
  `resolve_config` must: (a) `is_file()`-check the path first and raise `ConfigError` if absent;
  and (b) wrap the `load_env` call in `try/except SystemExit` and convert any escape to
  `ConfigError`. A bare `SystemExit` must never propagate out of the resolver.
- **Required keys — all six, all mandatory, no defaults, fail loud on any missing or empty value:**
  `OVERSEER_CEILING`, `HUMAN_REVIEWER`, `BOT_OVERSEER_USERNAME`, `BOT_WORKER_USERNAME`,
  `BOT_ACCOUNTS`, `TIER_CEILING_CHECK_NAME`. The error message names **every** missing key at once
  (not just the first) and names the file path.
- **Typed result.** `MergeConfig` is a frozen dataclass with: `overseer_ceiling: RiskTier`
  (parsed via `RiskTier.from_str`; an unrecognised value is a `ConfigError`, never a fallback to
  `LOW`), `human_reviewer: str`, `overseer_handle: str`, `worker_handle: str`,
  `bot_accounts: frozenset[str]` (whitespace-split), `tier_ceiling_check_name: str`, and
  `config_source: str` (the absolute path actually read).
  *(Iteration 2, ARCH-3b: `bot_accounts` stays `frozenset[str]`; the one consumer that needs a
  mutable `set[str]` — `check_pr_files` — converts at its own call site, per §3.4 `codeowners`. Do
  not widen the dataclass field to `set[str]` to dodge the conversion: that would make the resolved
  config mutable by any caller that touches it.)*
- **No environment-variable override of any resolved value.** `resolve_config` reads no `os.environ`
  key. This is AD-2 rule 5 applied to config.
- **Why the CLI resolves all six even when a subcommand uses two:** so a mis-configuration is caught
  by any invocation rather than only by the one subcommand that happens to need the broken key, and
  so slice 2's `config` block has one resolver with one failure mode.

### 6.2 `resolve_repo_slug(repo_root, explicit=None) -> str`

- If `--repo` was given, validate it against `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$` and use it.
- Otherwise run `git -C <repo_root> remote get-url origin` and normalise (strip
  `git@github.com:` / `https://github.com/` and a trailing `.git`), the same normalisation
  `query_issues.sh:135` performs — but **in Python**, because AD-1 says L3 does exactly three things
  and "no logic in bash". This is a deliberate, stated deviation from `query_issues.sh`'s
  bash-side resolution, taken on AD-1's instruction; it also makes the resolution unit-testable,
  which the bash version is not.
- Failure to resolve is exit 1 with a message naming the remote that was tried.

---

## 7. `bootstrap/merge_authority.sh` — the L3 wrapper

### 7.1 Shape (AF-6: copy `check_pr_reviewed.sh`'s proven shape)

```
bash bootstrap/merge_authority.sh <subcommand> --app <worker|overseer|human> [flags…]
```

The subcommand is a **positional keyword from a closed enum**, not free text. AD-2 rule 1 forbids
positional arguments *that carry content*; an enum keyword carries none, and the resulting line is a
fixed argv shape end to end. This mirrors `check_pr_reviewed.sh <pr#> <head_sha>`, the one control
in `overseer-cron-prompt.md` that actually runs (AF-6).

### 7.2 Header block (required)

A comment header in the house style (`query_issues.sh`, `check_pr_reviewed.sh`) stating: what it is
and why it exists (#1357 — the matrix was narrated, never executed); the full usage for all eight
subcommands; the exit-code table; **"stdout is exactly one JSON object; never suppress this
script's stderr"** (the #1523 lesson, verbatim in spirit from `check_pr_reviewed.sh`'s header); and
that it is read-only — it performs no GitHub write and can merge nothing. It must also state that
**the record schema is owned by `merge_authority_cli.py` alone** (iteration 2, ARCH-3a), so a future
maintainer does not add a bash-side JSON literal back.

### 7.3 Behaviour — exactly five steps, no logic beyond them

1. `set -euo pipefail`; resolve `SCRIPT_DIR` from `${BASH_SOURCE[0]}` and `REPO_ROOT="$SCRIPT_DIR/.."`.
   No absolute paths anywhere (the `portability_check.sh` gate).
2. **Extract, do not validate** (iteration 2 — ARCH-3a). Bash reads two values it needs *before*
   Python can run: the subcommand token (`$1`, if it does not begin with `-`) and the `--app` value.
   It **emits no JSON, prints no usage, and rejects nothing.** If either is absent or not in its
   enum, bash simply **skips the token mint** and proceeds to step 4, where `argparse` produces the
   single canonical exit-2 envelope. **Python is the sole author of the record schema** — adding a
   field to §3.2 must not require editing this script.

   *Why this shape:* iteration 1 had bash hand-composing the §3.2 envelope for its two pre-Python
   failures, which is a duplicate authority over a schema and drifts silently. The residual risk is
   bounded and fail-closed: if bash's extraction ever disagreed with `argparse` on a *valid* network
   invocation, the effect is a missing token, so `gh` fails and the run exits **1** — an operational
   failure, never a silently wrong answer. No validation reachable only through bash means no
   validation that `argparse` does not also perform.
3. If the subcommand was extracted, is in the network set —
   `gate`, `human-approval`, `hold-directive`, `protected-surface`, `security-surface`, `codeowners`
   — and a valid `--app` role was extracted, mint a token exactly as `query_issues.sh:140-146` does (`get_app_token.sh --app "$APP_ROLE"`
   into a `mktemp` file, `source`, `rm` immediately, `trap` for cleanup) and register an EXIT trap
   that revokes it. For `register` and `bounce-count` **no token is minted and no network call is
   made** — the record's `not_verified[]` is unaffected and nothing is revoked.
4. Invoke `python3 "$REPO_ROOT/scripts/automation/merge_authority_cli.py" "$@"` with the original
   argv, verbatim and unreordered. **Do not capture, filter, reformat or `jq` the child's stdout** —
   it passes straight through so AD-2 rule 2 holds byte-for-byte. Do not redirect the child's
   stderr.
5. Capture the child's exit code (with `set +e`/`set -e` around the call, or `|| rc=$?`), revoke the
   token via the trap, and `exit` with the child's code **unmodified**. Token revocation must write
   only to stderr on failure (`warn`), never to stdout, and must never change the exit code —
   `query_issues.sh:148-153`'s pattern.

### 7.4 What the wrapper must not do

No `jq` on the payload, no re-derivation of any field, no defaulting of any flag, no retry loop, no
`--force`/`--skip-*` passthrough, no `2>/dev/null` anywhere, no writing to any file, no `git`
mutation. It contains no knowledge of what the primitives mean.

**Added in iteration 2 (ARCH-3a):** no JSON literal of any kind, and no `printf`/`echo` to **stdout**
on any path. The script's only stdout is the child process's, passed through untouched. Its own
diagnostics go to stderr. It also performs no flag validation and emits no usage-rejection — §7.3
step 2.

---

## 8. Ship-set and portability (ADR AD-14)

**Decision (TD-D5): this surface is intended to ship to consumer installs, and the
`framework_consumer_files.txt` edit lands in slice 6, not here.** Reasons: (a) slice 6 is where
`overseer.md` starts naming these wrappers, and AF-5's bug is precisely prose naming an uninstalled
wrapper — so the ship-set edit must land with, or before, the prose, and no earlier requirement
exists; (b) shipping it in slice 1 would install a surface that no shipped instruction references,
with a config file that consumers do not have (TD-VF-3).

**Verified facts slice 6 must act on, recorded here so they are not re-derived:**

- `framework_consumer_files.txt` currently ships **no** `scripts/automation/**` file at all. The
  slice-6 additions are: `bootstrap/merge_authority.sh`, `scripts/automation/merge_authority_cli.py`,
  `scripts/automation/__init__.py`, `scripts/automation/lib/__init__.py`,
  `scripts/automation/lib/{merge_authority,github,merge_config}.py` — plus `scripts/__init__.py`,
  without which `from scripts.automation.lib…` cannot resolve in a consumer tree.
- `scripts/oversight/codeowners.py` already reaches consumers via the `scripts/oversight/` rsync
  (per that file's own header note), so it needs no new entry.
- **The import path is verified to work post-install only if all three `__init__.py` files ship.**
  They exist and are empty in this repo; none is currently listed. This is AD-14's TD-verification
  item, and the answer is: *it does not work today, and the three package markers are the fix.*
- **Blocking gap for a consumer install:** `scripts/framework/machine-accounts.env` is **not**
  shipped and is **not** generated by `hos_install.sh`; `hos_setup_partner.sh` writes the same six
  keys to `~/.config/hos/apps.env` instead (TD-VF-3). Slice 6 cannot ship this surface as
  functional until that is resolved. Routed as TD-O1 (§9) — **not** resolved here, because it is a
  config-topology question that touches `apps.env` provisioning.

---

## 9. Open items — routed, not silently absorbed

| # | Item | Disposition |
|---|---|---|
| **TD-O1** | AD-9 binds config to `scripts/framework/machine-accounts.env`, which does not exist on a consumer install (TD-VF-3). Slice 1 is unaffected (HOS repo only); slice 6's ship-set is blocked on it. | **To `architect`** with this design. My recommendation: extend `resolve_config` in slice 6 to try `<repo_root>/scripts/framework/machine-accounts.env` then the partner-provisioned `apps.env`, first-found-wins, echoing the chosen path in `config_source`. Both are operator-owned config files, so neither is a per-invocation widening input under AD-2 rule 5 — but an env-var-located path would be, so that must be confirmed, not assumed. |
| **TD-O2** | AD-10 says "every wrapper (including the read-only ones) records that it ran", but the audit-write seam is designed in slice 4. Slice 1 primitives therefore write no audit events. | **Deliberate deferral, flagged to `architect`.** Adding an audit producer in slice 1 would create a second, unreviewed write path ahead of AD-10's design. If the architect wants read-primitive audit events in slice 1, that is an additive change to §3.5 and §7.3, and the file budget absorbs it. |
| **TD-O3** | AD-13 test 4 ("record schema stability … `disposition` and `next_action` closed-enum … `not_verified[]` populated when a check errors") is written against the **decision record**, which is slice 2. | **Resolved by reading, not escalated.** Slice 1 implements test 4 against the *primitive* record: envelope completeness, `schema_version == 1`, per-subcommand payload keys present with the documented types, `reason_category` restricted to its closed enum, and `not_verified[]` populated (and the key always present) when a fetch degrades. The `disposition`/`next_action` half lands with slice 2's record. |

Nothing in this design contradicts the ADR; TD-O1 and TD-O2 are the only two points where I have
made a slice-scoped call that the architect may want to revisit.

### 9.1 Iteration-2 additions

**TD-O1, TD-O2 and TD-O3 are CLOSED by the architect's §13.1–§13.3 ruling and are not re-opened
here.** Two carried-forward actions from that ruling are recorded so they are not lost:

- **Carry-forward A (§13.1 action 1) — the `worker` files it, not this slice.** When slice 1 is
  built, open a separate issue for the consumer config-topology gap
  (`scripts/framework/machine-accounts.env` vs `~/.config/hos/apps.env`), naming
  `scripts/framework/require_tier_ceiling.py` as the **existing** broken consumer dependency (it is
  in `framework_consumer_files.txt:69` and hardcodes `ENV_FILE = Path(__file__).with_name(...)` at
  `:32`), and #1357 slice 6 as a blocked dependant; cross-reference #1542. **No slice-1 code change.**
- **Carry-forward B (§13.1 action 3) — the resolver principle, already binding.** A fixed, ordered,
  hardcoded candidate list is permitted; no env var, flag, `PATH`-like list, or cwd-relative lookup
  may select the config file. Slice 1 reads exactly one path, so nothing is required of it beyond
  continuing to echo `config_source` (§3.2). Slice 6 must additionally echo the full candidate list.

**TD-F1 (NEW, iteration 2) — routed to `architect`. AF-3 class, `register` variant.**

`check_register_completeness` returns `bounce_required=False, failures=[], reason_category=None`
when `_required_signoffs_for_step` resolves **no roles at all** — a missing, malformed, or
step-less `contract/step-manifest.yaml` — which is byte-identical to a genuinely complete register.
This is ADR §0 AF-3's class exactly: a permissive branch invisible today because nothing invokes the
function, becoming load-bearing the moment this surface makes it invocable.

- **What slice 1 does:** *surfaces* it (`gate_evaluable`, `required_roles_resolved`,
  `required_signoffs`, plus a `not_verified[]` entry — §3.4 `register`) and *constrains* slice 2
  against consuming it as a pass (§3.6.2). Per ARCH-2.4 and AD-1, **slice 1 does not change the L1
  behaviour**; §4's two-edit budget is unchanged.
- **What is routed:** whether the L1 fail-open is *fixed* (e.g. an explicit
  "manifest unreadable" outcome distinct from "nothing required") or *deliberately kept* is the
  architect's call, to be taken in slice 2's design rather than by omission here.
- **Sibling conditions, same class, bounded the same way:** `protected_surfaces.txt` absent →
  `touches: false`; `security_surfaces.txt` absent → `false`; `.github/CODEOWNERS` absent →
  `required: false`. All three are now disclosed under Rule B (§3.4.0) and constrained for slice 2
  (§3.6.3).
- **One member of the class that is deliberately NOT disclosed:** an empty `audit/log/` yields
  `bounce_count → 0` → `at_cap: false`. Zero prior bounces is a genuine, correct answer, and the
  library exposes no signal distinguishing "no trail" from "no bounces", so any discriminator the
  CLI invented would be a decision it is not entitled to make (§3.5). Recorded here so the omission
  is visible and deliberate rather than an oversight. Note that #1538 CR-1's filtered reads are the
  natural place for it.

**Iteration-2 self-check:** no item in §13.8's accepted list was modified. §3.2's two envelope
additions and §10's test additions are made **under the architect's explicit instruction**
(ARCH-1.4, ARCH-1.2, ARCH-2), which §13.8 carves out ("§10 apart from the additions ARCH-1.2 and
ARCH-2 require").

> **ARCHITECT, 2026-09-14: all three are now RULED — see §13.1 (TD-O1: deferral upheld, re-routed to
> its own issue, resolver principle bound), §13.2 (TD-O2: deferral accepted; AD-10's read-only clause
> is re-dated in the ADR, not waived) and §13.3 (TD-O3: confirmed). None of the three remains open.
> Two *new* blocking findings were raised on the flag surface — §13.5 and §13.6 — and one
> non-blocking, §13.7. The design is NOT cleared for the coder until those are addressed.**

---

## 10. Tests — AD-13 items 1–4, scoped to the primitive surface

Three new files. **No existing test file is edited**, and the 157 library tests
(`test_merge_authority_detection.py` 14, `test_bounce_gate.py` 20, `test_phase_b.py` 123) must run
unchanged and green — that is the slice gate. Logic is not re-tested here; these tests make the
categorically different claim that *the wiring exists and carries the right values* (AD-13).

### `tests/automation/test_merge_config.py` — AD-13 item 3

- **T3.1** Every one of the six keys resolves from a fixture `machine-accounts.env` under a
  `tmp_path` repo root.
- **T3.2** `overseer_ceiling` resolves to `RiskTier.HIGH` from a fixture containing
  `OVERSEER_CEILING="HIGH"` — and the test asserts explicitly that it is **not**
  `RiskTier.LOW`, the library default the ADR's AF-4 names.
- **T3.3** An absent `machine-accounts.env` raises `ConfigError` (never `SystemExit`, never a
  default) — this is the guard on `load_env`'s `sys.exit(2)`.
- **T3.4** Each required key, removed one at a time, raises `ConfigError`; the message names the
  missing key(s) and the file path. A present-but-empty value fails the same way.
- **T3.5** An unrecognised `OVERSEER_CEILING` value raises `ConfigError` rather than falling back.
- **T3.6** Inline comments, quotes and `${VAR}` expansion work — proving delegation to
  `require_tier_ceiling.load_env` rather than a second parser (assert `BOT_ACCOUNTS` expands to the
  four logins from a fixture written in the real file's style).
- **T3.7** `resolve_repo_slug` normalises both `git@github.com:o/r.git` and
  `https://github.com/o/r.git` to `o/r`, and rejects a malformed `--repo`.

### `tests/automation/test_merge_authority_cli.py` — AD-13 items 1, 2, 4

Calls `main(argv=[...], repo_root=<fixture>)` in-process with `github.py`'s read helpers patched
(the same mocking model the 157 tests already use for `github.py`) and stdout captured. No network,
no `gh`, no token. The `repo_root` keyword is the §3.4.0 injection point — it is how these tests
reach a fixture tree now that `--repo-root` no longer exists on the argv surface.

- **T1 — argv contract (AD-13 item 1).**
  - T1.1 Every documented flag of every one of the eight subcommands parses and dispatches.
  - T1.2 An unknown flag exits **2**; an unknown subcommand exits **2**.
  - T1.3 A non-numeric `--pr` exits **2** (and so does a missing `--pr` on a PR subcommand).
  - T1.4 A missing or invalid `--app` exits **2**.
  - T1.5 A malformed `--step` and a malformed/empty `--cid` exit **2**.
  - T1.6 **Every exit-2 path still prints exactly one parseable JSON object on stdout** with
    `schema_version`, `error` non-null, and `not_verified` present.
  - T1.7 **No widening input and no policy-source selector exists** (extended in iteration 2 —
    ARCH-1.2/1.3): parametrised over `--force`, `--skip-checks`, `--no-verify`, `--config`,
    `--head-sha`, **`--manifest`**, **`--repo-root`** — each exits 2 on **every** subcommand. This
    test is the executable form of AD-2 rule 5 and §3.4.0 Rule A, and must be kept in step with any
    future flag addition. The two additions are the mechanical guard that the removed flags cannot
    be quietly re-added, and that the test-only `repo_root` injection parameter is never plumbed
    from argv.
  - T1.8 **The injection point is not an argv surface** (iteration 2): `main(["register", "--app",
    "overseer", "--step", "1"], repo_root=<tmp>)` resolves against the fixture tree, while
    `main(["register", "--app", "overseer", "--step", "1", "--repo-root", str(tmp)])` exits **2**.
- **T2 — fetch→call marshalling (AD-13 item 2). This is the class AF-4 names.**
  - T2.1 `human-approval` passes the PR's real `head.sha` into the approval lookup: patch
    `merge_authority.has_human_approval`, assert the `head_sha` argument equals the fetched SHA and
    **is not `None`**.
  - T2.2 A PR object with a missing or empty `head.sha` exits **1** — never proceeds with `None`.
  - T2.3 `has_approval` follows `has_human_approval`'s return value, not the evidence filter: patch
    the library to return `False` while supplying reviews the evidence filter would match, and
    assert `has_approval is False` **and** that the disagreement is detected (exit 1 per the §3.4
    invariant).
  - T2.4 `hold-directive` passes the fetched head-commit date as `head_committed_at`; when the
    commit read fails it passes `None` **and** emits a `not_verified[]` entry (fail-safe, exit 0).
  - T2.5 `protected-surface` / `security-surface` pass the fetched `filename` list to the L1
    function, and `matched_paths[]` contains only files the L1 function matched.
  - T2.6 `codeowners` passes a non-`None` `bot_accounts` set equal to the resolved `BOT_ACCOUNTS`;
    with `BOT_ACCOUNTS` missing from the fixture config, it exits **1** rather than letting
    `check_pr_files` fall back to its env default.
  - T2.7 `gate` passes the resolved `BOT_OVERSEER_USERNAME` as `overseer_handle`, **not**
    `merge_authority.DEFAULT_OVERSEER_HANDLE`.
  - T2.8 `bounce-count` calls `merge_authority.bounce_count` exactly once with the given `cid`,
    and the CLI performs **no** filesystem read under `audit/` (assert via the patched call plus a
    patched `read_stream` that is never reached directly).
- **T4 — record schema (AD-13 item 4, scoped per TD-O3).**
  - T4.1 For each of the eight subcommands: stdout parses as exactly one JSON object; the envelope
    keys of §3.2 are all present; `schema_version == 1`; `not_verified` is present as a list even
    when empty.
  - T4.2 Each subcommand's documented payload keys are present with the documented types
    (table-driven from §3.4, so a field rename fails the test).
  - T4.3 `register`'s `reason_category` is `null` or one of the four closed-enum values.
  - T4.4 A degraded evidence fetch (patched to raise) yields exit **0**, the evidence field `null`,
    and a non-empty `not_verified[]` — never a missing key and never a changed decision.
  - T4.5 A failed **required** fetch yields exit **1** with an envelope-only record and `error`
    non-null.
  - T4.6 `gate`'s `autonomous_capable` and `reason` are the L1 result verbatim, and
    `tier_ceiling_check_required` does **not** influence `autonomous_capable` (assert both
    `true` and `false` context sets leave the decision unchanged).
  - T4.7 No subcommand ever exits 3.
  - T4.8 **Envelope identifies the tree** (iteration 2 — ARCH-1.4): every record carries `repo_root`
    as an **absolute** path equal to the resolved root, and `app_role` equal to the `--app` value.
- **T6 — the unevaluable-gate rule (iteration 2 — ARCH-2, §3.4.0 Rule B).** The tests that would have
  caught the fail-open this surface exposes.
  - T6.1 **The ARCH-2 case.** Two fixture trees: (a) a complete register satisfying every required
    role; (b) an **absent** `contract/step-manifest.yaml`. Both yield `bounce_required: false` — and
    the test asserts the records are **distinguishable**: (a) has `gate_evaluable: true`,
    `required_roles_resolved > 0`, and an empty `not_verified[]`; (b) has `gate_evaluable: false`,
    `required_roles_resolved == 0`, and a `not_verified[]` entry naming the absolute manifest path.
  - T6.2 Same assertions for a **malformed** manifest and for a manifest with **no entry for the
    requested step** — the two remaining ways `_required_signoffs_for_step` returns `[]`.
  - T6.3 `required_signoffs` equals what the library's own parser resolved (assert against
    `_required_signoffs_for_step` for the same fixture), proving the field is not re-parsed by the CLI.
  - T6.4 Both `register` calls read the **same** manifest path: patch
    `check_register_completeness` and assert its `manifest_path` argument is byte-equal to the path
    passed to the evidence call, and that both are `<repo_root>/contract/step-manifest.yaml`.
  - T6.5 `protected-surface` and `security-surface` against a tree with **no** surfaces file:
    `touches: false`, `surfaces_file_present: false`, non-empty `not_verified[]`, exit **0**, and
    `touches` unchanged by the disclosure.
  - T6.6 `codeowners` against a tree with **no** `.github/CODEOWNERS`: `required: false`,
    `codeowners_present: false`, non-empty `not_verified[]`, exit **0**.
  - T6.7 The converse, to prove the discriminators are not always-on: a tree **with** populated
    policy files yields `gate_evaluable: true` / `surfaces_file_present: true` /
    `codeowners_present: true` and an empty `not_verified[]`.
- **T5 — the promotion (§4).** `merge_authority.touches_security_surface` exists and is callable;
  `_touches_security_surface` **no longer exists** on the module (asserting the rename is real and
  no shim lingers); `merge_authority.BOUNCE_CAP == 2` and `bounce-count`'s `cap` reads it.

### `tests/automation/test_merge_authority_wrapper.py` — the L3 layer

Modelled directly on `tests/automation/test_query_issues.py`: run the real script with stubbed
`git`/`gh`/`curl`/`get_app_token.sh`/`python3` on `PATH`, capturing argv.

- **TW.1** Each of the eight subcommands invokes the CLI with argv passed through verbatim and
  unreordered.
- **TW.2** (revised in iteration 2 — ARCH-3a) An unknown subcommand and a missing/invalid `--app`
  are **forwarded to the CLI with no token minted**: assert the stubbed `get_app_token.sh` was
  **not** called, that the CLI stub received the original argv, and that the wrapper propagates the
  CLI's exit 2. The wrapper itself must emit **nothing** on stdout on these paths.
- **TW.2b** **One envelope producer** (iteration 2 — ARCH-3a): grep the wrapper for `schema_version`,
  `{"`, and `printf '{'` — all must be absent. The record schema appears in exactly one file in the
  repo, `merge_authority_cli.py`.
- **TW.3** The six network subcommands mint a token (`GET_APP_TOKEN_CALLED_WITH:--app <role>`) and
  revoke it; `register` and `bounce-count` mint **nothing**.
- **TW.4** The child's exit code is propagated unmodified for 0, 1 and 2.
- **TW.5** The child's stdout reaches the caller byte-for-byte (stub prints a known JSON blob);
  token-revocation output never appears on stdout.
- **TW.6** The token is revoked even when the child exits non-zero (trap fires).
- **TW.7** The script contains no `2>/dev/null` and no absolute path — a grep-level assertion, the
  #1523 lesson made executable at the file level.

---

## 11. File budget

| # | Path | New/Modified | Why |
|---|---|---|---|
| 1 | `scripts/automation/merge_authority_cli.py` | new | L2 primitives (§3) |
| 2 | `scripts/automation/lib/merge_config.py` | new | AD-9 config + repo identity (§6) |
| 3 | `scripts/automation/lib/merge_authority.py` | modified | promotion + `BOUNCE_CAP` (§4) — two edits only |
| 4 | `scripts/automation/lib/github.py` | modified | four additive read helpers (§5) |
| 5 | `bootstrap/merge_authority.sh` | new | L3 wrapper (§7) |
| 6 | `tests/automation/test_merge_authority_cli.py` | new | AD-13 1, 2, 4 |
| 7 | `tests/automation/test_merge_config.py` | new | AD-13 3 |
| 8 | `tests/automation/test_merge_authority_wrapper.py` | new | L3 wiring |
| 9 | `tests/automation/test_github.py` | modified | direct coverage of the four new read helpers |
| 10 | `SCRIPTS-INDEX.md` | regenerated | `scripts/framework/gen_scripts_index.sh` — a new `bootstrap/*.sh` must appear in the index |
| 11 | `.github/CODEOWNERS` | regenerated **only if it changes** | run `scripts/framework/regen_all.sh --check`; `bootstrap/**` is already a protected surface, so no change is expected — commit only if the generator produces a diff |

**11 files, comfortably inside the ≤15-file / ≤10-commit limit** (`worker-cron-prompt.md:104,137`).
A reasonable commit split is 4–6: (a) the L1 promotion + `BOUNCE_CAP`; (b) the `github.py` helpers +
their tests; (c) `merge_config.py` + its tests; (d) `merge_authority_cli.py` + its tests;
(e) `bootstrap/merge_authority.sh` + its tests; (f) generated-artifact regeneration.

**Explicitly NOT touched in this slice:** `.claude/agents/overseer.md`,
`bootstrap/overseer-cron-prompt.md`, `contract/OVERSIGHT-CONTRACT.md`,
`scripts/framework/framework_consumer_files.txt`, `DECISIONS.md`, any existing test file other than
`test_github.py`, and any file under `prompts/`. `bootstrap/**` is a protected surface, so this PR
is CODEOWNERS-human-gated regardless — which is correct for a new merge-decision surface.

---

## 12. Acceptance — the slice gate, made checkable

1. All eight subcommands run from a fixed argv line and print one JSON object:
   `bash bootstrap/merge_authority.sh <sub> --app overseer [flags]` for each of the eight.
2. `bash scripts/framework/run_tests_inner_loop.sh` is green, including the 157 pre-existing library
   tests, **unmodified**.
3. `bash scripts/oversight/run_gates.sh` is green (lint, type-check, shellcheck/`bash_check.sh`,
   `portability_check.sh`, secret scan).
4. `grep -r "_touches_security_surface" scripts/ bootstrap/ tests/` returns nothing.
5. No file under `scripts/automation/` or `bootstrap/merge_authority.sh` contains `2>/dev/null`,
   `--force`, `--skip`, or an absolute path.
6. Running `gate` against this repo answers ESC-2(i) empirically — `tier_ceiling_check_required`
   states whether `require-tier-ceiling` is a required context on the default branch, which ADR §0
   recorded as an unclosed verification gap.
7. **(iteration 2 — ARCH-1)** No policy-source selector is reachable:
   `grep -rn -- "--repo-root\|--manifest\|--config" bootstrap/merge_authority.sh scripts/automation/merge_authority_cli.py`
   returns nothing outside comments, and every one of those flags exits 2 on every subcommand
   (T1.7).
8. **(iteration 2 — ARCH-3a)** The record schema has one producer:
   `grep -n "schema_version" bootstrap/merge_authority.sh` returns nothing, and the wrapper writes
   nothing to stdout on any path except the child's passthrough (TW.2b).

---

## Human Review Required

**RISK:** MEDIUM
**CONFIDENCE:** HIGH on the primitive contracts (every L1 signature and every output field was read
in the tree, not inferred); MEDIUM on the consumer-install config topology (TD-O1), which I verified
as broken but did not resolve.
**Change classification:** `additive` — this document creates a new contract surface. It changes no
previously-approved contract, so no prior sign-off is orphaned and no re-review is triggered.
Slice 1 changes no merge disposition for any PR: every primitive is read-only, and the one behaviour
that could shift (`_dep_ceiling_check_present`) is explicitly out of scope until slice 5.

**Startup-gap check (CORE):** *should this have been settled before code was written against it?*
Yes — and the ADR already records that (§6): the missing invocation surface was an original B4/B10
design gap. This design does not introduce a *new* startup gap; it is the remediation. No sign-off
is invalidated by it.

Two items for the architect (neither blocks the coder if accepted as written):

1. **TD-O1** — AD-9's config file does not exist on a consumer install; slice 6's ship-set is
   blocked on the resolution. Recommendation in §9.
2. **TD-O2** — read-only primitives write no audit events in slice 1, deferring AD-10's
   "every wrapper records that it ran" to slice 4's audit seam.

*(Both are ruled on in §13. The "Human Review Required" block above is the design's own
self-flag and is left as authored; it is not the architect's verdict.)*

### Iteration-2 addendum to the self-flag

**RISK:** MEDIUM (unchanged). **CONFIDENCE:** raised to HIGH on the flag surface — ARCH-1 found a
real, agent-reachable fail-open (`--manifest`) that iteration 1 granted while prohibiting its
identical twin (`--config`), and the §3.4.0 classification now makes the rule explicit rather than
case-by-case, so the same error cannot recur silently.

**Change classification: `clarifying` for iteration 2 specifically.** No previously-agreed contract
was reversed: the flags removed were never implemented (slice 1 is unbuilt), the new payload fields
are additive, and the bash/Python producer split is an internal tightening. **No sign-off is
orphaned** — nothing has been approved or built against iteration 1.

**Startup-gap check on iteration 2's own changes.** *Should the §3.4.0 flag classification have been
settled in the initial technical design, before a coder wrote against it?* **Yes** — and it was
caught at the right gate, by architect review, before any code existed. That is the loop working,
not a startup gap: the affected-sign-offs analysis is empty because there is nothing downstream of
an unapproved design. TD-F1 (§9), by contrast, *is* a genuine startup-gap-class finding against the
**library** (B10), and it is routed to the architect rather than absorbed.

**One residual item for the architect in this pass:** TD-F1 (§9) — whether the L1
`check_register_completeness` fail-open is fixed or deliberately kept. Slice 1 surfaces it and
constrains slice 2 against consuming it; the disposition is the architect's, in slice 2's design.

---

## 13. Architect ruling — iteration 1 (2026-09-14)

**Verdict: REVISE. Not cleared for the coder.** The design is substantially sound — the
verification findings TD-VF-1…TD-VF-5 were independently re-checked against the tree and every one
of them holds, and the layer map, exit-code table, envelope, boundaries (§3.5) and L3 contract (§7)
are accepted as written. Two defects block clearance; both are in the flag surface and both are
instances of the exact hazard class this ADR exists to remove.

### 13.1 TD-O1 — RULED: correctly deferred. Does not block slice 1. Re-routed, and the resolver principle is bound now.

**Ruling.** TD-O1 blocks nothing in slice 1. Slice 1 is HOS-repo-only,
`scripts/framework/machine-accounts.env` exists here, and AD-9 binds that path — the design's
reading is correct.

**But the deferral target is corrected.** It does **not** belong to slice 6 as an inline decision,
and slice 6's technical design must not invent a resolution. The gap is **pre-existing and wider
than this ADR**, which the design came one step short of establishing: `scripts/framework/
require_tier_ceiling.py` **is** in `framework_consumer_files.txt` (line 69) and hardcodes
`ENV_FILE = Path(__file__).with_name("machine-accounts.env")` (`:32`) — so a *already-shipped*
consumer-facing script already depends on a file consumers never receive, while
`hos_setup_partner.sh` writes the same six keys to `~/.config/hos/apps.env`. Nothing in slice 1 or
slice 6 creates that; #1357 merely becomes its second victim. It is a consumer install/provisioning
topology question of the #1542 class.

**Actions bound by this ruling:**

1. **Open a separate issue** for the consumer config-topology gap (`machine-accounts.env` vs
   `~/.config/hos/apps.env`), naming `require_tier_ceiling.py` as the existing broken consumer
   dependency and #1357 slice 6 as a blocked dependant; cross-reference #1542. This is the
   `worker`'s to file when slice 1 is built, not a slice-1 code change.
2. **Slice 6's ship-set decision (TD-D5) is gated on that issue,** which is consistent with AD-14:
   slice 6 either ships the surface *after* the config topology is resolved, or declares it
   HOS-repo-only and says so in `overseer.md`. TD-D5's "intended to ship, edit lands in slice 6" is
   accepted as a slice-1 statement; it is not a commitment slice 6 may execute unconditionally.
3. **Resolver principle, bound now so slice 6 does not re-litigate it.** A **fixed, ordered,
   hardcoded** search path over operator-owned config locations is permitted and is **not** a
   widening input under AD-2 rule 5, because no per-invocation input selects which entry wins. **No
   environment variable, flag, `PATH`-like list, or cwd-relative lookup may select or influence the
   config file** — that would be a widening input and is prohibited outright. The record must echo
   both the path actually read (`config_source`) **and** the full candidate list considered, so a
   surprising ceiling is diagnosable from the artifact rather than from the resolver's source.
   Precedence between candidates is slice 6's to choose and justify; silence about which file won
   is not permitted.

**Startup-gap check (CORE), on my own ADR.** Should this have been settled in the initial
architecture review? **Partly yes** — AD-9 named `machine-accounts.env` without checking consumer
availability, and AD-14 flagged the *ship-set* but not *config provisioning*. That is a gap in
ADR-1357, not in this design; the design found it, which is the correct outcome. **Affected
sign-offs: none stand orphaned.** No design or code has been approved against AD-9 — slice 1 is
unbuilt and this document is unapproved — so every prior sign-off stands and nothing requires
re-review.

### 13.2 TD-O2 — RULED: deferral accepted. The premise it was routed under is corrected.

**Correction first, because it matters.** The deferral was routed to me on the understanding that
"AD-10 is about mutation wrappers, so there is nothing to defer." **That reading is wrong.** AD-10's
third paragraph says, verbatim: *"Every wrapper (including the read-only ones, and including AD-5
refusals) records that it ran."* The read-only clause is real and binding, and this design was
**right to flag a deferral rather than absorb it**. Had it accepted the "nothing to defer" framing,
a binding clause would have been silently dropped at the exact seam — evidence that a control
executed — that #1357 is about.

**Ruling: the deferral is accepted for slice 1, and the clause is re-dated, not waived.** Reasons,
which go beyond the design's own (the design's "second unreviewed write path" argument is correct
but is only the second-strongest):

- The clause's purpose is to make an **agent's claim to have run a control** verifiable. In slice 1
  no agent is instructed to call these primitives — the prose lands in slice 6 and slice 3's
  observation window wires the *decision surface*, not the primitives. An event written in slice 1
  records nothing that anyone will ever check against a claim.
- AD-10's halt-on-failure write ordering is designed in slice 4. A slice-1 producer would be a
  second, undesigned audit-write path — the duplicate-authority class AD-9 forbids by name.
- `bounce_count` linearly scans the entire committed trail (`merge_authority.py:1074-1092`) until
  #1538 CR-1's filtered reads land, and `audit/log/**` is one committed JSON file per event. A
  per-primitive event in slice 1 would measurably degrade the very function `bounce-count` wraps.
  This is a concrete cost, not a preference.

**What this does not license.** ADR-1357 AD-10 has been amended with a dated clarification binding
the new date: the read-side event lands **with the slice-4 audit seam, and no later than slice 6 —
in the same PR as the prose that names the primitives, or before it, never after.** The unit of
evidence is **one event per invocation of an agent-facing surface, not one per L1 call**
(`overseer_decide` emits a single event carrying `checks[]`; only a directly-invoked primitive emits
its own), which is what makes the volume objection dissolve rather than merely be deferred. Slice 6
must implement it or carry an explicit architect waiver; omission is not an option.

**Slice-1 consequence: none.** §3.5's "It writes nothing" stands exactly as written.

### 13.3 TD-O3 — CONFIRMED, as resolved by reading.

AD-13 item 4's `disposition`/`next_action` half is structurally unimplementable in slice 1 — those
fields belong to the decision record, which slice 2 creates. Rescoping item 4 to the primitive
record is the only coherent reading of the ADR §4 slice-1 gate, and applying the closed-enum
discipline to `reason_category` instead is a faithful analogue rather than a dilution. No escalation
was warranted; resolving it by reading was correct. T4.1–T4.7 as specified satisfy item 4 for this
slice.

### 13.4 Judgment calls independently verified — CONFIRMED (with what could still go wrong)

- **`touches_security_surface` promotion, rename with no alias (§4.1).** Re-verified: the only code
  references are the definition (`:414`) and the single call site (`:623`); `DECISIONS.md:606` and
  `prompts/…merge_authority.v2.md:27` are historical prose; **no test imports it**. So AD-13's "157
  tests untouched" genuinely survives a plain rename, and TD-D1's refusal of an alias is right —
  an alias would be a second name for one authority and would let a future caller bind to the
  private name. *What could still go wrong:* acceptance check §12.4's
  `grep -r "_touches_security_surface" scripts/ bootstrap/ tests/` is the right guard but its
  directory list excludes `docs/` and `.claude/` — correctly, since `DECISIONS.md`/`prompts/**` must
  **not** be edited (§4.1.5). Keep the grep scoped as written; do not "fix" it by widening it.
- **`_find_human_approval` and `_HOLD_DIRECTIVE_RE` stay private (§3.4).** Confirmed, and the
  asymmetry with the `touches_security_surface` promotion is principled, not inconsistent: AD-3
  note 2's promotion criterion was *"documented as a matrix input in `overseer.md:538-542`"*.
  `_find_human_approval` is not a matrix input — it is the internal helper `has_human_approval` is
  the public face of. Promoting it would create **two public approval entry points**, and the second
  one returns a truthy dict, so a future caller could treat evidence as decision. Keeping it private
  signals "not the decision surface" while the CLI consumes it for evidence only. *What could still
  go wrong:* a private helper carries no stability contract, so a refactor could change its return
  shape and the CLI would silently mis-report. The **disagreement invariant is precisely the right
  mitigation** — it converts that drift into exit 1 at runtime and T2.3 pins it at test time. It
  must not be softened to a warning in iteration 2. Same reasoning holds for running the
  module-level `_HOLD_DIRECTIVE_RE` object rather than copying the pattern: zero re-implementation,
  and a library/CLI divergence degrades to `matched_phrase: null` + `not_verified[]` rather than to
  a wrong phrase. `flake8` (the gate's linter — `gates/lint_check.sh:103`) carries no private-access
  rule, so this will not trip the gate.
- **The four `github.py` read helpers (§5).** Confirmed necessary and correctly shaped: the module's
  public surface genuinely lacks a single-PR read, a review list, a changed-files list and a commit
  read, and its own docstring makes *"all correctness-path reads MUST go through this module"*
  binding — so private helpers in the CLI would have been a contract violation. `_run_gh` already
  returns `None` on 404 (`github.py:105`) and raises `GitHubError`/`RateLimitError` otherwise, so the
  stated return contracts are the existing ones, not new ones. The pagination requirement on
  `list_pull_files` is the right call for the stated reason (a truncated file list under-reports a
  protected-surface match — the fail-open direction), and it applies equally to
  `list_pull_reviews`, which §5 already specifies. `commit.committer.date` is the correct field for
  `head_committed_at` (a rebase updates it; `author.date` would not), matching the library's
  "pushed/committed" semantics.
- **`BOUNCE_CAP` (§4.2, TD-D2).** Accepted as inside AD-1: it adds no `argparse`, no `__main__` and
  changes no signature, and AD-3's `bounce-count` row requires a `cap` field, so the alternative is
  literally coining a second `2` — the #1135 class the ADR forbids by name. The byte-identical-output
  requirement (and the verified absence of any `"cap: 2"` assertion in `test_bounce_gate.py`) is the
  right guard.

### 13.5 ARCH-1 (BLOCKING) — `--manifest` is a widening input, and `--repo-root`'s non-widening claim is false

§3.4 prohibits `--config` on the grounds that it *"would let a caller point the ceiling at a file of
their choosing, which is a widening input"* — and that reasoning is correct. **It applies verbatim
to `--manifest`, which the same section grants**, and the design does not notice.

The tree makes it worse than a symmetry argument. `_required_signoffs_for_step`
(`merge_authority.py:838-876`) returns `[]` on **any** unreadable or unparseable manifest, and
`check_register_completeness:906-910` then returns `bounce_required=False` with the comment *"even a
wholly absent register is not a gap."* So `register --step N --manifest <anything-that-does-not-parse>`
returns a **clean pass for any step**. That is a single-flag, statically-allowlistable, agent-reachable
**fail-open bypass of the register-completeness gate**, exposed on the merge-decision surface. It is
the precise hazard AD-2 rule 5 exists to forbid, and T1.7 — which parametrises `--force`,
`--skip-checks`, `--no-verify`, `--config`, `--head-sha` — would sail past it.

`--repo-root`'s claim *"It cannot widen any answer"* (§3.4) is **demonstrably false**, and the false
claim is itself part of the defect because a reviewer would rely on it: a `--repo-root` pointing at a
tree with an empty or absent `protected_surfaces.txt` yields `touches: false`
(`merge_authority.py:391-392`); an absent `security_surfaces.txt` yields `false` (`:433-434`); an
absent `.github/CODEOWNERS` yields `required: False, "no CODEOWNERS file"`
(`codeowners.py:200-202`); an empty `audit/log/` yields `count: 0` → `at_cap: false`; an absent
manifest yields `bounce_required: false`. Every one of those is the permissive direction.

**Required in iteration 2:**

1. **Classify every flag** on the primitive surface as either a **subject selector** (it identifies
   *what is being asked about* — `--pr`, `--repo`, `--branch`, `--cid`, `--step`, `--app`) or a
   **policy-source selector** (it changes *what counts as a pass* — `--config`, `--manifest`). Bind
   the rule explicitly in §3.4: **subject selectors are permitted and must be echoed in the record;
   policy-source selectors are prohibited under AD-2 rule 5.** Substituting the subject asks about a
   different thing and the record discloses it; substituting the policy source substitutes the rule.
2. **Remove `--manifest`.** Derive the manifest path from the resolved repo root. Add `--manifest`
   to T1.7's prohibited-flag parametrisation.
3. **`--repo-root` is both a subject and a policy source**, which is why it needs a bound rather than
   a claim. Either (a) remove it from the argv surface entirely — tests reach the resolver through an
   injection point not reachable from a command line, and L3 forwards nothing — or (b) keep it and
   state the operational need it serves plus what bounds the hazard. **(a) is my recommendation and
   the burden is on (b):** the overseer's checkout *is* the clone the wrapper lives in
   (`check_register_completeness`'s own docstring relies on that), so no operational need for (b) is
   currently visible. Whichever is chosen, **delete the "cannot widen any answer" sentence** and
   replace it with the analysis above.
4. **The envelope must carry the absolute repo root actually used** (§3.2 currently carries `repo`,
   `pr` and `config_source` but nothing that identifies the *tree*). Every filesystem-derived answer
   in this surface is only interpretable against the tree it was computed in, and repo-relative
   `register_path` / `surfaces_file` / `codeowners_path` conceal that. Slice 2's `compute_decision`
   must resolve the repo root itself and must never accept it from an agent-supplied argument —
   state that here as a forward constraint so slice 2 inherits it.
5. `--branch` on `gate` **passes** this test as a subject selector, because the record already echoes
   `branch` and `branch_source` and a consumer can check them against the PR's `base.ref`. Record it
   under the new classification rather than leaving it unclassified.

### 13.6 ARCH-2 (BLOCKING) — `register`'s record cannot distinguish "gate passed" from "gate had nothing to check"

Independent of ARCH-1's flags, the same library fail-open reaches the record through the **default**
path: if the PR branch's `contract/step-manifest.yaml` is missing, malformed, or simply has no entry
for `--step`, `check_register_completeness` returns `bounce_required=False, failures=[],
reason_category=None, summary=None` — **byte-identical to a genuinely complete register**. §3.4's
`register` payload as designed emits exactly those four fields plus two paths, so the record is
incapable of telling the two apart. The design anticipated the missing-*register* case ("a missing
register file is an answer, not an error") and missed the missing-*manifest* case, which is the one
that fails open.

This is **AF-3's class, reproduced**: a permissive library behaviour that is invisible today because
nothing invokes the function, and that becomes load-bearing the moment this surface makes it
invocable and slice 2 consumes it. Shipping the primitive without surfacing it would be repairing a
fail-safe and shipping a fail-open — the thing ADR §0 AF-3 explicitly warns against.

**Required in iteration 2** (contract-level; the mechanism is technical-design's to choose):

1. The `register` record must make the distinction **machine-readable** — a `bounce_required: false`
   reached because no required roles were resolved must be separable from one reached because every
   required role was satisfied. Emitting the resolved `required_signoffs` list (and/or an explicit
   `required_roles_resolved` count) is the obvious shape.
2. The no-required-roles case must add a **`not_verified[]` entry** naming which manifest was read and
   why nothing was resolved. It remains exit 0 — it is an answer, not an operational failure.
3. State as a **forward constraint on slice 2** that `compute_decision` must not treat a
   no-required-roles `register` result as a **passed** gate: per AD-4, an unevaluable gate is never a
   passed gate. Whether slice 2 routes it to `not_verified[]` alone or to `ESCALATE_HUMAN` is slice
   2's design call, but it may not silently read as clear.
4. **Do not fix the L1 behaviour in this slice.** AD-1 keeps `check_register_completeness`'s
   behaviour and signature unchanged, and §4's two-edit budget is binding. Surface the condition;
   route the fix. Record it as a new finding against ADR-1357 (AF-3 class, `register` variant) so
   slice 2's design inherits it and so a decision to change or keep the L1 fail-open is taken
   deliberately, by me, rather than by omission.

### 13.7 ARCH-3 (NON-BLOCKING) — two smaller items; adopt or rebut in iteration 2

- **The envelope has two producers.** §7.3 step 2 has bash hand-composing the §3.2 JSON envelope for
  its two pre-Python validation failures, while §3.1/§3.2 make Python the envelope's author. That is
  a duplicate authority over a schema: add a field to §3.2 and the bash copy drifts, silently. A
  cleaner shape is available — bash extracts the role, and on *any* validation failure invokes the
  CLI **without minting a token** so Python emits the single canonical exit-2 envelope (no network
  read is reached before `argparse` exits). Bash then owns only the token decision, which is the one
  thing it genuinely must decide before Python runs. If the two-producer shape is kept, say why, and
  add a test asserting the bash envelope carries the same envelope keys as the Python one.
- **`frozenset[str]` vs `set[str]`.** §6.1 types `MergeConfig.bot_accounts` as `frozenset[str]` and
  §3.4 passes it to `check_pr_files(…, bot_accounts: set[str] | None)` (`codeowners.py:187-191`).
  Runtime is fine; **mypy is a blocking gate** (`gates/type_check.sh:89`) and acceptance §12.3
  requires it green. Resolve the type at the boundary rather than discovering it in the coder's
  gate run.

### 13.8 What is accepted and must not be re-opened in iteration 2

§0 (TD-VF-1…5, all re-verified), §1, §2 and TD-D4's placement of `merge_config` in `lib/`, §3.1–§3.3,
§3.5, §4 in full, §5 in full, §6.1's delegation to `require_tier_ceiling.load_env` (confirmed: that
module has no import-time side effects beyond constants, and it **is** already in
`framework_consumer_files.txt`, so the delegation is consumer-portable) and its `SystemExit`
containment, §6.2, §7.1–§7.2 and §7.3 steps 1/3/4/5, §7.4, §8's recorded facts, §10 apart from the
additions ARCH-1.2 and ARCH-2 require, §11 and §12. One clarification so the coder is not misled:
§3.1's *"importing `merge_authority_cli` must perform no I/O"* governs code this slice authors;
importing `merge_authority` transitively executes `_load_audit_log()` at `:1071`, which is
pre-existing L1 behaviour, out of scope under AD-1, and not a violation of §3.1.

**Iteration count: 1 of 5 (CORE cap).** Return an iteration-2 revision addressing §13.5, §13.6 and
§13.7 only.

---

## 14. Architect ruling — iteration 2: ACCEPTED, cleared for the coder (2026-09-14)

**Verdict: ACCEPTED.** Iteration 2 closes ARCH-1, ARCH-2 and ARCH-3. Two binding conditions attach
(§14.5) and one residual risk is named and accepted (§14.6). The loop exits at **iteration 2 of 5**.

### 14.1 ARCH-1 — RESOLVED. The fail-open is closed.

Verified against the document, not against its change log:

- **`--manifest` is gone** — the `register` signature is now `… register --app <role> --step <N>`,
  §3.4.0's table classifies it prohibited with the tree-level reason, the path is **derived**
  (`<repo_root>/contract/step-manifest.yaml`), T1.7 parametrises it as an exit-2 flag, and acceptance
  check 7 greps for it. The bypass I found — `register --step N --manifest <nonparsing>` returning a
  clean pass for any step via `_required_signoffs_for_step`'s `[]` — is **no longer reachable**,
  because the only input that could reach the manifest path is gone and the derivation is
  file-relative, not caller-relative.
- **`--repo-root` is gone from argv** (option (a), as recommended) — removed from all five subcommand
  signatures that carried it in iteration 1, from the global-flag list, and pinned by T1.7 + T1.8.
  The false *"cannot widen any answer"* sentence is deleted and replaced with the five-way permissive
  analysis. Option (a) was the stronger choice and was taken without argument, which is the right
  instinct on this surface.
- **Rule A (§3.4.0) is the right generalisation**, and it is better than what I asked for: I asked
  for a classification, and the design added the reason *why policy-source selectors have no
  auditable form* — "a record that faithfully echoing the substituted policy file still reports a
  pass computed under a rule the caller chose." That sentence is the durable version of the rule and
  will survive into slice 2.
- **Envelope `repo_root` + `app_role`** (§3.2) — present, absolute, `app_role` justified on read
  visibility, and correctly **not** duplicating subject selectors the payloads already echo.

**T1.8's claim independently verified — it holds.** `main(argv=None, *, repo_root=None)` is
keyword-only; `argparse` never defines `--repo-root`; the `__main__` block is `sys.exit(main())` and
populates nothing from `sys.argv`; and L3 forwards `"$@"` verbatim, so a command-line `--repo-root`
arrives in `argv` and dies at `argparse` with exit 2. There is **no path** from a command line to the
parameter: a keyword-only parameter cannot be reached positionally, and nothing splats a dict into
the call. The pairing of T1.7 (the flag is rejected) with T1.8 (the parameter still works in-process)
is exactly the right two-sided pin — one alone would pass while the other silently regressed.

### 14.2 ARCH-2 — RESOLVED, and correctly generalised beyond what I required.

- `register` gains `required_signoffs` / `required_roles_resolved` / `gate_evaluable`, with
  `gate_evaluable: false` forcing a `not_verified[]` entry naming the absolute manifest path, at
  exit 0. The two byte-identical outcomes I found are now machine-distinguishable, and T6.1/T6.2
  test **both** trees side by side, which is the only test shape that actually proves
  distinguishability.
- Using `merge_authority._required_signoffs_for_step` for the evidence field is the correct choice
  and is consistent with the `_find_human_approval` precedent I confirmed in §13.4 — identical
  authority, zero re-implementation. **T6.4 is a better idea than anything I asked for:** asserting
  that the decision call and the evidence call receive a byte-equal manifest path forecloses the
  decision/evidence divergence that the `human-approval` invariant has to catch at runtime.
- **Rule B's extension to `protected_surfaces.txt` / `security_surfaces.txt` / CODEOWNERS-absent is
  right and I endorse it.** All three are the same AF-3 shape, all three are on the gates #1325 was
  about, and the cost is one boolean and one string each. Extending a rule the architect raised for
  one case to its whole class, with the class named, is the behaviour I want from this role.
- **§3.6's forward constraints are accepted and bind slice 2's design.** §3.6.1 is stronger than I
  asked — it extends the prohibition to the mutation wrappers with the correct reasoning (at L2 the
  root selects the policy source for the *composed* decision, so one flag would substitute the whole
  matrix's rule). §3.6.2–§3.6.4 stand as written.

**TD-F1's scope boundary is correct, not a dodge.** §13.6.4 instructed exactly this: *"Do not fix the
L1 behaviour in this slice… Surface the condition; route the fix."* AD-1 keeps L1 signatures and
behaviour unchanged and §4's two-edit budget is binding, so fixing `check_register_completeness` here
would have been the violation. The safety-relevant half — making the condition impossible to consume
silently as a pass — **is** delivered in slice 1, which is what matters; only the disposition is
deferred. **Noted for slice 2, so it is not discovered late:** a fix that turns a currently-passing
condition into `bounce_required: true` changes which PRs get bounced, which is a throughput and
failure-mode change with a product-visible effect. If slice 2's design proposes that direction, it
routes through the CORE product-boundary checkpoint before I bind it. I am not pre-judging it here.

**The `bounce-count` exclusion — reasoning verified, and it holds.** I checked whether a
discriminator was available and it is not: `bounce_count` returns a bare `int`, so the CLI cannot
learn how many events were scanned without reading `audit/log/**` itself, which §3.5 and AD-10
forbid (single call site, so #1538 CR-1 can swap the implementation by editing one function).
Inventing a discriminator would have required either violating that binding or changing an L1
signature (AD-1). Declining, and **recording the omission visibly in TD-F1 with #1538 CR-1 named as
its home**, is the correct disposition. I add the failure mode to the record in §14.6 so the risk is
carried explicitly rather than implied.

### 14.3 ARCH-3 — RESOLVED. Both items accepted.

- **Single envelope producer.** §7.3 step 2's "extract, do not validate" is the right shape and the
  fail-closed argument is sound as far as it goes: a bash/`argparse` disagreement costs a token, not
  a wrong answer. §7.2's header requirement and §7.4's "no JSON literal, no stdout `printf`/`echo`"
  close the door on a future maintainer re-adding a bash-side literal, and TW.2b enforces it by grep.
  One gap in the safety argument is real and is closed by ARCH-4 (§14.5).
- **mypy boundary.** Keeping `MergeConfig.bot_accounts` as `frozenset[str]` and converting with
  `set(...)` at the `check_pr_files` call site is the correct direction — the reason given
  (widening the dataclass field would make resolved config mutable by any caller) is the right one,
  and it is the config object AD-9 requires to be authoritative. Accepted.

### 14.4 Do-not-reopen discipline — VERIFIED against the text, not the claim

The document is untracked, so no `git diff` exists; I compared against iteration 1, which I read in
full. §0 (TD-VF-1…5), §1, §2, §3.5, §4.1, §4.2, §5, §6.2, §7.1, §8, §11, §12.1–§12.6 and §13 are
byte-unchanged, as claimed. The four judgment calls I confirmed in §13.4 are **untouched**: the
rename-with-no-alias (§4.1, including the do-not-edit rule for `DECISIONS.md`/`prompts/**`), the
`_find_human_approval` evidence pattern with its disagreement invariant, the `_HOLD_DIRECTIVE_RE`
module-object extraction, and the four `github.py` helpers. `BOUNCE_CAP` is likewise unchanged.
§9's TD-O1/O2/O3 rows were left **verbatim** with §9.1 recording their closure rather than being
rewritten — that is the correct discipline for a routed item that a ruling has closed, and it keeps
the history readable. The three disclosed touches to accepted text (§3.2, §7.3 step 3, §7.2/§7.4) are
each within an explicit instruction of mine and reverse nothing; all three are in bounds.

**Three clerical contradictions the "byte-unchanged" discipline left behind, which I corrected
myself rather than spend an iteration on** (all are inconsistencies *created by* iteration 2's
changes, not design decisions):

1. §3.1's `main` signature omitted the keyword-only `repo_root` that §3.4.0 introduces — corrected in
   place, with the correction marked.
2. §3.3 still said the bash layer emits the exit-2 envelope, which §7.3 step 2 now forbids. A coder
   reading §3.3 first would have re-created the exact duplicate-producer defect ARCH-3a removed —
   deleted, with the correction marked.
3. The iteration-2 change log named a `flags_echo` envelope field that §3.2 does not define (the real
   additions are `repo_root` and `app_role`) — corrected.

Nothing else in the document is altered by me.

### 14.5 Binding conditions on this clearance — ARCH-4 and ARCH-5

Both are requirements on the **coder**, not a further design iteration. I considered returning a
third iteration for them and judged it disproportionate: each is one mechanical application of a rule
this design already established (§3.4.0 Rule B; §7.3's single-producer shape), and neither changes a
contract. `code-reviewer` must verify both.

**ARCH-4 — bash's `--app` extraction must accept `--app=<value>` as well as `--app <value>`.**
§7.3 step 2's safety argument is *"if bash's extraction ever disagreed with `argparse` on a valid
network invocation, the effect is a missing token, so `gh` fails and the run exits 1."* That argument
holds only where no ambient credential exists — an environment assumption, not a design guarantee.
And there is a concrete, ordinary way to make the two disagree: `--app=overseer` is valid to
`argparse` but is missed by a naive `--app <value>` pair-scan in bash, so the run proceeds to a real
fetch **with no minted token**. Requirement: the extractor handles both forms, and
`tests/automation/test_merge_authority_wrapper.py` adds a case asserting
`merge_authority.sh gate --app=overseer` mints a token for role `overseer` exactly as the
space-separated form does. This restores §7.3 step 2's stated guarantee instead of leaving it
conditional on the environment.

**ARCH-5 — an empty changed-files list is an unevaluable gate, not a clean one.** On
`protected-surface`, `security-surface` and `codeowners`, `changed_file_count == 0` must add a
`not_verified[]` entry under §3.4.0 Rule B and must **not** alter `touches` / `required`. Reason: a
real PR always changes at least one file, so an empty list means **the read did not see the PR**, not
that the PR is clean. It is reachable — those three subcommands fetch only `list_pull_files`, with no
`get_pull` ahead of them, and §5 specifies a 404 as `None` → `[]`, so an identity that cannot see the
PR, a deleted/renumbered PR, or a transient empty response all yield `touches: false`,
`changed_file_count: 0`, **exit 0** — a silent fail-open on precisely the #1325 gates. This is the
same shape as the four conditions Rule B already covers, and the design's own machinery handles it.
Add a T6.8 asserting the disclosure fires on an empty file list for all three subcommands and that
the decision field is unchanged.

### 14.6 Residual risk — named and accepted, not closed

**A lost or absent `audit/log/**` makes the bounce cap unreachable.** `bounce_count` returns `0` both
for "no prior bounces" and for "no trail", so `at_cap` stays `false` and the escalation-to-human at
the cap never fires — the failure mode is unbounded autonomous bouncing with no human ever brought
in, rather than anything reaching merge. I accept this for slice 1 for the reason §14.2 gives: every
available discriminator would require breaking AD-10's single-call-site binding or changing an L1
signature under AD-1. It is recorded in TD-F1 and belongs to **#1538 CR-1**, whose filtered-read
primitive can return a scanned-event count alongside the match count at no extra cost. Slice 4, which
owns `overseer_bounce.sh`, must not assume the cap is reliable until CR-1 lands.

### 14.7 Status

**ACCEPTED. Cleared for the coder,** subject to ARCH-4 and ARCH-5 (§14.5), with §14.6 carried as a
named residual. The design loop closes at **iteration 2 of 5** — well inside the CORE cap and with no
escalation required. This document, plus `docs/v0.7.0/ADR-1357-merge-authority-execution.md` (AD-10
as amended 2026-09-14), is the binding input to implementation of ADR §4 slice 1.

**Affected sign-offs:** none. Nothing has been built or approved against any earlier revision of this
design, so no prior sign-off is orphaned and no re-review is triggered.
